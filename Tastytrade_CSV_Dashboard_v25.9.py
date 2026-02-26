import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional, NamedTuple
import html as _html
import io as _io
import json as _json
import os as _os

# ==========================================
# TastyMechanics v25.9
# ==========================================
#
# Changelog
# ---------
# v25.9 (2026-02-26)
#   - FIX: Assignment STO double-count — pre-purchase option that caused a
#     put assignment was being counted in both campaign premiums AND the
#     outside-window P/L bucket. Fixed: assignment STO stays solely in the
#     outside-window bucket. Verified against real account data.
#   - FIX: Windowed P/L and All Time P/L both missing dividends and interest.
#     Income now included in both window_realized_pnl and total_realized_pnl.
#   - FIX: Standalone ticker equity P/L replaced cash-flow approximation with
#     proper FIFO engine — correct for accounts with open equity positions.
#   - FIX: option_mask() typo introduced in v25.7 refactor (wrong function name
#     and wrong DataFrame at two call sites).
#   - TEST: 180-test suite (test_tastymechanics.py) added. All P/L figures,
#     campaign accounting, windowed views, and edge cases verified against
#     independently computed ground truth from raw CSV data.
#
# v25.8 (2026-02-26)
#   - REFACTOR: load_and_parse() returns ParsedData NamedTuple.
#     detect_corporate_actions() now runs exactly once.
#   - REFACTOR: equity_mask() / option_mask() vectorised helpers replace
#     scattered .str.strip() comparisons throughout.
#   - REFACTOR: AppData dataclass confirmed clean; all dict access migrated
#     to attribute access.
#
# v25.6 (2026-02-26)
#   - FIX: Stock splits (forward and reverse) handled end-to-end. Pre-split
#     lot sizes rescaled in FIFO engine; split REMOVAL rows no longer trigger
#     false P/L or duplicate campaigns. Warning banner shown at load time.
#   - FIX: Zero-cost share deliveries (spin-offs, ACATS transfers) flagged
#     with an amber warning noting the $0 basis will overstate P/L on sale.
#   - FIX: Timezone architecture unified — single UTC conversion in
#     load_and_parse(), naive datetimes everywhere downstream.
#   - FIX: Short equity FIFO — buy-to-cover now correctly matches the
#     originating short lot instead of treating proceeds as costless gain.
#   - FIX: Naked long options (LEAPS) no longer mislabelled as debit spreads.
#   - FIX: LEAPS excluded from ThetaGang DTE metrics (DTE > 90 threshold).
#   - FIX: Weekly bar chart hover negative formatting.
#   - REFACTOR: AppData dataclass, _iter_fifo_sells() shared FIFO core,
#     APP_VERSION constant, XSS prevention via xe() helper.
#
# v25.4 (2026-02-24)
#   - FIX: Pre-purchase options no longer credited to campaign effective basis.
#     Real impact: SMR basis corrected from $16.72 → $20.25/share.
#   - FIX: Prior period P/L double-counting.
#   - FIX: CSV validation, negative currency formatting, trade log date sort.
#   - NEW: How Closed column (Expired / Assigned / Exercised / Closed).
#   - NEW: Total Realized P/L by Week & Month charts.
#   - NEW: Window date label on all section headers.
#
# v25.3 (2026-02-23)
#   - NEW: Expiry alert strip (21-day lookahead, colour-coded urgency).
#   - NEW: Period comparison card (current vs prior window with deltas).
#   - NEW: Weekly / Monthly P/L bar charts.
#   - NEW: Open Positions card grid with strategy badges and DTE progress bars.
#   - UI: IBM Plex Sans + Mono typography, dark theme (#0a0e17).
# ==========================================

