"""
TastyMechanics — UI Components
================================
Pure visual helpers: HTML generators, chart layouts, DataFrame stylers.
No business logic or math lives here — these functions only produce
strings, dicts, and style values for rendering.

Dependencies: pandas (for isna / pd.to_datetime), config (for sub-type
constants used in colour lookups).
"""

import html as _html
import pandas as pd
from config import SUB_DIVIDEND, SUB_CREDIT_INT, SUB_DEBIT_INT
# is_share_row / is_option_row live in ingestion.py — that is the correct home
# for anything that encodes TastyTrade field values.  Re-exported here so that
# tastymechanics.py can continue to import them from ui_components without change.
from ingestion import is_share_row, is_option_row


# ── XSS safety ────────────────────────────────────────────────────────────────

def xe(s):
    """Escape a string for safe HTML interpolation. Prevents XSS from CSV data."""
    return _html.escape(str(s), quote=True)


# ── Position type helpers (pure classification, no math) ──────────────────────

def identify_pos_type(row):
    """Classify a single open-position row as Long/Short Stock/Call/Put."""
    qty  = row['Net_Qty']
    inst = str(row['Instrument Type'])
    cp   = str(row.get('Call or Put', '')).upper()
    if is_share_row(inst):  return 'Long Stock' if qty > 0 else 'Short Stock'
    if is_option_row(inst):
        if 'CALL' in cp: return 'Long Call' if qty > 0 else 'Short Call'
        if 'PUT'  in cp: return 'Long Put'  if qty > 0 else 'Short Put'
    return 'Asset'

def translate_readable(row):
    """Human-readable label for an open position row (e.g. 'STO 1 @ 25P (14/03)')."""
    if not is_option_row(str(row['Instrument Type'])):
        return '%s Shares' % row['Ticker']
    try:
        exp_dt = pd.to_datetime(
            row['Expiration Date'], format='mixed', errors='coerce'
        ).strftime('%d/%m')
    except (ValueError, TypeError, AttributeError):
        exp_dt = 'N/A'
    cp     = 'C' if 'CALL' in str(row['Call or Put']).upper() else 'P'
    action = 'STO' if row['Net_Qty'] < 0 else 'BTO'
    return '%s %d @ %.0f%s (%s)' % (
        action, abs(int(row['Net_Qty'])), row['Strike Price'], cp, exp_dt
    )

def format_cost_basis(val):
    """Format a cost-basis value as '$12.34 Cr' or '$12.34 Db'."""
    return '$%.2f %s' % (abs(val), 'Cr' if val < 0 else 'Db')

def fmt_dollar(val, decimals=2):
    """
    Format a dollar value with sign, commas, and configurable decimal places.
    Negative values render as '-$1,234.56' (not '$-1,234.56').
    Use decimals=0 for whole-dollar chart labels.

    Examples:
        fmt_dollar(1234.56)   → '$1,234.56'
        fmt_dollar(-99.5)     → '-$99.50'
        fmt_dollar(1500, 0)   → '$1,500'
    """
    fmt = f'{{:,.{decimals}f}}'
    if val >= 0:
        return f'${fmt.format(val)}'
    return f'-${fmt.format(abs(val))}'

def detect_strategy(ticker_df):
    """Infer the current strategy name for an open-position ticker DataFrame."""
    types = ticker_df.apply(identify_pos_type, axis=1)
    ls = (types == 'Long Stock').sum()
    sc = (types == 'Short Call').sum()
    lc = (types == 'Long Call').sum()
    sp = (types == 'Short Put').sum()
    lp = (types == 'Long Put').sum()
    strikes = ticker_df['Strike Price'].dropna().unique()
    exps    = ticker_df['Expiration Date'].dropna().unique()
    if lc > 0 and sc > 0 and len(exps) >= 2 and len(strikes) == 1: return 'Calendar Spread'
    if lp > 0 and sp > 0 and len(exps) >= 2 and len(strikes) == 1: return 'Calendar Spread'
    if lc == 2 and sc == 1 and len(strikes) == 3 and len(exps) == 1: return 'Call Butterfly'
    if lp == 2 and sp == 1 and len(strikes) == 3 and len(exps) == 1: return 'Put Butterfly'
    if ls > 0 and sc > 0 and sp > 0: return 'Covered Strangle'
    if ls > 0 and sc > 0:            return 'Covered Call'
    if sp >= 1 and sc >= 1 and lc >= 1: return 'Jade Lizard'
    if sc >= 1 and sp >= 1 and lp >= 1: return 'Big Lizard'
    if sc >= 1 and sp >= 1:             return 'Short Strangle'
    if lc >= 1 and sp >= 1:             return 'Risk Reversal'
    if lc > 1  and sc > 0:             return 'Call Debit Spread'
    if sp > 0:  return 'Short Put'
    if lc > 0:  return 'Long Call'
    if ls > 0:  return 'Long Stock'
    return 'Custom/Mixed'


