"""
TastyMechanics — Pure Math / Analytics Engine
===============================================
All computation that transforms parsed DataFrames into P/L figures,
campaign objects, and trade records. No Streamlit dependency — fully
importable and testable without a running server.

Public API
----------
  _iter_fifo_sells(equity_rows)                  → yields (date, proceeds, cost)
  calculate_windowed_equity_pnl(df, start, end)  → float
  calculate_daily_realized_pnl(df, start_date)   → DataFrame
  build_campaigns(df, ticker, use_lifetime)       → list[Campaign]
  effective_basis(campaign)                       → float
  realized_pnl(campaign)                          → float
  pure_options_pnl(df, ticker, campaigns)         → float
  build_closed_trades(df, campaign_windows)       → DataFrame
  build_option_chains(ticker_opts)                → list
  calc_dte(row, reference_date)                   → str
  compute_app_data(parsed, use_lifetime)          → AppData

Internal helpers (also importable and testable)
  _uf_find(parent, x)                            → str   (Union-Find with path compression)
  _uf_union(parent, a, b)                        → None  (Union-Find merge)
  _group_symbols_by_order(sym_open_orders)       → dict  (groups multi-leg trade symbols)
"""

from __future__ import annotations

from collections import deque, defaultdict
from typing import Any, Iterator, Optional

import pandas as pd

from models import Campaign, AppData, ParsedData
from config import (
    OPT_TYPES, TRADE_TYPES, MONEY_TYPES,
    SUB_SELL_OPEN, SUB_ASSIGNMENT, SUB_DIVIDEND,
    INCOME_SUB_TYPES,
    PAT_CLOSE, PAT_EXPIR, PAT_ASSIGN,
    WHEEL_MIN_SHARES,
    ROLL_CHAIN_GAP_DAYS,
    KNOWN_INDEXES,
    SPLIT_DSC_PATTERNS,
    FIFO_EPSILON, FIFO_ROUND,
    ANN_RETURN_CAP,
)
from ingestion import equity_mask, option_mask, is_share_row, is_option_row


# ── FIFO CORE ─────────────────────────────────────────────────────────────────
def _iter_fifo_sells(equity_rows: pd.DataFrame) -> Iterator[tuple[pd.Timestamp, float, float]]:
    """
    Shared FIFO engine — single source of truth for equity cost-basis logic.

    Handles both long and short equity positions:

      Long side  (long_queues):
        BUY  → push (qty, cost_per_share) onto long_queue
        SELL → if long_queue has shares, pop FIFO lots and yield realised P/L
               (proceeds - cost_basis).  This is a normal long sale.

      Short side  (short_queues):
        SELL → if long_queue is empty, this is a short-sell: push (qty, proceeds_per_share)
               onto short_queue.  Nothing yielded yet — P/L realises on the cover.
        BUY  → if short_queue has shares, pop FIFO lots and yield realised P/L
               (short_proceeds - cover_cost).  Positive when you shorted higher than you covered.

    Routing rule: a SELL routes to the long side first; only if the long queue is empty
    (no long inventory to close) does it open a short.  A BUY routes to the short side
    first; only if no short inventory exists does it open a long.

    Yields (date, proceeds, cost_basis) — callers apply their own window/bucketing.

    Examples
    --------
    All examples use Net_Qty_Row > 0 for buys, < 0 for sells.
    Total is negative on buys (cash out), positive on sells (cash in).

    1. Simple long — buy 100 shares @ $10, sell @ $15:

       BUY  100  Total=-1000  →  long_queue: [(100, 10.00)]       nothing yielded
       SELL 100  Total=+1500  →  long_queue: []
                                  yields (date, proceeds=1500.00, cost=1000.00)
                                  P/L = +$500.00

    2. Two lots, partial FIFO sell — buy 100@$10, buy 100@$12, sell 150@$15:

       BUY  100  Total=-1000  →  long_queue: [(100, 10.00)]
       BUY  100  Total=-1200  →  long_queue: [(100, 10.00), (100, 12.00)]
       SELL 150  Total=+2250  →  consumes first lot in full (100 @ $10)
                                  consumes 50 shares from second lot (50 @ $12)
                                  long_queue: [(50, 12.00)]
                                  yields (date, proceeds=2250.00, cost=1600.00)
                                  P/L = +$650.00

       Note: a single yield covers the whole sell even when multiple lots
       are consumed — proceeds and cost are summed across lots internally.

    3. Short sell then cover — short 100 @ $15, cover @ $10:

       SELL 100  Total=+1500  →  long_queue empty → opens short
                                  short_queue: [(100, 15.00)]  nothing yielded
       BUY  100  Total=-1000  →  covers short lot
                                  short_queue: []
                                  yields (date, proceeds=1500.00, cost=1000.00)
                                  P/L = +$500.00  (shorted high, covered low)
    """
    long_queues  = {}   # ticker -> deque of (qty, cost_per_share)   [long lots]
    short_queues = {}   # ticker -> deque of (qty, proceeds_per_share) [short lots]

    for row in equity_rows.itertuples(index=False):
        ticker = row.Ticker
        if ticker not in long_queues:
            long_queues[ticker]  = deque()
            short_queues[ticker] = deque()

        qty   = row.Net_Qty_Row
        total = row.Total                        # signed: negative on buys, positive on sells
        lq    = long_queues[ticker]
        sq    = short_queues[ticker]

        if qty > 0:
            # ── BUY row ───────────────────────────────────────────────────────
            # Cover shorts first (FIFO); any residual qty opens/adds to a long.
            remaining = qty
            # Guard: qty > 0 is guaranteed by the branch condition, but a row
            # with qty=0 and total!=0 (e.g. a misclassified fee) would cause
            # ZeroDivisionError without this check.
            pps = abs(total) / qty if qty != 0 else 0.0  # cost per share on this buy

            while remaining > FIFO_EPSILON and sq:
                s_qty, s_pps = sq[0]
                use      = min(remaining, s_qty)
                # P/L on covering a short = what we shorted it for minus cover cost
                short_proceeds = use * s_pps
                cover_cost     = use * pps
                yield row.Date, short_proceeds, cover_cost
                remaining = round(remaining - use, FIFO_ROUND)
                leftover  = round(s_qty - use, FIFO_ROUND)
                if leftover < FIFO_EPSILON:
                    sq.popleft()
                else:
                    sq[0] = (leftover, s_pps)

            if remaining > FIFO_EPSILON:
                # Residual qty is a new long position (or adding to existing)
                lq.append((remaining, pps))

        elif qty < 0:
            # ── SELL row ──────────────────────────────────────────────────────
            # Close longs first (FIFO); any residual qty opens/adds to a short.
            remaining       = abs(qty)
            pps             = abs(total) / remaining   # proceeds per share — remaining == abs(qty) > 0 always
            sale_cost_basis = 0.0

            while remaining > FIFO_EPSILON and lq:
                b_qty, b_cost = lq[0]
                use = min(remaining, b_qty)
                sale_cost_basis += use * b_cost
                remaining = round(remaining - use, FIFO_ROUND)
                leftover  = round(b_qty - use, FIFO_ROUND)
                if leftover < FIFO_EPSILON:
                    lq.popleft()
                else:
                    lq[0] = (leftover, b_cost)

            if sale_cost_basis > 0 or remaining < abs(qty) - FIFO_EPSILON:
                # We closed at least some long lots — yield that realised P/L
                long_qty_closed = abs(qty) - remaining
                yield row.Date, long_qty_closed * pps, sale_cost_basis

            if remaining > FIFO_EPSILON:
                # Residual qty is a new short position (or adding to existing)
                sq.append((remaining, pps))