APP_VERSION = "v25.9"
st.set_page_config(page_title=f"TastyMechanics {APP_VERSION}", layout="wide")
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

    .stApp { background-color: #0a0e17; color: #c9d1d9; font-family: 'IBM Plex Sans', sans-serif; }
    div[data-testid="stMetricValue"] { font-size: 1.4rem !important; color: #00cc96; font-family: 'IBM Plex Mono', monospace; font-weight: 600; }
    div[data-testid="stMetricLabel"] { color: #8b949e; font-size: 0.78rem !important; text-transform: uppercase; letter-spacing: 0.05em; }
    div[data-testid="stMetricDelta"] { font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem !important; }
    .stTable { font-size: 0.85rem !important; }
    [data-testid="stExpander"] { background: #111827; border-radius: 10px;
        border: 1px solid #1f2937; margin-bottom: 8px; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; border-bottom: 1px solid #1f2937; }
    .stTabs [data-baseweb="tab"] { background-color: #0f1520;
        border-radius: 6px 6px 0px 0px; padding: 10px 20px; font-size: 0.9rem; }
    .sync-header { color: #8b949e; font-size: 0.9rem;
        margin-top: -15px; margin-bottom: 25px; line-height: 1.5; }
    .highlight-range { color: #58a6ff; font-weight: 600; }

    /* Position cards and chart section titles use fully inline styles
       generated by render_position_card() and _badge_inline_style() —
       no CSS classes needed here. */
    </style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
# TastyTrade instrument type strings
OPT_TYPES        = ['Equity Option', 'Future Option']
EQUITY_TYPE      = 'Equity'

# TastyTrade transaction type strings
TRADE_TYPES      = ['Trade', 'Receive Deliver']
MONEY_TYPES      = ['Trade', 'Receive Deliver', 'Money Movement']

# TastyTrade sub-type strings (used as exact-match values)
SUB_SELL_OPEN    = 'sell to open'
SUB_ASSIGNMENT   = 'assignment'
SUB_DIVIDEND     = 'Dividend'
SUB_CREDIT_INT   = 'Credit Interest'
SUB_DEBIT_INT    = 'Debit Interest'
INCOME_SUB_TYPES = [SUB_DIVIDEND, SUB_CREDIT_INT, SUB_DEBIT_INT]
DEPOSIT_SUB_TYPES= ['Deposit', 'Withdrawal', SUB_DIVIDEND, SUB_CREDIT_INT, SUB_DEBIT_INT, 'Balance Adjustment']

# Sub-type pattern fragments (for .str.contains() matching)
PAT_CLOSE        = 'to close'
PAT_EXPIR        = 'expir'
PAT_ASSIGN       = 'assign'
PAT_EXERCISE     = 'exercise'
PAT_CLOSING      = f'{PAT_CLOSE}|{PAT_EXPIR}|{PAT_ASSIGN}|{PAT_EXERCISE}'

# Wheel strategy
WHEEL_MIN_SHARES = 100

# Index option detection
# Strikes above this threshold are treated as index underlyings (SPX, NDX, RUT, VIX etc.)
# rather than equity options. Used in capital_risk calculation for naked shorts:
# equity options use strike × 100 (theoretical max loss); index options use premium
# received (margin-based, since "underlying to zero" is not a realistic scenario).
# $500 sits safely above the highest-priced equity options (BRK.A aside) and well
# below the lowest common index strike (RUT ~2000, SPX ~5000, NDX ~20000).
INDEX_STRIKE_THRESHOLD = 500

# Corporate action detection
# TastyTrade Description field patterns for stock splits and zero-cost deliveries.
SPLIT_DSC_PATTERNS   = ['FORWARD SPLIT', 'REVERSE SPLIT', 'STOCK SPLIT', 'SPLIT']
ZERO_COST_WARN_TYPES = ['SPINOFF', 'SPIN-OFF', 'SPIN OFF', 'TRANSFER',
                        'ACATS', 'MERGER', 'ACQUISITION', 'RIGHTS', 'WARRANT']

# CSV validation
REQUIRED_COLUMNS = {
    'Date', 'Action', 'Description', 'Type', 'Sub Type',
    'Instrument Type', 'Symbol', 'Underlying Symbol',
    'Quantity', 'Total', 'Commissions', 'Fees',
    'Strike Price', 'Call or Put', 'Expiration Date', 'Root Symbol', 'Order #',
}

# ── helpers ───────────────────────────────────────────────────────────────────
def xe(s):
    """Escape a string for safe HTML interpolation. Prevents XSS from CSV data."""
    return _html.escape(str(s), quote=True)

def color_win_rate(v):
    if not isinstance(v, (int, float)) or pd.isna(v): return ''
    if v >= 70:   return 'color: #00cc96; font-weight: bold'
    if v >= 50:   return 'color: #ffa500'
    return 'color: #ef553b'

def clean_val(val):
    if pd.isna(val) or val == '--': return 0.0
    return float(str(val).replace('$', '').replace(',', ''))

def get_signed_qty(row):
    act = str(row['Action']).upper()
    dsc = str(row['Description']).upper()
    qty = row['Quantity']
    if 'BUY' in act or 'BOUGHT' in dsc:  return  qty
    if 'SELL' in act or 'SOLD' in dsc:   return -qty
    if 'REMOVAL' in dsc:
        if 'ASSIGNMENT' in dsc: return qty
        # Split removals must NOT be treated as sales — the quantity change
        # is handled by apply_split_adjustments() in load_and_parse().
        if any(p in dsc for p in SPLIT_DSC_PATTERNS): return 0
        return -qty
    return 0

def is_share_row(inst):  return str(inst).strip() == 'Equity'
def is_option_row(inst): return 'Option' in str(inst)

def equity_mask(series: pd.Series) -> pd.Series:
    """Vectorised is_share_row: True for plain 'Equity' rows, not options."""
    return series.str.strip() == 'Equity'

def option_mask(series: pd.Series) -> pd.Series:
    """Vectorised is_option_row: True for 'Equity Option' or 'Future Option' rows."""
    return series.str.contains('Option', na=False)

def identify_pos_type(row):
    qty  = row['Net_Qty']
    inst = str(row['Instrument Type'])
    cp   = str(row.get('Call or Put', '')).upper()
    if is_share_row(inst):   return 'Long Stock' if qty > 0 else 'Short Stock'
    if is_option_row(inst):
        if 'CALL' in cp: return 'Long Call' if qty > 0 else 'Short Call'
        if 'PUT'  in cp: return 'Long Put'  if qty > 0 else 'Short Put'
    return 'Asset'

def translate_readable(row):
    if not is_option_row(str(row['Instrument Type'])): return '%s Shares' % row['Ticker']
    try:    exp_dt = pd.to_datetime(row['Expiration Date'], format='mixed', errors='coerce').strftime('%d/%m')
    except (ValueError, TypeError, AttributeError): exp_dt = 'N/A'
    cp     = 'C' if 'CALL' in str(row['Call or Put']).upper() else 'P'
    action = 'STO' if row['Net_Qty'] < 0 else 'BTO'
    return '%s %d @ %.0f%s (%s)' % (action, abs(int(row['Net_Qty'])), row['Strike Price'], cp, exp_dt)

def format_cost_basis(val):
    return '$%.2f %s' % (abs(val), 'Cr' if val < 0 else 'Db')

# ── Styling helpers (used by DataFrame.style.map and inline HTML) ─────────────

def color_pnl_cell(val):
    """Green/red colouring for P/L columns in st.dataframe."""
    if not isinstance(val, (int, float)) or pd.isna(val): return ''
    return 'color: #00cc96' if val > 0 else 'color: #ef553b' if val < 0 else ''

def _pnl_chip(label, val):
    """Inline HTML chip showing a labelled P/L value with sign colour."""
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
        delta_str = (f'{dsign}${delta:,.2f}' if delta >= 0 else f'-${abs(delta):,.2f}')
    return (
        f'<div style="flex:1;min-width:120px;padding:0 16px;border-right:1px solid #1f2937;">'
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
    """Highlight open chain leg in the roll chain detail table."""
    if row.get('_open', False):
        return ['background-color: rgba(0,204,150,0.12); font-weight:600'] * len(row)
    return [''] * len(row)

def _color_cash_row(row):
    """Row background tint for the Deposits/Dividends table."""
    sub = str(row.get('Sub Type', ''))
    tints = {
        'Deposit':           'rgba(0,204,150,0.08)',
        'Withdrawal':        'rgba(239,85,59,0.08)',
        SUB_DIVIDEND:        'rgba(88,166,255,0.08)',
        SUB_CREDIT_INT:      'rgba(88,166,255,0.05)',
        SUB_DEBIT_INT:       'rgba(239,85,59,0.05)',
        'Balance Adjustment':'rgba(255,165,0,0.07)',
    }
    c = tints.get(sub, '')
    return [f'background-color:{c}' if c else ''] * len(row)

def _color_cash_total(val):
    """Green/red for the Total column in the cash flow table."""
    if not isinstance(val, (int, float)): return ''
    return 'color:#00cc96' if val > 0 else 'color:#ef553b' if val < 0 else ''

def chart_layout(title='', height=300, margin_t=36, margin_b=20):
    """Consistent base layout for all plotly charts."""
    return dict(
        template='plotly_dark',
        height=height,
        paper_bgcolor='rgba(10,14,23,0)',
        plot_bgcolor='rgba(10,14,23,0)',
        font=dict(family='IBM Plex Sans, sans-serif', size=12, color='#8b949e'),
        title=dict(text=title, font=dict(size=13, color='#c9d1d9', family='IBM Plex Sans'), x=0, xanchor='left', pad=dict(l=0, b=8)) if title else None,
        margin=dict(l=8, r=8, t=margin_t if title else 16, b=margin_b),
        xaxis=dict(gridcolor='rgba(255,255,255,0.05)', linecolor='rgba(255,255,255,0.08)', tickfont=dict(size=11)),
        yaxis=dict(gridcolor='rgba(255,255,255,0.05)', linecolor='rgba(255,255,255,0.08)', tickfont=dict(size=11)),
        legend=dict(bgcolor='rgba(0,0,0,0)', borderwidth=0, font=dict(size=11)),
    )

def _badge_inline_style(strat):
    """Return fully inlined style string for strategy badge (no CSS classes)."""
    _BASE = ('font-size:0.72rem;font-weight:600;padding:3px 10px;border-radius:20px;'
             'text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;')
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
    strat      = detect_strategy(t_df)
    badge_style = _badge_inline_style(strat)

    # Card wrapper — fully inline
    CARD  = ('background:linear-gradient(135deg,#111827 0%,#0f1520 100%);'
             'border:1px solid #1f2937;border-radius:12px;padding:18px 20px 14px 20px;'
             'margin-bottom:16px;box-shadow:0 2px 12px rgba(0,0,0,0.4);')
    HDR   = ('display:flex;align-items:center;justify-content:space-between;'
             'margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #1f2937;')
    TICK  = ('font-family:monospace;font-size:1.3rem;font-weight:600;'
             'color:#f0f6fc;letter-spacing:0.04em;')
    LEG   = ('display:flex;align-items:flex-start;justify-content:space-between;'
             'padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.05);')
    LBL   = 'color:#8b949e;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:2px;'
    VAL   = 'font-family:monospace;color:#e6edf3;font-size:0.88rem;'
    CHIP  = ('display:inline-block;margin-top:6px;background:rgba(255,255,255,0.04);'
             'border:1px solid #1f2937;border-radius:6px;padding:3px 10px;'
             'font-family:monospace;font-size:0.8rem;color:#8b949e;')

    legs_html = ''
    rows_sorted = t_df.sort_values('Status').rename(columns={'Cost Basis': 'Cost_Basis'})
    for i, row in enumerate(rows_sorted.itertuples(index=False)):
        pos_type = row.Status
        detail   = row.Details
        dte      = row.DTE
        basis    = format_cost_basis(row.Cost_Basis)
        is_last  = (i == len(rows_sorted) - 1)
        leg_style = LEG if not is_last else LEG.replace('border-bottom:1px solid rgba(255,255,255,0.05);', '')

        dte_html = ''
        if dte != 'N/A' and 'd' in str(dte):
            try:
                dte_val   = int(str(dte).replace('d', ''))
                pct       = min(dte_val / 45 * 100, 100)
                bar_color = '#00cc96' if dte_val > 14 else '#ffa500' if dte_val > 5 else '#ef553b'
                dte_html  = (
                    f'<div style="margin-top:6px;">'
                    f'<div style="background:#1f2937;border-radius:4px;height:4px;width:100%;">'
                    f'<div style="width:{pct:.0f}%;background:{bar_color};border-radius:4px;height:4px;"></div>'
                    f'</div>'
                    f'<div style="color:#6b7280;font-size:0.7rem;margin-top:3px;">{dte} to expiry</div>'
                    f'</div>'
                )
            except (ValueError, TypeError): pass

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

def detect_strategy(ticker_df):
    types = ticker_df.apply(identify_pos_type, axis=1)
    ls = (types == 'Long Stock').sum()
    sc = (types == 'Short Call').sum()
    lc = (types == 'Long Call').sum()
    sp = (types == 'Short Put').sum()
    lp = (types == 'Long Put').sum()
    strikes  = ticker_df['Strike Price'].dropna().unique()
    exps     = ticker_df['Expiration Date'].dropna().unique()
    if lc > 0 and sc > 0 and len(exps) >= 2 and len(strikes) == 1: return 'Calendar Spread'
    if lp > 0 and sp > 0 and len(exps) >= 2 and len(strikes) == 1: return 'Calendar Spread'
    if lc == 2 and sc == 1 and len(strikes) == 3 and len(exps) == 1: return 'Call Butterfly'
    if lp == 2 and sp == 1 and len(strikes) == 3 and len(exps) == 1: return 'Put Butterfly'
    if ls > 0 and sc > 0 and sp > 0:    return 'Covered Strangle'
    if ls > 0 and sc > 0:               return 'Covered Call'
    if sp >= 1 and sc >= 1 and lc >= 1: return 'Jade Lizard'
    if sc >= 1 and sp >= 1 and lp >= 1: return 'Big Lizard'
    if sc >= 1 and sp >= 1:             return 'Short Strangle'
    if lc >= 1 and sp >= 1:             return 'Risk Reversal'
    if lc > 1  and sc > 0:              return 'Call Debit Spread'
    if sp > 0:  return 'Short Put'
    if lc > 0:  return 'Long Call'
    if ls > 0:  return 'Long Stock'
    return 'Custom/Mixed'

# ── FIFO CORE ─────────────────────────────────────────────────────────────────
def _iter_fifo_sells(equity_rows):
    """
    Shared FIFO engine — single source of truth for equity cost-basis logic.

    Handles both long and short equity positions:

      Long side  (long_queues):
        BUY  → push (qty, cost_per_share) onto long_queue
        SELL → if long_queue has shares, pop FIFO lots and yield realised P/L
               (proceeds - cost_basis).  This is a normal long sale.

      Short side  (short_queues):
        SELL → if long_queue is empty, this is a short-sell: push (qty, proceeds_per_share)
               onto short_queue.  Nothing yielded yet — P/L realises on the cover.
        BUY  → if short_queue has shares, pop FIFO lots and yield realised P/L
               (short_proceeds - cover_cost).  Positive when you shorted higher than you covered.

    Routing rule: a SELL routes to the long side first; only if the long queue is empty
    (no long inventory to close) does it open a short.  A BUY routes to the short side
    first; only if no short inventory exists does it open a long.

    Yields (date, proceeds, cost_basis) — callers apply their own window/bucketing.
    """
    long_queues  = {}   # ticker -> deque of (qty, cost_per_share)   [long lots]
    short_queues = {}   # ticker -> deque of (qty, proceeds_per_share) [short lots]

    for row in equity_rows.itertuples(index=False):
        ticker = row.Ticker
        if ticker not in long_queues:
            long_queues[ticker]  = deque()
            short_queues[ticker] = deque()

        qty   = row.Net_Qty_Row
        total = row.Total                        # signed: negative on buys, positive on sells
        lq    = long_queues[ticker]
        sq    = short_queues[ticker]

        if qty > 0:
            # ── BUY row ───────────────────────────────────────────────────────
            # Cover shorts first (FIFO); any residual qty opens/adds to a long.
            remaining = qty
            pps = abs(total) / qty               # cost per share on this buy

            while remaining > 1e-9 and sq:
                s_qty, s_pps = sq[0]
                use      = min(remaining, s_qty)
                # P/L on covering a short = what we shorted it for minus cover cost
                short_proceeds = use * s_pps
                cover_cost     = use * pps
                yield row.Date, short_proceeds, cover_cost
                remaining = round(remaining - use, 9)
                leftover  = round(s_qty - use, 9)
                if leftover < 1e-9:
                    sq.popleft()
                else:
                    sq[0] = (leftover, s_pps)

            if remaining > 1e-9:
                # Residual qty is a new long position (or adding to existing)
                lq.append((remaining, pps))

        elif qty < 0:
            # ── SELL row ──────────────────────────────────────────────────────
            # Close longs first (FIFO); any residual qty opens/adds to a short.
            remaining       = abs(qty)
            pps             = abs(total) / remaining   # proceeds per share on this sell
            sale_cost_basis = 0.0

            while remaining > 1e-9 and lq:
                b_qty, b_cost = lq[0]
                use = min(remaining, b_qty)
                sale_cost_basis += use * b_cost
                remaining = round(remaining - use, 9)
                leftover  = round(b_qty - use, 9)
                if leftover < 1e-9:
                    lq.popleft()
                else:
                    lq[0] = (leftover, b_cost)

            if sale_cost_basis > 0 or remaining < abs(qty) - 1e-9:
                # We closed at least some long lots — yield that realised P/L
                long_qty_closed = abs(qty) - remaining
                yield row.Date, long_qty_closed * pps, sale_cost_basis

            if remaining > 1e-9:
                # Residual qty is a new short position (or adding to existing)
                sq.append((remaining, pps))


# ── TRUE FIFO EQUITY P/L ───────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def calculate_windowed_equity_pnl(df_full, start_date, end_date=None):
    """
    Calculates net equity P/L for sales on or after start_date and (optionally)
    before end_date. Cached on (df, start_date, end_date) — a window change
    re-runs once then hits cache on every subsequent interaction. The prior-period
    call is also independently cached.
    end_date is used for prior-period comparisons to prevent double-counting.
    """
    equity_rows = df_full[
        equity_mask(df_full['Instrument Type'])
    ].sort_values('Date')
    _eq_pnl = 0.0
    for date, proceeds, cost_basis in _iter_fifo_sells(equity_rows):
        in_window = date >= start_date
        if end_date is not None:
            in_window = in_window and date < end_date
        if in_window:
            _eq_pnl += (proceeds - cost_basis)
    return _eq_pnl


# ── DAILY REALIZED P/L (for period charts) ────────────────────────────────────
def calculate_daily_realized_pnl(df_full, start_date):
    """
    Returns a DataFrame with columns [Date, PnL] representing realized P/L
    by settlement date across the full portfolio:
      - Options: full cash flow on the day (already realized at close/expiry)
      - Equity sells: net gain/loss vs FIFO cost basis on the sale date
      - Dividends + interest: cash received on the day
    Share purchases are excluded — they are capital deployment, not P/L.
    Only rows with Date >= start_date are returned, but ALL equity history
    is processed so FIFO cost basis is always correct.
    """
    equity_rows = df_full[
        equity_mask(df_full['Instrument Type'])
    ].sort_values('Date')
    records = [
        {'Date': date, 'PnL': proceeds - cost_basis}
        for date, proceeds, cost_basis in _iter_fifo_sells(equity_rows)
        if date >= start_date
    ]

    # Options flows — vectorized: just select [Date, Total] columns directly
    opt_rows = df_full[
        df_full['Instrument Type'].isin(OPT_TYPES) &
        df_full['Type'].isin(TRADE_TYPES) &
        (df_full['Date'] >= start_date)
    ][['Date', 'Total']].rename(columns={'Total': 'PnL'})

    # Dividends + interest — vectorized
    income_rows = df_full[
        df_full['Sub Type'].isin(INCOME_SUB_TYPES) &
        (df_full['Date'] >= start_date)
    ][['Date', 'Total']].rename(columns={'Total': 'PnL'})

    if not records and opt_rows.empty and income_rows.empty:
        return pd.DataFrame(columns=['Date', 'PnL'])

    daily = pd.concat(
        [pd.DataFrame(records)] + ([opt_rows] if not opt_rows.empty else [])
                                 + ([income_rows] if not income_rows.empty else []),
        ignore_index=True
    )
    daily['Date'] = pd.to_datetime(daily['Date'])
    return daily.groupby('Date')['PnL'].sum().reset_index()


def build_campaigns(df, ticker, use_lifetime=False) -> list:
    """
    Build a list of Campaign objects for a ticker that has been wheeled.
    Each Campaign covers one continuous share-holding period.

    use_lifetime=True: collapses all history into a single campaign (no resets).
    use_lifetime=False: each buy-in starts a new campaign; exits close it.

    Returns a list of Campaign objects (may be empty).
    """
    t = df[df['Ticker'] == ticker].copy()
    t['Sort_Inst'] = t['Instrument Type'].apply(
        lambda x: 0 if 'Equity' in str(x) and 'Option' not in str(x) else 1
    )
    t = t.sort_values(['Date', 'Sort_Inst'])
    # Rename spaced columns so itertuples attribute access works cleanly
    t = t.rename(columns={
        'Instrument Type': 'Instrument_Type',
        'Sub Type':        'Sub_Type',
    })

    if use_lifetime:
        net_shares = t[t['Instrument_Type'].apply(is_share_row)]['Net_Qty_Row'].sum()
        if net_shares >= WHEEL_MIN_SHARES:
            premiums   = 0.0
            dividends  = 0.0
            events     = []
            start_date = t['Date'].iloc[0]
            for row in t.itertuples(index=False):
                inst     = str(row.Instrument_Type)
                total    = row.Total
                sub_type = str(row.Sub_Type)
                if is_share_row(inst):
                    if row.Net_Qty_Row > 0:
                        events.append({'date': row.Date, 'type': 'Entry/Add',
                            'detail': f'Bought {row.Net_Qty_Row} shares', 'cash': total})
                    else:
                        events.append({'date': row.Date, 'type': 'Exit',
                            'detail': f'Sold {abs(row.Net_Qty_Row)} shares', 'cash': total})
                elif is_option_row(inst):
                    if row.Date >= start_date:
                        premiums += total
                        events.append({'date': row.Date, 'type': sub_type,
                            'detail': str(row.Description)[:60], 'cash': total})
                elif sub_type == SUB_DIVIDEND:
                    dividends += total
                    events.append({'date': row.Date, 'type': SUB_DIVIDEND,
                        'detail': SUB_DIVIDEND, 'cash': total})
            net_lifetime_cash = t[t['Type'].isin(MONEY_TYPES)]['Total'].sum()
            total_cost = abs(net_lifetime_cash) if net_lifetime_cash < 0 else 0.0
            return [Campaign(
                ticker=ticker, total_shares=net_shares,
                total_cost=total_cost,
                blended_basis=total_cost / net_shares if net_shares > 0 else 0.0,
                premiums=premiums, dividends=dividends,
                exit_proceeds=0.0, start_date=start_date, end_date=None,
                status='open', events=events,
            )]

    campaigns: list      = []
    current:   Campaign  = None
    running_shares       = 0.0

    for row in t.itertuples(index=False):
        inst     = str(row.Instrument_Type)
        qty      = row.Net_Qty_Row
        total    = row.Total
        sub_type = str(row.Sub_Type)
        dsc_up   = str(row.Description).upper()

        # ── Stock split: rescale campaign quantities and basis ─────────────
        # Split rows have Net_Qty_Row == 0 (set in get_signed_qty).
        # We detect the addition row (no REMOVAL keyword) to compute the ratio
        # and rescale the live campaign. total_cost is unchanged — the same
        # cash was invested, there are just more shares now.
        if (is_share_row(inst) and qty == 0 and total == 0
                and any(p in dsc_up for p in SPLIT_DSC_PATTERNS)
                and 'REMOVAL' not in dsc_up
                and current is not None):
            split_qty = row.Quantity   # raw CSV quantity (always positive)
            if running_shares > 0.001 and split_qty > 0:
                ratio = split_qty / running_shares
                running_shares        = split_qty
                current.total_shares  = split_qty
                current.blended_basis = current.total_cost / split_qty
                current.events.append({
                    'date':   row.Date,
                    'type':   'Stock Split',
                    'detail': '%.6gx split: %.0f → %.0f shares @ $%.4f/sh basis' % (
                        ratio, split_qty / ratio, split_qty, current.blended_basis),
                    'cash':   0.0,
                })
            continue

        # ── Share buy / add ────────────────────────────────────────────────
        if is_share_row(inst) and qty >= WHEEL_MIN_SHARES:
            pps = abs(total) / qty
            if running_shares < 0.001:
                # New campaign entry — check if arrival was via put assignment
                assignment_premium, assignment_events = _find_assignment_premium(t, row)
                entry_label = 'Bought %.0f @ $%.2f/sh%s' % (
                    qty, pps, ' (Assigned)' if assignment_events else '')
                current = Campaign(
                    ticker=ticker, total_shares=qty, total_cost=abs(total),
                    blended_basis=pps, premiums=assignment_premium, dividends=0.0,
                    exit_proceeds=0.0, start_date=row.Date, end_date=None,
                    status='open',
                    events=assignment_events + [
                        {'date': row.Date, 'type': 'Entry', 'detail': entry_label, 'cash': total}
                    ],
                )
                running_shares = qty
            else:
                # Adding to an existing position — recalculate blended basis
                new_shares        = running_shares + qty
                new_cost          = current.total_cost + abs(total)
                new_basis         = new_cost / new_shares
                current.total_shares  = new_shares
                current.total_cost    = new_cost
                current.blended_basis = new_basis
                running_shares        = new_shares
                current.events.append({'date': row.Date, 'type': 'Add',
                    'detail': 'Added %.0f @ $%.2f → blended $%.2f/sh' % (qty, pps, new_basis),
                    'cash': total})

        # ── Share sale / partial exit ──────────────────────────────────────
        elif is_share_row(inst) and qty < 0:
            if current and running_shares > 0.001:
                current.exit_proceeds += total
                running_shares        += qty
                pps = abs(total) / abs(qty) if qty != 0 else 0
                current.events.append({'date': row.Date, 'type': 'Exit',
                    'detail': 'Sold %.0f @ $%.2f/sh' % (abs(qty), pps), 'cash': total})
                if running_shares < 0.001:
                    current.end_date = row.Date
                    current.status   = 'closed'
                    campaigns.append(current)
                    current        = None
                    running_shares = 0.0

        # ── Option premium ─────────────────────────────────────────────────
        elif is_option_row(inst) and current is not None:
            if row.Date >= current.start_date:
                current.premiums += total
                current.events.append({'date': row.Date, 'type': sub_type,
                    'detail': str(row.Description)[:60], 'cash': total})

        # ── Dividend ───────────────────────────────────────────────────────
        elif sub_type == SUB_DIVIDEND and current is not None:
            current.dividends += total
            current.events.append({'date': row.Date, 'type': SUB_DIVIDEND,
                'detail': 'Dividend received', 'cash': total})

    if current is not None:
        campaigns.append(current)
    return campaigns


def _find_assignment_premium(t, row):
    """
    Look for a put assignment at the same timestamp as a share delivery row.
    If found, trace back to the originating STO and record it in the campaign
    event log so the timeline shows "arrived via assignment".

    Returns (0.0, list_of_event_dicts).

    Why premium=0.0: the STO that caused assignment was traded *before* the
    campaign start date, so pure_options_pnl() already counts it as outside-
    window P/L. Adding it to c.premiums here would double-count it in
    total_realized_pnl. The event is retained for display only.
    """
    events  = []
    same_dt = t[t['Date'] == row.Date]
    assigned_syms = same_dt[
        same_dt['Sub_Type'].str.lower() == SUB_ASSIGNMENT
    ]['Symbol'].dropna().unique()
    for sym in assigned_syms:
        sto = t[
            (t['Symbol'] == sym) &
            (t['Sub_Type'].str.lower() == SUB_SELL_OPEN) &
            (t['Date'] < row.Date)
        ]
        for s in sto.itertuples(index=False):
            events.append({
                'date': s.Date, 'type': 'Assignment Put (STO)',
                'detail': str(s.Description)[:60], 'cash': s.Total,
            })
    return 0.0, events

def effective_basis(c: Campaign, use_lifetime=False) -> float:
    """Cost per share after netting premiums and dividends against total_cost."""
    if use_lifetime:
        return c.blended_basis
    net = c.total_cost - c.premiums - c.dividends
    return net / c.total_shares if c.total_shares > 0 else 0.0

def realized_pnl(c: Campaign, use_lifetime=False) -> float:
    """Total realised profit/loss for a campaign."""
    if use_lifetime:
        return c.premiums + c.dividends
    if c.status == 'closed':
        return c.exit_proceeds + c.premiums + c.dividends - c.total_cost
    return c.premiums + c.dividends

def pure_options_pnl(df, ticker, campaigns: list) -> float:
    """Options P/L for a ticker that falls *outside* all campaign windows."""
    windows = [(c.start_date, c.end_date or df['Date'].max()) for c in campaigns]
    t = df[(df['Ticker'] == ticker) & option_mask(df['Instrument Type'])]
    dates = t['Date']
    in_any_window = pd.Series(False, index=t.index)
    for s, e in windows:
        in_any_window |= (dates >= s) & (dates <= e)
    return t.loc[~in_any_window, 'Total'].sum()

# ── DERIVATIVES METRICS ENGINE ─────────────────────────────────────────────────

def build_closed_trades(df, campaign_windows=None):
    if campaign_windows is None: campaign_windows = {}
    equity_opts = df[df['Instrument Type'].isin(OPT_TYPES)].copy()
    sym_open_orders = {}
    for sym, grp in equity_opts.groupby('Symbol', dropna=False):
        opens = grp[grp['Sub Type'].str.lower().str.contains('to open', na=False)]
        if not opens.empty:
            sym_open_orders[sym] = opens['Order #'].dropna().unique().tolist()

    order_to_syms = defaultdict(set)
    for sym, orders in sym_open_orders.items():
        for oid in orders: order_to_syms[oid].add(sym)

    parent = {}
    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x: parent[x] = find(parent[x])
        return parent[x]
    def union(a, b): parent[find(a)] = find(b)

    for oid, syms in order_to_syms.items():
        syms = list(syms)
        for i in range(1, len(syms)): union(syms[0], syms[i])

    trade_groups = defaultdict(list)
    for sym in sym_open_orders: trade_groups[find(sym)].append(sym)

    closed_list = []
    for root, syms in trade_groups.items():
        grp = equity_opts[equity_opts['Symbol'].isin(syms)].sort_values('Date')
        all_closed = all(abs(equity_opts[equity_opts['Symbol'] == s]['Net_Qty_Row'].sum()) < 0.001 for s in syms)
        if not all_closed: continue

        opens = grp[grp['Sub Type'].str.lower().str.contains('to open', na=False)]
        if opens.empty: continue

        open_credit = opens['Total'].sum()
        net_pnl     = grp['Total'].sum()
        open_date   = opens['Date'].min()
        close_date  = grp['Date'].max()
        days_held   = max((close_date - open_date).days, 1)
        ticker      = grp['Ticker'].iloc[0]
        cp_vals     = grp['Call or Put'].dropna().str.upper().unique().tolist()
        cp          = cp_vals[0] if len(cp_vals) == 1 else 'Mixed'
        n_long      = (opens['Net_Qty_Row'] > 0).sum()
        is_credit   = open_credit > 0

        if n_long > 0:
            call_strikes = grp[grp['Call or Put'].str.upper().str.contains('CALL', na=False)]['Strike Price'].dropna().sort_values()
            put_strikes  = grp[grp['Call or Put'].str.upper().str.contains('PUT',  na=False)]['Strike Price'].dropna().sort_values()
            w_call = (call_strikes.max() - call_strikes.min()) * 100 if len(call_strikes) >= 2 else 0
            w_put  = (put_strikes.max()  - put_strikes.min())  * 100 if len(put_strikes)  >= 2 else 0

            expirations = grp['Expiration Date'].dropna().unique()
            strikes_all = grp['Strike Price'].dropna().unique()
            is_calendar = len(expirations) >= 2 and len(strikes_all) == 1

            short_opens_sp  = opens[opens['Net_Qty_Row'] < 0]
            long_opens_sp   = opens[opens['Net_Qty_Row'] > 0]
            n_short_legs    = len(short_opens_sp)
            n_long_legs     = len(long_opens_sp)
            short_qty_total = abs(short_opens_sp['Net_Qty_Row'].sum())
            long_qty_total  = long_opens_sp['Net_Qty_Row'].sum()
            is_butterfly = (n_long_legs == 2 and n_short_legs == 1 and
                            short_qty_total == 2 and long_qty_total == 2 and
                            len(strikes_all) == 3 and len(expirations) == 1)

            short_cp = short_opens_sp['Call or Put'].dropna().str.upper().tolist()
            long_cp  = long_opens_sp['Call or Put'].dropna().str.upper().tolist()
            has_short_put_only  = any('PUT'  in c for c in short_cp) and not any('PUT'  in c for c in long_cp)
            has_call_spread_leg = any('CALL' in c for c in short_cp) and any('CALL' in c for c in long_cp)
            is_jade_lizard = has_short_put_only and has_call_spread_leg and len(put_strikes) == 1

            # ── Naked long: no short legs at all (e.g. LEAPS, long call/put outright) ──
            # Must be checked before spread logic — w_call/w_put are both 0 for a
            # single-strike long, which would otherwise fall into the Put Credit Spread
            # branch and produce a capital_risk of $1.
            if n_short_legs == 0:
                long_cp_types = long_opens_sp['Call or Put'].dropna().str.upper().unique().tolist()
                has_lc = any('CALL' in c for c in long_cp_types)
                has_lp = any('PUT'  in c for c in long_cp_types)
                if has_lc and not has_lp:   trade_type = 'Long Call'
                elif has_lp and not has_lc: trade_type = 'Long Put'
                else:                       trade_type = 'Long Strangle'
                # Capital at risk for a long option = premium paid (max loss if expires worthless)
                capital_risk = max(abs(open_credit), 1)
            elif is_butterfly:
                trade_type = 'Call Butterfly' if len(call_strikes.unique()) == 3 else 'Put Butterfly'
                wing_width = (strikes_all.max() - strikes_all.min()) * 100 / 2
                capital_risk = max(abs(open_credit), wing_width, 1)
            elif is_jade_lizard:
                trade_type   = 'Jade Lizard'
                capital_risk = max(w_call - abs(open_credit), 1)
            elif is_calendar:
                trade_type   = 'Calendar Spread'
                capital_risk = max(abs(open_credit), 1)
            elif w_call > 0 and w_put > 0:
                trade_type   = 'Iron Condor'
                capital_risk = max(max(w_call, w_put) - abs(open_credit), 1)
            elif w_call > 0:
                trade_type   = 'Call Credit Spread' if is_credit else 'Call Debit Spread'
                # Credit spread: risk = wing_width - credit_received (net outlay if assigned)
                # Debit spread:  risk = debit_paid (max loss if expires worthless) = abs(open_credit)
                capital_risk = max(w_call - abs(open_credit), 1) if is_credit else max(abs(open_credit), 1)
            else:
                trade_type   = 'Put Credit Spread' if is_credit else 'Put Debit Spread'
                capital_risk = max(w_put - abs(open_credit), 1) if is_credit else max(abs(open_credit), 1)
        else:
            strikes      = grp['Strike Price'].dropna().tolist()
            # For naked shorts the theoretical max loss is strike × 100 (underlying → 0).
            # This is a reasonable proxy for equity options (strike typically < $500),
            # but produces meaningless Ann Return % for index options where strikes are
            # in the hundreds or thousands (SPX ~5000, NDX ~20000, RUT ~2000).
            # Heuristic: if the highest strike exceeds INDEX_STRIKE_THRESHOLD we treat
            # this as an index underlying and use premium received as the capital_risk
            # proxy instead — consistent with how traders actually manage index risk
            # (margin-based, not theoretical zero-underlying loss).
            max_strike   = max(strikes) if strikes else 0
            if max_strike >= INDEX_STRIKE_THRESHOLD:
                capital_risk = max(abs(open_credit), 1)   # index: use premium as risk
            else:
                capital_risk = max(max_strike * 100, 1)   # equity: theoretical max loss
            short_opens  = opens[opens['Net_Qty_Row'] < 0]
            long_opens   = opens[opens['Net_Qty_Row'] > 0]
            cp_shorts = short_opens['Call or Put'].dropna().str.upper().unique().tolist()
            cp_longs  = long_opens['Call or Put'].dropna().str.upper().unique().tolist()
            has_sc = any('CALL' in c for c in cp_shorts)
            has_sp = any('PUT'  in c for c in cp_shorts)
            has_lc = any('CALL' in c for c in cp_longs)
            has_lp = any('PUT'  in c for c in cp_longs)
            n_contracts = int(abs(opens['Net_Qty_Row'].sum()))
            if not is_credit:
                if has_lc and not has_lp: trade_type = 'Long Call'
                elif has_lp and not has_lc: trade_type = 'Long Put'
                else: trade_type = 'Long Strangle'
            else:
                if has_sc and has_sp:
                    all_strikes = grp['Strike Price'].dropna().unique()
                    trade_type = 'Short Straddle' if len(all_strikes) == 1 else 'Short Strangle'
                    windows = campaign_windows.get(ticker, [])
                    in_campaign = any(s <= open_date <= e for s, e in windows)
                    if in_campaign:
                        trade_type = 'Covered Straddle' if 'Straddle' in trade_type else 'Covered Strangle'
                elif has_sc:
                    windows = campaign_windows.get(ticker, [])
                    in_campaign = any(s <= open_date <= e for s, e in windows)
                    trade_type = 'Covered Call' if in_campaign else (
                        'Short Call' if n_contracts == 1 else 'Short Call (x%d)' % n_contracts)
                elif has_sp:
                    trade_type = 'Short Put' if n_contracts == 1 else 'Short Put (x%d)' % n_contracts
                else:
                    trade_type = 'Short (other)'

        try:
            exp_dates = opens['Expiration Date'].dropna()
            if not exp_dates.empty:
                nearest_exp = pd.to_datetime(exp_dates.iloc[0])
                dte_open = max((nearest_exp - open_date).days, 0)
            else:
                dte_open = None
        except (ValueError, TypeError, AttributeError): dte_open = None

        closes = grp[~grp['Sub Type'].str.lower().str.contains('to open', na=False)]
        _close_sub_types = closes['Sub Type'].dropna().str.lower().unique().tolist()
        if any(PAT_EXPIR in s for s in _close_sub_types):
            close_type = '⏹️ Expired'
        elif any(PAT_ASSIGN in s for s in _close_sub_types):
            close_type = '📋 Assigned'
        elif any('exercise' in s for s in _close_sub_types):
            close_type = '🏋️ Exercised'
        else:
            close_type = '✂️ Closed'

        closed_list.append({
            'Ticker': ticker, 'Trade Type': trade_type,
            'Type': 'Call' if 'CALL' in cp else 'Put' if 'PUT' in cp else 'Mixed',
            'Spread': n_long > 0, 'Is Credit': is_credit, 'Days Held': days_held,
            'Open Date': open_date, 'Close Date': close_date, 'Premium Rcvd': open_credit,
            'Net P/L': net_pnl,
            # Capture %: for credit trades = P/L as % of premium collected (how much of the
            # credit did you keep). For debit trades = P/L as % of premium paid (return on
            # the capital deployed into the trade). Sign-safe: uses abs(open_credit).
            'Capture %': net_pnl / abs(open_credit) * 100 if abs(open_credit) > 0 else None,
            'Capital Risk': capital_risk,
            # Ann Return %: enabled for ALL trades (credit and debit) — the formula is
            # the same: P/L / capital_at_risk * annualisation factor.
            # Previously gated to is_credit only, leaving debit trades always None.
            'Ann Return %': max(min(net_pnl / capital_risk * 365 / days_held * 100, 500), -500)
                if capital_risk > 0 else None,
            'Prem/Day': open_credit / days_held if is_credit else None,
            'Won': net_pnl > 0, 'DTE Open': dte_open, 'Close Type': close_type,
        })
    return pd.DataFrame(closed_list)


# ── ROLL CHAIN ENGINE ──────────────────────────────────────────────────────────

def build_option_chains(ticker_opts):
    """
    Groups option events into roll chains by call/put type.
    A chain = one continuous short position, rolled multiple times.
    Chain ends when position goes flat AND next STO is > 3 days later.
    """
    chains = []
    for cp_type in ['CALL', 'PUT']:
        legs = ticker_opts[
            ticker_opts['Call or Put'].str.upper().str.contains(cp_type, na=False)
        ].copy().sort_values('Date').reset_index(drop=True)
        if legs.empty: continue
        # Rename spaced columns so itertuples attribute access works
        legs = legs.rename(columns={
            'Sub Type':       'Sub_Type',
            'Strike Price':   'Strike_Price',
            'Expiration Date':'Expiration_Date',
        })

        current_chain = []
        net_qty = 0
        last_close_date = None

        for row in legs.itertuples(index=False):
            sub = str(row.Sub_Type).lower()
            qty = row.Net_Qty_Row
            exp_dt = row.Expiration_Date
            event = {
                'date': row.Date, 'sub_type': row.Sub_Type,
                'strike': row.Strike_Price,
                'exp': pd.to_datetime(exp_dt).strftime('%d/%m/%y') if pd.notna(exp_dt) else '',
                'qty': qty, 'total': row.Total, 'cp': cp_type,
                'desc': str(row.Description)[:55],
            }
            if 'to open' in sub and qty < 0:
                if last_close_date is not None and net_qty == 0:
                    if (row.Date - last_close_date).days > 3 and current_chain:
                        chains.append(current_chain)
                        current_chain = []
                net_qty += abs(qty)
                current_chain.append(event)
                last_close_date = None
            elif net_qty > 0 and (PAT_CLOSE in sub or 'expiration' in sub or 'assignment' in sub):
                net_qty = max(net_qty - abs(qty), 0)
                current_chain.append(event)
                if net_qty == 0:
                    last_close_date = row.Date

        if current_chain:
            chains.append(current_chain)
    return chains

def calc_dte(row, reference_date: pd.Timestamp) -> str:
    """
    Compute days-to-expiry for an open option row.
    Returns e.g. '21d' or 'N/A'.

    reference_date is passed explicitly (was previously an implicit module global,
    which made the function impossible to call correctly before the CSV was loaded).
    """
    if not is_option_row(str(row['Instrument Type'])) or pd.isna(row['Expiration Date']):
        return 'N/A'
    try:
        exp_date  = pd.to_datetime(row['Expiration Date'], format='mixed', errors='coerce')
        if pd.isna(exp_date):
            return 'N/A'
        exp_plain = exp_date.date() if hasattr(exp_date, 'date') else exp_date
        return '%dd' % max((exp_plain - reference_date.date()).days, 0)
    except (ValueError, TypeError, AttributeError):
        return 'N/A'

# ── MAIN APP ───────────────────────────────────────────────────────────────────

st.title(f'📟 TastyMechanics {APP_VERSION}')

with st.sidebar:
    st.header('⚙️ Data Control')
    uploaded_file = st.file_uploader('Upload TastyTrade History CSV', type='csv')
    st.markdown('---')
    st.header('🎯 Campaign Settings')
    use_lifetime = st.toggle('Show Lifetime "House Money"', value=False,
        help='If ON, combines ALL history for a ticker into one campaign. If OFF, resets breakeven every time shares hit zero.')

if not uploaded_file:
    st.markdown(f"""
    <div style="max-width:760px;margin:2rem auto 0 auto;">

    <p style="color:#8b949e;font-size:0.95rem;line-height:1.7;">
    Upload your TastyTrade transaction history CSV using the sidebar to get started.
    All processing happens locally in your browser — your data is never sent anywhere.
    </p>

    <h3 style="color:#c9d1d9;margin-top:2rem;">How to export from TastyTrade</h3>
    <p style="color:#8b949e;font-size:0.95rem;line-height:1.7;">
    <b style="color:#c9d1d9;">History → Transactions → set date range → Download CSV</b><br>
    Export your full history for the most accurate results.
    </p>

    <h3 style="color:#c9d1d9;margin-top:2rem;">⚠️ Disclaimer</h3>
    <div style="background:#161b22;border:1px solid #f0883e55;border-radius:8px;padding:1.2rem 1.4rem;font-size:0.88rem;color:#8b949e;line-height:1.75;">

    <p style="margin:0 0 0.75rem 0;color:#c9d1d9;font-weight:600;">
    This tool is for personal record-keeping only. It is not financial advice.
    </p>

    <b style="color:#c9d1d9;">Known limitations — verify these manually:</b>
    <ul style="margin:0.5rem 0 0.75rem 0;padding-left:1.2rem;">
    <li><b style="color:#c9d1d9;">Covered calls assigned away</b> — if your shares are called away by assignment, verify the campaign closes and P/L is recorded correctly.</li>
    <li><b style="color:#c9d1d9;">Multiple assignments on the same ticker</b> — each new buy-in starts a new campaign. Blended basis across campaigns is not currently combined.</li>
    <li><b style="color:#c9d1d9;">Long options exercised by you</b> — exercising a long call or put into shares is untested. Check the resulting position and cost basis.</li>
    <li><b style="color:#c9d1d9;">Futures options delivery</b> — cash-settled futures options (like /MES, /ZS) are included in P/L totals, but in-the-money expiry into a futures contract is not handled.</li>
    <li><b style="color:#c9d1d9;">Stock splits</b> — forward and reverse splits are detected and adjusted, but TastyTrade-issued post-split option symbols are not automatically stitched to pre-split contracts.</li>
    <li><b style="color:#c9d1d9;">Spin-offs and zero-cost deliveries</b> — shares received at $0 cost (spin-offs, ACATS transfers) will show a warning. The $0 basis means P/L on sale will be overstated until corrected.</li>
    <li><b style="color:#c9d1d9;">Complex multi-leg structures</b> — PMCC, diagonals, calendars, and ratio spreads may not be classified correctly in the trade log.</li>
    <li><b style="color:#c9d1d9;">Non-US accounts</b> — built and tested on a US TastyTrade account. Currency, tax treatment, and CSV format differences for other regions are unknown.</li>
    </ul>

    <p style="margin:0;color:#6e7681;">
    P/L figures are cash-flow based (what actually hit your account) and use FIFO cost basis
    for equity. They do not account for unrealised gains/losses, wash sale rules, or tax adjustments.
    Always reconcile against your official TastyTrade statements for tax purposes.
    </p>
    </div>

    <p style="color:#444d56;font-size:0.78rem;margin-top:1.5rem;text-align:center;">
    TastyMechanics {APP_VERSION} · Open source · MIT licence ·
    <a href="https://github.com/timluey/tastymechanics" style="color:#58a6ff;">GitHub</a>
    </p>

    </div>
    """, unsafe_allow_html=True)
    st.stop()


@dataclass
class Campaign:
    """
    A single wheel campaign — one continuous share-holding period for a ticker.

    Created in build_campaigns() when shares >= WHEEL_MIN_SHARES are bought,
    closed when shares reach zero. Multiple campaigns per ticker are possible
    (e.g. bought, fully exited, then re-entered).

    Fields:
        ticker         Underlying symbol, e.g. 'NVDA'
        total_shares   Current share count (updated on adds, exits, splits)
        total_cost     Cash paid to acquire shares (absolute value, always >= 0)
        blended_basis  total_cost / total_shares — average cost per share
        premiums       Net option premium collected while campaign is open (can be negative)
        dividends      Dividends received during the campaign
        exit_proceeds  Cash received from share sales (positive when sold)
        start_date     Date of first share purchase / assignment entry
        end_date       Date shares hit zero (None while still open)
        status         'open' or 'closed'
        events         Ordered list of dicts — {date, type, detail, cash} for the UI log
    """
    ticker:         str
    total_shares:   float
    total_cost:     float
    blended_basis:  float
    premiums:       float
    dividends:      float
    exit_proceeds:  float
    start_date:     pd.Timestamp
    end_date:       Optional[pd.Timestamp]
    status:         str                    # 'open' | 'closed'
    events:         list = field(default_factory=list)


@dataclass
class AppData:
    """Typed container for all heavy-computed data from build_all_data().
    Replaces a fragile 10-tuple — fields are named, self-documenting,
    and safe to reorder or extend without breaking the caller."""
    all_campaigns:          dict                # {ticker: list[Campaign]}
    wheel_tickers:          list
    pure_options_tickers:   list
    closed_trades_df:       pd.DataFrame
    df_open:                pd.DataFrame
    closed_camp_pnl:        float
    open_premiums_banked:   float
    capital_deployed:       float
    pure_opts_pnl:          float
    extra_capital_deployed: float
    pure_opts_per_ticker:   dict   # {ticker: float} options P/L outside campaign windows
    split_events:           list   # [{ticker,date,ratio,...}] detected stock splits
    zero_cost_rows:         list   # [{ticker,date,qty,...}] zero-cost deliveries with unknown basis



# ── Cached data loading ────────────────────────────────────────────────────────

class ParsedData(NamedTuple):
    """Return type of load_and_parse() — bundles the cleaned DataFrame with
    the corporate action lists so build_all_data() can use them without
    re-running detect_corporate_actions() a second time."""
    df:             pd.DataFrame
    split_events:   list   # [{ticker, date, ratio, pre_qty, post_qty}]
    zero_cost_rows: list   # [{ticker, date, qty, description}]


def detect_corporate_actions(df):
    """
    Scan the DataFrame for corporate actions that affect cost-basis correctness.
    Returns two lists for UI warnings:

      split_events  -- list of dicts: {ticker, date, ratio, pre_qty, post_qty}
                       Detected by pairing a zero-Total Receive Deliver REMOVAL
                       containing a split keyword with a zero-Total addition on
                       the same ticker+date.  ratio = post_qty / pre_qty.

      zero_cost_rows -- list of dicts: {ticker, date, qty, description}
                       Any zero-Total Receive Deliver share addition that is not
                       part of a detected split pair and is not an assignment.
                       Includes spin-offs, ACATS transfers, and mergers whose
                       cost basis defaults to $0 in the FIFO queue.

    Called from load_and_parse() after Net_Qty_Row is set.
    Results are also stored in AppData so the UI can show a warning banner.
    """
    split_events   = []
    zero_cost_rows = []

    rd = df[
        (df['Type'] == 'Receive Deliver') &
        (equity_mask(df['Instrument Type'])) &
        (df['Total'] == 0.0)
    ].copy()
    if rd.empty:
        return split_events, zero_cost_rows

    rd['_dsc'] = rd['Description'].fillna('').str.upper()

    def _is_split_row(dsc):
        return any(p in dsc for p in SPLIT_DSC_PATTERNS)

    processed_indices = set()
    for (ticker, date), grp in rd.groupby(['Ticker', 'Date']):
        removals  = grp[grp['_dsc'].apply(lambda d: 'REMOVAL' in d and _is_split_row(d))]
        additions = grp[grp['_dsc'].apply(lambda d: 'REMOVAL' not in d and _is_split_row(d))]
        if not removals.empty and not additions.empty:
            pre_qty  = removals['Quantity'].sum()
            post_qty = additions['Quantity'].sum()
            if pre_qty > 0:
                split_events.append({
                    'ticker':   ticker,
                    'date':     date,
                    'ratio':    round(post_qty / pre_qty, 6),
                    'pre_qty':  pre_qty,
                    'post_qty': post_qty,
                })
                processed_indices.update(removals.index)
                processed_indices.update(additions.index)

    # Zero-cost additions not matched to a split pair
    for row in rd[~rd.index.isin(processed_indices)].itertuples(index=False):
        # Note: itertuples renames columns starting with _ (e.g. _dsc -> _3),
        # so we read Description directly and uppercase it ourselves.
        dsc = str(row.Description).upper()
        if 'ASSIGNMENT' in dsc:
            continue
        if row.Quantity > 0:
            zero_cost_rows.append({
                'ticker':      row.Ticker,
                'date':        row.Date,
                'qty':         row.Quantity,
                'description': str(row.Description)[:80],
            })

    return split_events, zero_cost_rows


def apply_split_adjustments(df, split_events):
    """
    Rescale pre-split equity lot quantities in-place so the FIFO engine
    sees the correct post-split share counts and per-share cost basis.

    For each split event (ratio = post/pre, e.g. 2.0 for a 2:1 forward split):
      - Equity rows for that ticker with Date < split_date have their
        Quantity and Net_Qty_Row multiplied by ratio.
      - Total (cash paid/received) is unchanged — basis per share halves.
      - The split rows themselves (Total=0, Net_Qty_Row=0) are untouched.

    NOTE: Option strikes are NOT adjusted here.  TastyTrade issues new symbols
    for adjusted options — those are a known limitation (see README).
    """
    if not split_events:
        return df
    df = df.copy()
    for ev in split_events:
        mask = (
            (df['Ticker'] == ev['ticker']) &
            (equity_mask(df['Instrument Type'])) &
            (df['Date'] < ev['date']) &
            (df['Net_Qty_Row'] != 0)
        )
        df.loc[mask, 'Quantity']    = (df.loc[mask, 'Quantity']    * ev['ratio']).round(9)
        df.loc[mask, 'Net_Qty_Row'] = (df.loc[mask, 'Net_Qty_Row'] * ev['ratio']).round(9)
    return df


@st.cache_data(show_spinner='📂 Loading CSV…')
def load_and_parse(file_bytes: bytes) -> ParsedData:
    """
    Read and clean the TastyTrade CSV.
    Cached on raw file bytes — re-runs only when a new file is uploaded.

    Returns ParsedData(df, split_events, zero_cost_rows) so that
    build_all_data() can surface the corporate action lists in AppData
    without running detect_corporate_actions() a second time.
    """
    df = pd.read_csv(_io.BytesIO(file_bytes))
    # Parse as UTC (handles TastyTrade's +00:00 suffix), then strip tz.
    # All dates in the app are naive UTC from this point forward — no mixing.
    df['Date']        = pd.to_datetime(df['Date'], utc=True).dt.tz_localize(None)
    for col in ['Total', 'Quantity', 'Commissions', 'Fees']:
        df[col] = df[col].apply(clean_val)
    df['Ticker']      = df['Underlying Symbol'].fillna(
                            df['Symbol'].str.split().str[0]).fillna('CASH')
    df['Net_Qty_Row'] = df.apply(get_signed_qty, axis=1)
    df = df.sort_values('Date').reset_index(drop=True)
    # Detect corporate actions and apply split quantity adjustments.
    # Must run after Net_Qty_Row is assigned and df is date-sorted.
    # Both lists are returned in ParsedData so build_all_data() doesn't
    # need to re-run this scan.
    split_events, zero_cost_rows = detect_corporate_actions(df)
    df = apply_split_adjustments(df, split_events)
    return ParsedData(df=df, split_events=split_events, zero_cost_rows=zero_cost_rows)


@st.cache_data(show_spinner='⚙️ Building campaigns…')
def build_all_data(parsed: ParsedData, use_lifetime: bool):
    """
    All heavy computation that depends only on the full DataFrame and
    lifetime toggle — not on the selected time window.

    Accepts a ParsedData so it can include split_events and zero_cost_rows
    in AppData without re-running detect_corporate_actions().

    Cached separately from load_and_parse so that toggling Lifetime mode
    only re-runs campaign logic, not the CSV parse.

    Returns: AppData dataclass -- see AppData definition for field descriptions.
    """
    df, split_events, zero_cost_rows = parsed
    # ── Open positions ledger ──────────────────────────────────────────────
    trade_df = df[df['Type'].isin(TRADE_TYPES)].copy()
    groups   = trade_df.groupby(
        ['Ticker', 'Symbol', 'Instrument Type', 'Call or Put',
         'Expiration Date', 'Strike Price', 'Root Symbol'], dropna=False)
    open_records = []
    for name, group in groups:
        net_qty = group['Net_Qty_Row'].sum()
        if abs(net_qty) > 0.001:
            open_records.append({
                'Ticker': name[0], 'Symbol': name[1],
                'Instrument Type': name[2], 'Call or Put': name[3],
                'Expiration Date': name[4], 'Strike Price': name[5],
                'Root Symbol': name[6], 'Net_Qty': net_qty,
                'Cost Basis': group['Total'].sum() * -1,
            })
    df_open = pd.DataFrame(open_records)

    # ── Wheel campaigns ────────────────────────────────────────────────────
    wheel_tickers = []
    for t in df['Ticker'].unique():
        if t == 'CASH': continue
        if not df[(df['Ticker'] == t) &
                  (equity_mask(df['Instrument Type'])) &
                  (df['Net_Qty_Row'] >= WHEEL_MIN_SHARES)].empty:
            wheel_tickers.append(t)

    all_campaigns = {}
    for ticker in wheel_tickers:
        camps = build_campaigns(df, ticker, use_lifetime=use_lifetime)
        if camps:
            all_campaigns[ticker] = camps

    all_tickers          = [t for t in df['Ticker'].unique() if t != 'CASH']
    pure_options_tickers = [t for t in all_tickers if t not in wheel_tickers]

    # ── Closed trades ──────────────────────────────────────────────────────
    latest_date  = df['Date'].max()
    _camp_windows = {
        _t: [(_c.start_date, _c.end_date or latest_date) for _c in _camps]
        for _t, _camps in all_campaigns.items()
    }
    closed_trades_df = build_closed_trades(df, campaign_windows=_camp_windows)

    # ── All-time P/L accounting ────────────────────────────────────────────
    closed_camp_pnl      = sum(realized_pnl(c, use_lifetime)
                               for camps in all_campaigns.values()
                               for c in camps if c.status == 'closed')
    open_premiums_banked = sum(realized_pnl(c, use_lifetime)
                               for camps in all_campaigns.values()
                               for c in camps if c.status == 'open')
    capital_deployed     = sum(c.total_shares * c.blended_basis
                               for camps in all_campaigns.values()
                               for c in camps if c.status == 'open')

    # ── P/L for pure-options tickers (not part of a 100-share wheel) ─────────
    # Two components per ticker:
    #   1. Options cash flow — already realized at open/close, no basis tracking needed
    #   2. Equity realized P/L — FIFO via _iter_fifo_sells(), same engine as the
    #      windowed view. This replaces the old cash-flow hack that was correct only
    #      when all standalone equity positions happened to be fully closed.
    # Shares still held are capital deployment, not realized P/L — their cost basis
    # stays in the FIFO queue and contributes to extra_capital_deployed instead.
    pure_opts_pnl          = 0.0
    extra_capital_deployed = 0.0

    for t in pure_options_tickers:
        t_df = df[df['Ticker'] == t]

        # 1. Options cash flow
        opt_flow = t_df[
            t_df['Instrument Type'].isin(OPT_TYPES) &
            t_df['Type'].isin(TRADE_TYPES)
        ]['Total'].sum()

        # 2. Equity realized P/L via FIFO (correct for any mix of buys, partial sells,
        #    and full exits — not just the fully-closed case the old hack handled)
        t_eq_rows  = t_df[equity_mask(t_df['Instrument Type'])].sort_values('Date')
        eq_fifo_pnl = sum(p - c for _, p, c in _iter_fifo_sells(t_eq_rows))

        pure_opts_pnl += opt_flow + eq_fifo_pnl

        # 3. Shares still open → capital deployed (not realized P/L)
        net_shares = t_eq_rows['Net_Qty_Row'].sum()
        if net_shares > 0.0001:
            bought_rows    = t_eq_rows[t_eq_rows['Net_Qty_Row'] > 0]
            total_bought   = bought_rows['Net_Qty_Row'].sum()
            total_buy_cost = bought_rows['Total'].apply(abs).sum()
            avg_cost       = total_buy_cost / total_bought if total_bought > 0 else 0
            extra_capital_deployed += net_shares * avg_cost

    # Also include options P/L from wheel tickers that fell outside campaign windows
    # (e.g. options written before the first share purchase)
    pure_opts_per_ticker = {}
    for ticker, camps in all_campaigns.items():
        pot = pure_options_pnl(df, ticker, camps)
        pure_opts_per_ticker[ticker] = pot
        pure_opts_pnl += pot

    return AppData(
        all_campaigns=all_campaigns,
        wheel_tickers=wheel_tickers,
        pure_options_tickers=pure_options_tickers,
        closed_trades_df=closed_trades_df,
        df_open=df_open,
        closed_camp_pnl=closed_camp_pnl,
        open_premiums_banked=open_premiums_banked,
        capital_deployed=capital_deployed,
        pure_opts_pnl=pure_opts_pnl,
        extra_capital_deployed=extra_capital_deployed,
        pure_opts_per_ticker=pure_opts_per_ticker,
        split_events=split_events,
        zero_cost_rows=zero_cost_rows,
    )


@st.cache_data(show_spinner=False)
def get_daily_pnl(df: pd.DataFrame) -> pd.DataFrame:
    """
    Daily realized P/L series — FIFO-correct, whole portfolio.
    Cached on the full df — re-runs only when a new file is uploaded.
    Window slicing is done downstream by the caller.
    """
    return calculate_daily_realized_pnl(df, df['Date'].min())



# ── Validate + load ────────────────────────────────────────────────────────────
# Read raw bytes first so we can validate columns before the cached parse
_raw_bytes = uploaded_file.getvalue()
_check_df  = pd.read_csv(_io.BytesIO(_raw_bytes), nrows=0)
_missing   = REQUIRED_COLUMNS - set(_check_df.columns)
if _missing:
    st.error(
        '❌ **This doesn\'t look like a TastyTrade history CSV.**\n\n'
        f'Missing columns: `{", ".join(sorted(_missing))}`\n\n'
        'Export from **TastyTrade → History → Transactions → Download CSV**.'
    )
    st.stop()

try:
    _parsed = load_and_parse(_raw_bytes)
except Exception as e:
    st.error(f'❌ **File loaded but could not be parsed:** `{e}`\n\nMake sure you\'re uploading an unmodified TastyTrade CSV export.')
    st.stop()

df = _parsed.df
if df.empty:
    st.error('❌ The uploaded CSV is empty — no transactions found.')
    st.stop()

latest_date = df['Date'].max()

# ── Unpack cached heavy computation ───────────────────────────────────────────
_d = build_all_data(_parsed, use_lifetime)
all_campaigns          = _d.all_campaigns
wheel_tickers          = _d.wheel_tickers
pure_options_tickers   = _d.pure_options_tickers
closed_trades_df       = _d.closed_trades_df
df_open                = _d.df_open
closed_camp_pnl        = _d.closed_camp_pnl
open_premiums_banked   = _d.open_premiums_banked
capital_deployed       = _d.capital_deployed
pure_opts_pnl          = _d.pure_opts_pnl
extra_capital_deployed = _d.extra_capital_deployed
pure_opts_per_ticker   = _d.pure_opts_per_ticker
corp_split_events      = _d.split_events
corp_zero_cost_rows    = _d.zero_cost_rows

total_realized_pnl = closed_camp_pnl + open_premiums_banked + pure_opts_pnl
capital_deployed  += extra_capital_deployed

# Add all-time dividends + interest so that total_realized_pnl is computed on
# the same basis as window_realized_pnl (which now includes _w_div_int).
# Campaign accounting already includes wheel-ticker dividends via c.dividends,
# but interest and non-wheel-ticker income are missing without this line.
_all_time_income = df[df['Sub Type'].isin(INCOME_SUB_TYPES)]['Total'].sum()
# Subtract wheel-ticker dividends already counted in campaigns to avoid double-counting
_wheel_divs_in_camps = sum(
    c.dividends
    for camps in all_campaigns.values()
    for c in camps
)
total_realized_pnl += _all_time_income - _wheel_divs_in_camps

# ── Corporate action warnings ──────────────────────────────────────────────────────────────────────────
# Shown once at load time; both lists are empty for the vast majority of users.
if corp_split_events:
    for _ev in corp_split_events:
        _ratio = _ev['ratio']
        _fwd   = _ratio > 1
        _label = '%.0f:1 forward split' % _ratio if _fwd else '1:%.0f reverse split' % (1/_ratio)
        st.info(
            f"⚠️ **Stock split detected: {xe(_ev['ticker'])}** — {_label} on "
            f"{_ev['date'].strftime('%d/%m/%Y')} "
            f"({_ev['pre_qty']:.0f} → {_ev['post_qty']:.0f} shares). "
            "Pre-split lot sizes have been automatically rescaled in the FIFO engine "
            "so cost basis and P/L should be correct. "
            "Note: adjusted option symbols are a separate TastyTrade entry and are "
            "not automatically stitched to pre-split contracts.",
            icon=None
        )

if corp_zero_cost_rows:
    _zc_tickers = sorted({r['ticker'] for r in corp_zero_cost_rows})
    _zc_lines   = [
        f"**{xe(r['ticker'])}** — {r['qty']:.0f} shares on "
        f"{r['date'].strftime('%d/%m/%Y')}: _{xe(r['description'])}_"
        for r in corp_zero_cost_rows
    ]
    st.warning(
        "⚠️ **Zero-cost share delivery detected** — the following positions "
        "were received with Total = $0, which typically means the cost basis was not "
        "transferred (spin-off, ACATS, merger conversion). "
        "These shares have been loaded with a $0/share cost basis, which will "
        "**overstate P/L** on eventual sale by the full proceeds amount. "
        "Check your broker statement for the correct allocated basis and note "
        "this as a limitation of the current data.\n\n"
        + "\n\n".join(_zc_lines)
    )

# ── Expiry alert data (fast — from cached df_open) ────────────────────────────
_expiry_alerts = []
if not df_open.empty:
    _opts_open = df_open[option_mask(df_open['Instrument Type'])].copy()
    if not _opts_open.empty and _opts_open['Expiration Date'].notna().any():
        _opts_open['_exp_dt'] = pd.to_datetime(_opts_open['Expiration Date'], format='mixed', errors='coerce')
        _opts_open = _opts_open.dropna(subset=['_exp_dt'])
        _opts_open['_dte'] = (_opts_open['_exp_dt'] - latest_date).dt.days.clip(lower=0)
        _near = _opts_open[_opts_open['_dte'] <= 21].sort_values('_dte').copy()
        _near = _near.rename(columns={'_dte': 'dte_val', 'Strike Price': 'Strike_Price', 'Call or Put': 'Call_or_Put'})
        for row in _near.itertuples(index=False):
            cp   = str(row.Call_or_Put).upper()
            side = 'C' if 'CALL' in cp else 'P'
            _expiry_alerts.append({
                'ticker': row.Ticker,
                'label':  '%.0f%s' % (row.Strike_Price, side),
                'dte':    int(row.dte_val),
                'qty':    int(row.Net_Qty),
            })

# ── Window-dependent slices (re-run on every window change, fast) ─────────────
# ── Time window selector — top right ──────────────────────────────────────────
time_options = ['YTD', 'Last 5 Days', 'Last Month', 'Last 3 Months', 'Half Year', '1 Year', 'All Time']
_hdr_left, _hdr_right = st.columns([3, 1])
with _hdr_right:
    selected_period = st.selectbox('Time Window', time_options, index=6, label_visibility='collapsed')

if   selected_period == 'All Time':      start_date = df['Date'].min()
elif selected_period == 'YTD':           start_date = pd.Timestamp(latest_date.year, 1, 1)
elif selected_period == 'Last 5 Days':   start_date = latest_date - timedelta(days=5)
elif selected_period == 'Last Month':    start_date = latest_date - timedelta(days=30)
elif selected_period == 'Last 3 Months': start_date = latest_date - timedelta(days=90)
elif selected_period == 'Half Year':     start_date = latest_date - timedelta(days=182)
elif selected_period == '1 Year':        start_date = latest_date - timedelta(days=365)
else:                                    start_date = df['Date'].min()  # fallback

start_date = max(start_date, df['Date'].min())

df_window = df[df['Date'] >= start_date].copy()
window_label = '🗓 Window: %s → %s (%s)' % (
    start_date.strftime('%d/%m/%Y'), latest_date.strftime('%d/%m/%Y'), selected_period)

with _hdr_left:
    st.markdown("""
        <div class='sync-header'>
            📡 <b>DATA SYNC:</b> %s UTC &nbsp;|&nbsp;
            📅 <b>WINDOW:</b> <span class='highlight-range'>%s</span> → %s (%s)
        </div>
    """ % (latest_date.strftime('%d/%m/%Y %H:%M'),
           start_date.strftime('%d/%m/%Y'),
           latest_date.strftime('%d/%m/%Y'),
           xe(selected_period)), unsafe_allow_html=True)

window_trades_df = closed_trades_df[closed_trades_df['Close Date'] >= start_date].copy() \
    if not closed_trades_df.empty else pd.DataFrame()

# Slice the cached all-time daily P/L series to the current window
_daily_pnl_all = get_daily_pnl(df)
_daily_pnl     = _daily_pnl_all[
    _daily_pnl_all['Date'] >= start_date
].copy()

# ── Windowed P/L (respects time window selector) ──────────────────────────────
# Options: sum all option cash flows in the window (credits + debits)
# Equity: FIFO cost basis via calculate_windowed_equity_pnl() — oldest lot first,
#         partial lot splits handled correctly, pre-window buys tracked
# Income: dividends and net interest are real cash P/L, included here so
#         windowed and all-time totals are computed on the same basis.
_w_opts = df_window[df_window['Instrument Type'].isin(OPT_TYPES) &
                    (df_window['Type'].isin(TRADE_TYPES))]

_eq_pnl       = calculate_windowed_equity_pnl(df, start_date)
_w_div_int    = df_window[df_window['Sub Type'].isin(INCOME_SUB_TYPES)]['Total'].sum()

window_realized_pnl = _w_opts['Total'].sum() + _eq_pnl + _w_div_int

# ── Prior period P/L (for WoW / MoM comparison card) ─────────────────────────
_window_span  = latest_date - start_date
_prior_end    = start_date
_prior_start  = _prior_end - _window_span
_df_prior     = df[(df['Date'] >= _prior_start) & (df['Date'] < _prior_end)].copy()
_prior_opts   = _df_prior[_df_prior['Instrument Type'].isin(OPT_TYPES) &
                           _df_prior['Type'].isin(TRADE_TYPES)]['Total'].sum()
_prior_eq     = calculate_windowed_equity_pnl(df, _prior_start, end_date=_prior_end)
_prior_div_int = _df_prior[_df_prior['Sub Type'].isin(INCOME_SUB_TYPES)]['Total'].sum()
prior_period_pnl = _prior_opts + _prior_eq + _prior_div_int
prior_period_trades = 0
if not closed_trades_df.empty:
    prior_period_trades = closed_trades_df[
        (closed_trades_df['Close Date'] >= _prior_start) &
        (closed_trades_df['Close Date'] < _prior_end)
    ].shape[0]
current_period_trades = 0
if not closed_trades_df.empty:
    current_period_trades = closed_trades_df[
        closed_trades_df['Close Date'] >= start_date
    ].shape[0]

# Income
div_income = df_window[df_window['Sub Type']==SUB_DIVIDEND]['Total'].sum()
int_net    = df_window[df_window['Sub Type'].isin([SUB_CREDIT_INT,SUB_DEBIT_INT])]['Total'].sum()
deb_int    = df_window[df_window['Sub Type']==SUB_DEBIT_INT]['Total'].sum()
reg_fees   = df_window[df_window['Sub Type']=='Balance Adjustment']['Total'].sum()

# Portfolio stats
total_deposited = df[df['Sub Type']=='Deposit']['Total'].sum()
total_withdrawn = df[df['Sub Type']=='Withdrawal']['Total'].sum()
net_deposited   = total_deposited + total_withdrawn
first_date      = df['Date'].min()
account_days    = (latest_date - first_date).days
cash_balance    = df['Total'].cumsum().iloc[-1]
margin_loan     = abs(cash_balance) if cash_balance < 0 else 0.0
realized_ror    = total_realized_pnl / net_deposited * 100 if net_deposited > 0 else 0.0

# ── Window label helper — used in section titles throughout ───────────────────
_win_start_str = start_date.strftime('%d/%m/%Y')
_win_end_str   = latest_date.strftime('%d/%m/%Y')
_win_label     = (f'<span style="font-size:0.75rem;font-weight:400;color:#58a6ff;'
                  f'letter-spacing:0.02em;margin-left:8px;">'
                  f'{_win_start_str} → {_win_end_str} ({selected_period})</span>')
# Plain text version for plotly chart titles (no HTML)
_win_suffix    = f'  ·  {_win_start_str} → {_win_end_str}'

# ── Debug export (for test suite comparison) ──────────────────────────────────
# Only runs when the environment variable TASTYMECHANICS_TEST=1 is set.
# Writes app_snapshot.json to the same folder as the running script.
# Normal users never see this — it is a no-op in production.
if _os.environ.get('TASTYMECHANICS_TEST') == '1':
    def _campaign_snapshot(camps):
        return [dict(
            ticker=c.ticker, status=c.status,
            shares=c.total_shares, cost=round(c.total_cost, 4),
            basis=round(c.blended_basis, 4),
            premiums=round(c.premiums, 4),
            dividends=round(c.dividends, 4),
            exit_proceeds=round(c.exit_proceeds, 4),
            pnl=round(realized_pnl(c), 4),
        ) for c in camps]

    _snapshot = {
        # ── Headline P/L figures ──
        'total_realized_pnl':    round(total_realized_pnl, 4),
        'window_realized_pnl':   round(window_realized_pnl, 4),
        'prior_period_pnl':      round(prior_period_pnl, 4),
        'selected_period':       selected_period,
        # ── Components ──
        'closed_camp_pnl':       round(closed_camp_pnl, 4),
        'open_premiums_banked':  round(open_premiums_banked, 4),
        'pure_opts_pnl':         round(pure_opts_pnl, 4),
        'all_time_income':       round(_all_time_income, 4),
        'wheel_divs_in_camps':   round(_wheel_divs_in_camps, 4),
        # ── Window components ──
        'w_opts_total':          round(_w_opts['Total'].sum(), 4),
        'w_eq_pnl':              round(_eq_pnl, 4),
        'w_div_int':             round(_w_div_int, 4),
        # ── Portfolio stats ──
        'total_deposited':       round(total_deposited, 4),
        'total_withdrawn':       round(total_withdrawn, 4),
        'net_deposited':         round(net_deposited, 4),
        'capital_deployed':      round(capital_deployed, 4),
        'realized_ror':          round(realized_ror, 4),
        'div_income':            round(div_income, 4),
        'int_net':               round(int_net, 4),
        # ── Campaigns ──
        'campaigns':             {t: _campaign_snapshot(c) for t, c in all_campaigns.items()},
        # ── Per-ticker options P/L ──
        'pure_opts_per_ticker':  {t: round(v, 4) for t, v in pure_opts_per_ticker.items()},
        'wheel_tickers':         wheel_tickers,
        'pure_options_tickers':  pure_options_tickers,
        # ── Open positions ──
        'open_positions': {
            t: {
                'net_qty': round(
                    df[(df['Ticker']==t) & (df['Instrument Type'].str.strip()=='Equity')]['Net_Qty_Row'].sum(), 4
                )
            }
            for t in (wheel_tickers + [
                t for t in df['Ticker'].unique()
                if t not in wheel_tickers + ['CASH']
                and df[(df['Ticker']==t) & (df['Instrument Type'].str.strip()=='Equity')]['Net_Qty_Row'].sum() > 0.001
            ])
        },
        # ── Metadata ──
        'csv_rows':    len(df),
        'latest_date': latest_date.strftime('%Y-%m-%d'),
        'app_version': APP_VERSION,
    }
    _out = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'app_snapshot.json')
    with open(_out, 'w') as _f:
        _json.dump(_snapshot, _f, indent=2)
    st.info(f'🧪 Test snapshot written → `{_out}`')

# ── TOP METRICS ────────────────────────────────────────────────────────────────

st.markdown(f'### 📊 Portfolio Overview {_win_label}', unsafe_allow_html=True)
_is_all_time    = selected_period == 'All Time'
_is_short_window = selected_period in ['Last 5 Days', 'Last Month', 'Last 3 Months']
_pnl_display    = total_realized_pnl if _is_all_time else window_realized_pnl
_ror_display    = _pnl_display / net_deposited * 100 if net_deposited > 0 else 0.0
# Capital Efficiency Score — annualised return on capital currently deployed
# Uses window P/L and window days so it responds to time selector
_window_days_int = max((latest_date - start_date).days, 1)
cap_eff_score = (_pnl_display / capital_deployed / _window_days_int * 365 * 100)     if capital_deployed > 0 else 0.0

m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
m1.metric('Realized P/L',    '$%.2f' % _pnl_display)
m1.caption('All cash actually banked — options P/L, share sales, premiums collected. Filtered to selected time window. Unrealised share P/L not included.')
m2.metric('Realized ROR',    '%.1f%%' % _ror_display)
m2.caption('Realized P/L as a % of net deposits. How hard your deposited capital is working.')

if _is_short_window:
    st.warning(
        '⚠️ **Short window — Realized P/L may be misleading.** '
        'This view shows raw cash flows in the selected window. '
        'If a trade was *opened* in a previous window and *closed* in this one, '
        'only the buyback cost appears here — the original credit is in an earlier window. '
        'This can make an actively managed period look like a loss even when the underlying trades are profitable. '
        '**All Time or YTD give the most reliable P/L picture.**'
    )
m3.metric('Cap Efficiency',  '%.1f%%' % cap_eff_score)
m3.caption('Annualised return on capital deployed in shares — (Realized P/L ÷ Capital Deployed) × 365. Benchmark: S&P ~10%/yr. Shows if your wheel is outperforming simple buy-and-hold on the same capital.')
m4.metric('Capital Deployed','$%.2f' % capital_deployed)
m4.caption('Cash tied up in open share positions (wheel campaigns + any fractional holdings). Options margin not included.')
m5.metric('Margin Loan',     '$%.2f' % margin_loan)
m5.caption('Negative cash balance — what you currently owe the broker. Zero is ideal unless deliberately leveraging.')
m6.metric('Div + Interest',  '$%.2f' % (div_income + int_net))
m6.caption('Dividends received plus net interest (credit earned minus debit charged on margin). Filtered to selected time window.')
m7.metric('Account Age',     '%d days' % account_days)
m7.caption('Days since your first transaction. Useful context for how long your track record covers.')


# ── Realized P/L Breakdown — inline chip line ─────────────────────────────────
if _is_all_time:
    _breakdown_html = (
        _pnl_chip('Closed Wheel Campaigns', closed_camp_pnl) +
        _pnl_chip('Open Wheel Premiums', open_premiums_banked) +
        _pnl_chip('General Standalone Trading', pure_opts_pnl) +
        f'<span style="color:#4b5563;margin:0 6px;font-size:0.78rem;">·</span>'
        f'<span style="color:#8b949e;font-size:0.78rem;font-style:italic;">All Time</span>'
    )
else:
    _w_opts_only = _w_opts['Total'].sum()
    _breakdown_html = (
        _pnl_chip('Wheel & Options Trading', _w_opts_only) +
        _pnl_chip('Equity Sales', _eq_pnl) +
        _pnl_chip('Div + Interest', div_income + int_net)
    )

st.markdown(
    f'<div style="margin:-6px 0 10px 0;display:flex;flex-wrap:wrap;align-items:center;">'
    f'{_breakdown_html}</div>',
    unsafe_allow_html=True
)



# ── Period Comparison Card ─────────────────────────────────────────────────────
if selected_period != 'All Time' and not _df_prior.empty:
    _pnl_delta  = _pnl_display - prior_period_pnl
    _delta_sign = '+' if _pnl_delta >= 0 else ''
    _delta_col  = '#00cc96' if _pnl_delta >= 0 else '#ef553b'
    _arrow      = '▲' if _pnl_delta >= 0 else '▼'
    _period_lbl = selected_period.replace('Last ','').replace('YTD','Year-to-date')

    _curr_wr, _prev_wr = 0.0, 0.0
    if not closed_trades_df.empty:
        _cw = closed_trades_df[closed_trades_df['Close Date'] >= start_date]
        _pw = closed_trades_df[(closed_trades_df['Close Date'] >= _prior_start) &
                               (closed_trades_df['Close Date'] < _prior_end)]
        _curr_wr = _cw['Won'].mean() * 100 if not _cw.empty else 0.0
        _prev_wr = _pw['Won'].mean() * 100 if not _pw.empty else 0.0

    _curr_div = df_window[df_window['Sub Type']==SUB_DIVIDEND]['Total'].sum()
    _prev_div = _df_prior[_df_prior['Sub Type']==SUB_DIVIDEND]['Total'].sum()

    blocks = (
        _cmp_block('Realized P/L', _pnl_display, prior_period_pnl) +
        _cmp_block('Trades Closed', current_period_trades, prior_period_trades, is_pct=False) +
        _cmp_block('Win Rate', _curr_wr, _prev_wr, is_pct=True) +
        _cmp_block('Dividends', _curr_div, _prev_div)
    )

    st.markdown(
        f'<div style="background:linear-gradient(135deg,#111827,#0f1520);border:1px solid #1f2937;'
        f'border-radius:10px;padding:14px 18px;margin:0 0 20px 0;">'
        f'<div style="color:#8b949e;font-size:0.72rem;text-transform:uppercase;'
        f'letter-spacing:0.06em;margin-bottom:10px;">'
        f'📅 {selected_period} vs prior {_period_lbl}</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:0;">{blocks}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

# ── Shared derived slices — computed once, used by Tabs 1 and 2 ───────────────
# all_cdf: closed trades filtered to current time window (falls back to all-time
#          if the window contains no closed trades — avoids empty chart state).
all_cdf    = window_trades_df if not window_trades_df.empty else closed_trades_df
credit_cdf = all_cdf[all_cdf['Is Credit']].copy() if not all_cdf.empty else pd.DataFrame()
has_credit = not credit_cdf.empty
has_data   = not all_cdf.empty

# ── TABS ───────────────────────────────────────────────────────────────────────
tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs([
    '📡 Open Positions',
    '📈 Derivatives Performance',
    '🔬 Trade Analysis',
    '🎯 Wheel Campaigns',
    '🔍 All Trades',
    '💰 Deposits, Dividends & Fees'
])

# ── Tab 0: Active Positions ────────────────────────────────────────────────────
with tab0:
    st.subheader('📡 Open Positions')
    if df_open.empty:
        st.info('No active positions.')
    else:
        df_open['Status']  = df_open.apply(identify_pos_type, axis=1)
        df_open['Details'] = df_open.apply(translate_readable, axis=1)

        df_open['DTE'] = df_open.apply(lambda row: calc_dte(row, latest_date), axis=1)
        tickers_open = [t for t in sorted(df_open['Ticker'].unique()) if t != 'CASH']

        # Summary strip — count of positions and strategies
        n_options = df_open[option_mask(df_open['Instrument Type'])].shape[0]
        n_shares  = df_open[equity_mask(df_open['Instrument Type'])].shape[0]
        strategies = [detect_strategy(df_open[df_open['Ticker']==t]) for t in tickers_open]
        unique_strats = list(dict.fromkeys(strategies))  # preserve order

        summary_pills = ''.join(
            f'<span style="display:inline-block;background:rgba(88,166,255,0.1);border:1px solid rgba(88,166,255,0.2);'
            f'border-radius:20px;padding:2px 10px;font-size:0.75rem;color:#58a6ff;margin-right:6px;margin-bottom:6px;">{s}</span>'
            for s in unique_strats
        )
        st.markdown(
            f'<div style="margin-bottom:20px;color:#6b7280;font-size:0.85rem;">'
            f'<b style="color:#8b949e">{len(tickers_open)}</b> tickers &nbsp;·&nbsp; '
            f'<b style="color:#8b949e">{n_options}</b> option legs &nbsp;·&nbsp; '
            f'<b style="color:#8b949e">{n_shares}</b> share positions'
            f'</div>'
            f'<div style="margin-bottom:24px;">{summary_pills}</div>',
            unsafe_allow_html=True
        )

        # ── Expiry Alert Strip ─────────────────────────────────────────────
        if _expiry_alerts:
            _expiry_chips = ''.join(_dte_chip(a) for a in _expiry_alerts)
            st.markdown(
                f'<div style="margin:-4px 0 16px 0;display:flex;flex-wrap:wrap;align-items:center;">'
                f'<span style="color:#6b7280;font-size:0.75rem;margin-right:8px;">⏰ Expiring ≤21d</span>'
                f'{_expiry_chips}</div>',
                unsafe_allow_html=True
            )

        # 2-column card grid
        col_a, col_b = st.columns(2, gap='medium')
        for i, ticker in enumerate(tickers_open):
            t_df = df_open[df_open['Ticker'] == ticker].copy()
            card_html = render_position_card(ticker, t_df)
            if i % 2 == 0:
                col_a.markdown(card_html, unsafe_allow_html=True)
            else:
                col_b.markdown(card_html, unsafe_allow_html=True)

# ── Tab 1: Derivatives Performance ────────────────────────────────────────────
with tab1:
    if closed_trades_df.empty:
        st.info('No closed trades found.')
    else:
        st.info(window_label)
        st.markdown(f'#### 🎯 Premium Selling Scorecard {_win_label}', unsafe_allow_html=True)
        st.caption(
            'Credit trades only. '
            '**Win Rate** = % of trades closed positive, regardless of size. '
            '**Median Capture %** = typical % of opening credit kept at close — TastyTrade targets 50%. '
            '**Median Days Held** = typical time in a trade, resistant to outliers. '
            '**Median Ann. Return** = typical annualised return on capital at risk, capped at ±500% to prevent '
            '0DTE trades producing meaningless numbers — treat with caution on small sample sizes. '
            '**Med Premium/Day** = median credit-per-day across individual trades — your typical theta capture rate per trade, '
            'but skewed upward by short-dated trades where large credits are divided by very few days. '
            '**Banked $/Day** = realized P/L divided by window days — what you actually kept after all buybacks. '
            'The delta shows the gross credit rate for context — the gap between the two is your buyback cost. '
            'This is the number to compare against income needs or running costs.'
        )
        dm1, dm2, dm3, dm4, dm5, dm6 = st.columns(6)
        if has_credit:
            total_credit_rcvd    = credit_cdf['Premium Rcvd'].sum()
            total_net_pnl_closed = credit_cdf['Net P/L'].sum()
            window_days = max((latest_date - start_date).days, 1)
            dm1.metric('Win Rate',           '%.1f%%' % (credit_cdf['Won'].mean() * 100))
            dm2.metric('Median Capture %',   '%.1f%%' % credit_cdf['Capture %'].median())
            dm3.metric('Median Days Held',   '%.0f'   % credit_cdf['Days Held'].median())
            dm4.metric('Median Ann. Return', '%.0f%%' % credit_cdf['Ann Return %'].median())
            dm5.metric('Med Premium/Day',    '$%.2f'  % credit_cdf['Prem/Day'].median())
            dm6.metric('Banked $/Day', '$%.2f' % (total_net_pnl_closed / window_days),
                delta='vs $%.2f gross' % (total_credit_rcvd / window_days),
                delta_color='normal')

            # ── Row 2: Avg Winner / Avg Loser / Fees ──────────────────────
            _winners = all_cdf[all_cdf['Net P/L'] > 0]['Net P/L']
            _losers  = all_cdf[all_cdf['Net P/L'] < 0]['Net P/L']
            _avg_win  = _winners.mean() if not _winners.empty else 0.0
            _avg_loss = _losers.mean()  if not _losers.empty  else 0.0
            _ratio    = abs(_avg_win / _avg_loss) if _avg_loss != 0 else 0.0

            # Fees: commissions + fees on all option trades in window
            _w_option_rows = df_window[
                df_window['Instrument Type'].isin(OPT_TYPES) &
                df_window['Type'].isin(TRADE_TYPES)
            ]
            _total_fees = (_w_option_rows['Commissions'].apply(abs).sum() +
                           _w_option_rows['Fees'].apply(abs).sum())
            _fees_pct   = (_total_fees / abs(total_net_pnl_closed) * 100
                           if total_net_pnl_closed != 0 else 0.0)

            st.markdown('---')
            r1, r2, r3, r4, r5, r6 = st.columns(6)
            r1.metric('Avg Winner',   '$%.2f' % _avg_win)
            r1.caption('Mean P/L of all winning trades. Compare to Avg Loser — you want this number meaningfully larger.')
            r2.metric('Avg Loser',    '$%.2f' % _avg_loss)
            r2.caption('Mean P/L of all losing trades. A healthy system has avg loss smaller than avg win, even at high win rates.')
            r3.metric('Win/Loss Ratio', '%.2fx' % _ratio)
            r3.caption('Avg Winner ÷ Avg Loser. Above 1.0 means your wins are larger than your losses on average. TastyTrade targets >1.0 at lower win rates, or compensates with high win rate if below 1.0.')
            r4.metric('Total Fees',   '$%.2f' % _total_fees)
            r4.caption('Commissions + exchange fees on option trades in this window. The silent drag on every trade.')
            r5.metric('Fees % of P/L', '%.1f%%' % _fees_pct)
            r5.caption('Total fees as a percentage of net realized P/L. Under 10% is healthy. High on 0DTE or frequent small trades — fees eat a larger slice of smaller credits.')
            r6.metric('Fees/Trade',   '$%.2f' % (_total_fees / len(all_cdf) if len(all_cdf) > 0 else 0))
            r6.caption('Average fee cost per closed trade. Useful for comparing cost efficiency across strategies — defined risk spreads cost more per trade than naked puts.')
        else:
            st.info('No closed credit trades in this window.')

        if has_data:
            st.markdown('---')
            col1, col2 = st.columns(2)
            with col1:
                if has_credit:
                    bins   = [-999, 0, 25, 50, 75, 100, 999]
                    labels = ['Loss', '0–25%', '25–50%', '50–75%', '75–100%', '>100%']
                    credit_cdf['Bucket'] = pd.cut(credit_cdf['Capture %'], bins=bins, labels=labels)
                    bucket_df = credit_cdf.groupby('Bucket', observed=False).agg(
                        Trades=('Net P/L', 'count')).reset_index()
                    colors = ['#ef553b','#ffa421','#ffe066','#7ec8e3','#00cc96','#58a6ff']
                    fig_cap = px.bar(bucket_df, x='Bucket', y='Trades', color='Bucket',
                        color_discrete_sequence=colors, text='Trades')
                    fig_cap.update_traces(textposition='outside', textfont_size=11, marker_line_width=0)
                    _lay = chart_layout('Premium Capture % Distribution' + _win_suffix, height=320, margin_t=40)
                    _lay['showlegend'] = False
                    _lay['xaxis']['title'] = dict(text='Capture Bucket', font=dict(size=11))
                    _lay['yaxis']['title'] = dict(text='# Trades', font=dict(size=11))
                    fig_cap.update_layout(**_lay)
                    st.plotly_chart(fig_cap, width='stretch', config={'displayModeBar': False})

            with col2:
                if has_credit:
                    type_df = credit_cdf.groupby('Type').agg(
                        Trades=('Won', 'count'),
                        Win_Rate=('Won', lambda x: x.mean()*100),
                        Med_Capture=('Capture %', 'median'),
                        Total_PNL=('Net P/L', 'sum'),
                        Avg_PremDay=('Prem/Day', 'mean'),
                        Med_Days=('Days Held', 'median'),
                        Med_DTE=('DTE Open', 'median'),
                    ).reset_index().round(1)
                    type_df.columns = ['Type','Trades','Win %','Capture %','P/L','Prem/Day','Days','DTE']
                    st.markdown(f'##### 📊 Call vs Put Performance {_win_label}', unsafe_allow_html=True)
                    st.caption('Do you perform better selling calls or puts? Skew, IV rank and stock direction all affect which side pays more. Mixed = multi-leg trades with both calls and puts (strangles, iron condors, lizards). Knowing your edge by type helps you lean into your strengths.')
                    st.dataframe(type_df.style.format({
                        'Win %': lambda x: '{:.1f}%'.format(x),
                        'Capture %': lambda x: '{:.1f}%'.format(x),
                        'P/L': lambda x: '${:,.2f}'.format(x),
                        'Prem/Day': lambda x: '${:.2f}'.format(x),
                        'Days': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                        'DTE': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                    }).map(color_win_rate, subset=['Win %'])
                    .map(lambda v: 'color: #00cc96' if isinstance(v,(int,float)) and v>0
                        else ('color: #ef553b' if isinstance(v,(int,float)) and v<0 else ''),
                        subset=['P/L']),
                    width='stretch', hide_index=True)

            if has_data and has_credit:
                strat_df = all_cdf.groupby('Trade Type').agg(
                    Trades=('Won','count'),
                    Win_Rate=('Won', lambda x: x.mean()*100),
                    Total_PNL=('Net P/L','sum'),
                    Med_Capture=('Capture %','median'),
                    Med_Days=('Days Held','median'),
                    Med_DTE=('DTE Open','median'),
                ).reset_index().sort_values('Total_PNL', ascending=False).round(1)
                strat_df.columns = ['Strategy','Trades','Win %','P/L','Capture %','Days','DTE']
                st.markdown(f'##### 🧩 Defined vs Undefined Risk — by Strategy {_win_label}', unsafe_allow_html=True)
                st.caption('All closed trades — credit and debit. Naked = undefined risk, higher premium. Spreads/Condors = defined max loss, less credit. Debit spreads show P/L but no capture % (not applicable). Are your defined-risk trades worth the premium you give up for the protection?')
                st.dataframe(strat_df.style.format({
                    'Win %': lambda x: '{:.1f}%'.format(x),
                    'Capture %': lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                    'P/L': lambda x: '${:,.2f}'.format(x),
                    'Days': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                    'DTE': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                }).map(color_win_rate, subset=['Win %'])
                .map(lambda v: 'color: #00cc96' if isinstance(v,(int,float)) and v>0
                    else ('color: #ef553b' if isinstance(v,(int,float)) and v<0 else ''),
                    subset=['P/L']),
                width='stretch', hide_index=True)

            st.markdown('---')
            st.markdown(f'#### Performance by Ticker {_win_label}', unsafe_allow_html=True)
            st.caption(
                'All closed trades — credit and debit — grouped by underlying. '
                '**Win %** counts any trade that closed positive, regardless of size. '
                '**Total P/L** is your actual net result after all opens and closes on that ticker. '
                '**Med Days** = median holding period across all trades. '
                '**Med Capture %** = median percentage of opening credit kept at close — credit trades only. '
                'TastyTrade targets 50% capture. '
                '**Med Ann Ret %** = median annualised return on capital at risk, capped at ±500%. '
                '**Total Credit Rcvd** = gross cash received when opening credit trades.'
            )

            all_by_ticker = all_cdf.groupby('Ticker').agg(
                Trades=('Net P/L', 'count'),
                Win_Rate=('Won', lambda x: x.mean()*100),
                Total_PNL=('Net P/L', 'sum'),
                Med_Days=('Days Held', 'median'),
            ).round(1)

            if has_credit:
                credit_by_ticker = credit_cdf.groupby('Ticker').agg(
                    Med_Capture=('Capture %', 'median'),
                    Med_Ann=('Ann Return %', 'median'),
                    Total_Prem=('Premium Rcvd', 'sum'),
                ).round(1)
                ticker_df = all_by_ticker.join(credit_by_ticker, how='left').reset_index()
            else:
                ticker_df = all_by_ticker.reset_index()
                ticker_df['Med_Capture'] = None
                ticker_df['Med_Ann']     = None
                ticker_df['Total_Prem']  = None

            ticker_df = ticker_df.sort_values('Total_PNL', ascending=False)
            ticker_df.columns = ['Ticker','Trades','Win %','P/L','Days',
                                 'Capture %','Ann Ret %','Credit Rcvd']
            st.dataframe(
                ticker_df.style.format({
                    'Win %': lambda x: '{:.1f}%'.format(x),
                    'P/L': lambda x: '${:,.2f}'.format(x),
                    'Days': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                    'Capture %': lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                    'Ann Ret %': lambda v: '{:.0f}%'.format(v) if pd.notna(v) else '—',
                    'Credit Rcvd': lambda v: '${:.2f}'.format(v) if pd.notna(v) else '—'
                }).map(color_win_rate, subset=['Win %'])
                .map(color_pnl_cell, subset=['P/L']),
                width='stretch', hide_index=True
            )


# ── Tab 2: Trade Analysis ────────────────────────────────────────────────────
with tab2:
    if closed_trades_df.empty:
        st.info('No closed trades found.')
    else:
        st.markdown(f'### 🔬 Trade Analysis {_win_label}', unsafe_allow_html=True)

        st.markdown('---')
        # ── ThetaGang Metrics ─────────────────────────────────────────────
        st.markdown(f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">🎯 ThetaGang Metrics {_win_label}</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:0.8rem;color:#6b7280;margin-bottom:16px;line-height:1.5;">Metrics specific to theta selling strategy — management discipline, DTE behaviour, portfolio concentration, and win rate trend.</div>', unsafe_allow_html=True)

        if has_data and has_credit:
            _tg_opts = df_window[df_window['Instrument Type'].isin(OPT_TYPES)]
            _tg_closes = _tg_opts[_tg_opts['Sub Type'].str.lower().str.contains(PAT_CLOSING, na=False)].copy()
            _tg_closes['Exp'] = pd.to_datetime(_tg_closes['Expiration Date'], format='mixed', errors='coerce').dt.normalize()
            _tg_closes['DTE_close'] = (_tg_closes['Exp'] - _tg_closes['Date']).dt.days.clip(lower=0)

            # ── Separate LEAPS (DTE at open > 90) from short-premium trades ──────
            # LEAPS have fundamentally different holding periods and theta profiles.
            # Including them would inflate median DTE at open, skew the DTE-at-close
            # distribution, and pollute management rate — so ThetaGang metrics run
            # on short-premium trades only (DTE Open <= 90). LEAPS are surfaced below
            # as a separate informational callout.
            LEAPS_DTE_THRESHOLD = 90
            _leaps_cdf  = credit_cdf[credit_cdf['DTE Open'] > LEAPS_DTE_THRESHOLD] \
                if 'DTE Open' in credit_cdf.columns else pd.DataFrame()
            _short_cdf  = credit_cdf[credit_cdf['DTE Open'] <= LEAPS_DTE_THRESHOLD] \
                if 'DTE Open' in credit_cdf.columns else credit_cdf

            # Also exclude LEAPS close events from _tg_closes for management rate / DTE chart.
            # A close event belongs to a LEAPS trade if its expiry was >90d away at open.
            # We approximate: if DTE_close > 90 at time of closing, it was almost certainly
            # opened with even more DTE and is a LEAPS position.
            _tg_closes_short = _tg_closes[
                _tg_closes['DTE_close'].isna() | (_tg_closes['DTE_close'] <= LEAPS_DTE_THRESHOLD)
            ]

            # ── 1. Management Rate (short-premium only) ────────────────────
            _n_expired   = (_tg_closes_short['Sub Type'].str.lower().str.contains('expir|assign|exercise')).sum()
            _n_managed   = (_tg_closes_short['Sub Type'].str.lower().str.contains(PAT_CLOSE)).sum()
            _n_total_cls = len(_tg_closes_short)
            _mgmt_rate   = _n_managed / _n_total_cls * 100 if _n_total_cls > 0 else 0

            # ── 2. DTE at close distribution (short-premium only) ──────────
            _dte_valid = _tg_closes_short.dropna(subset=['DTE_close'])
            _med_dte_close = _dte_valid['DTE_close'].median() if not _dte_valid.empty else 0
            _med_dte_open  = _short_cdf['DTE Open'].median() \
                if ('DTE Open' in _short_cdf.columns and not _short_cdf.empty) else 0

            # ── 3. Concentration score ─────────────────────────────────────
            _tg_sto = _tg_opts[_tg_opts['Sub Type'].str.lower() == SUB_SELL_OPEN]
            _by_tkr = _tg_sto.groupby('Ticker')['Total'].sum().sort_values(ascending=False)
            _total_prem_conc = _by_tkr.sum()
            _top3_pct = _by_tkr.head(3).sum() / _total_prem_conc * 100 if _total_prem_conc > 0 else 0
            _top3_names = ', '.join(_by_tkr.head(3).index.tolist())

            # ── 4. Rolling 10-trade win rate ──────────────────────────────
            _roll_cdf = all_cdf.sort_values('Close Date').copy()
            _roll_cdf['Rolling_WR'] = _roll_cdf['Won'].rolling(10, min_periods=5).mean() * 100

            # ── Metrics row ───────────────────────────────────────────────
            tg1, tg2, tg3, tg4 = st.columns(4)
            tg1.metric('Management Rate', '%.0f%%' % _mgmt_rate,
                delta='%d managed, %d expired/assigned' % (_n_managed, _n_expired),
                delta_color='off')
            tg1.caption('% of trades actively closed early vs left to expire/assign. TastyTrade targets closing at 50%% max profit — high management rate = good discipline. LEAPS excluded.')

            tg2.metric('Median DTE at Open', '%.0fd' % _med_dte_open)
            tg2.caption('Median days-to-expiry when trades were opened. TastyTrade targets 30–45 DTE for optimal theta decay curve. LEAPS (>90 DTE) excluded.')

            tg3.metric('Median DTE at Close', '%.0fd' % _med_dte_close)
            tg3.caption('Median days-to-expiry remaining when trades were closed. Closing around 14–21 DTE captures most theta while avoiding gamma risk. LEAPS excluded.')

            _conc_color = '⚠️' if _top3_pct > 60 else '✅'
            tg4.metric('Top 3 Concentration', '%.0f%%' % _top3_pct)
            tg4.caption(f'{_conc_color} {_top3_names} — top 3 tickers as %% of total premium collected. Above 60%% means heavy concentration risk if correlated.')

            # ── LEAPS callout (shown only when LEAPS trades exist in window) ──
            if not _leaps_cdf.empty:
                _leaps_pnl    = _leaps_cdf['Net P/L'].sum()
                _leaps_wr     = _leaps_cdf['Won'].mean() * 100
                _leaps_count  = len(_leaps_cdf)
                _leaps_tickers = ', '.join(sorted(_leaps_cdf['Ticker'].unique().tolist()))
                _lc = '#00cc96' if _leaps_pnl >= 0 else '#ef553b'
                _lpnl_str = ('$%.2f' % _leaps_pnl) if _leaps_pnl >= 0 else ('-$%.2f' % abs(_leaps_pnl))
                st.markdown(
                    f'<div style="background:rgba(88,166,255,0.06);border:1px solid rgba(88,166,255,0.2);'
                    f'border-radius:8px;padding:10px 16px;margin:12px 0 0 0;font-size:0.82rem;color:#8b949e;">'
                    f'<span style="color:#58a6ff;font-weight:600;">📅 LEAPS detected</span>'
                    f' &nbsp;·&nbsp; {_leaps_count} trade(s) with DTE &gt; {LEAPS_DTE_THRESHOLD}d at open'
                    f' &nbsp;·&nbsp; Tickers: <span style="color:#c9d1d9;">{xe(_leaps_tickers)}</span>'
                    f' &nbsp;·&nbsp; Net P/L: <span style="color:{_lc};font-family:monospace;">{_lpnl_str}</span>'
                    f' &nbsp;·&nbsp; Win Rate: <span style="color:#c9d1d9;">{_leaps_wr:.0f}%</span>'
                    f' &nbsp;·&nbsp; <span style="font-style:italic;">Excluded from ThetaGang metrics above to avoid skewing DTE stats.</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )

            # ── DTE distribution chart ─────────────────────────────────────
            st.markdown('---')
            _tg_col1, _tg_col2 = st.columns(2)

            with _tg_col1:
                if not _dte_valid.empty:
                    _dte_bins   = [-1, 0, 7, 14, 21, 30, 999]
                    _dte_labels = ['0 (expired)', '1–7d', '8–14d', '15–21d', '22–30d', '>30d']
                    _dte_valid = _dte_valid.copy()  # already filtered to short-premium by _tg_closes_short above
                    _dte_valid['Bucket'] = pd.cut(_dte_valid['DTE_close'], bins=_dte_bins, labels=_dte_labels)
                    _dte_dist = _dte_valid['Bucket'].value_counts().reindex(_dte_labels, fill_value=0).reset_index()
                    _dte_dist.columns = ['DTE Bucket', 'Trades']
                    # Highlight the target zone (14-21d) in blue, rest grey
                    _dte_colors = ['#58a6ff' if b in ['8–14d','15–21d'] else '#30363d' for b in _dte_labels]
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
                    _fig_rwr.add_hline(y=50, line_dash='dash', line_color='rgba(255,255,255,0.15)', line_width=1)
                    _fig_rwr.add_trace(go.Scatter(
                        x=_roll_cdf['Close Date'], y=_roll_cdf['Rolling_WR'],
                        mode='lines', line=dict(color='#58a6ff', width=2),
                        fill='tozeroy', fillcolor='rgba(88,166,255,0.08)',
                        hovertemplate='%{x|%d/%m/%y}<br>Win Rate: <b>%{y:.1f}%</b><extra></extra>'
                    ))
                    _fig_rwr.add_hline(y=_roll_cdf['Won'].mean()*100,
                        line_dash='dot', line_color='#ffa421', line_width=1.5,
                        annotation_text='avg %.0f%%' % (_roll_cdf['Won'].mean()*100),
                        annotation_position='bottom right',
                        annotation_font=dict(color='#ffa421', size=11))
                    _rwr_lay = chart_layout('Rolling Win Rate · 10-trade window' + _win_suffix, height=300, margin_t=40)
                    _rwr_lay['yaxis']['ticksuffix'] = '%'
                    _rwr_lay['yaxis']['range'] = [0, 105]
                    _fig_rwr.update_layout(**_rwr_lay)
                    st.plotly_chart(_fig_rwr, width='stretch', config={'displayModeBar': False})
                    st.caption('Rolling 10-trade win rate over time. Amber = overall average. A rising trend means your edge is improving.')

        st.markdown('---')
        # ── Week-over-Week / Month-over-Month P/L bar chart ───────────────
        st.markdown(f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">📅 Options P/L by Week &amp; Month {_win_label}</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:0.8rem;color:#6b7280;margin-bottom:12px;line-height:1.5;"><b style="color:#58a6ff;">Options trades only</b> — net P/L from closed equity &amp; futures options, grouped by the date the trade closed. Excludes share sales, dividends, and interest. See the <b>All Trades</b> tab for total portfolio P/L by period.</div>', unsafe_allow_html=True)

        _period_df = all_cdf.copy()
        _period_df['CloseDate'] = pd.to_datetime(_period_df['Close Date'])
        _period_df['Week']  = _period_df['CloseDate'].dt.to_period('W').apply(lambda p: p.start_time)
        _period_df['Month'] = _period_df['CloseDate'].dt.to_period('M').apply(lambda p: p.start_time)

        _pcol1, _pcol2 = st.columns(2)

        with _pcol1:
            _weekly = _period_df.groupby('Week')['Net P/L'].sum().reset_index()
            _weekly['Week'] = pd.to_datetime(_weekly['Week'])
            _weekly['Colour'] = _weekly['Net P/L'].apply(lambda x: '#00cc96' if x >= 0 else '#ef553b')
            _fig_wk = go.Figure()
            _fig_wk.add_trace(go.Bar(
                x=_weekly['Week'], y=_weekly['Net P/L'],
                marker_color=_weekly['Colour'],
                marker_line_width=0,
                customdata=[f'${v:,.2f}' if v >= 0 else f'-${abs(v):,.2f}' for v in _weekly['Net P/L']],
                hovertemplate='Week of %{x|%d %b}<br><b>%{customdata}</b><extra></extra>'
            ))
            _fig_wk.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
            _wk_lay = chart_layout('Weekly P/L' + _win_suffix, height=280, margin_t=36)
            _wk_lay['yaxis']['tickprefix'] = '$'
            _wk_lay['yaxis']['tickformat'] = ',.0f'
            _wk_lay['bargap'] = 0.25
            _fig_wk.update_layout(**_wk_lay)
            st.plotly_chart(_fig_wk, width='stretch', config={'displayModeBar': False})

        with _pcol2:
            _monthly = _period_df.groupby('Month')['Net P/L'].sum().reset_index()
            _monthly['Month'] = pd.to_datetime(_monthly['Month'])
            _monthly['Colour'] = _monthly['Net P/L'].apply(lambda x: '#00cc96' if x >= 0 else '#ef553b')
            _monthly['Label'] = _monthly['Month'].dt.strftime('%b %Y')
            _fig_mo = go.Figure()
            _fig_mo.add_trace(go.Bar(
                x=_monthly['Label'], y=_monthly['Net P/L'],
                marker_color=_monthly['Colour'],
                marker_line_width=0,
                text=[f'${v:,.0f}' if v >= 0 else f'-${abs(v):,.0f}' for v in _monthly['Net P/L']],
                customdata=[f'${v:,.2f}' if v >= 0 else f'-${abs(v):,.2f}' for v in _monthly['Net P/L']],
                textposition='outside',
                textfont=dict(size=10, family='IBM Plex Mono', color='#8b949e'),
                hovertemplate='%{x}<br><b>%{customdata}</b><extra></extra>'
            ))
            _fig_mo.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
            _mo_lay = chart_layout('Monthly P/L' + _win_suffix, height=280, margin_t=36)
            _mo_lay['yaxis']['tickprefix'] = '$'
            _mo_lay['yaxis']['tickformat'] = ',.0f'
            _mo_lay['bargap'] = 0.35
            _fig_mo.update_layout(**_mo_lay)
            st.plotly_chart(_fig_mo, width='stretch', config={'displayModeBar': False})

        st.markdown('---')
        cum_df = all_cdf.sort_values('Close Date').copy()
        cum_df['Cumulative P/L'] = cum_df['Net P/L'].cumsum()
        final_pnl = cum_df['Cumulative P/L'].iloc[-1]
        eq_color = '#00cc96' if final_pnl >= 0 else '#ef553b'
        eq_fill  = 'rgba(0,204,150,0.12)' if final_pnl >= 0 else 'rgba(239,85,59,0.12)'
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
                mode='lines', line=dict(color='#58a6ff', width=2),
                fill='tozeroy', fillcolor='rgba(88,166,255,0.08)',
                hovertemplate='%{x|%d/%m/%y}<br>Capture: <b>%{y:.1f}%</b><extra></extra>'
            ))
            fig_cap2.add_hline(y=50, line_dash='dash', line_color='#ffa421', line_width=1.5,
                annotation_text='50% target', annotation_position='bottom right',
                annotation_font=dict(color='#ffa421', size=11))
            _cap2_lay = chart_layout('Rolling Avg Capture % · 10-trade window' + _win_suffix, height=260, margin_t=40)
            _cap2_lay['yaxis']['ticksuffix'] = '%'
            fig_cap2.update_layout(**_cap2_lay)
            st.plotly_chart(fig_cap2, width='stretch', config={'displayModeBar': False})

        st.markdown('---')
        st.markdown(f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">📊 Win / Loss Distribution {_win_label}</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:0.8rem;color:#6b7280;margin-bottom:12px;line-height:1.5;">Each bar is one trade. A healthy theta engine shows many small green bars near zero with losses contained — fat red tails mean outsized losses relative to wins.</div>', unsafe_allow_html=True)
        _hist_df = all_cdf.copy()
        _hist_df['Colour'] = _hist_df['Net P/L'].apply(lambda x: 'Win' if x >= 0 else 'Loss')
        _fig_hist = px.histogram(
            _hist_df, x='Net P/L', color='Colour',
            color_discrete_map={'Win': '#00cc96', 'Loss': '#ef553b'},
            nbins=40,
            labels={'Net P/L': 'Trade P/L ($)', 'count': 'Trades'},
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
        st.markdown(f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">🗓 P/L by Ticker &amp; Month {_win_label}</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:0.8rem;color:#6b7280;margin-bottom:12px;line-height:1.5;">Net P/L per ticker per calendar month (by close date). Green = profitable, red = losing. Intensity shows size. Grey = no closed trades that month.</div>', unsafe_allow_html=True)
        _hm_df = all_cdf.copy()
        _hm_df['Month']     = pd.to_datetime(_hm_df['Close Date']).dt.strftime('%b %Y')
        _hm_df['MonthSort'] = pd.to_datetime(_hm_df['Close Date']).dt.strftime('%Y-%m')
        _hm_pivot = _hm_df.groupby(['Ticker','MonthSort','Month'])['Net P/L'].sum().reset_index()
        _months_sorted  = sorted(_hm_pivot['MonthSort'].unique())
        _month_labels   = [_hm_pivot[_hm_pivot['MonthSort']==m]['Month'].iloc[0] for m in _months_sorted]
        _tickers_sorted = sorted(_hm_pivot['Ticker'].unique(),
            key=lambda t: _hm_pivot[_hm_pivot['Ticker']==t]['Net P/L'].sum(), reverse=True)
        _z = []; _text = []
        for tkr in _tickers_sorted:
            row_z, row_t = [], []
            for ms in _months_sorted:
                val = _hm_pivot[(_hm_pivot['Ticker']==tkr) & (_hm_pivot['MonthSort']==ms)]['Net P/L'].sum()
                row_z.append(val if val != 0 else None)
                row_t.append('$%.0f' % val if val != 0 else '')
            _z.append(row_z); _text.append(row_t)
        _fig_hm = go.Figure(data=go.Heatmap(
            z=_z, x=_month_labels, y=_tickers_sorted,
            text=_text, texttemplate='%{text}', textfont=dict(size=10, family='IBM Plex Mono'),
            colorscale=[
                [0.0,  '#7f1d1d'], [0.35, '#ef553b'],
                [0.5,  '#141c2e'],
                [0.65, '#00cc96'], [1.0,  '#004d3a'],
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
            best = all_cdf.nlargest(5, 'Net P/L')[['Ticker','Trade Type','Type','Days Held','Premium Rcvd','Net P/L']].copy()
            best.columns = ['Ticker','Strategy','C/P','Days','Credit','P/L']
            st.dataframe(best.style.format({
                'Credit': lambda x: '${:.2f}'.format(x),
                'P/L': lambda x: '${:.2f}'.format(x)
            }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)
        with wcol:
            st.markdown(f'##### 💀 Worst 5 Trades {_win_label}', unsafe_allow_html=True)
            worst = all_cdf.nsmallest(5, 'Net P/L')[['Ticker','Trade Type','Type','Days Held','Premium Rcvd','Net P/L']].copy()
            worst.columns = ['Ticker','Strategy','C/P','Days','Credit','P/L']
            st.dataframe(worst.style.format({
                'Credit': lambda x: '${:.2f}'.format(x),
                'P/L': lambda x: '${:.2f}'.format(x)
            }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)

        with st.expander(f'📋 Full Closed Trade Log  ·  {_win_start_str} → {_win_end_str}', expanded=False):
            log = all_cdf[['Ticker','Trade Type','Type','Close Type','Open Date','Close Date',
                           'Days Held','Premium Rcvd','Net P/L','Capture %',
                           'Capital Risk','Ann Return %']].copy()
            # Keep as datetime — do NOT strftime. Streamlit column_config renders
            # them as dates and sorts chronologically, not alphabetically.
            log['Open Date']  = pd.to_datetime(log['Open Date'])
            log['Close Date'] = pd.to_datetime(log['Close Date'])
            log.rename(columns={
                'Trade Type':'Strategy','Type':'C/P','Close Type':'How Closed',
                'Open Date':'Open','Close Date':'Close',
                'Days Held':'Days','Premium Rcvd':'Credit','Net P/L':'P/L',
                'Capital Risk':'Risk','Ann Return %':'Ann Ret %'
            }, inplace=True)
            log = log.sort_values('Close', ascending=False)

            # Append * to Ann Ret % for short-hold trades before styling
            log['Ann Ret %'] = log.apply(_fmt_ann_ret, axis=1)

            st.dataframe(
                log.style.format({
                    'Credit':    lambda x: '${:.2f}'.format(x),
                    'P/L':       lambda x: '${:.2f}'.format(x),
                    'Risk':      lambda x: '${:,.0f}'.format(x),
                    'Capture %': lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                    'Ann Ret %': lambda v: v if isinstance(v, str) else ('{:.0f}%'.format(v) if pd.notna(v) else '—'),
                }).apply(_style_ann_ret, axis=1)
                .map(color_pnl_cell, subset=['P/L']),
                width='stretch', hide_index=True,
                column_config={
                    'Open':  st.column_config.DateColumn('Open',  format='DD/MM/YY'),
                    'Close': st.column_config.DateColumn('Close', format='DD/MM/YY'),
                }
            )
            st.caption('\\* Trades held < 4 days — annualised return may be misleading.')

# ── Tab 3: Wheel Campaigns ─────────────────────────────────────────────────────
with tab3:
    st.subheader('🎯 Wheel Campaign Tracker')
    if use_lifetime:
        st.info("💡 **Lifetime mode** — all history for a ticker combined into one campaign. Effective basis and premiums accumulate across the full holding period without resetting.")
    else:
        st.caption(
            'Tracks each share-holding period as a campaign — starting when you buy 100+ shares, ending when you exit. '
            'Premiums banked from covered calls, covered strangles, and short puts are credited against your cost basis, '
            'reducing your effective break-even over time. Legging in or out of one side (e.g. closing a put while keeping '
            'the covered call) shows naturally as separate call/put chains below. '
            'Campaigns reset when shares hit zero — toggle Lifetime mode to see your full history as one continuous position.'
        )
    if not all_campaigns:
        st.info('No wheel campaigns found.')
    else:
        rows = []
        for ticker, camps in sorted(all_campaigns.items()):
            for i, c in enumerate(camps):
                rpnl = realized_pnl(c, use_lifetime); effb = effective_basis(c, use_lifetime)
                dur  = (c.end_date or latest_date) - c.start_date
                rows.append({'Ticker': ticker, 'Status': '✅ Closed' if c.status=='closed' else '🟢 Open',
                    'Qty': int(c.total_shares), 'Avg Price': c.blended_basis,
                    'Eff. Basis': effb, 'Premiums': c.premiums,
                    'Divs': c.dividends, 'Exit': c.exit_proceeds,
                    'P/L': rpnl, 'Days': dur.days,
                    'Opened': c.start_date.strftime('%d/%m/%y')})
        summary_df = pd.DataFrame(rows)
        st.dataframe(summary_df.style.format({
            'Avg Price': lambda x: '${:,.2f}'.format(x),
            'Eff. Basis': lambda x: '${:,.2f}'.format(x),
            'Premiums': lambda x: '${:,.2f}'.format(x),
            'Divs': lambda x: '${:,.2f}'.format(x),
            'Exit': lambda x: '${:,.2f}'.format(x),
            'P/L': lambda x: '${:,.2f}'.format(x)
        }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)
        st.markdown('---')

        for ticker, camps in sorted(all_campaigns.items()):
            for i, c in enumerate(camps):
                rpnl = realized_pnl(c, use_lifetime); effb = effective_basis(c, use_lifetime)
                is_open  = c.status == 'open'
                status_badge = '🟢 OPEN' if is_open else '✅ CLOSED'
                pnl_color    = '#00cc96' if rpnl >= 0 else '#ef553b'
                basis_reduction = c.blended_basis - effb
                card_html = """
                <div style="border:1px solid {border}; border-radius:10px; padding:16px 20px 12px 20px;
                             margin-bottom:12px; background:rgba(255,255,255,0.03);">
                  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                    <span style="font-size:1.2em; font-weight:700; letter-spacing:0.5px;">{ticker}
                      <span style="font-size:0.75em; font-weight:400; color:#888; margin-left:8px;">Campaign {camp_n}</span>
                    </span>
                    <span style="font-size:0.8em; font-weight:600; padding:3px 10px; border-radius:20px;
                                 background:{badge_bg}; color:{badge_col};">{status}</span>
                  </div>
                  <div style="display:grid; grid-template-columns:repeat(5,1fr); gap:12px; text-align:center;">
                    <div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">SHARES</div>
                         <div style="font-size:1.0em;font-weight:600;">{shares}</div></div>
                    <div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">ENTRY BASIS</div>
                         <div style="font-size:1.0em;font-weight:600;">${entry_basis:.2f}/sh</div></div>
                    <div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">EFF. BASIS</div>
                         <div style="font-size:1.0em;font-weight:600;">${eff_basis:.2f}/sh</div>
                         <div style="font-size:0.7em;color:#00cc96;">▼ ${reduction:.2f} saved</div></div>
                    <div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">PREMIUMS</div>
                         <div style="font-size:1.0em;font-weight:600;">${premiums:.2f}</div></div>
                    <div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">REALIZED P/L</div>
                         <div style="font-size:1.1em;font-weight:700;color:{pnl_color};">${pnl:+.2f}</div></div>
                  </div>
                </div>""".format(
                    border='#00cc96' if is_open else '#444',
                    ticker=xe(ticker), camp_n=i+1, status=xe(status_badge),
                    badge_bg='rgba(0,204,150,0.15)' if is_open else 'rgba(100,100,100,0.2)',
                    badge_col='#00cc96' if is_open else '#888',
                    shares=int(c.total_shares),
                    entry_basis=c.blended_basis, eff_basis=effb,
                    reduction=basis_reduction if basis_reduction > 0 else 0,
                    premiums=c.premiums, pnl=rpnl, pnl_color=pnl_color
                )
                st.markdown(card_html, unsafe_allow_html=True)
                with st.expander('📊 Detail — Chains & Events', expanded=is_open):
                    ticker_opts = df[(df['Ticker']==ticker) &
                        option_mask(df['Instrument Type'])].copy()
                    camp_start = c.start_date
                    camp_end   = c.end_date or latest_date
                    ticker_opts = ticker_opts[
                        (ticker_opts['Date'] >= camp_start) & (ticker_opts['Date'] <= camp_end)
                    ]
                    chains = build_option_chains(ticker_opts)

                    if chains:
                        st.markdown('**📎 Option Roll Chains**')
                        st.caption(
                            'Calls and puts tracked as separate chains — a Covered Strangle appears as two parallel chains, '
                            'closing the put reverts naturally to a Covered Call chain. '
                            'Rolls within ~3 days stay in the same chain; longer gaps start a new one. '
                            '⚠️ Complex structures inside a campaign (PMCC, Diagonals, Jade Lizards, Iron Condors, Butterflies) '
                            'are not fully decomposed here — their P/L is correct in the campaign total, '
                            'but the chain view may show fragments.'
                        )
                        for ci, chain in enumerate(chains):
                            cp      = chain[0]['cp']
                            ch_pnl  = sum(l['total'] for l in chain)
                            last    = chain[-1]
                            is_open_chain = 'to open' in str(last['sub_type']).lower()
                            n_rolls = sum(1 for l in chain if PAT_CLOSE in str(l['sub_type']).lower())
                            status_icon = '🟢' if is_open_chain else '✅'
                            cp_icon = '📞' if cp == 'CALL' else '📉'
                            chain_label = '%s %s %s Chain %d — %d roll(s) | Net: $%.2f' % (
                                status_icon, cp_icon, cp.title(), ci+1, n_rolls, ch_pnl)
                            with st.expander(chain_label, expanded=is_open_chain):
                                chain_rows = []
                                for leg_i, leg in enumerate(chain):
                                    sub = str(leg['sub_type']).lower()
                                    if 'to open' in sub:       action = '↪️ Sell to Open'
                                    elif PAT_CLOSE in sub:    action = '↩️ Buy to Close'
                                    elif PAT_EXPIR in sub:       action = '⏹️ Expired'
                                    elif PAT_ASSIGN in sub:      action = '📋 Assigned'
                                    else:                      action = leg['sub_type']
                                    dte_str = ''
                                    if 'to open' in sub:
                                        try:
                                            exp_dt = pd.to_datetime(leg['exp'], dayfirst=True)
                                            dte_str = '%dd' % max((exp_dt - leg['date']).days, 0)
                                        except (ValueError, TypeError): dte_str = ''
                                    is_open_leg = is_open_chain and leg_i == len(chain) - 1
                                    chain_rows.append({
                                        'Action': ('🟢 ' + action) if is_open_leg else action,
                                        'Date': leg['date'].strftime('%d/%m/%y'),
                                        'Strike': '%.1f%s' % (leg['strike'], cp[0]),
                                        'Exp': leg['exp'], 'DTE': dte_str,
                                        'Cash': leg['total'], '_open': is_open_leg,
                                    })
                                ch_df = pd.DataFrame(chain_rows)
                                ch_df = pd.concat([ch_df, pd.DataFrame([{
                                    'Action': '━━ Chain Total', 'Date': '',
                                    'Strike': '', 'Exp': '', 'DTE': '', 'Cash': ch_pnl, '_open': False
                                }])], ignore_index=True)
                                st.dataframe(
                                    ch_df[['Action','Date','Strike','Exp','DTE','Cash','_open']].style
                                        .apply(_style_chain_row, axis=1)
                                        .format({'Cash': lambda x: '${:.2f}'.format(x)})
                                        .map(lambda v: 'color: #00cc96' if isinstance(v,float) and v>0
                                            else ('color: #ef553b' if isinstance(v,float) and v<0 else ''),
                                            subset=['Cash']),
                                    width='stretch', hide_index=True,
                                    column_config={'_open': None}
                                )

                    st.markdown('**📋 Share & Dividend Events**')
                    ev_df = pd.DataFrame(c.events)
                    ev_share = ev_df[~ev_df['type'].str.lower().str.contains('to open|to close|expir|assign', na=False)]
                    if not ev_share.empty:
                        ev_share = ev_share.copy()
                        ev_share['date'] = pd.to_datetime(ev_share['date']).dt.strftime('%d/%m/%y %H:%M')
                        ev_share.columns = ['Date','Type','Detail','Amount']
                        st.dataframe(ev_share.style.format({'Amount': lambda x: '${:,.2f}'.format(x)})
                            .map(lambda v: 'color: #00cc96' if isinstance(v,float) and v>0
                                else ('color: #ef553b' if isinstance(v,float) and v<0 else ''),
                                subset=['Amount']),
                            width='stretch', hide_index=True)
                    else:
                        st.caption('No share/dividend events.')

# ── Tab 4: All Trades ─────────────────────────────────────────────────────────
with tab4:
    st.markdown(f'### 🔍 Realized P/L — All Tickers {_win_label}', unsafe_allow_html=True)

    # ── Sparkline equity curve ─────────────────────────────────────────────────
    if not closed_trades_df.empty:
        _spark_df = closed_trades_df[closed_trades_df['Close Date'] >= start_date].sort_values('Close Date').copy()
        if _spark_df.empty:
            _spark_df = closed_trades_df.sort_values('Close Date').copy()
        _spark_df['Cum P/L'] = _spark_df['Net P/L'].cumsum()
        _spark_color = '#00cc96' if _spark_df['Cum P/L'].iloc[-1] >= 0 else '#ef553b'
        _fill_color  = 'rgba(0,204,150,0.15)' if _spark_color == '#00cc96' else 'rgba(239,85,59,0.15)'
        _fig_spark = go.Figure()
        _fig_spark.add_trace(go.Scatter(
            x=_spark_df['Close Date'], y=_spark_df['Cum P/L'],
            mode='lines', line=dict(color=_spark_color, width=1.5),
            fill='tozeroy', fillcolor=_fill_color,
            hovertemplate='%{x|%d/%m/%y}<br>$%{y:,.2f}<extra></extra>'
        ))
        _fig_spark.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
        _fig_spark.update_layout(
            height=90, margin=dict(l=0, r=0, t=4, b=4),
            paper_bgcolor='rgba(10,14,23,0)', plot_bgcolor='rgba(10,14,23,0)',
            xaxis=dict(visible=False), yaxis=dict(visible=False),
            showlegend=False
        )
        st.plotly_chart(_fig_spark, width='stretch', config={'displayModeBar': False})
    st.markdown('---')
    rows = []
    for ticker, camps in sorted(all_campaigns.items()):
        tr = sum(realized_pnl(c, use_lifetime) for c in camps)
        td = sum(c.total_cost for c in camps if c.status=='open')
        tp = sum(c.premiums for c in camps)
        tv = sum(c.dividends for c in camps)
        po = pure_opts_per_ticker.get(ticker, 0.0)
        oc = sum(1 for c in camps if c.status=='open')
        cc = sum(1 for c in camps if c.status=='closed')
        rows.append({'Ticker': ticker, 'Type': '🎡 Wheel',
            'Campaigns': '%d open, %d closed'%(oc,cc),
            'Premiums': tp, 'Divs': tv,
            'Options P/L': po, 'Deployed': td, 'P/L': tr+po})
    for ticker in sorted(pure_options_tickers):
        t_df    = df[df['Ticker'] == ticker]
        t_eq    = t_df[equity_mask(t_df['Instrument Type'])].sort_values('Date')

        opt_flow    = t_df[
            t_df['Instrument Type'].isin(OPT_TYPES) &
            t_df['Type'].isin(TRADE_TYPES)
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
        deep_df = pd.DataFrame(rows)
        total_row = {'Ticker': 'TOTAL', 'Type': '', 'Campaigns': '',
            'Premiums': deep_df['Premiums'].sum(),
            'Divs': deep_df['Divs'].sum(),
            'Options P/L': deep_df['Options P/L'].sum(),
            'Deployed': deep_df['Deployed'].sum(),
            'P/L': deep_df['P/L'].sum()}
        deep_df = pd.concat([deep_df, pd.DataFrame([total_row])], ignore_index=True)
        st.dataframe(deep_df.style.format({
            'Premiums': lambda x: '${:,.2f}'.format(x),
            'Divs': lambda x: '${:,.2f}'.format(x),
            'Options P/L': lambda x: '${:,.2f}'.format(x),
            'Deployed': lambda x: '${:,.2f}'.format(x),
            'P/L': lambda x: '${:,.2f}'.format(x)
        }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)

    # ── Total Portfolio P/L by Week & Month ───────────────────────────────────
    st.markdown('---')
    st.markdown(f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">📅 Total Realized P/L by Week &amp; Month {_win_label}</div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.8rem;color:#6b7280;margin-bottom:12px;line-height:1.5;">'
        '<b style="color:#00cc96;">Whole portfolio — realized flows only</b>: '
        'options credits &amp; debits, share <em>sales</em> (FIFO gains/losses), dividends, and interest. '
        '<b>Share purchases are excluded</b> — they are capital deployment, not realized losses. '
        'This matches the <b>Realized P/L</b> top-line metric. Filtered to selected time window.'
        '</div>',
        unsafe_allow_html=True
    )

    # _daily_pnl already computed above as a window-sliced view of the cached all-time series
    _daily_pnl['Week']  = _daily_pnl['Date'].dt.to_period('W').apply(lambda p: p.start_time)
    _daily_pnl['Month'] = _daily_pnl['Date'].dt.to_period('M').apply(lambda p: p.start_time)
    _port_df = _daily_pnl  # alias for the if-check below

    if not _port_df.empty:
        _p_col1, _p_col2 = st.columns(2)

        with _p_col1:
            _p_weekly = _daily_pnl.groupby('Week')['PnL'].sum().reset_index()
            _p_weekly['Week'] = pd.to_datetime(_p_weekly['Week'])
            _p_weekly['Colour'] = _p_weekly['PnL'].apply(lambda x: '#00cc96' if x >= 0 else '#ef553b')
            _fig_pw = go.Figure()
            _fig_pw.add_trace(go.Bar(
                x=_p_weekly['Week'], y=_p_weekly['PnL'],
                marker_color=_p_weekly['Colour'],
                marker_line_width=0,
                customdata=[f'${v:,.2f}' if v >= 0 else f'-${abs(v):,.2f}' for v in _p_weekly['PnL']],
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
            _p_monthly = _daily_pnl.groupby('Month')['PnL'].sum().reset_index()
            _p_monthly['Month'] = pd.to_datetime(_p_monthly['Month'])
            _p_monthly['Colour'] = _p_monthly['PnL'].apply(lambda x: '#00cc96' if x >= 0 else '#ef553b')
            _p_monthly['Label'] = _p_monthly['Month'].dt.strftime('%b %Y')
            _fig_pm = go.Figure()
            _fig_pm.add_trace(go.Bar(
                x=_p_monthly['Label'], y=_p_monthly['PnL'],
                marker_color=_p_monthly['Colour'],
                marker_line_width=0,
                text=[f'${v:,.0f}' if v >= 0 else f'-${abs(v):,.0f}' for v in _p_monthly['PnL']],
                customdata=[f'${v:,.2f}' if v >= 0 else f'-${abs(v):,.2f}' for v in _p_monthly['PnL']],
                textposition='outside',
                textfont=dict(size=10, family='IBM Plex Mono', color='#8b949e'),
                hovertemplate='%{x}<br><b>%{customdata}</b><extra></extra>'
            ))
            _fig_pm.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
            _pm_lay = chart_layout('Monthly Total P/L' + _win_suffix, height=280, margin_t=36)
            _pm_lay['yaxis']['tickprefix'] = '$'
            _pm_lay['yaxis']['tickformat'] = ',.0f'
            _pm_lay['bargap'] = 0.35
            _fig_pm.update_layout(**_pm_lay)
            st.plotly_chart(_fig_pm, width='stretch', config={'displayModeBar': False})

        # ── P&L Volatility Metrics ─────────────────────────────────────────────
        st.markdown('---')
        st.markdown(f'<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">📉 P&amp;L Consistency {_win_label}</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:0.8rem;color:#6b7280;margin-bottom:16px;line-height:1.5;">Weekly buckets — a theta engine should produce a smooth, consistent stream. High volatility relative to your average week means lumpy, inconsistent results.</div>', unsafe_allow_html=True)

        if not _daily_pnl.empty and len(_daily_pnl) >= 2:
            # Weekly bucketing
            _vol_df = _daily_pnl.copy()
            _vol_df['Week'] = pd.to_datetime(_vol_df['Date']).dt.to_period('W').apply(lambda p: p.start_time)
            _weekly_pnl = _vol_df.groupby('Week')['PnL'].sum().reset_index()
            _weekly_pnl['Week'] = pd.to_datetime(_weekly_pnl['Week'])

            _avg_week     = _weekly_pnl['PnL'].mean()
            _std_week     = _weekly_pnl['PnL'].std()
            _sharpe_eq    = (_avg_week / _std_week) if _std_week > 0 else 0.0
            _pos_weeks    = (_weekly_pnl['PnL'] > 0).sum()
            _total_weeks  = len(_weekly_pnl)
            _consistency  = _pos_weeks / _total_weeks * 100 if _total_weeks > 0 else 0.0

            # Max drawdown on cumulative daily P/L
            _cum = _vol_df.sort_values('Date')['PnL'].cumsum().values
            _peak = _cum[0]; _max_dd = 0.0; _dd_start_i = 0; _dd_end_i = 0; _peak_i = 0
            for i, v in enumerate(_cum):
                if v > _peak:
                    _peak = v; _peak_i = i
                dd = v - _peak
                if dd < _max_dd:
                    _max_dd = dd; _dd_start_i = _peak_i; _dd_end_i = i

            # Recovery — days from trough back to previous peak
            _recovery_days = None
            if _max_dd < 0:
                _trough_val = _cum[_dd_end_i]
                for i in range(_dd_end_i + 1, len(_cum)):
                    if _cum[i] >= _cum[_dd_start_i]:
                        _recovery_days = i - _dd_end_i
                        break

            # Rolling 4-week std dev for chart
            _weekly_pnl['Rolling_Std'] = _weekly_pnl['PnL'].rolling(4, min_periods=2).std()

            # Metrics row
            vc1, vc2, vc3, vc4, vc5 = st.columns(5)
            vc1.metric('Avg Week P/L',      '$%.2f' % _avg_week)
            vc1.caption('Mean realized P/L per calendar week in the window. Your typical weekly income rate.')
            vc2.metric('Weekly Std Dev',     '$%.2f' % _std_week)
            vc2.caption('Standard deviation of weekly P/L. Lower = more consistent income stream. A theta engine should have this well below avg week P/L.')
            vc3.metric('Sharpe-Equiv',       '%.2f'  % _sharpe_eq)
            vc3.caption('Avg weekly P/L ÷ std dev. Above 1.0 means your average week outweighs your typical swing. Higher is better — 0.5–1.0 is decent for options selling.')
            vc4.metric('Profitable Weeks',   '%.0f%% (%d/%d)' % (_consistency, _pos_weeks, _total_weeks))
            vc4.caption('% of calendar weeks with positive realized P/L. Complements trade win rate — a week can have winning trades but net negative if one loss dominates.')
            if _max_dd < 0:
                _rec_str = '%dd' % _recovery_days if _recovery_days else 'Not yet'
                vc5.metric('Max Drawdown',   '-$%.2f' % abs(_max_dd), delta='Recovery: %s' % _rec_str, delta_color='off')
                vc5.caption('Largest peak-to-trough drop in cumulative daily P/L. Recovery = days from trough back to previous peak. "Not yet" means still underwater.')
            else:
                vc5.metric('Max Drawdown', '$0.00')
                vc5.caption('No drawdown in this window — cumulative P/L never fell below its starting peak.')

            # Chart: weekly P/L bars + rolling std dev band
            _fig_vol = go.Figure()
            _fig_vol.add_trace(go.Bar(
                x=_weekly_pnl['Week'], y=_weekly_pnl['PnL'],
                marker_color=_weekly_pnl['PnL'].apply(lambda x: '#00cc96' if x >= 0 else '#ef553b'),
                marker_line_width=0, name='Weekly P/L',
                customdata=[f'${v:,.2f}' if v >= 0 else f'-${abs(v):,.2f}' for v in _weekly_pnl['PnL']],
                hovertemplate='Week of %{x|%d %b}<br><b>%{customdata}</b><extra></extra>'
            ))
            if _weekly_pnl['Rolling_Std'].notna().sum() >= 2:
                _fig_vol.add_trace(go.Scatter(
                    x=_weekly_pnl['Week'], y=_weekly_pnl['Rolling_Std'],
                    mode='lines', name='4-wk Std Dev',
                    line=dict(color='#ffa421', width=1.5, dash='dot'),
                    yaxis='y2',
                    hovertemplate='Std Dev: <b>$%{y:,.2f}</b><extra></extra>'
                ))
                _fig_vol.add_trace(go.Scatter(
                    x=_weekly_pnl['Week'], y=(-_weekly_pnl['Rolling_Std']),
                    mode='lines', name='-4-wk Std Dev',
                    line=dict(color='#ffa421', width=1.5, dash='dot'),
                    yaxis='y2', showlegend=False,
                    hovertemplate='−Std Dev: <b>$%{y:,.2f}</b><extra></extra>'
                ))
            _fig_vol.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
            _vol_lay = chart_layout('Weekly P/L + Rolling 4-wk Volatility Band' + _win_suffix, height=300, margin_t=40)
            _vol_lay['yaxis']['tickprefix'] = '$'
            _vol_lay['yaxis']['tickformat'] = ',.0f'
            _vol_lay['bargap'] = 0.3
            _vol_lay['yaxis2'] = dict(
                overlaying='y', side='right',
                tickprefix='±$', tickformat=',.0f',
                tickfont=dict(size=10, color='#ffa421'),
                gridcolor='rgba(0,0,0,0)',
                showgrid=False
            )
            _vol_lay['legend'] = dict(orientation='h', yanchor='bottom', y=1.02,
                xanchor='right', x=1, bgcolor='rgba(0,0,0,0)', font=dict(size=11))
            _fig_vol.update_layout(**_vol_lay)
            st.plotly_chart(_fig_vol, width='stretch', config={'displayModeBar': False})
            st.caption('Amber dotted lines = rolling 4-week std dev (right axis). When the amber band widens your results are getting lumpier — tighten position sizing or reduce undefined risk.')
        else:
            st.info('Not enough data in this window for volatility metrics (need at least 2 days of activity).')
    else:
        st.info('No cash flow data in the selected window.')

# ── Tab 5: Deposits, Dividends & Fees ─────────────────────────────────────────
with tab5:
    st.markdown(f'### 💰 Deposits, Dividends & Fees {_win_label}', unsafe_allow_html=True)
    ic1, ic2, ic3, ic4 = st.columns(4)
    ic1.metric('Deposited',      '$%.2f' % total_deposited)
    ic2.metric('Withdrawn',      '$%.2f' % abs(total_withdrawn))
    ic3.metric('Dividends',      '$%.2f' % div_income)
    ic4.metric('Interest (net)', '$%.2f' % int_net)
    income_df = df_window[df_window['Sub Type'].isin(
        DEPOSIT_SUB_TYPES
    )][['Date','Ticker','Sub Type','Description','Total']].sort_values('Date', ascending=False)
    if not income_df.empty:
        st.dataframe(
            income_df.style
                .apply(_color_cash_row, axis=1)
                .format({'Total': lambda x: '${:,.2f}'.format(x)})
                .map(_color_cash_total, subset=['Total']),
            width='stretch', hide_index=True
        )
        st.caption(
            '🟢 Deposit &nbsp;&nbsp; 🔴 Withdrawal &nbsp;&nbsp; '
            '🔵 Dividend / Interest &nbsp;&nbsp; 🟡 Fee Adjustment'
        )
    else:
        st.info('No activity in this window.')