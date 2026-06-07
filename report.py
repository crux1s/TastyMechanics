"""
report.py — HTML report export for TastyMechanics.

Generates a self-contained dark fintech-themed HTML report containing:
  - Portfolio Overview scorecard (total P/L, capital deployed, dividends, interest)
  - Premium Selling Scorecard — two rows (trade quality + risk/fees)
  - Capture % Distribution bar chart
  - Short Calls vs Short Puts breakdown (own card) + Strategy breakdown (own card)
  - Cumulative P/L equity curve with drawdown fill
  - Weekly bar chart + Monthly candlestick (side-by-side)
  - Closed Wheel Campaigns table
  - Performance by Ticker — full expanded table

No Streamlit dependency — importable and testable standalone.
"""

import pandas as pd
import plotly.graph_objects as go

from config import COLOURS, WIN_RATE_GREEN, WIN_RATE_ORANGE, LEAPS_DTE_THRESHOLD
from mechanics import realized_pnl
from ui_components import fmt_dollar, chart_layout, xe


# ══════════════════════════════════════════════════════════════════════════════
# Fintech dark theme — local palette (independent of Streamlit COLOURS)
# ══════════════════════════════════════════════════════════════════════════════
_T = {
    'bg':       '#111827',   # page background
    'card':     '#1F2937',   # card / surface
    'card2':    '#253040',   # elevated card / metric inner
    'deep':     '#0D1117',   # inset / input backgrounds
    'text':     '#F9F7F4',   # primary text (warm off-white)
    'text2':    '#D1D5DB',   # secondary text
    'muted':    '#6B7280',   # tertiary / label text
    'subtle':   '#9CA3AF',   # placeholders / faint values
    'border':   '#374151',   # default border
    'border_h': '#4B5563',   # hover / elevated border
    'teal':     '#097F70',   # brand accent — CTAs, active states, positive badges
    'teal_l':   '#0DA898',   # lighter teal — accent hover, links
    'green':    '#22c55e',   # profit / positive
    'red':      '#ef4444',   # loss / danger
    'warn':     '#eab308',   # caution / warning
    'alert':    '#f97316',   # urgent / alert
}


# ══════════════════════════════════════════════════════════════════════════════
# HTML REPORT EXPORT
# ══════════════════════════════════════════════════════════════════════════════