# ── DataFrame stylers ─────────────────────────────────────────────────────────

def color_win_rate(v):
    """Green / amber / red for win-rate cells in st.dataframe."""
    if not isinstance(v, (int, float)) or pd.isna(v): return ''
    if v >= 70: return 'color: #00cc96; font-weight: bold'
    if v >= 50: return 'color: #ffa500'
    return 'color: #ef553b'

def color_pnl_cell(val):
    """Green/red colouring for P/L columns in st.dataframe."""
    if not isinstance(val, (int, float)) or pd.isna(val): return ''
    return 'color: #00cc96' if val > 0 else 'color: #ef553b' if val < 0 else ''

def _fmt_ann_ret(row):
    """Format Ann Ret % cell — appends * for trades held < 4 days."""
    v = row['Ann Ret %']
    if pd.isna(v):
        return '—'
    suffix = '*' if pd.notna(row['Days']) and row['Days'] < 4 else ''
    return '{:.0f}%{}'.format(v, suffix)

def _style_ann_ret(row):
    """Row-level style: dim Ann Ret % for very short-hold trades."""
    styles = [''] * len(row)
    try:
        idx = list(row.index).index('Ann Ret %')
        if pd.notna(row.get('Days')) and row.get('Days', 99) < 4:
            styles[idx] = 'color: #8b7355'
    except (ValueError, KeyError):
        pass
    return styles

def _style_chain_row(row):
    """Highlight the open leg in a roll-chain detail table."""
    if row.get('_open', False):
        return ['background-color: rgba(0,204,150,0.12); font-weight:600'] * len(row)
    return [''] * len(row)

def _color_cash_row(row):
    """Row background tint for the Deposits/Dividends table."""
    sub = str(row.get('Sub Type', ''))
    tints = {
        'Deposit':            'rgba(0,204,150,0.08)',
        'Withdrawal':         'rgba(239,85,59,0.08)',
        SUB_DIVIDEND:         'rgba(88,166,255,0.08)',
        SUB_CREDIT_INT:       'rgba(88,166,255,0.05)',
        SUB_DEBIT_INT:        'rgba(239,85,59,0.05)',
        'Balance Adjustment': 'rgba(255,165,0,0.07)',
    }
    c = tints.get(sub, '')
    return [f'background-color:{c}' if c else ''] * len(row)

def _color_cash_total(val):
    """Green/red for the Total column in the cash-flow table."""
    if not isinstance(val, (int, float)): return ''
    return 'color:#00cc96' if val > 0 else 'color:#ef553b' if val < 0 else ''


# ── Plotly chart layout ───────────────────────────────────────────────────────

def chart_layout(title='', height=300, margin_t=36, margin_b=20):
    """Consistent base layout dict for all Plotly charts."""
    return dict(
        template='plotly_dark',
        height=height,
        paper_bgcolor='rgba(10,14,23,0)',
        plot_bgcolor='rgba(10,14,23,0)',
        font=dict(family='IBM Plex Sans, sans-serif', size=12, color='#8b949e'),
        title=dict(
            text=title,
            font=dict(size=13, color='#c9d1d9', family='IBM Plex Sans'),
            x=0, xanchor='left', pad=dict(l=0, b=8),
        ) if title else None,
        margin=dict(l=8, r=8, t=margin_t if title else 16, b=margin_b),
        xaxis=dict(
            gridcolor='rgba(255,255,255,0.05)',
            linecolor='rgba(255,255,255,0.08)',
            tickfont=dict(size=11),
        ),
        yaxis=dict(
            gridcolor='rgba(255,255,255,0.05)',
            linecolor='rgba(255,255,255,0.08)',
            tickfont=dict(size=11),
        ),
        legend=dict(bgcolor='rgba(0,0,0,0)', borderwidth=0, font=dict(size=11)),
    )


