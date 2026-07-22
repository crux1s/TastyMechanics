"""
TastyMechanics — UI Components
================================
Pure visual helpers: HTML generators, chart layouts, DataFrame stylers.
No business logic or math lives here — these functions only produce
strings, dicts, and style values for rendering.

Dependencies: pandas (for isna / pd.to_datetime), config (for sub-type
constants used in colour lookups).
"""

import html
import pandas as pd
from config import SUB_DIVIDEND, SUB_CREDIT_INT, SUB_DEBIT_INT, WIN_RATE_GREEN, WIN_RATE_ORANGE, DTE_PROGRESS_MAX, DTE_ALERT_WARN, DTE_ALERT_CRIT, COLOURS, get_opt_multiplier, DAILY_THETA_CAP, DAILY_THETA_GREEN, DAILY_THETA_ORANGE
_C = COLOURS  # short alias — avoids quote conflicts in f-strings on Python < 3.12
# is_share_row / is_option_row live in ingestion.py — that is the correct home
# for anything that encodes TastyTrade field values.  Re-exported here so that
# tastymechanics.py can continue to import them from ui_components without change.
from ingestion import is_share_row, is_option_row


# ── XSS safety ────────────────────────────────────────────────────────────────

def xe(s):
    """Escape a string for safe HTML interpolation. Prevents XSS from CSV data."""
    return html.escape(str(s), quote=True)


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
        qty = row['Net_Qty']
        qty_str = str(int(qty)) if qty == int(qty) else f'{round(qty, 4):g}'
        return f'{qty_str} {row["Ticker"]} sh'
    try:
        exp_dt = pd.to_datetime(
            row['Expiration Date'], format='mixed', errors='coerce'
        ).strftime('%d/%m')
    except (ValueError, TypeError, AttributeError):
        exp_dt = 'N/A'
    cp     = 'C' if 'CALL' in str(row['Call or Put']).upper() else 'P'
    action = 'STO' if row['Net_Qty'] < 0 else 'BTO'
    return f'{action} {abs(int(row["Net_Qty"]))} @ {row["Strike Price"]:.0f}{cp} ({exp_dt})'