def build_html_report(
    all_cdf, credit_cdf, has_credit, has_data,
    df_window, start_date, latest_date,
    window_label, _win_suffix, _win_start_str, _win_end_str,
    window_realized_pnl=0.0, total_realized_pnl=0.0,
    div_income=0.0, int_net=0.0, total_fees=0.0,
    net_deposited=0.0, selected_period='All Time',
    daily_pnl_all=None,
    all_campaigns=None,
    capital_deployed=0.0,
    closed_camp_pnl=0.0,
    # v26.14 additions — reconciliation, version stamp, benchmark overlay
    open_premiums_banked=0.0,    # open campaign premiums (component of total_realized_pnl)
    pure_opts_pnl=0.0,           # options P/L outside any wheel campaign
    app_version='',              # e.g. 'v26.14' — appears in footer for reproducibility
    csv_fingerprint='',          # first 6 chars of file md5 — appears in footer
    benchmark_annual_pct=10.0,   # constant-growth benchmark line on equity chart (S&P proxy)
):
    """Build a self-contained dark fintech-themed HTML report string."""
    from datetime import datetime as _dt, timezone as _tz

    T = _T   # local alias

    # ── Computed metrics ───────────────────────────────────────────────────────
    _is_all_time = selected_period == 'All Time'
    _pnl_display = total_realized_pnl if _is_all_time else window_realized_pnl
    _trading_pnl = all_cdf['Net P/L'].sum() if has_data else 0.0
    window_days  = max((latest_date - start_date).days, 1)
    generated    = _dt.now(_tz.utc).strftime('%Y-%m-%d %H:%M UTC')

    # ── Helpers ────────────────────────────────────────────────────────────────
    plotly_included = [False]

    def _fig_html(fig):
        inc = 'cdn' if not plotly_included[0] else False
        plotly_included[0] = True
        # Match chart paper/plot background to card colour
        fig.update_layout(
            paper_bgcolor=T['card'],
            plot_bgcolor=T['card'],
        )
        return fig.to_html(full_html=False, include_plotlyjs=inc,
                           config={'displayModeBar': False})

    def _wr_color(rate):
        if rate >= WIN_RATE_GREEN:  return T['green']
        if rate >= WIN_RATE_ORANGE: return T['warn']
        return T['red']

    def _pnl_color(v):
        return T['green'] if v >= 0 else T['red']

    def _th(label, align='right'):
        return (
            '<th style="text-align:%s;padding:7px 12px;color:%s;'
            'font-size:0.68rem;text-transform:uppercase;letter-spacing:0.08em;'
            'font-weight:700;border-bottom:1px solid %s;white-space:nowrap;">'
            '%s</th>' % (align, T['muted'], T['border'], label)
        )

    def _td(val, align='right', color='', mono=False):
        fam  = 'font-family:Consolas,Menlo,monospace;' if mono else ''
        col  = 'color:%s;' % color if color else ''
        return (
            '<td style="text-align:%s;padding:6px 12px;border-bottom:'
            '1px solid %s;%s%s">%s</td>'
            % (align, T['bg'], col, fam, val)
        )

    def _tbl(headers, rows, caption=''):
        head = '<tr>' + ''.join(_th(h, 'left' if i == 0 else 'right')
                                for i, h in enumerate(headers)) + '</tr>'
        cap  = ('<caption style="color:%s;font-size:0.7rem;text-align:left;'
                'padding-bottom:8px;">%s</caption>' % (T['muted'], caption)) if caption else ''
        return (
            '<table style="width:100%;border-collapse:collapse;font-size:0.83rem;">'
            + cap
            + '<thead>' + head + '</thead>'
            + '<tbody style="color:%s;">' % T['text2']
            + ''.join(rows)
            + '</tbody></table>'
        )

    def _tr(cells, alt=False):
        bg = 'background:rgba(255,255,255,0.025);' if alt else ''
        return '<tr style="%s">' % bg + ''.join(cells) + '</tr>'

    # ── Section 1: Portfolio Overview ──────────────────────────────────────────
    pnl_col = _pnl_color(_pnl_display)
    port_cards = [
        ('Total P/L',          fmt_dollar(_pnl_display),   pnl_col),
        ('Trading P/L',        fmt_dollar(_trading_pnl),   _pnl_color(_trading_pnl)),
        ('Closed Wheel P/L',   fmt_dollar(closed_camp_pnl),_pnl_color(closed_camp_pnl)),
        ('Capital Deployed',   fmt_dollar(capital_deployed), T['text']),
        ('Dividends',          fmt_dollar(div_income),      T['green'] if div_income >= 0 else T['red']),
        ('Interest (net)',     fmt_dollar(int_net),          _pnl_color(int_net)),
        ('Total Fees',         fmt_dollar(total_fees),       T['red'] if total_fees > 0 else T['text']),
        ('Deposited',          fmt_dollar(net_deposited),    T['text']),
        ('Total Trades',       str(len(all_cdf)) if has_data else '0', T['text']),
    ]

    # ── Section 2: Premium Selling Scorecard ───────────────────────────────────
    scorecard_a = []
    scorecard_b = []
    tastytrade_note = ''

    if has_credit:
        total_credit_rcvd    = credit_cdf['Net Premium'].sum()
        total_net_pnl_closed = credit_cdf['Net P/L'].sum()
        _net_keep_pct = (total_net_pnl_closed / total_credit_rcvd * 100
                         if total_credit_rcvd != 0 else 0.0)
        _wr       = credit_cdf['Won'].mean() * 100
        _winners  = all_cdf[all_cdf['Net P/L'] > 0]['Net P/L']
        _losers   = all_cdf[all_cdf['Net P/L'] < 0]['Net P/L']
        _avg_win  = _winners.mean() if not _winners.empty else 0.0
        _avg_loss = _losers.mean()  if not _losers.empty  else 0.0
        _ratio         = abs(_avg_win / _avg_loss) if _avg_loss != 0 else None
        _gross_profit  = credit_cdf[credit_cdf['Net P/L'] > 0]['Net P/L'].sum()
        _gross_loss    = abs(credit_cdf[credit_cdf['Net P/L'] <= 0]['Net P/L'].sum())
        _profit_factor = _gross_profit / _gross_loss if _gross_loss > 0 else float('inf')
        _fees_pct      = (total_fees / abs(total_net_pnl_closed) * 100
                          if total_net_pnl_closed != 0 else 0.0)
        _n_trades      = max(len(all_cdf), 1)
        _med_daily_theta = (
            credit_cdf['Daily θ %'].median()
            if 'Daily θ %' in credit_cdf.columns and not credit_cdf.empty
            else None
        )

        scorecard_a = [
            ('Win Rate',           '%.1f%%' % _wr,                              _wr_color(_wr)),
            ('Median Capture %',   '%.1f%%' % credit_cdf['Capture %'].median(), T['text2']),
            ('Net Prem Kept %',    '%.1f%%' % _net_keep_pct,                    _pnl_color(_net_keep_pct)),
            ('Med Days in Trade',  '%.0fd'  % credit_cdf['Days Held'].median(), T['text2']),
            ('Med Prem/Day',       fmt_dollar(credit_cdf['Prem/Day'].median()),  T['text2']),
            ('Kept $/Day',         fmt_dollar(total_net_pnl_closed / window_days), _pnl_color(total_net_pnl_closed)),
            ('Med Daily θ %',
             '%.2f%%' % _med_daily_theta if _med_daily_theta is not None else '—', T['text2']),
        ]
        scorecard_b = [
            ('Avg Winner',     fmt_dollar(_avg_win),                               T['green']),
            ('Avg Loser',      fmt_dollar(_avg_loss),                              T['red']),
            ('Win/Loss Ratio', '%.2f×' % _ratio if _ratio is not None else '∞',   T['text2']),
            ('Total Fees',     fmt_dollar(total_fees),                             T['red'] if total_fees > 0 else T['text2']),
            ('Fees % of P/L',  '%.1f%%' % _fees_pct,                              T['text2']),
            ('Fees/Trade',     fmt_dollar(total_fees / _n_trades),                T['text2']),
            ('Profit Factor',  '%.2f' % _profit_factor if _profit_factor != float('inf') else '∞', T['text2']),
        ]
        tastytrade_note = (
            'TastyTrade targets: '
            '<strong style="color:%s">50%% capture at close</strong>'
            ' &nbsp;·&nbsp; '
            '<strong style="color:%s">25%% net premium kept</strong>'
            % (T['teal_l'], T['teal_l'])
        )

    # ── Account Health strip ───────────────────────────────────────────────────
    # 4 auto-derived traffic-light indicators that sit right under the report
    # header.  Lets the reader form a verdict in 5 seconds rather than reading
    # 20+ metric tiles.  Thresholds are calibrated for theta/wheel strategies:
    #   Win Rate: TastyTrade targets ≥70% on short premium
    #   Capture %: TastyTrade targets 50% management (close at half premium)
    #   Net Premium Kept: TastyTrade targets ~25% portfolio-level
    #   W/L Ratio: ≥0.5 healthy, <0.25 means one large loser undoes many wins
    health_cards = []
    if has_credit:
        _wr_v   = credit_cdf['Won'].mean() * 100
        _cap_v  = credit_cdf['Capture %'].median()
        _kept_v = _net_keep_pct
        _ratio_v = _ratio if _ratio is not None else 99.0  # ∞ → treated as healthy

        def _health_tile(label, value_str, status, note):
            colour = {'good': T['green'], 'warn': T['warn'], 'bad': T['red']}[status]
            icon   = {'good': '✅', 'warn': '⚠️', 'bad': '❌'}[status]
            return (label, '%s %s' % (icon, value_str), colour, note)

        # 1. Win Rate
        if   _wr_v >= 70: _wr_status, _wr_note  = 'good', 'above 70% target'
        elif _wr_v >= 50: _wr_status, _wr_note  = 'warn', 'below 70% target'
        else:             _wr_status, _wr_note  = 'bad',  'below 50% — review entries'

        # 2. Median Capture %
        if   _cap_v >= 45: _cap_status, _cap_note = 'good', 'near 50% TT target'
        elif _cap_v >= 25: _cap_status, _cap_note = 'warn', 'below 50% TT target'
        else:              _cap_status, _cap_note = 'bad',  'far below 50% target'

        # 3. Net Premium Kept %
        if   _kept_v >= 25: _kept_status, _kept_note = 'good', 'above 25% TT target'
        elif _kept_v >= 10: _kept_status, _kept_note = 'warn', 'below 25% TT target'
        else:               _kept_status, _kept_note = 'bad',  'below 10% — losses eroding income'

        # 4. Win/Loss Ratio — flag when one large loser eats many small wins
        if   _ratio_v >= 0.50: _rat_status, _rat_note = 'good', 'wins keep up with losers'
        elif _ratio_v >= 0.25: _rat_status, _rat_note = 'warn', 'avg loser 2-4× avg winner'
        else:                  _rat_status, _rat_note = 'bad',  'avg loser >4× avg winner'

        health_cards = [
            _health_tile('Win Rate',         '%.1f%%' % _wr_v,    _wr_status,   _wr_note),
            _health_tile('Median Capture %', '%.1f%%' % _cap_v,   _cap_status,  _cap_note),
            _health_tile('Net Premium Kept', '%.1f%%' % _kept_v,  _kept_status, _kept_note),
            _health_tile('Win/Loss Ratio',   '%.2f×' % _ratio_v   if _ratio is not None else '∞',
                                                                   _rat_status,  _rat_note),
        ]

    # ── Section 3: Capture % Distribution chart ────────────────────────────────
    html_cap = ''
    if has_credit:
        bins      = [-999, 0, 25, 50, 75, 100, 999]
        labels    = ['Loss', '0–25%', '25–50%', '50–75%', '75–100%', '>100%']
        bkt_colors = [T['red'], T['alert'], T['warn'], T['teal_l'], T['green'], T['teal']]
        credit_cdf = credit_cdf.copy()
        credit_cdf['Bucket'] = pd.cut(credit_cdf['Capture %'], bins=bins, labels=labels)
        bkt_df = credit_cdf.groupby('Bucket', observed=False).agg(
            Trades=('Net P/L', 'count')).reset_index()
        fig_cap = go.Figure()
        fig_cap.add_trace(go.Bar(
            x=bkt_df['Bucket'].astype(str),
            y=bkt_df['Trades'],
            marker_color=bkt_colors,
            marker_line_width=0,
            text=bkt_df['Trades'],
            textposition='outside',
            textfont=dict(size=11, color=T['subtle'], family='Consolas,Menlo,monospace'),
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
            dot = '🔵 ' if r['risk'] == True else ('🟠 ' if r['risk'] == False else '')  # noqa: E712
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

    # ── Section 5: Equity curve ────────────────────────────────────────────────
    html_eq = ''
    _eq_src = daily_pnl_all if (daily_pnl_all is not None and not daily_pnl_all.empty) else None
    if _eq_src is not None:
        cum_df = _eq_src.sort_values('Date').copy()
        cum_df['Cum']  = cum_df['PnL'].cumsum()
        cum_df['Peak'] = cum_df['Cum'].cummax()
        final_pnl = cum_df['Cum'].iloc[-1]
        eq_color = T['green'] if final_pnl >= 0 else T['red']
        eq_fill  = 'rgba(34,197,94,0.10)' if final_pnl >= 0 else 'rgba(239,68,68,0.10)'
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x=pd.concat([cum_df['Date'], cum_df['Date'][::-1]]),
            y=pd.concat([cum_df['Peak'], cum_df['Cum'][::-1]]),
            fill='toself', fillcolor='rgba(239,68,68,0.10)',
            line=dict(color='rgba(0,0,0,0)'), showlegend=False,
            hoverinfo='skip', name='Drawdown',
        ))
        fig_eq.add_trace(go.Scatter(
            x=cum_df['Date'], y=cum_df['Cum'],
            mode='lines', line=dict(color=eq_color, width=2),
            fill='tozeroy', fillcolor=eq_fill,
            hovertemplate='%{x|%d %b %y}<br><b>%{y:$,.2f}</b><extra></extra>',
            name='Cumulative P/L',
        ))
        # Benchmark overlay — constant-growth line representing what the same
        # net-deposited capital would have produced at `benchmark_annual_pct` per
        # year (default 10% — long-run S&P proxy).  Deterministic, no network
        # required.  Drawn faint and dotted so it doesn't compete visually with
        # the realised curve.
        if benchmark_annual_pct and net_deposited > 0:
            _days   = (cum_df['Date'] - cum_df['Date'].iloc[0]).dt.days.clip(lower=0)
            _daily  = benchmark_annual_pct / 100.0 / 365.0
            _bench  = net_deposited * ((1 + _daily) ** _days - 1)
            fig_eq.add_trace(go.Scatter(
                x=cum_df['Date'], y=_bench,
                mode='lines',
                line=dict(color=T['text2'], width=1.2, dash='dot'),
                opacity=0.55,
                hovertemplate='%{x|%d %b %y}<br>'
                              + '<b>%{y:$,.0f}</b> (S&amp;P proxy, '
                              + '%.0f%%/yr)' % benchmark_annual_pct
                              + '<extra></extra>',
                name='%.0f%%/yr on net deposited' % benchmark_annual_pct,
            ))
        fig_eq.add_annotation(
            x=cum_df['Date'].iloc[-1], y=final_pnl,
            text='<b>' + fmt_dollar(final_pnl) + '</b>',
            showarrow=True, arrowhead=2, arrowcolor=eq_color,
            font=dict(color=eq_color, size=12, family='Consolas,Menlo,monospace'),
            bgcolor='rgba(13,17,23,0.9)', bordercolor=T['border'], borderwidth=1,
            xanchor='right', yanchor='bottom',
        )
        fig_eq.add_hline(y=0, line_color='rgba(255,255,255,0.10)', line_width=1)
        _eq_lay = chart_layout(
            'Portfolio Equity Curve — Cumulative Realized P/L', height=340, margin_t=40)
        _eq_lay['yaxis']['tickprefix'] = '$'
        _eq_lay['yaxis']['tickformat'] = ',.0f'
        # Show legend only when the benchmark line is drawn — otherwise the
        # single-trace chart doesn't need one.
        _eq_lay['showlegend'] = bool(benchmark_annual_pct and net_deposited > 0)
        if _eq_lay['showlegend']:
            _eq_lay['legend'] = dict(
                orientation='h', yanchor='bottom', y=1.02,
                xanchor='right', x=1, bgcolor='rgba(0,0,0,0)',
                font=dict(size=10, color=T['text2']),
            )
        fig_eq.update_layout(**_eq_lay)
        html_eq = _fig_html(fig_eq)

    # ── Section 6: Weekly + Monthly charts ────────────────────────────────────
    html_wk = ''
    html_mo = ''
    if has_data:
        _pdf = all_cdf.copy()
        _pdf['CloseDate'] = pd.to_datetime(_pdf['Close Date'])
        _pdf = _pdf.sort_values('CloseDate')
        _pdf['Week']  = _pdf['CloseDate'].dt.to_period('W').apply(lambda p: p.start_time)
        _pdf['Month'] = _pdf['CloseDate'].dt.to_period('M').apply(lambda p: p.start_time)
        _pdf['CumPL'] = _pdf['Net P/L'].cumsum()

        wk_df = _pdf.groupby('Week', sort=True).agg(
            Net=('Net P/L', 'sum'),
            Trades=('Net P/L', 'count'),
        ).reset_index()
        wk_colors = [T['green'] if v >= 0 else T['red'] for v in wk_df['Net']]
        fig_wk = go.Figure()
        fig_wk.add_trace(go.Bar(
            x=wk_df['Week'], y=wk_df['Net'],
            marker_color=wk_colors, marker_line_width=0,
            customdata=list(zip([fmt_dollar(r) for r in wk_df['Net']], wk_df['Trades'])),
            hovertemplate='<b>w/c %{x|%d %b}</b><br>P/L: <b>%{customdata[0]}</b><br>Trades: %{customdata[1]}<extra></extra>',
        ))
        fig_wk.add_hline(y=0, line_color='rgba(255,255,255,0.10)', line_width=1)
        _wk_lay = chart_layout('Weekly P/L' + _win_suffix, height=290, margin_t=36)
        _wk_lay['yaxis']['tickprefix'] = '$'
        _wk_lay['yaxis']['tickformat'] = ',.0f'
        _wk_lay['showlegend'] = False
        fig_wk.update_layout(**_wk_lay)
        html_wk = _fig_html(fig_wk)

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
            increasing=dict(line=dict(color=T['green'], width=1), fillcolor='rgba(34,197,94,0.45)'),
            decreasing=dict(line=dict(color=T['red'],   width=1), fillcolor='rgba(239,68,68,0.45)'),
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
        fig_mo.add_hline(y=0, line_color='rgba(255,255,255,0.10)', line_width=1)
        _mo_lay = chart_layout('Monthly P/L (Cumulative Candles)' + _win_suffix, height=290, margin_t=36)
        _mo_lay['xaxis']['type']        = 'date'
        _mo_lay['xaxis']['tickformat']  = '%b %Y'
        _mo_lay['yaxis']['tickprefix']  = '$'
        _mo_lay['yaxis']['tickformat']  = ',.0f'
        _mo_lay['xaxis']['rangeslider'] = {'visible': False}
        fig_mo.update_layout(**_mo_lay)
        html_mo = _fig_html(fig_mo)

    # ── Section 7: Closed Wheel Campaigns ─────────────────────────────────────
    closed_rows = []
    if all_campaigns:
        for ticker, camps in sorted(all_campaigns.items()):
            for c in camps:
                if c.status != 'closed':
                    continue
                rpnl = realized_pnl(c)
                days = (c.end_date - c.start_date).days if c.end_date else None
                days_s = '%dd' % days if days is not None else '—'
                closed_rows.append(_tr([
                    _td('<strong style="font-family:Consolas,Menlo,monospace;color:%s;">%s</strong>'
                        % (T['text'], xe(ticker)), 'left'),
                    _td(fmt_dollar(c.total_cost),       mono=True),
                    _td(fmt_dollar(c.exit_proceeds),    mono=True),
                    _td(fmt_dollar(c.premiums),         mono=True),
                    _td(fmt_dollar(rpnl), color=_pnl_color(rpnl), mono=True),
                    _td(days_s),
                    _td(c.start_date.strftime('%d %b %Y') if c.start_date else '—', 'left'),
                    _td(c.end_date.strftime('%d %b %Y')   if c.end_date   else '—', 'left'),
                ], alt=bool(len(closed_rows) % 2)))

    # ── Section 8: Performance by Ticker ──────────────────────────────────────
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
                Total_Prem=('Net Premium', 'sum'),
            ).round(1)
            tdf = all_by_ticker.join(credit_by_ticker, how='left').reset_index()
        else:
            tdf = all_by_ticker.reset_index()
            tdf['Med_Capture'] = None
            tdf['Total_Prem']  = None
        tdf = tdf.sort_values('Total_PNL', ascending=False)

        for i, row in enumerate(tdf.itertuples(index=False)):
            cap_str  = '%.1f%%' % row.Med_Capture if pd.notna(row.Med_Capture) else '—'
            prem_str = fmt_dollar(row.Total_Prem)   if pd.notna(row.Total_Prem)  else '—'
            dit_str  = '$%.2f'  % row.PnL_per_DTE  if pd.notna(row.PnL_per_DTE) else '—'
            dim = 'opacity:0.4;font-style:italic;' if (int(row.Wins) + int(row.Losses)) < 3 else ''
            ticker_rows.append(
                '<tr style="background:%s;%s">' % (
                    'rgba(255,255,255,0.025)' if i % 2 else '', dim)
                + _td('<strong style="font-family:Consolas,Menlo,monospace;color:%s;">%s</strong>'
                      % (T['text'], xe(str(row.Ticker))), 'left')
                + _td(str(row.WL))
                + _td('%.1f%%' % row.Win_Rate, color=_wr_color(row.Win_Rate))
                + _td(fmt_dollar(row.Total_PNL), color=_pnl_color(row.Total_PNL), mono=True)
                + _td('%.0fd' % row.Avg_Days)
                + _td(dit_str, mono=True)
                + _td(cap_str)
                + _td(prem_str, mono=True)
                + '</tr>'
            )

    # ══════════════════════════════════════════════════════════════════════════
    # CSS — fintech dark theme
    # ══════════════════════════════════════════════════════════════════════════
    _css = (
        "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');\n"
        '* { box-sizing: border-box; margin: 0; padding: 0; }\n'
        'body { background: %(bg)s; color: %(text)s; '
        'font-family: Inter, Gilroy, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; '
        'font-size: 14px; line-height: 1.6; padding: 32px 24px 56px; }\n'
        '.wrap { max-width: 1200px; margin: 0 auto; }\n'

        # ── Header ──
        '.report-header { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }\n'
        '.brand-mark { width: 10px; height: 10px; background: %(teal)s; border-radius: 2px; '
        'flex-shrink: 0; }\n'
        '.report-title { font-size: 1.45rem; font-weight: 800; color: %(text)s; '
        'letter-spacing: -0.01em; }\n'
        '.report-badge { background: %(card2)s; color: %(muted)s; border: 1px solid %(border)s; '
        'font-size: 0.68rem; font-weight: 700; text-transform: uppercase; '
        'letter-spacing: 0.08em; padding: 3px 10px; border-radius: 9999px; }\n'
        '.report-meta { color: %(muted)s; font-size: 0.78rem; margin-bottom: 32px; '
        'padding-left: 22px; }\n'
        '.report-meta strong { color: %(text2)s; font-weight: 600; }\n'

        # ── Cards / sections ──
        '.section { background: %(card)s; border: 1px solid %(border)s; '
        'border-radius: 10px; padding: 22px 24px; margin-bottom: 20px; '
        'box-shadow: 0 2px 8px rgba(0,0,0,0.45); }\n'
        '.section-label { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.10em; '
        'text-transform: uppercase; color: %(muted)s; margin-bottom: 4px; }\n'
        '.section-title { font-size: 1.0rem; font-weight: 700; color: %(text)s; '
        'margin-bottom: 16px; padding-bottom: 10px; border-bottom: 1px solid %(border)s; '
        'letter-spacing: -0.005em; }\n'
        '.section-note { color: %(muted)s; font-size: 0.75rem; margin-bottom: 12px; '
        'line-height: 1.5; }\n'

        # ── Metric grid ──
        '.metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); '
        'gap: 10px; margin-bottom: 14px; }\n'
        '.metric-card { background: %(card2)s; border: 1px solid %(border)s; '
        'border-radius: 8px; padding: 14px 16px; }\n'
        '.metric-label { font-size: 0.67rem; text-transform: uppercase; letter-spacing: 0.08em; '
        'color: %(muted)s; margin-bottom: 6px; font-weight: 700; }\n'
        '.metric-value { font-family: Consolas, Menlo, monospace; font-size: 1.1rem; '
        'font-weight: 700; font-variant-numeric: tabular-nums; }\n'
        '.metric-row-label { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.10em; '
        'color: %(muted)s; font-weight: 700; '
        'margin: 16px 0 8px; padding-top: 14px; border-top: 1px solid %(border)s; }\n'

        # ── Layout helpers ──
        '.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }\n'
        '.charts-row { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }\n'
        '@media(max-width:820px) { .two-col, .charts-row { grid-template-columns: 1fr; } }\n'
        '.tbl-wrap { overflow-x: auto; }\n'

        # ── Health strip — 4 traffic-light verdicts right under the header ──
        '.health-grid { display: grid; grid-template-columns: repeat(4, 1fr); '
        'gap: 12px; margin: 18px 0 24px 0; }\n'
        '@media(max-width:820px) { .health-grid { grid-template-columns: 1fr 1fr; } }\n'
        '.health-card { background: %(card)s; border: 1px solid %(border)s; '
        'border-radius: 8px; padding: 14px 16px; border-left-width: 3px; }\n'
        '.health-label { font-size: 0.66rem; text-transform: uppercase; '
        'letter-spacing: 0.08em; color: %(muted)s; font-weight: 700; }\n'
        '.health-value { font-size: 1.25rem; font-weight: 700; margin: 4px 0 2px; '
        'font-variant-numeric: tabular-nums; }\n'
        '.health-note { font-size: 0.75rem; color: %(muted)s; line-height: 1.3; }\n'

        # ── Reconciliation strip — additive breakdown above the footer ──
        '.recon-strip { background: %(card)s; border: 1px solid %(border)s; '
        'border-radius: 8px; padding: 12px 16px; margin: 24px 0 10px 0; '
        'font-size: 0.78rem; color: %(muted)s; line-height: 1.5; }\n'
        '.recon-strip .recon-tag { color: %(text)s; font-family: Consolas,Menlo,monospace; '
        'font-weight: 600; }\n'
        '.recon-strip .recon-eq { color: %(teal_l)s; font-weight: 700; }\n'

        # ── Tables ──
        'table { width: 100%%; border-collapse: collapse; font-size: 0.83rem; }\n'
        'tr:hover td { background: rgba(9,127,112,0.07) !important; }\n'

        # ── Footer ──
        '.footer { color: %(muted)s; font-size: 0.70rem; '
        'text-align: center; margin-top: 36px; padding-top: 14px; '
        'border-top: 1px solid %(border)s; letter-spacing: 0.04em; }\n'

        # ── Print ──
        '@media print { body { background: #fff; color: #111; padding: 16px; } '
        '.section { background: #f8f8f8; border-color: #ccc; box-shadow: none; } '
        '.metric-card { background: #f0f0f0; border-color: #ccc; } '
        '.metric-label { color: #555; } }\n'
    ) % T

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
        col_s = 'color:%s;' % (color or T['text'])
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

    # Health strip — 4 traffic-light cards, sits directly under the report header.
    # Each card carries a colored left-border in the indicator's status colour so
    # the verdict is scannable at distance.
    if health_cards:
        _health_html = '<div class="health-grid">' + ''.join(
            '<div class="health-card" style="border-left-color:%s;">'
            '<div class="health-label">%s</div>'
            '<div class="health-value" style="color:%s;">%s</div>'
            '<div class="health-note">%s</div>'
            '</div>' % (col, label, col, val, note)
            for label, val, col, note in health_cards
        ) + '</div>\n'
    else:
        _health_html = ''

    # DTE Discipline mini-section — ThetaGang management metrics that exist in
    # Tab 2 but were never carried into the report.  Replicates the same maths
    # from tab2_trade_analysis.py using closed_trades_df columns only (no need
    # for the raw df_window option ledger).  LEAPS (DTE_open > LEAPS_DTE_THRESHOLD)
    # are excluded — they distort the median and don't fit the 30–45 DTE playbook.
    s_discipline = ''
    if has_credit and 'DTE at Open' in credit_cdf.columns:
        _disc_cdf = credit_cdf[credit_cdf['DTE at Open'] <= LEAPS_DTE_THRESHOLD]
        if not _disc_cdf.empty:
            _med_dte_open = _disc_cdf['DTE at Open'].median()
            _disc_valid   = (_disc_cdf.dropna(subset=['DTE at Close'])
                             if 'DTE at Close' in _disc_cdf.columns else pd.DataFrame())
            _med_dte_close = _disc_valid['DTE at Close'].median() if not _disc_valid.empty else 0.0
            _EARLY_DTE     = 21
            _n_early       = int((_disc_valid['DTE at Close'] >= _EARLY_DTE).sum()) if not _disc_valid.empty else 0
            _early_rate    = (_n_early / len(_disc_valid) * 100) if not _disc_valid.empty else 0.0
            _sp_cdf        = (_disc_cdf[_disc_cdf['Trade Type'].astype(str).str.startswith('Short Put')]
                              if 'Trade Type' in _disc_cdf.columns else pd.DataFrame())
            _n_assigned    = (int(_sp_cdf['Close Reason'].astype(str).str.contains('Assign', na=False).sum())
                              if not _sp_cdf.empty and 'Close Reason' in _sp_cdf.columns else 0)
            _n_sp_total    = len(_sp_cdf)
            _assign_rate   = (_n_assigned / _n_sp_total * 100) if _n_sp_total > 0 else 0.0

            discipline_cards = [
                ('Med DTE at Open',  '%.0fd' % _med_dte_open,  T['text2']),
                ('Med DTE at Close', '%.0fd' % _med_dte_close, T['text2']),
                ('Early Mgmt Rate',  '%.0f%%' % _early_rate,
                                     T['green'] if _early_rate >= 50 else T['warn']),
                ('Assignment Rate',
                 '%.0f%% (%d / %d)' % (_assign_rate, _n_assigned, _n_sp_total) if _n_sp_total else '—',
                 T['text2']),
            ]
            _disc_body = (
                '<div class="section-note">'
                'TastyTrade playbook: open ~30–45 DTE, close at ≥21 DTE to avoid gamma risk. '
                'LEAPS excluded. Assignment rate counts short puts only.</div>'
                + _cards_html(discipline_cards)
            )
            s_discipline = _section('Discipline', '📅 ThetaGang Discipline', _disc_body)

    # Reconciliation strip — additive breakdown showing what the Total P/L tile
    # is made of.  Sits above the footer to make the headline number debuggable
    # and build trust ("Total P/L $X = component A + component B + … ✓").
    # All components passed in from main(); we just sum and display.
    _recon_components = [
        ('Closed Wheel P/L',     closed_camp_pnl),
        ('Open Wheel Premiums',  open_premiums_banked),
        ('Pure Options P/L',     pure_opts_pnl),
        ('Dividends',            div_income),
        ('Interest (net)',       int_net),
    ]
    _recon_sum     = sum(v for _, v in _recon_components)
    _recon_ok      = abs(_recon_sum - total_realized_pnl) < 0.01
    _recon_tick    = ('<span class="recon-eq">✓</span>' if _recon_ok
                      else '<span style="color:%s">⚠ %s</span>' %
                           (T['red'], fmt_dollar(_recon_sum - total_realized_pnl)))
    _recon_parts = ' + '.join(
        '<span class="recon-tag">%s</span> %s' % (lbl, fmt_dollar(v))
        for lbl, v in _recon_components
    )
    _recon_html = (
        '<div class="recon-strip">'
        '<strong>Total Realized P/L Reconciliation:</strong> '
        '<span class="recon-tag">%s</span> &nbsp;=&nbsp; %s &nbsp;=&nbsp; %s %s'
        '</div>\n'
    ) % (fmt_dollar(total_realized_pnl), _recon_parts,
         fmt_dollar(_recon_sum), _recon_tick)

    # Section 1 — Portfolio Overview
    port_body = (
        '<div class="section-note">'
        'Total P/L includes trading gains, dividends, and interest. '
        'Capital Deployed = current cost basis of open wheel positions.</div>'
        + _cards_html(port_cards)
    )
    s_overview = _section('Portfolio', '📊 Overview', port_body)

    # Section 2 — Scorecard
    if scorecard_a:
        sc_body = (
            '<div class="section-note">Credit trades only (Short Puts, Covered Calls, '
            'Strangles, Iron Condors, etc.)</div>'
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
    s_capture = _section('Distribution', '📊 Premium Capture %', html_cap) if html_cap else ''

    # Section 4a — Call vs Put (own card)
    if cvp_rows:
        cvp_tbl = _tbl(
            ['Type', 'Trades', 'Win %', 'Capture %', 'P/L', 'Prem/Day', 'Med Days', 'DTE'],
            cvp_rows,
        )
        s_cvp = _section(
            'Breakdown', '🧩 Short Calls vs Short Puts',
            '<div class="tbl-wrap">%s</div>' % cvp_tbl,
        )
    else:
        s_cvp = ''

    # Section 4b — Strategy breakdown (own card)
    if strat_rows:
        strat_tbl = _tbl(
            ['Strategy', 'Trades', 'Win %', 'P/L', 'Capture %', 'Med Days', 'DTE'],
            strat_rows,
        )
        s_strategy = _section(
            'Breakdown', '🎯 Strategy Breakdown',
            '<div class="metric-row-label" style="margin-top:0;">'
            '🔵 Defined &nbsp;·&nbsp; 🟠 Undefined Risk</div>'
            '<div class="tbl-wrap">%s</div>'
            '<p class="section-note" style="margin-top:8px;">Dim = fewer than 5 trades.</p>'
            % strat_tbl,
        )
    else:
        s_strategy = ''

    # Section 5 — Equity Curve
    s_equity = _section('P/L', '📈 Cumulative Realized P/L', html_eq) if html_eq else ''

    # Section 6 — Weekly + Monthly charts
    if html_wk or html_mo:
        charts_body = (
            '<div class="charts-row"><div>%s</div><div>%s</div></div>'
            '<p class="section-note" style="margin-top:10px;">'
            'Monthly candles show cumulative P/L open/high/low/close. '
            'Green = closed higher than opened. Wicks = intra-month extremes.</p>'
        ) % (html_wk, html_mo)
        s_cashflow = _section('Cash Flow', '📅 Weekly &amp; Monthly P/L', charts_body)
    else:
        s_cashflow = ''

    # Section 7 — Closed Wheel Campaigns
    if closed_rows:
        closed_tbl = _tbl(
            ['Ticker', 'Cost', 'Exit Proceeds', 'Premiums', 'Realized P/L', 'Days', 'Entry', 'Exit'],
            closed_rows,
        )
        s_closed = _section(
            'Wheel',
            '🎡 Closed Wheel Campaigns',
            '<div class="section-note">Fully closed wheel cycles — '
            'shares assigned and subsequently sold. Realized P/L = exit proceeds + premiums − cost.</div>'
            '<div class="tbl-wrap">' + closed_tbl + '</div>',
        )
    else:
        s_closed = ''

    # Section 8 — Ticker table
    if ticker_rows:
        tbl_html = _tbl(
            ['Ticker', 'W/L', 'Win %', 'P/L', 'Avg Days', 'P/L/DIT', 'Capture %', 'Net Prem'],
            ticker_rows,
        )
        ticker_body = (
            '<div class="section-note">'
            'W/L = wins / losses. P/L/DIT = total P/L ÷ avg days in trade. '
            'Dim = fewer than 3 trades.</div>'
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
        '<title>TastyMechanics Report · %(wl)s</title>\n'
        '<style>%(css)s</style>\n</head>\n<body>\n'
        '<div class="wrap">\n'
        '<div class="report-header">'
        '<div class="brand-mark"></div>'
        '<span class="report-title">TastyMechanics</span>'
        '<span class="report-badge">%(period)s</span>'
        '</div>\n'
        '<div class="report-meta">'
        'Period: <strong>%(ws)s → %(we)s</strong>'
        '&nbsp;·&nbsp; Generated: %(gen)s'
        '</div>\n'
        % dict(wl=window_label, css=_css, period=selected_period,
               ws=_win_start_str, we=_win_end_str, gen=generated)
        + _health_html
        + s_overview
        + s_scorecard
        + s_discipline
        + s_capture
        + s_cvp
        + s_strategy
        + s_equity
        + s_cashflow
        + s_closed
        + s_tickers
        + _recon_html
        + '<div class="footer">TastyMechanics %(ver)s &nbsp;·&nbsp; %(gen)s'
          '%(fp)s</div>\n' % dict(
              gen=generated,
              ver=app_version if app_version else '',
              fp=(' &nbsp;·&nbsp; CSV %s' % csv_fingerprint) if csv_fingerprint else '',
          )
        + '</div>\n</body>\n</html>'
    )