# ── Inline HTML components ────────────────────────────────────────────────────

def _pnl_chip(label, val):
    """Inline HTML chip: labelled P/L value with sign colour."""
    col  = '#00cc96' if val >= 0 else '#ef553b'
    sign = '+' if val >= 0 else ''
    return (
        f'<span style="display:inline-flex;align-items:center;gap:5px;'
        f'background:rgba(255,255,255,0.04);border:1px solid #1f2937;'
        f'border-radius:6px;padding:3px 10px;margin:2px 4px 2px 0;font-size:0.78rem;">'
        f'<span style="color:#6b7280;">{label}</span>'
        f'<span style="color:{col};font-family:monospace;font-weight:600;">'
        f'{sign}${abs(val):,.2f}</span>'
        f'</span>'
    )

def _cmp_block(label, curr, prev, is_pct=False):
    """One column block in the period-comparison card."""
    delta = curr - prev
    dcol  = '#00cc96' if delta >= 0 else '#ef553b'
    dsign = '+' if delta >= 0 else ''
    if is_pct:
        curr_str  = f'{curr:.1f}%'
        delta_str = f'{dsign}{delta:.1f}%'
    else:
        curr_str  = f'${curr:,.2f}' if curr >= 0 else f'-${abs(curr):,.2f}'
        delta_str = f'{dsign}${delta:,.2f}' if delta >= 0 else f'-${abs(delta):,.2f}'
    return (
        f'<div style="flex:1;min-width:120px;padding:0 16px;'
        f'border-right:1px solid #1f2937;">'
        f'<div style="color:#6b7280;font-size:0.7rem;text-transform:uppercase;'
        f'letter-spacing:0.05em;margin-bottom:4px;">{label}</div>'
        f'<div style="font-family:monospace;font-size:1.05rem;color:#e6edf3;">{curr_str}</div>'
        f'<div style="font-size:0.78rem;color:{dcol};margin-top:2px;">{delta_str} vs prior</div>'
        f'</div>'
    )

def _dte_chip(a):
    """Inline HTML chip for an expiry alert item."""
    dte = a['dte']
    fg  = '#ef553b' if dte <= 5 else '#ffa500' if dte <= 14 else '#00cc96'
    return (
        f'<span style="display:inline-flex;align-items:center;gap:5px;'
        f'background:rgba(255,255,255,0.04);border:1px solid #1f2937;'
        f'border-radius:6px;padding:3px 10px;margin:2px 4px 2px 0;font-size:0.78rem;">'
        f'<span style="color:{fg};font-family:monospace;font-weight:600;">{dte}d</span>'
        f'<span style="color:#6b7280;">{xe(a["ticker"])}</span>'
        f'<span style="color:#8b949e;font-family:monospace;">{xe(a["label"])}</span>'
        f'</span>'
    )

def _badge_inline_style(strat):
    """Fully inlined CSS string for a strategy badge span."""
    _BASE = (
        'font-size:0.72rem;font-weight:600;padding:3px 10px;border-radius:20px;'
        'text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;'
    )
    _COLORS = {
        'bullish': 'background:rgba(0,204,150,0.1);color:#00cc96;border:1px solid rgba(0,204,150,0.25);',
        'bearish': 'background:rgba(239,85,59,0.1);color:#ef553b;border:1px solid rgba(239,85,59,0.25);',
        'covered': 'background:rgba(255,165,0,0.1);color:#ffa500;border:1px solid rgba(255,165,0,0.25);',
        'default': 'background:rgba(88,166,255,0.12);color:#58a6ff;border:1px solid rgba(88,166,255,0.25);',
    }
    s = strat.lower()
    if any(k in s for k in ['put', 'strangle', 'condor', 'lizard', 'reversal']):
        theme = 'bullish'
    elif any(k in s for k in ['long call', 'bearish']):
        theme = 'bearish'
    elif any(k in s for k in ['covered', 'wheel', 'stock']):
        theme = 'covered'
    else:
        theme = 'default'
    return _BASE + _COLORS[theme]

