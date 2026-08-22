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
  xirr(cash_flows)                                → Optional[float]  (money-weighted annual return)
  portfolio_metrics(daily_pnl_all, cash_flows, …) → dict             (long-term performance)
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
from dataclasses import dataclass

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
    ANN_RETURN_CAP, DAILY_THETA_CAP,
    CLOSE_EXPIRED, CLOSE_ASSIGNED, CLOSE_EXERCISED, CLOSE_CLOSED,
    XIRR_RATE_LO, XIRR_RATE_HI, XIRR_MAX_ITER, XIRR_TOL,
    get_opt_multiplier,
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
            pps = abs(total) / qty if abs(qty) > FIFO_EPSILON else 0.0  # cost per share on this buy

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
    Returns a DataFrame with columns [Date, Equity, Options, Income, PnL] representing
    realized P/L by settlement date across the full portfolio, broken down by type:
      - Equity:  net gain/loss vs FIFO cost basis on equity sale dates
      - Options: full cash flow on the day (already realized at close/expiry)
      - Income:  dividends + interest received on the day
      - PnL:     sum of all three (preserved for backward compatibility)
    Share purchases are excluded — they are capital deployment, not P/L.
    Only rows with Date >= start_date are returned, but ALL equity history
    is processed so FIFO cost basis is always correct.
    """
    equity_rows = df_full[
        equity_mask(df_full['Instrument Type'])
    ].sort_values('Date')
    eq_records = [
        {'Date': date, 'PnL': proceeds - cost_basis, 'Type': 'Equity'}
        for date, proceeds, cost_basis in _iter_fifo_sells(equity_rows)
        if date >= start_date
    ]

    # Options flows — vectorized: just select [Date, Total] columns directly
    opt_rows = df_full[
        df_full['Instrument Type'].isin(OPT_TYPES) &
        df_full['Type'].isin(TRADE_TYPES) &
        (df_full['Date'] >= start_date)
    ][['Date', 'Total']].rename(columns={'Total': 'PnL'}).copy()
    opt_rows['Type'] = 'Options'

    # Dividends + interest — vectorized
    income_rows = df_full[
        df_full['Sub Type'].isin(INCOME_SUB_TYPES) &
        (df_full['Date'] >= start_date)
    ][['Date', 'Total']].rename(columns={'Total': 'PnL'}).copy()
    income_rows['Type'] = 'Income'

    if not eq_records and opt_rows.empty and income_rows.empty:
        return pd.DataFrame(columns=['Date', 'Equity', 'Options', 'Income', 'PnL'])

    combined = pd.concat(
        [pd.DataFrame(eq_records)] + ([opt_rows] if not opt_rows.empty else [])
                                    + ([income_rows] if not income_rows.empty else []),
        ignore_index=True
    )
    combined['Date'] = pd.to_datetime(combined['Date'])
    daily = (combined.groupby(['Date', 'Type'])['PnL'].sum()
                     .unstack(fill_value=0.0)
                     .reset_index())
    for col in ('Equity', 'Options', 'Income'):
        if col not in daily.columns:
            daily[col] = 0.0
    daily['PnL'] = daily[['Equity', 'Options', 'Income']].sum(axis=1)
    return daily


# ── LONG-TERM PERFORMANCE — XIRR / money-weighted return + portfolio metrics ───

def _xnpv(rate: float, flows: list, t0: pd.Timestamp) -> float:
    """Net present value of dated cash flows at an annual `rate` (decimal).

    flows: list of (date, amount). Discount factor uses actual/365 day counts.
    """
    return sum(cf / (1.0 + rate) ** ((d - t0).days / 365.0) for d, cf in flows)


def xirr(cash_flows: list,
         lo: float = XIRR_RATE_LO, hi: float = XIRR_RATE_HI,
         max_iter: int = XIRR_MAX_ITER, tol: float = XIRR_TOL) -> Optional[float]:
    """Money-weighted annual return (XIRR) via bisection.

    cash_flows: list of (pd.Timestamp, amount). Sign convention — money OUT of
    pocket is negative (deposits), money IN is positive (withdrawals + the
    terminal account value as the final flow).

    Bisection is used over Newton: it needs no derivative, cannot diverge, and
    converges on any sign-changed bracket — robust over clever, matching the
    pure-stdlib (no numpy/scipy) constraint.

    Returns the annual rate as a decimal, or None when undefined:
      - fewer than 2 flows
      - all flows the same sign (no root exists)
      - no sign change of NPV across [lo, hi] (root outside the supported band)
    """
    flows = [(d, float(a)) for d, a in cash_flows if a is not None]
    if len(flows) < 2:
        return None
    amounts = [a for _, a in flows]
    if all(a >= 0 for a in amounts) or all(a <= 0 for a in amounts):
        return None

    t0 = min(d for d, _ in flows)
    f_lo = _xnpv(lo, flows, t0)
    f_hi = _xnpv(hi, flows, t0)
    if f_lo == 0:
        return lo
    if f_hi == 0:
        return hi
    if (f_lo > 0) == (f_hi > 0):
        return None  # no bracketed root in the supported range

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        f_mid = _xnpv(mid, flows, t0)
        if abs(f_mid) < tol or (hi - lo) < 1e-9:
            return mid
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _max_drawdown(daily_pnl_all: pd.DataFrame) -> dict:
    """Max drawdown of the all-time cumulative realized-P/L curve.

    Returns {dollar, pct, duration_days, recovery_days}.  pct is relative to the
    running peak at the trough (None when that peak is not positive).  duration
    is peak→trough days; recovery is trough→full-recovery days (None if never
    recovered).  Operates on realized P/L only — see Known-Limitations (no NLV).
    """
    out = {'dollar': None, 'pct': None, 'duration_days': None, 'recovery_days': None}
    if daily_pnl_all is None or daily_pnl_all.empty:
        return out
    d = daily_pnl_all.sort_values('Date')
    dates = pd.to_datetime(d['Date']).tolist()
    cum = d['PnL'].cumsum().tolist()

    peak = cum[0]
    peak_i = 0
    max_dd = 0.0          # most-negative trough-minus-peak
    dd_peak_i = dd_tr_i = 0
    for i, v in enumerate(cum):
        if v > peak:
            peak, peak_i = v, i
        dd = v - peak
        if dd < max_dd:
            max_dd, dd_peak_i, dd_tr_i = dd, peak_i, i

    if max_dd >= 0:
        return out  # no drawdown (monotonic non-decreasing curve)

    peak_val = cum[dd_peak_i]
    out['dollar'] = max_dd
    out['pct'] = (max_dd / peak_val * 100) if peak_val > 0 else None
    out['duration_days'] = (dates[dd_tr_i] - dates[dd_peak_i]).days
    # recovery: first index after the trough whose cum regains the prior peak
    rec_i = next((j for j in range(dd_tr_i + 1, len(cum)) if cum[j] >= peak_val), None)
    out['recovery_days'] = (dates[rec_i] - dates[dd_tr_i]).days if rec_i is not None else None
    return out


def portfolio_metrics(daily_pnl_all: pd.DataFrame, cash_flows: list,
                      net_deposited: float, total_realized_pnl: float,
                      account_days: int, latest_date: pd.Timestamp,
                      unrealized_total: Optional[float] = None) -> dict:
    """Long-term portfolio performance metrics.

    Pure / Streamlit-free.  Every key is always present (None when undefined).

    MWR (money-weighted return / XIRR) is the headline long-term figure — it
    accounts for *when* capital was added.  Time-weighted return (TWR) is NOT
    computed: it requires a daily account-value (NLV) series the transactions
    CSV does not contain; we don't fabricate it (see Known-Limitations).

    Terminal account value for XIRR:
      realized = net_deposited + total_realized_pnl
      mtm      = realized + unrealized_total   (only when unrealized_total given)
    """
    cf = list(cash_flows) if cash_flows else []
    terminal_realized = net_deposited + total_realized_pnl
    mwr_realized = xirr(cf + [(latest_date, terminal_realized)]) if cf else None

    terminal_mtm = mwr_mtm = None
    if unrealized_total is not None:
        terminal_mtm = terminal_realized + unrealized_total
        mwr_mtm = xirr(cf + [(latest_date, terminal_mtm)]) if cf else None

    # CAGR on deposited capital — annualised growth of realized P/L over deposits
    cagr = None
    if net_deposited > 0 and account_days >= 1:
        base = 1.0 + total_realized_pnl / net_deposited
        if base > 0:
            cagr = base ** (365.0 / account_days) - 1.0

    dd = _max_drawdown(daily_pnl_all)
    calmar = None
    if cagr is not None and dd['pct'] is not None and dd['pct'] != 0:
        calmar = cagr / abs(dd['pct'] / 100.0)

    # Monthly realized P/L
    monthly_pnl = None
    pct_profitable_months = n_months = best_month = worst_month = None
    if daily_pnl_all is not None and not daily_pnl_all.empty:
        m = daily_pnl_all.copy()
        m['Month'] = pd.to_datetime(m['Date']).dt.to_period('M').apply(lambda p: p.start_time)
        monthly_pnl = m.groupby('Month')['PnL'].sum().reset_index()
        n_months = len(monthly_pnl)
        if n_months:
            pct_profitable_months = (monthly_pnl['PnL'] > 0).mean() * 100
            best_month = monthly_pnl['PnL'].max()
            worst_month = monthly_pnl['PnL'].min()

    return {
        'mwr_realized': mwr_realized, 'mwr_mtm': mwr_mtm,
        'terminal_realized': terminal_realized, 'terminal_mtm': terminal_mtm,
        'cagr': cagr, 'calmar': calmar,
        'max_dd_dollar': dd['dollar'], 'max_dd_pct': dd['pct'],
        'dd_duration_days': dd['duration_days'], 'dd_recovery_days': dd['recovery_days'],
        'monthly_pnl': monthly_pnl, 'n_months': n_months,
        'pct_profitable_months': pct_profitable_months,
        'best_month': best_month, 'worst_month': worst_month,
    }


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
            start_date = t['Date'].iloc[0] if not t.empty else pd.NaT
            for row in t.itertuples(index=False):
                inst     = str(row.Instrument_Type)
                total    = row.Total
                sub_type = str(row.Sub_Type)
                if is_share_row(inst):
                    if row.Net_Qty_Row > 0:
                        pps_e   = abs(total) / row.Net_Qty_Row if row.Net_Qty_Row else 0.0
                        asgn_sfx = ' (Assigned)' if sub_type.lower() == SUB_ASSIGNMENT else ''
                        events.append({'date': row.Date, 'type': 'Entry/Add',
                            'detail': 'Bought %.0f @ $%.2f/sh%s' % (row.Net_Qty_Row, pps_e, asgn_sfx),
                            'cash': total})
                    else:
                        pps_s = abs(total) / abs(row.Net_Qty_Row) if abs(row.Net_Qty_Row) else 0.0
                        events.append({'date': row.Date, 'type': 'Exit',
                            'detail': 'Sold %.0f @ $%.2f/sh' % (abs(row.Net_Qty_Row), pps_s),
                            'cash': total})
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
                # Lifetime mode collapses history; use net held shares so
                # total_cost / shares_acquired equals blended_basis.
                shares_acquired=net_shares,
            )]

    # Pre-compute earliest STO date per option symbol so we can detect closes
    # that land inside the campaign window but whose opens predated share purchase.
    _opt_t = t[t['Instrument_Type'].apply(is_option_row)]
    _sto_dates: dict = (
        _opt_t[_opt_t['Sub_Type'].str.lower().str.contains('to open', na=False)]
        .groupby('Symbol')['Date'].min()
        .to_dict()
    )

    campaigns:    list               = []
    current:      Optional[Campaign] = None
    just_closed:  Optional[Campaign] = None  # last campaign sealed this iteration
    running_shares                   = 0.0
    # Pre-campaign odd-lot pool: share buys below WHEEL_MIN_SHARES while no
    # campaign is open. They fold into the next qualifying entry so the campaign
    # share count matches the broker position (e.g. 5 held + 100 assigned = 105).
    # A pool that never reaches a campaign stays invisible — wheel = 100-lot intent.
    pool_shares:  float              = 0.0
    pool_cost:    float              = 0.0
    pool_events:  list               = []
    # FIFO lot queue for the CURRENT open campaign — display only. Mirrors the
    # share buys/sells with per-lot cost so we can report the honest cost of the
    # shares STILL HELD (see Campaign.remaining_lot_cost). Does NOT touch
    # total_cost / blended_basis, which stay carry-full for P/L and MTM.
    lot_queue:    deque              = deque()   # (qty, cost_per_share), oldest first

    def _sync_remaining(camp: Optional[Campaign]) -> None:
        if camp is not None:
            camp.remaining_lot_cost = sum(q * cpps for q, cpps in lot_queue)

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
            if running_shares > FIFO_EPSILON and split_qty > 0:
                ratio = split_qty / running_shares
                running_shares        = split_qty
                current.total_shares  = split_qty
                current.blended_basis = current.total_cost / split_qty
                # Rescale cumulative acquisitions too so total_cost /
                # shares_acquired stays the correct per-share basis post-split.
                current.shares_acquired *= ratio
                # Rescale FIFO lot quantities by the split ratio (cost per share
                # divides by the same ratio, so remaining_lot_cost is invariant —
                # the same cash now spans more shares).
                lot_queue = deque((q * ratio, cpps / ratio) for q, cpps in lot_queue)
                _sync_remaining(current)
                current.events.append({
                    'date':   row.Date,
                    'type':   'Stock Split',
                    'detail': f'{ratio:.6g}x split: {split_qty / ratio:.0f} → {split_qty:.0f} shares @ ${current.blended_basis:.4f}/sh basis',
                    'cash':   0.0,
                })
            continue

        # ── Share buy / add ────────────────────────────────────────────────
        if is_share_row(inst) and qty > FIFO_EPSILON:
            pps = abs(total) / qty
            if running_shares < FIFO_EPSILON and qty + pool_shares < WHEEL_MIN_SHARES:
                # Odd-lot buy below the campaign threshold and no campaign open —
                # pool it; it folds into the next qualifying entry.
                pool_shares += qty
                pool_cost   += abs(total)
                pool_events.append({'date': row.Date, 'type': 'Add',
                    'detail': 'Bought %.0f @ $%.2f/sh (odd lot, pre-campaign)' % (qty, pps),
                    'cash': total})
            elif running_shares < FIFO_EPSILON:
                just_closed = None  # new entry invalidates prior just_closed reference
                # New campaign entry — check if arrival was via put assignment.
                # The assigning put's credit is folded into the campaign premiums
                # (natural wheel basis = strike − put premium); its symbol is
                # recorded so pure_options_pnl excludes it and the portfolio total
                # stays balanced.
                assignment_premium, assignment_events, assignment_syms = _find_assignment_premium(t, row)
                entry_label = 'Bought %.0f @ $%.2f/sh%s' % (
                    qty, pps, ' (Assigned)' if assignment_events else '')
                # Fold any pre-campaign odd-lot shares into the entry.
                # start_date stays the entry row's date so option-premium
                # windowing for later legs is unchanged; pool events simply carry
                # earlier dates in the event log.
                entry_shares = qty + pool_shares
                entry_cost   = abs(total) + pool_cost
                current = Campaign(
                    ticker=ticker, total_shares=entry_shares, total_cost=entry_cost,
                    blended_basis=entry_cost / entry_shares,
                    premiums=assignment_premium, dividends=0.0,
                    exit_proceeds=0.0, start_date=row.Date, end_date=None,
                    status='open',
                    events=assignment_events + pool_events + [
                        {'date': row.Date, 'type': 'Entry', 'detail': entry_label, 'cash': total}
                    ],
                    shares_acquired=entry_shares,
                    assignment_option_symbols=assignment_syms,
                )
                running_shares = entry_shares
                # Seed the FIFO lot queue: pooled odd-lot shares are the oldest
                # (bought before this entry), so they go first, then this buy.
                lot_queue = deque()
                if pool_shares > FIFO_EPSILON:
                    lot_queue.append((pool_shares, pool_cost / pool_shares))
                lot_queue.append((qty, pps))
                _sync_remaining(current)
                pool_shares, pool_cost, pool_events = 0.0, 0.0, []
            else:
                # Adding to an existing position — recalculate blended basis
                new_shares        = running_shares + qty
                new_cost          = current.total_cost + abs(total)
                new_basis         = new_cost / new_shares
                current.total_shares  = new_shares
                current.total_cost    = new_cost
                current.blended_basis = new_basis
                current.shares_acquired += qty
                running_shares        = new_shares
                # Mid-campaign assignment: the put STO is inside the open window
                # and already in premiums via the option-premium branch, so the
                # returned premium/symbols are ignored here (display event only).
                _, _mid_asgn, _ = _find_assignment_premium(t, row)
                if _mid_asgn:
                    current.events.append({
                        'date': row.Date, 'type': 'Mid-campaign Assignment',
                        'detail': 'Assigned %.0f @ $%.2f/sh → blended $%.2f/sh' % (qty, pps, new_basis),
                        'cash': total,
                    })
                current.events.append({'date': row.Date, 'type': 'Add',
                    'detail': 'Added %.0f @ $%.2f → blended $%.2f/sh%s' % (
                        qty, pps, new_basis, ' (Assigned)' if _mid_asgn else ''),
                    'cash': total})
                lot_queue.append((qty, pps))
                _sync_remaining(current)

        # ── Share sale / partial exit ──────────────────────────────────────
        elif is_share_row(inst) and qty < 0:
            if current and running_shares > FIFO_EPSILON:
                current.exit_proceeds += total
                running_shares        += qty
                pps = abs(total) / abs(qty) if abs(qty) > FIFO_EPSILON else 0
                # Label a call-away: a covered-call assignment at this same
                # timestamp removed the shares (broker sale, not a discretionary
                # exit). _find_call_away returns the assigned call's strike.
                _call_strike = _find_call_away(t, row)
                _exit_detail = 'Sold %.0f @ $%.2f/sh' % (abs(qty), pps)
                if _call_strike is not None:
                    _exit_detail += ' (Called away — $%s Call)' % _fmt_strike(_call_strike)
                current.events.append({'date': row.Date, 'type': 'Exit',
                    'detail': _exit_detail, 'cash': total})
                # Consume held lots FIFO (oldest first) for remaining_lot_cost.
                _rem = abs(qty)
                while _rem > FIFO_EPSILON and lot_queue:
                    _lq, _lc = lot_queue[0]
                    _use     = min(_rem, _lq)
                    _rem     = round(_rem - _use, FIFO_ROUND)
                    _left    = round(_lq - _use, FIFO_ROUND)
                    if _left < FIFO_EPSILON:
                        lot_queue.popleft()
                    else:
                        lot_queue[0] = (_left, _lc)
                if running_shares < FIFO_EPSILON:
                    current.total_shares  = 0.0
                    current.blended_basis = 0.0
                    current.remaining_lot_cost = 0.0
                    current.end_date = row.Date
                    current.status   = 'closed'
                    campaigns.append(current)
                    just_closed    = campaigns[-1]
                    current        = None
                    running_shares = 0.0
                    lot_queue      = deque()
                else:
                    current.total_shares  = running_shares
                    current.blended_basis = current.total_cost / running_shares
                    _sync_remaining(current)
            elif pool_shares > FIFO_EPSILON:
                # Odd-lot sale before any campaign — shrink the pool so stale
                # shares can't leak into a later campaign entry.
                sold      = min(abs(qty), pool_shares)
                remaining = pool_shares - sold
                pps = abs(total) / abs(qty) if abs(qty) > FIFO_EPSILON else 0
                if remaining > FIFO_EPSILON:
                    pool_cost  *= remaining / pool_shares
                    pool_shares = remaining
                    pool_events.append({'date': row.Date, 'type': 'Exit',
                        'detail': 'Sold %.0f @ $%.2f/sh (odd lot, pre-campaign)' % (sold, pps),
                        'cash': total})
                else:
                    pool_shares, pool_cost, pool_events = 0.0, 0.0, []

        # ── Option premium ─────────────────────────────────────────────────
        elif is_option_row(inst):
            # When a stock exit and option close share the same order/timestamp,
            # Sort_Inst=0 (equity) processes before Sort_Inst=1 (option), sealing
            # current → None before the BTC is reached.  Route those same-timestamp
            # closes into just_closed so the campaign P/L stays complete.
            _is_close = 'to open' not in sub_type.lower()
            target = current if current is not None else (
                just_closed
                if (just_closed is not None
                    and _is_close
                    and row.Date == just_closed.end_date)
                else None
            )
            if target is not None and row.Date >= target.start_date:
                target.premiums += total
                target.events.append({'date': row.Date, 'type': sub_type,
                    'detail': str(row.Description)[:60], 'cash': total})
                # Detect orphaned close: a non-open leg whose STO predates the
                # campaign start. The opening credit sits in pure_options_pnl;
                # only the closing debit lands here, creating a hidden drag.
                if _is_close:
                    _sto = _sto_dates.get(str(row.Symbol))
                    if _sto is not None and _sto < target.start_date:
                        target.pre_campaign_close_net += total

        # ── Dividend ───────────────────────────────────────────────────────
        elif sub_type == SUB_DIVIDEND and current is not None:
            current.dividends += total
            current.events.append({'date': row.Date, 'type': SUB_DIVIDEND,
                'detail': 'Dividend received', 'cash': total})

    if current is not None:
        campaigns.append(current)
    return campaigns


def _find_assignment_premium(t: pd.DataFrame, row: Any) -> tuple[float, list, list]:
    """
    Look for a put assignment at the same timestamp as a share delivery row.
    If found, trace back to the originating STO(s) and record them in the
    campaign event log so the timeline shows "arrived via assignment".

    Returns (premium, list_of_event_dicts, list_of_assigned_symbols) where
    `premium` is the net credit of the assigning put(s) (Σ STO Total) and
    `symbols` are their option symbols.

    The credit is folded into the campaign's premiums by the *entry* branch of
    build_campaigns() so the effective basis reflects the first rung of the
    wheel (natural wheel accounting: basis = strike − put premium − call
    premiums).  To avoid double-counting in total_realized_pnl, pure_options_pnl
    excludes these symbols (their STO would otherwise land in the pre-purchase /
    outside-window bucket).  Rolled puts: only the final assigned symbol's STO is
    captured here; earlier roll legs are different symbols and stay in
    pure_options (documented limitation).

    The mid-campaign branch ignores the returned premium/symbols — a mid-campaign
    put STO falls inside the open window and is already in premiums via the
    normal option-premium path, so nothing needs folding there.
    """
    events  = []
    premium = 0.0
    symbols: list = []
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
        if sto.empty:
            continue
        symbols.append(sym)
        for s in sto.itertuples(index=False):
            premium += s.Total
            events.append({
                'date': s.Date, 'type': 'Assignment Put (STO)',
                'detail': str(s.Description)[:60], 'cash': s.Total,
            })
    return premium, events, symbols

def _fmt_strike(strike: float) -> str:
    """Compact strike for event labels: 18.0 → '18', 18.5 → '18.5'."""
    return '%g' % strike

def _find_call_away(t: pd.DataFrame, row: Any) -> Optional[float]:
    """
    Detect a covered-call call-away for a share-sale row: a CALL assignment
    sharing the sale's exact timestamp means the shares were assigned away
    (broker-forced sale at the strike), not sold at will. Returns the assigned
    call's strike for the event label, or None when the sale was discretionary.

    Mirrors _find_assignment_premium's column access (`t` has 'Sub_Type' renamed
    but keeps the spaced 'Call or Put' / 'Strike Price' columns). Filtering to
    Call or Put == CALL keeps put assignments (which are share BUYS on the entry
    side) from ever matching here.
    """
    if 'Call or Put' not in t.columns:
        return None
    same_dt = t[(t['Date'] == row.Date) &
                (t['Sub_Type'].str.lower() == SUB_ASSIGNMENT) &
                (t['Call or Put'].astype(str).str.upper() == 'CALL')]
    if same_dt.empty:
        return None
    _strike = same_dt['Strike Price'].dropna()
    return float(_strike.iloc[0]) if not _strike.empty else None

def effective_basis(c: Campaign, use_lifetime: bool = False) -> float:
    """
    Cost per share after netting all premium income and dividends against the
    total share acquisition cost.

    Formula (window mode):
        effective_basis = (total_cost - premiums - dividends) / total_shares

    This answers: "What did these shares actually cost me, accounting for
    everything I have collected while holding them?" A negative effective basis
    means premiums + dividends have exceeded the total share cost — the
    position is running on house money.

    use_lifetime=True returns blended_basis instead — the raw FIFO cost per
    share with no premium offset. Used in the Wheel Campaigns tab when the
    House Money lifetime toggle is off, so the basis card shows the unmodified
    acquisition cost for comparison.

    Cost source: the FIFO cost of shares STILL HELD (remaining_lot_cost) when
    available, else total_cost. They differ only after a partial sale inside an
    open campaign — carry-full-cost leaves the sold lot's cost on total_cost
    (deferring its P/L to close), which would inflate the displayed basis after
    a below-basis call-away. remaining_lot_cost reflects only the held lots, so
    the shown basis stays honest. P/L / MTM keep using total_cost / blended_basis
    directly and are unaffected.

    Returns 0.0 when total_shares is 0 (campaign not yet holding shares,
    e.g. a pure-premium run with no assignment yet).
    """
    if use_lifetime:
        return c.blended_basis
    cost = c.remaining_lot_cost if c.remaining_lot_cost is not None else c.total_cost
    net  = cost - c.premiums - c.dividends
    return net / c.total_shares if c.total_shares > 0 else 0.0

def remaining_lot_basis(c: Campaign) -> float:
    """
    Gross (pre-premium) cost per share of the shares STILL HELD — the display
    counterpart to blended_basis after a partial sale. Uses remaining_lot_cost
    (FIFO cost of held lots) so a call-away doesn't leave the sold lot's cost
    riding on the remaining shares; falls back to blended_basis when the FIFO
    cost wasn't tracked (lifetime path) or no partial sale has occurred (they are
    equal there anyway). Display only — never used in P/L, MTM, or capital.
    """
    if c.remaining_lot_cost is not None and c.total_shares > 0:
        return c.remaining_lot_cost / c.total_shares
    return c.blended_basis

def campaign_net_mtm(c: Campaign, last_price: float, use_lifetime: bool = False) -> Optional[float]:
    """
    Net campaign P/L if it were CLOSED at `last_price` right now — the number the
    premiums-only `realized_pnl()` hides on an open wheel. It folds the deferred
    equity result (a below-basis call-away's loss still sitting in the carry-full
    cost) and the mark on the still-held shares back into a single figure.

    Returns None when there's nothing to mark — no/zero/negative price, a closed
    campaign, or no live share position — so the caller shows '—'.

    Non-lifetime:
        exit_proceeds + premiums + dividends − total_cost + last_price × shares
        i.e. what realized_pnl() would return if the held shares were sold at
        last_price. Uses the carry-full total_cost, which still holds every lot's
        cost (incl. the called-away lot), so the deferred loss is included.
    Lifetime:
        last_price × shares − total_cost.  Lifetime total_cost is already net of
        premiums and prior sales, so only the held shares are marked against it
        (equivalently (last_price − blended_basis) × shares); adding premiums
        again would double-count.

    Pure / Streamlit-free — takes a scalar price so the tab layer owns the live
    fetch and this stays unit-testable.
    """
    if not last_price or last_price <= 0 or c.status != 'open' or c.total_shares <= 0:
        return None
    if use_lifetime:
        return last_price * c.total_shares - c.total_cost
    return (c.exit_proceeds + c.premiums + c.dividends
            - c.total_cost + last_price * c.total_shares)

def realized_pnl(c: Campaign, use_lifetime: bool = False) -> float:
    """
    Total realised profit/loss for a campaign.

    Open campaign:
        realized_pnl = premiums + dividends
        Only income actually banked. The equity position is unrealised —
        shares are still held, so no exit proceeds are included.

    Closed campaign:
        realized_pnl = exit_proceeds + premiums + dividends - total_cost
        exit_proceeds is the cash received when shares were sold (positive).
        total_cost is the cash paid to acquire shares (positive, subtracted).
        Equivalent to: equity_gain + premiums + dividends,
        where equity_gain = exit_proceeds - total_cost.

    use_lifetime=True returns only premiums + dividends regardless of status —
    used when the House Money lifetime toggle strips out the equity component
    so the scorecard shows pure premium income only.

    Note: this function is the single formula for campaign P/L. It is called
    from both compute_app_data() and the zero-cost exclusion path via
    _aggregate_campaign_pnl() — a change here propagates to both automatically.
    """
    if use_lifetime:
        return c.premiums + c.dividends
    if c.status == 'closed':
        return c.exit_proceeds + c.premiums + c.dividends - c.total_cost
    return c.premiums + c.dividends

def open_campaign_equity(df: pd.DataFrame, all_campaigns: dict) -> float:
    """
    FIFO-settled equity P/L of share sales that happened *inside still-open*
    wheel campaigns — the component that `realized_pnl()` defers.

    For an open campaign, `realized_pnl()` returns premiums + dividends only:
    the equity gain/loss on a partial sale is deferred until the campaign
    closes (the carry-full-cost convention — remaining shares carry all
    remaining cost). The Portfolio-tab chart (`calculate_daily_realized_pnl`),
    by contrast, books equity P/L via FIFO on each sale's settlement date, so a
    partial sale inside an open campaign is recognised immediately. This helper
    returns exactly that deferred amount so the All-Time Realized P/L headline
    can reconcile to the chart / broker-realized figure.

    Per wheel ticker:
        full_fifo = Σ (proceeds − cost) over every FIFO sale, full history
        closed_eq = Σ (exit_proceeds − total_cost) for that ticker's CLOSED
                    campaigns (equity already recognised in closed_camp_pnl)
        contribution = full_fifo − closed_eq

    A ticker whose campaigns are all closed contributes 0 (full FIFO equals the
    closed-campaign equity). Reads `df` directly, so it honours any upstream
    ticker filtering (e.g. the zero-cost exclusion) without a separate cache.
    Pure / Streamlit-free.
    """
    total = 0.0
    for ticker, camps in all_campaigns.items():
        rows = df[equity_mask(df['Instrument Type']) &
                  (df['Ticker'] == ticker)].sort_values('Date')
        full_fifo = sum(p - c for _, p, c in _iter_fifo_sells(rows))
        closed_eq = sum(c.exit_proceeds - c.total_cost
                        for c in camps if c.status == 'closed')
        total += full_fifo - closed_eq
    return total

def pure_options_pnl(df: pd.DataFrame, ticker: str, campaigns: list[Campaign]) -> float:
    """
    Options P/L for a ticker that falls *outside* all campaign windows.

    Window boundary convention
    --------------------------
    Start is always inclusive (>= start_date).
    End depends on whether the campaign is closed or still open:

      Closed campaign (c.end_date is set):
        End is *inclusive* (<= end_date).  Options that close on the same
        timestamp as the stock sale belong to the campaign (same-order BTC
        plus stock close share the exact end_date timestamp).  build_campaigns()
        now routes those same-timestamp closes into campaign.premiums via the
        just_closed reference, so using <= here keeps the two sides in sync
        and avoids double-counting the BTC in both campaign and pure_options.

      Open campaign (c.end_date is None):
        No upper bound is applied.  Options from start_date onwards are inside
        the live campaign regardless of the latest data date, so no sentinel
        value is needed and no edge case can arise.
    """
    t = df[(df['Ticker'] == ticker) & option_mask(df['Instrument Type'])]
    # Exclude assigning-put symbols whose credit was folded into a campaign's
    # premiums on entry — their STO would otherwise be counted again here (it
    # predates the campaign start, so it lands in the outside-window bucket).
    _assigned = {s for c in campaigns for s in c.assignment_option_symbols}
    if _assigned:
        t = t[~t['Symbol'].isin(_assigned)]
    dates = t['Date']
    in_any_window = pd.Series(False, index=t.index)
    for c in campaigns:
        s = c.start_date
        if c.end_date is not None:
            # Closed campaign — inclusive end: option on sale date is inside
            in_any_window |= (dates >= s) & (dates <= c.end_date)
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


# ── TRADE CLASSIFICATION HELPERS ──────────────────────────────────────────────

@dataclass
class _LegInfo:
    """
    Derived leg partitions and structure flags for a closed trade group.

    Computed once by ``_derive_leg_info(grp, opens)`` and consumed by both
    ``_classify_trade_type`` and ``_calculate_capital_risk``.  Previously each
    of those functions independently re-derived ~16 lines of identical prelude
    (CLAUDE.md flagged the ``is_butterfly`` / ``is_short_butterfly`` flags as
    a known sync-or-drift hazard).  Folding them through one builder means a
    single source of truth — change a flag here, both consumers update.
    """
    # Leg partitions (kept as DataFrames so consumers can re-filter by strike
    # for downstream specifics like ratio-spread max-short-strike lookups).
    short_opens:     pd.DataFrame
    long_opens:      pd.DataFrame
    n_short_legs:    int
    n_long_legs:     int
    short_qty_total: float
    long_qty_total:  float
    # Strike series (sorted ascending, NaN dropped).
    call_strikes:    pd.Series
    put_strikes:     pd.Series
    strikes_all:     Any   # np.ndarray of unique strikes
    expirations:     Any   # np.ndarray of unique expiry dates
    # Direction-tagged contract quantities.
    short_call_qty:  float
    long_call_qty:   float
    short_put_qty:   float
    long_put_qty:    float
    # Presence flags.
    has_sc:          bool
    has_sp:          bool
    has_lc:          bool
    has_lp:          bool
    # Composite-structure flags — single source of truth.
    is_butterfly:        bool
    is_short_butterfly:  bool
    is_jade_lizard:      bool
    is_ratio_lizard:     bool
    is_call_ratio:       bool
    is_put_ratio:        bool
    is_calendar:         bool


def _derive_leg_info(grp: pd.DataFrame, opens: pd.DataFrame) -> _LegInfo:
    """
    Pure builder for ``_LegInfo`` from a closed trade group.

    Single source of truth for the ``is_butterfly`` / ``is_short_butterfly`` /
    ``is_jade_lizard`` / etc. detection conditions — both consumers must read
    them from the same object, so they cannot drift apart silently.
    """
    call_mask    = grp['Call or Put'].str.upper().str.contains('CALL', na=False)
    put_mask     = grp['Call or Put'].str.upper().str.contains('PUT',  na=False)
    call_strikes = grp.loc[call_mask, 'Strike Price'].dropna().sort_values()
    put_strikes  = grp.loc[put_mask,  'Strike Price'].dropna().sort_values()

    expirations  = grp['Expiration Date'].dropna().unique()
    strikes_all  = grp['Strike Price'].dropna().unique()

    short_opens     = opens[opens['Net_Qty_Row'] < 0]
    long_opens      = opens[opens['Net_Qty_Row'] > 0]
    n_short_legs    = len(short_opens)
    n_long_legs     = len(long_opens)
    short_qty_total = abs(short_opens['Net_Qty_Row'].sum())
    long_qty_total  = long_opens['Net_Qty_Row'].sum()

    sc_mask = short_opens['Call or Put'].str.upper().str.contains('CALL', na=False)
    sp_mask = short_opens['Call or Put'].str.upper().str.contains('PUT',  na=False)
    lc_mask = long_opens['Call or Put'].str.upper().str.contains('CALL', na=False)
    lp_mask = long_opens['Call or Put'].str.upper().str.contains('PUT',  na=False)

    short_call_qty = abs(short_opens.loc[sc_mask, 'Net_Qty_Row'].sum())
    long_call_qty  =     long_opens.loc[lc_mask, 'Net_Qty_Row'].sum()
    short_put_qty  = abs(short_opens.loc[sp_mask, 'Net_Qty_Row'].sum())
    long_put_qty   =     long_opens.loc[lp_mask, 'Net_Qty_Row'].sum()

    has_sc = short_call_qty > 0
    has_sp = short_put_qty  > 0
    has_lc = long_call_qty  > 0
    has_lp = long_put_qty   > 0

    is_butterfly = (n_long_legs == 2 and n_short_legs == 1 and
                    short_qty_total == 2 and long_qty_total == 2 and
                    len(strikes_all) == 3 and len(expirations) == 1)

    is_short_butterfly = (n_long_legs == 1 and n_short_legs == 2 and
                          long_qty_total == 2 and short_qty_total == 2 and
                          len(strikes_all) == 3 and len(expirations) == 1)

    has_short_put_only  = has_sp and not has_lp
    has_call_spread_leg = has_sc and has_lc
    is_jade_lizard  = (has_short_put_only and has_call_spread_leg
                       and len(put_strikes) == 1 and short_call_qty == long_call_qty)
    is_ratio_lizard = (has_short_put_only and has_call_spread_leg
                       and len(put_strikes) == 1 and short_call_qty != long_call_qty)
    is_call_ratio   = (has_sc and has_lc and not has_sp and not has_lp
                       and short_call_qty != long_call_qty)
    is_put_ratio    = (has_sp and has_lp and not has_sc and not has_lc
                       and short_put_qty != long_put_qty)
    is_calendar     = len(expirations) >= 2 and len(strikes_all) == 1

    return _LegInfo(
        short_opens=short_opens, long_opens=long_opens,
        n_short_legs=n_short_legs, n_long_legs=n_long_legs,
        short_qty_total=short_qty_total, long_qty_total=long_qty_total,
        call_strikes=call_strikes, put_strikes=put_strikes,
        strikes_all=strikes_all, expirations=expirations,
        short_call_qty=short_call_qty, long_call_qty=long_call_qty,
        short_put_qty=short_put_qty,   long_put_qty=long_put_qty,
        has_sc=has_sc, has_sp=has_sp, has_lc=has_lc, has_lp=has_lp,
        is_butterfly=is_butterfly, is_short_butterfly=is_short_butterfly,
        is_jade_lizard=is_jade_lizard, is_ratio_lizard=is_ratio_lizard,
        is_call_ratio=is_call_ratio,   is_put_ratio=is_put_ratio,
        is_calendar=is_calendar,
    )


def _classify_trade_type(
    grp: pd.DataFrame,
    opens: pd.DataFrame,
    ticker: str,
    campaign_windows: dict,
    known_indexes: set,
    is_credit: bool,
    open_date: pd.Timestamp,
    n_contracts: int,
) -> str:
    """
    Pure function — returns strategy label from a closed trade group.
    All arguments passed explicitly; no module-global reads except via caller.
    """
    info = _derive_leg_info(grp, opens)
    n_long = (opens['Net_Qty_Row'] > 0).sum()
    # Spread-width signals at multiplier 100 — only used as booleans here
    # (>0 ⇒ exists), so the actual mult value doesn't matter for labelling.
    w_call = ((info.call_strikes.max() - info.call_strikes.min()) * 100
              if len(info.call_strikes) >= 2 else 0)
    w_put  = ((info.put_strikes.max()  - info.put_strikes.min())  * 100
              if len(info.put_strikes)  >= 2 else 0)

    # ── Multi-leg (has at least one long open leg) ─────────────────────────────
    if n_long > 0:
        if info.n_short_legs == 0:
            if info.has_lc and not info.has_lp: return 'Long Call'
            elif info.has_lp and not info.has_lc: return 'Long Put'
            else:                                  return 'Long Strangle'
        elif info.is_butterfly:
            return 'Long Call Butterfly' if len(info.call_strikes.unique()) == 3 else 'Long Put Butterfly'
        elif info.is_short_butterfly:
            return 'Short Call Butterfly' if len(info.call_strikes.unique()) == 3 else 'Short Put Butterfly'
        elif info.is_call_ratio:
            return 'Call Ratio Spread'
        elif info.is_put_ratio:
            return 'Put Ratio Spread'
        elif info.is_jade_lizard:
            return 'Jade Lizard'
        elif info.is_ratio_lizard:
            return 'Ratio Lizard'
        elif info.is_calendar:
            return 'Calendar Spread'
        elif w_call > 0 and w_put > 0:
            if info.short_opens['Strike Price'].nunique() == 1:
                return 'Iron Butterfly'
            elif info.long_opens['Strike Price'].nunique() == 1:
                return 'Reverse Iron Butterfly'
            elif is_credit:
                return 'Iron Condor'
            else:
                return 'Reverse Iron Condor'
        elif w_call > 0:
            return 'Call Credit Spread' if is_credit else 'Call Debit Spread'
        else:
            return 'Put Credit Spread' if is_credit else 'Put Debit Spread'

    # ── Naked short (no long legs) ─────────────────────────────────────────────
    if not is_credit:
        if info.has_lc and not info.has_lp: return 'Long Call'
        elif info.has_lp and not info.has_lc: return 'Long Put'
        else: return 'Long Strangle'
    else:
        windows = campaign_windows.get(ticker, [])
        in_campaign = any(s <= open_date <= e for s, e in windows)
        if info.has_sc and info.has_sp:
            base = 'Short Straddle' if len(info.strikes_all) == 1 else 'Short Strangle'
            return ('Covered Straddle' if 'Straddle' in base else 'Covered Strangle') if in_campaign else base
        elif info.has_sc:
            if in_campaign: return 'Covered Call'
            return 'Short Call' if n_contracts == 1 else 'Short Call (x%d)' % n_contracts
        elif info.has_sp:
            return 'Short Put' if n_contracts == 1 else 'Short Put (x%d)' % n_contracts
        else:
            return 'Short (other)'


def _calculate_capital_risk(
    grp: pd.DataFrame,
    opens: pd.DataFrame,
    is_credit: bool,
    ticker: str,
    known_indexes: set,
    campaign_windows: Optional[dict] = None,
    open_date: Optional[pd.Timestamp] = None,
    campaign_basis: Optional[dict] = None,
) -> float:
    """
    Pure function — computes Capital at Risk for a closed trade group.
    Uses opens['Total'].sum() (not net) for index premium proxy.

    campaign_basis: optional {ticker: [(start, end, basis_per_share)]} —
    average acquisition cost per share for each campaign window.  When
    available, a pure covered call uses basis_per_share × mult as its
    capital base (the stock actually pinned by the position) instead of
    the premium proxy.  Premium-as-capital made Daily θ % degenerate to
    100/DTE and pegged Ann Return % at ±cap for every covered call.
    """
    inst_type   = grp['Instrument Type'].iloc[0] if not grp.empty else 'Equity Option'
    mult        = get_opt_multiplier(ticker, inst_type)
    open_credit = opens['Total'].sum()
    n_long      = (opens['Net_Qty_Row'] > 0).sum()

    info   = _derive_leg_info(grp, opens)
    w_call = ((info.call_strikes.max() - info.call_strikes.min()) * mult
              if len(info.call_strikes) >= 2 else 0)
    w_put  = ((info.put_strikes.max()  - info.put_strikes.min())  * mult
              if len(info.put_strikes)  >= 2 else 0)

    # ── Multi-leg ──────────────────────────────────────────────────────────────
    if n_long > 0:
        if info.n_short_legs == 0:
            return max(abs(open_credit), 1)
        elif info.is_butterfly:
            wing_width = (info.strikes_all.max() - info.strikes_all.min()) * mult / 2
            return max(abs(open_credit), wing_width, 1)
        elif info.is_short_butterfly:
            wing_width = (info.strikes_all.max() - info.strikes_all.min()) * mult / 2
            return max(wing_width - open_credit, 1)   # max loss = wing width minus credit received
        elif info.is_call_ratio or info.is_put_ratio:
            # Extra short leg is effectively naked — highest short strike is the risk proxy
            short_strikes = info.short_opens['Strike Price'].dropna()
            max_short = float(short_strikes.max()) if not short_strikes.empty else 0.0
            return max(max_short * mult - abs(open_credit), 1)
        elif info.is_jade_lizard or info.is_ratio_lizard:
            _jl_put_strike = float(info.put_strikes.min()) if len(info.put_strikes) > 0 else 0.0
            return max(_jl_put_strike * mult - abs(open_credit), 1)
        elif info.is_calendar:
            return max(abs(open_credit), 1)
        elif w_call > 0 and w_put > 0:
            return max(max(w_call, w_put) - abs(open_credit), 1)
        elif w_call > 0:
            return max(w_call - abs(open_credit), 1) if is_credit else max(abs(open_credit), 1)
        else:
            return max(w_put - abs(open_credit), 1) if is_credit else max(abs(open_credit), 1)

    # ── Covered by wheel stock ─────────────────────────────────────────────────
    # Short option(s) opened while holding shares in a live wheel campaign.
    # The stock collateral hedges the call side fully; the put side (if any)
    # is unhedged and contributes max_loss = put_strike × mult, less the
    # premium collected.  This matches what `_classify_trade_type` labels
    # 'Covered Call' / 'Covered Straddle' / 'Covered Strangle' — see the
    # symmetric in_campaign check there.
    if campaign_windows is not None and open_date is not None and is_credit:
        _windows = campaign_windows.get(ticker, [])
        if any(s <= open_date <= e for s, e in _windows):
            # Covered strangle / straddle: short call + short put, no longs.
            # Call side fully covered by stock, put side cash-secured to its
            # strike.  Without this branch the function fell through to the
            # naked-short path below and returned max_strike × mult (i.e. the
            # call strike, ignoring the put liability entirely), which both
            # overstated risk on the call side and understated it on the put.
            if (info.has_sc and info.has_sp
                    and not info.has_lc and not info.has_lp
                    and len(info.put_strikes) > 0):
                _put_strike = float(info.put_strikes.min())
                return max(_put_strike * mult - abs(open_credit), 1)
            # Pure covered call: the stock bag is the capital actually pinned
            # by the position — use the campaign's average acquisition cost
            # per share × mult (100 shares per contract).  This keeps Daily θ %
            # a genuine yield-on-collateral (comparable to a CSP's
            # strike × mult) instead of degenerating to 100/DTE, and stops
            # Ann Return % pegging at ±cap on every covered call.
            if info.has_sc and not info.has_lc and not info.has_sp:
                if campaign_basis is not None:
                    for _s, _e, _basis in campaign_basis.get(ticker, []):
                        if _s <= open_date <= _e and _basis > 0:
                            return max(_basis * mult, 1)
                # Fallback when no basis is known (caller didn't supply it):
                # premium proxy, the pre-v26.15 behaviour.
                return max(abs(open_credit), 1)

    # ── Naked short ────────────────────────────────────────────────────────────
    ticker_upper = ticker.upper().split()[0]
    if ticker_upper in known_indexes:
        return max(abs(open_credit), 1)
    strikes = grp['Strike Price'].dropna().tolist()
    max_strike = max(strikes) if strikes else 0
    return max(max_strike * mult, 1)


def build_closed_trades(
    df: pd.DataFrame,
    campaign_windows: Optional[dict] = None,
    campaign_basis: Optional[dict] = None,
) -> pd.DataFrame:
    if campaign_windows is None: campaign_windows = {}
    equity_opts = df[df['Instrument Type'].isin(OPT_TYPES)].copy()
    sym_open_orders = {}
    for sym, grp in equity_opts.groupby('Symbol', dropna=False):
        opens = grp[grp['Sub Type'].str.lower().str.contains('to open', na=False)]
        if not opens.empty:
            sym_open_orders[sym] = opens['Order #'].dropna().unique().tolist()

    trade_groups = _group_symbols_by_order(sym_open_orders)

    # Pre-compute net qty per symbol once (O(E)) so the all-closed check below
    # is an O(T×S) dict lookup instead of O(T×S×E) repeated boolean indexing.
    # On the 700-row test CSV this avoids ~21M comparisons; on a 5000-row file
    # it scales to ~1.4B otherwise.
    sym_net_qty = equity_opts.groupby('Symbol', dropna=False)['Net_Qty_Row'].sum().abs()

    closed_list = []
    for root, syms in trade_groups.items():
        grp = equity_opts[equity_opts['Symbol'].isin(syms)].sort_values('Date')
        all_closed = all(sym_net_qty.get(s, 0) < FIFO_EPSILON for s in syms)
        if not all_closed: continue

        opens = grp[grp['Sub Type'].str.lower().str.contains('to open', na=False)]
        if opens.empty: continue

        open_credit = opens['Total'].sum()
        _short_opens = opens[opens['Net_Qty_Row'] < 0]
        # n_contracts = number of complete structures traded.
        # Group short legs by option type and sum — so an IC (1 short call + 1 short put)
        # gives max(1, 1)=1, while a 2-lot short put gives max(2)=2.
        if not _short_opens.empty:
            n_contracts = int(
                _short_opens.groupby(_short_opens['Call or Put'].fillna(''))['Net_Qty_Row']
                .apply(lambda x: x.abs().sum()).max()
            )
        else:
            n_contracts = int(opens['Net_Qty_Row'].abs().max())
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
        ticker      = grp['Ticker'].iloc[0] if not grp.empty else ''
        cp_vals     = grp['Call or Put'].dropna().str.upper().unique().tolist()
        cp          = cp_vals[0] if len(cp_vals) == 1 else 'Mixed'
        n_long      = (opens['Net_Qty_Row'] > 0).sum()
        is_credit   = open_credit > 0

        trade_type   = _classify_trade_type(
            grp, opens, ticker, campaign_windows, KNOWN_INDEXES,
            is_credit, open_date, n_contracts,
        )
        capital_risk = _calculate_capital_risk(
            grp, opens, is_credit, ticker, KNOWN_INDEXES,
            campaign_windows=campaign_windows, open_date=open_date,
            campaign_basis=campaign_basis,
        )

        try:
            exp_dates = opens['Expiration Date'].dropna()
            if not exp_dates.empty:
                # earliest expiry by calendar date — NOT iloc[0], which would
                # return the first-by-transaction-Date row (wrong for any
                # calendar spread where the far-month leg is opened first).
                # dte_open feeds Daily θ %, Expiration display, and DTE at
                # Close, so the wrong choice silently distorts all three.
                nearest_exp = pd.to_datetime(exp_dates.min())
                dte_open    = max((nearest_exp - open_date).days, 0)
                expiry_date = nearest_exp.date()
            else:
                nearest_exp = None
                dte_open    = None
                expiry_date = None
        except (ValueError, TypeError, AttributeError):
            nearest_exp = None
            dte_open    = None
            expiry_date = None

        closes = grp[~grp['Sub Type'].str.lower().str.contains('to open', na=False)]
        _close_sub_types = closes['Sub Type'].dropna().str.lower().unique().tolist()
        if any(PAT_EXPIR in s for s in _close_sub_types):
            close_type = CLOSE_EXPIRED
        elif any(PAT_ASSIGN in s for s in _close_sub_types):
            close_type = CLOSE_ASSIGNED
        elif any('exercise' in s for s in _close_sub_types):
            close_type = CLOSE_EXERCISED
        else:
            close_type = CLOSE_CLOSED

        closed_list.append({
            'Ticker': ticker, 'Trade Type': trade_type,
            'Type': 'Call' if 'CALL' in cp else 'Put' if 'PUT' in cp else 'Mixed',
            'Spread': n_long > 0, 'Is Credit': is_credit, 'Days Held': days_held,
            'Open Date': open_date, 'Close Date': close_date, 'Net Premium': open_credit,
            'Net P/L': net_pnl,
            # Capture %: for credit trades = P/L as % of premium collected (how much of the
            # credit did you keep). For debit trades = P/L as % of premium paid (return on
            # the capital deployed into the trade). Sign-safe: uses abs(open_credit).
            # Capture % is only meaningful for credit trades — for debits it produces
            # misleading values like -100% (full loss) that look like a valid metric.
            'Capture %': net_pnl / abs(open_credit) * 100 if (is_credit and abs(open_credit) > 0) else None,
            'Capital at Risk': capital_risk,
            # Ann Return %: enabled for ALL trades (credit and debit) — the formula is
            # the same: P/L / capital_at_risk * annualisation factor.
            # Previously gated to is_credit only, leaving debit trades always None.
            # NOTE: this column is per-trade only.  Do NOT re-introduce a Median Ann
            # Return aggregate — the 365/days_held extrapolation degenerates on a
            # mixed weekly/swing book, pegging the median to the ±cap.  v26.11
            # dropped the scorecard tile, per-ticker median, and HTML report column
            # for exactly that reason; this row-level value is kept only for
            # sortable inspection in the per-trade table.
            'Ann Return %': max(min(net_pnl / capital_risk * 365 / days_held * 100, ANN_RETURN_CAP), -ANN_RETURN_CAP)
                if capital_risk > 0 else None,
            'Prem/Day': open_credit / days_held if is_credit else None,  # credit trades only
            # Daily θ %: entry-quality metric — credit collected per DAY OF INTENDED RISK,
            # divided by capital at risk.  Uses DTE at open rather than days_held so that
            # closing winners fast doesn't artificially inflate it.  Answers "at the
            # moment I opened this, what was the theoretical theta yield I was buying?"
            # Independent of close timing — a 45-DTE put paying 0.3%/day stays 0.3%/day
            # whether held 1 day or 30.
            'Daily θ %': min(open_credit / max(dte_open, 1) / capital_risk * 100, DAILY_THETA_CAP)
                if (is_credit and capital_risk > 0 and dte_open is not None) else None,
            'Won': net_pnl > 0, 'DTE at Open': dte_open, 'Close Reason': close_type,
            '50% Target': round(open_credit * 0.50, 2) if is_credit else None,
            'Expiration': expiry_date,
            'Contracts': n_contracts,
        })
    ct = pd.DataFrame(closed_list)
    if not ct.empty and 'Expiration' in ct.columns:
        ct['DTE at Close'] = ct.apply(
            lambda r: max((pd.Timestamp(r['Expiration']) - pd.Timestamp(r['Close Date'])).days, 0)
            if pd.notna(r['Expiration']) else None, axis=1
        )
    return ct


# ── MARK-TO-MARKET ─────────────────────────────────────────────────────────────

@dataclass
class UnrealizedPnL:
    equity:     float  # unrealized P/L on open equity positions
    options:    float  # unrealized P/L on open option legs
    total:      float  # equity + options
    notional:   float  # equity capital deployed (cost basis × shares) — ROR denominator
    coverage:   int    # tickers for which a live price was found
    total_open: int    # total tickers with open positions in df_open


def compute_unrealized_pnl(
    df_open: pd.DataFrame,
    all_campaigns: dict,
    live_prices: dict,
) -> UnrealizedPnL:
    """
    Compute unrealized P/L for all open positions given live_prices from fetch_live_prices().

    Equity uses blended_basis (raw acquisition cost) so premiums already counted in
    realized P/L are not double-counted here.  Options use the unified formula:
        mark × Net_Qty × multiplier − Cost_Basis
    which is correct for both longs (Cost_Basis > 0) and shorts (Cost_Basis < 0).
    """
    if df_open.empty or not live_prices:
        n = len(df_open['Ticker'].dropna().unique()) if not df_open.empty else 0
        return UnrealizedPnL(0.0, 0.0, 0.0, 0.0, 0, n)

    eq_unreal   = 0.0
    eq_notional = 0.0
    opt_unreal  = 0.0
    covered: set = set()

    # 1. Wheel campaign equity — use blended_basis as cost (premiums already in realized)
    campaign_tickers: set = set()
    for ticker, camps in all_campaigns.items():
        c = next((c for c in reversed(camps)
                  if c.status == 'open' and c.total_shares > FIFO_EPSILON), None)
        if c is None:
            continue
        campaign_tickers.add(ticker)
        lp = live_prices.get(ticker, {}).get('last', 0.0)
        if lp > 0:
            eq_unreal   += (lp - c.blended_basis) * c.total_shares
            eq_notional += c.blended_basis * c.total_shares
            covered.add(ticker)

    # 2. Non-campaign equity in df_open (long shares not part of a wheel)
    eq_rows = df_open[equity_mask(df_open['Instrument Type'])]
    for _, row in eq_rows.iterrows():
        t = row['Ticker']
        if t in campaign_tickers or row['Net_Qty'] <= FIFO_EPSILON:
            continue
        lp = live_prices.get(t, {}).get('last', 0.0)
        if lp > 0:
            cost_per_share = row['Cost Basis'] / row['Net_Qty']
            eq_unreal   += (lp - cost_per_share) * row['Net_Qty']
            eq_notional += row['Cost Basis']
            covered.add(t)

    # 3. Open option legs — mark × Net_Qty × multiplier − Cost_Basis
    opt_rows = df_open[option_mask(df_open['Instrument Type'])]
    for _, row in opt_rows.iterrows():
        t = row['Ticker']
        if t not in live_prices:
            continue
        try:
            exp_key = row['Expiration Date']
            strike  = float(row['Strike Price'])
            cp      = str(row['Call or Put']).upper()
            mark    = live_prices[t]['options'].get((exp_key, strike, cp), {}).get('mark')
            if mark is None:
                continue
            mult = get_opt_multiplier(row.get('Root Symbol', t))
            opt_unreal += mark * row['Net_Qty'] * mult - row['Cost Basis']
            covered.add(t)
        except Exception:
            pass

    all_tickers_open = set(df_open['Ticker'].dropna()) if not df_open.empty else set()
    total = eq_unreal + opt_unreal
    return UnrealizedPnL(eq_unreal, opt_unreal, total, eq_notional,
                         len(covered), len(all_tickers_open))


# ── ROLL CHAIN ENGINE ──────────────────────────────────────────────────────────

def build_option_chains(ticker_opts: pd.DataFrame) -> list:
    """
    Groups option events into roll chains by call/put type.
    A chain = one continuous short position, rolled multiple times, plus any
    long wings (spread legs) opened/closed alongside it.

    Legs are classified by direction = (open/close) × qty sign, and ALL legs are
    recorded with an 'is_long' flag so the display can mark long wings:

        open,  qty < 0  → short open   (short_qty += |qty|)
        open,  qty > 0  → long open    (long_qty  += |qty|,  is_long=True)
        close, qty > 0  → short close  (short_qty -= |qty|)   [BTC / short expiry/assign]
        close, qty < 0  → long close   (long_qty  -= |qty|,  is_long=True)  [STC / long expiry]

    Chain-break (the > ROLL_CHAIN_GAP_DAYS split) keys on the SHORT leg going flat
    before a new short open — long legs never trigger a break. Tracking short and
    long separately keeps a spread's legs from mis-counting each other (a long-leg
    close no longer consumes a short slot, so the real short close isn't dropped).
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
        short_qty = 0
        long_qty  = 0
        last_close_date = None

        for row in legs.itertuples(index=False):
            sub = str(row.Sub_Type).lower()
            qty = row.Net_Qty_Row
            exp_dt = row.Expiration_Date
            is_open  = 'to open' in sub
            is_close = (PAT_CLOSE in sub or 'expiration' in sub or 'assignment' in sub)
            is_long  = (is_open and qty > 0) or (is_close and qty < 0)
            event = {
                'date': row.Date, 'sub_type': row.Sub_Type,
                'strike': row.Strike_Price,
                'exp': pd.to_datetime(exp_dt).strftime('%d/%m/%y') if pd.notna(exp_dt) else '',
                'qty': qty, 'total': row.Total, 'cp': cp_type,
                'desc': str(row.Description)[:55], 'is_long': is_long,
            }
            if is_open:
                # A new open after the position went fully flat (short AND long)
                # more than the gap ago starts a fresh chain. Applies to long and
                # short opens alike, so a spread's long wing stays with its shorts
                # (they share the same order) instead of being stranded.
                if (last_close_date is not None and short_qty == 0 and long_qty == 0
                        and current_chain
                        and (row.Date - last_close_date).days > ROLL_CHAIN_GAP_DAYS):
                    chains.append(current_chain)
                    current_chain = []
                if qty < 0:
                    short_qty += abs(qty)   # short open — anchors the roll
                else:
                    long_qty += abs(qty)    # long wing (spread leg)
                current_chain.append(event)
                last_close_date = None
            elif is_close:
                if qty > 0:
                    short_qty = max(short_qty - abs(qty), 0)  # BTC / short expiry / assign
                else:
                    long_qty = max(long_qty - abs(qty), 0)    # STC / long-wing expiry
                current_chain.append(event)
                if short_qty == 0 and long_qty == 0:
                    last_close_date = row.Date

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
        return f'{max((exp_plain - reference_date.date()).days, 0)}d'
    except (ValueError, TypeError, AttributeError):
        return 'N/A'