# ── TRUE FIFO EQUITY P/L ───────────────────────────────────────────────────────
def calculate_windowed_equity_pnl(df_full: pd.DataFrame, start_date: pd.Timestamp, end_date: Optional[pd.Timestamp] = None) -> float:
    """
    Calculates net equity P/L for sales on or after start_date and (optionally)
    before end_date. Cached on (df, start_date, end_date) — a window change
    re-runs once then hits cache on every subsequent interaction. The prior-period
    call is also independently cached.
    end_date is used for prior-period comparisons to prevent double-counting.
    """
    equity_rows = df_full[
        equity_mask(df_full['Instrument Type'])
    ].sort_values('Date')
    _eq_pnl = 0.0
    for date, proceeds, cost_basis in _iter_fifo_sells(equity_rows):
        in_window = date >= start_date
        if end_date is not None:
            in_window = in_window and date < end_date
        if in_window:
            _eq_pnl += (proceeds - cost_basis)
    return _eq_pnl


# ── DAILY REALIZED P/L (for period charts) ────────────────────────────────────
def calculate_daily_realized_pnl(df_full: pd.DataFrame, start_date: pd.Timestamp) -> pd.DataFrame:
    """
    Returns a DataFrame with columns [Date, PnL] representing realized P/L
    by settlement date across the full portfolio:
      - Options: full cash flow on the day (already realized at close/expiry)
      - Equity sells: net gain/loss vs FIFO cost basis on the sale date
      - Dividends + interest: cash received on the day
    Share purchases are excluded — they are capital deployment, not P/L.
    Only rows with Date >= start_date are returned, but ALL equity history
    is processed so FIFO cost basis is always correct.
    """
    equity_rows = df_full[
        equity_mask(df_full['Instrument Type'])
    ].sort_values('Date')
    records = [
        {'Date': date, 'PnL': proceeds - cost_basis}
        for date, proceeds, cost_basis in _iter_fifo_sells(equity_rows)
        if date >= start_date
    ]

    # Options flows — vectorized: just select [Date, Total] columns directly
    opt_rows = df_full[
        df_full['Instrument Type'].isin(OPT_TYPES) &
        df_full['Type'].isin(TRADE_TYPES) &
        (df_full['Date'] >= start_date)
    ][['Date', 'Total']].rename(columns={'Total': 'PnL'})

    # Dividends + interest — vectorized
    income_rows = df_full[
        df_full['Sub Type'].isin(INCOME_SUB_TYPES) &
        (df_full['Date'] >= start_date)
    ][['Date', 'Total']].rename(columns={'Total': 'PnL'})

    if not records and opt_rows.empty and income_rows.empty:
        return pd.DataFrame(columns=['Date', 'PnL'])

    daily = pd.concat(
        [pd.DataFrame(records)] + ([opt_rows] if not opt_rows.empty else [])
                                 + ([income_rows] if not income_rows.empty else []),
        ignore_index=True
    )
    daily['Date'] = pd.to_datetime(daily['Date'])
    return daily.groupby('Date')['PnL'].sum().reset_index()


