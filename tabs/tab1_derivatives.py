"""
tabs/tab1_derivatives.py — Tab1 Derivatives tab renderer.
"""

from __future__ import annotations

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
    WIN_RATE_GREEN, WIN_RATE_ORANGE,
    DAILY_THETA_GREEN, DAILY_THETA_ORANGE,
)
from ui_components import (
    xe, is_share_row, is_option_row,
    identify_pos_type, translate_readable, format_cost_basis, detect_strategy,
    fmt_dollar, color_win_rate, color_pnl_cell,
    _pnl_chip, _cmp_block, _dte_chip,
    _fmt_ann_ret, _style_ann_ret, _style_chain_row, _style_risk_row,
    _color_cash_row, _color_cash_total,
    chart_layout, _badge_inline_style, render_position_card,
    color_daily_theta,
)
from ingestion import equity_mask, option_mask
from mechanics import (
    _iter_fifo_sells, build_option_chains,
    effective_basis, realized_pnl, calc_dte,
)

_SECTION_LABEL = (
    'font-size:10px;font-weight:700;letter-spacing:0.1em;'
    'opacity:0.55;text-transform:uppercase'
)


def render_tab1(
    closed_trades_df: pd.DataFrame,
    all_cdf: pd.DataFrame,
    credit_cdf: pd.DataFrame,
    has_credit: bool,
    has_data: bool,
    df_window: pd.DataFrame,
    start_date: pd.Timestamp,
    latest_date: pd.Timestamp,
    window_label: str,
    _win_label: str,
    _win_suffix: str,
) -> None:
    """Tab 1 — Derivatives Performance: scorecard, call/put breakdown, per-ticker table."""
    if closed_trades_df.empty:
        st.info('No closed trades found.')
        return
    st.info(window_label)
    st.markdown(f'#### 🎯 Premium Selling Scorecard {_win_label}', unsafe_allow_html=True)
    st.caption('Credit trades only. Hover the ℹ on each metric for details.')
    if has_credit:
        total_credit_rcvd    = credit_cdf['Net Premium'].sum()
        total_net_pnl_closed = credit_cdf['Net P/L'].sum()
        window_days = max((latest_date - start_date).days, 1)

        _net_keep_pct = (total_net_pnl_closed / total_credit_rcvd * 100
                         if total_credit_rcvd != 0 else 0.0)

        st.markdown(f'<span style="{_SECTION_LABEL}">Trade Quality</span>', unsafe_allow_html=True)
        dm1, dm2, dm3, dm4, dm5, dm6, dm7, dm8 = st.columns(8)
        dm1.metric('Win Rate',           '%.1f%%' % (credit_cdf['Won'].mean() * 100),
            help='% of credit trades closed at a profit, regardless of size.')
        dm2.metric('Median Capture %',   '%.1f%%' % credit_cdf['Capture %'].median(),
            help='Typical % of opening credit kept at close, per trade. TastyTrade targets 50% — close the trade when half the premium has decayed.')
        dm3.metric('Net Premium Kept %', '%.1f%%' % _net_keep_pct,
            delta='%.1f%% vs 25%% target' % (_net_keep_pct - 25.0),
            delta_color='normal',
            help=(
                'Portfolio-level: total net P/L ÷ total gross premium collected. '
                'The answer to "of everything I sold, what did I actually keep?" after all buybacks and losses. '
                'TastyTrade targets ~25% — the maths of closing at 50% profit with a ~50% win rate. '
                'Anything above 25% is ahead of plan.'
            ))
        dm4.metric('Median Days in Trade', '%.0f' % credit_cdf['Days Held'].median(),
            help='Typical number of days a position was held. Median is used rather than mean to reduce the effect of outliers.')
        dm5.metric('Median Ann. Return', '%.0f%%' % credit_cdf['Ann Return %'].median(),
            help='Typical annualised return on capital at risk, capped at ±%d%% to stop 0DTE trades producing astronomical figures. Treat with caution on small samples.' % ANN_RETURN_CAP)
        dm6.metric('Med Premium/Day',    fmt_dollar(credit_cdf['Prem/Day'].median()),
            help='Median credit collected per day held, across individual trades. Measures theta efficiency per position.')
        dm7.metric('Kept $/Day', fmt_dollar(total_net_pnl_closed / window_days),
            delta='vs $%.2f gross/day' % (total_credit_rcvd / window_days), delta_color='normal',
            help='Net realized P/L divided by the number of calendar days in this window — what you actually kept per day after all buybacks and losses. Delta shows gross premium collected per day for comparison.')
        _med_daily_theta = credit_cdf['Daily θ %'].median()
        dm8.metric('Med Daily θ %',
            '%.2f%%' % _med_daily_theta if pd.notna(_med_daily_theta) else '—',
            help='Median daily credit yield per unit of max risk (Prem/Day ÷ Capital at Risk × 100). '
                 'Trade entry quality score — was the trade worth putting on at the time? '
                 'Green ≥ %.2f%%, orange ≥ %.2f%%.' % (DAILY_THETA_GREEN, DAILY_THETA_ORANGE))

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
        st.markdown(f'<span style="{_SECTION_LABEL}">Risk & Fees</span>', unsafe_allow_html=True)
        r1, r2, r3, r4, r5, r6, r7 = st.columns(7)
        r1.metric('Avg Winner',     fmt_dollar(_avg_win),
            help='Mean P/L of all winning trades (Net P/L > 0).')
        r2.metric('Avg Loser',      fmt_dollar(_avg_loss),
            help='Mean P/L of all losing trades (Net P/L < 0).')
        r3.metric('Win/Loss Ratio', '%.2f×' % _ratio if _ratio is not None else '∞',
            help='Avg Winner ÷ Avg Loser in absolute terms. A ratio above 1× means your average win is larger than your average loss. ∞ = no losing trades in this window.')
        r4.metric('Total Fees',     fmt_dollar(_total_fees),
            help='Total commissions and exchange fees paid on option trades in this window.')
        r5.metric('Fees % of P/L',  '%.1f%%' % _fees_pct,
            help='Total fees as a percentage of net realized P/L. High values mean fees are consuming a significant share of profits.')
        r6.metric('Fees/Trade',     fmt_dollar(_total_fees / len(all_cdf) if len(all_cdf) > 0 else 0),
            help='Average fee cost per closed trade. Useful for comparing fee drag across different account sizes or brokers.')
        r7.metric('Profit Factor',  '%.2f' % _profit_factor if _profit_factor != float('inf') else '∞',
            help='Gross profit ÷ gross loss. Above 1.0 = net profitable. The higher the better — 1.5+ is generally considered solid for a premium-selling strategy.')
    else:
        st.info('No closed credit trades in this window.')

    if has_data:
        st.markdown('---')
        if has_credit:
            _PAIR_HEIGHT = 360  # shared height for chart and Call vs Put table
            _col_chart, _col_cvp = st.columns(2)

            with _col_chart:
                # ── Capture % Distribution chart ─────────────────────────────
                bins   = [-999, 0, 25, 50, 75, 100, 999]
                labels = ['Loss', '0–25%', '25–50%', '50–75%', '75–100%', '>100%']
                _cap_cdf = credit_cdf.copy()
                _cap_cdf['Bucket'] = pd.cut(_cap_cdf['Capture %'], bins=bins, labels=labels)
                bucket_df = _cap_cdf.groupby('Bucket', observed=False).agg(
                    Trades=('Net P/L', 'count')).reset_index()
                colors = [COLOURS['red'], '#ffa421', '#ffe066', '#7ec8e3', COLOURS['green'], COLOURS['blue']]
                fig_cap = px.bar(bucket_df, x='Bucket', y='Trades', color='Bucket',
                    color_discrete_sequence=colors, text='Trades')
                fig_cap.update_traces(textposition='outside', textfont_size=11, marker_line_width=0)
                _lay = chart_layout('Premium Capture % Distribution' + _win_suffix, height=_PAIR_HEIGHT, margin_t=40)
                _lay['showlegend'] = False
                _lay['xaxis']['title'] = dict(text='Capture Bucket', font=dict(size=11))
                _lay['yaxis']['title'] = dict(text='# Trades', font=dict(size=11))
                fig_cap.update_layout(**_lay)
                st.plotly_chart(fig_cap, width='stretch', config={'displayModeBar': False})
                st.caption(
                    'Bar colours — '
                    '<span style="color:%s">■</span> Loss &nbsp;'
                    '<span style="color:#ffa421">■</span> 0–25%% &nbsp;'
                    '<span style="color:#ffe066">■</span> 25–50%% &nbsp;'
                    '<span style="color:#7ec8e3">■</span> 50–75%% &nbsp;'
                    '<span style="color:%s">■</span> 75–100%% &nbsp;'
                    '<span style="color:%s">■</span> &gt;100%% (rolled / leveraged)'
                    % (COLOURS['red'], COLOURS['green'], COLOURS['blue']),
                    unsafe_allow_html=True,
                )

            with _col_cvp:
                # ── Call vs Put table ─────────────────────────────────────────
                st.markdown(f'##### 📊 Call vs Put Performance {_win_label}', unsafe_allow_html=True)
                type_df = credit_cdf.groupby('Type').agg(
                    Trades=('Won', 'count'),
                    Win_Rate=('Won', lambda x: x.mean() * 100),
                    Med_Capture=('Capture %', 'median'),
                    Total_PNL=('Net P/L', 'sum'),
                    Avg_PremDay=('Prem/Day', 'mean'),
                    Med_Days=('Days Held', 'median'),
                    Med_DTE=('DTE at Open', 'median'),
                ).reset_index().round(1)
                type_df.columns = ['Type', 'Trades', 'Win %', 'Capture %', 'P/L', 'Prem/Day', 'Med Days in Trade', 'DTE at Entry']
                _total_row = pd.DataFrame([{
                    'Type': '— Total',
                    'Trades': int(type_df['Trades'].sum()),
                    'Win %': round(credit_cdf['Won'].mean() * 100, 1),
                    'Capture %': round(credit_cdf['Capture %'].median(), 1),
                    'P/L': type_df['P/L'].sum(),
                    'Prem/Day': round(credit_cdf['Prem/Day'].median(), 1),
                    'Med Days in Trade': round(credit_cdf['Days Held'].median(), 1),
                    'DTE at Entry': round(credit_cdf['DTE at Open'].median(), 1),
                }])
                type_df_display = pd.concat([type_df, _total_row], ignore_index=True)
                st.dataframe(type_df_display.style.format({
                    'Win %':     lambda x: '{:.1f}%'.format(x),
                    'Capture %': lambda x: '{:.1f}%'.format(x),
                    'P/L':       fmt_dollar,
                    'Prem/Day':  lambda x: '${:.2f}'.format(x),
                    'Med Days in Trade': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                    'DTE at Entry':       lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                }).map(color_win_rate, subset=['Win %'])
                .map(lambda v: 'color: #00cc96' if isinstance(v, (int, float)) and v > 0
                    else ('color: #ef553b' if isinstance(v, (int, float)) and v < 0 else ''),
                    subset=['P/L']),
                width='stretch', hide_index=True, height=_PAIR_HEIGHT)

            # ── Strategy table — full width ───────────────────────────────────
            strat_df = all_cdf.groupby('Trade Type').agg(
                Trades=('Won', 'count'),
                Win_Rate=('Won', lambda x: x.mean() * 100),
                Total_PNL=('Net P/L', 'sum'),
                Med_Capture=('Capture %', 'median'),
                Med_Days=('Days Held', 'median'),
                Med_DTE=('DTE at Open', 'median'),
            ).reset_index().sort_values('Total_PNL', ascending=False).round(1)
            strat_df.columns = ['Strategy', 'Trades', 'Win %', 'P/L', 'Capture %', 'Med Days in Trade', 'DTE at Entry']
            strat_df['_risk'] = strat_df['Strategy'].map(
                all_cdf.groupby('Trade Type')['Spread'].first()
            )
            # Covered Call is defined risk — stock ownership fully covers the short call obligation.
            # Covered Straddle/Strangle retain undefined downside from the short put leg.
            strat_df.loc[strat_df['Strategy'] == 'Covered Call', '_risk'] = True

            def _risk_dot(risk):
                if risk is True:
                    return '🔵 '
                if risk is False:
                    return '🟠 '
                return ''
            strat_df['Strategy'] = strat_df.apply(
                lambda r: _risk_dot(r['_risk']) + str(r['Strategy']), axis=1
            )

            _strat_total = pd.DataFrame([{
                'Strategy': '— Total',
                'Trades': int(strat_df['Trades'].sum()),
                'Win %': round(all_cdf['Won'].mean() * 100, 1),
                'P/L': strat_df['P/L'].sum(),
                'Capture %': float('nan'),
                'Med Days in Trade': float('nan'),
                'DTE at Entry': float('nan'),
                '_risk': None,
            }])
            strat_df_display = pd.concat([strat_df, _strat_total], ignore_index=True)

            def _style_strat_row(row):
                """Risk tint for defined/undefined rows; dim low-count rows (< 5 trades)."""
                trades = row.get('Trades', 0)
                if pd.notna(trades) and int(trades) < 5 and row.get('Strategy', '') != '— Total':
                    return ['color: rgba(200,200,200,0.40); font-style:italic'] * len(row)
                risk = row.get('_risk', None)
                if risk is True:
                    return ['background-color: rgba(88,166,255,0.09)'] * len(row)
                if risk is False:
                    return ['background-color: rgba(255,165,0,0.08)'] * len(row)
                return [''] * len(row)

            st.markdown(f'##### 🧩 Defined vs Undefined Risk — by Strategy {_win_label}', unsafe_allow_html=True)
            st.caption('🔵 Defined risk (spread / protected)   🟠 Undefined risk (naked short)   Dim rows = fewer than 5 trades')
            st.dataframe(
                strat_df_display[['Strategy', 'Trades', 'Win %', 'P/L', 'Capture %', 'Med Days in Trade', 'DTE at Entry', '_risk']]
                .style.apply(_style_strat_row, axis=1)
                .format({
                    'Win %':     lambda x: '{:.1f}%'.format(x) if pd.notna(x) else '—',
                    'Capture %': lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                    'P/L':       fmt_dollar,
                    'Med Days in Trade': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                    'DTE at Entry':       lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                }).map(color_win_rate, subset=['Win %'])
                .map(lambda v: 'color: #00cc96' if isinstance(v, (int, float)) and v > 0
                    else ('color: #ef553b' if isinstance(v, (int, float)) and v < 0 else ''),
                    subset=['P/L']),
                width='stretch', hide_index=True,
                column_config={'_risk': None},
            )

        st.markdown('---')
        # ── Performance by Ticker — header with independent window selector ────
        _col_ticker_hdr, _col_ticker_win = st.columns([3, 2])
        with _col_ticker_win:
            _ticker_period = st.selectbox(
                'Table time window (override)',
                options=['YTD', 'Last 7 Days', 'Last Month', 'Last 3 Months', 'Half Year', '1 Year', 'All Time'],
                index=6,
                key='ticker_perf_window',
                help='Independent of the global time window above — shows a different date range for this table only.',
            )
        with _col_ticker_hdr:
            st.markdown(f'#### 📊 Performance by Ticker — {_ticker_period}', unsafe_allow_html=True)
        st.caption((
            'All closed trades grouped by underlying. '
            '**W/L** = wins and losses as separate counts. '
            '**Win %%** colour-coded: green ≥ %d%%, orange ≥ %d%%, red below. '
            '**Premium Capture** = median %% of opening credit kept at close — TastyTrade targets 50%%. '
            '**P/L per DIT** = total P/L ÷ avg days in trade — theta efficiency per ticker. '
            '**Med Ann Ret %%** capped at ±%d%% — ⚠ = capped value. '
            '**Dim rows** = fewer than 3 trades, small sample size.'
        ) % (WIN_RATE_GREEN, WIN_RATE_ORANGE, ANN_RETURN_CAP))

        # ── Slice closed_trades_df to the locally selected window ─────────────
        if _ticker_period == 'All Time':
            _ticker_cdf        = closed_trades_df
            _ticker_credit_cdf = (closed_trades_df[closed_trades_df['Is Credit']].copy()
                                  if not closed_trades_df.empty else pd.DataFrame())
        else:
            _TICKER_WINDOW = {
                'YTD':           pd.Timestamp(year=latest_date.year, month=1, day=1),
                'Last 7 Days':   latest_date - timedelta(days=7),
                'Last Month':    latest_date - timedelta(days=30),
                'Last 3 Months': latest_date - timedelta(days=90),
                'Half Year':     latest_date - timedelta(days=182),
                '1 Year':        latest_date - timedelta(days=365),
            }
            _ticker_start = _TICKER_WINDOW[_ticker_period]
            _ticker_cdf = closed_trades_df[
                closed_trades_df['Close Date'] >= _ticker_start
            ].copy()
            _ticker_credit_cdf = (_ticker_cdf[_ticker_cdf['Is Credit']].copy()
                                  if not _ticker_cdf.empty else pd.DataFrame())
        _ticker_has_credit = not _ticker_credit_cdf.empty

        if _ticker_cdf.empty:
            st.info('No closed trades in the selected window.')
        else:
            all_by_ticker = _ticker_cdf.groupby('Ticker').agg(
                Wins=('Won', 'sum'),
                Losses=('Won', lambda x: (x == 0).sum()),
                Trades=('Net P/L', 'count'),
                Win_Rate=('Won', lambda x: x.mean() * 100),
                Total_PNL=('Net P/L', 'sum'),
                Avg_Days=('Days Held', 'mean'),
            ).round(1)
            # W/L display string
            all_by_ticker['W/L'] = (
                all_by_ticker['Wins'].astype(int).astype(str) + '/' +
                all_by_ticker['Losses'].astype(int).astype(str)
            )
            # P/L per DIT — theta efficiency
            all_by_ticker['PnL_per_DTE'] = (
                all_by_ticker['Total_PNL'] / all_by_ticker['Avg_Days'].replace(0, float('nan'))
            ).round(2)

            if _ticker_has_credit:
                credit_by_ticker = _ticker_credit_cdf.groupby('Ticker').agg(
                    Med_Capture=('Capture %', 'median'),
                    Med_Ann=('Ann Return %', 'median'),
                    Med_Daily_Theta=('Daily θ %', 'median'),
                    Total_Prem=('Net Premium', 'sum'),
                ).round(2)
                ticker_df = all_by_ticker.join(credit_by_ticker, how='left').reset_index()
            else:
                ticker_df = all_by_ticker.reset_index()
                ticker_df['Med_Capture']     = None
                ticker_df['Med_Ann']         = None
                ticker_df['Med_Daily_Theta'] = None
                ticker_df['Total_Prem']      = None

            ticker_df = ticker_df.sort_values('Total_PNL', ascending=False)
            ticker_df = ticker_df[[
                'Ticker', 'W/L', 'Win_Rate', 'Total_PNL', 'Avg_Days',
                'PnL_per_DTE', 'Med_Capture', 'Med_Ann', 'Med_Daily_Theta', 'Total_Prem'
            ]]
            ticker_df.columns = [
                'Ticker', 'W/L', 'Win %', 'P/L',
                'Avg Days in Trade', 'P/L per DIT',
                'Premium Capture', 'Ann Ret %', 'Daily θ %', 'Total Net Prem'
            ]

            def _style_ticker_row(row):
                """Dim low-sample rows (< 3 trades)."""
                wins, losses = row['W/L'].split('/')
                total = int(wins) + int(losses)
                if total < 3:
                    return ['color: rgba(200,200,200,0.35); font-style:italic'] * len(row)
                return [''] * len(row)

            def _style_ticker_ann_ret(col):
                return [
                    'color: #ffa500' if pd.notna(v) and abs(v) >= ANN_RETURN_CAP else ''
                    for v in col
                ]

            def _color_capture(val):
                try:
                    v = float(val)
                except (TypeError, ValueError):
                    return ''
                if v >= 50: return f'color: {COLOURS["green"]}'
                if v >= 25: return f'color: {COLOURS["orange"]}'
                return f'color: {COLOURS["red"]}'

            def _fmt_ann_ret_capped(v):
                if not pd.notna(v):
                    return '—'
                if abs(v) >= ANN_RETURN_CAP:
                    return '⚠ {:.0f}%'.format(v)
                return '{:.0f}%'.format(v)

            st.dataframe(
                ticker_df.style.format({
                    'Win %':            lambda x: '{:.1f}%'.format(x),
                    'P/L':              fmt_dollar,
                    'Avg Days in Trade': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                    'P/L per DIT':      lambda v: '${:.2f}'.format(v) if pd.notna(v) else '—',
                    'Premium Capture':  lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                    'Ann Ret %':        _fmt_ann_ret_capped,
                    'Daily θ %':        lambda v: '{:.2f}%'.format(v) if pd.notna(v) else '—',
                    'Total Net Prem':   lambda v: '${:.2f}'.format(v) if pd.notna(v) else '—',
                }).bar(subset=['Win %'], color='rgba(88,166,255,0.18)', vmin=0, vmax=100)
                 .apply(_style_ticker_ann_ret, subset=['Ann Ret %'])
                 .apply(_style_ticker_row, axis=1)
                 .map(color_win_rate, subset=['Win %'])
                 .map(color_pnl_cell, subset=['P/L'])
                 .map(_color_capture, subset=['Premium Capture'])
                 .map(color_daily_theta, subset=['Daily θ %']),
                width='stretch', hide_index=True
            )