def format_cost_basis(val):
    """Format a cost-basis value as '$12.34 Cr' or '$12.34 Db'."""
    return f'${abs(val):.2f} {"Cr" if val < 0 else "Db"}'

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
    # Quantity totals — needed to detect ratio legs (e.g. 2 short : 1 long)
    sc_qty = abs(ticker_df[types == 'Short Call']['Net_Qty'].sum())
    lc_qty =     ticker_df[types == 'Long Call' ]['Net_Qty'].sum()
    sp_qty = abs(ticker_df[types == 'Short Put' ]['Net_Qty'].sum())
    lp_qty =     ticker_df[types == 'Long Put'  ]['Net_Qty'].sum()
    strikes = ticker_df['Strike Price'].dropna().unique()
    exps    = ticker_df['Expiration Date'].dropna().unique()
    if lc > 0 and sc > 0 and len(exps) >= 2 and len(strikes) == 1: return 'Calendar Spread'
    if lp > 0 and sp > 0 and len(exps) >= 2 and len(strikes) == 1: return 'Calendar Spread'
    # Butterfly: 2 longs + 1 short, 3 strikes, 1 expiry AND short strike must be the middle strike
    # Butterfly detection requires an options-only structure (ls == 0): a
    # butterfly held against stock is really a covered / ratio structure and
    # must fall through to those checks below.  The body leg must also sit on
    # the MIDDLE of the 3 strikes — without that guard, a covered call plus an
    # unrelated call spread (e.g. long 70 / short 75 / short 90 + 100 shares)
    # would satisfy the bare leg-count test and mislabel as a Short Butterfly.
    # Long Butterfly: 2 long wings + 1 short body, short body on the middle strike.
    if ls == 0 and lc == 2 and sc == 1 and len(strikes) == 3 and len(exps) == 1:
        _sc_strikes = ticker_df[types == 'Short Call']['Strike Price'].dropna()
        if not _sc_strikes.empty and sorted(strikes)[0] < _sc_strikes.iloc[0] < sorted(strikes)[-1]:
            return 'Long Call Butterfly'
    if ls == 0 and lp == 2 and sp == 1 and len(strikes) == 3 and len(exps) == 1:
        _sp_strikes = ticker_df[types == 'Short Put']['Strike Price'].dropna()
        if not _sp_strikes.empty and sorted(strikes)[0] < _sp_strikes.iloc[0] < sorted(strikes)[-1]:
            return 'Long Put Butterfly'
    # Short Butterfly: 1 long body (qty 2) + 2 short wings, long body on the middle strike.
    if ls == 0 and lc == 1 and sc == 2 and len(strikes) == 3 and len(exps) == 1:
        _lc_strikes = ticker_df[types == 'Long Call']['Strike Price'].dropna()
        if not _lc_strikes.empty and sorted(strikes)[0] < _lc_strikes.iloc[0] < sorted(strikes)[-1]:
            return 'Short Call Butterfly'
    if ls == 0 and lp == 1 and sp == 2 and len(strikes) == 3 and len(exps) == 1:
        _lp_strikes = ticker_df[types == 'Long Put']['Strike Price'].dropna()
        if not _lp_strikes.empty and sorted(strikes)[0] < _lp_strikes.iloc[0] < sorted(strikes)[-1]:
            return 'Short Put Butterfly'
    if ls > 0 and sc > 0 and sp > 0: return 'Covered Strangle'
    # Covered ratio spread: stock + more short calls/puts than long calls/puts
    if ls > 0 and sc > 0 and lc > 0 and sc_qty > lc_qty and sp == 0 and lp == 0:
        return 'Covered Call Ratio Spread'
    if ls > 0 and sp > 0 and lp > 0 and sp_qty > lp_qty and sc == 0 and lc == 0:
        return 'Covered Put Ratio Spread'
    if ls > 0 and sc > 0:            return 'Covered Call'
    # Four-leg condor/butterfly structures — must precede Jade Lizard/Big Lizard
    # because those checks are subsets that would fire on the same legs.
    if sc >= 1 and lc >= 1 and sp >= 1 and lp >= 1 and len(exps) == 1:
        _sc_str = ticker_df[types == 'Short Call']['Strike Price'].dropna()
        _lc_str = ticker_df[types == 'Long Call']['Strike Price'].dropna()
        _sp_str = ticker_df[types == 'Short Put']['Strike Price'].dropna()
        _lp_str = ticker_df[types == 'Long Put']['Strike Price'].dropna()
        if not (_sc_str.empty or _lc_str.empty or _sp_str.empty or _lp_str.empty):
            _net = ticker_df['Cost Basis'].sum() if 'Cost Basis' in ticker_df.columns else 0.0
            # Iron/Reverse Iron Butterfly: short (or long) legs share the ATM strike
            if _sc_str.iloc[0] == _sp_str.iloc[0]:
                return 'Iron Butterfly'
            elif _lc_str.iloc[0] == _lp_str.iloc[0]:
                return 'Reverse Iron Butterfly'
            # Iron Condor: 4 distinct strikes, net credit; Reverse: net debit
            elif _net < 0:
                return 'Iron Condor'
            else:
                return 'Reverse Iron Condor'
    if sp >= 1 and sc >= 1 and lc >= 1: return 'Jade Lizard'
    if sc >= 1 and sp >= 1 and lp >= 1: return 'Big Lizard'
    if sc >= 1 and sp >= 1:             return 'Short Strangle'
    if lc >= 1 and sp >= 1:             return 'Risk Reversal'
    # Ratio spreads — must precede vertical spread checks (same legs, different qty)
    if sc > 0 and lc > 0 and sc_qty > lc_qty and sp == 0 and lp == 0:
        return 'Call Ratio Spread'
    if sp > 0 and lp > 0 and sp_qty > lp_qty and sc == 0 and lc == 0:
        return 'Put Ratio Spread'
    # Vertical call spread: at least 1 long + 1 short call, same expiry, no puts
    if lc >= 1 and sc >= 1 and sp == 0 and lp == 0 and len(exps) == 1:
        _sc_str = ticker_df[types == 'Short Call']['Strike Price'].dropna()
        _lc_str = ticker_df[types == 'Long Call']['Strike Price'].dropna()
        if not _sc_str.empty and not _lc_str.empty:
            return 'Call Credit Spread' if _sc_str.min() < _lc_str.min() else 'Call Debit Spread'
    # Vertical put spread: at least 1 long + 1 short put, same expiry, no calls
    if lp >= 1 and sp >= 1 and sc == 0 and lc == 0 and len(exps) == 1:
        _sp_str = ticker_df[types == 'Short Put']['Strike Price'].dropna()
        _lp_str = ticker_df[types == 'Long Put']['Strike Price'].dropna()
        if not _sp_str.empty and not _lp_str.empty:
            return 'Put Credit Spread' if _sp_str.min() > _lp_str.min() else 'Put Debit Spread'
    # Single-leg fallbacks fire only when the position is that leg-type ALONE.
    # A heterogeneous leftover that matched no named structure above (e.g. a
    # diagonal, or stock plus unmatched long options) is genuinely unclassifiable
    # — return Custom/Mixed rather than labelling it by one leg and hiding the rest.
    if sp > 0  and sc == 0 and lc == 0 and lp == 0 and ls == 0: return 'Short Put'
    if sc > 0  and sp == 0 and lc == 0 and lp == 0 and ls == 0: return 'Short Call'
    if lc == 1 and sc == 0 and sp == 0 and lp == 0 and ls == 0: return 'Long Call'
    if lp == 1 and sc == 0 and sp == 0 and lc == 0 and ls == 0: return 'Long Put'
    if ls > 0  and sc == 0 and lc == 0 and sp == 0 and lp == 0: return 'Long Stock'
    return 'Custom/Mixed'