def build_campaigns(df: pd.DataFrame, ticker: str, use_lifetime: bool = False) -> list[Campaign]:
    """
    Build a list of Campaign objects for a ticker that has been wheeled.
    Each Campaign covers one continuous share-holding period.

    use_lifetime=True: collapses all history into a single campaign (no resets).
    use_lifetime=False: each buy-in starts a new campaign; exits close it.

    Returns a list of Campaign objects (may be empty).
    """
    t = df[df['Ticker'] == ticker].copy()
    t['Sort_Inst'] = t['Instrument Type'].apply(
        lambda x: 0 if 'Equity' in str(x) and 'Option' not in str(x) else 1
    )
    t = t.sort_values(['Date', 'Sort_Inst'])
    # Rename spaced columns so itertuples attribute access works cleanly
    t = t.rename(columns={
        'Instrument Type': 'Instrument_Type',
        'Sub Type':        'Sub_Type',
    })

    if use_lifetime:
        net_shares = t[t['Instrument_Type'].apply(is_share_row)]['Net_Qty_Row'].sum()
        if net_shares >= WHEEL_MIN_SHARES:
            premiums   = 0.0
            dividends  = 0.0
            events     = []
            start_date = t['Date'].iloc[0]
            for row in t.itertuples(index=False):
                inst     = str(row.Instrument_Type)
                total    = row.Total
                sub_type = str(row.Sub_Type)
                if is_share_row(inst):
                    if row.Net_Qty_Row > 0:
                        events.append({'date': row.Date, 'type': 'Entry/Add',
                            'detail': f'Bought {row.Net_Qty_Row} shares', 'cash': total})
                    else:
                        events.append({'date': row.Date, 'type': 'Exit',
                            'detail': f'Sold {abs(row.Net_Qty_Row)} shares', 'cash': total})
                elif is_option_row(inst):
                    if row.Date >= start_date:
                        premiums += total
                        events.append({'date': row.Date, 'type': sub_type,
                            'detail': str(row.Description)[:60], 'cash': total})
                elif sub_type == SUB_DIVIDEND:
                    dividends += total
                    events.append({'date': row.Date, 'type': SUB_DIVIDEND,
                        'detail': SUB_DIVIDEND, 'cash': total})
            net_lifetime_cash = t[t['Type'].isin(MONEY_TYPES)]['Total'].sum()
            total_cost = abs(net_lifetime_cash) if net_lifetime_cash < 0 else 0.0
            return [Campaign(
                ticker=ticker, total_shares=net_shares,
                total_cost=total_cost,
                blended_basis=total_cost / net_shares if net_shares > 0 else 0.0,
                premiums=premiums, dividends=dividends,
                exit_proceeds=0.0, start_date=start_date, end_date=None,
                status='open', events=events,
            )]

    campaigns: list               = []
    current:   Optional[Campaign] = None
    running_shares                = 0.0

    for row in t.itertuples(index=False):
        inst     = str(row.Instrument_Type)
        qty      = row.Net_Qty_Row
        total    = row.Total
        sub_type = str(row.Sub_Type)
        dsc_up   = str(row.Description).upper()

        # ── Stock split: rescale campaign quantities and basis ─────────────
        # Split rows have Net_Qty_Row == 0 (set in get_signed_qty).
        # We detect the addition row (no REMOVAL keyword) to compute the ratio
        # and rescale the live campaign. total_cost is unchanged — the same
        # cash was invested, there are just more shares now.
        #
        # Ratio source: split_qty (TastyTrade's addition row) / running_shares
        # (our tracked post-previous-split count). This is correct because
        # apply_split_adjustments() has already rescaled all pre-split lot
        # quantities in the DataFrame, so running_shares always reflects the
        # current share count immediately before this split event. On a second
        # split the same logic applies: running_shares is the post-first-split
        # count, and split_qty is the post-second-split count.
        #
        # Edge case: if TastyTrade's addition row quantity doesn't exactly match
        # running_shares × ratio (e.g. fractional rounding on a reverse split),
        # running_shares is set directly to split_qty — TastyTrade's figure is
        # authoritative; our tracked count defers to theirs.
        if (is_share_row(inst) and qty == 0 and total == 0
                and any(p in dsc_up for p in SPLIT_DSC_PATTERNS)
                and 'REMOVAL' not in dsc_up
                and current is not None):
            split_qty = row.Quantity   # raw CSV quantity (always positive)
            if running_shares > 0.001 and split_qty > 0:
                ratio = split_qty / running_shares
                running_shares        = split_qty
                current.total_shares  = split_qty
                current.blended_basis = current.total_cost / split_qty
                current.events.append({
                    'date':   row.Date,
                    'type':   'Stock Split',
                    'detail': '%.6gx split: %.0f → %.0f shares @ $%.4f/sh basis' % (
                        ratio, split_qty / ratio, split_qty, current.blended_basis),
                    'cash':   0.0,
                })
            continue

        # ── Share buy / add ────────────────────────────────────────────────
        if is_share_row(inst) and qty >= WHEEL_MIN_SHARES:
            pps = abs(total) / qty
            if running_shares < 0.001:
                # New campaign entry — check if arrival was via put assignment
                assignment_premium, assignment_events = _find_assignment_premium(t, row)
                entry_label = 'Bought %.0f @ $%.2f/sh%s' % (
                    qty, pps, ' (Assigned)' if assignment_events else '')
                current = Campaign(
                    ticker=ticker, total_shares=qty, total_cost=abs(total),
                    blended_basis=pps, premiums=assignment_premium, dividends=0.0,
                    exit_proceeds=0.0, start_date=row.Date, end_date=None,
                    status='open',
                    events=assignment_events + [
                        {'date': row.Date, 'type': 'Entry', 'detail': entry_label, 'cash': total}
                    ],
                )
                running_shares = qty
            else:
                # Adding to an existing position — recalculate blended basis
                new_shares        = running_shares + qty
                new_cost          = current.total_cost + abs(total)
                new_basis         = new_cost / new_shares
                current.total_shares  = new_shares
                current.total_cost    = new_cost
                current.blended_basis = new_basis
                running_shares        = new_shares
                current.events.append({'date': row.Date, 'type': 'Add',
                    'detail': 'Added %.0f @ $%.2f → blended $%.2f/sh' % (qty, pps, new_basis),
                    'cash': total})

        # ── Share sale / partial exit ──────────────────────────────────────
        elif is_share_row(inst) and qty < 0:
            if current and running_shares > 0.001:
                current.exit_proceeds += total
                running_shares        += qty
                pps = abs(total) / abs(qty) if qty != 0 else 0
                current.events.append({'date': row.Date, 'type': 'Exit',
                    'detail': 'Sold %.0f @ $%.2f/sh' % (abs(qty), pps), 'cash': total})
                if running_shares < 0.001:
                    current.end_date = row.Date
                    current.status   = 'closed'
                    campaigns.append(current)
                    current        = None
                    running_shares = 0.0

        # ── Option premium ─────────────────────────────────────────────────
        elif is_option_row(inst) and current is not None:
            if row.Date >= current.start_date:
                current.premiums += total
                current.events.append({'date': row.Date, 'type': sub_type,
                    'detail': str(row.Description)[:60], 'cash': total})

        # ── Dividend ───────────────────────────────────────────────────────
        elif sub_type == SUB_DIVIDEND and current is not None:
            current.dividends += total
            current.events.append({'date': row.Date, 'type': SUB_DIVIDEND,
                'detail': 'Dividend received', 'cash': total})

    if current is not None:
        campaigns.append(current)
    return campaigns


