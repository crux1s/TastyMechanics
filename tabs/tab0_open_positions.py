"""
tabs/tab0_open_positions.py — Tab0 Open Positions tab renderer.
"""

import streamlit as st
import pandas as pd
from typing import List, Dict, Any

from ui_components import (
    identify_pos_type, translate_readable, detect_strategy,
    _dte_chip, render_position_card,
)
from ingestion import equity_mask, option_mask
from mechanics import calc_dte


def render_tab0(df_open: pd.DataFrame, _expiry_alerts: List[Dict[str, Any]], latest_date: pd.Timestamp) -> None:
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
    col_a, col_b = st.columns(2, gap='medium')
    for i, ticker in enumerate(tickers_open):
        t_df = df_open[df_open['Ticker'] == ticker].copy()
        card_html = render_position_card(ticker, t_df)
        if i % 2 == 0:
            col_a.markdown(card_html, unsafe_allow_html=True)
        else:
            col_b.markdown(card_html, unsafe_allow_html=True)


