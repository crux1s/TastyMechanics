"""
tabs/tab0_open_positions.py — Tab0 Open Positions tab renderer.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta

from config import (
    OPT_TYPES, EQUITY_TYPE, TRADE_TYPES, MONEY_TYPES,
    SUB_SELL_OPEN, SUB_ASSIGNMENT, SUB_DIVIDEND, SUB_CREDIT_INT, SUB_DEBIT_INT,
    INCOME_SUB_TYPES, DEPOSIT_SUB_TYPES,
    PAT_CLOSE, PAT_EXPIR, PAT_ASSIGN, PAT_EXERCISE, PAT_CLOSING,
    WHEEL_MIN_SHARES, LEAPS_DTE_THRESHOLD, ROLL_CHAIN_GAP_DAYS,
    ANN_RETURN_CAP, COLOURS,
)
from ui_components import (
    xe, is_share_row, is_option_row,
    identify_pos_type, translate_readable, format_cost_basis, detect_strategy,
    fmt_dollar, color_win_rate, color_pnl_cell,
    _pnl_chip, _cmp_block, _dte_chip,
    _fmt_ann_ret, _style_ann_ret, _style_chain_row,
    _color_cash_row, _color_cash_total,
    chart_layout, _badge_inline_style, render_position_card,
)
from ingestion import equity_mask, option_mask
from mechanics import (
    _iter_fifo_sells, build_option_chains,
    effective_basis, realized_pnl, calc_dte,
)
from market_data import fetch_live_prices


def render_tab0(df_open, _expiry_alerts, latest_date):
    """Tab 0 — Active Positions: open position cards + expiry alert strip."""
    st.subheader('📡 Open Positions')
    if df_open.empty:
        st.info('No active positions.')
        return
    df_open['Status']  = df_open.apply(identify_pos_type, axis=1)
    df_open['Details'] = df_open.apply(translate_readable, axis=1)
    df_open['DTE'] = df_open.apply(lambda row: calc_dte(row, latest_date), axis=1)
    tickers_open = [t for t in sorted(df_open['Ticker'].unique()) if t != 'CASH']

    n_options = df_open[option_mask(df_open['Instrument Type'])].shape[0]
    n_shares  = df_open[equity_mask(df_open['Instrument Type'])].shape[0]
    strategies    = [detect_strategy(df_open[df_open['Ticker'] == t]) for t in tickers_open]
    unique_strats = list(dict.fromkeys(strategies))

    summary_pills = ''.join(
        f'<span style="display:inline-block;background:rgba(88,166,255,0.1);'
        f'border:1px solid rgba(88,166,255,0.2);border-radius:20px;padding:2px 10px;'
        f'font-size:0.75rem;color:#58a6ff;margin-right:6px;margin-bottom:6px;">{s}</span>'
        for s in unique_strats
    )
    st.markdown(
        f'<div style="margin-bottom:20px;color:#6b7280;font-size:0.85rem;">'
        f'<b style="color:#8b949e">{len(tickers_open)}</b> tickers &nbsp;·&nbsp; '
        f'<b style="color:#8b949e">{n_options}</b> option legs &nbsp;·&nbsp; '
        f'<b style="color:#8b949e">{n_shares}</b> share positions'
        f'</div><div style="margin-bottom:24px;">{summary_pills}</div>',
        unsafe_allow_html=True
    )
    if _expiry_alerts:
        _expiry_chips = ''.join(_dte_chip(a) for a in _expiry_alerts)
        st.markdown(
            f'<div style="margin:-4px 0 16px 0;display:flex;flex-wrap:wrap;align-items:center;">'
            f'<span style="color:#6b7280;font-size:0.75rem;margin-right:8px;">⏰ Expiring ≤21d</span>'
            f'{_expiry_chips}</div>',
            unsafe_allow_html=True
        )

    # ── Live prices toggle ────────────────────────────────────────────────────
    live_on = st.toggle(
        '📡 Live Prices',
        key='live_prices_on',
        help=(
            'Fetch current equity quotes and option marks from Yahoo Finance. '
            'Equity prices are near real-time during market hours; '
            'options are delayed ~15 min. Ticker symbols are sent to Yahoo Finance.'
        ),
    )

    live_prices: dict = {}
    if live_on:
        tickers_frozen = frozenset(tickers_open)

        # Build (ticker, expiry_ymd, strike, cp) specs for every open option leg,
        # keeping the original expiry string so we can remap after fetching.
        specs = []  # (ticker, expiry_original, expiry_ymd, strike, cp)
        opt_rows = df_open[option_mask(df_open['Instrument Type'])]
        for _, row in opt_rows.iterrows():
            try:
                expiry_ymd = pd.to_datetime(
                    row['Expiration Date'], dayfirst=False
                ).strftime('%Y-%m-%d')
                specs.append((
                    row['Ticker'],
                    str(row['Expiration Date']),
                    expiry_ymd,
                    float(row['Strike Price']),
                    str(row['Call or Put']).upper(),
                ))
            except Exception:
                pass

        option_specs_frozen = frozenset(
            (t, ey, s, cp) for t, _eo, ey, s, cp in specs
        )

        with st.spinner('Fetching live prices…'):
            raw_prices = fetch_live_prices(tickers_frozen, option_specs_frozen)

        if raw_prices and any(v['last'] > 0 for v in raw_prices.values()):
            # Remap option keys: yfinance uses YYYY-MM-DD; our rows use the
            # original CSV expiry string.  Build {ticker: {ymd: original}} then
            # re-key the options dict so render_position_card can look up without
            # any date parsing.
            ymd_to_orig: dict = {}
            for t, eo, ey, s, cp in specs:
                ymd_to_orig.setdefault(t, {})[ey] = eo

            for ticker, data in raw_prices.items():
                opts_remapped: dict = {}
                t_map = ymd_to_orig.get(ticker, {})
                for (ey, strike, cp), opt_data in data['options'].items():
                    orig = t_map.get(ey, ey)
                    opts_remapped[(orig, strike, cp)] = opt_data
                live_prices[ticker] = {
                    'last': data['last'],
                    'prev_close': data['prev_close'],
                    'options': opts_remapped,
                }
            st.caption(
                '📡 Prices: Yahoo Finance — equity near real-time, options ~15 min delayed. '
                'Cached 5 min. Ticker symbols sent to Yahoo Finance servers.'
            )
        else:
            from market_data import _YF_AVAILABLE
            if not _YF_AVAILABLE:
                st.warning(
                    '`yfinance` is not installed. Run `pip install yfinance` '
                    'in your Python environment and restart the app.'
                )
            else:
                st.warning(
                    'Live prices unavailable — Yahoo Finance returned no data. '
                    'Check your internet connection.'
                )

    # ── Position cards ────────────────────────────────────────────────────────
    col_a, col_b = st.columns(2, gap='medium')
    for i, ticker in enumerate(tickers_open):
        t_df = df_open[df_open['Ticker'] == ticker].copy()
        card_html = render_position_card(ticker, t_df, ticker_live=live_prices.get(ticker))
        if i % 2 == 0:
            col_a.markdown(card_html, unsafe_allow_html=True)
        else:
            col_b.markdown(card_html, unsafe_allow_html=True)