def _find_assignment_premium(t: pd.DataFrame, row: Any) -> tuple[float, list]:
    """
    Look for a put assignment at the same timestamp as a share delivery row.
    If found, trace back to the originating STO and record it in the campaign
    event log so the timeline shows "arrived via assignment".

    Returns (0.0, list_of_event_dicts).

    Why premium=0.0: the STO that caused assignment was traded *before* the
    campaign start date, so pure_options_pnl() already counts it as outside-
    window P/L. Adding it to c.premiums here would double-count it in
    total_realized_pnl. The event is retained for display only.
    """
    events  = []
    same_dt = t[t['Date'] == row.Date]
    assigned_syms = same_dt[
        same_dt['Sub_Type'].str.lower() == SUB_ASSIGNMENT
    ]['Symbol'].dropna().unique()
    for sym in assigned_syms:
        sto = t[
            (t['Symbol'] == sym) &
            (t['Sub_Type'].str.lower() == SUB_SELL_OPEN) &
            (t['Date'] < row.Date)
        ]
        for s in sto.itertuples(index=False):
            events.append({
                'date': s.Date, 'type': 'Assignment Put (STO)',
                'detail': str(s.Description)[:60], 'cash': s.Total,
            })
    return 0.0, events

def effective_basis(c: Campaign, use_lifetime: bool = False) -> float:
    """Cost per share after netting premiums and dividends against total_cost."""
    if use_lifetime:
        return c.blended_basis
    net = c.total_cost - c.premiums - c.dividends
    return net / c.total_shares if c.total_shares > 0 else 0.0

def realized_pnl(c: Campaign, use_lifetime: bool = False) -> float:
    """Total realised profit/loss for a campaign."""
    if use_lifetime:
        return c.premiums + c.dividends
    if c.status == 'closed':
        return c.exit_proceeds + c.premiums + c.dividends - c.total_cost
    return c.premiums + c.dividends

def pure_options_pnl(df: pd.DataFrame, ticker: str, campaigns: list[Campaign]) -> float:
    """
    Options P/L for a ticker that falls *outside* all campaign windows.

    Window boundary convention
    --------------------------
    Start is always inclusive (>= start_date).
    End depends on whether the campaign is closed or still open:

      Closed campaign (c.end_date is set):
        End is *exclusive* (< end_date).  The end_date is the share-sale date.
        An option that closes on that exact date is after the campaign has ended
        and must not be counted as campaign premium — it belongs in the
        outside-window bucket.  Using <= would double-count it.

      Open campaign (c.end_date is None):
        No upper bound is applied.  Options from start_date onwards are inside
        the live campaign regardless of the latest data date, so no sentinel
        value is needed and no edge case can arise.
    """
    t = df[(df['Ticker'] == ticker) & option_mask(df['Instrument Type'])]
    dates = t['Date']
    in_any_window = pd.Series(False, index=t.index)
    for c in campaigns:
        s = c.start_date
        if c.end_date is not None:
            # Closed campaign — exclusive end: option on sale date is outside
            in_any_window |= (dates >= s) & (dates < c.end_date)
        else:
            # Open campaign — no upper bound: all options from start are inside
            in_any_window |= (dates >= s)
    return t.loc[~in_any_window, 'Total'].sum()

# ── DERIVATIVES METRICS ENGINE ─────────────────────────────────────────────────

# Union-Find (disjoint-set) helpers used by build_closed_trades to group
# option symbols that share an Order # into a single multi-leg trade.
# Extracted to module level so they are independently importable and testable.

def _uf_find(parent: dict, x: str) -> str:
    """Return the root of x's component, with path compression."""
    parent.setdefault(x, x)
    if parent[x] != x:
        parent[x] = _uf_find(parent, parent[x])
    return parent[x]


def _uf_union(parent: dict, a: str, b: str) -> None:
    """Merge the components containing a and b."""
    parent[_uf_find(parent, a)] = _uf_find(parent, b)


def _group_symbols_by_order(sym_open_orders: dict) -> dict:
    """
    Given {symbol: [order_id, ...]} return {root_symbol: [symbol, ...]}
    where all symbols that share at least one Order # end up in the same group.
    Uses Union-Find to handle chains: A∩B and B∩C → {A, B, C} one group.
    """
    order_to_syms: dict = defaultdict(set)
    for sym, orders in sym_open_orders.items():
        for oid in orders:
            order_to_syms[oid].add(sym)

    parent: dict = {}
    for syms in order_to_syms.values():
        syms = list(syms)
        for i in range(1, len(syms)):
            _uf_union(parent, syms[0], syms[i])

    groups: dict = defaultdict(list)
    for sym in sym_open_orders:
        groups[_uf_find(parent, sym)].append(sym)
    return groups


