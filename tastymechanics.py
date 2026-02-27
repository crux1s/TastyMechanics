import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta
from collections import defaultdict, deque
from models import Campaign, AppData, ParsedData

# ── Constants (all in config.py) ──────────────────────────────────────────────
from config import (
    OPT_TYPES, EQUITY_TYPE,
    TRADE_TYPES, MONEY_TYPES,
    SUB_SELL_OPEN, SUB_ASSIGNMENT, SUB_DIVIDEND, SUB_CREDIT_INT, SUB_DEBIT_INT,
    INCOME_SUB_TYPES, DEPOSIT_SUB_TYPES,
    PAT_CLOSE, PAT_EXPIR, PAT_ASSIGN, PAT_EXERCISE, PAT_CLOSING,
    WHEEL_MIN_SHARES, LEAPS_DTE_THRESHOLD, ROLL_CHAIN_GAP_DAYS,
    INDEX_STRIKE_THRESHOLD,
    SPLIT_DSC_PATTERNS, ZERO_COST_WARN_TYPES,
    REQUIRED_COLUMNS,
    ANN_RETURN_CAP,
)

# ── UI helpers & components (all in ui_components.py) ─────────────────────────
from ui_components import (
    xe,
    is_share_row, is_option_row,
    identify_pos_type, translate_readable, format_cost_basis, detect_strategy,
    fmt_dollar,
    color_win_rate, color_pnl_cell,
    _pnl_chip, _cmp_block, _dte_chip,
    _fmt_ann_ret, _style_ann_ret, _style_chain_row,
    _color_cash_row, _color_cash_total,
    chart_layout, _badge_inline_style, render_position_card,
)

# ── Ingestion (pure Python — no Streamlit dependency) ─────────────────────────
from ingestion import (
    clean_val, get_signed_qty,
    equity_mask, option_mask,
    detect_corporate_actions, apply_split_adjustments,
    validate_columns, parse_csv,
    CSVParseError,
)


# ── Analytics engine (pure Python — no Streamlit dependency) ──────────────────
from mechanics import (
    _iter_fifo_sells,
    calculate_windowed_equity_pnl,
    calculate_daily_realized_pnl,
    build_campaigns,
    effective_basis, realized_pnl, pure_options_pnl,
    build_closed_trades,
    build_option_chains,
    calc_dte,
    compute_app_data,
)

import json as _json
import os as _os

# ==========================================
# TastyMechanics v25.9
# ==========================================
#
# Changelog
# ---------
# v25.9 (2026-02-27)
#   - NEW: Win Rate & Avg P/L by DTE at Open charts (Trade Analysis tab).
#     Two-column view showing win rate and avg P/L per DTE bucket (0–7d through
#     61–90d). LEAPS excluded. Reveals where your edge is strongest by DTE.
#   - NEW: Rolling 90-day Capital Efficiency chart (All Trades tab).
#     13-week rolling P/L annualised against deployed capital. S&P 10% benchmark
#     line. Rising = capital working harder; flat/falling = sizing drift.
#   - NEW: Campaign P/L Waterfall chart (Wheel Campaigns tab, per campaign).
#     Shows Share Cost → Premiums → Dividends → Exit Proceeds → Net P/L as a
#     stacked waterfall. Makes the "house money" story visually obvious.
#   - FIX: Zero-cost basis exclusion toggle — sidebar opt-in to exclude
#     tickers with spin-off / ACATS $0-basis deliveries from all portfolio
#     P/L metrics (ROR, Capital Efficiency, Realized P/L). FIFO engine
#     unchanged; filtered at display layer only.
#   - FIX: Realized ROR now shows '∞ house money' when net_deposited < 0
#     (withdrawn more than deposited) and 'N/A' when net_deposited == 0,
#     rather than the misleading 0.0% previously returned in both cases.
#   - FIX: Capital Efficiency Score now shows 'N/A' when no capital is
#     deployed, rather than 0.0%.
#   - FIX: 5-day window changed to 7-day (Last 7 Days) so prior-period
#     comparison always aligns Mon-Sun vs Mon-Sun — equal trading days.
#
# v25.9 (2026-02-26)
#   - FIX: Assignment STO double-count — pre-purchase option that caused a
#     put assignment was being counted in both campaign premiums AND the
#     outside-window P/L bucket. Fixed: assignment STO stays solely in the
#     outside-window bucket. Verified against real account data.
#   - FIX: Windowed P/L and All Time P/L both missing dividends and interest.
#     Income now included in both window_realized_pnl and total_realized_pnl.
#   - FIX: Standalone ticker equity P/L replaced cash-flow approximation with
#     proper FIFO engine — correct for accounts with open equity positions.
#   - FIX: option_mask() typo introduced in v25.7 refactor (wrong function name
#     and wrong DataFrame at two call sites).
#   - TEST: 180-test suite (test_tastymechanics.py) added. All P/L figures,
#     campaign accounting, windowed views, and edge cases verified against
#     independently computed ground truth from raw CSV data.
#
# v25.8 (2026-02-26)
#   - REFACTOR: load_and_parse() returns ParsedData NamedTuple.
#     detect_corporate_actions() now runs exactly once.
#   - REFACTOR: equity_mask() / option_mask() vectorised helpers replace
#     scattered .str.strip() comparisons throughout.
#   - REFACTOR: AppData dataclass confirmed clean; all dict access migrated
#     to attribute access.
#
# v25.6 (2026-02-26)
#   - FIX: Stock splits (forward and reverse) handled end-to-end. Pre-split
#     lot sizes rescaled in FIFO engine; split REMOVAL rows no longer trigger
#     false P/L or duplicate campaigns. Warning banner shown at load time.
#   - FIX: Zero-cost share deliveries (spin-offs, ACATS transfers) flagged
#     with an amber warning noting the $0 basis will overstate P/L on sale.
#   - FIX: Timezone architecture unified — single UTC conversion in
#     load_and_parse(), naive datetimes everywhere downstream.
#   - FIX: Short equity FIFO — buy-to-cover now correctly matches the
#     originating short lot instead of treating proceeds as costless gain.
#   - FIX: Naked long options (LEAPS) no longer mislabelled as debit spreads.
#   - FIX: LEAPS excluded from ThetaGang DTE metrics (DTE > 90 threshold).
#   - FIX: Weekly bar chart hover negative formatting.
#   - REFACTOR: AppData dataclass, _iter_fifo_sells() shared FIFO core,
#     APP_VERSION constant, XSS prevention via xe() helper.
#
# v25.4 (2026-02-24)
#   - FIX: Pre-purchase options no longer credited to campaign effective basis.
#     Real impact: SMR basis corrected from $16.72 → $20.25/share.
#   - FIX: Prior period P/L double-counting.
#   - FIX: CSV validation, negative currency formatting, trade log date sort.
#   - NEW: How Closed column (Expired / Assigned / Exercised / Closed).
#   - NEW: Total Realized P/L by Week & Month charts.
#   - NEW: Window date label on all section headers.
#
# v25.3 (2026-02-23)
#   - NEW: Expiry alert strip (21-day lookahead, colour-coded urgency).
#   - NEW: Period comparison card (current vs prior window with deltas).
#   - NEW: Weekly / Monthly P/L bar charts.
#   - NEW: Open Positions card grid with strategy badges and DTE progress bars.
#   - UI: IBM Plex Sans + Mono typography, dark theme (#0a0e17).
# ==========================================

APP_VERSION = "v25.9"
st.set_page_config(page_title=f"TastyMechanics {APP_VERSION}", layout="wide")


