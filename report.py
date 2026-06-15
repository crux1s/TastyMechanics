"""
report.py — HTML report export for TastyMechanics.

Generates a self-contained, dependency-free HTML dashboard: tabbed layout
(Overview / Performance / Wheel & Discipline), hand-rolled inline-SVG equity
curve and OHLC candlesticks, animated bars, sortable tables, count-up hero
numbers, vanilla JS.  No CDN, no build step, no Streamlit dependency — opens
in any browser and prints cleanly.

Public entry point
------------------
  build_html_report(all_cdf, credit_cdf, ...)  → str (full HTML document)

`build_html_report` keeps a stable signature (the Streamlit layer calls it with
the same kwargs it always has); internally it derives a single DATA dict from
those arguments via `_dashboard_data` and bakes it into the dashboard template.

Per the module dependency chain, report.py sits below mechanics.py and may
import its pure helpers (realized_pnl, effective_basis).
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import pandas as pd

from config import LEAPS_DTE_THRESHOLD
from mechanics import realized_pnl, effective_basis


# ══════════════════════════════════════════════════════════════════════════════
# Data extraction — args → DATA dict consumed by the dashboard template
# ══════════════════════════════════════════════════════════════════════════════

def _r(v, dp=2):
    """Safe round — NaN/None/non-numeric collapse to 0.0."""
    try:
        if v is None:
            return 0.0
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return 0.0
        return round(f, dp)
    except (TypeError, ValueError):
        return 0.0


def _dashboard_data(all_cdf, credit_cdf, all_campaigns, daily_pnl_all, series_df,
                    pnl_display, net_deposited, capital_deployed,
                    div_income, int_net, total_fees,
                    win_start, win_end, days, n_trades):
    cdf = all_cdf if all_cdf is not None else pd.DataFrame()
    credit = credit_cdf if (credit_cdf is not None) else pd.DataFrame()
    has_credit = not credit.empty

    # ── overview ──
    # pnl_display is window-aware (window figure when a window is selected,
    # all-time figure for 'All Time') so the hero matches the windowed curve
    # endpoint and the windowed scorecard below it.
    overview = {
        'total_pnl': _r(pnl_display),
        'ror': _r(pnl_display / net_deposited * 100, 1) if net_deposited else 0.0,
        'deployed': _r(capital_deployed),
        'div': _r(div_income), 'int': _r(int_net),
        'deposited': _r(net_deposited),
    }

    # ── scorecard ──
    def col(dfx, c):
        return dfx[c] if (not dfx.empty and c in dfx.columns) else pd.Series(dtype=float)
    cred_pnl = col(credit, 'Net P/L')
    prem_sum = col(credit, 'Net Premium').sum()
    winners = cdf[cdf['Net P/L'] > 0]['Net P/L'] if (not cdf.empty and 'Net P/L' in cdf) else pd.Series(dtype=float)
    losers  = cdf[cdf['Net P/L'] < 0]['Net P/L'] if (not cdf.empty and 'Net P/L' in cdf) else pd.Series(dtype=float)
    avgw = winners.mean() if len(winners) else 0.0
    avgl = losers.mean()  if len(losers)  else 0.0
    gp = credit[credit['Net P/L'] > 0]['Net P/L'].sum() if has_credit else 0.0
    gl = abs(credit[credit['Net P/L'] <= 0]['Net P/L'].sum()) if has_credit else 0.0
    net_closed = cred_pnl.sum()
    scorecard = {
        'wr':   _r(col(credit, 'Won').mean() * 100, 1) if has_credit else 0.0,
        'cap':  _r(col(credit, 'Capture %').median(), 1) if has_credit else 0.0,
        'kept': _r(net_closed / prem_sum * 100, 1) if prem_sum else 0.0,
        'med_days': _r(col(credit, 'Days Held').median(), 0) if has_credit else 0.0,
        'prem_day': _r(col(credit, 'Prem/Day').median(), 2) if has_credit else 0.0,
        'theta': _r(col(credit, 'Daily θ %').median(), 3) if has_credit else 0.0,
        'kept_day': _r(net_closed / max(days, 1), 2),
        'avgw': _r(avgw), 'avgl': _r(avgl),
        'wl': _r(abs(avgw / avgl), 2) if avgl else 0.0,
        'fees': _r(total_fees),
        'fees_pct': _r(total_fees / abs(net_closed) * 100, 1) if net_closed else 0.0,
        'fees_trade': _r(total_fees / max(n_trades, 1), 2),
        'pf': _r(gp / gl, 2) if gl > 0 else 999,
    }

    # ── DTE + ThetaGang (all from cdf/credit columns — no raw df needed) ──
    short = credit[credit['DTE at Open'] <= LEAPS_DTE_THRESHOLD] if (has_credit and 'DTE at Open' in credit) else credit
    dvalid = short.dropna(subset=['DTE at Close']) if (not short.empty and 'DTE at Close' in short) else pd.DataFrame()
    sp = short[short['Type'].astype(str).str.contains('PUT', na=False)] if (not short.empty and 'Type' in short) else pd.DataFrame()
    asg = (sp['Close Reason'].astype(str).str.contains('Assign', na=False).mean() * 100) if (not sp.empty and 'Close Reason' in sp) else 0.0
    early = ((dvalid['DTE at Close'] >= 21).mean() * 100) if not dvalid.empty else 0.0
    mgmt = (cdf['Close Reason'].astype(str).str.contains('Closed', na=False).mean() * 100) if (not cdf.empty and 'Close Reason' in cdf) else 0.0
    by_t = credit.groupby('Ticker')['Net Premium'].sum().sort_values(ascending=False) if has_credit else pd.Series(dtype=float)
    top3 = (by_t.head(3).sum() / by_t.sum() * 100) if (len(by_t) and by_t.sum()) else 0.0
    dte = {'open': _r(short['DTE at Open'].median(), 0) if (not short.empty and 'DTE at Open' in short) else 0.0,
           'close': _r(dvalid['DTE at Close'].median(), 0) if not dvalid.empty else 0.0,
           'early': _r(early, 0), 'asg': _r(asg, 0)}
    thetagang = dict(dte, mgmt=_r(mgmt, 0), top3=_r(top3, 0),
                     top3names=', '.join(by_t.head(3).index.astype(str)) if len(by_t) else '—')

    # ── strategy breakdown ──
    strategy = []
    if not cdf.empty and 'Trade Type' in cdf:
        g = cdf.groupby('Trade Type').agg(n=('Won', 'count'), wr=('Won', lambda x: x.mean() * 100),
                                          pnl=('Net P/L', 'sum'), cap=('Capture %', 'median'))
        for name, r in g.sort_values('pnl', ascending=False).iterrows():
            strategy.append({'name': str(name), 'n': int(r['n']), 'wr': _r(r['wr'], 1),
                             'pnl': _r(r['pnl']), 'cap': None if pd.isna(r['cap']) else _r(r['cap'], 1)})

    # ── call vs put (credit) ──
    cvp = []
    if has_credit and 'Type' in credit:
        g = credit.groupby('Type').agg(n=('Won', 'count'), wr=('Won', lambda x: x.mean() * 100),
                                       cap=('Capture %', 'median'), pnl=('Net P/L', 'sum'))
        for t, r in g.iterrows():
            cvp.append({'type': str(t), 'n': int(r['n']), 'wr': _r(r['wr'], 1),
                        'cap': _r(r['cap'], 1), 'pnl': _r(r['pnl'])})

    # ── capture distribution ──
    cap_dist = []
    labels = ['Loss', '0-25%', '25-50%', '50-75%', '75-100%', '>100%']
    if has_credit and 'Capture %' in credit:
        bins = [-1e9, 0, 25, 50, 75, 100, 1e9]
        cb = pd.cut(credit['Capture %'], bins=bins, labels=labels).value_counts().reindex(labels, fill_value=0)
        cap_dist = [{'label': l, 'n': int(cb[l])} for l in labels]
    else:
        cap_dist = [{'label': l, 'n': 0} for l in labels]

    # ── portfolio realized P/L series — reflects the selected window ──
    # series_df is daily_pnl_all sliced to [win start, win end] by the caller
    # (full frame when 'All Time'), so the cumulative curve starts at 0 at the
    # window open and its endpoint equals the windowed hero P/L.
    series = []
    src = series_df if (series_df is not None) else daily_pnl_all
    if src is not None and not src.empty:
        d = src.sort_values('Date').copy()
        d['cum'] = d['PnL'].cumsum()
        series = [{'d': str(r['Date'])[:10], 'v': _r(r['cum'])} for _, r in d.iterrows()]

    # ── weekly / monthly OHLC candles of cumulative options P/L ──
    def candles(freq, fmt):
        if cdf.empty or 'Close Date' not in cdf:
            return []
        c2 = cdf.copy()
        c2['cd'] = pd.to_datetime(c2['Close Date'])
        c2 = c2.sort_values('cd')
        c2['cum'] = c2['Net P/L'].cumsum()
        rows, prev = [], 0.0
        for period, grp in c2.groupby(c2['cd'].dt.to_period(freq), sort=True):
            o, c = prev, grp['cum'].iloc[-1]
            rows.append({'lbl': period.start_time.strftime(fmt), 'o': _r(o), 'h': _r(max(grp['cum'].max(), o)),
                         'l': _r(min(grp['cum'].min(), o)), 'c': _r(c), 'net': _r(grp['Net P/L'].sum()), 'n': int(len(grp))})
            prev = c
        return rows
    weekly, monthly = candles('W', '%d %b'), candles('M', '%b %y')

    # ── performance by ticker ──
    tickers = []
    if not cdf.empty and 'Ticker' in cdf:
        cred_g_cap = credit.groupby('Ticker')['Capture %'].median() if has_credit else pd.Series(dtype=float)
        cred_g_th  = credit.groupby('Ticker')['Daily θ %'].median() if (has_credit and 'Daily θ %' in credit) else pd.Series(dtype=float)
        cred_g_pr  = credit.groupby('Ticker')['Net Premium'].sum() if has_credit else pd.Series(dtype=float)
        for tk, grp in cdf.groupby('Ticker'):
            wins = int((grp['Won'] == True).sum()); n = int(len(grp))
            cap = cred_g_cap.get(tk); th = cred_g_th.get(tk); pr = cred_g_pr.get(tk)
            tickers.append({'ticker': str(tk), 'wins': wins, 'losses': n - wins,
                            'wr': _r(grp['Won'].mean() * 100, 1), 'pnl': _r(grp['Net P/L'].sum()),
                            'avgd': _r(grp['Days Held'].mean(), 1),
                            'cap': None if (cap is None or pd.isna(cap)) else _r(cap, 1),
                            'theta': None if (th is None or pd.isna(th)) else _r(th, 3),
                            'prem': _r(pr) if (pr is not None and not pd.isna(pr)) else 0.0})
        tickers.sort(key=lambda x: -x['pnl'])

    # ── wheel campaigns (no roll detail) ──
    campaigns = []
    if all_campaigns:
        latest = daily_pnl_all['Date'].max() if (daily_pnl_all is not None and not daily_pnl_all.empty) else pd.Timestamp.now()
        for tk, camps in all_campaigns.items():
            for c in camps:
                dur = ((c.end_date if c.end_date is not None else latest) - c.start_date).days
                campaigns.append({'ticker': str(tk), 'status': 'Closed' if c.status == 'closed' else 'Open',
                                  'qty': int(c.total_shares), 'avg': _r(c.blended_basis),
                                  'basis': _r(effective_basis(c)), 'prem': _r(c.premiums),
                                  'div': _r(c.dividends), 'exit': _r(c.exit_proceeds),
                                  'pnl': _r(realized_pnl(c)), 'days': int(dur)})
        campaigns.sort(key=lambda x: -x['pnl'])

    return {
        'meta': {'start': win_start, 'end': win_end, 'days': int(days), 'n_trades': int(n_trades)},
        'overview': overview, 'scorecard': scorecard, 'dte': dte, 'thetagang': thetagang,
        'strategy': strategy, 'cvp': cvp, 'cap_dist': cap_dist, 'series': series,
        'weekly': weekly, 'monthly': monthly, 'tickers': tickers, 'campaigns': campaigns,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Dashboard template  (token __NAME__ substitution; no f-strings so CSS/JS
# braces need no escaping)
# ══════════════════════════════════════════════════════════════════════════════

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TastyMechanics — Dashboard</title>
<style>
  :root {
    --bg:#0a0e1a; --bg2:#0e1426; --card:#141b30; --card2:#1a2238;
    --bd:rgba(255,255,255,0.07); --bd2:rgba(255,255,255,0.12);
    --txt:#eef2fb; --mut:#97a1bd; --dim:#626c88;
    --emerald:#34d399; --rose:#fb7185; --teal:#2dd4bf; --cyan:#22d3ee;
    --violet:#a78bfa; --amber:#fbbf24; --blue:#60a5fa;
    --good:#34d399; --warn:#fbbf24; --bad:#fb7185;
    --sans:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  }
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
  * { box-sizing:border-box; margin:0; padding:0; }
  body {
    background:
      radial-gradient(1100px 600px at 12% -8%, rgba(45,212,191,0.10), transparent 60%),
      radial-gradient(1000px 560px at 100% 0%, rgba(167,139,250,0.10), transparent 55%),
      var(--bg);
    color:var(--txt); font-family:var(--sans); font-size:16px; line-height:1.55;
    padding:34px 20px 70px; -webkit-font-smoothing:antialiased;
  }
  .wrap { max-width:1180px; margin:0 auto; }
  .hdr { display:flex; align-items:center; gap:14px; margin-bottom:6px; }
  .brand { width:36px; height:36px; border-radius:9px; flex-shrink:0;
    background:linear-gradient(135deg,var(--teal),var(--violet));
    display:grid; place-items:center; font-size:19px; box-shadow:0 6px 20px rgba(45,212,191,0.35); }
  .brand-block { display:flex; flex-direction:column; gap:4px; }
  .brand-txt { font-weight:800; font-size:1.4rem; letter-spacing:-0.02em; line-height:1; }
  .period-line { display:flex; align-items:center; gap:11px; flex-wrap:wrap; }
  .pp { font-size:0.74rem; font-weight:800; letter-spacing:0.08em; text-transform:uppercase;
    color:#06121a; background:linear-gradient(135deg,var(--teal),var(--cyan)); padding:4px 12px; border-radius:999px; }
  .pr { font-size:1.12rem; font-weight:700; color:var(--txt); font-variant-numeric:tabular-nums; letter-spacing:-0.01em; }
  .brand-sub { color:var(--mut); font-size:0.86rem; margin-left:auto; text-align:right; }
  .brand-sub b { color:var(--txt); }
  .rise { opacity:0; transform:translateY(14px); animation:rise .6s cubic-bezier(.2,.7,.3,1) forwards; }
  @keyframes rise { to { opacity:1; transform:none; } }
  .hero { display:grid; grid-template-columns:1.4fr 1fr 1fr; gap:16px; margin:20px 0; }
  .card { background:linear-gradient(160deg,var(--card),var(--bg2));
    border:1px solid var(--bd); border-radius:16px; padding:22px 24px;
    box-shadow:0 8px 30px rgba(0,0,0,0.35); position:relative; overflow:hidden; }
  .card-lbl { font-size:0.74rem; font-weight:700; letter-spacing:0.13em; text-transform:uppercase; color:var(--mut); }
  .hero-main { background:linear-gradient(150deg,#16233f,#101a30); }
  .hero-main::after { content:''; position:absolute; inset:0;
    background:radial-gradient(400px 200px at 85% 0%,rgba(45,212,191,0.16),transparent 70%); }
  .hero-pnl { font-size:3rem; font-weight:900; letter-spacing:-0.03em; margin-top:6px; font-variant-numeric:tabular-nums; }
  .hero-row { display:flex; gap:10px; margin-top:14px; flex-wrap:wrap; position:relative; z-index:1; }
  .pill { font-size:0.86rem; font-weight:600; padding:5px 12px; border-radius:999px; background:rgba(255,255,255,0.06); border:1px solid var(--bd2); }
  .pill b { font-variant-numeric:tabular-nums; }
  .hero-side { display:flex; flex-direction:column; justify-content:center; gap:4px; }
  .hero-side .v { font-size:1.8rem; font-weight:800; font-variant-numeric:tabular-nums; letter-spacing:-0.02em; margin-top:4px; }
  .pos { color:var(--emerald); } .neg { color:var(--rose); }
  .tabs { display:flex; gap:4px; margin:24px 0 4px; border-bottom:1px solid var(--bd2); flex-wrap:wrap; }
  .tab-btn { padding:11px 20px; font-size:1rem; font-weight:600; color:var(--mut); font-family:inherit;
    background:none; border:none; cursor:pointer; border-bottom:2px solid transparent; margin-bottom:-1px; }
  .tab-btn:hover { color:var(--txt); }
  .tab-btn.active { color:var(--txt); border-bottom-color:var(--teal); }
  .panel { display:none; } .panel.active { display:block; animation:rise .4s ease; }
  .grid4 { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:16px 0; }
  .health { border-radius:14px; padding:16px 18px; border:1px solid var(--bd); border-left-width:4px; background:var(--card); }
  .health .icon { font-size:1.05rem; }
  .health .v { font-size:1.65rem; font-weight:800; margin:6px 0 2px; font-variant-numeric:tabular-nums; letter-spacing:-0.02em; }
  .health .note { font-size:0.82rem; color:var(--mut); }
  .g-good { border-left-color:var(--good); } .g-good .v { color:var(--good); }
  .g-warn { border-left-color:var(--warn); } .g-warn .v { color:var(--warn); }
  .g-bad  { border-left-color:var(--bad);  } .g-bad  .v { color:var(--bad); }
  .sec { margin:26px 0 12px; display:flex; align-items:baseline; gap:10px; }
  .sec h2 { font-size:1.18rem; font-weight:700; letter-spacing:-0.01em; }
  .sec .tag { font-size:0.72rem; font-weight:700; letter-spacing:0.13em; text-transform:uppercase; color:var(--teal); }
  .sec .meta { margin-left:auto; color:var(--dim); font-size:0.82rem; }
  .mgrid { display:grid; gap:13px; }
  .mrow7 { grid-template-columns:repeat(7,1fr); }
  .mcard { background:var(--card); border:1px solid var(--bd); border-radius:12px; padding:14px 15px; }
  .mcard .l { font-size:0.72rem; color:var(--mut); text-transform:uppercase; letter-spacing:0.06em; font-weight:700; line-height:1.25; min-height:2.5em; }
  .mcard .v { font-size:1.42rem; font-weight:800; margin-top:6px; font-variant-numeric:tabular-nums; letter-spacing:-0.02em; }
  .mcard .sub { font-size:0.74rem; color:var(--dim); margin-top:2px; }
  .row-lbl { font-size:0.72rem; font-weight:700; letter-spacing:0.1em; text-transform:uppercase; color:var(--mut); margin:14px 0 9px; }
  .chart-card { padding:20px 22px 14px; }
  .eqwrap { position:relative; }
  .eqsvg { width:100%; height:300px; display:block; overflow:visible; }
  .eqsvg.mini { height:180px; }
  .crosshair { position:absolute; top:0; width:1px; background:rgba(255,255,255,0.25); pointer-events:none; opacity:0; }
  .tip { position:absolute; pointer-events:none; opacity:0; transform:translate(-50%,-130%);
    background:#0c1326; border:1px solid var(--bd2); border-radius:9px; padding:7px 11px;
    font-size:0.84rem; white-space:nowrap; box-shadow:0 8px 24px rgba(0,0,0,0.5); z-index:5; }
  .tip .d { color:var(--mut); font-size:0.76rem; } .tip .v { font-weight:800; font-variant-numeric:tabular-nums; }
  .legend { display:flex; gap:16px; margin-top:8px; font-size:0.82rem; color:var(--mut); }
  .legend i { display:inline-block; width:16px; height:3px; border-radius:2px; vertical-align:middle; margin-right:6px; }
  .endval { font-size:0.95rem; font-weight:800; font-variant-numeric:tabular-nums; }
  .two { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  @media(max-width:880px){ .two,.hero,.grid4,.mrow7 { grid-template-columns:1fr 1fr; } }
  @media(max-width:560px){ .two,.hero,.grid4,.mrow7 { grid-template-columns:1fr; } }
  .bar-row { display:flex; align-items:center; gap:12px; margin:10px 0; }
  .bar-lbl { width:78px; font-size:0.84rem; color:var(--mut); text-align:right; flex-shrink:0; }
  .bar-track { flex:1; height:28px; background:rgba(255,255,255,0.04); border-radius:7px; overflow:hidden; }
  .bar-fill { height:100%; width:0; border-radius:7px; transition:width 1s cubic-bezier(.2,.7,.3,1);
    display:flex; align-items:center; justify-content:flex-end; padding-right:9px; font-size:0.8rem; font-weight:700; color:#06121a; }
  table { width:100%; border-collapse:collapse; font-size:0.9rem; }
  th { text-align:right; padding:10px 12px; color:var(--mut); font-weight:600; font-size:0.76rem;
    text-transform:uppercase; letter-spacing:0.05em; border-bottom:1px solid var(--bd2); cursor:pointer; user-select:none; white-space:nowrap; }
  th:first-child, td:first-child { text-align:left; }
  th:hover { color:var(--txt); }
  th.sorted::after { content:' ▾'; color:var(--teal); } th.sorted.asc::after { content:' ▴'; }
  td { padding:10px 12px; border-bottom:1px solid var(--bd); font-variant-numeric:tabular-nums; }
  tr:hover td { background:rgba(45,212,191,0.05); }
  tr.dim td { opacity:0.45; font-style:italic; }
  .strat-name { font-weight:600; }
  .plbar-wrap { display:flex; align-items:center; gap:8px; justify-content:flex-end; }
  .plbar { height:8px; border-radius:4px; }
  .chip { font-size:0.74rem; font-weight:700; padding:2px 9px; border-radius:999px; background:rgba(255,255,255,0.06); }
  .badge-open { color:var(--emerald); } .badge-closed { color:var(--mut); }
  .tbl-scroll { overflow-x:auto; }
  .cvp { display:flex; gap:16px; }
  .cvp-card { flex:1; border-radius:14px; padding:18px 20px; border:1px solid var(--bd); background:var(--card); }
  .cvp-card .top { display:flex; align-items:center; gap:8px; }
  .cvp-card .emoji { font-size:1.25rem; } .cvp-card .nm { font-weight:700; font-size:1.02rem; }
  .cvp-card .big { font-size:2rem; font-weight:800; margin-top:8px; font-variant-numeric:tabular-nums; }
  .cvp-stats { display:flex; gap:20px; margin-top:10px; }
  .cvp-stats div { font-size:0.84rem; color:var(--mut); }
  .cvp-stats b { display:block; color:var(--txt); font-size:1.05rem; font-weight:700; }
  @media(max-width:880px){ .cvp { flex-direction:column; } }
  .empty { color:var(--mut); padding:18px; font-size:0.95rem; }
  .foot { text-align:center; color:var(--dim); font-size:0.8rem; margin-top:38px; padding-top:16px; border-top:1px solid var(--bd); }
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr rise">
    <div class="brand">📟</div>
    <div class="brand-block">
      <div class="brand-txt">TastyMechanics</div>
      <div class="period-line"><span class="pp">__PERIOD__</span><span class="pr">__RANGE__</span></div>
    </div>
    <div class="brand-sub"><b>__NTRADES__ closed trades</b><br>__DAYS__ days</div>
  </div>
  <div class="hero">
    <div class="card hero-main rise" style="animation-delay:.05s">
      <div class="card-lbl">__PNL_LABEL__</div>
      <div class="hero-pnl" id="heroPnl">$0</div>
      <div class="hero-row">
        <span class="pill">ROR <b id="heroRor" class="pos">0%</b></span>
        <span class="pill">Deposited <b>__DEPOSITED__</b></span>
        <span class="pill">Capital Deployed <b>__DEPLOYED__</b></span>
      </div>
    </div>
    <div class="card hero-side rise" style="animation-delay:.1s">
      <div class="card-lbl">Dividends + Interest</div>
      <div class="v" id="divint">$0</div>
      <div style="color:var(--mut);font-size:0.84rem;">Div __DIV__ · Int __INT__</div>
    </div>
    <div class="card hero-side rise" style="animation-delay:.15s">
      <div class="card-lbl">Median Daily θ</div>
      <div class="v pos">__THETA__%</div>
      <div style="color:var(--mut);font-size:0.84rem;">yield on capital at risk · per day</div>
    </div>
  </div>
  <div class="tabs">
    <button class="tab-btn active" data-tab="overview">Overview</button>
    <button class="tab-btn" data-tab="perf">Performance</button>
    <button class="tab-btn" data-tab="wheel">Wheel &amp; Discipline</button>
  </div>
  <div class="panel active" id="panel-overview">
    <div class="sec"><span class="tag">Verdict</span><h2>Account Health</h2>
      <span class="meta">traffic-light thresholds · TastyTrade playbook</span></div>
    <div class="grid4" id="health"></div>
    <div class="sec"><span class="tag">Performance</span><h2>Portfolio Realized P/L</h2>
      <span class="meta">cumulative · options + equity + income</span></div>
    <div class="card chart-card">
      <div class="eqwrap" id="eqwrap">
        <svg class="eqsvg" id="eqsvg" viewBox="0 0 1000 300" preserveAspectRatio="none"></svg>
        <div class="crosshair"></div><div class="tip"></div>
      </div>
      <div class="legend">
        <span><i style="background:var(--teal)"></i>Realized P/L</span>
        <span><i style="background:var(--violet);opacity:.7"></i>10%/yr S&amp;P proxy on deposits</span>
      </div>
    </div>
  </div>
  <div class="panel" id="panel-perf">
    <div class="sec"><span class="tag">Options</span><h2>Premium Selling Scorecard</h2>
      <span class="meta">credit trades only</span></div>
    <div class="card">
      <div class="row-lbl">Trade Quality</div>
      <div class="mgrid mrow7" id="scQuality"></div>
      <div class="row-lbl">Risk &amp; Fees</div>
      <div class="mgrid mrow7" id="scRisk"></div>
    </div>
    <div class="sec"><span class="tag">Options curve</span><h2>Weekly &amp; Monthly Options P/L</h2>
      <span class="meta">cumulative-P/L candlesticks · by close date</span></div>
    <div class="two">
      <div class="card chart-card">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">
          <span class="card-lbl">Weekly</span><span class="endval" id="wkEnd"></span></div>
        <div class="eqwrap"><svg class="eqsvg mini" id="wkSvg" viewBox="0 0 500 180" preserveAspectRatio="none"></svg><div class="tip"></div></div>
      </div>
      <div class="card chart-card">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">
          <span class="card-lbl">Monthly</span><span class="endval" id="moEnd"></span></div>
        <div class="eqwrap"><svg class="eqsvg mini" id="moSvg" viewBox="0 0 500 180" preserveAspectRatio="none"></svg><div class="tip"></div></div>
      </div>
    </div>
    <div class="sec"><span class="tag">Quality</span><h2>Premium Capture %</h2></div>
    <div class="card" id="capdist"></div>
    <div class="sec"><span class="tag">Breakdown</span><h2>Strategy Performance</h2>
      <span class="meta">click a column to sort</span></div>
    <div class="card tbl-scroll" style="padding:8px 16px 16px;">
      <table id="strat"><thead><tr>
        <th data-k="name">Strategy</th><th data-k="n">Trades</th><th data-k="wr">Win %</th>
        <th data-k="cap">Capture %</th><th data-k="pnl" class="sorted">P/L</th>
      </tr></thead><tbody></tbody></table>
    </div>
    <div class="sec"><span class="tag">Premium</span><h2>Short Calls vs Short Puts</h2></div>
    <div class="cvp" id="cvp"></div>
    <div class="sec"><span class="tag">Per ticker</span><h2>Performance by Ticker</h2>
      <span class="meta">dim = &lt; 3 trades · click to sort</span></div>
    <div class="card tbl-scroll" style="padding:8px 16px 16px;">
      <table id="tickers"><thead><tr>
        <th data-k="ticker">Ticker</th><th data-k="wins">W/L</th><th data-k="wr">Win %</th>
        <th data-k="pnl" class="sorted">P/L</th><th data-k="avgd">Avg Days</th>
        <th data-k="cap">Capture %</th><th data-k="theta">Daily θ %</th><th data-k="prem">Net Prem</th>
      </tr></thead><tbody></tbody></table>
    </div>
  </div>
  <div class="panel" id="panel-wheel">
    <div class="sec"><span class="tag">Discipline</span><h2>ThetaGang Metrics</h2></div>
    <div class="card"><div class="mgrid" style="grid-template-columns:repeat(3,1fr);" id="tg"></div></div>
    <div class="sec"><span class="tag">Wheel</span><h2>Wheel Campaigns</h2>
      <span class="meta">share-holding campaigns · roll detail omitted</span></div>
    <div class="card tbl-scroll" style="padding:8px 16px 16px;">
      <table id="camps"><thead><tr>
        <th data-k="ticker">Ticker</th><th data-k="status">Status</th><th data-k="qty">Qty</th>
        <th data-k="avg">Avg Price</th><th data-k="basis">Cost Basis</th><th data-k="prem">Premiums</th>
        <th data-k="exit">Exit</th><th data-k="pnl" class="sorted">P/L</th><th data-k="days">Days</th>
      </tr></thead><tbody></tbody></table>
    </div>
  </div>
  <div class="foot">TastyMechanics dashboard · __VERSTAMP__generated __GENERATED__ · self-contained, no dependencies</div>
</div>
<script>
const DATA = __DATA__;
const fmtUSD = (v,dp=0) => (v<0?'-':'') + '$' + Math.abs(v).toLocaleString('en-US',{minimumFractionDigits:dp,maximumFractionDigits:dp});
const cls = v => v>=0 ? 'pos':'neg';
const ov=DATA.overview, sc=DATA.scorecard;
function countUp(el,target,fmt,ms=1100){const t0=performance.now();
  (function tick(now){const p=Math.min((now-t0)/ms,1),e=1-Math.pow(1-p,3);
   el.textContent=fmt(target*e); if(p<1)requestAnimationFrame(tick);})(t0);}
const heroPnl=document.getElementById('heroPnl');
countUp(heroPnl,ov.total_pnl,v=>fmtUSD(v)); heroPnl.className=cls(ov.total_pnl);
const ror=document.getElementById('heroRor'); ror.textContent=ov.ror.toFixed(1)+'%'; ror.className=cls(ov.ror);
const di=ov.div+ov.int; const dv=document.getElementById('divint');
countUp(dv,di,v=>fmtUSD(v,2)); dv.className=cls(di);
function verdict(val,g,w,gn,wn,bn){ if(val>=g)return['good','✅',gn]; if(val>=w)return['warn','⚠️',wn]; return['bad','❌',bn]; }
document.getElementById('health').innerHTML=[
  ['Win Rate',sc.wr.toFixed(1)+'%',verdict(sc.wr,70,50,'above 70% target','below 70% target','below 50% — review entries')],
  ['Median Capture %',sc.cap.toFixed(1)+'%',verdict(sc.cap,45,25,'near 50% TT target','below 50% TT target','far below target')],
  ['Net Premium Kept',sc.kept.toFixed(1)+'%',verdict(sc.kept,25,10,'above 25% TT target','below 25% TT target','losses eroding income')],
  ['Win/Loss Ratio',sc.wl.toFixed(2)+'×',verdict(sc.wl,0.5,0.25,'wins keep up with losers','avg loser 2–4× winner','avg loser >4× winner')],
].map(([l,v,[g,ic,n]])=>`<div class="health g-${g}"><span class="icon">${ic}</span> <span class="card-lbl">${l}</span>
   <div class="v">${v}</div><div class="note">${n}</div></div>`).join('');
const mcard=(l,v,sub,c='')=>`<div class="mcard"><div class="l">${l}</div><div class="v ${c}">${v}</div>${sub?`<div class="sub">${sub}</div>`:''}</div>`;
document.getElementById('scQuality').innerHTML=[
  mcard('Win Rate',sc.wr.toFixed(1)+'%','',sc.wr>=70?'pos':''),
  mcard('Median Capture %',sc.cap.toFixed(1)+'%','TT 50%'),
  mcard('Net Prem Kept %',sc.kept.toFixed(1)+'%','TT 25%',cls(sc.kept)),
  mcard('Med Days in Trade',sc.med_days.toFixed(0)+'d'),
  mcard('Med Prem/Day',fmtUSD(sc.prem_day,2)),
  mcard('Kept $/Day',fmtUSD(sc.kept_day,2),'',cls(sc.kept_day)),
  mcard('Med Daily θ %',sc.theta.toFixed(3)+'%','','pos'),
].join('');
document.getElementById('scRisk').innerHTML=[
  mcard('Avg Winner',fmtUSD(sc.avgw,2),'','pos'), mcard('Avg Loser',fmtUSD(sc.avgl,2),'','neg'),
  mcard('Win/Loss Ratio',sc.wl.toFixed(2)+'×'), mcard('Total Fees',fmtUSD(sc.fees,2),'','neg'),
  mcard('Fees % of P/L',sc.fees_pct.toFixed(1)+'%'), mcard('Fees/Trade',fmtUSD(sc.fees_trade,2)),
  mcard('Profit Factor',sc.pf>=999?'∞':sc.pf.toFixed(2),'',sc.pf>=1?'pos':'neg'),
].join('');
const tg=DATA.thetagang;
document.getElementById('tg').innerHTML=[
  mcard('Management Rate',tg.mgmt.toFixed(0)+'%','closed vs expired',tg.mgmt>=50?'pos':''),
  mcard('Med DTE at Open',tg.open.toFixed(0)+'d','TT 30–45'),
  mcard('Med DTE at Close',tg.close.toFixed(0)+'d','TT 14–21'),
  mcard('Early Mgmt Rate',tg.early.toFixed(0)+'%','≥21 DTE',tg.early>=50?'pos':'warn'),
  mcard('Assignment Rate',tg.asg.toFixed(0)+'%','short puts'),
  mcard('Top 3 Concentration',tg.top3.toFixed(0)+'%',tg.top3names,tg.top3>60?'warn':''),
].join('');
const pal={'Loss':'var(--rose)','0-25%':'#fb923c','25-50%':'var(--amber)','50-75%':'var(--cyan)','75-100%':'var(--emerald)','>100%':'var(--violet)'};
const maxN=Math.max(...DATA.cap_dist.map(d=>d.n),1);
document.getElementById('capdist').innerHTML=DATA.cap_dist.map(d=>
  `<div class="bar-row"><div class="bar-lbl">${d.label}</div>
   <div class="bar-track"><div class="bar-fill" data-w="${d.n/maxN*100}" style="background:${pal[d.label]}">${d.n||''}</div></div></div>`).join('');
function animBars(){ document.querySelectorAll('#capdist .bar-fill').forEach(b=>{ b.style.width='0'; requestAnimationFrame(()=>requestAnimationFrame(()=>b.style.width=b.dataset.w+'%')); }); }
function sortable(tblId, rows, render, defKey){
  let k=defKey, asc=false;
  function draw(){
    const r=[...rows].sort((a,b)=>{let x=a[k],y=b[k];
      if(typeof x==='string')return asc?x.localeCompare(y):y.localeCompare(x);
      x=x??-1e12;y=y??-1e12;return asc?x-y:y-x;});
    document.querySelector('#'+tblId+' tbody').innerHTML=r.map(render).join('');
    document.querySelectorAll('#'+tblId+' th').forEach(th=>{
      th.classList.toggle('sorted',th.dataset.k===k); th.classList.toggle('asc',th.dataset.k===k&&asc);});
  }
  document.querySelectorAll('#'+tblId+' th').forEach(th=>th.onclick=()=>{
    const nk=th.dataset.k; if(nk===k)asc=!asc; else{k=nk;asc=false;} draw();});
  draw();
}
if(DATA.strategy.length){
  const maxAbs=Math.max(...DATA.strategy.map(s=>Math.abs(s.pnl)),1);
  sortable('strat',DATA.strategy,s=>{
    const w=Math.abs(s.pnl)/maxAbs*90, col=s.pnl>=0?'var(--emerald)':'var(--rose)';
    return `<tr><td class="strat-name">${s.name}</td><td>${s.n}</td>
      <td><span class="chip" style="color:${s.wr>=70?'var(--emerald)':s.wr>=50?'var(--amber)':'var(--rose)'}">${s.wr.toFixed(0)}%</span></td>
      <td>${s.cap==null?'—':s.cap.toFixed(1)+'%'}</td>
      <td><div class="plbar-wrap"><span class="${cls(s.pnl)}">${fmtUSD(s.pnl,0)}</span>
        <span class="plbar" style="width:${w}px;background:${col}"></span></div></td></tr>`;},'pnl');
}
document.getElementById('cvp').innerHTML=DATA.cvp.length?DATA.cvp.map(c=>{
  const isC=c.type.toUpperCase().includes('CALL');
  return `<div class="cvp-card"><div class="top"><span class="emoji">${isC?'📞':'📍'}</span>
    <span class="nm">Short ${isC?'Calls':'Puts'}</span><span style="margin-left:auto" class="chip">${c.n} trades</span></div>
    <div class="big ${cls(c.pnl)}">${fmtUSD(c.pnl,2)}</div>
    <div class="cvp-stats"><div>Win Rate<b>${c.wr.toFixed(0)}%</b></div>
      <div>Med Capture<b>${c.cap.toFixed(1)}%</b></div></div></div>`;}).join(''):'<div class="empty">No credit trades.</div>';
if(DATA.tickers.length){
  sortable('tickers',DATA.tickers,t=>{
    const dim=(t.wins+t.losses)<3?' class="dim"':'';
    const wrc=t.wr>=70?'var(--emerald)':t.wr>=50?'var(--amber)':'var(--rose)';
    return `<tr${dim}><td class="strat-name">${t.ticker}</td><td>${t.wins}/${t.losses}</td>
      <td><span class="chip" style="color:${wrc}">${t.wr.toFixed(0)}%</span></td>
      <td class="${cls(t.pnl)}">${fmtUSD(t.pnl,2)}</td><td>${t.avgd.toFixed(0)}d</td>
      <td>${t.cap==null?'—':t.cap.toFixed(1)+'%'}</td><td>${t.theta==null?'—':t.theta.toFixed(3)+'%'}</td>
      <td>${fmtUSD(t.prem,2)}</td></tr>`;},'pnl');
}
if(DATA.campaigns.length){
  sortable('camps',DATA.campaigns,c=>
    `<tr><td class="strat-name">${c.ticker}</td>
      <td><span class="chip ${c.status==='Open'?'badge-open':'badge-closed'}">${c.status}</span></td>
      <td>${c.qty}</td><td>${fmtUSD(c.avg,2)}</td><td>${fmtUSD(c.basis,2)}</td>
      <td>${fmtUSD(c.prem,2)}</td><td>${c.exit?fmtUSD(c.exit,2):'—'}</td>
      <td class="${cls(c.pnl)}">${fmtUSD(c.pnl,2)}</td><td>${c.days}</td></tr>`,'pnl');
} else { document.querySelector('#camps tbody').innerHTML='<tr><td colspan="9" class="empty">No wheel campaigns.</td></tr>'; }
const drawStyle=document.createElement('style'); drawStyle.textContent='@keyframes draw{to{stroke-dashoffset:0}}@keyframes cfade{to{opacity:1}}'; document.head.appendChild(drawStyle);
function areaCurve(svg, pts, valKey, opts){
  opts=opts||{}; const W=opts.W||1000, H=opts.H||300, pT=14,pB=4,pL=4,pR=4;
  const vals=pts.map(p=>p[valKey]);
  const xs=pts.map((_,i)=> pts.length>1 ? pL+i/(pts.length-1)*(W-pL-pR) : W/2);
  let all=vals.concat([0]); if(opts.bench) all=all.concat(opts.bench);
  const lo=Math.min(...all), hi=Math.max(...all), span=(hi-lo)||1;
  const Y=v=>pT+(1-(v-lo)/span)*(H-pT-pB);
  const ys=vals.map(Y), y0=Y(0);
  const path=xs.map((x,i)=>(i?'L':'M')+x.toFixed(1)+' '+ys[i].toFixed(1)).join(' ');
  const area=path+` L${xs[xs.length-1].toFixed(1)} ${y0.toFixed(1)} L${xs[0].toFixed(1)} ${y0.toFixed(1)} Z`;
  const last=vals[vals.length-1], line=last>=0?'var(--emerald)':'var(--rose)', fill=last>=0?'rgba(52,211,153,0.16)':'rgba(251,113,133,0.16)';
  const gid='g'+Math.random().toString(36).slice(2,7);
  let bench=''; if(opts.bench){const yb=opts.bench.map(Y);
    bench=`<path d="${xs.map((x,i)=>(i?'L':'M')+x.toFixed(1)+' '+yb[i].toFixed(1)).join(' ')}" fill="none" stroke="var(--violet)" stroke-width="1.4" stroke-dasharray="4 4" opacity="0.65"/>`;}
  svg.innerHTML=`<defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${fill}"/><stop offset="100%" stop-color="transparent"/></linearGradient></defs>
    <line x1="0" y1="${y0.toFixed(1)}" x2="${W}" y2="${y0.toFixed(1)}" stroke="rgba(255,255,255,0.10)"/>
    <path d="${area}" fill="url(#${gid})"/>${bench}
    <path d="${path}" fill="none" stroke="${line}" stroke-width="2.4" stroke-linejoin="round"
      pathLength="1" style="stroke-dasharray:1;stroke-dashoffset:1;animation:draw 1.5s .15s ease forwards"/>
    <circle class="hd" r="4.5" fill="${line}" opacity="0"/>`;
  svg._mode='line'; svg._geo={xs,ys,vals,W,H}; svg._pts=pts; svg._lbl=opts.lbl||'d'; svg._vk=valKey;
}
function candleChart(svg, pts){
  const W=500,H=180,pT=12,pB=4,pL=8,pR=8;
  let all=[0]; pts.forEach(p=>{all.push(p.h,p.l);});
  const lo=Math.min(...all), hi=Math.max(...all), span=(hi-lo)||1;
  const Y=v=>pT+(1-(v-lo)/span)*(H-pT-pB);
  const n=pts.length, slot=(W-pL-pR)/Math.max(n,1), bw=Math.max(2,Math.min(slot*0.62,16)), y0=Y(0);
  const cx=i=>pL+slot*(i+0.5);
  let s=`<line x1="0" y1="${y0.toFixed(1)}" x2="${W}" y2="${y0.toFixed(1)}" stroke="rgba(255,255,255,0.10)"/>`;
  pts.forEach((p,i)=>{
    const up=p.c>=p.o, col=up?'var(--emerald)':'var(--rose)', x=cx(i);
    const yH=Y(p.h),yL=Y(p.l),top=Math.min(Y(p.o),Y(p.c)),bh=Math.max(Math.abs(Y(p.o)-Y(p.c)),1.6);
    s+=`<line x1="${x.toFixed(1)}" y1="${yH.toFixed(1)}" x2="${x.toFixed(1)}" y2="${yL.toFixed(1)}" stroke="${col}" stroke-width="1.1" opacity="0.6"/>`;
    s+=`<rect x="${(x-bw/2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" rx="1.4" fill="${col}"
        style="opacity:0;animation:cfade .5s ease forwards;animation-delay:${(i/Math.max(n,1)*0.5).toFixed(2)}s"/>`;
  });
  svg.innerHTML=s;
  svg._mode='candle'; svg._geo={W,H,pL,slot,cx,Y}; svg._pts=pts;
}
function wireHover(svg){
  const wrap=svg.closest('.eqwrap'); if(wrap._wired) return; wrap._wired=true;
  const tip=wrap.querySelector('.tip'); const dot=()=>svg.querySelector('.hd');
  wrap.addEventListener('mousemove',e=>{
    const pts=svg._pts, geo=svg._geo; if(!pts||!pts.length) return;
    const r=svg.getBoundingClientRect();
    if(svg._mode==='line'){
      let i=Math.round((e.clientX-r.left)/r.width*(pts.length-1)); i=Math.max(0,Math.min(pts.length-1,i));
      const cxPct=geo.xs[i]/geo.W*100, cyPx=geo.ys[i]/geo.H*r.height, v=geo.vals[i];
      const c=wrap.querySelector('.crosshair'); if(c){c.style.left=cxPct+'%';c.style.height=r.height+'px';c.style.opacity=1;}
      const d=dot(); if(d){d.setAttribute('cx',geo.xs[i]);d.setAttribute('cy',geo.ys[i]);d.setAttribute('opacity','1');}
      tip.style.left=cxPct+'%'; tip.style.top=cyPx+'px'; tip.style.opacity=1;
      tip.innerHTML=`<div class="d">${pts[i][svg._lbl]}</div><div class="v ${cls(v)}">${fmtUSD(v,2)}</div>`;
    } else {
      let i=Math.floor((e.clientX-r.left)/r.width*pts.length); i=Math.max(0,Math.min(pts.length-1,i));
      const p=pts[i], cxPct=geo.cx(i)/geo.W*100, cyPx=geo.Y(Math.max(p.o,p.c))/geo.H*r.height;
      tip.style.left=cxPct+'%'; tip.style.top=cyPx+'px'; tip.style.opacity=1;
      tip.innerHTML=`<div class="d">${p.lbl} · ${p.n} trades</div><div class="v ${cls(p.net)}">Net ${fmtUSD(p.net,2)}</div>`;
    }
  });
  wrap.addEventListener('mouseleave',()=>{ tip.style.opacity=0; const c=wrap.querySelector('.crosshair'); if(c)c.style.opacity=0; const d=dot(); if(d)d.setAttribute('opacity','0'); });
}
function renderEquity(){
  const S=DATA.series; if(!S.length) return;
  const d0=new Date(S[0].d), dep=ov.deposited;
  const bench=dep>0?S.map(p=>{const days=(new Date(p.d)-d0)/86400000; return dep*(Math.pow(1+0.10/365,days)-1);}):null;
  const svg=document.getElementById('eqsvg'); areaCurve(svg,S,'v',{bench,lbl:'d'}); wireHover(svg);
}
function renderPerf(){
  if(DATA.weekly.length){ const s=document.getElementById('wkSvg'); candleChart(s,DATA.weekly); wireHover(s);
    const e=DATA.weekly[DATA.weekly.length-1].c, el=document.getElementById('wkEnd'); el.textContent=fmtUSD(e,0); el.className='endval '+cls(e); }
  if(DATA.monthly.length){ const s=document.getElementById('moSvg'); candleChart(s,DATA.monthly); wireHover(s);
    const e=DATA.monthly[DATA.monthly.length-1].c, el=document.getElementById('moEnd'); el.textContent=fmtUSD(e,0); el.className='endval '+cls(e); }
  animBars();
}
renderEquity();  // Portfolio Realized P/L lives in Overview (default-active tab) — draw on load
document.querySelectorAll('.tab-btn').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');
  document.getElementById('panel-'+b.dataset.tab).classList.add('active');
  if(b.dataset.tab==='perf') renderPerf();
  else if(b.dataset.tab==='overview') renderEquity();
});
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# Public entry point — stable signature called by the Streamlit layer
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
    open_premiums_banked=0.0,
    pure_opts_pnl=0.0,
    app_version='',
    csv_fingerprint='',
    benchmark_annual_pct=10.0,
    end_date=None,               # window upper bound (Custom-aware); defaults to latest_date
):
    """Build the self-contained tabbed HTML dashboard as a string.

    Signature is stable — the Streamlit layer passes the same kwargs it always
    has.  The all-time-vs-window split mirrors the prior report: the scorecard,
    breakdowns, candlesticks and per-ticker table reflect ``all_cdf`` /
    ``credit_cdf`` (already window-sliced by the caller), while the Portfolio
    Realized P/L curve uses ``daily_pnl_all`` (full history).
    """
    generated = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    try:
        days = max((latest_date - start_date).days, 1)
    except (TypeError, AttributeError):
        days = 1
    n_trades = len(all_cdf) if all_cdf is not None else 0

    _is_all_time = (selected_period == 'All Time')
    # Window-aware hero P/L — matches the windowed curve endpoint + scorecard.
    pnl_display = total_realized_pnl if _is_all_time else window_realized_pnl

    # Slice the daily P/L series to the selected window so the Portfolio
    # Realized P/L curve reflects the same range as every other chart.  Use the
    # real start_date / end_date Timestamps (time-aware) — the exact bounds the
    # caller used to slice df_window / all_cdf — so the curve's endpoint equals
    # the windowed hero P/L to the cent.  (Normalising to calendar dates pulled
    # in an extra boundary day and broke that match.)
    series_df = daily_pnl_all
    _end = end_date if end_date is not None else latest_date
    if (daily_pnl_all is not None and not daily_pnl_all.empty and not _is_all_time):
        try:
            _d = pd.to_datetime(daily_pnl_all['Date'])
            series_df = daily_pnl_all[(_d >= start_date) & (_d <= _end)]
        except (ValueError, TypeError):
            series_df = daily_pnl_all

    data = _dashboard_data(
        all_cdf, credit_cdf, all_campaigns, daily_pnl_all, series_df,
        pnl_display, net_deposited, capital_deployed,
        div_income, int_net, total_fees,
        _win_start_str, _win_end_str, days, n_trades,
    )

    # ── headline period + range (e.g. "30 DAYS   11 May 2026 → 10 Jun 2026") ──
    def _pretty(s):
        for fmt in ('%d/%m/%y', '%d/%m/%Y', '%Y-%m-%d'):
            try:
                return datetime.strptime(str(s), fmt).strftime('%d %b %Y')
            except (ValueError, TypeError):
                continue
        return str(s)
    range_str = '%s → %s' % (_pretty(_win_start_str), _pretty(_win_end_str))
    pnl_label = 'Total Realized P/L' if _is_all_time else 'Realized P/L · window'

    ov = data['overview']
    fmt_int = lambda v: '$%s' % format(round(v), ',')
    fmt_signed = lambda v: ('-$%.2f' % abs(v)) if v < 0 else '$%.2f' % v
    verstamp = ''
    if app_version or csv_fingerprint:
        bits = [b for b in (app_version, ('CSV %s' % csv_fingerprint) if csv_fingerprint else '') if b]
        verstamp = ' · '.join(bits) + ' · '

    return (_TEMPLATE
        .replace('__DATA__', json.dumps(data))
        .replace('__GENERATED__', generated)
        .replace('__VERSTAMP__', verstamp)
        .replace('__PERIOD__', str(selected_period))
        .replace('__RANGE__', range_str)
        .replace('__PNL_LABEL__', pnl_label)
        .replace('__DAYS__', str(days))
        .replace('__NTRADES__', str(n_trades))
        .replace('__DEPOSITED__', fmt_int(ov['deposited']))
        .replace('__DEPLOYED__', fmt_int(ov['deployed']))
        .replace('__DIV__', '$%.2f' % ov['div'])
        .replace('__INT__', fmt_signed(ov['int']))
        .replace('__THETA__', '%.3f' % data['scorecard']['theta'])
    )
