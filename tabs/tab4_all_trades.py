"""
tabs/tab4_all_trades.py — Tab4 All Trades tab renderer.
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


def render_tab4(all_campaigns, df, _daily_pnl, _daily_pnl_all,
                pure_options_tickers, pure_opts_per_ticker,
                capital_deployed, start_date, latest_date,
                _is_all_time, selected_period, _win_label, _win_suffix,
                use_lifetime):
    """Tab 4 — All Trades: equity curve, per-ticker table, period charts, volatility metrics."""
    st.markdown(f'### 🔍 Realized P/L — All Tickers {_win_label}', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.8rem;color:#6b7280;margin-bottom:8px;line-height:1.5;">'
        'Full-history cumulative realized P/L — options, equity sales, dividends and interest. '
        'FIFO-correct. Shaded region = selected time window.</div>',
        unsafe_allow_html=True
    )

    if not _daily_pnl_all.empty:
        _eq_curve            = _daily_pnl_all.sort_values('Date').copy()
        _eq_curve['Cum P/L'] = _eq_curve['PnL'].cumsum()
        _eq_final = _eq_curve['Cum P/L'].iloc[-1]
        _eq_color = COLOURS['green'] if _eq_final >= 0 else COLOURS['red']
        _eq_fill  = 'rgba(0,204,150,0.10)' if _eq_final >= 0 else 'rgba(239,85,59,0.10)'
        _eq_curve['Peak']     = _eq_curve['Cum P/L'].cummax()
        _eq_curve['Drawdown'] = _eq_curve['Cum P/L'] - _eq_curve['Peak']

        _fig_eq2 = go.Figure()
        if (_eq_curve['Drawdown'] < 0).any():
            _fig_eq2.add_trace(go.Scatter(
                x=_eq_curve['Date'], y=_eq_curve['Peak'],
                mode='lines', line=dict(width=0), showlegend=False, hoverinfo='skip'
            ))
            _fig_eq2.add_trace(go.Scatter(
                x=_eq_curve['Date'], y=_eq_curve['Cum P/L'],
                mode='none', fill='tonexty', fillcolor='rgba(239,85,59,0.18)',
                showlegend=False, hoverinfo='skip', name='Drawdown'
            ))
        _fig_eq2.add_trace(go.Scatter(
            x=_eq_curve['Date'], y=_eq_curve['Cum P/L'],
            mode='lines', line=dict(color=_eq_color, width=2),
            fill='tozeroy', fillcolor=_eq_fill, name='Cumulative P/L',
            hovertemplate='%{x|%d/%m/%y}<br><b>%{y:$,.2f}</b><extra></extra>'
        ))
        if not _is_all_time:
            _fig_eq2.add_vrect(
                x0=start_date, x1=latest_date,
                fillcolor='rgba(88,166,255,0.06)',
                line=dict(color='rgba(88,166,255,0.3)', width=1, dash='dot'),
                annotation_text=selected_period, annotation_position='top left',
                annotation_font=dict(color=COLOURS['blue'], size=10)
            )
        _fig_eq2.add_annotation(
            x=_eq_curve['Date'].iloc[-1], y=_eq_final,
            text='<b>%s</b>' % fmt_dollar(_eq_final),
            showarrow=False, xanchor='right', yanchor='bottom',
            font=dict(color=_eq_color, size=12, family='IBM Plex Mono'),
            bgcolor='rgba(10,14,23,0.8)', borderpad=4
        )
        _fig_eq2.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
        _eq2_lay = chart_layout(
            'Portfolio Equity Curve — Cumulative Realized P/L', height=300, margin_t=36)
        _eq2_lay['yaxis']['tickprefix'] = '$'
        _eq2_lay['yaxis']['tickformat'] = ',.0f'
        _eq2_lay['showlegend'] = False
        _fig_eq2.update_layout(**_eq2_lay)
        st.plotly_chart(_fig_eq2, width='stretch', config={'displayModeBar': False})
        st.caption(
            'Red shading = drawdown from realized P/L peak. '
            'Blue region = selected time window. Curve starts from your first transaction.'
        )

        if len(_daily_pnl_all) >= 2:
            _top_days = (_daily_pnl_all.copy()
                .reindex(_daily_pnl_all['PnL'].abs().sort_values(ascending=False).index)
                .head(10).copy())
            _top_days['Date'] = pd.to_datetime(_top_days['Date'])

            def _day_summary(date):
                _d = df[df['Date'].dt.date == date.date()]
                parts = []
                _opts = _d[_d['Instrument Type'].isin(OPT_TYPES) & _d['Type'].isin(TRADE_TYPES)]
                _eq_s = _d[equity_mask(_d['Instrument Type']) & (_d['Net_Qty_Row'] < 0)]
                _inc  = _d[_d['Sub Type'].isin(INCOME_SUB_TYPES)]
                if not _opts.empty:
                    parts.append('Options (%s)' % ', '.join(sorted(_opts['Ticker'].unique()[:3])))
                if not _eq_s.empty:
                    parts.append('Equity sale (%s)' % ', '.join(sorted(_eq_s['Ticker'].unique()[:3])))
                if not _inc.empty:
                    tks = ', '.join(sorted(_inc['Ticker'].dropna().unique()[:3]))
                    parts.append('Income (%s)' % tks if tks else 'Income')
                return ' + '.join(parts) if parts else '—'

            _top_days['What']     = _top_days['Date'].apply(_day_summary)
            _top_days['P/L']      = _top_days['PnL'].apply(fmt_dollar)
            _top_days['Date_fmt'] = _top_days['Date'].dt.strftime('%d %b %Y')
            with st.expander(
                '🔍 Top 10 single-day P/L events (explains curve spikes)', expanded=False
            ):
                _td = _top_days[['Date_fmt', 'P/L', 'What']].rename(
                    columns={'Date_fmt': 'Date'})
                st.dataframe(
                    _td.style.map(
                        lambda v: 'color:#00cc96;font-family:IBM Plex Mono'
                                  if isinstance(v, str) and v.startswith('$') and '-' not in v
                                  else ('color:#ef553b;font-family:IBM Plex Mono'
                                        if isinstance(v, str) and (v.startswith('-') or '−' in v)
                                        else ''),
                        subset=['P/L']
                    ),
                    width='stretch', hide_index=True
                )
                st.caption('Sorted by absolute P/L. Covers full account history.')

    st.markdown('---')
    rows = []
    for ticker, camps in sorted(all_campaigns.items()):
        tr = sum(realized_pnl(c, use_lifetime) for c in camps)
        td = sum(c.total_cost for c in camps if c.status == 'open')
        tp = sum(c.premiums for c in camps)
        tv = sum(c.dividends for c in camps)
        po = pure_opts_per_ticker.get(ticker, 0.0)
        oc = sum(1 for c in camps if c.status == 'open')
        cc = sum(1 for c in camps if c.status == 'closed')
        rows.append({'Ticker': ticker, 'Type': '🎡 Wheel',
            'Campaigns': '%d open, %d closed' % (oc, cc),
            'Premiums': tp, 'Divs': tv, 'Options P/L': po, 'Deployed': td, 'P/L': tr + po})
    for ticker in sorted(pure_options_tickers):
        t_df        = df[df['Ticker'] == ticker]
        t_eq        = t_df[equity_mask(t_df['Instrument Type'])].sort_values('Date')
        opt_flow    = t_df[
            t_df['Instrument Type'].isin(OPT_TYPES) & t_df['Type'].isin(TRADE_TYPES)
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
        deep_df   = pd.DataFrame(rows)
        total_row = {
            'Ticker': 'TOTAL', 'Type': '', 'Campaigns': '',
            'Premiums':    deep_df['Premiums'].sum(),
            'Divs':        deep_df['Divs'].sum(),
            'Options P/L': deep_df['Options P/L'].sum(),
            'Deployed':    deep_df['Deployed'].sum(),
            'P/L':         deep_df['P/L'].sum(),
        }
        deep_df = pd.concat([deep_df, pd.DataFrame([total_row])], ignore_index=True)
        st.dataframe(deep_df.style.format({
            'Premiums': fmt_dollar, 'Divs': fmt_dollar,
            'Options P/L': fmt_dollar, 'Deployed': fmt_dollar, 'P/L': fmt_dollar,
        }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)

    st.markdown('---')
    st.markdown(
        f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;">'
        f'📅 Total Realized P/L by Week &amp; Month {_win_label}</div>',
        unsafe_allow_html=True
    )
    _daily_pnl['Week']  = _daily_pnl['Date'].dt.to_period('W').apply(lambda p: p.start_time)
    _daily_pnl['Month'] = _daily_pnl['Date'].dt.to_period('M').apply(lambda p: p.start_time)

    if not _daily_pnl.empty:
        _p_col1, _p_col2 = st.columns(2)
        with _p_col1:
            _pw = _daily_pnl.groupby('Week')['PnL'].sum().reset_index()
            _pw['Week']   = pd.to_datetime(_pw['Week'])
            _pw['Colour'] = _pw['PnL'].apply(lambda x: COLOURS['green'] if x >= 0 else COLOURS['red'])
            _fig_pw = go.Figure()
            _fig_pw.add_trace(go.Bar(
                x=_pw['Week'], y=_pw['PnL'],
                marker_color=_pw['Colour'], marker_line_width=0,
                customdata=[fmt_dollar(v) for v in _pw['PnL']],
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
            _pm = _daily_pnl.groupby('Month')['PnL'].sum().reset_index()
            _pm['Month']  = pd.to_datetime(_pm['Month'])
            _pm['Colour'] = _pm['PnL'].apply(lambda x: COLOURS['green'] if x >= 0 else COLOURS['red'])
            _pm['Label']  = _pm['Month'].dt.strftime('%b %Y')
            _fig_pm = go.Figure()
            _fig_pm.add_trace(go.Bar(
                x=_pm['Label'], y=_pm['PnL'],
                marker_color=_pm['Colour'], marker_line_width=0,
                text=[fmt_dollar(v, 0) for v in _pm['PnL']],
                customdata=[fmt_dollar(v) for v in _pm['PnL']],
                textposition='outside',
                textfont=dict(size=10, family='IBM Plex Mono', color=COLOURS['text_muted']),
                hovertemplate='%{x}<br><b>%{customdata}</b><extra></extra>'
            ))
            _fig_pm.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
            _pm_lay = chart_layout('Monthly Total P/L' + _win_suffix, height=280, margin_t=36)
            _pm_lay['yaxis']['tickprefix'] = '$'
            _pm_lay['yaxis']['tickformat'] = ',.0f'
            _pm_lay['bargap'] = 0.35
            _fig_pm.update_layout(**_pm_lay)
            st.plotly_chart(_fig_pm, width='stretch', config={'displayModeBar': False})

        st.markdown('---')
        st.markdown(
            f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;">'
            f'📉 P&amp;L Consistency {_win_label}</div>',
            unsafe_allow_html=True
        )
        if not _daily_pnl.empty and len(_daily_pnl) >= 2:
            _vol_df = _daily_pnl.copy()
            _vol_df['Week'] = pd.to_datetime(_vol_df['Date']).dt.to_period('W').apply(
                lambda p: p.start_time)
            _wkly = _vol_df.groupby('Week')['PnL'].sum().reset_index()
            _wkly['Week'] = pd.to_datetime(_wkly['Week'])

            _avg_week    = _wkly['PnL'].mean()
            _std_week    = _wkly['PnL'].std()
            _sharpe_eq   = (_avg_week / _std_week) if _std_week > 0 else 0.0
            _pos_weeks   = (_wkly['PnL'] > 0).sum()
            _total_weeks = len(_wkly)
            _consistency = _pos_weeks / _total_weeks * 100 if _total_weeks > 0 else 0.0

            _cum = _vol_df.sort_values('Date')['PnL'].cumsum().values
            _peak = _cum[0]; _max_dd = 0.0; _peak_i = 0; _dd_start_i = 0; _dd_end_i = 0
            for idx, v in enumerate(_cum):
                if v > _peak: _peak = v; _peak_i = idx
                dd = v - _peak
                if dd < _max_dd: _max_dd = dd; _dd_start_i = _peak_i; _dd_end_i = idx
            _recovery_days = None
            if _max_dd < 0:
                for idx in range(_dd_end_i + 1, len(_cum)):
                    if _cum[idx] >= _cum[_dd_start_i]:
                        _recovery_days = idx - _dd_end_i; break

            _wkly['Rolling_Std'] = _wkly['PnL'].rolling(4, min_periods=2).std()

            vc1, vc2, vc3, vc4, vc5 = st.columns(5)
            vc1.metric('Avg Week P/L',    fmt_dollar(_avg_week))
            vc2.metric('Weekly Std Dev',  fmt_dollar(_std_week))
            vc3.metric('Sharpe-Equiv',    '%.2f' % _sharpe_eq)
            vc4.metric('Profitable Weeks',
                '%.0f%% (%d/%d)' % (_consistency, _pos_weeks, _total_weeks))
            if _max_dd < 0:
                vc5.metric('Max Drawdown', fmt_dollar(_max_dd),
                    delta='Recovery: %s' % ('%dd' % _recovery_days if _recovery_days else 'Not yet'),
                    delta_color='off')
            else:
                vc5.metric('Max Drawdown', '$0.00')

            _fig_vol = go.Figure()
            _fig_vol.add_trace(go.Bar(
                x=_wkly['Week'], y=_wkly['PnL'],
                marker_color=_wkly['PnL'].apply(lambda x: COLOURS['green'] if x >= 0 else COLOURS['red']),
                marker_line_width=0, name='Weekly P/L',
                customdata=[fmt_dollar(v) for v in _wkly['PnL']],
                hovertemplate='Week of %{x|%d %b}<br><b>%{customdata}</b><extra></extra>'
            ))
            if _wkly['Rolling_Std'].notna().sum() >= 2:
                _fig_vol.add_trace(go.Scatter(
                    x=_wkly['Week'], y=_wkly['Rolling_Std'],
                    mode='lines', name='4-wk Std Dev',
                    line=dict(color='#ffa421', width=1.5, dash='dot'), yaxis='y2',
                    hovertemplate='Std Dev: <b>$%{y:,.2f}</b><extra></extra>'
                ))
                _fig_vol.add_trace(go.Scatter(
                    x=_wkly['Week'], y=(-_wkly['Rolling_Std']),
                    mode='lines', name='-4-wk Std Dev',
                    line=dict(color='#ffa421', width=1.5, dash='dot'),
                    yaxis='y2', showlegend=False
                ))
            _fig_vol.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
            _vol_lay = chart_layout(
                'Weekly P/L + Rolling 4-wk Volatility Band' + _win_suffix, height=300, margin_t=40)
            _vol_lay['yaxis']['tickprefix'] = '$'
            _vol_lay['yaxis']['tickformat'] = ',.0f'
            _vol_lay['bargap'] = 0.3
            _vol_lay['yaxis2'] = dict(
                overlaying='y', side='right',
                tickprefix='±$', tickformat=',.0f',
                tickfont=dict(size=10, color='#ffa421'),
                gridcolor='rgba(0,0,0,0)', showgrid=False
            )
            _vol_lay['legend'] = dict(orientation='h', yanchor='bottom', y=1.02,
                xanchor='right', x=1, bgcolor='rgba(0,0,0,0)', font=dict(size=11))
            _fig_vol.update_layout(**_vol_lay)
            st.plotly_chart(_fig_vol, width='stretch', config={'displayModeBar': False})

            if capital_deployed > 0 and len(_wkly) >= 6:
                st.markdown('---')
                st.markdown(
                    f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;">'
                    f'📈 Rolling Capital Efficiency {_win_label}</div>',
                    unsafe_allow_html=True
                )
                _rp = _wkly.copy()
                _rp['Rolling_PnL_90d'] = _rp['PnL'].rolling(13, min_periods=4).sum()
                _rp['Rolling_CapEff']  = _rp['Rolling_PnL_90d'] / capital_deployed / 90 * 365 * 100
                _rv = _rp.dropna(subset=['Rolling_CapEff'])
                if not _rv.empty:
                    _ce_color = COLOURS['green'] if _rv['Rolling_CapEff'].iloc[-1] >= 0 else COLOURS['red']
                    _ce_fill  = ('rgba(0,204,150,0.08)' if _rv['Rolling_CapEff'].iloc[-1] >= 0
                                 else 'rgba(239,85,59,0.08)')
                    _fig_ce = go.Figure()
                    _fig_ce.add_hrect(y0=0, y1=10, fillcolor='rgba(255,164,33,0.04)',
                        line_width=0, annotation_text='S&P benchmark ~10%',
                        annotation_position='top left',
                        annotation_font=dict(color='#ffa421', size=10))
                    _fig_ce.add_trace(go.Scatter(
                        x=_rv['Week'], y=_rv['Rolling_CapEff'],
                        mode='lines', line=dict(color=_ce_color, width=2),
                        fill='tozeroy', fillcolor=_ce_fill,
                        hovertemplate='Week of %{x|%d %b}<br>Cap Efficiency: <b>%{y:.1f}%</b><extra></extra>'
                    ))
                    _fig_ce.add_hline(y=10, line_dash='dot', line_color='#ffa421', line_width=1.5,
                        annotation_text='S&P ~10%', annotation_position='bottom right',
                        annotation_font=dict(color='#ffa421', size=11))
                    _fig_ce.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
                    _ce_lay = chart_layout(
                        'Rolling 90-day Capital Efficiency (annualised)' + _win_suffix,
                        height=300, margin_t=40)
                    _ce_lay['yaxis']['ticksuffix'] = '%'
                    _ce_lay['yaxis']['tickformat'] = ',.0f'
                    _fig_ce.update_layout(**_ce_lay)
                    st.plotly_chart(_fig_ce, width='stretch', config={'displayModeBar': False})
        else:
            st.info('Not enough data for volatility metrics (need at least 2 days).')
    else:
        st.info('No cash flow data in the selected window.')