def main():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

        .stApp { background-color: #0a0e17; color: #c9d1d9; font-family: 'IBM Plex Sans', sans-serif; }
        div[data-testid="stMetricValue"] { font-size: 1.4rem !important; color: #00cc96; font-family: 'IBM Plex Mono', monospace; font-weight: 600; }
        div[data-testid="stMetricLabel"] { color: #8b949e; font-size: 0.78rem !important; text-transform: uppercase; letter-spacing: 0.05em; }
        div[data-testid="stMetricDelta"] { font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem !important; }
        .stTable { font-size: 0.85rem !important; }
        [data-testid="stExpander"] { background: #111827; border-radius: 10px;
            border: 1px solid #1f2937; margin-bottom: 8px; }
        .stTabs [data-baseweb="tab-list"] { gap: 8px; border-bottom: 1px solid #1f2937; }
        .stTabs [data-baseweb="tab"] { background-color: #0f1520;
            border-radius: 6px 6px 0px 0px; padding: 10px 20px; font-size: 0.9rem; }
        .sync-header { color: #8b949e; font-size: 0.9rem;
            margin-top: -15px; margin-bottom: 25px; line-height: 1.5; }
        .highlight-range { color: #58a6ff; font-weight: 600; }

        /* Position cards and chart section titles use fully inline styles
           generated by render_position_card() and _badge_inline_style() —
           no CSS classes needed here. */
        </style>
    """, unsafe_allow_html=True)

    # ── Test snapshot (diagnostic only — never runs in production) ────────────────

    def _write_test_snapshot(df, all_campaigns, wheel_tickers, pure_options_tickers,
                             pure_opts_per_ticker, total_realized_pnl, window_realized_pnl,
                             prior_period_pnl, selected_period, closed_camp_pnl,
                             open_premiums_banked, pure_opts_pnl, _all_time_income,
                             _wheel_divs_in_camps, _w_opts, _eq_pnl, _w_div_int,
                             total_deposited, total_withdrawn, net_deposited,
                             capital_deployed, realized_ror, div_income, int_net,
                             latest_date):
        """
        Write app_snapshot.json for the test suite to compare against ground truth.
        Only called when TASTYMECHANICS_TEST=1 is set in the environment.
        Normal users never trigger this path.
        """
        def _campaign_snapshot(camps):
            return [dict(
                ticker=c.ticker, status=c.status,
                shares=c.total_shares, cost=round(c.total_cost, 4),
                basis=round(c.blended_basis, 4),
                premiums=round(c.premiums, 4),
                dividends=round(c.dividends, 4),
                exit_proceeds=round(c.exit_proceeds, 4),
                pnl=round(realized_pnl(c), 4),
            ) for c in camps]

        snapshot = {
            # ── Headline P/L figures ──
            'total_realized_pnl':    round(total_realized_pnl, 4),
            'window_realized_pnl':   round(window_realized_pnl, 4),
            'prior_period_pnl':      round(prior_period_pnl, 4),
            'selected_period':       selected_period,
            # ── Components ──
            'closed_camp_pnl':       round(closed_camp_pnl, 4),
            'open_premiums_banked':  round(open_premiums_banked, 4),
            'pure_opts_pnl':         round(pure_opts_pnl, 4),
            'all_time_income':       round(_all_time_income, 4),
            'wheel_divs_in_camps':   round(_wheel_divs_in_camps, 4),
            # ── Window components ──
            'w_opts_total':          round(_w_opts['Total'].sum(), 4),
            'w_eq_pnl':              round(_eq_pnl, 4),
            'w_div_int':             round(_w_div_int, 4),
            # ── Portfolio stats ──
            'total_deposited':       round(total_deposited, 4),
            'total_withdrawn':       round(total_withdrawn, 4),
            'net_deposited':         round(net_deposited, 4),
            'capital_deployed':      round(capital_deployed, 4),
            'realized_ror':          round(realized_ror, 4),
            'div_income':            round(div_income, 4),
            'int_net':               round(int_net, 4),
            # ── Campaigns ──
            'campaigns':             {t: _campaign_snapshot(c) for t, c in all_campaigns.items()},
            # ── Per-ticker options P/L ──
            'pure_opts_per_ticker':  {t: round(v, 4) for t, v in pure_opts_per_ticker.items()},
            'wheel_tickers':         wheel_tickers,
            'pure_options_tickers':  pure_options_tickers,
            # ── Open positions ──
            'open_positions': {
                t: {
                    'net_qty': round(
                        df[(df['Ticker'] == t) &
                           (df['Instrument Type'].str.strip() == 'Equity')]['Net_Qty_Row'].sum(), 4
                    )
                }
                for t in (wheel_tickers + [
                    t for t in df['Ticker'].unique()
                    if t not in wheel_tickers + ['CASH']
                    and df[(df['Ticker'] == t) &
                           (df['Instrument Type'].str.strip() == 'Equity')]['Net_Qty_Row'].sum() > 0.001
                ])
            },
            # ── Metadata ──
            'csv_rows':    len(df),
            'latest_date': latest_date.strftime('%Y-%m-%d'),
            'app_version': APP_VERSION,
        }
        out_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'app_snapshot.json')
        with open(out_path, 'w') as f:
            _json.dump(snapshot, f, indent=2)
        st.info(f'🧪 Test snapshot written → `{out_path}`')


    # ── MAIN APP ───────────────────────────────────────────────────────────────────

    st.title(f'📟 TastyMechanics {APP_VERSION}')

    with st.sidebar:
        st.header('⚙️ Data Control')
        uploaded_file = st.file_uploader('Upload TastyTrade History CSV', type='csv')
        st.markdown('---')
        st.header('🎯 Campaign Settings')
        use_lifetime = st.toggle('Show Lifetime "House Money"', value=False,
            help='If ON, combines ALL history for a ticker into one campaign. If OFF, resets breakeven every time shares hit zero.')

    if not uploaded_file:
        st.markdown(f"""
        <div style="max-width:760px;margin:2rem auto 0 auto;">

        <p style="color:#8b949e;font-size:0.95rem;line-height:1.7;">
        Upload your TastyTrade transaction history CSV using the sidebar to get started.
        All processing happens locally in your browser — your data is never sent anywhere.
        </p>

        <h3 style="color:#c9d1d9;margin-top:2rem;">How to export from TastyTrade</h3>
        <p style="color:#8b949e;font-size:0.95rem;line-height:1.7;">
        <b style="color:#c9d1d9;">History → Transactions → set date range → Download CSV</b><br>
        Export your <b style="color:#c9d1d9;">full account history</b> for accurate results —
        not just a recent window. FIFO cost basis for equity P/L requires all prior buy
        transactions to be present, even if the shares were purchased years ago. A partial
        export will produce incorrect basis and P/L figures for any position that has earlier
        lots outside the date range.
        </p>

        <h3 style="color:#c9d1d9;margin-top:2rem;">⚠️ Disclaimer</h3>
        <div style="background:#161b22;border:1px solid #f0883e55;border-radius:8px;padding:1.2rem 1.4rem;font-size:0.88rem;color:#8b949e;line-height:1.75;">

        <p style="margin:0 0 0.75rem 0;color:#c9d1d9;font-weight:600;">
        This tool is for personal record-keeping only. It is not financial advice.
        </p>

        <b style="color:#c9d1d9;">Known limitations — verify these manually:</b>
        <ul style="margin:0.5rem 0 0.75rem 0;padding-left:1.2rem;">
        <li><b style="color:#c9d1d9;">Covered calls assigned away</b> — if your shares are called away by assignment, verify the campaign closes and P/L is recorded correctly.</li>
        <li><b style="color:#c9d1d9;">Multiple assignments on the same ticker</b> — each new buy-in starts a new campaign. Blended basis across campaigns is not currently combined.</li>
        <li><b style="color:#c9d1d9;">Long options exercised by you</b> — exercising a long call or put into shares is untested. Check the resulting position and cost basis.</li>
        <li><b style="color:#c9d1d9;">Futures options delivery</b> — cash-settled futures options (like /MES, /ZS) are included in P/L totals, but in-the-money expiry into a futures contract is not handled.</li>
        <li><b style="color:#c9d1d9;">Stock splits</b> — forward and reverse splits are detected and adjusted, but TastyTrade-issued post-split option symbols are not automatically stitched to pre-split contracts.</li>
        <li><b style="color:#c9d1d9;">Spin-offs and zero-cost deliveries</b> — shares received at $0 cost (spin-offs, ACATS transfers) trigger a warning. Use the sidebar toggle to exclude those tickers from P/L metrics if the inflated basis distorts your numbers.</li>
        <li><b style="color:#c9d1d9;">Mergers and acquisitions</b> — if a ticker you hold is acquired or merged, the original campaign may be orphaned with no exit recorded. P/L for that position will be incomplete. Reconcile manually against your broker statement.</li>
        <li><b style="color:#c9d1d9;">Complex multi-leg structures</b> — PMCC, diagonals, calendars, and ratio spreads may not be classified correctly in the trade log. P/L totals are correct; labels may not be.</li>
        <li><b style="color:#c9d1d9;">Non-US accounts</b> — built and tested on a US TastyTrade account. Currency, tax treatment, and CSV format differences for other regions are unknown.</li>
        </ul>

        <p style="margin:0;color:#6e7681;">
        P/L figures are cash-flow based (what actually hit your account) and use FIFO cost basis
        for equity. They do not account for unrealised gains/losses, wash sale rules, or tax adjustments.
        Always reconcile against your official TastyTrade statements for tax purposes.
        </p>
        </div>

        <p style="color:#444d56;font-size:0.78rem;margin-top:1.5rem;text-align:center;">
        TastyMechanics {APP_VERSION} · Open source · MIT licence ·
        <a href="https://github.com/timluey/tastymechanics" style="color:#58a6ff;">GitHub</a>
        </p>

        </div>
        """, unsafe_allow_html=True)
        st.stop()


    # ── Cached data loading ────────────────────────────────────────────────────────

    @st.cache_data(show_spinner='📂 Loading CSV…')
    def load_and_parse(file_bytes: bytes) -> ParsedData:
        """
        Thin Streamlit cache wrapper around ingestion.parse_csv().
        Cached on raw file bytes — re-runs only when a new file is uploaded.
        The actual parsing logic lives in ingestion.py and is independently
        importable and testable without a running Streamlit server.
        """
        return parse_csv(file_bytes)


    @st.cache_data(show_spinner='⚙️ Building campaigns…')
    def build_all_data(_parsed: ParsedData, use_lifetime: bool) -> AppData:
        """
        Thin Streamlit cache wrapper around mechanics.compute_app_data().
        Cached separately from load_and_parse so that toggling Lifetime mode
        only re-runs campaign logic, not the CSV parse.
        _parsed is prefixed with _ so Streamlit skips hashing the full DataFrame
        (only the tiny use_lifetime bool is hashed). Hashing a 50k-row DataFrame
        on every rerun would cost more CPU than just running the math cold.
        """
        return compute_app_data(_parsed, use_lifetime)

    @st.cache_data(show_spinner=False)
    def get_daily_pnl(_df: pd.DataFrame) -> pd.DataFrame:
        """
        Daily realized P/L series — FIFO-correct, whole portfolio.
        Cached on the full df — re-runs only when a new file is uploaded.
        Window slicing is done downstream by the caller.
        _df is prefixed with _ so Streamlit skips hashing the full DataFrame.
        """
        return calculate_daily_realized_pnl(_df, _df['Date'].min())



    # ── Validate + load ────────────────────────────────────────────────────────────
    _raw_bytes = uploaded_file.getvalue()
    _missing   = validate_columns(_raw_bytes)
    if _missing:
        st.error(
            '❌ **This doesn\'t look like a TastyTrade history CSV.**\n\n'
            f'Missing columns: `{", ".join(sorted(_missing))}`\n\n'
            'Export from **TastyTrade → History → Transactions → Download CSV**.'
        )
        st.stop()

    try:
        _parsed = load_and_parse(_raw_bytes)
    except CSVParseError as e:
        st.error(f'❌ **{e}**')
        st.stop()
    except Exception as e:
        st.error(
            f'❌ **Unexpected error while parsing the file.**\n\n'
            f'Technical detail: `{type(e).__name__}: {e}`\n\n'
            'Please report this at GitHub if it persists.'
        )
        st.stop()

    df = _parsed.df
    if df.empty:
        st.error('❌ The uploaded CSV is empty — no transactions found.')
        st.stop()

    latest_date = df['Date'].max()

    # ── Unpack cached heavy computation ───────────────────────────────────────────
    _d = build_all_data(_parsed, use_lifetime)
    all_campaigns          = _d.all_campaigns
    wheel_tickers          = _d.wheel_tickers
    pure_options_tickers   = _d.pure_options_tickers
    closed_trades_df       = _d.closed_trades_df
    df_open                = _d.df_open
    closed_camp_pnl        = _d.closed_camp_pnl
    open_premiums_banked   = _d.open_premiums_banked
    capital_deployed       = _d.capital_deployed
    pure_opts_pnl          = _d.pure_opts_pnl
    extra_capital_deployed = _d.extra_capital_deployed
    pure_opts_per_ticker   = _d.pure_opts_per_ticker
    corp_split_events      = _d.split_events
    corp_zero_cost_rows    = _d.zero_cost_rows

    total_realized_pnl = closed_camp_pnl + open_premiums_banked + pure_opts_pnl
    capital_deployed  += extra_capital_deployed

    # Add all-time dividends + interest so that total_realized_pnl is computed on
    # the same basis as window_realized_pnl (which now includes _w_div_int).
    # Campaign accounting already includes wheel-ticker dividends via c.dividends,
    # but interest and non-wheel-ticker income are missing without this line.
    _all_time_income = df[df['Sub Type'].isin(INCOME_SUB_TYPES)]['Total'].sum()
    # Subtract wheel-ticker dividends already counted in campaigns to avoid double-counting
    _wheel_divs_in_camps = sum(
        c.dividends
        for camps in all_campaigns.values()
        for c in camps
    )
    total_realized_pnl += _all_time_income - _wheel_divs_in_camps

    # ── Zero-cost basis exclusion toggle ──────────────────────────────────────────
    # Shown in sidebar only when zero-cost deliveries were detected.
    # When enabled, all tickers with a $0-basis delivery are stripped from every
    # P/L metric so their artificially inflated gains don't pollute ROR / Cap Efficiency.
    # The FIFO engine and underlying data are unchanged — this is a display filter only.
    _zc_excluded: set[str] = set()
    if corp_zero_cost_rows:
        _zc_tickers_all = sorted({r['ticker'] for r in corp_zero_cost_rows})
        with st.sidebar:
            st.markdown('---')
            st.header('⚠️ Basis Warnings')
            _exclude_zc = st.toggle(
                'Exclude zero-cost tickers from P/L',
                value=False,
                help=(
                    'Tickers with spin-off / ACATS deliveries have a $0 cost basis. '
                    'When shares are sold, the full proceeds appear as P/L, overstating '
                    'Realized ROR and Capital Efficiency. Enable this to exclude those ' 
                    'tickers from all portfolio-wide metrics.'
                )
            )
            st.caption('Affected: ' + ', '.join(_zc_tickers_all))
        if _exclude_zc:
            _zc_excluded = set(_zc_tickers_all)

    if _zc_excluded:
        # Strip excluded tickers from every aggregated variable.
        # df stays intact for deposits/withdrawals — we only filter the P/L-relevant slices.
        df = df[~df['Ticker'].isin(_zc_excluded)].copy()

        # Campaigns
        all_campaigns  = {t: c for t, c in all_campaigns.items()  if t not in _zc_excluded}
        wheel_tickers  = [t for t in wheel_tickers          if t not in _zc_excluded]
        pure_options_tickers = [t for t in pure_options_tickers if t not in _zc_excluded]
        pure_opts_per_ticker = {t: v for t, v in pure_opts_per_ticker.items() if t not in _zc_excluded}

        # Recalculate aggregates from the filtered campaigns
        closed_camp_pnl      = sum(realized_pnl(c, use_lifetime)
                                   for camps in all_campaigns.values()
                                   for c in camps if c.status == 'closed')
        open_premiums_banked = sum(realized_pnl(c, use_lifetime)
                                   for camps in all_campaigns.values()
                                   for c in camps if c.status == 'open')
        capital_deployed     = sum(c.total_shares * c.blended_basis
                                   for camps in all_campaigns.values()
                                   for c in camps if c.status == 'open')
        pure_opts_pnl        = sum(pure_opts_per_ticker.values())

        # Recalculate pure-options tickers contribution (non-wheel equity/options)
        _pot_eq = 0.0
        _pot_cap = 0.0
        for _t in pure_options_tickers:
            _t_eq = df[equity_mask(df['Instrument Type']) & (df['Ticker'] == _t)].sort_values('Date')
            _pot_eq  += sum(p - c for _, p, c in _iter_fifo_sells(_t_eq))
            _pot_cap += _t_eq[_t_eq['Net_Qty_Row'] > 0]['Total'].apply(abs).sum()
        pure_opts_pnl  += _pot_eq
        capital_deployed += _pot_cap

        # Recompute dividends/income without excluded tickers
        _all_time_income     = df[df['Sub Type'].isin(INCOME_SUB_TYPES)]['Total'].sum()
        _wheel_divs_in_camps = sum(c.dividends for camps in all_campaigns.values() for c in camps)

        total_realized_pnl   = (closed_camp_pnl + open_premiums_banked + pure_opts_pnl
                                 + _all_time_income - _wheel_divs_in_camps)

        # Filter closed trades table
        if not closed_trades_df.empty:
            closed_trades_df = closed_trades_df[
                ~closed_trades_df['Ticker'].isin(_zc_excluded)
            ].copy()

    # ── Corporate action warnings ──────────────────────────────────────────────────────────────────────────
    # Shown once at load time; both lists are empty for the vast majority of users.
    if corp_split_events:
        for _ev in corp_split_events:
            _ratio = _ev['ratio']
            _fwd   = _ratio > 1
            _label = '%.0f:1 forward split' % _ratio if _fwd else '1:%.0f reverse split' % (1/_ratio)
            st.info(
                f"⚠️ **Stock split detected: {xe(_ev['ticker'])}** — {_label} on "
                f"{_ev['date'].strftime('%d/%m/%Y')} "
                f"({_ev['pre_qty']:.0f} → {_ev['post_qty']:.0f} shares). "
                "Pre-split lot sizes have been automatically rescaled in the FIFO engine "
                "so cost basis and P/L should be correct. "
                "Note: adjusted option symbols are a separate TastyTrade entry and are "
                "not automatically stitched to pre-split contracts.",
                icon=None
            )

    if corp_zero_cost_rows:
        _zc_tickers = sorted({r['ticker'] for r in corp_zero_cost_rows})
        _zc_lines   = [
            f"**{xe(r['ticker'])}** — {r['qty']:.0f} shares on "
            f"{r['date'].strftime('%d/%m/%Y')}: _{xe(r['description'])}_"
            for r in corp_zero_cost_rows
        ]
        st.warning(
            "⚠️ **Zero-cost share delivery detected** — the following positions "
            "were received with Total = $0, which typically means the cost basis was not "
            "transferred (spin-off, ACATS, merger conversion). "
            "These shares have been loaded with a $0/share cost basis, which will "
            "**overstate P/L** on eventual sale by the full proceeds amount. "
            "Check your broker statement for the correct allocated basis and note "
            "this as a limitation of the current data.\n\n"
            + "\n\n".join(_zc_lines)
        )

    # ── Expiry alert data (fast — from cached df_open) ────────────────────────────
    _expiry_alerts = []
    if not df_open.empty:
        _opts_open = df_open[option_mask(df_open['Instrument Type'])].copy()
        if not _opts_open.empty and _opts_open['Expiration Date'].notna().any():
            _opts_open['_exp_dt'] = pd.to_datetime(_opts_open['Expiration Date'], format='mixed', errors='coerce')
            _opts_open = _opts_open.dropna(subset=['_exp_dt'])
            _opts_open['_dte'] = (_opts_open['_exp_dt'] - latest_date).dt.days.clip(lower=0)
            _near = _opts_open[_opts_open['_dte'] <= 21].sort_values('_dte').copy()
            _near = _near.rename(columns={'_dte': 'dte_val', 'Strike Price': 'Strike_Price', 'Call or Put': 'Call_or_Put'})
            for row in _near.itertuples(index=False):
                cp   = str(row.Call_or_Put).upper()
                side = 'C' if 'CALL' in cp else 'P'
                _expiry_alerts.append({
                    'ticker': row.Ticker,
                    'label':  '%.0f%s' % (row.Strike_Price, side),
                    'dte':    int(row.dte_val),
                    'qty':    int(row.Net_Qty),
                })

    # ── Window-dependent slices (re-run on every window change, fast) ─────────────
    # ── Time window selector — top right ──────────────────────────────────────────
    time_options = ['YTD', 'Last 7 Days', 'Last Month', 'Last 3 Months', 'Half Year', '1 Year', 'All Time']
    _hdr_left, _hdr_right = st.columns([3, 1])
    with _hdr_right:
        selected_period = st.selectbox('Time Window', time_options, index=6, label_visibility='collapsed')

    if   selected_period == 'All Time':      start_date = df['Date'].min()
    elif selected_period == 'YTD':           start_date = pd.Timestamp(latest_date.year, 1, 1)
    elif selected_period == 'Last 7 Days':   start_date = latest_date - timedelta(days=7)
    elif selected_period == 'Last Month':    start_date = latest_date - timedelta(days=30)
    elif selected_period == 'Last 3 Months': start_date = latest_date - timedelta(days=90)
    elif selected_period == 'Half Year':     start_date = latest_date - timedelta(days=182)
    elif selected_period == '1 Year':        start_date = latest_date - timedelta(days=365)
    else:                                    start_date = df['Date'].min()  # fallback

    start_date = max(start_date, df['Date'].min())

    df_window = df[df['Date'] >= start_date].copy()
    window_label = '🗓 Window: %s → %s (%s)' % (
        start_date.strftime('%d/%m/%Y'), latest_date.strftime('%d/%m/%Y'), selected_period)

    with _hdr_left:
        st.markdown("""
            <div class='sync-header'>
                📡 <b>DATA SYNC:</b> %s UTC &nbsp;|&nbsp;
                📅 <b>WINDOW:</b> <span class='highlight-range'>%s</span> → %s (%s)
            </div>
        """ % (latest_date.strftime('%d/%m/%Y %H:%M'),
               start_date.strftime('%d/%m/%Y'),
               latest_date.strftime('%d/%m/%Y'),
               xe(selected_period)), unsafe_allow_html=True)

    window_trades_df = closed_trades_df[closed_trades_df['Close Date'] >= start_date].copy() \
        if not closed_trades_df.empty else pd.DataFrame()

    # Slice the cached all-time daily P/L series to the current window
    _daily_pnl_all = get_daily_pnl(df)
    _daily_pnl     = _daily_pnl_all[
        _daily_pnl_all['Date'] >= start_date
    ].copy()

    # ── Windowed P/L (respects time window selector) ──────────────────────────────
    # Options: sum all option cash flows in the window (credits + debits)
    # Equity: FIFO cost basis via calculate_windowed_equity_pnl() — oldest lot first,
    #         partial lot splits handled correctly, pre-window buys tracked
    # Income: dividends and net interest are real cash P/L, included here so
    #         windowed and all-time totals are computed on the same basis.
    _w_opts = df_window[df_window['Instrument Type'].isin(OPT_TYPES) &
                        (df_window['Type'].isin(TRADE_TYPES))]

    _eq_pnl       = calculate_windowed_equity_pnl(df, start_date)
    _w_div_int    = df_window[df_window['Sub Type'].isin(INCOME_SUB_TYPES)]['Total'].sum()

    window_realized_pnl = _w_opts['Total'].sum() + _eq_pnl + _w_div_int

    # ── Prior period P/L (for WoW / MoM comparison card) ─────────────────────────
    _window_span  = latest_date - start_date
    _prior_end    = start_date
    _prior_start  = _prior_end - _window_span
    _df_prior     = df[(df['Date'] >= _prior_start) & (df['Date'] < _prior_end)].copy()
    _prior_opts   = _df_prior[_df_prior['Instrument Type'].isin(OPT_TYPES) &
                               _df_prior['Type'].isin(TRADE_TYPES)]['Total'].sum()
    _prior_eq     = calculate_windowed_equity_pnl(df, _prior_start, end_date=_prior_end)
    _prior_div_int = _df_prior[_df_prior['Sub Type'].isin(INCOME_SUB_TYPES)]['Total'].sum()
    prior_period_pnl = _prior_opts + _prior_eq + _prior_div_int
    prior_period_trades = 0
    if not closed_trades_df.empty:
        prior_period_trades = closed_trades_df[
            (closed_trades_df['Close Date'] >= _prior_start) &
            (closed_trades_df['Close Date'] < _prior_end)
        ].shape[0]
    current_period_trades = 0
    if not closed_trades_df.empty:
        current_period_trades = closed_trades_df[
            closed_trades_df['Close Date'] >= start_date
        ].shape[0]

    # Income
    div_income = df_window[df_window['Sub Type']==SUB_DIVIDEND]['Total'].sum()
    int_net    = df_window[df_window['Sub Type'].isin([SUB_CREDIT_INT,SUB_DEBIT_INT])]['Total'].sum()
    deb_int    = df_window[df_window['Sub Type']==SUB_DEBIT_INT]['Total'].sum()
    reg_fees   = df_window[df_window['Sub Type']=='Balance Adjustment']['Total'].sum()

    # Portfolio stats
    total_deposited = df[df['Sub Type']=='Deposit']['Total'].sum()
    total_withdrawn = df[df['Sub Type']=='Withdrawal']['Total'].sum()
    net_deposited   = total_deposited + total_withdrawn
    first_date      = df['Date'].min()
    account_days    = (latest_date - first_date).days
    cash_balance    = df['Total'].cumsum().iloc[-1]
    margin_loan     = abs(cash_balance) if cash_balance < 0 else 0.0
    if net_deposited > 0:
        realized_ror = total_realized_pnl / net_deposited * 100
    elif net_deposited == 0:
        realized_ror = None          # undefined — no net deposits
    else:
        realized_ror = None          # negative net deposits — house money, ROR is infinite

    # ── Window label helper — used in section titles throughout ───────────────────
    _win_start_str = start_date.strftime('%d/%m/%Y')
    _win_end_str   = latest_date.strftime('%d/%m/%Y')
    _win_label     = (f'<span style="font-size:0.75rem;font-weight:400;color:#58a6ff;'
                      f'letter-spacing:0.02em;margin-left:8px;">'
                      f'{_win_start_str} → {_win_end_str} ({selected_period})</span>')
    # Plain text version for plotly chart titles (no HTML)
    _win_suffix    = f'  ·  {_win_start_str} → {_win_end_str}'

    # ── Debug export (for test suite comparison) ──────────────────────────────────
    if _os.environ.get('TASTYMECHANICS_TEST') == '1':
        _write_test_snapshot(
            df, all_campaigns, wheel_tickers, pure_options_tickers,
            pure_opts_per_ticker, total_realized_pnl, window_realized_pnl,
            prior_period_pnl, selected_period, closed_camp_pnl,
            open_premiums_banked, pure_opts_pnl, _all_time_income,
            _wheel_divs_in_camps, _w_opts, _eq_pnl, _w_div_int,
            total_deposited, total_withdrawn, net_deposited,
            capital_deployed, realized_ror, div_income, int_net,
            latest_date,
        )

    # ── TOP METRICS ────────────────────────────────────────────────────────────────

    st.markdown(f'### 📊 Portfolio Overview {_win_label}', unsafe_allow_html=True)
    _is_all_time    = selected_period == 'All Time'
    _is_short_window = selected_period in ['Last 7 Days', 'Last Month', 'Last 3 Months']
    _pnl_display    = total_realized_pnl if _is_all_time else window_realized_pnl
    if net_deposited > 0:
        _ror_display = _pnl_display / net_deposited * 100
    elif net_deposited == 0:
        _ror_display = None          # undefined — no net deposits in CSV
    else:
        _ror_display = None          # withdrawn more than deposited — house money
    # Capital Efficiency Score — annualised return on capital currently deployed
    # Uses window P/L and window days so it responds to time selector
    _window_days_int = max((latest_date - start_date).days, 1)
    cap_eff_score = (
        _pnl_display / capital_deployed / _window_days_int * 365 * 100
        if capital_deployed > 0 else None
    )

    m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
    m1.metric('Realized P/L',    fmt_dollar(_pnl_display))
    m1.caption('All cash actually banked — options P/L, share sales, premiums collected. ' + ('Full account history.' if _is_all_time else 'Filtered to selected time window.') + ' Unrealised share P/L not included.')
    if _ror_display is None:
        _ror_label  = '∞ house money' if net_deposited < 0 else 'N/A'
        _ror_help   = (
            'You have withdrawn more than you deposited — you are trading on profits. '
            'ROR vs deposits is mathematically undefined (infinite).'
            if net_deposited < 0 else
            'No net deposits found in this CSV. Export your full account history to see ROR.'
        )
    else:
        _ror_label = '%.1f%%' % _ror_display
        _ror_help  = None
    m2.metric('Realized ROR', _ror_label)
    if _ror_help:
        m2.caption(_ror_help)
    else:
        m2.caption('Realized P/L as a % of net deposits. How hard your deposited capital is working.')

    if _is_short_window:
        st.warning(
            '⚠️ **Short window — Realized P/L may be misleading.** '
            'This view shows raw cash flows in the selected window. '
            'If a trade was *opened* in a previous window and *closed* in this one, '
            'only the buyback cost appears here — the original credit is in an earlier window. '
            'This can make an actively managed period look like a loss even when the underlying trades are profitable. '
            '**All Time or YTD give the most reliable P/L picture.**'
        )
    _cap_label = '%.1f%%' % cap_eff_score if cap_eff_score is not None else 'N/A'
    m3.metric('Cap Efficiency', _cap_label)
    m3.caption('Annualised return on capital deployed in shares — (Window P/L ÷ Capital Deployed ÷ Window Days × 365). Responds to the time window selector: short windows will show higher or lower rates than the true long-run figure. Benchmark: S&P ~10%/yr.' if cap_eff_score is not None else 'No capital currently deployed in share positions.')
    m4.metric('Capital Deployed',fmt_dollar(capital_deployed))
    m4.caption('Cash tied up in open share positions (wheel campaigns + any fractional holdings). Options margin not included.')
    m5.metric('Margin Loan',     fmt_dollar(margin_loan))
    m5.caption('Negative cash balance — what you currently owe the broker. Zero is ideal unless deliberately leveraging.')
    m6.metric('Div + Interest',  fmt_dollar(div_income + int_net))
    m6.caption('Dividends received plus net interest (credit earned minus debit charged on margin). Filtered to selected time window.')
    m7.metric('Account Age',     '%d days' % account_days)
    m7.caption('Days since your first transaction. Useful context for how long your track record covers.')


    # ── Realized P/L Breakdown — inline chip line ─────────────────────────────────
    if _is_all_time:
        _breakdown_html = (
            _pnl_chip('Closed Wheel Campaigns', closed_camp_pnl) +
            _pnl_chip('Open Wheel Premiums', open_premiums_banked) +
            _pnl_chip('General Standalone Trading', pure_opts_pnl) +
            f'<span style="color:#4b5563;margin:0 6px;font-size:0.78rem;">·</span>'
            f'<span style="color:#8b949e;font-size:0.78rem;font-style:italic;">All Time</span>'
        )
    else:
        _w_opts_only = _w_opts['Total'].sum()
        _breakdown_html = (
            _pnl_chip('Wheel & Options Trading', _w_opts_only) +
            _pnl_chip('Equity Sales', _eq_pnl) +
            _pnl_chip('Div + Interest', div_income + int_net)
        )

    st.markdown(
        f'<div style="margin:-6px 0 10px 0;display:flex;flex-wrap:wrap;align-items:center;">'
        f'{_breakdown_html}</div>',
        unsafe_allow_html=True
    )



    # ── Period Comparison Card ─────────────────────────────────────────────────────
    if selected_period != 'All Time' and not _df_prior.empty:
        _pnl_delta  = _pnl_display - prior_period_pnl
        _delta_sign = '+' if _pnl_delta >= 0 else ''
        _delta_col  = '#00cc96' if _pnl_delta >= 0 else '#ef553b'
        _arrow      = '▲' if _pnl_delta >= 0 else '▼'
        _period_lbl = selected_period.replace('Last ','').replace('YTD','Year-to-date')

        _curr_wr, _prev_wr = 0.0, 0.0
        if not closed_trades_df.empty:
            _cw = closed_trades_df[closed_trades_df['Close Date'] >= start_date]
            _pw = closed_trades_df[(closed_trades_df['Close Date'] >= _prior_start) &
                                   (closed_trades_df['Close Date'] < _prior_end)]
            _curr_wr = _cw['Won'].mean() * 100 if not _cw.empty else 0.0
            _prev_wr = _pw['Won'].mean() * 100 if not _pw.empty else 0.0

        _curr_div = df_window[df_window['Sub Type']==SUB_DIVIDEND]['Total'].sum()
        _prev_div = _df_prior[_df_prior['Sub Type']==SUB_DIVIDEND]['Total'].sum()

        blocks = (
            _cmp_block('Realized P/L', _pnl_display, prior_period_pnl) +
            _cmp_block('Trades Closed', current_period_trades, prior_period_trades, is_pct=False) +
            _cmp_block('Win Rate', _curr_wr, _prev_wr, is_pct=True) +
            _cmp_block('Dividends', _curr_div, _prev_div)
        )

        st.markdown(
            f'<div style="background:linear-gradient(135deg,#111827,#0f1520);border:1px solid #1f2937;'
            f'border-radius:10px;padding:14px 18px;margin:0 0 20px 0;">'
            f'<div style="color:#8b949e;font-size:0.72rem;text-transform:uppercase;'
            f'letter-spacing:0.06em;margin-bottom:10px;">'
            f'📅 {selected_period} vs prior {_period_lbl}</div>'
            f'<div style="display:flex;flex-wrap:wrap;gap:0;">{blocks}</div>'
            f'</div>',
            unsafe_allow_html=True
        )

    # ── Shared derived slices — computed once, used by Tabs 1 and 2 ───────────────
    # all_cdf: closed trades filtered to current time window (falls back to all-time
    #          if the window contains no closed trades — avoids empty chart state).
    all_cdf    = window_trades_df if not window_trades_df.empty else closed_trades_df
    credit_cdf = all_cdf[all_cdf['Is Credit']].copy() if not all_cdf.empty else pd.DataFrame()
    has_credit = not credit_cdf.empty
    has_data   = not all_cdf.empty

    # ── TABS ───────────────────────────────────────────────────────────────────────
    tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs([
        '📡 Open Positions',
        '📈 Derivatives Performance',
        '🔬 Trade Analysis',
        '🎯 Wheel Campaigns',
        '🔍 All Trades',
        '💰 Deposits, Dividends & Fees'
    ])

    # ── Tab 0: Active Positions ────────────────────────────────────────────────────
    with tab0:
        st.subheader('📡 Open Positions')
        if df_open.empty:
            st.info('No active positions.')
        else:
            df_open['Status']  = df_open.apply(identify_pos_type, axis=1)
            df_open['Details'] = df_open.apply(translate_readable, axis=1)

            df_open['DTE'] = df_open.apply(lambda row: calc_dte(row, latest_date), axis=1)
            tickers_open = [t for t in sorted(df_open['Ticker'].unique()) if t != 'CASH']

            # Summary strip — count of positions and strategies
            n_options = df_open[option_mask(df_open['Instrument Type'])].shape[0]
            n_shares  = df_open[equity_mask(df_open['Instrument Type'])].shape[0]
            strategies = [detect_strategy(df_open[df_open['Ticker']==t]) for t in tickers_open]
            unique_strats = list(dict.fromkeys(strategies))  # preserve order

            summary_pills = ''.join(
                f'<span style="display:inline-block;background:rgba(88,166,255,0.1);border:1px solid rgba(88,166,255,0.2);'
                f'border-radius:20px;padding:2px 10px;font-size:0.75rem;color:#58a6ff;margin-right:6px;margin-bottom:6px;">{s}</span>'
                for s in unique_strats
            )
            st.markdown(
                f'<div style="margin-bottom:20px;color:#6b7280;font-size:0.85rem;">'
                f'<b style="color:#8b949e">{len(tickers_open)}</b> tickers &nbsp;·&nbsp; '
                f'<b style="color:#8b949e">{n_options}</b> option legs &nbsp;·&nbsp; '
                f'<b style="color:#8b949e">{n_shares}</b> share positions'
                f'</div>'
                f'<div style="margin-bottom:24px;">{summary_pills}</div>',
                unsafe_allow_html=True
            )

            # ── Expiry Alert Strip ─────────────────────────────────────────────
            if _expiry_alerts:
                _expiry_chips = ''.join(_dte_chip(a) for a in _expiry_alerts)
                st.markdown(
                    f'<div style="margin:-4px 0 16px 0;display:flex;flex-wrap:wrap;align-items:center;">'
                    f'<span style="color:#6b7280;font-size:0.75rem;margin-right:8px;">⏰ Expiring ≤21d</span>'
                    f'{_expiry_chips}</div>',
                    unsafe_allow_html=True
                )

            # 2-column card grid
            col_a, col_b = st.columns(2, gap='medium')
            for i, ticker in enumerate(tickers_open):
                t_df = df_open[df_open['Ticker'] == ticker].copy()
                card_html = render_position_card(ticker, t_df)
                if i % 2 == 0:
                    col_a.markdown(card_html, unsafe_allow_html=True)
                else:
                    col_b.markdown(card_html, unsafe_allow_html=True)

    # ── Tab 1: Derivatives Performance ────────────────────────────────────────────
    with tab1:
        if closed_trades_df.empty:
            st.info('No closed trades found.')
        else:
            st.info(window_label)
            st.markdown(f'#### 🎯 Premium Selling Scorecard {_win_label}', unsafe_allow_html=True)
            st.caption((
                'Credit trades only. '
                '**Win Rate** = %% of trades closed positive, regardless of size. '
                '**Median Capture %%** = typical %% of opening credit kept at close — TastyTrade targets 50%%. '
                '**Median Days Held** = typical time in a trade, resistant to outliers. '
                '**Median Ann. Return** = typical annualised return on capital at risk, capped at ±%d%% to prevent '
                '0DTE trades producing meaningless numbers — treat with caution on small sample sizes. '
                '**Med Premium/Day** = median credit-per-day across individual trades — your typical theta capture rate per trade, '
                'but skewed upward by short-dated trades where large credits are divided by very few days. '
                '**Banked $/Day** = realized P/L divided by window days — what you actually kept after all buybacks. '
                'The delta shows the gross credit rate for context — the gap between the two is your buyback cost. '
                'This is the number to compare against income needs or running costs.'
            ) % ANN_RETURN_CAP)
            dm1, dm2, dm3, dm4, dm5, dm6 = st.columns(6)
            if has_credit:
                total_credit_rcvd    = credit_cdf['Premium Rcvd'].sum()
                total_net_pnl_closed = credit_cdf['Net P/L'].sum()
                window_days = max((latest_date - start_date).days, 1)
                dm1.metric('Win Rate',           '%.1f%%' % (credit_cdf['Won'].mean() * 100))
                dm2.metric('Median Capture %',   '%.1f%%' % credit_cdf['Capture %'].median())
                dm3.metric('Median Days Held',   '%.0f'   % credit_cdf['Days Held'].median())
                dm4.metric('Median Ann. Return', '%.0f%%' % credit_cdf['Ann Return %'].median())
                dm5.metric('Med Premium/Day',    fmt_dollar(credit_cdf['Prem/Day'].median()))
                dm6.metric('Banked $/Day', fmt_dollar(total_net_pnl_closed / window_days),
                    delta='vs $%.2f gross' % (total_credit_rcvd / window_days),
                    delta_color='normal')

                # ── Row 2: Avg Winner / Avg Loser / Fees ──────────────────────
                _winners = all_cdf[all_cdf['Net P/L'] > 0]['Net P/L']
                _losers  = all_cdf[all_cdf['Net P/L'] < 0]['Net P/L']
                _avg_win  = _winners.mean() if not _winners.empty else 0.0
                _avg_loss = _losers.mean()  if not _losers.empty  else 0.0
                _ratio    = abs(_avg_win / _avg_loss) if _avg_loss != 0 else None  # None = no losing trades

                # Fees: commissions + fees on all option trades in window
                _w_option_rows = df_window[
                    df_window['Instrument Type'].isin(OPT_TYPES) &
                    df_window['Type'].isin(TRADE_TYPES)
                ]
                _total_fees = (_w_option_rows['Commissions'].apply(abs).sum() +
                               _w_option_rows['Fees'].apply(abs).sum())
                _fees_pct   = (_total_fees / abs(total_net_pnl_closed) * 100
                               if total_net_pnl_closed != 0 else 0.0)

                st.markdown('---')
                r1, r2, r3, r4, r5, r6 = st.columns(6)
                r1.metric('Avg Winner',   fmt_dollar(_avg_win))
                r1.caption('Mean P/L of all winning trades. Compare to Avg Loser — you want this number meaningfully larger.')
                r2.metric('Avg Loser',    fmt_dollar(_avg_loss))
                r2.caption('Mean P/L of all losing trades. A healthy system has avg loss smaller than avg win, even at high win rates.')
                r3.metric('Win/Loss Ratio', '%.2f×' % _ratio if _ratio is not None else '∞')
                r3.caption('Avg Winner ÷ Avg Loser. Above 1.0 means your wins are larger than your losses on average. TastyTrade targets >1.0 at lower win rates, or compensates with high win rate if below 1.0. ∞ = no losing trades in this window.')
                r4.metric('Total Fees',   fmt_dollar(_total_fees))
                r4.caption('Commissions + exchange fees on option trades in this window. The silent drag on every trade.')
                r5.metric('Fees % of P/L', '%.1f%%' % _fees_pct)
                r5.caption('Total fees as a percentage of net realized P/L. Under 10% is healthy. High on 0DTE or frequent small trades — fees eat a larger slice of smaller credits.')
                r6.metric('Fees/Trade',   fmt_dollar(_total_fees / len(all_cdf) if len(all_cdf) > 0 else 0))
                r6.caption('Average fee cost per closed trade. Useful for comparing cost efficiency across strategies — defined risk spreads cost more per trade than naked puts.')
            else:
                st.info('No closed credit trades in this window.')

            if has_data:
                st.markdown('---')
                col1, col2 = st.columns(2)
                with col1:
                    if has_credit:
                        bins   = [-999, 0, 25, 50, 75, 100, 999]
                        labels = ['Loss', '0–25%', '25–50%', '50–75%', '75–100%', '>100%']
                        credit_cdf['Bucket'] = pd.cut(credit_cdf['Capture %'], bins=bins, labels=labels)
                        bucket_df = credit_cdf.groupby('Bucket', observed=False).agg(
                            Trades=('Net P/L', 'count')).reset_index()
                        colors = ['#ef553b','#ffa421','#ffe066','#7ec8e3','#00cc96','#58a6ff']
                        fig_cap = px.bar(bucket_df, x='Bucket', y='Trades', color='Bucket',
                            color_discrete_sequence=colors, text='Trades')
                        fig_cap.update_traces(textposition='outside', textfont_size=11, marker_line_width=0)
                        _lay = chart_layout('Premium Capture % Distribution' + _win_suffix, height=320, margin_t=40)
                        _lay['showlegend'] = False
                        _lay['xaxis']['title'] = dict(text='Capture Bucket', font=dict(size=11))
                        _lay['yaxis']['title'] = dict(text='# Trades', font=dict(size=11))
                        fig_cap.update_layout(**_lay)
                        st.plotly_chart(fig_cap, width='stretch', config={'displayModeBar': False})

                with col2:
                    if has_credit:
                        type_df = credit_cdf.groupby('Type').agg(
                            Trades=('Won', 'count'),
                            Win_Rate=('Won', lambda x: x.mean()*100),
                            Med_Capture=('Capture %', 'median'),
                            Total_PNL=('Net P/L', 'sum'),
                            Avg_PremDay=('Prem/Day', 'mean'),
                            Med_Days=('Days Held', 'median'),
                            Med_DTE=('DTE Open', 'median'),
                        ).reset_index().round(1)
                        type_df.columns = ['Type','Trades','Win %','Capture %','P/L','Prem/Day','Days','DTE']
                        st.markdown(f'##### 📊 Call vs Put Performance {_win_label}', unsafe_allow_html=True)
                        st.caption('Do you perform better selling calls or puts? Skew, IV rank and stock direction all affect which side pays more. Mixed = multi-leg trades with both calls and puts (strangles, iron condors, lizards). Knowing your edge by type helps you lean into your strengths.')
                        st.dataframe(type_df.style.format({
                            'Win %': lambda x: '{:.1f}%'.format(x),
                            'Capture %': lambda x: '{:.1f}%'.format(x),
                            'P/L': fmt_dollar,
                            'Prem/Day': lambda x: '${:.2f}'.format(x),
                            'Days': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                            'DTE': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                        }).map(color_win_rate, subset=['Win %'])
                        .map(lambda v: 'color: #00cc96' if isinstance(v,(int,float)) and v>0
                            else ('color: #ef553b' if isinstance(v,(int,float)) and v<0 else ''),
                            subset=['P/L']),
                        width='stretch', hide_index=True)

                if has_data and has_credit:
                    strat_df = all_cdf.groupby('Trade Type').agg(
                        Trades=('Won','count'),
                        Win_Rate=('Won', lambda x: x.mean()*100),
                        Total_PNL=('Net P/L','sum'),
                        Med_Capture=('Capture %','median'),
                        Med_Days=('Days Held','median'),
                        Med_DTE=('DTE Open','median'),
                    ).reset_index().sort_values('Total_PNL', ascending=False).round(1)
                    strat_df.columns = ['Strategy','Trades','Win %','P/L','Capture %','Days','DTE']
                    st.markdown(f'##### 🧩 Defined vs Undefined Risk — by Strategy {_win_label}', unsafe_allow_html=True)
                    st.caption('All closed trades — credit and debit. Naked = undefined risk, higher premium. Spreads/Condors = defined max loss, less credit. Debit spreads show P/L but no capture % (not applicable). Are your defined-risk trades worth the premium you give up for the protection?')
                    st.dataframe(strat_df.style.format({
                        'Win %': lambda x: '{:.1f}%'.format(x),
                        'Capture %': lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                        'P/L': fmt_dollar,
                        'Days': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                        'DTE': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                    }).map(color_win_rate, subset=['Win %'])
                    .map(lambda v: 'color: #00cc96' if isinstance(v,(int,float)) and v>0
                        else ('color: #ef553b' if isinstance(v,(int,float)) and v<0 else ''),
                        subset=['P/L']),
                    width='stretch', hide_index=True)

                st.markdown('---')
                st.markdown(f'#### Performance by Ticker {_win_label}', unsafe_allow_html=True)
                st.caption((
                    'All closed trades — credit and debit — grouped by underlying. '
                    '**Win %%** counts any trade that closed positive, regardless of size. '
                    '**Total P/L** is your actual net result after all opens and closes on that ticker. '
                    '**Med Days** = median holding period across all trades. '
                    '**Med Capture %%** = median percentage of opening credit kept at close — credit trades only. '
                    'TastyTrade targets 50%% capture. '
                    '**Med Ann Ret %%** = median annualised return on capital at risk, capped at ±%d%%. '
                    '**Total Credit Rcvd** = gross cash received when opening credit trades.'
                ) % ANN_RETURN_CAP)

                all_by_ticker = all_cdf.groupby('Ticker').agg(
                    Trades=('Net P/L', 'count'),
                    Win_Rate=('Won', lambda x: x.mean()*100),
                    Total_PNL=('Net P/L', 'sum'),
                    Med_Days=('Days Held', 'median'),
                ).round(1)

                if has_credit:
                    credit_by_ticker = credit_cdf.groupby('Ticker').agg(
                        Med_Capture=('Capture %', 'median'),
                        Med_Ann=('Ann Return %', 'median'),
                        Total_Prem=('Premium Rcvd', 'sum'),
                    ).round(1)
                    ticker_df = all_by_ticker.join(credit_by_ticker, how='left').reset_index()
                else:
                    ticker_df = all_by_ticker.reset_index()
                    ticker_df['Med_Capture'] = None
                    ticker_df['Med_Ann']     = None
                    ticker_df['Total_Prem']  = None

                ticker_df = ticker_df.sort_values('Total_PNL', ascending=False)
                ticker_df.columns = ['Ticker','Trades','Win %','P/L','Days',
                                     'Capture %','Ann Ret %','Credit Rcvd']
                st.dataframe(
                    ticker_df.style.format({
                        'Win %': lambda x: '{:.1f}%'.format(x),
                        'P/L': fmt_dollar,
                        'Days': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                        'Capture %': lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                        'Ann Ret %': lambda v: '{:.0f}%'.format(v) if pd.notna(v) else '—',
                        'Credit Rcvd': lambda v: '${:.2f}'.format(v) if pd.notna(v) else '—'
                    }).map(color_win_rate, subset=['Win %'])
                    .map(color_pnl_cell, subset=['P/L']),
                    width='stretch', hide_index=True
                )


    # ── Tab 2: Trade Analysis ────────────────────────────────────────────────────
    with tab2:
        if closed_trades_df.empty:
            st.info('No closed trades found.')
        else:
            st.markdown(f'### 🔬 Trade Analysis {_win_label}', unsafe_allow_html=True)

            st.markdown('---')
            # ── ThetaGang Metrics ─────────────────────────────────────────────
            st.markdown(f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">🎯 ThetaGang Metrics {_win_label}</div>', unsafe_allow_html=True)
            st.markdown('<div style="font-size:0.8rem;color:#6b7280;margin-bottom:16px;line-height:1.5;">Metrics specific to theta selling strategy — management discipline, DTE behaviour, portfolio concentration, and win rate trend.</div>', unsafe_allow_html=True)

            if has_data and has_credit:
                _tg_opts = df_window[df_window['Instrument Type'].isin(OPT_TYPES)]
                _tg_closes = _tg_opts[_tg_opts['Sub Type'].str.lower().str.contains(PAT_CLOSING, na=False)].copy()
                _tg_closes['Exp'] = pd.to_datetime(_tg_closes['Expiration Date'], format='mixed', errors='coerce').dt.normalize()
                _tg_closes['DTE_close'] = (_tg_closes['Exp'] - _tg_closes['Date']).dt.days.clip(lower=0)

                # ── Separate LEAPS (DTE at open > 90) from short-premium trades ──────
                # LEAPS have fundamentally different holding periods and theta profiles.
                # Including them would inflate median DTE at open, skew the DTE-at-close
                # distribution, and pollute management rate — so ThetaGang metrics run
                # on short-premium trades only (DTE Open <= LEAPS_DTE_THRESHOLD).
                # LEAPS are surfaced below as a separate informational callout.
                _leaps_cdf  = credit_cdf[credit_cdf['DTE Open'] > LEAPS_DTE_THRESHOLD] \
                    if 'DTE Open' in credit_cdf.columns else pd.DataFrame()
                _short_cdf  = credit_cdf[credit_cdf['DTE Open'] <= LEAPS_DTE_THRESHOLD] \
                    if 'DTE Open' in credit_cdf.columns else credit_cdf

                # Also exclude LEAPS close events from _tg_closes for management rate / DTE chart.
                # A close event belongs to a LEAPS trade if its expiry was >90d away at open.
                # We approximate: if DTE_close > 90 at time of closing, it was almost certainly
                # opened with even more DTE and is a LEAPS position.
                _tg_closes_short = _tg_closes[
                    _tg_closes['DTE_close'].isna() | (_tg_closes['DTE_close'] <= LEAPS_DTE_THRESHOLD)
                ]

                # ── 1. Management Rate (short-premium only) ────────────────────
                _n_expired   = (_tg_closes_short['Sub Type'].str.lower().str.contains('expir|assign|exercise')).sum()
                _n_managed   = (_tg_closes_short['Sub Type'].str.lower().str.contains(PAT_CLOSE)).sum()
                _n_total_cls = len(_tg_closes_short)
                _mgmt_rate   = _n_managed / _n_total_cls * 100 if _n_total_cls > 0 else 0

                # ── 2. DTE at close distribution (short-premium only) ──────────
                _dte_valid = _tg_closes_short.dropna(subset=['DTE_close'])
                _med_dte_close = _dte_valid['DTE_close'].median() if not _dte_valid.empty else 0
                _med_dte_open  = _short_cdf['DTE Open'].median() \
                    if ('DTE Open' in _short_cdf.columns and not _short_cdf.empty) else 0

                # ── 3. Concentration score ─────────────────────────────────────
                _tg_sto = _tg_opts[_tg_opts['Sub Type'].str.lower() == SUB_SELL_OPEN]
                _by_tkr = _tg_sto.groupby('Ticker')['Total'].sum().sort_values(ascending=False)
                _total_prem_conc = _by_tkr.sum()
                _top3_pct = _by_tkr.head(3).sum() / _total_prem_conc * 100 if _total_prem_conc > 0 else 0
                _top3_names = ', '.join(_by_tkr.head(3).index.tolist())

                # ── 4. Rolling 10-trade win rate ──────────────────────────────
                _roll_cdf = all_cdf.sort_values('Close Date').copy()
                _roll_cdf['Rolling_WR'] = _roll_cdf['Won'].rolling(10, min_periods=5).mean() * 100

                # ── Metrics row ───────────────────────────────────────────────
                tg1, tg2, tg3, tg4 = st.columns(4)
                tg1.metric('Management Rate', '%.0f%%' % _mgmt_rate,
                    delta='%d managed, %d expired/assigned' % (_n_managed, _n_expired),
                    delta_color='off')
                tg1.caption('% of trades actively closed early vs left to expire/assign. TastyTrade targets closing at 50%% max profit — high management rate = good discipline. LEAPS excluded.')

                tg2.metric('Median DTE at Open', '%.0fd' % _med_dte_open)
                tg2.caption('Median days-to-expiry when trades were opened. TastyTrade targets 30–45 DTE for optimal theta decay curve. LEAPS (>90 DTE) excluded.')

                tg3.metric('Median DTE at Close', '%.0fd' % _med_dte_close)
                tg3.caption('Median days-to-expiry remaining when trades were closed. Closing around 14–21 DTE captures most theta while avoiding gamma risk. LEAPS excluded.')

                _conc_color = '⚠️' if _top3_pct > 60 else '✅'
                tg4.metric('Top 3 Concentration', '%.0f%%' % _top3_pct)
                tg4.caption(f'{_conc_color} {_top3_names} — top 3 tickers as %% of total premium collected. Above 60%% means heavy concentration risk if correlated.')

                # ── LEAPS callout (shown only when LEAPS trades exist in window) ──
                if not _leaps_cdf.empty:
                    _leaps_pnl    = _leaps_cdf['Net P/L'].sum()
                    _leaps_wr     = _leaps_cdf['Won'].mean() * 100
                    _leaps_count  = len(_leaps_cdf)
                    _leaps_tickers = ', '.join(sorted(_leaps_cdf['Ticker'].unique().tolist()))
                    _lc = '#00cc96' if _leaps_pnl >= 0 else '#ef553b'
                    _lpnl_str = fmt_dollar(_leaps_pnl)
                    st.markdown(
                        f'<div style="background:rgba(88,166,255,0.06);border:1px solid rgba(88,166,255,0.2);'
                        f'border-radius:8px;padding:10px 16px;margin:12px 0 0 0;font-size:0.82rem;color:#8b949e;">'
                        f'<span style="color:#58a6ff;font-weight:600;">📅 LEAPS detected</span>'
                        f' &nbsp;·&nbsp; {_leaps_count} trade(s) with DTE &gt; {LEAPS_DTE_THRESHOLD}d at open'
                        f' &nbsp;·&nbsp; Tickers: <span style="color:#c9d1d9;">{xe(_leaps_tickers)}</span>'
                        f' &nbsp;·&nbsp; Net P/L: <span style="color:{_lc};font-family:monospace;">{_lpnl_str}</span>'
                        f' &nbsp;·&nbsp; Win Rate: <span style="color:#c9d1d9;">{_leaps_wr:.0f}%</span>'
                        f' &nbsp;·&nbsp; <span style="font-style:italic;">Excluded from ThetaGang metrics above to avoid skewing DTE stats.</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

                # ── DTE distribution chart ─────────────────────────────────────
                st.markdown('---')
                _tg_col1, _tg_col2 = st.columns(2)

                with _tg_col1:
                    if not _dte_valid.empty:
                        _dte_bins   = [-1, 0, 7, 14, 21, 30, 999]
                        _dte_labels = ['0 (expired)', '1–7d', '8–14d', '15–21d', '22–30d', '>30d']
                        _dte_valid = _dte_valid.copy()  # already filtered to short-premium by _tg_closes_short above
                        _dte_valid['Bucket'] = pd.cut(_dte_valid['DTE_close'], bins=_dte_bins, labels=_dte_labels)
                        _dte_dist = _dte_valid['Bucket'].value_counts().reindex(_dte_labels, fill_value=0).reset_index()
                        _dte_dist.columns = ['DTE Bucket', 'Trades']
                        # Highlight the target zone (14-21d) in blue, rest grey
                        _dte_colors = ['#58a6ff' if b in ['8–14d','15–21d'] else '#30363d' for b in _dte_labels]
                        _fig_dte = go.Figure(go.Bar(
                            x=_dte_dist['DTE Bucket'], y=_dte_dist['Trades'],
                            marker_color=_dte_colors, marker_line_width=0,
                            text=_dte_dist['Trades'], textposition='outside',
                            textfont=dict(size=11, family='IBM Plex Mono'),
                            hovertemplate='%{x}<br><b>%{y} trades</b><extra></extra>'
                        ))
                        _dte_lay = chart_layout('DTE at Close Distribution' + _win_suffix, height=300, margin_t=40)
                        _dte_lay['showlegend'] = False
                        _dte_lay['xaxis']['title'] = dict(text='DTE Remaining at Close', font=dict(size=11))
                        _dte_lay['yaxis']['title'] = dict(text='# Trades', font=dict(size=11))
                        _fig_dte.update_layout(**_dte_lay)
                        st.plotly_chart(_fig_dte, width='stretch', config={'displayModeBar': False})
                        st.caption('🔵 Blue = TastyTrade target close zone (8–21 DTE remaining at close). Grey = outside target. Closing in this window captures most theta while reducing gamma risk.')

                with _tg_col2:
                    if not _roll_cdf.empty and _roll_cdf['Rolling_WR'].notna().sum() >= 2:
                        _fig_rwr = go.Figure()
                        _fig_rwr.add_hline(y=50, line_dash='dash', line_color='rgba(255,255,255,0.15)', line_width=1)
                        _fig_rwr.add_trace(go.Scatter(
                            x=_roll_cdf['Close Date'], y=_roll_cdf['Rolling_WR'],
                            mode='lines', line=dict(color='#58a6ff', width=2),
                            fill='tozeroy', fillcolor='rgba(88,166,255,0.08)',
                            hovertemplate='%{x|%d/%m/%y}<br>Win Rate: <b>%{y:.1f}%</b><extra></extra>'
                        ))
                        _fig_rwr.add_hline(y=_roll_cdf['Won'].mean()*100,
                            line_dash='dot', line_color='#ffa421', line_width=1.5,
                            annotation_text='avg %.0f%%' % (_roll_cdf['Won'].mean()*100),
                            annotation_position='bottom right',
                            annotation_font=dict(color='#ffa421', size=11))
                        _rwr_lay = chart_layout('Rolling Win Rate · 10-trade window' + _win_suffix, height=300, margin_t=40)
                        _rwr_lay['yaxis']['ticksuffix'] = '%'
                        _rwr_lay['yaxis']['range'] = [0, 105]
                        _fig_rwr.update_layout(**_rwr_lay)
                        st.plotly_chart(_fig_rwr, width='stretch', config={'displayModeBar': False})
                        st.caption('Rolling 10-trade win rate over time. Amber = overall average. A rising trend means your edge is improving.')

            st.markdown('---')
            # ── Week-over-Week / Month-over-Month P/L bar chart ───────────────
            st.markdown(f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">📅 Options P/L by Week &amp; Month {_win_label}</div>', unsafe_allow_html=True)
            st.markdown('<div style="font-size:0.8rem;color:#6b7280;margin-bottom:12px;line-height:1.5;"><b style="color:#58a6ff;">Options trades only</b> — net P/L from closed equity &amp; futures options, grouped by the date the trade closed. Excludes share sales, dividends, and interest. See the <b>All Trades</b> tab for total portfolio P/L by period.</div>', unsafe_allow_html=True)

            _period_df = all_cdf.copy()
            _period_df['CloseDate'] = pd.to_datetime(_period_df['Close Date'])
            _period_df['Week']  = _period_df['CloseDate'].dt.to_period('W').apply(lambda p: p.start_time)
            _period_df['Month'] = _period_df['CloseDate'].dt.to_period('M').apply(lambda p: p.start_time)

            _pcol1, _pcol2 = st.columns(2)

            with _pcol1:
                _weekly = _period_df.groupby('Week')['Net P/L'].sum().reset_index()
                _weekly['Week'] = pd.to_datetime(_weekly['Week'])
                _weekly['Colour'] = _weekly['Net P/L'].apply(lambda x: '#00cc96' if x >= 0 else '#ef553b')
                _fig_wk = go.Figure()
                _fig_wk.add_trace(go.Bar(
                    x=_weekly['Week'], y=_weekly['Net P/L'],
                    marker_color=_weekly['Colour'],
                    marker_line_width=0,
                    customdata=[fmt_dollar(v) for v in _weekly['Net P/L']],
                    hovertemplate='Week of %{x|%d %b}<br><b>%{customdata}</b><extra></extra>'
                ))
                _fig_wk.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
                _wk_lay = chart_layout('Weekly P/L' + _win_suffix, height=280, margin_t=36)
                _wk_lay['yaxis']['tickprefix'] = '$'
                _wk_lay['yaxis']['tickformat'] = ',.0f'
                _wk_lay['bargap'] = 0.25
                _fig_wk.update_layout(**_wk_lay)
                st.plotly_chart(_fig_wk, width='stretch', config={'displayModeBar': False})

            with _pcol2:
                _monthly = _period_df.groupby('Month')['Net P/L'].sum().reset_index()
                _monthly['Month'] = pd.to_datetime(_monthly['Month'])
                _monthly['Colour'] = _monthly['Net P/L'].apply(lambda x: '#00cc96' if x >= 0 else '#ef553b')
                _monthly['Label'] = _monthly['Month'].dt.strftime('%b %Y')
                _fig_mo = go.Figure()
                _fig_mo.add_trace(go.Bar(
                    x=_monthly['Label'], y=_monthly['Net P/L'],
                    marker_color=_monthly['Colour'],
                    marker_line_width=0,
                    text=[fmt_dollar(v, 0) for v in _monthly['Net P/L']],
                    customdata=[fmt_dollar(v) for v in _monthly['Net P/L']],
                    textposition='outside',
                    textfont=dict(size=10, family='IBM Plex Mono', color='#8b949e'),
                    hovertemplate='%{x}<br><b>%{customdata}</b><extra></extra>'
                ))
                _fig_mo.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
                _mo_lay = chart_layout('Monthly P/L' + _win_suffix, height=280, margin_t=36)
                _mo_lay['yaxis']['tickprefix'] = '$'
                _mo_lay['yaxis']['tickformat'] = ',.0f'
                _mo_lay['bargap'] = 0.35
                _fig_mo.update_layout(**_mo_lay)
                st.plotly_chart(_fig_mo, width='stretch', config={'displayModeBar': False})

            st.markdown('---')
            cum_df = all_cdf.sort_values('Close Date').copy()
            cum_df['Cumulative P/L'] = cum_df['Net P/L'].cumsum()
            final_pnl = cum_df['Cumulative P/L'].iloc[-1]
            eq_color = '#00cc96' if final_pnl >= 0 else '#ef553b'
            eq_fill  = 'rgba(0,204,150,0.12)' if final_pnl >= 0 else 'rgba(239,85,59,0.12)'
            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(
                x=cum_df['Close Date'], y=cum_df['Cumulative P/L'],
                mode='lines', line=dict(color=eq_color, width=2),
                fill='tozeroy', fillcolor=eq_fill,
                hovertemplate='%{x|%d/%m/%y}<br><b>$%{y:,.2f}</b><extra></extra>'
            ))
            fig_eq.add_hline(y=0, line_color='rgba(255,255,255,0.1)', line_width=1)
            _eq_lay = chart_layout('Cumulative Realized P/L' + _win_suffix, height=300, margin_t=40)
            _eq_lay['yaxis']['tickprefix'] = '$'
            _eq_lay['yaxis']['tickformat'] = ',.0f'
            fig_eq.update_layout(**_eq_lay)
            st.plotly_chart(fig_eq, width='stretch', config={'displayModeBar': False})

            if has_credit:
                roll_df = credit_cdf.sort_values('Close Date').copy()
                roll_df['Rolling Capture'] = roll_df['Capture %'].rolling(10, min_periods=1).mean()
                fig_cap2 = go.Figure()
                fig_cap2.add_trace(go.Scatter(
                    x=roll_df['Close Date'], y=roll_df['Rolling Capture'],
                    mode='lines', line=dict(color='#58a6ff', width=2),
                    fill='tozeroy', fillcolor='rgba(88,166,255,0.08)',
                    hovertemplate='%{x|%d/%m/%y}<br>Capture: <b>%{y:.1f}%</b><extra></extra>'
                ))
                fig_cap2.add_hline(y=50, line_dash='dash', line_color='#ffa421', line_width=1.5,
                    annotation_text='50% target', annotation_position='bottom right',
                    annotation_font=dict(color='#ffa421', size=11))
                _cap2_lay = chart_layout('Rolling Avg Capture % · 10-trade window' + _win_suffix, height=260, margin_t=40)
                _cap2_lay['yaxis']['ticksuffix'] = '%'
                fig_cap2.update_layout(**_cap2_lay)
                st.plotly_chart(fig_cap2, width='stretch', config={'displayModeBar': False})

            st.markdown('---')
            st.markdown(f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">📊 Win / Loss Distribution {_win_label}</div>', unsafe_allow_html=True)
            st.markdown('<div style="font-size:0.8rem;color:#6b7280;margin-bottom:12px;line-height:1.5;">Each bar is one trade. A healthy theta engine shows many small green bars near zero with losses contained — fat red tails mean outsized losses relative to wins.</div>', unsafe_allow_html=True)
            _hist_df = all_cdf.copy()
            _hist_df['Colour'] = _hist_df['Net P/L'].apply(lambda x: 'Win' if x >= 0 else 'Loss')
            _fig_hist = px.histogram(
                _hist_df, x='Net P/L', color='Colour',
                color_discrete_map={'Win': '#00cc96', 'Loss': '#ef553b'},
                nbins=40,
                labels={'Net P/L': 'Trade P/L ($)', 'count': 'Trades'},
                barmode='overlay', opacity=0.8
            )
            _fig_hist.add_vline(x=0, line_color='rgba(255,255,255,0.2)', line_width=1)
            _fig_hist.add_vline(
                x=all_cdf['Net P/L'].median(),
                line_dash='dot', line_color='#ffa421', line_width=1.5,
                annotation_text='median $%.0f' % all_cdf['Net P/L'].median(),
                annotation_position='top right',
                annotation_font=dict(color='#ffa421', size=11)
            )
            _hist_lay = chart_layout(height=300, margin_t=20)
            _hist_lay['legend'] = dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1,
                bgcolor='rgba(0,0,0,0)', borderwidth=0, font=dict(size=11))
            _hist_lay['xaxis']['tickprefix'] = '$'
            _hist_lay['xaxis']['tickformat'] = ',.0f'
            _fig_hist.update_layout(**_hist_lay)
            st.plotly_chart(_fig_hist, width='stretch', config={'displayModeBar': False})

            st.markdown('---')
            # ── Win Rate by DTE Bucket ────────────────────────────────────────
            st.markdown(f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">🎯 Win Rate &amp; P/L by DTE at Open {_win_label}</div>', unsafe_allow_html=True)
            st.markdown('<div style="font-size:0.8rem;color:#6b7280;margin-bottom:12px;line-height:1.5;">Where is your edge strongest? Win rate and average P/L split by days-to-expiry when the trade was opened. Use this to tune which DTE range to target — your best bucket is the one with high win rate <i>and</i> positive average P/L.</div>', unsafe_allow_html=True)
            if has_credit and 'DTE Open' in all_cdf.columns:
                _dte_open_df = all_cdf[all_cdf['DTE Open'].notna()].copy()
                _dte_open_df = _dte_open_df[_dte_open_df['DTE Open'] <= LEAPS_DTE_THRESHOLD]  # exclude LEAPS
                if not _dte_open_df.empty:
                    _dte_open_bins   = [0, 7, 14, 21, 30, 45, 60, LEAPS_DTE_THRESHOLD]
                    _dte_open_labels = ['0–7d', '8–14d', '15–21d', '22–30d', '31–45d', '46–60d', '61–90d']
                    _dte_open_df['DTE Bucket'] = pd.cut(_dte_open_df['DTE Open'],
                        bins=_dte_open_bins, labels=_dte_open_labels, include_lowest=True)
                    _dte_grp = _dte_open_df.groupby('DTE Bucket', observed=True).agg(
                        Trades=('Won', 'count'),
                        Win_Rate=('Won', 'mean'),
                        Avg_PnL=('Net P/L', 'mean'),
                        Total_PnL=('Net P/L', 'sum'),
                    ).reset_index()
                    _dte_grp = _dte_grp[_dte_grp['Trades'] > 0].copy()
                    _dte_grp['Win_Rate_Pct'] = _dte_grp['Win_Rate'] * 100

                    _dcol1, _dcol2 = st.columns(2)
                    with _dcol1:
                        # Win rate bar chart coloured green/red by threshold
                        _wr_colors = ['#00cc96' if w >= 50 else '#ef553b' for w in _dte_grp['Win_Rate_Pct']]
                        _fig_dtewr = go.Figure(go.Bar(
                            x=_dte_grp['DTE Bucket'].astype(str),
                            y=_dte_grp['Win_Rate_Pct'],
                            marker_color=_wr_colors, marker_line_width=0,
                            text=['%.0f%% (%d)' % (w, t) for w, t in zip(_dte_grp['Win_Rate_Pct'], _dte_grp['Trades'])],
                            textposition='outside',
                            textfont=dict(size=10, family='IBM Plex Mono'),
                            hovertemplate='%{x}<br>Win Rate: <b>%{y:.1f}%</b><extra></extra>'
                        ))
                        _fig_dtewr.add_hline(y=50, line_dash='dash',
                            line_color='rgba(255,255,255,0.2)', line_width=1)
                        _dtewr_lay = chart_layout('Win Rate by DTE at Open (LEAPS excluded)' + _win_suffix, height=300, margin_t=40)
                        _dtewr_lay['showlegend'] = False
                        _dtewr_lay['yaxis']['ticksuffix'] = '%'
                        _dtewr_lay['yaxis']['range'] = [0, 115]
                        _dtewr_lay['xaxis']['title'] = dict(text='DTE at Open', font=dict(size=11))
                        _fig_dtewr.update_layout(**_dtewr_lay)
                        st.plotly_chart(_fig_dtewr, width='stretch', config={'displayModeBar': False})
                        st.caption('Green = win rate ≥ 50%. Format: 82% (14) = 82% win rate on 14 trades. Dashed line = 50% threshold. Buckets with fewer than 5 trades should be treated with caution.')

                    with _dcol2:
                        # Average P/L per trade by DTE bucket
                        _pnl_colors = ['#00cc96' if p >= 0 else '#ef553b' for p in _dte_grp['Avg_PnL']]
                        _fig_dtepnl = go.Figure(go.Bar(
                            x=_dte_grp['DTE Bucket'].astype(str),
                            y=_dte_grp['Avg_PnL'],
                            marker_color=_pnl_colors, marker_line_width=0,
                            text=[fmt_dollar(p, 0) for p in _dte_grp['Avg_PnL']],
                            textposition='outside',
                            textfont=dict(size=10, family='IBM Plex Mono'),
                            hovertemplate='%{x}<br>Avg P/L: <b>$%{y:,.2f}</b><extra></extra>'
                        ))
                        _fig_dtepnl.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
                        _dtepnl_lay = chart_layout('Avg P/L per Trade by DTE at Open' + _win_suffix, height=300, margin_t=40)
                        _dtepnl_lay['showlegend'] = False
                        _dtepnl_lay['yaxis']['tickprefix'] = '$'
                        _dtepnl_lay['yaxis']['tickformat'] = ',.0f'
                        _dtepnl_lay['xaxis']['title'] = dict(text='DTE at Open', font=dict(size=11))
                        _fig_dtepnl.update_layout(**_dtepnl_lay)
                        st.plotly_chart(_fig_dtepnl, width='stretch', config={'displayModeBar': False})
                        st.caption('Average realized P/L per trade in each DTE bucket. Your sweet spot is the bucket with both high win rate and positive avg P/L.')
                else:
                    st.info('Not enough trades with DTE data in this window.')

            st.markdown('---')
            st.markdown(f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">🗓 P/L by Ticker &amp; Month {_win_label}</div>', unsafe_allow_html=True)
            st.markdown('<div style="font-size:0.8rem;color:#6b7280;margin-bottom:12px;line-height:1.5;">Net P/L per ticker per calendar month (by close date). Green = profitable, red = losing. Intensity shows size. Grey = no closed trades that month.</div>', unsafe_allow_html=True)
            _hm_df = all_cdf.copy()
            _hm_df['Month']     = pd.to_datetime(_hm_df['Close Date']).dt.strftime('%b %Y')
            _hm_df['MonthSort'] = pd.to_datetime(_hm_df['Close Date']).dt.strftime('%Y-%m')
            _hm_pivot = _hm_df.groupby(['Ticker','MonthSort','Month'])['Net P/L'].sum().reset_index()
            _months_sorted  = sorted(_hm_pivot['MonthSort'].unique())
            _month_labels   = [_hm_pivot[_hm_pivot['MonthSort']==m]['Month'].iloc[0] for m in _months_sorted]
            _tickers_sorted = sorted(_hm_pivot['Ticker'].unique(),
                key=lambda t: _hm_pivot[_hm_pivot['Ticker']==t]['Net P/L'].sum(), reverse=True)
            _z = []; _text = []
            for tkr in _tickers_sorted:
                row_z, row_t = [], []
                for ms in _months_sorted:
                    val = _hm_pivot[(_hm_pivot['Ticker']==tkr) & (_hm_pivot['MonthSort']==ms)]['Net P/L'].sum()
                    row_z.append(val if val != 0 else None)
                    row_t.append('$%.0f' % val if val != 0 else '')
                _z.append(row_z); _text.append(row_t)
            _fig_hm = go.Figure(data=go.Heatmap(
                z=_z, x=_month_labels, y=_tickers_sorted,
                text=_text, texttemplate='%{text}', textfont=dict(size=10, family='IBM Plex Mono'),
                colorscale=[
                    [0.0,  '#7f1d1d'], [0.35, '#ef553b'],
                    [0.5,  '#141c2e'],
                    [0.65, '#00cc96'], [1.0,  '#004d3a'],
                ],
                zmid=0, showscale=True,
                colorbar=dict(title=dict(text='P/L', side='right'), tickformat='$,.0f',
                    tickfont=dict(size=10, family='IBM Plex Mono'), len=0.9),
                hoverongaps=False,
                hovertemplate='<b>%{y}</b> — %{x}<br>P/L: <b>$%{z:,.2f}</b><extra></extra>',
            ))
            _hm_lay = chart_layout(height=max(300, len(_tickers_sorted) * 32 + 60), margin_t=16)
            _hm_lay['xaxis'] = dict(side='top', gridcolor='rgba(0,0,0,0)', tickfont=dict(size=11))
            _hm_lay['yaxis'] = dict(autorange='reversed', gridcolor='rgba(0,0,0,0)',
                tickfont=dict(size=11, family='IBM Plex Mono'))
            _fig_hm.update_layout(**_hm_lay)
            st.plotly_chart(_fig_hm, width='stretch', config={'displayModeBar': False})

            st.markdown('---')
            bcol, wcol = st.columns(2)
            with bcol:
                st.markdown(f'##### 🏆 Best 5 Trades {_win_label}', unsafe_allow_html=True)
                best = all_cdf.nlargest(5, 'Net P/L')[['Ticker','Trade Type','Type','Days Held','Premium Rcvd','Net P/L']].copy()
                best.columns = ['Ticker','Strategy','C/P','Days','Credit','P/L']
                st.dataframe(best.style.format({
                    'Credit': lambda x: '${:.2f}'.format(x),
                    'P/L': lambda x: '${:.2f}'.format(x)
                }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)
            with wcol:
                st.markdown(f'##### 💀 Worst 5 Trades {_win_label}', unsafe_allow_html=True)
                worst = all_cdf.nsmallest(5, 'Net P/L')[['Ticker','Trade Type','Type','Days Held','Premium Rcvd','Net P/L']].copy()
                worst.columns = ['Ticker','Strategy','C/P','Days','Credit','P/L']
                st.dataframe(worst.style.format({
                    'Credit': lambda x: '${:.2f}'.format(x),
                    'P/L': lambda x: '${:.2f}'.format(x)
                }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)

            with st.expander(f'📋 Full Closed Trade Log  ·  {_win_start_str} → {_win_end_str}', expanded=False):
                log = all_cdf[['Ticker','Trade Type','Type','Close Type','Open Date','Close Date',
                               'Days Held','Premium Rcvd','Net P/L','Capture %',
                               'Capital Risk','Ann Return %']].copy()
                # Keep as datetime — do NOT strftime. Streamlit column_config renders
                # them as dates and sorts chronologically, not alphabetically.
                log['Open Date']  = pd.to_datetime(log['Open Date'])
                log['Close Date'] = pd.to_datetime(log['Close Date'])
                log.rename(columns={
                    'Trade Type':'Strategy','Type':'C/P','Close Type':'How Closed',
                    'Open Date':'Open','Close Date':'Close',
                    'Days Held':'Days','Premium Rcvd':'Credit','Net P/L':'P/L',
                    'Capital Risk':'Risk','Ann Return %':'Ann Ret %'
                }, inplace=True)
                log = log.sort_values('Close', ascending=False)

                # Append * to Ann Ret % for short-hold trades before styling
                log['Ann Ret %'] = log.apply(_fmt_ann_ret, axis=1)

                st.dataframe(
                    log.style.format({
                        'Credit':    lambda x: '${:.2f}'.format(x),
                        'P/L':       lambda x: '${:.2f}'.format(x),
                        'Risk':      lambda x: '${:,.0f}'.format(x),
                        'Capture %': lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                        'Ann Ret %': lambda v: v if isinstance(v, str) else ('{:.0f}%'.format(v) if pd.notna(v) else '—'),
                    }).apply(_style_ann_ret, axis=1)
                    .map(color_pnl_cell, subset=['P/L']),
                    width='stretch', hide_index=True,
                    column_config={
                        'Open':  st.column_config.DateColumn('Open',  format='DD/MM/YY'),
                        'Close': st.column_config.DateColumn('Close', format='DD/MM/YY'),
                    }
                )
                st.caption('\\* Trades held < 4 days — annualised return may be misleading.')

    # ── Tab 3: Wheel Campaigns ─────────────────────────────────────────────────────
    with tab3:
        st.subheader('🎯 Wheel Campaign Tracker')
        if use_lifetime:
            st.info("💡 **Lifetime mode** — all history for a ticker combined into one campaign. Effective basis and premiums accumulate across the full holding period without resetting.")
        else:
            st.caption(
                ('Tracks each share-holding period as a campaign — starting when you buy %d+ shares, ending when you exit. '
                'Premiums banked from covered calls, covered strangles, and short puts are credited against your cost basis, '
                'reducing your effective break-even over time. Legging in or out of one side (e.g. closing a put while keeping '
                'the covered call) shows naturally as separate call/put chains below. '
                'Campaigns reset when shares hit zero — toggle Lifetime mode to see your full history as one continuous position.') % WHEEL_MIN_SHARES
            )
        if not all_campaigns:
            st.info('No wheel campaigns found.')
        else:
            rows = []
            for ticker, camps in sorted(all_campaigns.items()):
                for i, c in enumerate(camps):
                    rpnl = realized_pnl(c, use_lifetime); effb = effective_basis(c, use_lifetime)
                    dur  = (c.end_date or latest_date) - c.start_date
                    rows.append({'Ticker': ticker, 'Status': '✅ Closed' if c.status=='closed' else '🟢 Open',
                        'Qty': int(c.total_shares), 'Avg Price': c.blended_basis,
                        'Eff. Basis': effb, 'Premiums': c.premiums,
                        'Divs': c.dividends, 'Exit': c.exit_proceeds,
                        'P/L': rpnl, 'Days': dur.days,
                        'Opened': c.start_date.strftime('%d/%m/%y')})
            summary_df = pd.DataFrame(rows)
            st.dataframe(summary_df.style.format({
                'Avg Price': fmt_dollar,
                'Eff. Basis': fmt_dollar,
                'Premiums': fmt_dollar,
                'Divs': fmt_dollar,
                'Exit': fmt_dollar,
                'P/L': fmt_dollar
            }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)
            st.markdown('---')

            for ticker, camps in sorted(all_campaigns.items()):
                for i, c in enumerate(camps):
                    rpnl = realized_pnl(c, use_lifetime); effb = effective_basis(c, use_lifetime)
                    is_open  = c.status == 'open'
                    status_badge = '🟢 OPEN' if is_open else '✅ CLOSED'
                    pnl_color    = '#00cc96' if rpnl >= 0 else '#ef553b'
                    basis_reduction = c.blended_basis - effb
                    card_html = """
                    <div style="border:1px solid {border}; border-radius:10px; padding:16px 20px 12px 20px;
                                 margin-bottom:12px; background:rgba(255,255,255,0.03);">
                      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                        <span style="font-size:1.2em; font-weight:700; letter-spacing:0.5px;">{ticker}
                          <span style="font-size:0.75em; font-weight:400; color:#888; margin-left:8px;">Campaign {camp_n}</span>
                        </span>
                        <span style="font-size:0.8em; font-weight:600; padding:3px 10px; border-radius:20px;
                                     background:{badge_bg}; color:{badge_col};">{status}</span>
                      </div>
                      <div style="display:grid; grid-template-columns:repeat(5,1fr); gap:12px; text-align:center;">
                        <div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">SHARES</div>
                             <div style="font-size:1.0em;font-weight:600;">{shares}</div></div>
                        <div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">ENTRY BASIS</div>
                             <div style="font-size:1.0em;font-weight:600;">${entry_basis:.2f}/sh</div></div>
                        <div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">EFF. BASIS</div>
                             <div style="font-size:1.0em;font-weight:600;">${eff_basis:.2f}/sh</div>
                             <div style="font-size:0.7em;color:#00cc96;">▼ ${reduction:.2f} saved</div></div>
                        <div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">PREMIUMS</div>
                             <div style="font-size:1.0em;font-weight:600;">${premiums:.2f}</div></div>
                        <div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">REALIZED P/L</div>
                             <div style="font-size:1.1em;font-weight:700;color:{pnl_color};">${pnl:+.2f}</div></div>
                      </div>
                    </div>""".format(
                        border='#00cc96' if is_open else '#444',
                        ticker=xe(ticker), camp_n=i+1, status=xe(status_badge),
                        badge_bg='rgba(0,204,150,0.15)' if is_open else 'rgba(100,100,100,0.2)',
                        badge_col='#00cc96' if is_open else '#888',
                        shares=int(c.total_shares),
                        entry_basis=c.blended_basis, eff_basis=effb,
                        reduction=basis_reduction if basis_reduction > 0 else 0,
                        premiums=c.premiums, pnl=rpnl, pnl_color=pnl_color
                    )
                    st.markdown(card_html, unsafe_allow_html=True)
                    with st.expander('📊 Detail — Chains & Events', expanded=is_open):
                        ticker_opts = df[(df['Ticker']==ticker) &
                            option_mask(df['Instrument Type'])].copy()
                        camp_start = c.start_date
                        camp_end   = c.end_date or latest_date
                        ticker_opts = ticker_opts[
                            (ticker_opts['Date'] >= camp_start) & (ticker_opts['Date'] <= camp_end)
                        ]

                        # ── P/L Waterfall ──────────────────────────────────────
                        # Shows how each component contributes to the campaign result:
                        # Share cost → premiums banked → dividends → exit proceeds → net P/L
                        _wf_share_cost = -abs(c.total_cost)
                        _wf_premiums   = c.premiums
                        _wf_dividends  = c.dividends
                        _wf_exit       = c.exit_proceeds if c.status == 'closed' else 0.0
                        _wf_net        = rpnl

                        _wf_labels  = ['Share Cost', 'Premiums', 'Dividends']
                        _wf_values  = [_wf_share_cost, _wf_premiums, _wf_dividends]
                        _wf_measure = ['absolute', 'relative', 'relative']

                        if c.status == 'closed':
                            _wf_labels.append('Exit Proceeds')
                            _wf_values.append(_wf_exit)
                            _wf_measure.append('relative')

                        _wf_labels.append('Net P/L')
                        _wf_values.append(_wf_net)
                        _wf_measure.append('total')

                        _wf_colors = []
                        for lbl, val, msr in zip(_wf_labels, _wf_values, _wf_measure):
                            if msr == 'absolute':
                                _wf_colors.append('#ef553b')        # share cost always red (outflow)
                            elif msr == 'total':
                                _wf_colors.append('#00cc96' if val >= 0 else '#ef553b')
                            else:
                                _wf_colors.append('#00cc96' if val >= 0 else '#ef553b')

                        _fig_wf = go.Figure(go.Waterfall(
                            orientation='v',
                            measure=_wf_measure,
                            x=_wf_labels,
                            y=_wf_values,
                            connector=dict(line=dict(color='rgba(255,255,255,0.15)', width=1, dash='dot')),
                            increasing=dict(marker=dict(color='#00cc96', line=dict(width=0))),
                            decreasing=dict(marker=dict(color='#ef553b', line=dict(width=0))),
                            totals=dict(marker=dict(
                                color='#00cc96' if _wf_net >= 0 else '#ef553b',
                                line=dict(width=0)
                            )),
                            text=[fmt_dollar(abs(v)) for v in _wf_values],
                            textposition='outside',
                            textfont=dict(size=10, family='IBM Plex Mono', color='#c9d1d9'),
                            hovertemplate='%{x}<br><b>%{y:$,.2f}</b><extra></extra>',
                        ))
                        _wf_lay = chart_layout(
                            f'{xe(ticker)} Campaign {i+1} — P/L Waterfall',
                            height=280, margin_t=36
                        )
                        _wf_lay['showlegend'] = False
                        _wf_lay['yaxis']['tickprefix'] = '$'
                        _wf_lay['yaxis']['tickformat'] = ',.0f'
                        _fig_wf.update_layout(**_wf_lay)
                        st.plotly_chart(_fig_wf, width='stretch', config={'displayModeBar': False})
                        if c.status == 'open':
                            st.caption('Share cost = total cash paid for shares. Premiums and dividends reduce your effective basis. Exit proceeds will appear when the campaign closes.')
                        else:
                            st.caption('Share cost = total cash paid for shares. Each component stacks to show how premiums, dividends, and the share exit combine into your net P/L.')

                        chains = build_option_chains(ticker_opts)

                        if chains:
                            st.markdown('**📎 Option Roll Chains**')
                            st.caption(
                                'Calls and puts tracked as separate chains — a Covered Strangle appears as two parallel chains, '
                                'closing the put reverts naturally to a Covered Call chain. '
                                'Rolls within ~3 days stay in the same chain; longer gaps start a new one. '
                                '⚠️ Complex structures inside a campaign (PMCC, Diagonals, Jade Lizards, Iron Condors, Butterflies) '
                                'are not fully decomposed here — their P/L is correct in the campaign total, '
                                'but the chain view may show fragments.'
                            )
                            for ci, chain in enumerate(chains):
                                cp      = chain[0]['cp']
                                ch_pnl  = sum(l['total'] for l in chain)
                                last    = chain[-1]
                                is_open_chain = 'to open' in str(last['sub_type']).lower()
                                n_rolls = sum(1 for l in chain if PAT_CLOSE in str(l['sub_type']).lower())
                                status_icon = '🟢' if is_open_chain else '✅'
                                cp_icon = '📞' if cp == 'CALL' else '📉'
                                chain_label = '%s %s %s Chain %d — %d roll(s) | Net: $%.2f' % (
                                    status_icon, cp_icon, cp.title(), ci+1, n_rolls, ch_pnl)
                                with st.expander(chain_label, expanded=is_open_chain):
                                    chain_rows = []
                                    for leg_i, leg in enumerate(chain):
                                        sub = str(leg['sub_type']).lower()
                                        if 'to open' in sub:       action = '↪️ Sell to Open'
                                        elif PAT_CLOSE in sub:    action = '↩️ Buy to Close'
                                        elif PAT_EXPIR in sub:       action = '⏹️ Expired'
                                        elif PAT_ASSIGN in sub:      action = '📋 Assigned'
                                        else:                      action = leg['sub_type']
                                        dte_str = ''
                                        if 'to open' in sub:
                                            try:
                                                exp_dt = pd.to_datetime(leg['exp'], dayfirst=True)
                                                dte_str = '%dd' % max((exp_dt - leg['date']).days, 0)
                                            except (ValueError, TypeError): dte_str = ''
                                        is_open_leg = is_open_chain and leg_i == len(chain) - 1
                                        chain_rows.append({
                                            'Action': ('🟢 ' + action) if is_open_leg else action,
                                            'Date': leg['date'].strftime('%d/%m/%y'),
                                            'Strike': '%.1f%s' % (leg['strike'], cp[0]),
                                            'Exp': leg['exp'], 'DTE': dte_str,
                                            'Cash': leg['total'], '_open': is_open_leg,
                                        })
                                    ch_df = pd.DataFrame(chain_rows)
                                    ch_df = pd.concat([ch_df, pd.DataFrame([{
                                        'Action': '━━ Chain Total', 'Date': '',
                                        'Strike': '', 'Exp': '', 'DTE': '', 'Cash': ch_pnl, '_open': False
                                    }])], ignore_index=True)
                                    st.dataframe(
                                        ch_df[['Action','Date','Strike','Exp','DTE','Cash','_open']].style
                                            .apply(_style_chain_row, axis=1)
                                            .format({'Cash': lambda x: '${:.2f}'.format(x)})
                                            .map(lambda v: 'color: #00cc96' if isinstance(v,float) and v>0
                                                else ('color: #ef553b' if isinstance(v,float) and v<0 else ''),
                                                subset=['Cash']),
                                        width='stretch', hide_index=True,
                                        column_config={'_open': None}
                                    )

                        st.markdown('**📋 Share & Dividend Events**')
                        ev_df = pd.DataFrame(c.events)
                        ev_share = ev_df[~ev_df['type'].str.lower().str.contains('to open|to close|expir|assign', na=False)]
                        if not ev_share.empty:
                            ev_share = ev_share.copy()
                            ev_share['date'] = pd.to_datetime(ev_share['date']).dt.strftime('%d/%m/%y %H:%M')
                            ev_share.columns = ['Date','Type','Detail','Amount']
                            st.dataframe(ev_share.style.format({'Amount': fmt_dollar})
                                .map(lambda v: 'color: #00cc96' if isinstance(v,float) and v>0
                                    else ('color: #ef553b' if isinstance(v,float) and v<0 else ''),
                                    subset=['Amount']),
                                width='stretch', hide_index=True)
                        else:
                            st.caption('No share/dividend events.')

    # ── Tab 4: All Trades ─────────────────────────────────────────────────────────
    with tab4:
        st.markdown(f'### 🔍 Realized P/L — All Tickers {_win_label}', unsafe_allow_html=True)

        # ── Portfolio Equity Curve ─────────────────────────────────────────────────
        # Full-history FIFO-correct cumulative P/L: options + equity sales + dividends.
        # Uses _daily_pnl_all (all-time) so the curve shows your true account trajectory
        # from day one — not just the selected window. The selected window is shaded.
        st.markdown('<div style="font-size:0.8rem;color:#6b7280;margin-bottom:8px;line-height:1.5;">Full-history cumulative realized P/L — options, equity sales, dividends and interest. FIFO-correct. Shaded region = selected time window.</div>', unsafe_allow_html=True)
        if not _daily_pnl_all.empty:
            _eq_curve = _daily_pnl_all.sort_values('Date').copy()
            _eq_curve['Cum P/L'] = _eq_curve['PnL'].cumsum()
            _eq_final   = _eq_curve['Cum P/L'].iloc[-1]
            _eq_color   = '#00cc96' if _eq_final >= 0 else '#ef553b'
            _eq_fill    = 'rgba(0,204,150,0.10)' if _eq_final >= 0 else 'rgba(239,85,59,0.10)'

            # Peak for drawdown shading
            _eq_curve['Peak']     = _eq_curve['Cum P/L'].cummax()
            _eq_curve['Drawdown'] = _eq_curve['Cum P/L'] - _eq_curve['Peak']

            _fig_eq2 = go.Figure()

            # Drawdown fill (below peak — shows recovery valleys)
            _dd_mask = _eq_curve['Drawdown'] < 0
            if _dd_mask.any():
                _fig_eq2.add_trace(go.Scatter(
                    x=_eq_curve['Date'], y=_eq_curve['Peak'],
                    mode='lines', line=dict(width=0),
                    showlegend=False, hoverinfo='skip'
                ))
                _fig_eq2.add_trace(go.Scatter(
                    x=_eq_curve['Date'], y=_eq_curve['Cum P/L'],
                    mode='none', fill='tonexty',
                    fillcolor='rgba(239,85,59,0.18)',
                    showlegend=False, hoverinfo='skip',
                    name='Drawdown'
                ))

            # Main equity curve
            _fig_eq2.add_trace(go.Scatter(
                x=_eq_curve['Date'], y=_eq_curve['Cum P/L'],
                mode='lines', line=dict(color=_eq_color, width=2),
                fill='tozeroy', fillcolor=_eq_fill,
                name='Cumulative P/L',
                hovertemplate='%{x|%d/%m/%y}<br><b>%{y:$,.2f}</b><extra></extra>'
            ))

            # Selected window shading
            if not _is_all_time:
                _fig_eq2.add_vrect(
                    x0=start_date, x1=latest_date,
                    fillcolor='rgba(88,166,255,0.06)',
                    line=dict(color='rgba(88,166,255,0.3)', width=1, dash='dot'),
                    annotation_text=selected_period,
                    annotation_position='top left',
                    annotation_font=dict(color='#58a6ff', size=10)
                )

            # Final value annotation
            _fig_eq2.add_annotation(
                x=_eq_curve['Date'].iloc[-1], y=_eq_final,
                text='<b>%s</b>' % fmt_dollar(_eq_final),
                showarrow=False, xanchor='right', yanchor='bottom',
                font=dict(color=_eq_color, size=12, family='IBM Plex Mono'),
                bgcolor='rgba(10,14,23,0.8)', borderpad=4
            )

            _fig_eq2.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)

            _eq2_lay = chart_layout('Portfolio Equity Curve — Cumulative Realized P/L', height=300, margin_t=36)
            _eq2_lay['yaxis']['tickprefix'] = '$'
            _eq2_lay['yaxis']['tickformat'] = ',.0f'
            _eq2_lay['showlegend'] = False
            _fig_eq2.update_layout(**_eq2_lay)
            st.plotly_chart(_fig_eq2, width='stretch', config={'displayModeBar': False})
            st.caption('Red shading between curve and peak = drawdown from realized P/L peak (not account value — deposits and withdrawals are excluded entirely). Blue shaded region = selected time window. Curve always starts from your first transaction regardless of window selection.')

            # ── Top single-day P/L events ──────────────────────────────────────
            # Explains spikes and troughs in the equity curve above.
            # Uses _daily_pnl_all (all-time) so big days outside the window are visible.
            if len(_daily_pnl_all) >= 2:
                _top_days = _daily_pnl_all.copy()
                _top_days = _top_days.reindex(_top_days['PnL'].abs().sort_values(ascending=False).index)
                _top_days = _top_days.head(10).copy()
                _top_days['Date'] = pd.to_datetime(_top_days['Date'])

                # For each big day, find the dominant transaction type
                def _day_summary(date):
                    _d_rows = df[df['Date'].dt.date == date.date()]
                    # Options trades
                    _opts = _d_rows[
                        _d_rows['Instrument Type'].isin(OPT_TYPES) &
                        _d_rows['Type'].isin(TRADE_TYPES)
                    ]
                    # Equity sells
                    _eq_sells = _d_rows[
                        equity_mask(_d_rows['Instrument Type']) &
                        (_d_rows['Net_Qty_Row'] < 0)
                    ]
                    # Income
                    _inc = _d_rows[_d_rows['Sub Type'].isin(INCOME_SUB_TYPES)]
                    parts = []
                    if not _opts.empty:
                        _tickers = ', '.join(sorted(_opts['Ticker'].unique()[:3]))
                        parts.append('Options (%s)' % _tickers)
                    if not _eq_sells.empty:
                        _tickers = ', '.join(sorted(_eq_sells['Ticker'].unique()[:3]))
                        parts.append('Equity sale (%s)' % _tickers)
                    if not _inc.empty:
                        _tickers = ', '.join(sorted(_inc['Ticker'].dropna().unique()[:3]))
                        parts.append('Income (%s)' % _tickers if _tickers else 'Income')
                    return ' + '.join(parts) if parts else '—'

                _top_days['What'] = _top_days['Date'].apply(_day_summary)
                _top_days['P/L']  = _top_days['PnL'].apply(fmt_dollar)
                _top_days['Date_fmt'] = _top_days['Date'].dt.strftime('%d %b %Y')

                with st.expander('🔍 Top 10 single-day P/L events (explains curve spikes)', expanded=False):
                    _top_display = _top_days[['Date_fmt', 'P/L', 'What']].copy()
                    _top_display.columns = ['Date', 'P/L', 'What']
                    st.dataframe(
                        _top_display.style.map(
                            lambda v: 'color:#00cc96;font-family:IBM Plex Mono' if v.startswith('$') and '-' not in v
                                      else ('color:#ef553b;font-family:IBM Plex Mono' if v.startswith('-') or '−' in v else ''),
                            subset=['P/L']
                        ),
                        width='stretch', hide_index=True
                    )
                    st.caption('Sorted by absolute P/L — largest moves first regardless of direction. Covers full account history, not just the selected window.')

        st.markdown('---')
        rows = []
        for ticker, camps in sorted(all_campaigns.items()):
            tr = sum(realized_pnl(c, use_lifetime) for c in camps)
            td = sum(c.total_cost for c in camps if c.status=='open')
            tp = sum(c.premiums for c in camps)
            tv = sum(c.dividends for c in camps)
            po = pure_opts_per_ticker.get(ticker, 0.0)
            oc = sum(1 for c in camps if c.status=='open')
            cc = sum(1 for c in camps if c.status=='closed')
            rows.append({'Ticker': ticker, 'Type': '🎡 Wheel',
                'Campaigns': '%d open, %d closed'%(oc,cc),
                'Premiums': tp, 'Divs': tv,
                'Options P/L': po, 'Deployed': td, 'P/L': tr+po})
        for ticker in sorted(pure_options_tickers):
            t_df    = df[df['Ticker'] == ticker]
            t_eq    = t_df[equity_mask(t_df['Instrument Type'])].sort_values('Date')

            opt_flow    = t_df[
                t_df['Instrument Type'].isin(OPT_TYPES) &
                t_df['Type'].isin(TRADE_TYPES)
            ]['Total'].sum()
            eq_fifo_pnl = sum(p - c for _, p, c in _iter_fifo_sells(t_eq))
            pnl         = opt_flow + eq_fifo_pnl

            net_shares  = t_eq['Net_Qty_Row'].sum()
            cap_dep     = 0.0
            if net_shares > 0.0001:
                bought_rows    = t_eq[t_eq['Net_Qty_Row'] > 0]
                total_bought   = bought_rows['Net_Qty_Row'].sum()
                total_buy_cost = bought_rows['Total'].apply(abs).sum()
                avg_cost       = total_buy_cost / total_bought if total_bought > 0 else 0
                cap_dep        = net_shares * avg_cost

            rows.append({'Ticker': ticker, 'Type': '📊 Standalone',
                'Campaigns': '—', 'Premiums': pnl, 'Divs': 0.0,
                'Options P/L': 0.0, 'Deployed': cap_dep, 'P/L': pnl})
        if rows:
            deep_df = pd.DataFrame(rows)
            total_row = {'Ticker': 'TOTAL', 'Type': '', 'Campaigns': '',
                'Premiums': deep_df['Premiums'].sum(),
                'Divs': deep_df['Divs'].sum(),
                'Options P/L': deep_df['Options P/L'].sum(),
                'Deployed': deep_df['Deployed'].sum(),
                'P/L': deep_df['P/L'].sum()}
            deep_df = pd.concat([deep_df, pd.DataFrame([total_row])], ignore_index=True)
            st.dataframe(deep_df.style.format({
                'Premiums': fmt_dollar,
                'Divs': fmt_dollar,
                'Options P/L': fmt_dollar,
                'Deployed': fmt_dollar,
                'P/L': fmt_dollar
            }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)

        # ── Total Portfolio P/L by Week & Month ───────────────────────────────────
        st.markdown('---')
        st.markdown(f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">📅 Total Realized P/L by Week &amp; Month {_win_label}</div>', unsafe_allow_html=True)
        st.markdown(
            '<div style="font-size:0.8rem;color:#6b7280;margin-bottom:12px;line-height:1.5;">'
            '<b style="color:#00cc96;">Whole portfolio — realized flows only</b>: '
            'options credits &amp; debits, share <em>sales</em> (FIFO gains/losses), dividends, and interest. '
            '<b>Share purchases are excluded</b> — they are capital deployment, not realized losses. '
            'This matches the <b>Realized P/L</b> top-line metric. Filtered to selected time window.'
            '</div>',
            unsafe_allow_html=True
        )

        # _daily_pnl already computed above as a window-sliced view of the cached all-time series
        _daily_pnl['Week']  = _daily_pnl['Date'].dt.to_period('W').apply(lambda p: p.start_time)
        _daily_pnl['Month'] = _daily_pnl['Date'].dt.to_period('M').apply(lambda p: p.start_time)
        _port_df = _daily_pnl  # alias for the if-check below

        if not _port_df.empty:
            _p_col1, _p_col2 = st.columns(2)

            with _p_col1:
                _p_weekly = _daily_pnl.groupby('Week')['PnL'].sum().reset_index()
                _p_weekly['Week'] = pd.to_datetime(_p_weekly['Week'])
                _p_weekly['Colour'] = _p_weekly['PnL'].apply(lambda x: '#00cc96' if x >= 0 else '#ef553b')
                _fig_pw = go.Figure()
                _fig_pw.add_trace(go.Bar(
                    x=_p_weekly['Week'], y=_p_weekly['PnL'],
                    marker_color=_p_weekly['Colour'],
                    marker_line_width=0,
                    customdata=[fmt_dollar(v) for v in _p_weekly['PnL']],
                    hovertemplate='Week of %{x|%d %b}<br><b>%{customdata}</b><extra></extra>'
                ))
                _fig_pw.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
                _pw_lay = chart_layout('Weekly Total P/L' + _win_suffix, height=280, margin_t=36)
                _pw_lay['yaxis']['tickprefix'] = '$'
                _pw_lay['yaxis']['tickformat'] = ',.0f'
                _pw_lay['bargap'] = 0.25
                _fig_pw.update_layout(**_pw_lay)
                st.plotly_chart(_fig_pw, width='stretch', config={'displayModeBar': False})

            with _p_col2:
                _p_monthly = _daily_pnl.groupby('Month')['PnL'].sum().reset_index()
                _p_monthly['Month'] = pd.to_datetime(_p_monthly['Month'])
                _p_monthly['Colour'] = _p_monthly['PnL'].apply(lambda x: '#00cc96' if x >= 0 else '#ef553b')
                _p_monthly['Label'] = _p_monthly['Month'].dt.strftime('%b %Y')
                _fig_pm = go.Figure()
                _fig_pm.add_trace(go.Bar(
                    x=_p_monthly['Label'], y=_p_monthly['PnL'],
                    marker_color=_p_monthly['Colour'],
                    marker_line_width=0,
                    text=[fmt_dollar(v, 0) for v in _p_monthly['PnL']],
                    customdata=[fmt_dollar(v) for v in _p_monthly['PnL']],
                    textposition='outside',
                    textfont=dict(size=10, family='IBM Plex Mono', color='#8b949e'),
                    hovertemplate='%{x}<br><b>%{customdata}</b><extra></extra>'
                ))
                _fig_pm.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
                _pm_lay = chart_layout('Monthly Total P/L' + _win_suffix, height=280, margin_t=36)
                _pm_lay['yaxis']['tickprefix'] = '$'
                _pm_lay['yaxis']['tickformat'] = ',.0f'
                _pm_lay['bargap'] = 0.35
                _fig_pm.update_layout(**_pm_lay)
                st.plotly_chart(_fig_pm, width='stretch', config={'displayModeBar': False})

            # ── P&L Volatility Metrics ─────────────────────────────────────────────
            st.markdown('---')
            st.markdown(f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">📉 P&amp;L Consistency {_win_label}</div>', unsafe_allow_html=True)
            st.markdown('<div style="font-size:0.8rem;color:#6b7280;margin-bottom:16px;line-height:1.5;">Weekly buckets — a theta engine should produce a smooth, consistent stream. High volatility relative to your average week means lumpy, inconsistent results.</div>', unsafe_allow_html=True)

            if not _daily_pnl.empty and len(_daily_pnl) >= 2:
                # Weekly bucketing
                _vol_df = _daily_pnl.copy()
                _vol_df['Week'] = pd.to_datetime(_vol_df['Date']).dt.to_period('W').apply(lambda p: p.start_time)
                _weekly_pnl = _vol_df.groupby('Week')['PnL'].sum().reset_index()
                _weekly_pnl['Week'] = pd.to_datetime(_weekly_pnl['Week'])

                _avg_week     = _weekly_pnl['PnL'].mean()
                _std_week     = _weekly_pnl['PnL'].std()
                _sharpe_eq    = (_avg_week / _std_week) if _std_week > 0 else 0.0
                _pos_weeks    = (_weekly_pnl['PnL'] > 0).sum()
                _total_weeks  = len(_weekly_pnl)
                _consistency  = _pos_weeks / _total_weeks * 100 if _total_weeks > 0 else 0.0

                # Max drawdown on cumulative daily P/L
                _cum = _vol_df.sort_values('Date')['PnL'].cumsum().values
                _peak = _cum[0]; _max_dd = 0.0; _dd_start_i = 0; _dd_end_i = 0; _peak_i = 0
                for i, v in enumerate(_cum):
                    if v > _peak:
                        _peak = v; _peak_i = i
                    dd = v - _peak
                    if dd < _max_dd:
                        _max_dd = dd; _dd_start_i = _peak_i; _dd_end_i = i

                # Recovery — days from trough back to previous peak
                _recovery_days = None
                if _max_dd < 0:
                    _trough_val = _cum[_dd_end_i]
                    for i in range(_dd_end_i + 1, len(_cum)):
                        if _cum[i] >= _cum[_dd_start_i]:
                            _recovery_days = i - _dd_end_i
                            break

                # Rolling 4-week std dev for chart
                _weekly_pnl['Rolling_Std'] = _weekly_pnl['PnL'].rolling(4, min_periods=2).std()

                # Metrics row
                vc1, vc2, vc3, vc4, vc5 = st.columns(5)
                vc1.metric('Avg Week P/L',      fmt_dollar(_avg_week))
                vc1.caption('Mean realized P/L per calendar week in the window. Your typical weekly income rate.')
                vc2.metric('Weekly Std Dev',     fmt_dollar(_std_week))
                vc2.caption('Standard deviation of weekly P/L. Lower = more consistent income stream. A theta engine should have this well below avg week P/L.')
                vc3.metric('Sharpe-Equiv',       '%.2f'  % _sharpe_eq)
                vc3.caption('Avg weekly P/L ÷ std dev. Above 1.0 means your average week outweighs your typical swing. Higher is better — 0.5–1.0 is decent for options selling.')
                vc4.metric('Profitable Weeks',   '%.0f%% (%d/%d)' % (_consistency, _pos_weeks, _total_weeks))
                vc4.caption('% of calendar weeks with positive realized P/L. Complements trade win rate — a week can have winning trades but net negative if one loss dominates.')
                if _max_dd < 0:
                    _rec_str = '%dd' % _recovery_days if _recovery_days else 'Not yet'
                    vc5.metric('Max Drawdown',   fmt_dollar(_max_dd), delta='Recovery: %s' % _rec_str, delta_color='off')
                    vc5.caption('Largest peak-to-trough drop in cumulative daily P/L. Recovery = days from trough back to previous peak. "Not yet" means still underwater.')
                else:
                    vc5.metric('Max Drawdown', '$0.00')
                    vc5.caption('No drawdown in this window — cumulative P/L never fell below its starting peak.')

                # Chart: weekly P/L bars + rolling std dev band
                _fig_vol = go.Figure()
                _fig_vol.add_trace(go.Bar(
                    x=_weekly_pnl['Week'], y=_weekly_pnl['PnL'],
                    marker_color=_weekly_pnl['PnL'].apply(lambda x: '#00cc96' if x >= 0 else '#ef553b'),
                    marker_line_width=0, name='Weekly P/L',
                    customdata=[fmt_dollar(v) for v in _weekly_pnl['PnL']],
                    hovertemplate='Week of %{x|%d %b}<br><b>%{customdata}</b><extra></extra>'
                ))
                if _weekly_pnl['Rolling_Std'].notna().sum() >= 2:
                    _fig_vol.add_trace(go.Scatter(
                        x=_weekly_pnl['Week'], y=_weekly_pnl['Rolling_Std'],
                        mode='lines', name='4-wk Std Dev',
                        line=dict(color='#ffa421', width=1.5, dash='dot'),
                        yaxis='y2',
                        hovertemplate='Std Dev: <b>$%{y:,.2f}</b><extra></extra>'
                    ))
                    _fig_vol.add_trace(go.Scatter(
                        x=_weekly_pnl['Week'], y=(-_weekly_pnl['Rolling_Std']),
                        mode='lines', name='-4-wk Std Dev',
                        line=dict(color='#ffa421', width=1.5, dash='dot'),
                        yaxis='y2', showlegend=False,
                        hovertemplate='−Std Dev: <b>$%{y:,.2f}</b><extra></extra>'
                    ))
                _fig_vol.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
                _vol_lay = chart_layout('Weekly P/L + Rolling 4-wk Volatility Band' + _win_suffix, height=300, margin_t=40)
                _vol_lay['yaxis']['tickprefix'] = '$'
                _vol_lay['yaxis']['tickformat'] = ',.0f'
                _vol_lay['bargap'] = 0.3
                _vol_lay['yaxis2'] = dict(
                    overlaying='y', side='right',
                    tickprefix='±$', tickformat=',.0f',
                    tickfont=dict(size=10, color='#ffa421'),
                    gridcolor='rgba(0,0,0,0)',
                    showgrid=False
                )
                _vol_lay['legend'] = dict(orientation='h', yanchor='bottom', y=1.02,
                    xanchor='right', x=1, bgcolor='rgba(0,0,0,0)', font=dict(size=11))
                _fig_vol.update_layout(**_vol_lay)
                st.plotly_chart(_fig_vol, width='stretch', config={'displayModeBar': False})
                st.caption('Amber dotted lines = rolling 4-week std dev (right axis). When the amber band widens your results are getting lumpier — tighten position sizing or reduce undefined risk.')

                # ── Rolling 90-day Capital Efficiency ─────────────────────────
                # Shows how the annualised return on deployed capital has evolved
                # over time — each point is (90-day rolling P/L / capital_deployed)
                # annualised. A rising line means you are deploying capital more
                # productively. Flat or falling = position sizing or selection drifting.
                if capital_deployed > 0 and len(_weekly_pnl) >= 6:
                    st.markdown('---')
                    st.markdown(f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">📈 Rolling Capital Efficiency {_win_label}</div>', unsafe_allow_html=True)
                    st.markdown('<div style="font-size:0.8rem;color:#6b7280;margin-bottom:12px;line-height:1.5;">Annualised return on deployed capital on a rolling 13-week (90-day) basis. Shows whether your capital efficiency is improving or drifting over time. Benchmark: S&amp;P ~10%/yr.</div>', unsafe_allow_html=True)

                    _roll_pnl = _weekly_pnl.copy()
                    # 13-week rolling sum of P/L, annualised against current capital deployed
                    _roll_pnl['Rolling_PnL_90d'] = _roll_pnl['PnL'].rolling(13, min_periods=4).sum()
                    _roll_pnl['Rolling_CapEff']  = (
                        _roll_pnl['Rolling_PnL_90d'] / capital_deployed / 90 * 365 * 100
                    )
                    _roll_valid = _roll_pnl.dropna(subset=['Rolling_CapEff'])

                    if not _roll_valid.empty:
                        _ce_color = '#00cc96' if _roll_valid['Rolling_CapEff'].iloc[-1] >= 0 else '#ef553b'
                        _ce_fill  = 'rgba(0,204,150,0.08)' if _roll_valid['Rolling_CapEff'].iloc[-1] >= 0 else 'rgba(239,85,59,0.08)'
                        _fig_ce = go.Figure()
                        _fig_ce.add_hrect(y0=0, y1=10, fillcolor='rgba(255,164,33,0.04)',
                            line_width=0, annotation_text='S&P benchmark ~10%',
                            annotation_position='top left',
                            annotation_font=dict(color='#ffa421', size=10))
                        _fig_ce.add_trace(go.Scatter(
                            x=_roll_valid['Week'], y=_roll_valid['Rolling_CapEff'],
                            mode='lines', line=dict(color=_ce_color, width=2),
                            fill='tozeroy', fillcolor=_ce_fill,
                            hovertemplate='Week of %{x|%d %b}<br>Cap Efficiency: <b>%{y:.1f}%</b><extra></extra>'
                        ))
                        _fig_ce.add_hline(y=10, line_dash='dot', line_color='#ffa421',
                            line_width=1.5,
                            annotation_text='S&P ~10%',
                            annotation_position='bottom right',
                            annotation_font=dict(color='#ffa421', size=11))
                        _fig_ce.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
                        _ce_lay = chart_layout('Rolling 90-day Capital Efficiency (annualised)' + _win_suffix, height=300, margin_t=40)
                        _ce_lay['yaxis']['ticksuffix'] = '%'
                        _ce_lay['yaxis']['tickformat'] = ',.0f'
                        _fig_ce.update_layout(**_ce_lay)
                        st.plotly_chart(_fig_ce, width='stretch', config={'displayModeBar': False})
                        st.caption('Rolling 13-week P/L annualised against your current capital deployed. Note: capital deployed is today\'s figure applied to historical P/L — if position sizes have changed significantly over time, earlier periods will be under or overstated. Amber line = S&P ~10%/yr benchmark.')

            else:
                st.info('Not enough data in this window for volatility metrics (need at least 2 days of activity).')
        else:
            st.info('No cash flow data in the selected window.')

    # ── Tab 5: Deposits, Dividends & Fees ─────────────────────────────────────────
    with tab5:
        st.markdown(f'### 💰 Deposits, Dividends & Fees {_win_label}', unsafe_allow_html=True)
        ic1, ic2, ic3, ic4 = st.columns(4)
        ic1.metric('Deposited',      fmt_dollar(total_deposited))
        ic2.metric('Withdrawn',      fmt_dollar(abs(total_withdrawn)))
        ic3.metric('Dividends',      fmt_dollar(div_income))
        ic4.metric('Interest (net)', fmt_dollar(int_net))
        income_df = df_window[df_window['Sub Type'].isin(
            DEPOSIT_SUB_TYPES
        )][['Date','Ticker','Sub Type','Description','Total']].sort_values('Date', ascending=False)
        if not income_df.empty:
            st.dataframe(
                income_df.style
                    .apply(_color_cash_row, axis=1)
                    .format({'Total': fmt_dollar})
                    .map(_color_cash_total, subset=['Total']),
                width='stretch', hide_index=True
            )
            st.caption(
                '🟢 Deposit &nbsp;&nbsp; 🔴 Withdrawal &nbsp;&nbsp; '
                '🔵 Dividend / Interest &nbsp;&nbsp; 🟡 Fee Adjustment'
            )
        else:
            st.info('No activity in this window.')


main()
