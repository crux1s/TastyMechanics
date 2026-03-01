"""
report.py — HTML report export for TastyMechanics.

Generates a self-contained dark-theme HTML report string containing:
  - Portfolio Overview scorecard (total P/L, dividends, interest, fees)
  - Options Trading scorecard (credit trades only — win rate, capture %, etc.)
  - Cumulative P/L equity curve (Plotly, embedded via CDN)
  - Weekly and Monthly P/L candlestick charts (Plotly, embedded)
  - Performance by ticker table

No Streamlit dependency — importable and testable standalone.
"""

import pandas as pd
import plotly.graph_objects as go

from config import COLOURS
from ui_components import fmt_dollar, chart_layout



# ══════════════════════════════════════════════════════════════════════════════
# HTML REPORT EXPORT
# ══════════════════════════════════════════════════════════════════════════════

def build_html_report(all_cdf, credit_cdf, has_credit, has_data,
                      df_window, start_date, latest_date,
                      window_label, _win_suffix, _win_start_str, _win_end_str,
                      window_realized_pnl=0.0, total_realized_pnl=0.0,
                      div_income=0.0, int_net=0.0, total_fees=0.0,
                      net_deposited=0.0, selected_period='All Time'):
    """Build a self-contained dark-theme HTML report string.
    Two scorecard sections:
      1. Portfolio Overview  — total P/L, dividends, interest, fees, net deposited
      2. Options Trading     — credit-trade-only metrics (win rate, capture, etc.)
    """
    from datetime import datetime as _dt, timezone as _tz

    C = COLOURS

    # ── Section 1: Portfolio Overview metrics ─────────────────────────────────
    _is_all_time    = selected_period == 'All Time'
    _pnl_display    = total_realized_pnl if _is_all_time else window_realized_pnl
    _trading_pnl    = all_cdf['Net P/L'].sum()   # options + equity closes only
    portfolio_metrics = {
        'Total P/L (incl. div/int)': fmt_dollar(_pnl_display),
        'Trading P/L':               fmt_dollar(_trading_pnl),
        'Dividends':                 fmt_dollar(div_income),
        'Interest (net)':            fmt_dollar(int_net),
        'Total Fees':                fmt_dollar(total_fees),
        'Net Deposited':             fmt_dollar(net_deposited),
        'Total Trades':              str(len(all_cdf)),
    }

    # ── Section 2: Options Trading metrics (credit trades only) ───────────────
    options_metrics = {}
    if has_credit:
        window_days = max((latest_date - start_date).days, 1)
        total_credit_rcvd    = credit_cdf['Net Premium'].sum()
        total_net_pnl_closed = credit_cdf['Net P/L'].sum()
        _winners = all_cdf[all_cdf['Net P/L'] > 0]['Net P/L']
        _losers  = all_cdf[all_cdf['Net P/L'] < 0]['Net P/L']
        _avg_win  = _winners.mean() if not _winners.empty else 0.0
        _avg_loss = _losers.mean()  if not _losers.empty  else 0.0
        _ratio         = abs(_avg_win / _avg_loss) if _avg_loss != 0 else None
        _gross_profit  = credit_cdf[credit_cdf['Net P/L'] > 0]['Net P/L'].sum()
        _gross_loss    = abs(credit_cdf[credit_cdf['Net P/L'] <= 0]['Net P/L'].sum())
        _profit_factor = _gross_profit / _gross_loss if _gross_loss > 0 else float('inf')
        options_metrics = {
            'Win Rate':           '%.1f%%' % (credit_cdf['Won'].mean() * 100),
            'Median Capture %':   '%.1f%%' % credit_cdf['Capture %'].median(),
            'Median Days Held':   '%.0fd'  % credit_cdf['Days Held'].median(),
            'Median Ann. Return': '%.0f%%' % credit_cdf['Ann Return %'].median(),
            'Med Premium/Day':    fmt_dollar(credit_cdf['Prem/Day'].median()),
            'Banked $/Day':       fmt_dollar(total_net_pnl_closed / window_days),
            'Avg Winner':         fmt_dollar(_avg_win),
            'Avg Loser':          fmt_dollar(_avg_loss),
            'Win/Loss Ratio':     '%.2f×' % _ratio if _ratio else '∞',
            'Profit Factor':      '%.2f'  % _profit_factor if _profit_factor != float('inf') else '∞',
        }

    # ── Performance by ticker ─────────────────────────────────────────────────
    ticker_rows = ''
    if has_data:
        all_by_ticker = all_cdf.groupby('Ticker').agg(
            Trades=('Net P/L', 'count'),
            Win_Rate=('Won', lambda x: x.mean() * 100),
            Total_PNL=('Net P/L', 'sum'),
            Med_Days=('Days Held', 'median'),
        ).round(1)
        if has_credit:
            credit_by_ticker = credit_cdf.groupby('Ticker').agg(
                Med_Capture=('Capture %', 'median'),
                Total_Prem=('Net Premium', 'sum'),
            ).round(1)
            tdf = all_by_ticker.join(credit_by_ticker, how='left').reset_index()
        else:
            tdf = all_by_ticker.reset_index()
            tdf['Med_Capture'] = None
            tdf['Total_Prem']  = None
        tdf = tdf.sort_values('Total_PNL', ascending=False)
        for _, row in tdf.iterrows():
            pnl_col = C['green'] if row['Total_PNL'] >= 0 else C['red']
            wr_col  = C['green'] if row['Win_Rate'] >= 70 else (C['orange'] if row['Win_Rate'] >= 50 else C['red'])
            cap_str = '%.1f%%' % row['Med_Capture'] if pd.notna(row.get('Med_Capture')) else '\u2014'
            prem_str = fmt_dollar(row['Total_Prem']) if pd.notna(row.get('Total_Prem')) else '\u2014'
            ticker_rows += (
                '<tr>'
                '<td style="font-family:monospace;font-weight:600;">' + str(row['Ticker']) + '</td>'
                '<td>' + str(int(row['Trades'])) + '</td>'
                '<td style="color:' + wr_col + ';">' + '%.1f%%' % row['Win_Rate'] + '</td>'
                '<td style="color:' + pnl_col + ';font-family:monospace;">' + fmt_dollar(row['Total_PNL']) + '</td>'
                '<td>' + '%.0fd' % row['Med_Days'] + '</td>'
                '<td>' + cap_str + '</td>'
                '<td>' + prem_str + '</td>'
                '</tr>\n'
            )

    # ── Charts ────────────────────────────────────────────────────────────────
    plotly_included = [False]

    def _fig_html(fig):
        inc = 'cdn' if not plotly_included[0] else False
        plotly_included[0] = True
        return fig.to_html(full_html=False, include_plotlyjs=inc,
                           config={'displayModeBar': False})

    # Equity curve
    cum_df = all_cdf.sort_values('Close Date').copy()
    cum_df['Cumulative P/L'] = cum_df['Net P/L'].cumsum()
    final_pnl = cum_df['Cumulative P/L'].iloc[-1]
    eq_color = C['green'] if final_pnl >= 0 else C['red']
    eq_fill  = 'rgba(0,204,150,0.12)' if final_pnl >= 0 else 'rgba(239,85,59,0.12)'
    fig_eq = go.Figure()
    fig_eq.add_trace(go.Scatter(
        x=cum_df['Close Date'], y=cum_df['Cumulative P/L'],
        mode='lines', line=dict(color=eq_color, width=2),
        fill='tozeroy', fillcolor=eq_fill,
        hovertemplate='%{x|%d/%m/%y}<br><b>$%{y:,.2f}</b><extra></extra>'
    ))
    fig_eq.add_hline(y=0, line_color='rgba(255,255,255,0.1)', line_width=1)
    _eq_lay = chart_layout('Cumulative Realized P/L' + _win_suffix, height=320, margin_t=40)
    _eq_lay['yaxis']['tickprefix'] = '$'
    _eq_lay['yaxis']['tickformat'] = ',.0f'
    fig_eq.update_layout(**_eq_lay)
    html_eq = _fig_html(fig_eq)

    # Weekly + monthly candles
    _pdf = all_cdf.copy()
    _pdf['CloseDate'] = pd.to_datetime(_pdf['Close Date'])
    _pdf = _pdf.sort_values('CloseDate')
    _pdf['Week']  = _pdf['CloseDate'].dt.to_period('W').apply(lambda p: p.start_time)
    _pdf['Month'] = _pdf['CloseDate'].dt.to_period('M').apply(lambda p: p.start_time)
    _pdf['CumPL'] = _pdf['Net P/L'].cumsum()

    def _cagg(group_col):
        rows, prev = [], 0.0
        for period, grp in _pdf.groupby(group_col, sort=True):
            o = prev; c = grp['CumPL'].iloc[-1]
            rows.append({'Period': pd.Timestamp(str(period)),
                         'Open': o, 'High': max(grp['CumPL'].max(), o),
                         'Low':  min(grp['CumPL'].min(), o), 'Close': c,
                         'Net': grp['Net P/L'].sum(), 'Trades': len(grp)})
            prev = c
        return pd.DataFrame(rows)

    def _cfig(df_c, title, x_fmt):
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df_c['Period'], open=df_c['Open'], high=df_c['High'],
            low=df_c['Low'],  close=df_c['Close'],
            increasing=dict(line=dict(color=C['green'], width=1), fillcolor='rgba(0,204,150,0.5)'),
            decreasing=dict(line=dict(color=C['red'],   width=1), fillcolor='rgba(239,85,59,0.5)'),
            customdata=list(zip([fmt_dollar(r) for r in df_c['Net']], df_c['Trades'],
                                [fmt_dollar(r) for r in df_c['Open']],
                                [fmt_dollar(r) for r in df_c['Close']])),
            hovertemplate=(
                '<b>%{x|' + x_fmt + '}</b><br>'
                'Net: <b>%{customdata[0]}</b> (%{customdata[1]} trades)<br>'
                'Open: %{customdata[2]}  Close: %{customdata[3]}'
                '<extra></extra>'
            ),
            name='',
        ))
        fig.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
        lay = chart_layout(title, height=300, margin_t=36)
        lay['xaxis']['type']        = 'date'
        lay['xaxis']['tickformat']  = x_fmt
        lay['yaxis']['tickprefix']  = '$'
        lay['yaxis']['tickformat']  = ',.0f'
        lay['xaxis']['rangeslider'] = {'visible': False}
        fig.update_layout(**lay)
        return fig

    html_wk = _fig_html(_cfig(_cagg('Week'),  'Weekly P/L'  + _win_suffix, '%d %b'))
    html_mo = _fig_html(_cfig(_cagg('Month'), 'Monthly P/L' + _win_suffix, '%b %Y'))

    # ── Assemble ──────────────────────────────────────────────────────────────
    bg  = C['card_bg'];  bdr = C['border']; txt = C['text']
    mut = C['text_muted']
    generated = _dt.now(_tz.utc).strftime('%Y-%m-%d %H:%M UTC')

    sec_style = (
        'background:#1a2233;border:1px solid ' + bdr + ';border-radius:10px;'
        'padding:20px 24px;margin-bottom:24px;'
    )

    def _metric_card(k, v):
        return (
            '<div style="background:#111827;border:1px solid ' + bdr + ';border-radius:8px;'
            'padding:14px 18px;min-width:130px;">'
            '<div style="color:' + mut + ';font-size:0.7rem;text-transform:uppercase;'
            'letter-spacing:0.05em;margin-bottom:4px;">' + k + '</div>'
            '<div style="font-family:monospace;font-size:1.1rem;color:' + txt + ';font-weight:600;">' + v + '</div>'
            '</div>'
        )
    portfolio_cards_html = ''.join(_metric_card(k, v) for k, v in portfolio_metrics.items())
    options_cards_html   = ''.join(_metric_card(k, v) for k, v in options_metrics.items()) if options_metrics else ''

    ticker_table_html = (
        '<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">'
        '<thead><tr style="color:' + mut + ';font-size:0.7rem;text-transform:uppercase;'
        'letter-spacing:0.05em;border-bottom:1px solid ' + bdr + ';">'
        '<th style="text-align:left;padding:6px 10px;">Ticker</th>'
        '<th style="text-align:right;padding:6px 10px;">Trades</th>'
        '<th style="text-align:right;padding:6px 10px;">Win %</th>'
        '<th style="text-align:right;padding:6px 10px;">P/L</th>'
        '<th style="text-align:right;padding:6px 10px;">Med Days</th>'
        '<th style="text-align:right;padding:6px 10px;">Capture %</th>'
        '<th style="text-align:right;padding:6px 10px;">Net Prem</th>'
        '</tr></thead>'
        '<tbody style="color:' + txt + ';">' + ticker_rows + '</tbody>'
        '</table>'
    ) if has_data else '<p style="color:' + mut + '">No data.</p>'

    _options_section = (
        '<div class="section"><h2>\U0001f3af Options Trading \u2014 Credit Trades Only</h2>'
        '<p style="color:' + mut + ';font-size:0.75rem;margin-bottom:12px;">'
        'Win Rate, Capture %, and other metrics apply to credit trades only '
        '(Short Puts, Covered Calls, Strangles, Iron Condors etc.).</p>'
        '<div class="metrics">' + options_cards_html + '</div></div>\n'
    ) if options_cards_html else ''

    _css = (
        '* { box-sizing:border-box; margin:0; padding:0; }\n'
        'body { background:#0a0e17; color:' + txt + '; font-family:"IBM Plex Sans",system-ui,sans-serif; font-size:14px; line-height:1.6; padding:32px 24px; }\n'
        'h1 { font-size:1.5rem; font-weight:700; color:' + txt + '; margin-bottom:4px; }\n'
        'h2 { font-size:1.05rem; font-weight:600; color:' + txt + '; margin-bottom:14px; padding-bottom:8px; border-bottom:1px solid ' + bdr + '; }\n'
        '.meta { color:' + mut + '; font-size:0.8rem; margin-bottom:32px; }\n'
        '.section { ' + sec_style + ' }\n'
        '.metrics { display:flex; flex-wrap:wrap; gap:12px; }\n'
        'td { padding:6px 10px; text-align:right; border-bottom:1px solid ' + bdr + '22; }\n'
        'td:first-child { text-align:left; }\n'
        'tr:last-child td { border-bottom:none; }\n'
        '.charts-row { display:grid; grid-template-columns:1fr 1fr; gap:16px; }\n'
        '@media(max-width:700px) { .charts-row { grid-template-columns:1fr; } }\n'
        '.footer { color:' + mut + '; font-size:0.75rem; text-align:center; margin-top:32px; padding-top:16px; border-top:1px solid ' + bdr + '; }\n'
    )

    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '<title>TastyMechanics Report \u00b7 ' + window_label + '</title>\n'
        '<style>\n' + _css + '</style>\n</head>\n<body>\n'
        '<h1>\U0001f4ca TastyMechanics Report</h1>\n'
        '<div class="meta">Period: <strong style="color:' + txt + '">'
        + _win_start_str + ' \u2192 ' + _win_end_str + '</strong>'
        + ' &nbsp;\u00b7&nbsp; Generated: ' + generated + '</div>\n'
        + '<div class="section"><h2>\U0001f4ca Portfolio Overview</h2>'
        '<p style="color:' + mut + ';font-size:0.75rem;margin-bottom:12px;">'
        'Total P/L includes trading gains, dividends, and interest. '
        'Trading P/L is options and equity closes only.</p>'
        '<div class="metrics">' + portfolio_cards_html + '</div></div>\n'
        + _options_section
        + '<div class="section"><h2>\U0001f4c8 Cumulative P/L</h2>' + html_eq + '</div>\n'
        + '<div class="section"><h2>\U0001f56f Weekly &amp; Monthly P/L Candles</h2>'
        '<div class="charts-row"><div>' + html_wk + '</div><div>' + html_mo + '</div></div>'
        '<p style="color:' + mut + ';font-size:0.75rem;margin-top:10px;">'
        'Candles show cumulative P/L open/high/low/close per period. '
        'Green = closed higher than opened. Wicks show intra-period extremes.</p></div>\n'
        + '<div class="section"><h2>\U0001f3f7 Performance by Ticker</h2>' + ticker_table_html + '</div>\n'
        + '<div class="footer">TastyMechanics \u00b7 ' + generated + '</div>\n'
        + '</body>\n</html>'
    )

