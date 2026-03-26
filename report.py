"""
report.py — HTML report export for TastyMechanics.

Generates a dark-theme HTML report string (requires CDN for Plotly charts) containing:
  - Portfolio Overview scorecard (total P/L, dividends, interest, fees)
  - Premium Selling Scorecard — two rows matching Tab 1 (trade quality + risk/fees)
  - Capture % Distribution bar chart
  - Call vs Put + Strategy breakdown tables (side-by-side)
  - Cumulative P/L equity curve with drawdown fill
  - Weekly bar chart + Monthly candlestick (side-by-side)
  - Performance by Ticker — full expanded table

No Streamlit dependency — importable and testable standalone.
"""

import pandas as pd
import plotly.graph_objects as go

from config import COLOURS, WIN_RATE_GREEN, WIN_RATE_ORANGE, ANN_RETURN_CAP
from ui_components import fmt_dollar, chart_layout, xe


# ══════════════════════════════════════════════════════════════════════════════
# HTML REPORT EXPORT
# ══════════════════════════════════════════════════════════════════════════════

def build_html_report(all_cdf, credit_cdf, has_credit, has_data,
                      df_window, start_date, latest_date,
                      window_label, _win_suffix, _win_start_str, _win_end_str,
                      window_realized_pnl=0.0, total_realized_pnl=0.0,
                      div_income=0.0, int_net=0.0, total_fees=0.0,
                      net_deposited=0.0, selected_period='All Time',
                      daily_pnl_all=None):
    """Build a self-contained dark-theme HTML report string."""
    from datetime import datetime as _dt, timezone as _tz

    C = COLOURS

    # ── Computed metrics ───────────────────────────────────────────────────────
    _is_all_time = selected_period == 'All Time'
    _pnl_display = total_realized_pnl if _is_all_time else window_realized_pnl
    _trading_pnl = all_cdf['Net P/L'].sum() if has_data else 0.0
    window_days  = max((latest_date - start_date).days, 1)

    generated = _dt.now(_tz.utc).strftime('%Y-%m-%d %H:%M UTC')

    # ── Helpers ────────────────────────────────────────────────────────────────
    plotly_included = [False]

    def _fig_html(fig):
        inc = 'cdn' if not plotly_included[0] else False
        plotly_included[0] = True
        return fig.to_html(full_html=False, include_plotlyjs=inc,
                           config={'displayModeBar': False})

    def _wr_color(rate):
        if rate >= WIN_RATE_GREEN:  return C['green']
        if rate >= WIN_RATE_ORANGE: return C['orange']
        return C['red']

    def _pnl_color(v):
        return C['green'] if v >= 0 else C['red']

    def _th(label, align='right'):
        return (
            '<th style="text-align:%s;padding:7px 10px;color:%s;'
            'font-size:0.7rem;text-transform:uppercase;letter-spacing:0.06em;'
            'font-weight:600;border-bottom:1px solid %s;">'
            '%s</th>' % (align, C['text_muted'], C['border'], label)
        )

    def _td(val, align='right', color='', mono=False):
        mono_s = 'font-family:monospace;' if mono else ''
        col_s  = 'color:%s;' % color if color else ''
        return (
            '<td style="text-align:%s;padding:6px 10px;%s%s">%s</td>'
            % (align, col_s, mono_s, val)
        )

    def _tbl(headers, rows, caption=''):
        head = '<tr>' + ''.join(_th(h, 'left' if i == 0 else 'right')
                                for i, h in enumerate(headers)) + '</tr>'
        cap = ('<caption style="color:%s;font-size:0.7rem;text-align:left;'
               'padding-bottom:8px;">%s</caption>' % (C['text_muted'], caption)) if caption else ''
        return (
            '<table style="width:100%;border-collapse:collapse;font-size:0.84rem;">'
            + cap
            + '<thead>' + head + '</thead>'
            '<tbody style="color:%s;">' % C['text']
            + ''.join(rows)
            + '</tbody></table>'
        )

    def _tr(cells, alt=False):
        bg = 'background:rgba(255,255,255,0.025);' if alt else ''
        return '<tr style="%s">' % bg + ''.join(cells) + '</tr>'

    # ── Section 1: Portfolio Overview ──────────────────────────────────────────
    pnl_col = _pnl_color(_pnl_display)
    port_cards = [
        ('Total P/L', fmt_dollar(_pnl_display), pnl_col),
        ('Trading P/L', fmt_dollar(_trading_pnl), _pnl_color(_trading_pnl)),
        ('Dividends', fmt_dollar(div_income), C['green'] if div_income >= 0 else C['red']),
        ('Interest (net)', fmt_dollar(int_net), _pnl_color(int_net)),
        ('Total Fees', fmt_dollar(total_fees), C['red'] if total_fees > 0 else C['text']),
        ('Deposited', fmt_dollar(net_deposited), C['text']),
        ('Total Trades', str(len(all_cdf)) if has_data else '0', C['text']),
    ]

    # ── Section 2: Premium Selling Scorecard ───────────────────────────────────
    scorecard_a = []   # Trade Quality row
    scorecard_b = []   # Risk & Fees row
    tastytrade_note = ''

    if has_credit:
        total_credit_rcvd    = credit_cdf['Net Premium'].sum()
        total_net_pnl_closed = credit_cdf['Net P/L'].sum()
        _net_keep_pct = (total_net_pnl_closed / total_credit_rcvd * 100
                         if total_credit_rcvd != 0 else 0.0)
        _wr = credit_cdf['Won'].mean() * 100
        _winners = all_cdf[all_cdf['Net P/L'] > 0]['Net P/L']
        _losers  = all_cdf[all_cdf['Net P/L'] < 0]['Net P/L']
        _avg_win  = _winners.mean() if not _winners.empty else 0.0
        _avg_loss = _losers.mean()  if not _losers.empty  else 0.0
        _ratio         = abs(_avg_win / _avg_loss) if _avg_loss != 0 else None
        _gross_profit  = credit_cdf[credit_cdf['Net P/L'] > 0]['Net P/L'].sum()
        _gross_loss    = abs(credit_cdf[credit_cdf['Net P/L'] <= 0]['Net P/L'].sum())
        _profit_factor = _gross_profit / _gross_loss if _gross_loss > 0 else float('inf')
        _fees_pct      = (total_fees / abs(total_net_pnl_closed) * 100
                          if total_net_pnl_closed != 0 else 0.0)
        _n_trades      = max(len(all_cdf), 1)

        scorecard_a = [
            ('Win Rate',           '%.1f%%' % _wr,                          _wr_color(_wr)),
            ('Median Capture %',   '%.1f%%' % credit_cdf['Capture %'].median(), C['text']),
            ('Net Prem Kept %',    '%.1f%%' % _net_keep_pct,                _pnl_color(_net_keep_pct)),
            ('Med Days in Trade',  '%.0fd'  % credit_cdf['Days Held'].median(), C['text']),
            ('Med Ann. Return',    '%.0f%%' % credit_cdf['Ann Return %'].median(), C['text']),
            ('Med Prem/Day',       fmt_dollar(credit_cdf['Prem/Day'].median()), C['text']),
            ('Kept $/Day',         fmt_dollar(total_net_pnl_closed / window_days), _pnl_color(total_net_pnl_closed)),
        ]
        scorecard_b = [
            ('Avg Winner',      fmt_dollar(_avg_win),                               C['green']),
            ('Avg Loser',       fmt_dollar(_avg_loss),                              C['red']),
            ('Win/Loss Ratio',  '%.2f×' % _ratio if _ratio is not None else '∞',   C['text']),
            ('Total Fees',      fmt_dollar(total_fees),                             C['red'] if total_fees > 0 else C['text']),
            ('Fees % of P/L',   '%.1f%%' % _fees_pct,                              C['text']),
            ('Fees/Trade',      fmt_dollar(total_fees / _n_trades),                C['text']),
            ('Profit Factor',   '%.2f' % _profit_factor if _profit_factor != float('inf') else '∞', C['text']),
        ]
        tastytrade_note = (
            'TastyTrade targets: <strong style="color:%s">50%% capture at close</strong>'
            ' &nbsp;·&nbsp; <strong style="color:%s">25%% net premium kept</strong>'
            % (C['blue'], C['blue'])
        )

    # ── Section 3: Capture % Distribution chart ────────────────────────────────
    html_cap = ''
    if has_credit:
        bins   = [-999, 0, 25, 50, 75, 100, 999]
        labels = ['Loss', '0–25%', '25–50%', '50–75%', '75–100%', '>100%']
        bkt_colors = [C['red'], '#ffa421', '#ffe066', '#7ec8e3', C['green'], C['blue']]
        credit_cdf = credit_cdf.copy()
        credit_cdf['Bucket'] = pd.cut(credit_cdf['Capture %'], bins=bins, labels=labels)
        bkt_df = credit_cdf.groupby('Bucket', observed=False).agg(
            Trades=('Net P/L', 'count')).reset_index()
        fig_cap = go.Figure()
        fig_cap.add_trace(go.Bar(
            x=bkt_df['Bucket'].astype(str),
            y=bkt_df['Trades'],
            marker_color=bkt_colors,
            text=bkt_df['Trades'],
            textposition='outside',
            textfont=dict(size=11, color=C['text']),
        ))
        _cap_lay = chart_layout('Premium Capture % Distribution' + _win_suffix, height=300, margin_t=40)
        _cap_lay['showlegend']          = False
        _cap_lay['xaxis']['title']      = dict(text='Capture Bucket', font=dict(size=11))
        _cap_lay['yaxis']['title']      = dict(text='# Trades',       font=dict(size=11))
        _cap_lay['xaxis']['fixedrange'] = True
        _cap_lay['yaxis']['fixedrange'] = True
        fig_cap.update_layout(**_cap_lay)
        html_cap = _fig_html(fig_cap)

    # ── Section 4: Call vs Put table ───────────────────────────────────────────
    cvp_rows = []
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
        # totals row
        _tot = {
            'Type': '— Total',
            'Trades': int(type_df['Trades'].sum()),
            'Win_Rate': round(credit_cdf['Won'].mean() * 100, 1),
            'Med_Capture': round(credit_cdf['Capture %'].median(), 1),
            'Total_PNL': type_df['Total_PNL'].sum(),
            'Avg_PremDay': round(type_df['Avg_PremDay'].mean(), 1),
            'Med_Days': round(credit_cdf['Days Held'].median(), 1),
            'Med_DTE': round(credit_cdf['DTE at Open'].median(), 1),
        }
        for i, r in enumerate(type_df.itertuples(index=False)):
            cvp_rows.append(_tr([
                _td(xe(str(r.Type)),       'left'),
                _td(str(int(r.Trades))),
                _td('%.1f%%' % r.Win_Rate,  color=_wr_color(r.Win_Rate)),
                _td('%.1f%%' % r.Med_Capture),
                _td(fmt_dollar(r.Total_PNL), color=_pnl_color(r.Total_PNL), mono=True),
                _td('$%.2f'  % r.Avg_PremDay),
                _td('%.0fd'  % r.Med_Days),
                _td('%.0fd'  % r.Med_DTE),
            ], alt=bool(i % 2)))
        cvp_rows.append(_tr([
            _td('<strong>— Total</strong>', 'left'),
            _td('<strong>%d</strong>' % int(type_df['Trades'].sum())),
            _td('<strong>%.1f%%</strong>' % (credit_cdf['Won'].mean() * 100),
                color=_wr_color(credit_cdf['Won'].mean() * 100)),
            _td('<strong>%.1f%%</strong>' % credit_cdf['Capture %'].median()),
            _td('<strong>%s</strong>' % fmt_dollar(type_df['Total_PNL'].sum()),
                color=_pnl_color(type_df['Total_PNL'].sum()), mono=True),
            _td('<strong>$%.2f</strong>' % credit_cdf['Prem/Day'].median()),
            _td('<strong>%.0fd</strong>' % credit_cdf['Days Held'].median()),
            _td('<strong>%.0fd</strong>' % credit_cdf['DTE at Open'].median()),
        ]))

    # ── Section 4b: Strategy breakdown table ──────────────────────────────────
    strat_rows = []
    if has_data:
        strat_df = all_cdf.groupby('Trade Type').agg(
            Trades=('Won', 'count'),
            Win_Rate=('Won', lambda x: x.mean() * 100),
            Total_PNL=('Net P/L', 'sum'),
            Med_Capture=('Capture %', 'median'),
            Med_Days=('Days Held', 'median'),
            Med_DTE=('DTE at Open', 'median'),
        ).reset_index().sort_values('Total_PNL', ascending=False).round(1)
        spread_map = all_cdf.groupby('Trade Type')['Spread'].first()
        strat_df['risk'] = strat_df['Trade Type'].map(spread_map)
        strat_df.loc[strat_df['Trade Type'] == 'Covered Call', 'risk'] = True
        for i, (_, r) in enumerate(strat_df.iterrows()):
            dot = '🔵 ' if r['risk'] == True else ('🟠 ' if r['risk'] == False else '')  # noqa: E712 — numpy.bool_ fails with `is`
            dim = 'opacity:0.45;font-style:italic;' if r['Trades'] < 5 else ''
            strat_rows.append(
                '<tr style="background:%s;%s">' % (
                    'rgba(255,255,255,0.025)' if i % 2 else '', dim)
                + _td(dot + xe(str(r['Trade Type'])), 'left')
                + _td(str(int(r['Trades'])))
                + _td('%.1f%%' % r['Win_Rate'], color=_wr_color(r['Win_Rate']))
                + _td(fmt_dollar(r['Total_PNL']), color=_pnl_color(r['Total_PNL']), mono=True)
                + _td('%.1f%%' % r['Med_Capture'] if pd.notna(r['Med_Capture']) else '—')
                + _td('%.0fd' % r['Med_Days'] if pd.notna(r['Med_Days']) else '—')
                + _td('%.0fd' % r['Med_DTE'] if pd.notna(r['Med_DTE']) else '—')
                + '</tr>'
            )
        _strat_total_pnl = strat_df['Total_PNL'].sum()
        strat_rows.append(_tr([
            _td('<strong>— Total</strong>', 'left'),
            _td('<strong>%d</strong>' % int(strat_df['Trades'].sum())),
            _td('<strong>%.1f%%</strong>' % (all_cdf['Won'].mean() * 100),
                color=_wr_color(all_cdf['Won'].mean() * 100)),
            _td('<strong>%s</strong>' % fmt_dollar(_strat_total_pnl),
                color=_pnl_color(_strat_total_pnl), mono=True),
            _td('—'), _td('—'), _td('—'),
        ]))

    # ── Section 5: Equity curve — mirrors Tab 4 (daily_pnl_all, full history) ──
    html_eq = ''
    _eq_src = daily_pnl_all if (daily_pnl_all is not None and not daily_pnl_all.empty) else None
    if _eq_src is not None:
        cum_df = _eq_src.sort_values('Date').copy()
        cum_df['Cum']  = cum_df['PnL'].cumsum()
        cum_df['Peak'] = cum_df['Cum'].cummax()
        final_pnl = cum_df['Cum'].iloc[-1]
        eq_color = C['green'] if final_pnl >= 0 else C['red']
        eq_fill  = 'rgba(0,204,150,0.10)' if final_pnl >= 0 else 'rgba(239,85,59,0.10)'
        fig_eq = go.Figure()
        # Drawdown fill
        fig_eq.add_trace(go.Scatter(
            x=pd.concat([cum_df['Date'], cum_df['Date'][::-1]]),
            y=pd.concat([cum_df['Peak'], cum_df['Cum'][::-1]]),
            fill='toself', fillcolor='rgba(239,85,59,0.10)',
            line=dict(color='rgba(0,0,0,0)'), showlegend=False,
            hoverinfo='skip', name='Drawdown',
        ))
        # Equity line
        fig_eq.add_trace(go.Scatter(
            x=cum_df['Date'], y=cum_df['Cum'],
            mode='lines', line=dict(color=eq_color, width=2),
            fill='tozeroy', fillcolor=eq_fill,
            hovertemplate='%{x|%d %b %y}<br><b>%{y:$,.2f}</b><extra></extra>',
            name='Cumulative P/L',
        ))
        # Final value annotation
        fig_eq.add_annotation(
            x=cum_df['Date'].iloc[-1], y=final_pnl,
            text='<b>' + fmt_dollar(final_pnl) + '</b>',
            showarrow=True, arrowhead=2, arrowcolor=eq_color,
            font=dict(color=eq_color, size=12),
            bgcolor='rgba(10,14,23,0.8)', bordercolor=eq_color, borderwidth=1,
            xanchor='right', yanchor='bottom',
        )
        fig_eq.add_hline(y=0, line_color='rgba(255,255,255,0.12)', line_width=1)
        _eq_lay = chart_layout(
            'Portfolio Equity Curve — Cumulative Realized P/L', height=340, margin_t=40)
        _eq_lay['yaxis']['tickprefix'] = '$'
        _eq_lay['yaxis']['tickformat'] = ',.0f'
        _eq_lay['showlegend'] = False
        fig_eq.update_layout(**_eq_lay)
        html_eq = _fig_html(fig_eq)

    # ── Section 6a: Weekly cash flow bar ──────────────────────────────────────
    html_wk = ''
    html_mo = ''
    if has_data:
        _pdf = all_cdf.copy()
        _pdf['CloseDate'] = pd.to_datetime(_pdf['Close Date'])
        _pdf = _pdf.sort_values('CloseDate')
        _pdf['Week']  = _pdf['CloseDate'].dt.to_period('W').apply(lambda p: p.start_time)
        _pdf['Month'] = _pdf['CloseDate'].dt.to_period('M').apply(lambda p: p.start_time)
        _pdf['CumPL'] = _pdf['Net P/L'].cumsum()

        # Weekly bar chart
        wk_df = _pdf.groupby('Week', sort=True).agg(
            Net=('Net P/L', 'sum'),
            Trades=('Net P/L', 'count'),
        ).reset_index()
        wk_colors = [C['green'] if v >= 0 else C['red'] for v in wk_df['Net']]
        fig_wk = go.Figure()
        fig_wk.add_trace(go.Bar(
            x=wk_df['Week'], y=wk_df['Net'],
            marker_color=wk_colors,
            customdata=list(zip([fmt_dollar(r) for r in wk_df['Net']], wk_df['Trades'])),
            hovertemplate='<b>w/c %{x|%d %b}</b><br>P/L: <b>%{customdata[0]}</b><br>Trades: %{customdata[1]}<extra></extra>',
        ))
        fig_wk.add_hline(y=0, line_color='rgba(255,255,255,0.12)', line_width=1)
        _wk_lay = chart_layout('Weekly P/L' + _win_suffix, height=290, margin_t=36)
        _wk_lay['yaxis']['tickprefix'] = '$'
        _wk_lay['yaxis']['tickformat'] = ',.0f'
        _wk_lay['showlegend'] = False
        fig_wk.update_layout(**_wk_lay)
        html_wk = _fig_html(fig_wk)

        # Monthly candlestick
        def _cagg(group_col):
            rows, prev = [], 0.0
            for period, grp in _pdf.groupby(group_col, sort=True):
                o = prev; c = grp['CumPL'].iloc[-1]
                rows.append({'Period': pd.Timestamp(period),
                             'Open': o, 'High': max(grp['CumPL'].max(), o),
                             'Low':  min(grp['CumPL'].min(), o), 'Close': c,
                             'Net': grp['Net P/L'].sum(), 'Trades': len(grp)})
                prev = c
            return pd.DataFrame(rows)

        mo_df = _cagg('Month')
        fig_mo = go.Figure()
        fig_mo.add_trace(go.Candlestick(
            x=mo_df['Period'], open=mo_df['Open'], high=mo_df['High'],
            low=mo_df['Low'], close=mo_df['Close'],
            increasing=dict(line=dict(color=C['green'], width=1), fillcolor='rgba(0,204,150,0.5)'),
            decreasing=dict(line=dict(color=C['red'],   width=1), fillcolor='rgba(239,85,59,0.5)'),
            customdata=list(zip([fmt_dollar(r) for r in mo_df['Net']], mo_df['Trades'],
                                [fmt_dollar(r) for r in mo_df['Open']],
                                [fmt_dollar(r) for r in mo_df['Close']])),
            hovertemplate=(
                '<b>%{x|%b %Y}</b><br>'
                'Net: <b>%{customdata[0]}</b> (%{customdata[1]} trades)<br>'
                'Open: %{customdata[2]}  Close: %{customdata[3]}<extra></extra>'
            ),
            name='',
        ))
        fig_mo.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
        _mo_lay = chart_layout('Monthly P/L (Cumulative Candles)' + _win_suffix, height=290, margin_t=36)
        _mo_lay['xaxis']['type']        = 'date'
        _mo_lay['xaxis']['tickformat']  = '%b %Y'
        _mo_lay['yaxis']['tickprefix']  = '$'
        _mo_lay['yaxis']['tickformat']  = ',.0f'
        _mo_lay['xaxis']['rangeslider'] = {'visible': False}
        fig_mo.update_layout(**_mo_lay)
        html_mo = _fig_html(fig_mo)

    # ── Section 7: Performance by Ticker ──────────────────────────────────────
    ticker_rows = []
    if has_data:
        all_by_ticker = all_cdf.groupby('Ticker').agg(
            Wins=('Won', 'sum'),
            Losses=('Won', lambda x: (x == 0).sum()),
            Trades=('Net P/L', 'count'),
            Win_Rate=('Won', lambda x: x.mean() * 100),
            Total_PNL=('Net P/L', 'sum'),
            Avg_Days=('Days Held', 'mean'),
        ).round(1)
        all_by_ticker['WL'] = (
            all_by_ticker['Wins'].astype(int).astype(str) + '/' +
            all_by_ticker['Losses'].astype(int).astype(str)
        )
        all_by_ticker['PnL_per_DTE'] = (
            all_by_ticker['Total_PNL'] /
            all_by_ticker['Avg_Days'].replace(0, float('nan'))
        ).round(2)
        if has_credit:
            credit_by_ticker = credit_cdf.groupby('Ticker').agg(
                Med_Capture=('Capture %', 'median'),
                Med_Ann=('Ann Return %', 'median'),
                Total_Prem=('Net Premium', 'sum'),
            ).round(1)
            tdf = all_by_ticker.join(credit_by_ticker, how='left').reset_index()
        else:
            tdf = all_by_ticker.reset_index()
            tdf['Med_Capture'] = None
            tdf['Med_Ann']     = None
            tdf['Total_Prem']  = None
        tdf = tdf.sort_values('Total_PNL', ascending=False)

        for i, row in enumerate(tdf.itertuples(index=False)):
            cap_str  = '%.1f%%' % row.Med_Capture if pd.notna(row.Med_Capture) else '—'
            prem_str = fmt_dollar(row.Total_Prem)   if pd.notna(row.Total_Prem)  else '—'
            dit_str  = '$%.2f' % row.PnL_per_DTE    if pd.notna(row.PnL_per_DTE) else '—'
            if pd.notna(row.Med_Ann):
                ann_str = ('⚠ %.0f%%' if abs(row.Med_Ann) >= ANN_RETURN_CAP else '%.0f%%') % row.Med_Ann
                ann_col = C['orange'] if abs(row.Med_Ann) >= ANN_RETURN_CAP else C['text']
            else:
                ann_str, ann_col = '—', C['text']
            dim = 'opacity:0.4;font-style:italic;' if (int(row.Wins) + int(row.Losses)) < 3 else ''
            ticker_rows.append(
                '<tr style="background:%s;%s">' % (
                    'rgba(255,255,255,0.025)' if i % 2 else '', dim)
                + _td('<strong style="font-family:monospace;color:%s;">%s</strong>'
                      % (C['white'], xe(str(row.Ticker))), 'left')
                + _td(str(row.WL))
                + _td('%.1f%%' % row.Win_Rate, color=_wr_color(row.Win_Rate))
                + _td(fmt_dollar(row.Total_PNL), color=_pnl_color(row.Total_PNL), mono=True)
                + _td('%.0fd' % row.Avg_Days)
                + _td(dit_str, mono=True)
                + _td(cap_str)
                + _td(ann_str, color=ann_col)
                + _td(prem_str, mono=True)
                + '</tr>'
            )

    # ══════════════════════════════════════════════════════════════════════════
    # CSS
    # ══════════════════════════════════════════════════════════════════════════
    _css = (
        '* { box-sizing: border-box; margin: 0; padding: 0; }\n'
        'body { background: #0a0e17; color: ' + C['text'] + '; '
        'font-family: "IBM Plex Sans", system-ui, -apple-system, sans-serif; '
        'font-size: 14px; line-height: 1.6; padding: 28px 20px 48px; }\n'
        '.wrap { max-width: 1200px; margin: 0 auto; }\n'
        '.report-header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 6px; }\n'
        '.report-title { font-size: 1.5rem; font-weight: 700; color: ' + C['text'] + '; }\n'
        '.report-badge { background: ' + C['border'] + '; color: ' + C['text_muted'] + '; '
        'font-size: 0.72rem; font-weight: 600; text-transform: uppercase; '
        'letter-spacing: 0.07em; padding: 3px 10px; border-radius: 99px; }\n'
        '.report-meta { color: ' + C['text_muted'] + '; font-size: 0.8rem; margin-bottom: 28px; }\n'
        '.section { background: ' + C['card_bg'] + '; border: 1px solid ' + C['border'] + '; '
        'border-radius: 10px; padding: 20px 22px; margin-bottom: 20px; }\n'
        '.section-label { font-size: 0.65rem; font-weight: 700; letter-spacing: 0.12em; '
        'text-transform: uppercase; color: ' + C['text_dim'] + '; margin-bottom: 4px; }\n'
        '.section-title { font-size: 1.0rem; font-weight: 600; color: ' + C['text'] + '; '
        'margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid ' + C['border'] + '; }\n'
        '.section-note { color: ' + C['text_muted'] + '; font-size: 0.75rem; margin-bottom: 12px; }\n'
        '.metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); '
        'gap: 10px; margin-bottom: 14px; }\n'
        '.metric-card { background: ' + C['card_bg2'] + '; border: 1px solid ' + C['border'] + '; '
        'border-radius: 8px; padding: 13px 15px; }\n'
        '.metric-label { font-size: 0.67rem; text-transform: uppercase; letter-spacing: 0.07em; '
        'color: ' + C['text_muted'] + '; margin-bottom: 5px; font-weight: 600; }\n'
        '.metric-value { font-family: monospace; font-size: 1.1rem; font-weight: 700; }\n'
        '.metric-row-label { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.08em; '
        'color: ' + C['text_dim'] + '; font-weight: 700; '
        'margin: 14px 0 8px; padding-top: 12px; border-top: 1px solid ' + C['border'] + '; }\n'
        '.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }\n'
        '.charts-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }\n'
        '@media(max-width:800px) { .two-col, .charts-row { grid-template-columns: 1fr; } }\n'
        '.tbl-wrap { overflow-x: auto; }\n'
        'table { width: 100%; border-collapse: collapse; font-size: 0.83rem; }\n'
        'tr:hover td { background: rgba(255,255,255,0.04); }\n'
        '.footer { color: ' + C['text_dim'] + '; font-size: 0.72rem; '
        'text-align: center; margin-top: 32px; padding-top: 14px; '
        'border-top: 1px solid ' + C['border'] + '; }\n'
        '@media print { body { background: #fff; color: #111; padding: 16px; } '
        '.section { background: #f8f8f8; border-color: #ccc; } '
        '.metric-card { background: #f0f0f0; border-color: #ccc; } '
        '.metric-label { color: #555; } }\n'
    )

    # ══════════════════════════════════════════════════════════════════════════
    # HTML ASSEMBLY HELPERS
    # ══════════════════════════════════════════════════════════════════════════
    def _section(label, title, body):
        return (
            '<div class="section">'
            '<div class="section-label">%s</div>'
            '<div class="section-title">%s</div>'
            '%s</div>\n' % (label, title, body)
        )

    def _metric_card(label, value, color=''):
        col_s = 'color:%s;' % color if color else 'color:%s;' % C['text']
        return (
            '<div class="metric-card">'
            '<div class="metric-label">%s</div>'
            '<div class="metric-value" style="%s">%s</div>'
            '</div>' % (label, col_s, value)
        )

    def _cards_html(cards):
        return ('<div class="metric-grid">'
                + ''.join(_metric_card(l, v, c) for l, v, c in cards)
                + '</div>')

    # ── Build sections ─────────────────────────────────────────────────────────

    # Section 1 — Portfolio Overview
    port_body = (
        '<div class="section-note">'
        'Total P/L includes trading gains, dividends, and interest. '
        'Trading P/L is options and equity closes only.</div>'
        + _cards_html(port_cards)
    )
    s_overview = _section('Portfolio', '📊 Overview', port_body)

    # Section 2 — Scorecard
    if scorecard_a:
        sc_body = (
            '<div class="section-note">Credit trades only (Short Puts, Covered Calls, Strangles, Iron Condors, etc.)</div>'
            '<div class="metric-row-label">Trade Quality</div>'
            + _cards_html(scorecard_a)
            + '<div class="metric-row-label">Risk &amp; Fees</div>'
            + _cards_html(scorecard_b)
        )
        if tastytrade_note:
            sc_body += ('<div class="section-note" style="margin-top:10px;">'
                        + tastytrade_note + '</div>')
        s_scorecard = _section('Options', '🎯 Premium Selling Scorecard', sc_body)
    else:
        s_scorecard = _section('Options', '🎯 Premium Selling Scorecard',
                               '<p class="section-note">No closed credit trades in this window.</p>')

    # Section 3 — Capture distribution
    if html_cap:
        s_capture = _section('Distribution', '📊 Premium Capture %', html_cap)
    else:
        s_capture = ''

    # Section 4 — Call vs Put + Strategy
    if cvp_rows or strat_rows:
        cvp_tbl   = _tbl(['Type', 'Trades', 'Win %', 'Capture %', 'P/L', 'Prem/Day', 'Med Days', 'DTE at Entry'], cvp_rows)   if cvp_rows   else '<p class="section-note">No credit trades.</p>'
        strat_tbl = _tbl(['Strategy', 'Trades', 'Win %', 'P/L', 'Capture %', 'Med Days', 'DTE at Entry'], strat_rows) if strat_rows else '<p class="section-note">No data.</p>'
        split_body = (
            '<div class="two-col">'
            '<div><div class="metric-row-label" style="margin-top:0;">Call vs Put</div>'
            '<div class="tbl-wrap">%s</div></div>'
            '<div><div class="metric-row-label" style="margin-top:0;">'
            '🔵 Defined Risk &nbsp; 🟠 Undefined Risk</div>'
            '<div class="tbl-wrap">%s</div>'
            '<p class="section-note" style="margin-top:8px;">Dim = fewer than 5 trades.</p>'
            '</div></div>'
        ) % (cvp_tbl, strat_tbl)
        s_breakdown = _section('Breakdown', '🧩 Trade Breakdown', split_body)
    else:
        s_breakdown = ''

    # Section 5 — Equity Curve
    s_equity = _section('P/L', '📈 Cumulative Realized P/L', html_eq) if html_eq else ''

    # Section 6 — Weekly + Monthly charts
    if html_wk or html_mo:
        charts_body = (
            '<div class="charts-row">'
            '<div>%s</div><div>%s</div>'
            '</div>'
            '<p class="section-note" style="margin-top:10px;">'
            'Monthly candles show cumulative P/L open/high/low/close per month. '
            'Green = closed month higher than it opened. Wicks show intra-month extremes.</p>'
        ) % (html_wk, html_mo)
        s_cashflow = _section('Cash Flow', '📅 Weekly &amp; Monthly P/L', charts_body)
    else:
        s_cashflow = ''

    # Section 7 — Ticker table
    if ticker_rows:
        tbl_html = _tbl(
            ['Ticker', 'W/L', 'Win %', 'P/L', 'Avg Days', 'P/L per DIT', 'Capture %', 'Ann Ret %', 'Net Prem'],
            ticker_rows,
        )
        ticker_body = (
            '<div class="section-note">'
            'W/L = wins / losses. P/L per DIT = total P/L ÷ avg days in trade. '
            'Ann Ret % capped at ±' + str(ANN_RETURN_CAP) + '% — ⚠ = capped. Dim = fewer than 3 trades.</div>'
            '<div class="tbl-wrap">' + tbl_html + '</div>'
        )
        s_tickers = _section('Performance', '🏷 By Ticker', ticker_body)
    else:
        s_tickers = ''

    # ══════════════════════════════════════════════════════════════════════════
    # Final assembly
    # ══════════════════════════════════════════════════════════════════════════
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '<title>TastyMechanics Report · %s</title>\n'
        '<style>%s</style>\n</head>\n<body>\n'
        '<div class="wrap">\n'
        '<div class="report-header">'
        '<span class="report-title">📊 TastyMechanics Report</span>'
        '<span class="report-badge">%s</span>'
        '</div>\n'
        '<div class="report-meta">Period: <strong style="color:%s">%s → %s</strong>'
        ' &nbsp;·&nbsp; Generated: %s</div>\n'
        % (window_label, _css, selected_period,
           C['text'], _win_start_str, _win_end_str, generated)
        + s_overview
        + s_scorecard
        + s_capture
        + s_breakdown
        + s_equity
        + s_cashflow
        + s_tickers
        + '<div class="footer">TastyMechanics · %s</div>\n' % generated
        + '</div>\n</body>\n</html>'
    )
