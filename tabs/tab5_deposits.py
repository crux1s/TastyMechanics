"""
tabs/tab5_deposits.py — Tab5 Deposits tab renderer.
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


def render_tab5(df_window, total_deposited, total_withdrawn, div_income, int_net, _win_label):
    """Tab 5 — Deposits, Dividends & Fees: money movement table for the selected window."""
    st.markdown(f'### 💰 Deposits, Dividends & Fees {_win_label}', unsafe_allow_html=True)
    ic1, ic2, ic3, ic4 = st.columns(4)
    ic1.metric('Deposited',      fmt_dollar(total_deposited))
    ic2.metric('Withdrawn',      fmt_dollar(abs(total_withdrawn)))
    ic3.metric('Dividends',      fmt_dollar(div_income))
    ic4.metric('Interest (net)', fmt_dollar(int_net))
    income_df = df_window[df_window['Sub Type'].isin(DEPOSIT_SUB_TYPES)][
        ['Date', 'Ticker', 'Sub Type', 'Description', 'Total']
    ].sort_values('Date', ascending=False)
    if not income_df.empty:
        st.dataframe(
            income_df.style.apply(_color_cash_row, axis=1)
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