def build_closed_trades(df: pd.DataFrame, campaign_windows: Optional[dict] = None) -> pd.DataFrame:
    if campaign_windows is None: campaign_windows = {}
    equity_opts = df[df['Instrument Type'].isin(OPT_TYPES)].copy()
    sym_open_orders = {}
    for sym, grp in equity_opts.groupby('Symbol', dropna=False):
        opens = grp[grp['Sub Type'].str.lower().str.contains('to open', na=False)]
        if not opens.empty:
            sym_open_orders[sym] = opens['Order #'].dropna().unique().tolist()

    trade_groups = _group_symbols_by_order(sym_open_orders)

    closed_list = []
    for root, syms in trade_groups.items():
        grp = equity_opts[equity_opts['Symbol'].isin(syms)].sort_values('Date')
        all_closed = all(abs(equity_opts[equity_opts['Symbol'] == s]['Net_Qty_Row'].sum()) < 0.001 for s in syms)
        if not all_closed: continue

        opens = grp[grp['Sub Type'].str.lower().str.contains('to open', na=False)]
        if opens.empty: continue

        open_credit = opens['Total'].sum()
        net_pnl     = grp['Total'].sum()
        # open_date is the earliest open across ALL legs in the trade group,
        # including legs from subsequent rolls. For a rolled position this means
        # days_held spans the full roll chain (first open → final close), not
        # just the last leg. This is intentional: it treats a roll as one
        # continuous trade rather than a series of independent ones, giving a
        # conservative (lower) Ann Return % that reflects the real capital
        # commitment duration. A future improvement could expose per-roll
        # metrics separately for accounts with active roll histories.
        open_date   = opens['Date'].min()
        close_date  = grp['Date'].max()
        days_held   = max((close_date - open_date).days, 1)
        ticker      = grp['Ticker'].iloc[0]
        cp_vals     = grp['Call or Put'].dropna().str.upper().unique().tolist()
        cp          = cp_vals[0] if len(cp_vals) == 1 else 'Mixed'
        n_long      = (opens['Net_Qty_Row'] > 0).sum()
        is_credit   = open_credit > 0

        if n_long > 0:
            call_strikes = grp[grp['Call or Put'].str.upper().str.contains('CALL', na=False)]['Strike Price'].dropna().sort_values()
            put_strikes  = grp[grp['Call or Put'].str.upper().str.contains('PUT',  na=False)]['Strike Price'].dropna().sort_values()
            w_call = (call_strikes.max() - call_strikes.min()) * 100 if len(call_strikes) >= 2 else 0
            w_put  = (put_strikes.max()  - put_strikes.min())  * 100 if len(put_strikes)  >= 2 else 0

            expirations = grp['Expiration Date'].dropna().unique()
            strikes_all = grp['Strike Price'].dropna().unique()
            is_calendar = len(expirations) >= 2 and len(strikes_all) == 1

            short_opens_sp  = opens[opens['Net_Qty_Row'] < 0]
            long_opens_sp   = opens[opens['Net_Qty_Row'] > 0]
            n_short_legs    = len(short_opens_sp)
            n_long_legs     = len(long_opens_sp)
            short_qty_total = abs(short_opens_sp['Net_Qty_Row'].sum())
            long_qty_total  = long_opens_sp['Net_Qty_Row'].sum()
            is_butterfly = (n_long_legs == 2 and n_short_legs == 1 and
                            short_qty_total == 2 and long_qty_total == 2 and
                            len(strikes_all) == 3 and len(expirations) == 1)

            short_cp = short_opens_sp['Call or Put'].dropna().str.upper().tolist()
            long_cp  = long_opens_sp['Call or Put'].dropna().str.upper().tolist()
            has_short_put_only  = any('PUT'  in c for c in short_cp) and not any('PUT'  in c for c in long_cp)
            has_call_spread_leg = any('CALL' in c for c in short_cp) and any('CALL' in c for c in long_cp)
            is_jade_lizard = has_short_put_only and has_call_spread_leg and len(put_strikes) == 1

            # ── Naked long: no short legs at all (e.g. LEAPS, long call/put outright) ──
            # Must be checked before spread logic — w_call/w_put are both 0 for a
            # single-strike long, which would otherwise fall into the Put Credit Spread
            # branch and produce a capital_risk of $1.
            if n_short_legs == 0:
                long_cp_types = long_opens_sp['Call or Put'].dropna().str.upper().unique().tolist()
                has_lc = any('CALL' in c for c in long_cp_types)
                has_lp = any('PUT'  in c for c in long_cp_types)
                if has_lc and not has_lp:   trade_type = 'Long Call'
                elif has_lp and not has_lc: trade_type = 'Long Put'
                else:                       trade_type = 'Long Strangle'
                # Capital at risk for a long option = premium paid (max loss if expires worthless)
                capital_risk = max(abs(open_credit), 1)
            elif is_butterfly:
                trade_type = 'Call Butterfly' if len(call_strikes.unique()) == 3 else 'Put Butterfly'
                wing_width = (strikes_all.max() - strikes_all.min()) * 100 / 2
                capital_risk = max(abs(open_credit), wing_width, 1)
            elif is_jade_lizard:
                # Standard Jade Lizard: short put (naked) + short call spread.
                # Max loss is on the put side — the naked short put carries uncapped
                # downside. Best practical proxy: put_strike × 100 − net credit received.
                # The original code used w_call (call spread width) which is wrong —
                # it understates risk on high-strike put assignments.
                # TODO(reverse_jade_lizard): A Reverse Jade Lizard (short call naked +
                # short put spread) has the opposite risk profile — max loss on the call
                # side. Detect and handle separately once trades exist in the CSV.
                _jl_put_strike = float(put_strikes.min()) if len(put_strikes) > 0 else 0.0
                trade_type   = 'Jade Lizard'
                capital_risk = max(_jl_put_strike * 100 - abs(open_credit), 1)
            elif is_calendar:
                # TODO(calendar): Detection is correct (same strike, 2+ expirations).
                # Capital risk should be debit paid for debit calendars, credit received
                # for credit calendars — currently both use abs(open_credit) which is
                # correct for debits but may misstate credit calendars.
                # Also: rolled calendars (front expires, new back sold) likely appear as
                # separate closed trades rather than one continuous position. Needs real
                # CSV data to verify — implement once you have calendar trades in your history.
                trade_type   = 'Calendar Spread'
                capital_risk = max(abs(open_credit), 1)
            elif w_call > 0 and w_put > 0:
                trade_type   = 'Iron Condor'
                capital_risk = max(max(w_call, w_put) - abs(open_credit), 1)
            elif w_call > 0:
                trade_type   = 'Call Credit Spread' if is_credit else 'Call Debit Spread'
                # Credit spread: risk = wing_width - credit_received (net outlay if assigned)
                # Debit spread:  risk = debit_paid (max loss if expires worthless) = abs(open_credit)
                capital_risk = max(w_call - abs(open_credit), 1) if is_credit else max(abs(open_credit), 1)
            else:
                trade_type   = 'Put Credit Spread' if is_credit else 'Put Debit Spread'
                capital_risk = max(w_put - abs(open_credit), 1) if is_credit else max(abs(open_credit), 1)
        else:
            strikes      = grp['Strike Price'].dropna().tolist()
            # For naked shorts the theoretical max loss is strike × 100 (underlying → 0).
            # This is a reasonable proxy for equity options (strike typically < $500),
            # but produces meaningless Ann Return % for index options where strikes are
            # in the hundreds or thousands (SPX ~5000, NDX ~20000, RUT ~2000).
            # Check if this is a known cash-settled index (SPX, NDX, RUT etc.).
            # Index options use premium received as the capital risk proxy since
            # they are margin-based, not subject to theoretical zero-underlying loss.
            # Using an explicit list avoids misclassifying high-priced equities
            # (MSTR, NFLX, AVGO etc.) that would trip a strike price threshold.
            ticker_upper = ticker.upper().split()[0]  # strip suffixes
            if ticker_upper in KNOWN_INDEXES:
                capital_risk = max(abs(open_credit), 1)   # index: use premium as risk
            else:
                max_strike   = max(strikes) if strikes else 0
                capital_risk = max(max_strike * 100, 1)   # equity: theoretical max loss
            short_opens  = opens[opens['Net_Qty_Row'] < 0]
            long_opens   = opens[opens['Net_Qty_Row'] > 0]
            cp_shorts = short_opens['Call or Put'].dropna().str.upper().unique().tolist()
            cp_longs  = long_opens['Call or Put'].dropna().str.upper().unique().tolist()
            has_sc = any('CALL' in c for c in cp_shorts)
            has_sp = any('PUT'  in c for c in cp_shorts)
            has_lc = any('CALL' in c for c in cp_longs)
            has_lp = any('PUT'  in c for c in cp_longs)
            n_contracts = int(abs(opens['Net_Qty_Row'].sum()))
            if not is_credit:
                if has_lc and not has_lp: trade_type = 'Long Call'
                elif has_lp and not has_lc: trade_type = 'Long Put'
                else: trade_type = 'Long Strangle'
            else:
                if has_sc and has_sp:
                    all_strikes = grp['Strike Price'].dropna().unique()
                    trade_type = 'Short Straddle' if len(all_strikes) == 1 else 'Short Strangle'
                    windows = campaign_windows.get(ticker, [])
                    in_campaign = any(s <= open_date <= e for s, e in windows)
                    if in_campaign:
                        trade_type = 'Covered Straddle' if 'Straddle' in trade_type else 'Covered Strangle'
                elif has_sc:
                    windows = campaign_windows.get(ticker, [])
                    in_campaign = any(s <= open_date <= e for s, e in windows)
                    trade_type = 'Covered Call' if in_campaign else (
                        'Short Call' if n_contracts == 1 else 'Short Call (x%d)' % n_contracts)
                elif has_sp:
                    trade_type = 'Short Put' if n_contracts == 1 else 'Short Put (x%d)' % n_contracts
                else:
                    trade_type = 'Short (other)'

        try:
            exp_dates = opens['Expiration Date'].dropna()
            if not exp_dates.empty:
                nearest_exp = pd.to_datetime(exp_dates.iloc[0])
                dte_open = max((nearest_exp - open_date).days, 0)
            else:
                dte_open = None
        except (ValueError, TypeError, AttributeError): dte_open = None

        closes = grp[~grp['Sub Type'].str.lower().str.contains('to open', na=False)]
        _close_sub_types = closes['Sub Type'].dropna().str.lower().unique().tolist()
        if any(PAT_EXPIR in s for s in _close_sub_types):
            close_type = '⏹️ Expired'
        elif any(PAT_ASSIGN in s for s in _close_sub_types):
            close_type = '📋 Assigned'
        elif any('exercise' in s for s in _close_sub_types):
            close_type = '🏋️ Exercised'
        else:
            close_type = '✂️ Closed'

        closed_list.append({
            'Ticker': ticker, 'Trade Type': trade_type,
            'Type': 'Call' if 'CALL' in cp else 'Put' if 'PUT' in cp else 'Mixed',
            'Spread': n_long > 0, 'Is Credit': is_credit, 'Days Held': days_held,
            'Open Date': open_date, 'Close Date': close_date, 'Premium Rcvd': open_credit,
            'Net P/L': net_pnl,
            # Capture %: for credit trades = P/L as % of premium collected (how much of the
            # credit did you keep). For debit trades = P/L as % of premium paid (return on
            # the capital deployed into the trade). Sign-safe: uses abs(open_credit).
            'Capture %': net_pnl / abs(open_credit) * 100 if abs(open_credit) > 0 else None,
            'Capital Risk': capital_risk,
            # Ann Return %: enabled for ALL trades (credit and debit) — the formula is
            # the same: P/L / capital_at_risk * annualisation factor.
            # Previously gated to is_credit only, leaving debit trades always None.
            'Ann Return %': max(min(net_pnl / capital_risk * 365 / days_held * 100, ANN_RETURN_CAP), -ANN_RETURN_CAP)
                if capital_risk > 0 else None,
            'Prem/Day': open_credit / days_held if is_credit else None,
            'Won': net_pnl > 0, 'DTE Open': dte_open, 'Close Type': close_type,
        })
    return pd.DataFrame(closed_list)