# ── DataFrame stylers ─────────────────────────────────────────────────────────

def color_win_rate(v):
    """Green / amber / red for win-rate cells in st.dataframe."""
    if not isinstance(v, (int, float)) or pd.isna(v): return ''
    if v >= WIN_RATE_GREEN:  return 'color: ' + COLOURS['green'] + '; font-weight: bold'
    if v >= WIN_RATE_ORANGE: return 'color: ' + COLOURS['orange']
    return 'color: ' + COLOURS['red']

def color_pnl_cell(val):
    """Green/red colouring for P/L columns in st.dataframe."""
    if not isinstance(val, (int, float)) or pd.isna(val): return ''
    return 'color: ' + COLOURS['green'] if val > 0 else 'color: ' + COLOURS['red'] if val < 0 else ''

def color_daily_theta(val):
    """Green/orange/red colouring for Daily θ % cells in st.dataframe."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return ''
    if v >= DAILY_THETA_GREEN:  return 'color: ' + COLOURS['green']
    if v >= DAILY_THETA_ORANGE: return 'color: ' + COLOURS['orange']
    return 'color: ' + COLOURS['red']

def _fmt_ann_ret(row):
    """Format Ann Ret % cell — appends * for trades held < 4 days."""
    v = row['Ann Ret %']
    if pd.isna(v):
        return '—'
    _days = row.get('Days in Trade', row.get('Days Held'))
    suffix = '*' if pd.notna(_days) and _days < 4 else ''
    return '{:.0f}%{}'.format(v, suffix)

def _style_ann_ret(row):
    """Row-level style: dim Ann Ret % for very short-hold trades."""
    styles = [''] * len(row)
    try:
        idx = list(row.index).index('Ann Ret %')
        _days = row.get('Days in Trade', row.get('Days Held', 99))
        if pd.notna(_days) and _days < 4:
            styles[idx] = 'color: ' + COLOURS['tan']
    except (ValueError, KeyError):
        pass  # 'Ann Ret %' column absent in this table variant — safe to skip
    return styles

def _fmt_daily_theta(row):
    """Format Daily θ % cell — appends * for trades held < 4 days, ⚠ at cap."""
    v = row.get('Daily θ %')
    if v is None or pd.isna(v):
        return '—'
    _days = row.get('Days in Trade', row.get('Days Held'))
    suffix = '*' if pd.notna(_days) and _days < 4 else ''
    cap_marker = '⚠ ' if v >= DAILY_THETA_CAP else ''
    return '{}{:.2f}%{}'.format(cap_marker, v, suffix)

def _style_daily_theta(row):
    """Row-level style: colour Daily θ % green/orange/red by entry quality threshold."""
    styles = [''] * len(row)
    try:
        idx = list(row.index).index('Daily θ %')
        raw = row['Daily θ %']
        # column may already be a formatted string from _fmt_daily_theta
        if isinstance(raw, str):
            s = raw.replace('⚠ ', '').rstrip('*').rstrip('%').strip()
            if s == '—':
                return styles
            v = float(s)
        elif pd.isna(raw):
            return styles
        else:
            v = float(raw)
        if v >= DAILY_THETA_GREEN:
            styles[idx] = 'color: ' + COLOURS['green']
        elif v >= DAILY_THETA_ORANGE:
            styles[idx] = 'color: ' + COLOURS['orange']
        else:
            styles[idx] = 'color: ' + COLOURS['red']
    except (ValueError, KeyError):
        pass
    return styles

def _style_chain_row(row):
    """Highlight open leg and alternate pair tints in a roll-chain detail table."""
    if row.get('_open', False):
        return ['background-color: rgba(0,204,150,0.12); font-weight:600'] * len(row)  # COLOURS['green'] @ 12% opacity
    pair = row.get('_pair', -1)
    if pair < 0:
        return [''] * len(row)
    if pair % 2 == 0:
        return ['background-color: rgba(88,166,255,0.09)'] * len(row)   # COLOURS['blue'] @ 9% opacity
    return ['background-color: rgba(150,110,255,0.09)'] * len(row)       # purple @ 9% opacity

def _style_risk_row(row):
    """Tint defined-risk rows blue, undefined-risk rows orange in the strategy table."""
    risk = row.get('_risk', None)
    if risk is True:
        return ['background-color: rgba(88,166,255,0.09)'] * len(row)   # COLOURS['blue'] @ 9%
    if risk is False:
        return ['background-color: rgba(255,165,0,0.08)'] * len(row)    # COLOURS['orange'] @ 8%
    return [''] * len(row)

def _color_cash_row(row):
    """Row background tint for the Deposits/Dividends table."""
    sub = str(row.get('Sub Type', ''))
    _g = COLOURS['green']; _r = COLOURS['red']
    _b = COLOURS['blue'];  _o = COLOURS['orange']
    tints = {
        'Deposit':            f'rgba({int(_g[1:3],16)},{int(_g[3:5],16)},{int(_g[5:7],16)},0.08)',
        'Withdrawal':         f'rgba({int(_r[1:3],16)},{int(_r[3:5],16)},{int(_r[5:7],16)},0.08)',
        SUB_DIVIDEND:         f'rgba({int(_b[1:3],16)},{int(_b[3:5],16)},{int(_b[5:7],16)},0.08)',
        SUB_CREDIT_INT:       f'rgba({int(_b[1:3],16)},{int(_b[3:5],16)},{int(_b[5:7],16)},0.05)',
        SUB_DEBIT_INT:        f'rgba({int(_r[1:3],16)},{int(_r[3:5],16)},{int(_r[5:7],16)},0.05)',
        'Balance Adjustment': f'rgba({int(_o[1:3],16)},{int(_o[3:5],16)},{int(_o[5:7],16)},0.07)',
    }
    c = tints.get(sub, '')
    return [f'background-color:{c}' if c else ''] * len(row)

def _color_cash_total(val):
    """Green/red for the Total column in the cash-flow table."""
    if not isinstance(val, (int, float)): return ''
    return 'color:' + COLOURS['green'] if val > 0 else 'color:' + COLOURS['red'] if val < 0 else ''


# ── Plotly chart layout ───────────────────────────────────────────────────────

def chart_layout(title='', height=300, margin_t=36, margin_b=20):
    """Consistent base layout dict for all Plotly charts."""
    return dict(
        template='plotly_dark',
        height=height,
        paper_bgcolor='rgba(10,14,23,0)',
        plot_bgcolor='rgba(10,14,23,0)',
        font=dict(family='IBM Plex Sans, sans-serif', size=12, color=COLOURS['text_muted']),
        title=dict(
            text=title,
            font=dict(size=13, color=COLOURS['header_text'], family='IBM Plex Sans'),
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
    col  = COLOURS['green'] if val >= 0 else COLOURS['red']
    sign = '+' if val >= 0 else ''
    _bdr = COLOURS['border']; _dim = COLOURS['text_dim']
    return (
        f'<span style="display:inline-flex;align-items:center;gap:5px;'
        f'background:rgba(255,255,255,0.04);border:1px solid {_bdr};'
        f'border-radius:6px;padding:3px 10px;margin:2px 4px 2px 0;font-size:0.78rem;">'
        f'<span style="color:{_dim};">{label}</span>'
        f'<span style="color:{col};font-family:monospace;font-weight:600;">'
        f'{sign}${abs(val):,.2f}</span>'
        f'</span>'
    )

def _cmp_block(label, curr, prev, is_pct=False):
    """One column block in the period-comparison card."""
    delta = curr - prev
    dcol  = COLOURS['green'] if delta >= 0 else COLOURS['red']
    dsign = '+' if delta >= 0 else ''
    if is_pct:
        curr_str  = f'{curr:.1f}%'
        delta_str = f'{dsign}{delta:.1f}%'
    else:
        curr_str  = f'${curr:,.2f}' if curr >= 0 else f'-${abs(curr):,.2f}'
        delta_str = f'{dsign}${delta:,.2f}' if delta >= 0 else f'-${abs(delta):,.2f}'
    _bdr = COLOURS['border']; _dim = COLOURS['text_dim']; _txt = COLOURS['text']
    return (
        '<div style="flex:1;min-width:120px;padding:0 16px;'
        'border-right:1px solid ' + _bdr + ';">'
        '<div style="color:' + _dim + ';font-size:0.7rem;text-transform:uppercase;'
        'letter-spacing:0.05em;margin-bottom:4px;">' + label + '</div>'
        '<div style="font-family:monospace;font-size:1.05rem;color:' + _txt + ';">' + curr_str + '</div>'
        '<div style="font-size:0.78rem;color:' + dcol + ';margin-top:2px;">' + delta_str + ' vs prior</div>'
        '</div>'
    )

def _dte_chip(a):
    """Inline HTML chip for an expiry alert item."""
    dte = a['dte']
    fg  = COLOURS['red'] if dte <= DTE_ALERT_CRIT else COLOURS['orange'] if dte <= DTE_ALERT_WARN else COLOURS['green']
    _bdr = COLOURS['border']; _dim = COLOURS['text_dim']; _mut = COLOURS['text_muted']
    return (
        '<span style="display:inline-flex;align-items:center;gap:5px;'
        'background:rgba(255,255,255,0.04);border:1px solid ' + _bdr + ';'
        'border-radius:6px;padding:3px 10px;margin:2px 4px 2px 0;font-size:0.78rem;">'
        '<span style="color:' + fg + ';font-family:monospace;font-weight:600;">' + str(dte) + 'd</span>'
        '<span style="color:' + _dim + ';">' + xe(a['ticker']) + '</span>'
        '<span style="color:' + _mut + ';font-family:monospace;">' + xe(a['label']) + '</span>'
        '</span>'
    )

def _badge_inline_style(strat):
    """Fully inlined CSS string for a strategy badge span."""
    _BASE = (
        'font-size:0.72rem;font-weight:600;padding:3px 10px;border-radius:20px;'
        'text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;'
    )
    _g = COLOURS['green']; _r = COLOURS['red']; _o = COLOURS['orange']; _b = COLOURS['blue']
    _COLORS = {
        'bullish': 'background:rgba(0,204,150,0.1);color:' + _g + ';border:1px solid rgba(0,204,150,0.25);',
        'bearish': 'background:rgba(239,85,59,0.1);color:'  + _r + ';border:1px solid rgba(239,85,59,0.25);',
        'covered': 'background:rgba(255,165,0,0.1);color:'  + _o + ';border:1px solid rgba(255,165,0,0.25);',
        'default': 'background:rgba(88,166,255,0.12);color:'+ _b + ';border:1px solid rgba(88,166,255,0.25);',
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

def render_position_card(ticker, t_df, ticker_live=None):
    """Build the full HTML card for one open-position ticker.

    ticker_live — optional dict from market_data.fetch_live_prices, keyed by ticker:
        {'last': float, 'prev_close': float,
         'options': {(expiry_original_str, strike, cp): {'bid', 'ask', 'mark'}}}
    When provided, each leg gains a live price / mark and unrealised P/L display.
    """
    strat       = detect_strategy(t_df)
    badge_style = _badge_inline_style(strat)

    _bg1 = COLOURS['card_bg']; _bg2 = COLOURS['card_bg2']
    _bdr = COLOURS['border'];   _wht = COLOURS['white']
    _mut = COLOURS['text_muted']; _txt = COLOURS['text']
    _grn = COLOURS['green'];    _red = COLOURS['red']
    _dim = COLOURS['text_dim']
    CARD = (
        'background:linear-gradient(135deg,' + _bg1 + ' 0%,' + _bg2 + ' 100%);'
        'border:1px solid ' + _bdr + ';border-radius:12px;padding:18px 20px 14px 20px;'
        'margin-bottom:16px;box-shadow:0 2px 12px rgba(0,0,0,0.4);'
    )
    HDR = (
        'display:flex;align-items:center;justify-content:space-between;'
        'margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid ' + _bdr + ';'
    )
    TICK = (
        'font-family:monospace;font-size:1.3rem;font-weight:600;'
        'color:' + _wht + ';letter-spacing:0.04em;'
    )
    LEG = (
        'display:flex;align-items:flex-start;justify-content:space-between;'
        'padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.05);'
    )
    LBL  = 'color:' + _mut + ';font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:2px;'
    VAL  = 'font-family:monospace;color:' + _txt + ';font-size:0.88rem;'
    CHIP = (
        'display:inline-block;margin-top:6px;background:rgba(255,255,255,0.04);'
        'border:1px solid ' + _bdr + ';border-radius:6px;padding:3px 10px;'
        'font-family:monospace;font-size:0.8rem;color:' + _mut + ';'
    )

    # ── Spread context pre-computation ────────────────────────────────────────
    _is_spread      = 'Spread' in strat
    _is_cr_spread   = _is_spread and 'Credit' in strat
    _is_db_spread   = _is_spread and 'Debit'  in strat
    _spread_net_basis = float(t_df['Cost Basis'].sum()) if _is_spread else 0.0
    _spread_strikes   = t_df['Strike Price'].dropna() if _is_spread else pd.Series(dtype=float)
    _inst_type        = t_df['Instrument Type'].iloc[0] if not t_df.empty else 'Equity Option'
    _opt_mult         = get_opt_multiplier(ticker, _inst_type)
    _spread_width     = (
        (_spread_strikes.max() - _spread_strikes.min()) * _opt_mult
        if _is_spread and len(_spread_strikes) >= 2 else 0.0
    )

    legs_html   = ''
    total_unreal: float | None = None
    _live_legs_found = 0  # count of legs that actually received a live mark
    rows_sorted = t_df.sort_values('Status').rename(columns={
        'Cost Basis':     'Cost_Basis',
        'Expiration Date': 'Expiration_Date',
        'Strike Price':    'Strike_Price',
        'Call or Put':     'Call_or_Put',
    })
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
                pct       = min(dte_val / DTE_PROGRESS_MAX * 100, 100)
                bar_color = COLOURS['green'] if dte_val > DTE_ALERT_WARN else COLOURS['orange'] if dte_val > DTE_ALERT_CRIT else COLOURS['red']
                dte_html  = (
                    '<div style="margin-top:6px;">'
                    '<div style="background:' + _bdr + ';border-radius:4px;height:4px;width:100%;">'
                    '<div style="width:' + f'{pct:.0f}' + '%;background:' + bar_color + ';'
                    'border-radius:4px;height:4px;"></div>'
                    '</div>'
                    '<div style="color:' + _dim + ';font-size:0.7rem;margin-top:3px;">'
                    + str(dte) + ' to expiry</div>'
                    '</div>'
                )
            except (ValueError, TypeError):
                pass  # DTE string is non-numeric (e.g. 'N/A') — leave progress bar absent

        # ── Live price section ─────────────────────────────────────────────
        live_html = ''
        if ticker_live:
            is_equity = 'stock' in str(pos_type).lower()
            if is_equity and ticker_live.get('last', 0.0):
                last  = ticker_live['last']
                prev  = ticker_live.get('prev_close', last)
                chg   = last - prev
                chg_pct = (chg / prev * 100) if prev else 0.0
                chg_col = _grn if chg >= 0 else _red
                chg_sgn = '+' if chg >= 0 else ''
                qty   = float(getattr(row, 'Net_Qty', 0))
                unreal = last * qty - float(row.Cost_Basis)
                total_unreal = (total_unreal or 0.0) + unreal
                _live_legs_found += 1
                u_col = _grn if unreal >= 0 else _red
                u_sgn = '+' if unreal >= 0 else '-'
                ps_str = (
                    f' <span style="color:{_dim};">({u_sgn}${abs(unreal / qty):,.2f}/sh)</span>'
                    if qty else ''
                )
                live_html = (
                    f'<div style="margin-top:6px;font-size:0.75rem;">'
                    f'<span style="color:{_mut};">Last </span>'
                    f'<span style="font-family:monospace;color:{_txt};">${last:,.2f}</span>'
                    f'<span style="color:{chg_col};margin-left:6px;">{chg_sgn}{chg_pct:.2f}%</span>'
                    f'<span style="display:block;color:{u_col};font-family:monospace;margin-top:2px;">'
                    f'Unreal {u_sgn}${abs(unreal):,.2f}{ps_str}</span>'
                    f'</div>'
                )
            elif not is_equity:
                expiry = str(getattr(row, 'Expiration_Date', ''))
                strike = float(getattr(row, 'Strike_Price', 0.0))
                cp     = str(getattr(row, 'Call_or_Put', '')).upper()
                opt_data = ticker_live.get('options', {}).get((expiry, strike, cp))
                if not opt_data:
                    live_html = (
                        f'<div style="margin-top:4px;font-size:0.7rem;color:{_dim};">'
                        f'Mark — (no data)</div>'
                    )
                if opt_data:
                    mark  = opt_data['mark']
                    bid   = opt_data['bid']
                    ask   = opt_data['ask']
                    qty   = float(getattr(row, 'Net_Qty', 0))
                    cost  = float(row.Cost_Basis)
                    unreal = mark * qty * 100 - cost
                    total_unreal = (total_unreal or 0.0) + unreal
                    _live_legs_found += 1
                    u_col = _grn if unreal >= 0 else _red
                    u_sgn = '+' if unreal >= 0 else '-'
                    # % of premium captured — only for single-leg credit trades
                    # (spreads get a combined % in the footer instead)
                    pct_str = ''
                    if not _is_spread and cost < 0 and abs(cost) > 0:
                        pct = unreal / abs(cost) * 100
                        pct_str = (
                            f' <span style="color:{_dim};">({pct:.0f}% captured)</span>'
                        )
                    live_html = (
                        f'<div style="margin-top:6px;font-size:0.75rem;">'
                        f'<span style="color:{_mut};">Mark </span>'
                        f'<span style="font-family:monospace;color:{_txt};">${mark:.2f}</span>'
                        f'<span style="color:{_dim};margin-left:6px;">'
                        f'${bid:.2f} / ${ask:.2f}</span>'
                        f'<span style="display:block;color:{u_col};font-family:monospace;margin-top:2px;">'
                        f'Unreal {u_sgn}${abs(unreal):,.2f}{pct_str}</span>'
                        f'</div>'
                    )

        legs_html += (
            f'<div style="{leg_style}">'
            f'  <div>'
            f'    <div style="{LBL}">{xe(pos_type)}</div>'
            f'    <div style="{VAL}">{xe(detail)}</div>'
            f'    {dte_html}'
            f'    {live_html}'
            f'  </div>'
            f'  <div style="text-align:right;flex-shrink:0;margin-left:12px;">'
            f'    <div style="{LBL}">Basis</div>'
            f'    <div style="{CHIP}">{xe(basis)}</div>'
            f'  </div>'
            f'</div>'
        )

    # ── Spread context row (credit/debit, max profit/loss, % of max) ─────────
    spread_ctx_html = ''
    if _is_spread and total_unreal is not None and _spread_width > 0:
        if _is_cr_spread and _spread_net_basis < 0:
            net_cr   = abs(_spread_net_basis)
            max_loss = max(_spread_width - net_cr, 0)
            pct_max  = (total_unreal / net_cr * 100) if net_cr > 0 else 0.0
            p_col    = _grn if pct_max >= 50 else _mut
            spread_ctx_html = (
                f'<div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.05);'
                f'font-size:0.72rem;display:flex;gap:14px;flex-wrap:wrap;">'
                f'<span style="color:{_mut};">Net cr '
                f'<span style="font-family:monospace;color:{_txt};">${net_cr:.2f}</span></span>'
                f'<span style="color:{_mut};">Max loss '
                f'<span style="font-family:monospace;color:{_red};">${max_loss:.2f}</span></span>'
                f'<span style="color:{_mut};">% of max '
                f'<span style="font-family:monospace;color:{p_col};">{pct_max:.0f}%</span></span>'
                f'</div>'
            )
        elif _is_db_spread and _spread_net_basis > 0:
            net_db     = _spread_net_basis
            max_profit = max(_spread_width - net_db, 0)
            pct_loss   = (abs(total_unreal) / net_db * 100) if net_db > 0 else 0.0
            spread_ctx_html = (
                f'<div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.05);'
                f'font-size:0.72rem;display:flex;gap:14px;flex-wrap:wrap;">'
                f'<span style="color:{_mut};">Net db '
                f'<span style="font-family:monospace;color:{_txt};">${net_db:.2f}</span></span>'
                f'<span style="color:{_mut};">Max profit '
                f'<span style="font-family:monospace;color:{_grn};">${max_profit:.2f}</span></span>'
                f'<span style="color:{_mut};">% at risk '
                f'<span style="font-family:monospace;color:{_mut};">{pct_loss:.0f}%</span></span>'
                f'</div>'
            )

    # ── Total unrealised P/L footer (only when live prices are active) ─────
    footer_html = ''
    if total_unreal is not None:
        f_col = _grn if total_unreal >= 0 else _red
        f_sgn = '+' if total_unreal >= 0 else '-'
        footer_html = (
            f'<div style="margin-top:10px;padding-top:8px;border-top:1px solid {_bdr};'
            f'display:flex;justify-content:space-between;align-items:center;">'
            f'<span style="color:{_mut};font-size:0.72rem;text-transform:uppercase;'
            f'letter-spacing:0.04em;">Unrealised P/L</span>'
            f'<span style="font-family:monospace;font-size:0.95rem;font-weight:600;'
            f'color:{f_col};">{f_sgn}${abs(total_unreal):,.2f}</span>'
            f'</div>'
        )

    # ── Equity last-price header pill (only when live prices are active) ───
    live_hdr_html = ''
    if ticker_live and ticker_live.get('last', 0.0):
        last = ticker_live['last']
        prev = ticker_live.get('prev_close', last)
        chg  = last - prev
        chg_col = _grn if chg >= 0 else _red
        chg_sgn = '+' if chg >= 0 else ''
        live_hdr_html = (
            f'<span style="font-family:monospace;font-size:0.82rem;color:{_txt};">'
            f'${last:,.2f} '
            f'<span style="color:{chg_col};">{chg_sgn}{chg:.2f}</span>'
            f'</span>'
        )

    return (
        f'<div style="{CARD}">'
        f'  <div style="{HDR}">'
        f'    <span style="{TICK}">{xe(ticker)}</span>'
        f'    <div style="display:flex;align-items:center;gap:10px;">'
        f'      {live_hdr_html}'
        f'      <span style="{badge_style}">{xe(strat)}</span>'
        f'    </div>'
        f'  </div>'
        f'  {legs_html}'
        f'  {spread_ctx_html}'
        f'  {footer_html}'
        f'</div>'
    )
