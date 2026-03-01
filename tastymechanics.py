import streamlit as st
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta
from models import Campaign, AppData, ParsedData

# ── Constants (all in config.py) ──────────────────────────────────────────────
from config import (
    OPT_TYPES, EQUITY_TYPE,
    TRADE_TYPES, MONEY_TYPES,
    SUB_SELL_OPEN, SUB_ASSIGNMENT, SUB_DIVIDEND, SUB_CREDIT_INT, SUB_DEBIT_INT,
    INCOME_SUB_TYPES, DEPOSIT_SUB_TYPES,
    PAT_CLOSE, PAT_EXPIR, PAT_ASSIGN, PAT_EXERCISE, PAT_CLOSING,
    WHEEL_MIN_SHARES, LEAPS_DTE_THRESHOLD, ROLL_CHAIN_GAP_DAYS,
    SPLIT_DSC_PATTERNS, ZERO_COST_WARN_TYPES,
    REQUIRED_COLUMNS,
    ANN_RETURN_CAP,
    COLOURS,
)

# ── UI helpers & components (all in ui_components.py) ─────────────────────────
from report import build_html_report
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
    _aggregate_campaign_pnl,
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
import hashlib as _hashlib

# ==========================================
# TastyMechanics v25.12
# ==========================================
#
# Changelog (recent versions — full history in git log)
# -----------------------------------------------------
# v25.12 (2026-03-01)
#   - FEATURE: Candlestick charts replace bar charts for weekly/monthly P/L.
#   - FEATURE: HTML report export (Portfolio Overview + Premium Selling Performance).
#   - FEATURE: Lifetime "House Money" toggle moved into Wheel Campaigns tab header.
#   - REFACTOR: report.py extracted — HTML export has no Streamlit dependency.
#   - REFACTOR: tabs/tab0–tab5 extracted — tastymechanics.py is now orchestration only.
#   - REFACTOR: _classify_trade_type() and _calculate_capital_risk() extracted to
#     module-level pure functions in mechanics.py — independently testable.
#   - REFACTOR: _aggregate_campaign_pnl() extracted — eliminates duplicate aggregation
#     between compute_app_data() and the zero-cost exclusion path.
#   - FIX: f-string Python 3.10/3.11 compatibility (Unraid Docker).
#   - FIX: datetime.utcnow() deprecation warning on Python 3.12+.
#   - FIX: Report "Deposited" figure corrected (was net, now gross deposits).
#   - FIX: Streamlit Cloud cache stale-file bug — hashlib.md5 replaces hash().
#   - FIX: detect_strategy() Call Butterfly and Long Call false positives.
#   - FIX: DTE alert thresholds (5d/14d) moved to config.py as named constants.
#   - FIX: .iloc[0] unguarded calls in mechanics.py.
#   - FIX: qty != 0 → abs(qty) > FIFO_EPSILON for consistency with FIFO engine.
#   - COLOURS: Full COLOURS palette migration — all hardcoded hex removed from
#     tastymechanics.py and ui_components.py. config.py is single source of truth.
#   - TESTING: 294 tests passing (was 258). TSLA Call Debit Spread VERIFIED.
#
# v25.11 (2026-02-28)
#   - REFACTOR: render_tab0–render_tab5 extracted from main().
#   - REFACTOR: Union-Find helpers extracted to module level in mechanics.py.
#   - TESTING: Suite expanded 185 → 258 tests (23 sections).
#   - FIX: build_option_chains() empty-DataFrame crash.
#
# v25.3–v25.10 — foundational releases
#   Core FIFO engine, campaign tracking, stock split handling, zero-cost exclusion,
#   windowed P/L, period comparison, DTE charts, equity curve, Sharpe, drawdown,
#   capital efficiency, candlestick charts, HTML export. See git log for details.
# ==========================================