# ── ROLL CHAIN ENGINE ──────────────────────────────────────────────────────────

def build_option_chains(ticker_opts: pd.DataFrame) -> list:
    """
    Groups option events into roll chains by call/put type.
    A chain = one continuous short position, rolled multiple times.
    Chain ends when position goes flat AND next STO is > 3 days later.
    """
    if ticker_opts.empty:
        return []
    chains = []
    for cp_type in ['CALL', 'PUT']:
        legs = ticker_opts[
            ticker_opts['Call or Put'].str.upper().str.contains(cp_type, na=False)
        ].copy().sort_values('Date').reset_index(drop=True)
        if legs.empty: continue
        # Rename spaced columns so itertuples attribute access works
        legs = legs.rename(columns={
            'Sub Type':       'Sub_Type',
            'Strike Price':   'Strike_Price',
            'Expiration Date':'Expiration_Date',
        })

        current_chain = []
        net_qty = 0
        last_close_date = None

        for row in legs.itertuples(index=False):
            sub = str(row.Sub_Type).lower()
            qty = row.Net_Qty_Row
            exp_dt = row.Expiration_Date
            event = {
                'date': row.Date, 'sub_type': row.Sub_Type,
                'strike': row.Strike_Price,
                'exp': pd.to_datetime(exp_dt).strftime('%d/%m/%y') if pd.notna(exp_dt) else '',
                'qty': qty, 'total': row.Total, 'cp': cp_type,
                'desc': str(row.Description)[:55],
            }
            if 'to open' in sub and qty < 0:
                if last_close_date is not None and net_qty == 0:
                    if (row.Date - last_close_date).days > ROLL_CHAIN_GAP_DAYS and current_chain:
                        chains.append(current_chain)
                        current_chain = []
                net_qty += abs(qty)
                current_chain.append(event)
                last_close_date = None
            elif net_qty > 0 and (PAT_CLOSE in sub or 'expiration' in sub or 'assignment' in sub):
                # Close / expiry / assignment — reduce net position and record.
                net_qty = max(net_qty - abs(qty), 0)
                current_chain.append(event)
                if net_qty == 0:
                    last_close_date = row.Date
            # BTO legs (qty > 0, 'to open' in sub) are intentionally not recorded.
            # Roll chains model short-premium positions — the long wing of a spread
            # is opened in the same order as the short and appears in closed_trades_df
            # with correct P/L. Recording it here would duplicate the entry in the
            # chain visualisation without adding information. If spread-leg detail
            # is ever needed, add an 'is_long_wing' flag to the event dict here.

        if current_chain:
            chains.append(current_chain)
    return chains