def render_position_card(ticker, t_df):
    """Build the full HTML card for one open-position ticker."""
    strat       = detect_strategy(t_df)
    badge_style = _badge_inline_style(strat)

    CARD = (
        'background:linear-gradient(135deg,#111827 0%,#0f1520 100%);'
        'border:1px solid #1f2937;border-radius:12px;padding:18px 20px 14px 20px;'
        'margin-bottom:16px;box-shadow:0 2px 12px rgba(0,0,0,0.4);'
    )
    HDR = (
        'display:flex;align-items:center;justify-content:space-between;'
        'margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #1f2937;'
    )
    TICK = (
        'font-family:monospace;font-size:1.3rem;font-weight:600;'
        'color:#f0f6fc;letter-spacing:0.04em;'
    )
    LEG = (
        'display:flex;align-items:flex-start;justify-content:space-between;'
        'padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.05);'
    )
    LBL  = 'color:#8b949e;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:2px;'
    VAL  = 'font-family:monospace;color:#e6edf3;font-size:0.88rem;'
    CHIP = (
        'display:inline-block;margin-top:6px;background:rgba(255,255,255,0.04);'
        'border:1px solid #1f2937;border-radius:6px;padding:3px 10px;'
        'font-family:monospace;font-size:0.8rem;color:#8b949e;'
    )

    legs_html   = ''
    rows_sorted = t_df.sort_values('Status').rename(columns={'Cost Basis': 'Cost_Basis'})
    for i, row in enumerate(rows_sorted.itertuples(index=False)):
        pos_type  = row.Status
        detail    = row.Details
        dte       = row.DTE
        basis     = format_cost_basis(row.Cost_Basis)
        is_last   = (i == len(rows_sorted) - 1)
        leg_style = LEG if not is_last else LEG.replace(
            'border-bottom:1px solid rgba(255,255,255,0.05);', ''
        )

        dte_html = ''
        if dte != 'N/A' and 'd' in str(dte):
            try:
                dte_val   = int(str(dte).replace('d', ''))
                pct       = min(dte_val / 45 * 100, 100)
                bar_color = '#00cc96' if dte_val > 14 else '#ffa500' if dte_val > 5 else '#ef553b'
                dte_html  = (
                    f'<div style="margin-top:6px;">'
                    f'<div style="background:#1f2937;border-radius:4px;height:4px;width:100%;">'
                    f'<div style="width:{pct:.0f}%;background:{bar_color};'
                    f'border-radius:4px;height:4px;"></div>'
                    f'</div>'
                    f'<div style="color:#6b7280;font-size:0.7rem;margin-top:3px;">'
                    f'{dte} to expiry</div>'
                    f'</div>'
                )
            except (ValueError, TypeError):
                pass

        legs_html += (
            f'<div style="{leg_style}">'
            f'  <div>'
            f'    <div style="{LBL}">{xe(pos_type)}</div>'
            f'    <div style="{VAL}">{xe(detail)}</div>'
            f'    {dte_html}'
            f'  </div>'
            f'  <div style="text-align:right;flex-shrink:0;margin-left:12px;">'
            f'    <div style="{LBL}">Basis</div>'
            f'    <div style="{CHIP}">{xe(basis)}</div>'
            f'  </div>'
            f'</div>'
        )

    return (
        f'<div style="{CARD}">'
        f'  <div style="{HDR}">'
        f'    <span style="{TICK}">{xe(ticker)}</span>'
        f'    <span style="{badge_style}">{xe(strat)}</span>'
        f'  </div>'
        f'  {legs_html}'
        f'</div>'
    )