# ── Full portfolio computation ───────────────────────────────────────────────

def _aggregate_campaign_pnl(
    all_campaigns: dict,
    use_lifetime: bool,
) -> tuple:
    """
    Aggregate P/L and capital figures from a campaign dict.
    Returns (closed_camp_pnl, open_premiums_banked, capital_deployed).

    Extracted to avoid duplication between compute_app_data() and the
    zero-cost exclusion filter in tastymechanics.py — a bug fix in one
    formula now propagates to both automatically.

    closed_camp_pnl      — realized_pnl() for all closed campaigns
    open_premiums_banked — realized_pnl() for all open campaigns
                           (premiums + dividends already banked but position still open)
    capital_deployed     — total_shares × blended_basis for open campaigns
                           (equity capital currently at risk)
    """
    closed_camp_pnl = sum(
        realized_pnl(c, use_lifetime)
        for camps in all_campaigns.values()
        for c in camps if c.status == 'closed'
    )
    open_premiums_banked = sum(
        realized_pnl(c, use_lifetime)
        for camps in all_campaigns.values()
        for c in camps if c.status == 'open'
    )
    capital_deployed = sum(
        c.total_shares * c.blended_basis
        for camps in all_campaigns.values()
        for c in camps if c.status == 'open'
    )
    return closed_camp_pnl, open_premiums_banked, capital_deployed


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
    df              = parsed.df
    split_events    = parsed.split_events
    zero_cost_rows  = parsed.zero_cost_rows
    # ── Open positions ledger ──────────────────────────────────────────────
    trade_df = df[df['Type'].isin(TRADE_TYPES)].copy()
    groups   = trade_df.groupby(
        ['Ticker', 'Symbol', 'Instrument Type', 'Call or Put',
         'Expiration Date', 'Strike Price', 'Root Symbol'], dropna=False)
    open_records = []
    for name, group in groups:
        net_qty = group['Net_Qty_Row'].sum()
        if abs(net_qty) > FIFO_EPSILON:
            open_records.append({
                'Ticker': name[0], 'Symbol': name[1],
                'Instrument Type': name[2], 'Call or Put': name[3],
                'Expiration Date': name[4], 'Strike Price': name[5],
                'Root Symbol': name[6], 'Net_Qty': net_qty,
                'Cost Basis': group['Total'].sum() * -1,
            })
    df_open = pd.DataFrame(open_records)

    # ── Wheel campaigns ────────────────────────────────────────────────────
    # Candidate = cumulative bought shares reach WHEEL_MIN_SHARES, not a single
    # 100-lot row — consistent with build_campaigns' odd-lot pool, which lets
    # accumulation entries (e.g. 60 + 60) start a campaign.
    _eq_rows  = df[equity_mask(df['Instrument Type'])]
    _buy_sums = (_eq_rows[_eq_rows['Net_Qty_Row'] > 0]
                 .groupby('Ticker')['Net_Qty_Row'].sum())
    wheel_tickers = [
        t for t in df['Ticker'].unique()
        if t != 'CASH' and _buy_sums.get(t, 0) >= WHEEL_MIN_SHARES
    ]

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
    # Per-campaign average acquisition cost per share — covered-call capital
    # base in _calculate_capital_risk.  total_cost / shares_acquired survives
    # campaign close (blended_basis is zeroed when shares hit 0).
    _camp_basis = {
        _t: [
            (_c.start_date, _c.end_date or latest_date,
             (_c.total_cost / _c.shares_acquired)
             if _c.shares_acquired > FIFO_EPSILON else _c.blended_basis)
            for _c in _camps
        ]
        for _t, _camps in all_campaigns.items()
    }
    closed_trades_df = build_closed_trades(
        df, campaign_windows=_camp_windows, campaign_basis=_camp_basis)

    # ── All-time P/L accounting ────────────────────────────────────────────
    closed_camp_pnl, open_premiums_banked, capital_deployed = _aggregate_campaign_pnl(
        all_campaigns, use_lifetime
    )

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