def calc_dte(row: pd.Series, reference_date: pd.Timestamp) -> str:
    """
    Compute days-to-expiry for an open option row.
    Returns e.g. '21d' or 'N/A'.

    reference_date is passed explicitly (was previously an implicit module global,
    which made the function impossible to call correctly before the CSV was loaded).
    """
    if not is_option_row(str(row['Instrument Type'])) or pd.isna(row['Expiration Date']):
        return 'N/A'
    try:
        exp_date  = pd.to_datetime(row['Expiration Date'], format='mixed', errors='coerce')
        if pd.isna(exp_date):
            return 'N/A'
        exp_plain = exp_date.date() if hasattr(exp_date, 'date') else exp_date
        return '%dd' % max((exp_plain - reference_date.date()).days, 0)
    except (ValueError, TypeError, AttributeError):
        return 'N/A'



# ── Full portfolio computation ───────────────────────────────────────────────

def compute_app_data(parsed: ParsedData, use_lifetime: bool) -> AppData:
    """
    All heavy computation that depends only on the full DataFrame and
    lifetime toggle — not on the selected time window.

    Accepts a ParsedData so it can include split_events and zero_cost_rows
    in AppData without re-running detect_corporate_actions().

    Cached separately from load_and_parse so that toggling Lifetime mode
    only re-runs campaign logic, not the CSV parse.

    Returns: AppData dataclass -- see AppData definition for field descriptions.
    """
    df, split_events, zero_cost_rows = parsed
    # ── Open positions ledger ──────────────────────────────────────────────
    trade_df = df[df['Type'].isin(TRADE_TYPES)].copy()
    groups   = trade_df.groupby(
        ['Ticker', 'Symbol', 'Instrument Type', 'Call or Put',
         'Expiration Date', 'Strike Price', 'Root Symbol'], dropna=False)
    open_records = []
    for name, group in groups:
        net_qty = group['Net_Qty_Row'].sum()
        if abs(net_qty) > 0.001:
            open_records.append({
                'Ticker': name[0], 'Symbol': name[1],
                'Instrument Type': name[2], 'Call or Put': name[3],
                'Expiration Date': name[4], 'Strike Price': name[5],
                'Root Symbol': name[6], 'Net_Qty': net_qty,
                'Cost Basis': group['Total'].sum() * -1,
            })
    df_open = pd.DataFrame(open_records)

    # ── Wheel campaigns ────────────────────────────────────────────────────
    wheel_tickers = []
    for t in df['Ticker'].unique():
        if t == 'CASH': continue
        if not df[(df['Ticker'] == t) &
                  (equity_mask(df['Instrument Type'])) &
                  (df['Net_Qty_Row'] >= WHEEL_MIN_SHARES)].empty:
            wheel_tickers.append(t)

    all_campaigns = {}
    for ticker in wheel_tickers:
        camps = build_campaigns(df, ticker, use_lifetime=use_lifetime)
        if camps:
            all_campaigns[ticker] = camps

    all_tickers          = [t for t in df['Ticker'].unique() if t != 'CASH']
    pure_options_tickers = [t for t in all_tickers if t not in wheel_tickers]

    # TODO(pmcc): Poor Man's Covered Call detection would slot in here.
    # A PMCC ticker has a long deep-ITM call (LEAPS, DTE > 90 at open) plus
    # recurring short calls on the same underlying — no share purchases.
    # Detection: ticker appears in pure_options_tickers AND has a long call
    # with DTE > LEAPS_DTE_THRESHOLD at open AND has subsequent short calls.
    # Each PMCC would become a PmccCampaign(leaps_cost, premiums_collected,
    # leaps_status) added to AppData, with a dedicated tab in the UI consuming it.
    # P/L = premiums_collected - leaps_cost (+ leaps_exit if sold/expired).
    # Capital at risk = LEAPS premium paid, not strike × 100.
    # Implement once you have real PMCC trades in your CSV — the TastyTrade
    # order/description format for LEAPS + short call rolls needs to be
    # verified against actual data before building the detection logic.

    # ── Closed trades ──────────────────────────────────────────────────────
    latest_date  = df['Date'].max()
    _camp_windows = {
        _t: [(_c.start_date, _c.end_date or latest_date) for _c in _camps]
        for _t, _camps in all_campaigns.items()
    }
    closed_trades_df = build_closed_trades(df, campaign_windows=_camp_windows)

    # ── All-time P/L accounting ────────────────────────────────────────────
    closed_camp_pnl      = sum(realized_pnl(c, use_lifetime)
                               for camps in all_campaigns.values()
                               for c in camps if c.status == 'closed')
    open_premiums_banked = sum(realized_pnl(c, use_lifetime)
                               for camps in all_campaigns.values()
                               for c in camps if c.status == 'open')
    capital_deployed     = sum(c.total_shares * c.blended_basis
                               for camps in all_campaigns.values()
                               for c in camps if c.status == 'open')

    # ── P/L for pure-options tickers (not part of a 100-share wheel) ─────────
    # Two components per ticker:
    #   1. Options cash flow — already realized at open/close, no basis tracking needed
    #   2. Equity realized P/L — FIFO via _iter_fifo_sells(), same engine as the
    #      windowed view. This replaces the old cash-flow hack that was correct only
    #      when all standalone equity positions happened to be fully closed.
    # Shares still held are capital deployment, not realized P/L — their cost basis
    # stays in the FIFO queue and contributes to extra_capital_deployed instead.
    pure_opts_pnl          = 0.0
    extra_capital_deployed = 0.0

    for t in pure_options_tickers:
        t_df = df[df['Ticker'] == t]

        # 1. Options cash flow
        opt_flow = t_df[
            t_df['Instrument Type'].isin(OPT_TYPES) &
            t_df['Type'].isin(TRADE_TYPES)
        ]['Total'].sum()

        # 2. Equity realized P/L via FIFO (correct for any mix of buys, partial sells,
        #    and full exits — not just the fully-closed case the old hack handled)
        t_eq_rows  = t_df[equity_mask(t_df['Instrument Type'])].sort_values('Date')
        eq_fifo_pnl = sum(p - c for _, p, c in _iter_fifo_sells(t_eq_rows))

        pure_opts_pnl += opt_flow + eq_fifo_pnl

        # 3. Shares still open → capital deployed (not realized P/L)
        #
        # Approximation: remaining capital is costed at the average buy price
        # across ALL lots for this ticker, including lots that have already been
        # sold. The FIFO engine has consumed those lots internally, but we don't
        # expose the remaining queue here without restructuring the engine.
        # For a ticker with no partial sells this is exact. For one with partial
        # sells it slightly overstates capital deployed (sold-lot cost leaks in).
        # The error is bounded by (sold_qty / total_bought) × total_buy_cost and
        # is typically small. A precise fix would require _iter_fifo_sells() to
        # return the residual queue — deferred until this becomes measurable.
        net_shares = t_eq_rows['Net_Qty_Row'].sum()
        if net_shares > 0.0001:
            bought_rows    = t_eq_rows[t_eq_rows['Net_Qty_Row'] > 0]
            total_bought   = bought_rows['Net_Qty_Row'].sum()
            total_buy_cost = bought_rows['Total'].apply(abs).sum()
            avg_cost       = total_buy_cost / total_bought if total_bought > 0 else 0
            extra_capital_deployed += net_shares * avg_cost

    # Also include options P/L from wheel tickers that fell outside campaign windows
    # (e.g. options written before the first share purchase)
    pure_opts_per_ticker = {}
    for ticker, camps in all_campaigns.items():
        pot = pure_options_pnl(df, ticker, camps)
        pure_opts_per_ticker[ticker] = pot
        pure_opts_pnl += pot

    return AppData(
        all_campaigns=all_campaigns,
        wheel_tickers=wheel_tickers,
        pure_options_tickers=pure_options_tickers,
        closed_trades_df=closed_trades_df,
        df_open=df_open,
        closed_camp_pnl=closed_camp_pnl,
        open_premiums_banked=open_premiums_banked,
        capital_deployed=capital_deployed,
        pure_opts_pnl=pure_opts_pnl,
        extra_capital_deployed=extra_capital_deployed,
        pure_opts_per_ticker=pure_opts_per_ticker,
        split_events=split_events,
        zero_cost_rows=zero_cost_rows,
    )


