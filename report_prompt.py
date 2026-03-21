"""
report_prompt.py — Builds a structured AI review prompt from computed app metrics.

No Streamlit dependency. Pure function — takes data, returns a plain-text string
ready to paste into any LLM (Claude, ChatGPT, Gemini, etc.).
"""

import pandas as pd

from config import (
    OPT_TYPES, SUB_SELL_OPEN, PAT_CLOSING, PAT_CLOSE,
    LEAPS_DTE_THRESHOLD, INCOME_SUB_TYPES,
)
from ui_components import fmt_dollar
from mechanics import realized_pnl, effective_basis


# ── helpers ───────────────────────────────────────────────────────────────────

def _pct(n, d, fallback='—'):
    return '%.0f%%' % (n / d * 100) if d else fallback

def _days_to_free(c, latest_date):
    """Return 'Free', '~Nd', or '—' for an open campaign."""
    days_active = max(1, (latest_date - c.start_date).days)
    income      = c.premiums + c.dividends
    remaining   = c.total_cost - income
    rate        = income / days_active
    if remaining <= 0:
        return 'Free (basis recovered)'
    if rate > 0:
        return '~%dd' % int(remaining / rate)
    return '—'


# ── main builder ──────────────────────────────────────────────────────────────

def build_review_prompt(
    all_cdf,
    credit_cdf,
    all_campaigns,
    df_window,
    latest_date,
    start_date,
    selected_period,
    window_realized_pnl,
    total_realized_pnl,
    div_income,
    int_net,
    total_deposited,
    net_deposited,
    realized_ror,
    use_lifetime,
):
    """
    Build a plain-text AI review prompt populated with the current window's metrics.
    Returns a str. All monetary values are formatted as dollars. Percentages are
    rounded to the nearest integer.
    """
    lines = []
    add   = lines.append

    win_start = start_date.strftime('%d/%m/%Y')
    win_end   = latest_date.strftime('%d/%m/%Y')

    add('# TastyMechanics — Theta Selling Review')
    add(f'Period: {win_start} → {win_end}  ({selected_period})')
    add('')

    # ── 1. Portfolio overview ─────────────────────────────────────────────────
    add('## 1. Portfolio Overview')
    add(f'- Realized P/L (window):  {fmt_dollar(window_realized_pnl)}')
    add(f'- Realized P/L (all-time): {fmt_dollar(total_realized_pnl)}')
    add(f'- Net deposited capital:   {fmt_dollar(net_deposited)}')
    add(f'- Return on capital (RoR): {realized_ror:.1f}%')
    add(f'- Dividend income (window): {fmt_dollar(div_income)}')
    add(f'- Interest net (window):    {fmt_dollar(int_net)}')
    add('')

    if all_cdf.empty:
        add('No closed trades in this window.')
        add('')
        _add_review_questions(lines)
        return '\n'.join(lines)

    n_trades  = len(all_cdf)
    n_wins    = all_cdf['Won'].sum() if 'Won' in all_cdf.columns else 0
    win_rate  = n_wins / n_trades * 100 if n_trades else 0
    avg_pnl   = all_cdf['Net P/L'].mean()
    winners   = all_cdf[all_cdf['Net P/L'] >= 0]['Net P/L']
    losers    = all_cdf[all_cdf['Net P/L'] < 0]['Net P/L']
    avg_win   = winners.mean() if not winners.empty else 0
    avg_loss  = losers.mean()  if not losers.empty  else 0
    pf_denom  = abs(losers.sum())
    prof_fac  = winners.sum() / pf_denom if pf_denom > 0 else float('inf')

    add('## 2. Closed Trade Summary')
    add(f'- Trades in window:   {n_trades}')
    add(f'- Win rate:           {win_rate:.0f}%  ({int(n_wins)} wins / {int(n_trades - n_wins)} losses)')
    add(f'- Avg P/L per trade:  {fmt_dollar(avg_pnl)}')
    add(f'- Avg win:            {fmt_dollar(avg_win)}')
    add(f'- Avg loss:           {fmt_dollar(avg_loss)}')
    add(f'- Profit factor:      {prof_fac:.2f}' if prof_fac != float('inf') else '- Profit factor: ∞ (no losses)')
    add(f'- Median trade P/L:   {fmt_dollar(all_cdf["Net P/L"].median())}')
    add('')

    # ── 2. ThetaGang discipline ───────────────────────────────────────────────
    add('## 3. ThetaGang Discipline Metrics')

    _tg_opts = df_window[df_window['Instrument Type'].isin(OPT_TYPES)]
    _tg_cls  = _tg_opts[
        _tg_opts['Sub Type'].str.lower().str.contains(PAT_CLOSING, na=False)
    ].copy()
    _tg_cls['Exp'] = pd.to_datetime(
        _tg_cls['Expiration Date'], format='mixed', errors='coerce'
    ).dt.normalize()
    _tg_cls['DTE_close'] = (_tg_cls['Exp'] - _tg_cls['Date']).dt.days.clip(lower=0)

    _short_cdf = (
        credit_cdf[credit_cdf['DTE at Open'] <= LEAPS_DTE_THRESHOLD]
        if 'DTE at Open' in credit_cdf.columns and not credit_cdf.empty
        else credit_cdf
    )
    _tg_short = _tg_cls[
        _tg_cls['DTE_close'].isna() | (_tg_cls['DTE_close'] <= LEAPS_DTE_THRESHOLD)
    ]
    _dte_valid = _tg_short.dropna(subset=['DTE_close'])

    n_managed  = (_tg_short['Sub Type'].str.lower().str.contains(PAT_CLOSE)).sum()
    n_expired  = (_tg_short['Sub Type'].str.lower().str.contains('expir|assign|exercise')).sum()
    n_total    = len(_tg_short)
    mgmt_rate  = n_managed / n_total * 100 if n_total else 0

    med_dte_open  = (
        _short_cdf['DTE at Open'].median()
        if 'DTE at Open' in _short_cdf.columns and not _short_cdf.empty
        else None
    )
    med_dte_close = _dte_valid['DTE_close'].median() if not _dte_valid.empty else None

    n_early    = (_dte_valid['DTE_close'] >= 21).sum()
    early_rate = n_early / len(_dte_valid) * 100 if not _dte_valid.empty else 0

    avg_capture = (
        _short_cdf['Capture %'].mean()
        if 'Capture %' in _short_cdf.columns and not _short_cdf.empty
        else None
    )

    _sp = _short_cdf[
        _short_cdf['Type'].str.upper().str.contains('PUT', na=False)
    ] if 'Type' in _short_cdf.columns and not _short_cdf.empty else pd.DataFrame()
    n_assigned = (
        (_sp['Close Reason'].str.contains('Assign', na=False)).sum()
        if not _sp.empty and 'Close Reason' in _sp.columns else 0
    )
    n_sp_total = len(_sp)

    # Concentration
    _sto = _tg_opts[_tg_opts['Sub Type'].str.lower() == SUB_SELL_OPEN]
    _by_tkr = _sto.groupby('Ticker')['Total'].sum().sort_values(ascending=False)
    _total_prem_conc = _by_tkr.sum()
    top3_pct   = _by_tkr.head(3).sum() / _total_prem_conc * 100 if _total_prem_conc else 0
    top3_names = ', '.join(_by_tkr.head(3).index.tolist()) if not _by_tkr.empty else '—'

    add(f'- Management rate:          {mgmt_rate:.0f}%  ({n_managed} managed, {n_expired} expired/assigned)')
    add(f'- Median DTE at open:       {med_dte_open:.0f}d' if med_dte_open is not None else '- Median DTE at open:       —')
    add(f'- Median DTE at close:      {med_dte_close:.0f}d' if med_dte_close is not None else '- Median DTE at close:      —')
    add(f'- Early mgmt rate (≥21 DTE): {early_rate:.0f}%  (TastyTrade target: close before gamma risk)')
    add(f'- Avg capture %:            {avg_capture:.0f}%' if avg_capture is not None else '- Avg capture %:            —')
    add(f'- Assignment rate:          {_pct(n_assigned, n_sp_total)}  ({n_assigned} of {n_sp_total} short puts)')
    add(f'- Top 3 concentration:      {top3_pct:.0f}%  ({top3_names})')
    add('')

    # ── 3. Strategy breakdown ─────────────────────────────────────────────────
    add('## 4. Strategy Breakdown')
    if 'Trade Type' in all_cdf.columns:
        _strat = all_cdf.groupby('Trade Type').agg(
            Trades=('Net P/L', 'count'),
            Wins=('Won', 'sum'),
            Total_PL=('Net P/L', 'sum'),
            Avg_PL=('Net P/L', 'mean'),
        ).sort_values('Total_PL', ascending=False)
        add(f'{"Strategy":<30} {"Trades":>6}  {"WinRate":>7}  {"Total P/L":>10}  {"Avg P/L":>9}')
        add('-' * 68)
        for strat, row in _strat.iterrows():
            wr = row['Wins'] / row['Trades'] * 100 if row['Trades'] else 0
            add(f'{str(strat):<30} {int(row["Trades"]):>6}  {wr:>6.0f}%  {fmt_dollar(row["Total_PL"]):>10}  {fmt_dollar(row["Avg_PL"]):>9}')
    else:
        add('(strategy data not available)')
    add('')

    # ── 4. Per-ticker performance ─────────────────────────────────────────────
    add('## 5. Per-Ticker Performance')
    if 'Ticker' in all_cdf.columns:
        _tkr = all_cdf.groupby('Ticker').agg(
            Trades=('Net P/L', 'count'),
            Wins=('Won', 'sum'),
            Total_PL=('Net P/L', 'sum'),
        ).sort_values('Total_PL', ascending=False)
        add(f'{"Ticker":<10} {"Trades":>6}  {"WinRate":>7}  {"Total P/L":>10}')
        add('-' * 38)
        for tkr, row in _tkr.iterrows():
            wr = row['Wins'] / row['Trades'] * 100 if row['Trades'] else 0
            add(f'{str(tkr):<10} {int(row["Trades"]):>6}  {wr:>6.0f}%  {fmt_dollar(row["Total_PL"]):>10}')
    else:
        add('(ticker data not available)')
    add('')

    # ── 5. Open wheel campaigns ───────────────────────────────────────────────
    add('## 6. Open Wheel Campaigns')
    open_camps = [
        (ticker, i, c)
        for ticker, camps in (all_campaigns.items() if hasattr(all_campaigns, 'items') else [])
        for i, c in enumerate(camps)
        if c.status == 'open'
    ]
    if open_camps:
        add(f'{"Ticker":<8} {"Shares":>6}  {"Entry":>8}  {"Eff Basis":>9}  {"Premiums":>9}  {"Days":>5}  {"Days to Free":>14}  {"Realized P/L":>13}')
        add('-' * 84)
        for ticker, i, c in open_camps:
            effb  = effective_basis(c, use_lifetime)
            rpnl  = realized_pnl(c, use_lifetime)
            days  = (latest_date - c.start_date).days
            dtf   = _days_to_free(c, latest_date)
            add(f'{ticker:<8} {int(c.total_shares):>6}  ${c.blended_basis:>7.2f}  ${effb:>8.2f}  {fmt_dollar(c.premiums):>9}  {days:>5}d  {dtf:>14}  {fmt_dollar(rpnl):>13}')
    else:
        add('No open wheel campaigns.')
    add('')

    # ── 6. Best & worst trades ────────────────────────────────────────────────
    add('## 7. Best 5 Trades')
    _best_cols = [c for c in ['Ticker', 'Trade Type', 'Days Held', 'Net P/L'] if c in all_cdf.columns]
    for _, row in all_cdf.nlargest(5, 'Net P/L')[_best_cols].iterrows():
        tkr   = row.get('Ticker', '?')
        strat = row.get('Trade Type', '?')
        days  = ('%dd' % int(row['Days Held'])) if pd.notna(row.get('Days Held')) else '?'
        add(f'  {tkr}  {strat}  held {days}  →  {fmt_dollar(row["Net P/L"])}')
    add('')

    add('## 8. Worst 5 Trades')
    for _, row in all_cdf.nsmallest(5, 'Net P/L')[_best_cols].iterrows():
        tkr   = row.get('Ticker', '?')
        strat = row.get('Trade Type', '?')
        days  = ('%dd' % int(row['Days Held'])) if pd.notna(row.get('Days Held')) else '?'
        add(f'  {tkr}  {strat}  held {days}  →  {fmt_dollar(row["Net P/L"])}')
    add('')

    # ── Review questions ──────────────────────────────────────────────────────
    _add_review_questions(lines)
    return '\n'.join(lines)


def _add_review_questions(lines):
    lines.append('---')
    lines.append('')
    lines.append('## Review Request')
    lines.append(
        'I trade theta strategies on TastyTrade — short puts, covered calls, strangles, '
        'iron condors, and the full wheel cycle (take assignment on short puts, sell covered '
        'calls against the shares until called away). The metrics above are from my trading '
        'dashboard (TastyMechanics).'
    )
    lines.append('')
    lines.append('Please review my trading and:')
    lines.append('')
    lines.append('1. Identify the 2–3 areas of discipline that most need attention (with specific evidence from the numbers above).')
    lines.append('2. Flag any concentration, sizing, or risk concerns.')
    lines.append('3. Note what the DTE and management metrics say about my trade management habits.')
    lines.append('4. Highlight anything that looks healthy and worth continuing.')
    lines.append('5. Suggest one or two concrete adjustments I could make in the next 30 days.')
    lines.append('')
    lines.append('Be specific and reference the actual numbers. Skip general options education — I know the mechanics.')
