"""
tabs/tab5_deposits.py — Tab5 Deposits tab renderer.
"""

import streamlit as st
import pandas as pd

from config import DEPOSIT_SUB_TYPES
from ui_components import (
    fmt_dollar,
    _color_cash_row, _color_cash_total,
)


def render_tab5(
    df_window: pd.DataFrame,
    total_deposited: float,
    total_withdrawn: float,
    div_income: float,
    int_net: float,
    _win_label: str
) -> None:
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