APP_VERSION = "v25.12"
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

    def _write_test_snapshot(ctx: dict) -> None:
        """
        Write app_snapshot.json for the test suite to compare against ground truth.
        Only called when TASTYMECHANICS_TEST=1 is set in the environment.
        Normal users never trigger this path.

        ctx is a plain dict assembled at the call site from already-computed
        local variables — no positional argument ordering to get wrong.
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

        df_             = ctx['df']
        all_campaigns_  = ctx['all_campaigns']
        wheel_tickers_  = ctx['wheel_tickers']

        snapshot = {
            # ── Headline P/L figures ──
            'total_realized_pnl':    round(ctx['total_realized_pnl'], 4),
            'window_realized_pnl':   round(ctx['window_realized_pnl'], 4),
            'prior_period_pnl':      round(ctx['prior_period_pnl'], 4),
            'selected_period':       ctx['selected_period'],
            # ── Components ──
            'closed_camp_pnl':       round(ctx['closed_camp_pnl'], 4),
            'open_premiums_banked':  round(ctx['open_premiums_banked'], 4),
            'pure_opts_pnl':         round(ctx['pure_opts_pnl'], 4),
            'all_time_income':       round(ctx['_all_time_income'], 4),
            'wheel_divs_in_camps':   round(ctx['_wheel_divs_in_camps'], 4),
            # ── Window components ──
            'w_opts_total':          round(ctx['_w_opts']['Total'].sum(), 4),
            'w_eq_pnl':              round(ctx['_eq_pnl'], 4),
            'w_div_int':             round(ctx['_w_div_int'], 4),
            # ── Portfolio stats ──
            'total_deposited':       round(ctx['total_deposited'], 4),
            'total_withdrawn':       round(ctx['total_withdrawn'], 4),
            'net_deposited':         round(ctx['net_deposited'], 4),
            'capital_deployed':      round(ctx['capital_deployed'], 4),
            'realized_ror':          round(ctx['realized_ror'], 4),
            'div_income':            round(ctx['div_income'], 4),
            'int_net':               round(ctx['int_net'], 4),
            # ── Campaigns ──
            'campaigns':             {t: _campaign_snapshot(c) for t, c in all_campaigns_.items()},
            # ── Per-ticker options P/L ──
            'pure_opts_per_ticker':  {t: round(v, 4) for t, v in ctx['pure_opts_per_ticker'].items()},
            'wheel_tickers':         wheel_tickers_,
            'pure_options_tickers':  ctx['pure_options_tickers'],
            # ── Open positions ──
            'open_positions': {
                t: {
                    'net_qty': round(
                        df_[(df_['Ticker'] == t) &
                           (df_['Instrument Type'].str.strip() == 'Equity')]['Net_Qty_Row'].sum(), 4
                    )
                }
                for t in (wheel_tickers_ + [
                    t for t in df_['Ticker'].unique()
                    if t not in wheel_tickers_ + ['CASH']
                    and df_[(df_['Ticker'] == t) &
                           (df_['Instrument Type'].str.strip() == 'Equity')]['Net_Qty_Row'].sum() > 0.001
                ])
            },
            # ── Metadata ──
            'csv_rows':    len(df_),
            'latest_date': ctx['latest_date'].strftime('%Y-%m-%d'),
            'app_version': APP_VERSION,
        }
        out_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'app_snapshot.json')
        with open(out_path, 'w') as f:
            _json.dump(snapshot, f, indent=2)
        st.info(f'🧪 Test snapshot written → `{out_path}`')


    # ── MAIN APP ───────────────────────────────────────────────────────────────────

    st.markdown(
        f'<div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.5rem;">'
        f'<span style="font-size:2rem;font-weight:700;color:{COLOURS["header_text"]};">'
        f'📟 TastyMechanics {APP_VERSION}</span>'
        f'<a href="https://www.buymeacoffee.com/Cruxis" target="_blank">'
        f'<img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" '
        f'alt="Buy Me A Coffee" style="height:36px;border-radius:6px;"></a>'
        f'</div>',
        unsafe_allow_html=True
    )

    with st.sidebar:
        _icon_path = Path(__file__).parent / 'icon.png'
        if _icon_path.exists():
            st.image(str(_icon_path), width=80)
        st.header('⚙️ Data Control')
        uploaded_file = st.file_uploader('Upload TastyTrade History CSV', type='csv')
        _td = COLOURS['text_dim']; _bl = COLOURS['blue']
        st.markdown(
            '<div style="font-size:0.75rem;color:' + _td + ';margin-top:0.5rem;">'
            'New to TastyTrade? <a href="https://tastytrade.com/welcome/?referralCode=NT57Z3P85B" '
            'target="_blank" style="color:' + _bl + ';">Open an account</a>'
            ' &nbsp;·&nbsp; <a href="https://www.buymeacoffee.com/Cruxis" '
            'target="_blank" style="color:#ffdd00;">Buy me a coffee</a>'
            '</div>',
            unsafe_allow_html=True,
        )


    if not uploaded_file:
        _ht = COLOURS["header_text"]; _tm = COLOURS["text_muted"]
        _td = COLOURS["text_dim"];    _bl = COLOURS["blue"]
        _cb = COLOURS["card_bg"];     _or = COLOURS["orange"] + "55"
        st.markdown(f"""
        <div style="max-width:780px;margin:2rem auto 0 auto;">

        <p style="color:{_tm};font-size:1rem;line-height:1.75;">
        Built for <b style="color:{_ht};">wheel traders and theta harvesters</b> — short puts,
        covered calls, strangles, iron condors, and the full wheel cycle. General options
        trading is fully supported. Upload your TastyTrade CSV and get a complete picture
        of your realized P/L, premium selling performance, wheel campaigns, and portfolio health.
        Your data is processed locally and never sent anywhere.
        </p>

        <h3 style="color:{_ht};margin-top:2rem;">What you get</h3>
        <ul style="color:{_tm};font-size:0.92rem;line-height:1.9;padding-left:1.2rem;margin-top:0.5rem;">
        <li><b style="color:{_ht};">Open Positions</b> — live view of all open options and equity positions with DTE, strategy label, and expiry alerts</li>
        <li><b style="color:{_ht};">Premium Selling Performance</b> — win rate, capture %, annualised return, profit factor, and trade breakdown by ticker and strategy</li>
        <li><b style="color:{_ht};">Trade Analysis</b> — equity curve, weekly/monthly P/L candles, DTE distributions, day-of-week and hour-of-day heat maps</li>
        <li><b style="color:{_ht};">Wheel Campaigns</b> — per-ticker campaign cards tracking entry basis, effective basis, premiums banked, and realised P/L across full roll chains</li>
        <li><b style="color:{_ht};">All Trades</b> — portfolio equity curve, drawdown, Sharpe, capital deployed, and income breakdown</li>
        <li><b style="color:{_ht};">Deposits, Dividends &amp; Fees</b> — full cash flow ledger with deposited capital, dividend income, and fee summary</li>
        </ul>

        <h3 style="color:{_ht};margin-top:2rem;">How to export from TastyTrade</h3>
        <p style="color:{_tm};font-size:0.92rem;line-height:1.75;">
        <b style="color:{_ht};">History → Transactions → set date range → Download CSV</b><br>
        Export your <b style="color:{_ht};">full account history</b> for best results —
        not just a recent window. FIFO cost basis for equity P/L requires all prior buy
        transactions to be present. A partial export will produce incorrect basis and
        P/L figures for positions with earlier lots outside the date range.
        </p>

        <h3 style="color:{_ht};margin-top:2rem;">⚠️ Disclaimer &amp; Known Limitations</h3>
        <div style="background:{_cb};border:1px solid {_or};border-radius:8px;padding:1.2rem 1.4rem;font-size:0.88rem;color:{_tm};line-height:1.75;">

        <p style="margin:0 0 0.75rem 0;color:{_ht};font-weight:600;">
        This tool is for personal record-keeping only. It is not financial advice.
        </p>

        <p style="margin:0 0 0.5rem 0;color:{_tm};">
        P/L figures are cash-flow based (what actually hit your account) and use FIFO cost
        basis for equity. They do not account for unrealised gains/losses, wash sale rules,
        or tax adjustments. Always reconcile against your official TastyTrade statements.
        </p>

        <b style="color:{_ht};">Verify these scenarios manually:</b>
        <ul style="margin:0.5rem 0 0.75rem 0;padding-left:1.2rem;">
        <li><b style="color:{_ht};">Covered calls assigned away</b> — if your shares are called away, verify the campaign closes and P/L is recorded correctly.</li>
        <li><b style="color:{_ht};">Multiple assignments on the same ticker</b> — each new buy-in starts a new campaign. Blended basis across campaigns is not combined.</li>
        <li><b style="color:{_ht};">Long options exercised by you</b> — exercising a long call or put into shares is untested. Check the resulting position and cost basis.</li>
        <li><b style="color:{_ht};">Futures options delivery</b> — cash-settled futures (/MES, /ZS etc.) are included in P/L totals, but in-the-money expiry into a futures contract is not handled.</li>
        <li><b style="color:{_ht};">Stock splits</b> — forward and reverse splits are detected and adjusted, but post-split option symbols are not automatically stitched to pre-split contracts.</li>
        <li><b style="color:{_ht};">Spin-offs and zero-cost deliveries</b> — shares received at $0 cost trigger a warning. Use the sidebar toggle to exclude those tickers if the inflated basis distorts your numbers.</li>
        <li><b style="color:{_ht};">Mergers and acquisitions</b> — if a ticker is acquired or merged, the campaign may be orphaned with no exit recorded. Reconcile manually.</li>
        <li><b style="color:{_ht};">Complex multi-leg structures</b> — PMCC, diagonals, calendars, and ratio spreads may not be labelled correctly. P/L totals are correct; trade type labels may not be.</li>
        <li><b style="color:{_ht};">Rolled calendars</b> — front-month expiry rolls may appear as separate closed trades rather than one continuous position. Needs real data to verify.</li>
        <li><b style="color:{_ht};">Reverse Jade Lizard</b> — detected as a Jade Lizard but capital risk may be understated (max loss is on the call side). Verify if you trade this structure.</li>
        <li><b style="color:{_ht};">0DTE trades</b> — P/L is correct, but Ann Return %, Med Premium/Day, and Wheel Campaigns are less meaningful for same-day holds.</li>
        <li><b style="color:{_ht};">Non-US accounts</b> — built and tested on a US TastyTrade account. Currency, tax treatment, and CSV format differences for other regions are unknown.</li>
        </ul>
        </div>

        <p style="color:{_td};font-size:0.78rem;margin-top:1.5rem;text-align:center;">
        TastyMechanics {APP_VERSION} · Open source · AGPL-3.0 ·
        <a href="https://github.com/crux1s/TastyMechanics" style="color:{_bl};">GitHub</a> ·
        <a href="https://www.buymeacoffee.com/Cruxis" style="color:#ffdd00;">Buy me a coffee</a> ·
        <a href="https://tastytrade.com/welcome/?referralCode=NT57Z3P85B" style="color:{_bl};">Open a TastyTrade account</a>
        </p>

        </div>
        """, unsafe_allow_html=True)
        st.stop()
    # ── Cached data loading ────────────────────────────────────────────────────────

    @st.cache_data(max_entries=2, show_spinner='📂 Loading CSV…')
    def load_and_parse(file_bytes: bytes) -> ParsedData:
        """
        Thin Streamlit cache wrapper around ingestion.parse_csv().
        Cached on raw file bytes — re-runs only when a new file is uploaded.
        The actual parsing logic lives in ingestion.py and is independently
        importable and testable without a running Streamlit server.
        """
        return parse_csv(file_bytes)


    @st.cache_data(show_spinner='⚙️ Building campaigns…')
    def build_all_data(_parsed: ParsedData, use_lifetime: bool, file_hash: int) -> AppData:
        """
        Thin Streamlit cache wrapper around mechanics.compute_app_data().
        Cached separately from load_and_parse so that toggling Lifetime mode
        only re-runs campaign logic, not the CSV parse.
        _parsed is prefixed with _ so Streamlit skips hashing the full DataFrame.
        file_hash is a hashable int derived from the raw bytes — ensures the cache
        invalidates when a new file is uploaded, even if use_lifetime is unchanged.
        """
        return compute_app_data(_parsed, use_lifetime)

    @st.cache_data(show_spinner=False)
    def get_daily_pnl(_df: pd.DataFrame, file_hash: int) -> pd.DataFrame:
        """
        Daily realized P/L series — FIFO-correct, whole portfolio.
        Cached on the full df — re-runs only when a new file is uploaded.
        Window slicing is done downstream by the caller.
        _df is prefixed with _ so Streamlit skips hashing the full DataFrame.
        file_hash ensures cache invalidation when a new CSV is uploaded.
        """
        return calculate_daily_realized_pnl(_df, _df['Date'].min())



    # ── Validate + load ────────────────────────────────────────────────────────────
    _raw_bytes  = uploaded_file.getvalue()
    _file_hash  = _hashlib.md5(_raw_bytes).hexdigest()  # content-stable hash — safe across processes and Streamlit Cloud restarts
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

    # ── Lifetime toggle — lives in tab3 but affects whole-app data ──────────────
    use_lifetime = st.session_state.get('use_lifetime', False)

    # ── Unpack cached heavy computation ───────────────────────────────────────────
    _d = build_all_data(_parsed, use_lifetime, _file_hash)
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
        closed_camp_pnl, open_premiums_banked, capital_deployed = _aggregate_campaign_pnl(
            all_campaigns, use_lifetime
        )
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

    # ── Realized ROR — computed here so it always reflects the final total_realized_pnl,
    # whether or not the zero-cost exclusion filter was applied above.
    # net_deposited uses the original df (deposits/withdrawals are never filtered out).
    total_deposited = df[df['Sub Type']=='Deposit']['Total'].sum()
    total_withdrawn = df[df['Sub Type']=='Withdrawal']['Total'].sum()
    net_deposited   = total_deposited + total_withdrawn
    if net_deposited > 0:
        realized_ror = total_realized_pnl / net_deposited * 100
    elif net_deposited == 0:
        realized_ror = None          # undefined — no net deposits
    else:
        realized_ror = None          # negative net deposits — house money, ROR is infinite

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

    # Map each period label to the corresponding start_date.
    # lambdas are evaluated lazily so latest_date and df are captured at call time.
    _WINDOW_START = {
        'All Time':       lambda: df['Date'].min(),
        'YTD':            lambda: pd.Timestamp(latest_date.year, 1, 1),
        'Last 7 Days':    lambda: latest_date - timedelta(days=7),
        'Last Month':     lambda: latest_date - timedelta(days=30),
        'Last 3 Months':  lambda: latest_date - timedelta(days=90),
        'Half Year':      lambda: latest_date - timedelta(days=182),
        '1 Year':         lambda: latest_date - timedelta(days=365),
    }
    start_date = _WINDOW_START.get(selected_period, lambda: df['Date'].min())()

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
    _daily_pnl_all = get_daily_pnl(df, _file_hash)
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
    # total_deposited, total_withdrawn, net_deposited, realized_ror — computed earlier,
    # after the zero-cost exclusion block, so they always reflect the final total_realized_pnl.
    first_date      = df['Date'].min()
    account_days    = (latest_date - first_date).days
    cash_balance    = df['Total'].cumsum().iloc[-1]
    margin_loan     = abs(cash_balance) if cash_balance < 0 else 0.0

    # ── Window label helper — used in section titles throughout ───────────────────
    _win_start_str = start_date.strftime('%d/%m/%Y')
    _win_end_str   = latest_date.strftime('%d/%m/%Y')
    _win_label     = (f'<span style="font-size:0.75rem;font-weight:400;color:' + COLOURS['blue'] + ';'
                      f'letter-spacing:0.02em;margin-left:8px;">'
                      f'{_win_start_str} → {_win_end_str} ({selected_period})</span>')
    # Plain text version for plotly chart titles (no HTML)
    _win_suffix    = f'  ·  {_win_start_str} → {_win_end_str}'

    # ── Debug export (for test suite comparison) ──────────────────────────────────
    if _os.environ.get('TASTYMECHANICS_TEST') == '1':
        _write_test_snapshot({
            'df':                   df,
            'all_campaigns':        all_campaigns,
            'wheel_tickers':        wheel_tickers,
            'pure_options_tickers': pure_options_tickers,
            'pure_opts_per_ticker': pure_opts_per_ticker,
            'total_realized_pnl':   total_realized_pnl,
            'window_realized_pnl':  window_realized_pnl,
            'prior_period_pnl':     prior_period_pnl,
            'selected_period':      selected_period,
            'closed_camp_pnl':      closed_camp_pnl,
            'open_premiums_banked': open_premiums_banked,
            'pure_opts_pnl':        pure_opts_pnl,
            '_all_time_income':     _all_time_income,
            '_wheel_divs_in_camps': _wheel_divs_in_camps,
            '_w_opts':              _w_opts,
            '_eq_pnl':              _eq_pnl,
            '_w_div_int':           _w_div_int,
            'total_deposited':      total_deposited,
            'total_withdrawn':      total_withdrawn,
            'net_deposited':        net_deposited,
            'capital_deployed':     capital_deployed,
            'realized_ror':         realized_ror,
            'div_income':           div_income,
            'int_net':              int_net,
            'latest_date':          latest_date,
        })

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
    m1.caption('Total realised P/L — options premiums, share sales, and dividends. ' + ('Full account history.' if _is_all_time else 'Filtered to selected window.') + ' Unrealised share gains not included.')
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
        m2.caption('Realised P/L as a % of net deposits — how hard your capital is working. Excludes unrealised gains.')

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
    m3.caption('Annualised return on capital in shares (Window P/L ÷ Capital Deployed × 365 ÷ Window Days). Changes with the time window. Benchmark: S&P ~10%/yr.' if cap_eff_score is not None else 'No capital currently deployed in share positions.')
    m4.metric('Capital Deployed',fmt_dollar(capital_deployed))
    m4.caption('Cash tied up in open share positions — wheel campaigns and fractional holdings. Options margin not included.')
    m5.metric('Margin Loan',     fmt_dollar(margin_loan))
    m5.caption('Your current broker debt — the negative cash balance. Zero is ideal unless you are deliberately leveraging.')
    m6.metric('Div + Interest',  fmt_dollar(div_income + int_net))
    m6.caption('Dividends received plus net interest (credit earned minus margin debit). Filtered to the selected time window.')
    m7.metric('Account Age',     '%d days' % account_days)
    m7.caption('Days since your first transaction — how long your track record covers. Longer means more reliable statistics.')


    # ── Realized P/L Breakdown — inline chip line ─────────────────────────────────
    if _is_all_time:
        _breakdown_html = (
            _pnl_chip('Closed Wheel Campaigns', closed_camp_pnl) +
            _pnl_chip('Open Wheel Premiums', open_premiums_banked) +
            _pnl_chip('General Standalone Trading', pure_opts_pnl) +
            f'<span style="color:' + COLOURS['text_dim'] + ';margin:0 6px;font-size:0.78rem;">·</span>'
            f'<span style="color:' + COLOURS['text_muted'] + ';font-size:0.78rem;font-style:italic;">All Time</span>'
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
        _delta_col  = COLOURS['green'] if _pnl_delta >= 0 else COLOURS['red']
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
            f'<div style="background:linear-gradient(135deg,' + COLOURS['card_bg'] + ',' + COLOURS['card_bg2'] + ');border:1px solid ' + COLOURS['border'] + ';'
            f'border-radius:10px;padding:14px 18px;margin:0 0 20px 0;">'
            f'<div style="color:' + COLOURS['text_muted'] + ';font-size:0.72rem;text-transform:uppercase;'
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

    with tab0: render_tab0(df_open, _expiry_alerts, latest_date)
    with tab1: render_tab1(closed_trades_df, all_cdf, credit_cdf, has_credit, has_data,
                           df_window, start_date, latest_date, window_label,
                           _win_label, _win_suffix)
    with tab2: render_tab2(closed_trades_df, all_cdf, credit_cdf, has_credit, has_data,
                           df_window, _win_label, _win_suffix, _win_start_str, _win_end_str)
    with tab3: render_tab3(all_campaigns, df, latest_date, start_date, use_lifetime)
    with tab4: render_tab4(all_campaigns, df, _daily_pnl, _daily_pnl_all,
                           pure_options_tickers, pure_opts_per_ticker,
                           capital_deployed, start_date, latest_date,
                           _is_all_time, selected_period, _win_label, _win_suffix,
                           use_lifetime)
    with tab5: render_tab5(df_window, total_deposited, total_withdrawn,
                           div_income, int_net, _win_label)

    # ── Report download (sidebar) ─────────────────────────────────────────────
    with st.sidebar:
        st.markdown('---')
        st.markdown('#### 📄 Export Report')
        if has_data:
            # Fees computed same way as render_tab1
            _rpt_opt_rows = df_window[
                df_window['Instrument Type'].isin(OPT_TYPES) &
                df_window['Type'].isin(TRADE_TYPES)
            ]
            _rpt_total_fees = (
                _rpt_opt_rows['Commissions'].apply(abs).sum() +
                _rpt_opt_rows['Fees'].apply(abs).sum()
            )
            _report_html = build_html_report(
                all_cdf, credit_cdf, has_credit, has_data,
                df_window, start_date, latest_date,
                window_label, _win_suffix, _win_start_str, _win_end_str,
                window_realized_pnl=window_realized_pnl,
                total_realized_pnl=total_realized_pnl,
                div_income=div_income,
                int_net=int_net,
                total_fees=_rpt_total_fees,
                net_deposited=total_deposited,
                selected_period=selected_period,
            )
            _report_fname = 'tastymechanics_report_%s.html' % _win_start_str.replace('/', '-')
            st.download_button(
                label='⬇️ Download HTML Report',
                data=_report_html,
                file_name=_report_fname,
                mime='text/html',
                use_container_width=True,
                help='Self-contained HTML report with scorecard, charts & ticker performance for the selected window.',
            )
        else:
            st.caption('Upload data to enable report export.')





# ══════════════════════════════════════════════════════════════════════════════
# TAB RENDERERS  (one file per tab in tabs/)
# ══════════════════════════════════════════════════════════════════════════════
from tabs.tab0_open_positions   import render_tab0
from tabs.tab1_derivatives      import render_tab1
from tabs.tab2_trade_analysis   import render_tab2
from tabs.tab3_wheel_campaigns  import render_tab3
from tabs.tab4_all_trades       import render_tab4
from tabs.tab5_deposits         import render_tab5


main()
