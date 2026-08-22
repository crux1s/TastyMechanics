"""
tabs/tab0_open_positions.py — Tab0 Open Positions tab renderer.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st
import pandas as pd

from config import COLOURS
from models import Campaign
from ui_components import (
    identify_pos_type, translate_readable, detect_strategy,
    _dte_chip, render_position_card,
)
from ingestion import equity_mask, option_mask
from mechanics import calc_dte, effective_basis, remaining_lot_basis
from market_data import fetch_live_prices
from position_snapshot import build_position_snapshot


def render_tab0(
    df_open: pd.DataFrame,
    _expiry_alerts: list,
    latest_date: pd.Timestamp,
    all_campaigns: Optional[dict[str, list[Campaign]]] = None,
    all_cdf: Optional[pd.DataFrame] = None,
    credit_cdf: Optional[pd.DataFrame] = None,
    total_realized_pnl: float = 0.0,
    capital_deployed: float = 0.0,
    open_premiums_banked: float = 0.0,
) -> None:
    """Tab 0 — Active Positions: open position cards + expiry alert strip."""

    _c_hdr, _c_csv, _c_tog = st.columns([5, 1, 1])
    with _c_hdr:
        st.subheader('📡 Open Positions')
    # _c_csv is filled later, after live_prices + _camp_lookup are available.
    with _c_tog:
        live_on = st.toggle(
            '📡 Live',
            key='live_prices_on',
            help=(
                'Fetch current equity quotes and option marks from Yahoo Finance. '
                'Equity prices are near real-time during market hours; '
                'options are delayed ~15 min. Ticker symbols are sent to Yahoo Finance.'
            ),
        )
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

    live_prices: dict = {}
    if live_on:
        tickers_frozen = frozenset(tickers_open) | {'SPY'}  # SPY needed for beta-weighted delta

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
                    'beta': data.get('beta'),   # pass through for BWD calculation
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

    # ── Campaign lookup: ticker → most recent open Campaign with shares ───────
    _use_lifetime = st.session_state.get('use_lifetime', False)
    _camp_lookup: dict = {}
    if all_campaigns:
        for _t, _cs in all_campaigns.items():
            _open_c = [_c for _c in _cs if _c.status == 'open' and _c.total_shares > 0]
            if _open_c:
                _camp_lookup[_t] = _open_c[-1]

    # ── Position Snapshot download ────────────────────────────────────────────
    with _c_csv:
        if not df_open.empty:
            _snap_txt = build_position_snapshot(
                df_open=df_open,
                all_campaigns=all_campaigns,
                all_cdf=all_cdf if all_cdf is not None else pd.DataFrame(),
                credit_cdf=credit_cdf if credit_cdf is not None else pd.DataFrame(),
                live_prices=live_prices,
                latest_date=latest_date,
                total_realized_pnl=total_realized_pnl,
                capital_deployed=capital_deployed,
                open_premiums_banked=open_premiums_banked,
                use_lifetime=_use_lifetime,
            )
            st.download_button(
                label='⬇️ Snapshot',
                data=_snap_txt,
                file_name='position_snapshot.txt',
                mime='text/plain',
                use_container_width=True,
                help='Download a plain-text position snapshot with live marks, IV, and Greeks — ready to paste into any LLM.',
            )

    # ── Position cards ────────────────────────────────────────────────────────
    col_a, col_b = st.columns(2, gap='medium')
    for i, ticker in enumerate(tickers_open):
        t_df      = df_open[df_open['Ticker'] == ticker].copy()
        card_html = render_position_card(ticker, t_df, ticker_live=live_prices.get(ticker))

        # Append wheel campaign basis strip when this ticker has an open campaign
        _camp = _camp_lookup.get(ticker)
        if _camp:
            if _use_lifetime and _camp.total_shares > 0:
                _c_entry = (_camp.total_cost + _camp.premiums + _camp.dividends) / _camp.total_shares
                _c_effb  = _camp.blended_basis
            else:
                _c_entry = remaining_lot_basis(_camp)
                _c_effb  = effective_basis(_camp)
            _c_reduc = _c_entry - _c_effb
            _c_prems = _camp.premiums + _camp.dividends
            _mut     = COLOURS['text_muted']
            _grn     = COLOURS['green']
            _red     = COLOURS['red']

            # Unrealised P/L vs effective basis — only when live price is available
            _lp = live_prices.get(ticker, {})
            _lp_last = float(_lp.get('last', 0.0)) if _lp else 0.0
            if _lp_last and _camp.total_shares > 0:
                _unreal      = (_lp_last - _c_effb) * _camp.total_shares
                _u_col       = _grn if _unreal >= 0 else _red
                _u_sgn       = '+' if _unreal >= 0 else '-'
                _unreal_html = (
                    f'<div style="width:1px;height:28px;background:rgba(255,255,255,0.07);flex-shrink:0;"></div>'
                    f'<div><div style="font-size:0.65em;color:{_mut};">UNREAL (vs eff.)</div>'
                    f'<div style="font-family:monospace;font-size:0.88em;font-weight:700;color:{_u_col};">'
                    f'{_u_sgn}${abs(_unreal):,.2f}</div></div>'
                )
            else:
                _unreal_html = ''

            card_html += (
                f'<div style="margin-top:-4px;margin-bottom:12px;padding:7px 14px;'
                f'background:rgba(0,204,150,0.04);border-radius:0 0 8px 8px;'
                f'border:1px solid rgba(0,204,150,0.15);border-top:none;'
                f'display:flex;flex-wrap:wrap;align-items:center;gap:6px 20px;">'
                f'<div style="font-size:0.68em;color:{_mut};font-weight:600;'
                f'letter-spacing:0.04em;margin-right:4px;">🎯 WHEEL</div>'
                f'<div><div style="font-size:0.65em;color:{_mut};">ENTRY BASIS</div>'
                f'<div style="font-family:monospace;font-size:0.88em;font-weight:600;">'
                f'${_c_entry:.2f}/sh</div></div>'
                f'<div style="width:1px;height:28px;background:rgba(255,255,255,0.07);flex-shrink:0;"></div>'
                f'<div><div style="font-size:0.65em;color:{_mut};">EFF. BASIS</div>'
                f'<div style="font-family:monospace;font-size:0.88em;font-weight:700;color:{_grn};">'
                f'${_c_effb:.2f}/sh</div></div>'
                f'<div style="width:1px;height:28px;background:rgba(255,255,255,0.07);flex-shrink:0;"></div>'
                f'<div><div style="font-size:0.65em;color:{_mut};">BASIS REDUCED</div>'
                f'<div style="font-family:monospace;font-size:0.88em;font-weight:600;color:{_grn};">'
                f'▼ ${_c_reduc:.2f}/sh</div></div>'
                f'<div style="width:1px;height:28px;background:rgba(255,255,255,0.07);flex-shrink:0;"></div>'
                f'<div><div style="font-size:0.65em;color:{_mut};">PREMIUMS BANKED</div>'
                f'<div style="font-family:monospace;font-size:0.88em;font-weight:600;color:{_grn};">'
                f'${_c_prems:.2f}</div></div>'
                f'{_unreal_html}'
                f'</div>'
            )

        if i % 2 == 0:
            col_a.markdown(card_html, unsafe_allow_html=True)
        else:
            col_b.markdown(card_html, unsafe_allow_html=True)
