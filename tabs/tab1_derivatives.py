"""
tabs/tab1_derivatives.py — Tab1 Derivatives tab renderer.
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


def render_tab1(closed_trades_df, all_cdf, credit_cdf, has_credit, has_data,
                df_window, start_date, latest_date, window_label, _win_label, _win_suffix):
    """Tab 1 — Derivatives Performance: scorecard, call/put breakdown, per-ticker table."""
    if closed_trades_df.empty:
        st.info('No closed trades found.')
        return
    st.info(window_label)
    st.markdown(f'#### 🎯 Premium Selling Scorecard {_win_label}', unsafe_allow_html=True)
    st.caption((
        'Credit trades only. '
        '**Win Rate** = %% of trades closed positive, regardless of size. '
        '**Median Capture %%** = typical %% of opening credit kept at close — TastyTrade targets 50%%. '
        '**Median Days Held** = typical time in a trade, resistant to outliers. '
        '**Median Ann. Return** = typical annualised return on capital at risk, capped at ±%d%% to prevent '
        '0DTE trades producing meaningless numbers — treat with caution on small sample sizes. '
        '**Med Premium/Day** = median credit-per-day across individual trades. '
        '**Banked $/Day** = realized P/L divided by window days — what you actually kept after all buybacks.'
    ) % ANN_RETURN_CAP)
    dm1, dm2, dm3, dm4, dm5, dm6 = st.columns(6)
    if has_credit:
        total_credit_rcvd    = credit_cdf['Net Premium'].sum()
        total_net_pnl_closed = credit_cdf['Net P/L'].sum()
        window_days = max((latest_date - start_date).days, 1)
        dm1.metric('Win Rate',           '%.1f%%' % (credit_cdf['Won'].mean() * 100))
        dm2.metric('Median Capture %',   '%.1f%%' % credit_cdf['Capture %'].median())
        dm3.metric('Median Days Held',   '%.0f'   % credit_cdf['Days Held'].median())
        dm4.metric('Median Ann. Return', '%.0f%%' % credit_cdf['Ann Return %'].median())
        dm5.metric('Med Premium/Day',    fmt_dollar(credit_cdf['Prem/Day'].median()))
        dm6.metric('Banked $/Day', fmt_dollar(total_net_pnl_closed / window_days),
            delta='vs $%.2f gross' % (total_credit_rcvd / window_days), delta_color='normal')

        _winners = all_cdf[all_cdf['Net P/L'] > 0]['Net P/L']
        _losers  = all_cdf[all_cdf['Net P/L'] < 0]['Net P/L']
        _avg_win  = _winners.mean() if not _winners.empty else 0.0
        _avg_loss = _losers.mean()  if not _losers.empty  else 0.0
        _ratio         = abs(_avg_win / _avg_loss) if _avg_loss != 0 else None
        _gross_profit  = credit_cdf[credit_cdf['Net P/L'] > 0]['Net P/L'].sum()
        _gross_loss    = abs(credit_cdf[credit_cdf['Net P/L'] <= 0]['Net P/L'].sum())
        _profit_factor = _gross_profit / _gross_loss if _gross_loss > 0 else float('inf')
        _w_option_rows = df_window[
            df_window['Instrument Type'].isin(OPT_TYPES) & df_window['Type'].isin(TRADE_TYPES)
        ]
        _total_fees = (_w_option_rows['Commissions'].apply(abs).sum() +
                       _w_option_rows['Fees'].apply(abs).sum())
        _fees_pct = _total_fees / abs(total_net_pnl_closed) * 100 if total_net_pnl_closed != 0 else 0.0

        st.markdown('---')
        r1, r2, r3, r4, r5, r6, r7 = st.columns(7)
        r1.metric('Avg Winner',     fmt_dollar(_avg_win))
        r1.caption('Mean P/L of all winning trades.')
        r2.metric('Avg Loser',      fmt_dollar(_avg_loss))
        r2.caption('Mean P/L of all losing trades.')
        r3.metric('Win/Loss Ratio', '%.2f×' % _ratio if _ratio is not None else '∞')
        r3.caption('Avg Winner ÷ Avg Loser. ∞ = no losing trades in this window.')
        r4.metric('Total Fees',     fmt_dollar(_total_fees))
        r4.caption('Commissions + exchange fees on option trades in this window.')
        r5.metric('Fees % of P/L',  '%.1f%%' % _fees_pct)
        r5.caption('Total fees as a percentage of net realized P/L.')
        r6.metric('Fees/Trade',     fmt_dollar(_total_fees / len(all_cdf) if len(all_cdf) > 0 else 0))
        r6.caption('Average fee cost per closed trade.')
        r7.metric('Profit Factor',  '%.2f' % _profit_factor if _profit_factor != float('inf') else '∞')
        r7.caption('Gross profit ÷ gross loss. >1 = net positive. The higher the better.')
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
                colors = [COLOURS['red'], '#ffa421', '#ffe066', '#7ec8e3', COLOURS['green'], COLOURS['blue']]
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
                    Win_Rate=('Won', lambda x: x.mean() * 100),
                    Med_Capture=('Capture %', 'median'),
                    Total_PNL=('Net P/L', 'sum'),
                    Avg_PremDay=('Prem/Day', 'mean'),
                    Med_Days=('Days Held', 'median'),
                    Med_DTE=('DTE at Open', 'median'),
                ).reset_index().round(1)
                type_df.columns = ['Type', 'Trades', 'Win %', 'Capture %', 'P/L', 'Prem/Day', 'Days', 'DTE']
                st.markdown(f'##### 📊 Call vs Put Performance {_win_label}', unsafe_allow_html=True)
                st.dataframe(type_df.style.format({
                    'Win %':     lambda x: '{:.1f}%'.format(x),
                    'Capture %': lambda x: '{:.1f}%'.format(x),
                    'P/L':       fmt_dollar,
                    'Prem/Day':  lambda x: '${:.2f}'.format(x),
                    'Days':      lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                    'DTE':       lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                }).map(color_win_rate, subset=['Win %'])
                .map(lambda v: 'color: #00cc96' if isinstance(v, (int, float)) and v > 0
                    else ('color: #ef553b' if isinstance(v, (int, float)) and v < 0 else ''),
                    subset=['P/L']),
                width='stretch', hide_index=True)

        if has_data and has_credit:
            strat_df = all_cdf.groupby('Trade Type').agg(
                Trades=('Won', 'count'),
                Win_Rate=('Won', lambda x: x.mean() * 100),
                Total_PNL=('Net P/L', 'sum'),
                Med_Capture=('Capture %', 'median'),
                Med_Days=('Days Held', 'median'),
                Med_DTE=('DTE at Open', 'median'),
            ).reset_index().sort_values('Total_PNL', ascending=False).round(1)
            strat_df.columns = ['Strategy', 'Trades', 'Win %', 'P/L', 'Capture %', 'Days', 'DTE']
            st.markdown(f'##### 🧩 Defined vs Undefined Risk — by Strategy {_win_label}', unsafe_allow_html=True)
            st.dataframe(strat_df.style.format({
                'Win %':     lambda x: '{:.1f}%'.format(x),
                'Capture %': lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                'P/L':       fmt_dollar,
                'Days':      lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                'DTE':       lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
            }).map(color_win_rate, subset=['Win %'])
            .map(lambda v: 'color: #00cc96' if isinstance(v, (int, float)) and v > 0
                else ('color: #ef553b' if isinstance(v, (int, float)) and v < 0 else ''),
                subset=['P/L']),
            width='stretch', hide_index=True)

        st.markdown('---')
        st.markdown(f'#### Performance by Ticker {_win_label}', unsafe_allow_html=True)
        st.caption((
            'All closed trades grouped by underlying. '
            '**Win %%** counts any trade that closed positive. '
            '**Med Capture %%** = median %% of opening credit kept — credit trades only. '
            '**Med Ann Ret %%** = median annualised return on capital at risk, capped at ±%d%% '
            'to prevent 0DTE and short-dated trades producing meaningless numbers — '
            'values shown in orange hit the cap. '
            '**Total Prem Sold** = gross cash received opening credit trades, before buybacks.'
        ) % ANN_RETURN_CAP)
        all_by_ticker = all_cdf.groupby('Ticker').agg(
            Trades=('Net P/L', 'count'),
            Win_Rate=('Won', lambda x: x.mean() * 100),
            Total_PNL=('Net P/L', 'sum'),
            Med_Days=('Days Held', 'median'),
        ).round(1)
        if has_credit:
            credit_by_ticker = credit_cdf.groupby('Ticker').agg(
                Med_Capture=('Capture %', 'median'),
                Med_Ann=('Ann Return %', 'median'),
                Total_Prem=('Net Premium', 'sum'),
            ).round(1)
            ticker_df = all_by_ticker.join(credit_by_ticker, how='left').reset_index()
        else:
            ticker_df = all_by_ticker.reset_index()
            ticker_df['Med_Capture'] = None
            ticker_df['Med_Ann']     = None
            ticker_df['Total_Prem']  = None
        ticker_df = ticker_df.sort_values('Total_PNL', ascending=False)
        ticker_df.columns = ['Ticker', 'Trades', 'Win %', 'P/L', 'Days Held',
                              'Capture %', 'Ann Ret %', 'Total Net Prem']

        def _style_ticker_ann_ret(col):
            return [
                'color: #ffa500' if pd.notna(v) and abs(v) >= ANN_RETURN_CAP else ''
                for v in col
            ]

        st.dataframe(
            ticker_df.style.format({
                'Win %':           lambda x: '{:.1f}%'.format(x),
                'P/L':             fmt_dollar,
                'Days Held':       lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                'Capture %':       lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                'Ann Ret %':       lambda v: '{:.0f}%'.format(v) if pd.notna(v) else '—',
                'Total Net Prem': lambda v: '${:.2f}'.format(v) if pd.notna(v) else '—',
            }).apply(_style_ticker_ann_ret, subset=['Ann Ret %'])
             .map(color_win_rate, subset=['Win %'])
             .map(color_pnl_cell, subset=['P/L']),
            width='stretch', hide_index=True
        )


