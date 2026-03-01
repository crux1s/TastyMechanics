"""
tabs/tab2_trade_analysis.py — Tab2 Trade Analysis tab renderer.
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


def render_tab2(closed_trades_df, all_cdf, credit_cdf, has_credit, has_data,
                df_window, _win_label, _win_suffix, _win_start_str, _win_end_str):
    """Tab 2 — Trade Analysis: ThetaGang metrics, period charts, heatmap, best/worst, trade log."""
    if closed_trades_df.empty:
        st.info('No closed trades found.')
        return
    st.markdown(f'### 🔬 Trade Analysis {_win_label}', unsafe_allow_html=True)
    st.markdown('---')
    st.markdown(
        f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;">'
        f'🎯 ThetaGang Metrics {_win_label}</div>',
        unsafe_allow_html=True
    )
    st.markdown(
        '<div style="font-size:0.8rem;color:#6b7280;margin-bottom:16px;line-height:1.5;">'
        'Metrics specific to theta selling — management discipline, DTE behaviour, '
        'portfolio concentration, and win rate trend.</div>',
        unsafe_allow_html=True
    )

    if has_data and has_credit:
        _tg_opts = df_window[df_window['Instrument Type'].isin(OPT_TYPES)]
        _tg_closes = _tg_opts[
            _tg_opts['Sub Type'].str.lower().str.contains(PAT_CLOSING, na=False)
        ].copy()
        _tg_closes['Exp'] = pd.to_datetime(
            _tg_closes['Expiration Date'], format='mixed', errors='coerce'
        ).dt.normalize()
        _tg_closes['DTE_close'] = (_tg_closes['Exp'] - _tg_closes['Date']).dt.days.clip(lower=0)

        _leaps_cdf = credit_cdf[credit_cdf['DTE at Open'] > LEAPS_DTE_THRESHOLD] \
            if 'DTE at Open' in credit_cdf.columns else pd.DataFrame()
        _short_cdf = credit_cdf[credit_cdf['DTE at Open'] <= LEAPS_DTE_THRESHOLD] \
            if 'DTE at Open' in credit_cdf.columns else credit_cdf
        _tg_closes_short = _tg_closes[
            _tg_closes['DTE_close'].isna() | (_tg_closes['DTE_close'] <= LEAPS_DTE_THRESHOLD)
        ]

        _n_expired   = (_tg_closes_short['Sub Type'].str.lower()
                        .str.contains('expir|assign|exercise')).sum()
        _n_managed   = (_tg_closes_short['Sub Type'].str.lower()
                        .str.contains(PAT_CLOSE)).sum()
        _n_total_cls = len(_tg_closes_short)
        _mgmt_rate   = _n_managed / _n_total_cls * 100 if _n_total_cls > 0 else 0

        _dte_valid     = _tg_closes_short.dropna(subset=['DTE_close'])
        _med_dte_close = _dte_valid['DTE_close'].median() if not _dte_valid.empty else 0
        _med_dte_open  = _short_cdf['DTE at Open'].median() \
            if 'DTE at Open' in _short_cdf.columns and not _short_cdf.empty else 0

        _tg_sto = _tg_opts[_tg_opts['Sub Type'].str.lower() == SUB_SELL_OPEN]
        _by_tkr = _tg_sto.groupby('Ticker')['Total'].sum().sort_values(ascending=False)
        _total_prem_conc = _by_tkr.sum()
        _top3_pct   = _by_tkr.head(3).sum() / _total_prem_conc * 100 if _total_prem_conc > 0 else 0
        _top3_names = ', '.join(_by_tkr.head(3).index.tolist())

        _roll_cdf = all_cdf.sort_values('Close Date').copy()
        _roll_cdf['Rolling_WR'] = _roll_cdf['Won'].rolling(10, min_periods=5).mean() * 100

        tg1, tg2, tg3, tg4 = st.columns(4)
        tg1.metric('Management Rate',    '%.0f%%' % _mgmt_rate,
            delta='%d managed, %d expired/assigned' % (_n_managed, _n_expired), delta_color='off')
        tg1.caption('% of trades actively closed early vs left to expire/assign. LEAPS excluded.')
        tg2.metric('Median DTE at Open', '%.0fd' % _med_dte_open)
        tg2.caption('Median DTE when trades opened. TastyTrade targets 30–45 DTE. LEAPS excluded.')
        tg3.metric('Median DTE at Close', '%.0fd' % _med_dte_close)
        tg3.caption('Median DTE remaining at close. Target: 14–21 DTE. LEAPS excluded.')
        _conc_icon = '⚠️' if _top3_pct > 60 else '✅'
        tg4.metric('Top 3 Concentration', '%.0f%%' % _top3_pct)
        tg4.caption(f'{_conc_icon} {_top3_names} — above 60%% = concentration risk.')

        if not _leaps_cdf.empty:
            _lc = COLOURS['green'] if _leaps_cdf['Net P/L'].sum() >= 0 else COLOURS['red']
            st.markdown(
                f'<div style="background:rgba(88,166,255,0.06);border:1px solid rgba(88,166,255,0.2);'
                f'border-radius:8px;padding:10px 16px;margin:12px 0 0 0;font-size:0.82rem;color:#8b949e;">'
                f'<span style="color:#58a6ff;font-weight:600;">📅 LEAPS detected</span>'
                f' &nbsp;·&nbsp; {len(_leaps_cdf)} trade(s) with DTE &gt; {LEAPS_DTE_THRESHOLD}d at open'
                f' &nbsp;·&nbsp; Tickers: <span style="color:#c9d1d9;">'
                f'{xe(", ".join(sorted(_leaps_cdf["Ticker"].unique())))}</span>'
                f' &nbsp;·&nbsp; Net P/L: <span style="color:{_lc};font-family:monospace;">'
                f'{fmt_dollar(_leaps_cdf["Net P/L"].sum())}</span>'
                f' &nbsp;·&nbsp; Win Rate: <span style="color:#c9d1d9;">'
                f'{_leaps_cdf["Won"].mean() * 100:.0f}%</span>'
                f' &nbsp;·&nbsp; <span style="font-style:italic;">Excluded from ThetaGang metrics above.</span>'
                f'</div>',
                unsafe_allow_html=True
            )

        st.markdown('---')
        _tg_col1, _tg_col2 = st.columns(2)
        with _tg_col1:
            if not _dte_valid.empty:
                _dte_bins   = [-1, 0, 7, 14, 21, 30, 999]
                _dte_labels = ['0 (expired)', '1–7d', '8–14d', '15–21d', '22–30d', '>30d']
                _dv = _dte_valid.copy()
                _dv['Bucket'] = pd.cut(_dv['DTE_close'], bins=_dte_bins, labels=_dte_labels)
                _dte_dist = _dv['Bucket'].value_counts().reindex(_dte_labels, fill_value=0).reset_index()
                _dte_dist.columns = ['DTE Bucket', 'Trades']
                _dte_colors = [COLOURS['blue'] if b in ['8–14d', '15–21d'] else '#30363d' for b in _dte_labels]
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
                st.caption('🔵 Blue = TastyTrade target close zone (8–21 DTE). Grey = outside target.')

        with _tg_col2:
            if not _roll_cdf.empty and _roll_cdf['Rolling_WR'].notna().sum() >= 2:
                _fig_rwr = go.Figure()
                _fig_rwr.add_hline(y=50, line_dash='dash',
                    line_color='rgba(255,255,255,0.15)', line_width=1)
                _fig_rwr.add_trace(go.Scatter(
                    x=_roll_cdf['Close Date'], y=_roll_cdf['Rolling_WR'],
                    mode='lines', line=dict(color=COLOURS['blue'], width=2),
                    fill='tozeroy', fillcolor='rgba(88,166,255,0.08)',
                    hovertemplate='%{x|%d/%m/%y}<br>Win Rate: <b>%{y:.1f}%</b><extra></extra>'
                ))
                _fig_rwr.add_hline(
                    y=_roll_cdf['Won'].mean() * 100,
                    line_dash='dot', line_color='#ffa421', line_width=1.5,
                    annotation_text='avg %.0f%%' % (_roll_cdf['Won'].mean() * 100),
                    annotation_position='bottom right',
                    annotation_font=dict(color='#ffa421', size=11)
                )
                _rwr_lay = chart_layout(
                    'Rolling Win Rate · 10-trade window' + _win_suffix, height=300, margin_t=40)
                _rwr_lay['yaxis']['ticksuffix'] = '%'
                _rwr_lay['yaxis']['range'] = [0, 105]
                _fig_rwr.update_layout(**_rwr_lay)
                st.plotly_chart(_fig_rwr, width='stretch', config={'displayModeBar': False})
                st.caption('Rolling 10-trade win rate. Amber = overall average.')

    st.markdown('---')
    st.markdown(
        f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;">'
        f'📅 Options P/L by Week &amp; Month {_win_label}</div>',
        unsafe_allow_html=True
    )
    st.markdown(
        '<div style="font-size:0.8rem;color:#6b7280;margin-bottom:12px;line-height:1.5;">'
        '<b style="color:#58a6ff;">Options trades only</b> — net P/L from closed equity &amp; '
        'futures options, grouped by the date the trade closed.</div>',
        unsafe_allow_html=True
    )
    _period_df = all_cdf.copy()
    _period_df['CloseDate'] = pd.to_datetime(_period_df['Close Date'])
    _period_df = _period_df.sort_values('CloseDate')
    _period_df['Week']  = _period_df['CloseDate'].dt.to_period('W').apply(lambda p: p.start_time)
    _period_df['Month'] = _period_df['CloseDate'].dt.to_period('M').apply(lambda p: p.start_time)

    # Cumulative P/L — candle OHLC is computed from the running equity curve
    _period_df['CumPL'] = _period_df['Net P/L'].cumsum()

    def _candle_agg(group_col):
        """OHLC from the running cumulative P/L curve within each period.
        Open  = cumPL just before the first trade of the period (prev close)
        Close = cumPL after the last trade of the period
        High  = peak cumPL reached during the period (incl. open level)
        Low   = trough cumPL reached during the period (incl. open level)
        """
        rows, prev_close = [], 0.0
        for period, grp in _period_df.groupby(group_col, sort=True):
            o = prev_close
            c = grp['CumPL'].iloc[-1]
            h = max(grp['CumPL'].max(), o)
            l = min(grp['CumPL'].min(), o)
            rows.append({'Period': pd.Timestamp(str(period)),
                         'Open': o, 'High': h, 'Low': l, 'Close': c,
                         'Net': grp['Net P/L'].sum(), 'Trades': len(grp)})
            prev_close = c
        return pd.DataFrame(rows)

    def _candle_fig(df_c, title, x_fmt):
        """Plotly candlestick from an OHLC DataFrame."""
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df_c['Period'],
            open=df_c['Open'], high=df_c['High'],
            low=df_c['Low'],   close=df_c['Close'],
            increasing=dict(line=dict(color=COLOURS['green'], width=1),
                            fillcolor='rgba(0,204,150,0.5)'),
            decreasing=dict(line=dict(color=COLOURS['red'], width=1),
                            fillcolor='rgba(239,85,59,0.5)'),
            customdata=list(zip(
                [fmt_dollar(r) for r in df_c['Net']],
                df_c['Trades'],
                [fmt_dollar(r) for r in df_c['Open']],
                [fmt_dollar(r) for r in df_c['Close']],
                [fmt_dollar(r) for r in df_c['High']],
                [fmt_dollar(r) for r in df_c['Low']],
            )),
            hovertemplate=(
                '<b>%{x|' + x_fmt + '}</b><br>'
                'Net: <b>%{customdata[0]}</b>  (%{customdata[1]} trades)<br>'
                'Open: %{customdata[2]}  Close: %{customdata[3]}<br>'
                'High: %{customdata[4]}  Low: %{customdata[5]}'
                '<extra></extra>'
            ),
            name='',
        ))
        fig.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
        return fig

    _pcol1, _pcol2 = st.columns(2)
    with _pcol1:
        _wk_c   = _candle_agg('Week')
        _fig_wk = _candle_fig(_wk_c, 'Weekly P/L' + _win_suffix, '%d %b')
        _wk_lay = chart_layout('Weekly P/L' + _win_suffix, height=300, margin_t=36)
        _wk_lay['xaxis']['type']        = 'date'
        _wk_lay['xaxis']['tickformat']  = '%d %b'
        _wk_lay['yaxis']['tickprefix']  = '$'
        _wk_lay['yaxis']['tickformat']  = ',.0f'
        _wk_lay['xaxis']['rangeslider'] = {'visible': False}
        _fig_wk.update_layout(**_wk_lay)
        st.plotly_chart(_fig_wk, width='stretch', config={'displayModeBar': False})

    with _pcol2:
        _mo_c   = _candle_agg('Month')
        _fig_mo = _candle_fig(_mo_c, 'Monthly P/L' + _win_suffix, '%b %Y')
        _mo_lay = chart_layout('Monthly P/L' + _win_suffix, height=300, margin_t=36)
        _mo_lay['xaxis']['type']        = 'date'
        _mo_lay['xaxis']['tickformat']  = '%b %Y'
        _mo_lay['yaxis']['tickprefix']  = '$'
        _mo_lay['yaxis']['tickformat']  = ',.0f'
        _mo_lay['xaxis']['rangeslider'] = {'visible': False}
        _fig_mo.update_layout(**_mo_lay)
        st.plotly_chart(_fig_mo, width='stretch', config={'displayModeBar': False})

    st.caption(
        'Candles show the cumulative P/L equity curve open/high/low/close for each period. '
        'Green = period closed higher than it opened. '
        'Wicks show the best and worst points reached intra-period.'
    )

    st.markdown('---')
    cum_df = all_cdf.sort_values('Close Date').copy()
    cum_df['Cumulative P/L'] = cum_df['Net P/L'].cumsum()
    final_pnl = cum_df['Cumulative P/L'].iloc[-1]
    eq_color  = COLOURS['green'] if final_pnl >= 0 else COLOURS['red']
    eq_fill   = 'rgba(0,204,150,0.12)' if final_pnl >= 0 else 'rgba(239,85,59,0.12)'
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
            mode='lines', line=dict(color=COLOURS['blue'], width=2),
            fill='tozeroy', fillcolor='rgba(88,166,255,0.08)',
            hovertemplate='%{x|%d/%m/%y}<br>Capture: <b>%{y:.1f}%</b><extra></extra>'
        ))
        fig_cap2.add_hline(y=50, line_dash='dash', line_color='#ffa421', line_width=1.5,
            annotation_text='50% target', annotation_position='bottom right',
            annotation_font=dict(color='#ffa421', size=11))
        _cap2_lay = chart_layout(
            'Rolling Avg Capture % · 10-trade window' + _win_suffix, height=260, margin_t=40)
        _cap2_lay['yaxis']['ticksuffix'] = '%'
        fig_cap2.update_layout(**_cap2_lay)
        st.plotly_chart(fig_cap2, width='stretch', config={'displayModeBar': False})

    st.markdown('---')
    st.markdown(
        f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;">'
        f'📊 Win / Loss Distribution {_win_label}</div>',
        unsafe_allow_html=True
    )
    _hist_df = all_cdf.copy()
    _hist_df['Colour'] = _hist_df['Net P/L'].apply(lambda x: 'Win' if x >= 0 else 'Loss')
    _fig_hist = px.histogram(
        _hist_df, x='Net P/L', color='Colour',
        color_discrete_map={'Win': COLOURS['green'], 'Loss': COLOURS['red']},
        nbins=40, labels={'Net P/L': 'Trade P/L ($)', 'count': 'Trades'},
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
    st.markdown(
        f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;">'
        f'🎯 Win Rate &amp; P/L by DTE at Open {_win_label}</div>',
        unsafe_allow_html=True
    )
    if has_credit and 'DTE at Open' in all_cdf.columns:
        _dte_open_df = all_cdf[all_cdf['DTE at Open'].notna()].copy()
        _dte_open_df = _dte_open_df[_dte_open_df['DTE at Open'] <= LEAPS_DTE_THRESHOLD]
        if not _dte_open_df.empty:
            _dte_open_bins   = [0, 7, 14, 21, 30, 45, 60, LEAPS_DTE_THRESHOLD]
            _dte_open_labels = ['0–7d', '8–14d', '15–21d', '22–30d', '31–45d', '46–60d', '61–90d']
            _dte_open_df['DTE Bucket'] = pd.cut(
                _dte_open_df['DTE at Open'], bins=_dte_open_bins,
                labels=_dte_open_labels, include_lowest=True
            )
            _dte_grp = _dte_open_df.groupby('DTE Bucket', observed=True).agg(
                Trades=('Won', 'count'), Win_Rate=('Won', 'mean'),
                Avg_PnL=('Net P/L', 'mean'),
            ).reset_index()
            _dte_grp = _dte_grp[_dte_grp['Trades'] > 0].copy()
            _dte_grp['Win_Rate_Pct'] = _dte_grp['Win_Rate'] * 100

            _dcol1, _dcol2 = st.columns(2)
            with _dcol1:
                _wr_colors = [COLOURS['green'] if w >= 50 else COLOURS['red']
                              for w in _dte_grp['Win_Rate_Pct']]
                _fig_dtewr = go.Figure(go.Bar(
                    x=_dte_grp['DTE Bucket'].astype(str), y=_dte_grp['Win_Rate_Pct'],
                    marker_color=_wr_colors, marker_line_width=0,
                    text=['%.0f%% (%d)' % (w, t)
                          for w, t in zip(_dte_grp['Win_Rate_Pct'], _dte_grp['Trades'])],
                    textposition='outside', textfont=dict(size=10, family='IBM Plex Mono'),
                    hovertemplate='%{x}<br>Win Rate: <b>%{y:.1f}%</b><extra></extra>'
                ))
                _fig_dtewr.add_hline(y=50, line_dash='dash',
                    line_color='rgba(255,255,255,0.2)', line_width=1)
                _dtewr_lay = chart_layout(
                    'Win Rate by DTE at Open (LEAPS excluded)' + _win_suffix, height=300, margin_t=40)
                _dtewr_lay['showlegend'] = False
                _dtewr_lay['yaxis']['ticksuffix'] = '%'
                _dtewr_lay['yaxis']['range'] = [0, 115]
                _dtewr_lay['xaxis']['title'] = dict(text='DTE at Open', font=dict(size=11))
                _fig_dtewr.update_layout(**_dtewr_lay)
                st.plotly_chart(_fig_dtewr, width='stretch', config={'displayModeBar': False})
                st.caption('Green ≥ 50% win rate. Format: 82% (14) = 82% win rate on 14 trades.')

            with _dcol2:
                _pnl_colors = [COLOURS['green'] if p >= 0 else COLOURS['red'] for p in _dte_grp['Avg_PnL']]
                _fig_dtepnl = go.Figure(go.Bar(
                    x=_dte_grp['DTE Bucket'].astype(str), y=_dte_grp['Avg_PnL'],
                    marker_color=_pnl_colors, marker_line_width=0,
                    text=[fmt_dollar(p, 0) for p in _dte_grp['Avg_PnL']],
                    textposition='outside', textfont=dict(size=10, family='IBM Plex Mono'),
                    hovertemplate='%{x}<br>Avg P/L: <b>$%{y:,.2f}</b><extra></extra>'
                ))
                _fig_dtepnl.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
                _dtepnl_lay = chart_layout(
                    'Avg P/L per Trade by DTE at Open' + _win_suffix, height=300, margin_t=40)
                _dtepnl_lay['showlegend'] = False
                _dtepnl_lay['yaxis']['tickprefix'] = '$'
                _dtepnl_lay['yaxis']['tickformat'] = ',.0f'
                _dtepnl_lay['xaxis']['title'] = dict(text='DTE at Open', font=dict(size=11))
                _fig_dtepnl.update_layout(**_dtepnl_lay)
                st.plotly_chart(_fig_dtepnl, width='stretch', config={'displayModeBar': False})
                st.caption('Your sweet spot = high win rate AND positive avg P/L.')
        else:
            st.info('Not enough trades with DTE data in this window.')

    # ── P/L by Day of Week & Hour of Day ─────────────────────────────────────────
    if has_data and not all_cdf.empty:
        st.markdown('---')
        st.markdown(
            f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;">'
            f'📅 P/L by Day of Week &amp; Hour of Day {_win_label}</div>',
            unsafe_allow_html=True
        )
        st.caption(
            'When do you trade best? Close date/time in UTC. '
            'US market open = 14:30 UTC (13:30 UTC during EDT). '
            'NZT = UTC +13 (summer) / +12 (winter).'
        )
        _dow_df = all_cdf.copy()
        _dow_df['Close Date'] = pd.to_datetime(_dow_df['Close Date'])
        _dow_df['Day'] = _dow_df['Close Date'].dt.day_name()
        _dow_df['Hour'] = _dow_df['Close Date'].dt.hour

        _dow_agg = _dow_df.groupby('Day').agg(
            Net_PL=('Net P/L', 'sum'),
            Trades=('Net P/L', 'count'),
            Win_Rate=('Won', lambda x: x.mean() * 100)
        ).reindex(['Monday','Tuesday','Wednesday','Thursday','Friday']).reset_index()

        _hour_agg = _dow_df.groupby('Hour').agg(
            Net_PL=('Net P/L', 'sum'),
            Trades=('Net P/L', 'count'),
        ).reset_index().sort_values('Hour')

        _dow_col, _hour_col = st.columns(2)

        with _dow_col:
            _fig_dow = go.Figure()
            _fig_dow.add_trace(go.Bar(
                x=_dow_agg['Day'],
                y=_dow_agg['Net_PL'],
                marker_color=[
                    COLOURS['green'] if v >= 0 else COLOURS['red'] for v in _dow_agg['Net_PL']
                ],
                text=['$%.0f' % v for v in _dow_agg['Net_PL']],
                textposition='outside',
                customdata=_dow_agg[['Trades','Win_Rate']].values,
                hovertemplate='%{x}<br>P/L: <b>$%{y:,.0f}</b><br>Trades: %{customdata[0]:.0f}<br>Win Rate: %{customdata[1]:.1f}%<extra></extra>',
            ))
            _dow_lay = chart_layout('Net P/L by Day of Week', height=320, margin_t=40)
            _dow_lay['yaxis'] = {'tickprefix': '$', 'tickformat': ',.0f', 'gridcolor': COLOURS['border']}
            _dow_lay['xaxis'] = {'gridcolor': COLOURS['border']}
            _dow_lay['showlegend'] = False
            _fig_dow.update_layout(**_dow_lay)
            st.plotly_chart(_fig_dow, width='stretch', config={'displayModeBar': False})

        with _hour_col:
            _fig_hour = go.Figure()
            _fig_hour.add_trace(go.Bar(
                x=_hour_agg['Hour'],
                y=_hour_agg['Net_PL'],
                marker_color=[
                    COLOURS['green'] if v >= 0 else COLOURS['red'] for v in _hour_agg['Net_PL']
                ],
                text=['$%.0f' % v for v in _hour_agg['Net_PL']],
                textposition='outside',
                customdata=_hour_agg[['Trades']].values,
                hovertemplate='Hour %{x}:00 UTC<br>P/L: <b>$%{y:,.0f}</b><br>Trades: %{customdata[0]:.0f}<extra></extra>',
            ))

            _hour_lay = chart_layout('Net P/L by Hour (UTC)', height=320, margin_t=40)
            _hour_lay['yaxis'] = {'tickprefix': '$', 'tickformat': ',.0f', 'gridcolor': COLOURS['border']}
            _hour_lay['xaxis'] = {'title': {'text': 'Hour (UTC)', 'font': {'size': 10}}, 'dtick': 1, 'gridcolor': COLOURS['border']}
            _hour_lay['showlegend'] = False
            _fig_hour.update_layout(**_hour_lay)
            st.plotly_chart(_fig_hour, width='stretch', config={'displayModeBar': False})

    st.markdown('---')
    st.markdown(
        f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;">'
        f'🗓 P/L by Ticker &amp; Month {_win_label}</div>',
        unsafe_allow_html=True
    )
    _hm_df = all_cdf.copy()
    _hm_df['Month']     = pd.to_datetime(_hm_df['Close Date']).dt.strftime('%b %Y')
    _hm_df['MonthSort'] = pd.to_datetime(_hm_df['Close Date']).dt.strftime('%Y-%m')
    _hm_pivot = _hm_df.groupby(['Ticker', 'MonthSort', 'Month'])['Net P/L'].sum().reset_index()
    _months_sorted  = sorted(_hm_pivot['MonthSort'].unique())
    _month_labels   = [_hm_pivot[_hm_pivot['MonthSort'] == m]['Month'].iloc[0]
                       for m in _months_sorted]
    _tickers_sorted = sorted(
        _hm_pivot['Ticker'].unique(),
        key=lambda t: _hm_pivot[_hm_pivot['Ticker'] == t]['Net P/L'].sum(),
        reverse=True
    )
    _z = []; _text = []
    for tkr in _tickers_sorted:
        row_z, row_t = [], []
        for ms in _months_sorted:
            val = _hm_pivot[
                (_hm_pivot['Ticker'] == tkr) & (_hm_pivot['MonthSort'] == ms)
            ]['Net P/L'].sum()
            row_z.append(val if val != 0 else None)
            row_t.append('$%.0f' % val if val != 0 else '')
        _z.append(row_z); _text.append(row_t)
    _fig_hm = go.Figure(data=go.Heatmap(
        z=_z, x=_month_labels, y=_tickers_sorted,
        text=_text, texttemplate='%{text}', textfont=dict(size=10, family='IBM Plex Mono'),
        colorscale=[
            [0.0, '#7f1d1d'], [0.35, COLOURS['red']],
            [0.5, '#141c2e'],
            [0.65, COLOURS['green']], [1.0, '#004d3a'],
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
        best = all_cdf.nlargest(5, 'Net P/L')[
            ['Ticker', 'Trade Type', 'Type', 'Days Held', 'Net Premium', 'Net P/L']
        ].copy()
        best.columns = ['Ticker', 'Strategy', 'C/P', 'Days', 'Net Premium', 'P/L']
        st.dataframe(best.style.format({
            'Net Premium': lambda x: '${:.2f}'.format(x), 'P/L': lambda x: '${:.2f}'.format(x)
        }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)
    with wcol:
        st.markdown(f'##### 💀 Worst 5 Trades {_win_label}', unsafe_allow_html=True)
        worst = all_cdf.nsmallest(5, 'Net P/L')[
            ['Ticker', 'Trade Type', 'Type', 'Days Held', 'Net Premium', 'Net P/L']
        ].copy()
        worst.columns = ['Ticker', 'Strategy', 'C/P', 'Days', 'Net Premium', 'P/L']
        st.dataframe(worst.style.format({
            'Net Premium': lambda x: '${:.2f}'.format(x), 'P/L': lambda x: '${:.2f}'.format(x)
        }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)

    with st.expander(
        f'📋 Full Closed Trade Log  ·  {_win_start_str} → {_win_end_str}', expanded=False
    ):
        log = all_cdf[['Ticker', 'Trade Type', 'Type', 'Close Reason', 'Open Date', 'Close Date',
                        'Days Held', 'Expiration', 'DTE at Close', 'Contracts',
                        'Net Premium', '50% Target', 'Net P/L', 'Capture %',
                        'Capital at Risk', 'Ann Return %']].copy()
        log['Open Date']  = pd.to_datetime(log['Open Date'])
        log['Close Date'] = pd.to_datetime(log['Close Date'])
        log.rename(columns={
            'Trade Type': 'Strategy', 'Type': 'Call/Put', 'Close Reason': 'Close Reason',
            'Open Date': 'Open', 'Close Date': 'Close',
            'Net P/L': 'P/L',
            'Capital at Risk': 'Cap at Risk', 'Ann Return %': 'Ann Ret %'
        }, inplace=True)
        log = log.sort_values('Close', ascending=False)
        log['Ann Ret %'] = log.apply(_fmt_ann_ret, axis=1)
        st.dataframe(
            log.style.format({
                'Net Premium':    lambda x: '${:.2f}'.format(x),
                '50% Target': lambda v: '${:.2f}'.format(v) if pd.notna(v) else '—',
                'DTE at Close': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                'Contracts':  lambda v: '{:.0f}'.format(v) if pd.notna(v) else '—',
                'P/L':       lambda x: '${:.2f}'.format(x),
                'Cap at Risk':      lambda x: '${:,.0f}'.format(x),
                'Capture %': lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                'Ann Ret %': lambda v: v if isinstance(v, str) else
                             ('{:.0f}%'.format(v) if pd.notna(v) else '—'),
            }).apply(_style_ann_ret, axis=1).map(color_pnl_cell, subset=['P/L']),
            width='stretch', hide_index=True,
            column_config={
                'Open':        st.column_config.DateColumn('Open',        format='DD/MM/YY'),
                'Close':       st.column_config.DateColumn('Close',       format='DD/MM/YY'),
                'Expiration': st.column_config.DateColumn('Expiration', format='DD/MM/YY'),
            }
        )
        st.caption('\\* Trades held < 4 days — annualised return may be misleading.')


