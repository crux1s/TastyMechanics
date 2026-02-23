import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from collections import defaultdict, deque

# ==========================================
# TastyMechanics v25.3
# ==========================================
# Changelog:
#
# v25.3 (2026-02-23)
#   Weekly Review Features:
#   - Expiry Alert Strip: inline chip strip below metrics showing all options
#     expiring within 21 days. Green (>14d) → amber (≤14d) → red (≤5d).
#     Only shown when open option positions exist.
#   - Period Comparison Card: "this period vs last period" inline summary card
#     showing Realized P/L, Trades Closed, Win Rate, and Dividends — each with
#     a delta vs the prior equivalent window. Shown for all windows except All Time.
#   - Weekly / Monthly P/L bar chart (Derivatives Performance tab): side-by-side
#     colour-coded bar charts (green = positive week/month, red = negative).
#     Monthly bars include value labels. Sits above the ticker heatmap.
#
#   Open Positions tab:
#   - Replaced cramped 3-column expanders with 2-column card grid
#   - Each card has: ticker + strategy badge (colour-coded by bias),
#     per-leg breakdown with basis chip, DTE progress bar (green→amber→red)
#   - Summary strip at top: ticker count, option legs, share positions,
#     strategy pills showing active strategies at a glance
#   - Cards use CSS hover effect and gradient backgrounds
#
#   Charts & Visualisations:
#   - New chart_layout() helper: consistent dark background, IBM Plex font,
#     subtle grid, proper margins across all charts
#   - Cumulative P/L: upgraded to go.Scatter for fill colour control,
#     $-formatted y-axis, cleaner hover tooltips
#   - Rolling Capture %: gradient fill under line, styled 50% target annotation
#   - Win/Loss histogram: dot-style median line, $-formatted x-axis
#   - Heatmap: IBM Plex Mono cell font, improved colorbar, per-cell hover
#   - Capture % distribution: outside text labels, axis labels added
#   - Sparkline: slightly taller, transparent background
#
#   Styling:
#   - New CSS: IBM Plex Sans + IBM Plex Mono typography throughout
#   - Deeper background (#0a0e17), refined metric label styling
#   - chart-section-title / chart-section-sub classes for consistent
#     section headings without relying on markdown headers
#
#
# v25.1 (2026-02-22)
#   - FIXED: Windowed equity P/L now uses true FIFO cost basis via deque —
#     oldest lot consumed first, partial lot splits handled correctly.
#     Our v25 used .iloc[-1] (most recent buy = LIFO-like), which gave
#     correct results for single-lot positions but would diverge on partial
#     sales of multi-lot positions (e.g. selling 50 of 200 SOFI shares).
#     Extracted into named function: calculate_windowed_equity_pnl().
#
# v25 (2026-02-22)
#   UI & Charts:
#   - Win/Loss distribution histogram (Derivatives Performance tab)
#   - P/L heatmap by ticker and month (Derivatives Performance tab)
#   - Open chain leg highlighted in roll chains (green row + 🟢 prefix)
#   - Time window selector moved from sidebar to top-right of main area
#   - Window start capped at first transaction date (fixes 1 Year = All Time
#     when account is less than 12 months old)
#
#   Metrics:
#   - Portfolio Overview Realized P/L now respects selected time window
#   - Breakdown expander shows Options/Equity/Div split for windowed views
#   - "Actual $/Day (gross)" removed — replaced by "Banked $/Day" (net P/L/day)
#     with gross as delta for context
#   - Short window warning added (Last 5 Days / Month / 3 Months) explaining
#     cross-window trade distortion
#
#   Code quality:
#   - .applymap() → .map() throughout (pandas 2.1+ compatibility)
#   - use_container_width= → width= throughout (Streamlit deprecation)
#   - st.plotly_chart config={'displayModeBar': False} on all charts
#   - strat_df column count fixed (was 6, now correctly 7 with medians)
#
# v24 (prior)
#   - TastyMechanics branding
#   - Sparkline equity curve (window-aware)
#   - Win % colour coding across all performance tables
#   - Campaign cards replacing outer expanders
#   - Banked $/Day metric (window-aware)
#   - Window labels on filtered tabs
# ==========================================

st.set_page_config(page_title="TastyMechanics v25.3", layout="wide")
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

    /* ── Position Cards ── */
    .pos-card {
        background: linear-gradient(135deg, #111827 0%, #0f1520 100%);
        border: 1px solid #1f2937;
        border-radius: 12px;
        padding: 18px 20px 14px 20px;
        margin-bottom: 16px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.4);
        transition: border-color 0.2s ease;
    }
    .pos-card:hover { border-color: #374151; }
    .pos-card-header {
        display: flex; align-items: center; justify-content: space-between;
        margin-bottom: 12px;
        padding-bottom: 10px;
        border-bottom: 1px solid #1f2937;
    }
    .pos-ticker {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 1.3rem; font-weight: 600; color: #f0f6fc;
        letter-spacing: 0.04em;
    }
    .pos-strategy-badge {
        font-size: 0.72rem; font-weight: 600;
        padding: 3px 10px; border-radius: 20px;
        text-transform: uppercase; letter-spacing: 0.06em;
        background: rgba(88,166,255,0.12); color: #58a6ff;
        border: 1px solid rgba(88,166,255,0.25);
        white-space: nowrap;
    }
    .pos-badge-bullish { background: rgba(0,204,150,0.1); color: #00cc96; border-color: rgba(0,204,150,0.25); }
    .pos-badge-bearish { background: rgba(239,85,59,0.1); color: #ef553b; border-color: rgba(239,85,59,0.25); }
    .pos-badge-neutral { background: rgba(255,165,0,0.1); color: #ffa500; border-color: rgba(255,165,0,0.25); }
    .pos-leg {
        display: flex; align-items: center; justify-content: space-between;
        padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.04);
        font-size: 0.85rem;
    }
    .pos-leg:last-child { border-bottom: none; }
    .pos-leg-label { color: #8b949e; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; }
    .pos-leg-value { font-family: 'IBM Plex Mono', monospace; color: #e6edf3; font-size: 0.88rem; }
    .pos-dte-bar-wrap { margin-top: 10px; }
    .pos-dte-bar-bg { background: #1f2937; border-radius: 4px; height: 4px; width: 100%; }
    .pos-dte-bar-fill { background: #58a6ff; border-radius: 4px; height: 4px; }
    .pos-dte-label { color: #6b7280; font-size: 0.72rem; margin-top: 4px; }
    .pos-basis-chip {
        display: inline-block; margin-top: 8px;
        background: rgba(255,255,255,0.04); border: 1px solid #1f2937;
        border-radius: 6px; padding: 3px 10px;
        font-family: 'IBM Plex Mono', monospace; font-size: 0.8rem; color: #8b949e;
    }

    /* ── Chart section titles ── */
    .chart-section-title {
        font-size: 1.05rem; font-weight: 600; color: #e6edf3;
        margin: 28px 0 2px 0; letter-spacing: 0.01em;
    }
    .chart-section-sub {
        font-size: 0.8rem; color: #6b7280; margin-bottom: 12px; line-height: 1.5;
    }
    </style>
""", unsafe_allow_html=True)

# ── helpers ───────────────────────────────────────────────────────────────────
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
    if 'REMOVAL' in dsc: return qty if 'ASSIGNMENT' in dsc else -qty
    return 0

def is_share_row(inst):  return str(inst).strip() == 'Equity'
def is_option_row(inst): return 'Option' in str(inst)

def identify_pos_type(row):
    qty = row['Net_Qty']; inst = str(row['Instrument Type'])
    cp  = str(row.get('Call or Put', '')).upper()
    if is_share_row(inst):   return 'Long Stock' if qty > 0 else 'Short Stock'
    if is_option_row(inst):
        if 'CALL' in cp: return 'Long Call' if qty > 0 else 'Short Call'
        if 'PUT'  in cp: return 'Long Put'  if qty > 0 else 'Short Put'
    return 'Asset'

def translate_readable(row):
    if not is_option_row(str(row['Instrument Type'])): return '%s Shares' % row['Ticker']
    try:    exp_dt = pd.to_datetime(row['Expiration Date']).strftime('%d/%m')
    except: exp_dt = 'N/A'
    cp     = 'C' if 'CALL' in str(row['Call or Put']).upper() else 'P'
    action = 'STO' if row['Net_Qty'] < 0 else 'BTO'
    return '%s %d @ %.0f%s (%s)' % (action, abs(int(row['Net_Qty'])), row['Strike Price'], cp, exp_dt)

def format_cost_basis(val):
    return '$%.2f %s' % (abs(val), 'Cr' if val < 0 else 'Db')

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
    s = strat.lower()
    if any(k in s for k in ['put', 'strangle', 'condor', 'lizard', 'reversal']):
        return ('font-size:0.72rem;font-weight:600;padding:3px 10px;border-radius:20px;'
                'text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;'
                'background:rgba(0,204,150,0.1);color:#00cc96;border:1px solid rgba(0,204,150,0.25);')
    if any(k in s for k in ['long call', 'bearish']):
        return ('font-size:0.72rem;font-weight:600;padding:3px 10px;border-radius:20px;'
                'text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;'
                'background:rgba(239,85,59,0.1);color:#ef553b;border:1px solid rgba(239,85,59,0.25);')
    if any(k in s for k in ['covered', 'wheel', 'stock']):
        return ('font-size:0.72rem;font-weight:600;padding:3px 10px;border-radius:20px;'
                'text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;'
                'background:rgba(255,165,0,0.1);color:#ffa500;border:1px solid rgba(255,165,0,0.25);')
    return ('font-size:0.72rem;font-weight:600;padding:3px 10px;border-radius:20px;'
            'text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;'
            'background:rgba(88,166,255,0.12);color:#58a6ff;border:1px solid rgba(88,166,255,0.25);')

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
    rows_sorted = t_df.sort_values('Status')
    for i, (_, row) in enumerate(rows_sorted.iterrows()):
        pos_type = row['Status']
        detail   = row['Details']
        dte      = row['DTE']
        basis    = format_cost_basis(row['Cost Basis'])
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
                    f'<div style="background:#1f2937;border-radius:4px;height:4px;width:140px;">'
                    f'<div style="width:{pct:.0f}%;background:{bar_color};border-radius:4px;height:4px;"></div>'
                    f'</div>'
                    f'<div style="color:#6b7280;font-size:0.7rem;margin-top:3px;">{dte} to expiry</div>'
                    f'</div>'
                )
            except: pass

        legs_html += (
            f'<div style="{leg_style}">'
            f'  <div>'
            f'    <div style="{LBL}">{pos_type}</div>'
            f'    <div style="{VAL}">{detail}</div>'
            f'    {dte_html}'
            f'  </div>'
            f'  <div style="text-align:right;flex-shrink:0;margin-left:12px;">'
            f'    <div style="{LBL}">Basis</div>'
            f'    <div style="{CHIP}">{basis}</div>'
            f'  </div>'
            f'</div>'
        )

    return (
        f'<div style="{CARD}">'
        f'  <div style="{HDR}">'
        f'    <span style="{TICK}">{ticker}</span>'
        f'    <span style="{badge_style}">{strat}</span>'
        f'  </div>'
        f'  {legs_html}'
        f'</div>'
    )

def detect_strategy(ticker_df):
    types = [identify_pos_type(r) for _, r in ticker_df.iterrows()]
    ls = types.count('Long Stock');  sc = types.count('Short Call')
    lc = types.count('Long Call');   sp = types.count('Short Put')
    lp = types.count('Long Put')
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

# ── TRUE FIFO EQUITY P/L ───────────────────────────────────────────────────────
def calculate_windowed_equity_pnl(df_full, start_date, end_date=None):
    """
    Calculates net equity P/L for sales occurring on or after start_date
    and (optionally) on or before end_date.
    Uses a per-ticker FIFO deque — oldest lot consumed first, with correct
    partial lot handling. Processes ALL equity rows chronologically so cost
    basis is always accurate regardless of when the buy occurred.
    end_date is required for prior-period comparisons to avoid double-counting
    sales that fall in the current window.
    """
    _eq_pnl = 0.0
    fifo_queues = {}

    equity_rows = df_full[df_full['Instrument Type'].str.strip() == 'Equity'].sort_values('Date')
    for _, row in equity_rows.iterrows():
        ticker = row['Ticker']
        if ticker not in fifo_queues:
            fifo_queues[ticker] = deque()

        if row['Net_Qty_Row'] > 0:
            # Buy — push lot onto queue as (qty, cost_per_share)
            qty = row['Net_Qty_Row']
            cost_per = abs(row['Total']) / qty if qty != 0 else 0
            fifo_queues[ticker].append((qty, cost_per))

        elif row['Net_Qty_Row'] < 0:
            # Sell — consume oldest lots first (FIFO)
            sell_qty      = abs(row['Net_Qty_Row'])
            sell_proceeds = row['Total']
            remaining     = sell_qty
            sale_cost_basis = 0.0
            q = fifo_queues[ticker]

            while remaining > 0 and q:
                b_qty, b_cost = q[0]
                use = min(remaining, b_qty)
                sale_cost_basis += use * b_cost
                remaining -= use
                if use == b_qty:
                    q.popleft()          # lot fully consumed
                else:
                    q[0] = (b_qty - use, b_cost)  # partial lot — update in place

            # Only count P/L if sale is inside the window (start_date..end_date)
            in_window = row['Date'] >= start_date
            if end_date is not None:
                in_window = in_window and row['Date'] < end_date
            if in_window:
                _eq_pnl += (sell_proceeds - sale_cost_basis)

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
    records = []
    fifo_queues = {}

    equity_rows = df_full[df_full['Instrument Type'].str.strip() == 'Equity'].sort_values('Date')
    for _, row in equity_rows.iterrows():
        ticker = row['Ticker']
        if ticker not in fifo_queues:
            fifo_queues[ticker] = deque()
        if row['Net_Qty_Row'] > 0:
            qty      = row['Net_Qty_Row']
            cost_per = abs(row['Total']) / qty if qty != 0 else 0
            fifo_queues[ticker].append((qty, cost_per))
        elif row['Net_Qty_Row'] < 0:
            sell_qty        = abs(row['Net_Qty_Row'])
            sell_proceeds   = row['Total']
            remaining       = sell_qty
            sale_cost_basis = 0.0
            q = fifo_queues[ticker]
            while remaining > 0 and q:
                b_qty, b_cost = q[0]
                use = min(remaining, b_qty)
                sale_cost_basis += use * b_cost
                remaining -= use
                if use == b_qty:
                    q.popleft()
                else:
                    q[0] = (b_qty - use, b_cost)
            if row['Date'] >= start_date:
                records.append({'Date': row['Date'], 'PnL': sell_proceeds - sale_cost_basis})

    # Options flows (all realized at trade/expiry date)
    opt_rows = df_full[
        df_full['Instrument Type'].isin(['Equity Option', 'Future Option']) &
        df_full['Type'].isin(['Trade', 'Receive Deliver']) &
        (df_full['Date'] >= start_date)
    ]
    for _, row in opt_rows.iterrows():
        records.append({'Date': row['Date'], 'PnL': row['Total']})

    # Dividends + interest
    income_rows = df_full[
        df_full['Sub Type'].isin(['Dividend', 'Credit Interest', 'Debit Interest']) &
        (df_full['Date'] >= start_date)
    ]
    for _, row in income_rows.iterrows():
        records.append({'Date': row['Date'], 'PnL': row['Total']})

    if not records:
        return pd.DataFrame(columns=['Date', 'PnL'])

    daily = pd.DataFrame(records)
    daily['Date'] = pd.to_datetime(daily['Date']).dt.tz_localize(None)
    return daily.groupby('Date')['PnL'].sum().reset_index()



WHEEL_MIN_SHARES = 100

def build_campaigns(df, ticker, use_lifetime=False):
    t = df[df['Ticker'] == ticker].copy()
    t['Sort_Inst'] = t['Instrument Type'].apply(lambda x: 0 if 'Equity' in str(x) and 'Option' not in str(x) else 1)
    t = t.sort_values(['Date', 'Sort_Inst'])

    if use_lifetime:
        net_shares = 0
        for _, row in t.iterrows():
            if is_share_row(row['Instrument Type']):
                net_shares += row['Net_Qty_Row']
        if net_shares >= WHEEL_MIN_SHARES:
            total_cost = 0.0; premiums = 0.0; dividends = 0.0; events = []
            start_date = t['Date'].iloc[0]
            for _, row in t.iterrows():
                inst = str(row['Instrument Type']); total = row['Total']; sub_type = str(row['Sub Type'])
                if is_share_row(inst):
                    if row['Net_Qty_Row'] > 0:
                        total_cost += abs(total)
                        events.append({'date': row['Date'], 'type': 'Entry/Add', 'detail': f"Bought {row['Net_Qty_Row']} shares", 'cash': total})
                    else:
                        total_cost -= abs(total)
                        events.append({'date': row['Date'], 'type': 'Exit', 'detail': f"Sold {abs(row['Net_Qty_Row'])} shares", 'cash': total})
                elif is_option_row(inst):
                    premiums += total
                    events.append({'date': row['Date'], 'type': sub_type, 'detail': str(row['Description'])[:60], 'cash': total})
                elif sub_type == 'Dividend':
                    dividends += total
                    events.append({'date': row['Date'], 'type': 'Dividend', 'detail': 'Dividend', 'cash': total})
            net_lifetime_cash = t[t['Type'].isin(['Trade', 'Receive Deliver', 'Money Movement'])]['Total'].sum()
            return [{
                'ticker': ticker, 'total_shares': net_shares,
                'total_cost': abs(net_lifetime_cash) if net_lifetime_cash < 0 else 0,
                'blended_basis': abs(net_lifetime_cash)/net_shares if net_shares>0 else 0,
                'premiums': premiums, 'dividends': dividends,
                'exit_proceeds': 0, 'start_date': start_date, 'end_date': None,
                'status': 'open', 'events': events
            }]

    campaigns = []; current = None; running_shares = 0.0
    for _, row in t.iterrows():
        inst = str(row['Instrument Type']); qty = row['Net_Qty_Row']
        total = row['Total']; sub_type = str(row['Sub Type'])
        if is_share_row(inst) and qty >= WHEEL_MIN_SHARES:
            pps = abs(total) / qty
            if running_shares < 0.001:
                current = {'ticker': ticker, 'total_shares': qty, 'total_cost': abs(total),
                    'blended_basis': pps, 'premiums': 0.0, 'dividends': 0.0,
                    'exit_proceeds': 0.0, 'start_date': row['Date'], 'end_date': None,
                    'status': 'open', 'events': [{'date': row['Date'], 'type': 'Entry',
                        'detail': 'Bought %.0f @ $%.2f/sh' % (qty, pps), 'cash': total}]}
                running_shares = qty
            else:
                ns = running_shares + qty; nc = current['total_cost'] + abs(total); nb = nc / ns
                current['total_shares'] = ns; current['total_cost'] = nc
                current['blended_basis'] = nb; running_shares = ns
                current['events'].append({'date': row['Date'], 'type': 'Add',
                    'detail': 'Added %.0f @ $%.2f → blended $%.2f/sh' % (qty, pps, nb), 'cash': total})
        elif is_share_row(inst) and qty < 0:
            if current and running_shares > 0.001:
                current['exit_proceeds'] += total; running_shares += qty
                pps = abs(total) / abs(qty) if qty != 0 else 0
                current['events'].append({'date': row['Date'], 'type': 'Exit',
                    'detail': 'Sold %.0f @ $%.2f/sh' % (abs(qty), pps), 'cash': total})
                if running_shares < 0.001:
                    current['end_date'] = row['Date']; current['status'] = 'closed'
                    campaigns.append(current); current = None; running_shares = 0.0
        elif is_option_row(inst) and current is not None:
            current['premiums'] += total
            current['events'].append({'date': row['Date'], 'type': sub_type,
                'detail': str(row['Description'])[:60], 'cash': total})
        elif sub_type == 'Dividend' and current is not None:
            current['dividends'] += total
            current['events'].append({'date': row['Date'], 'type': 'Dividend',
                'detail': 'Dividend received', 'cash': total})
    if current is not None: campaigns.append(current)
    return campaigns

def effective_basis(c, use_lifetime=False):
    if use_lifetime: return c['blended_basis']
    net = c['total_cost'] - c['premiums'] - c['dividends']
    return net / c['total_shares'] if c['total_shares'] > 0 else 0.0

def realized_pnl(c, use_lifetime=False):
    if use_lifetime: return c['premiums'] + c['dividends']
    if c['status'] == 'closed':
        return c['exit_proceeds'] + c['premiums'] + c['dividends'] - c['total_cost']
    return c['premiums'] + c['dividends']

def pure_options_pnl(df, ticker, campaigns):
    windows = [(c['start_date'], c['end_date'] or df['Date'].max()) for c in campaigns]
    t = df[(df['Ticker'] == ticker) & df['Instrument Type'].str.contains('Option', na=False)]
    total = 0.0
    for _, row in t.iterrows():
        if not any(s <= row['Date'] <= e for s, e in windows):
            total += row['Total']
    return total

# ── DERIVATIVES METRICS ENGINE ─────────────────────────────────────────────────

def build_closed_trades(df, campaign_windows=None):
    if campaign_windows is None: campaign_windows = {}
    equity_opts = df[df['Instrument Type'].isin(['Equity Option', 'Future Option'])].copy()
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

            short_opens_sp = opens[opens['Net_Qty_Row'] < 0]
            long_opens_sp  = opens[opens['Net_Qty_Row'] > 0]
            n_short_legs   = len(short_opens_sp)
            n_long_legs    = len(long_opens_sp)
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

            if is_butterfly:
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
                capital_risk = max(w_call - abs(open_credit), 1)
            else:
                trade_type   = 'Put Credit Spread' if is_credit else 'Put Debit Spread'
                capital_risk = max(w_put - abs(open_credit), 1)
        else:
            strikes      = grp['Strike Price'].dropna().tolist()
            capital_risk = max(strikes) * 100 if strikes else 1
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
                dte_open = max((nearest_exp - open_date.replace(tzinfo=None)).days, 0)
            else:
                dte_open = None
        except: dte_open = None

        closed_list.append({
            'Ticker': ticker, 'Trade Type': trade_type,
            'Type': 'Call' if 'CALL' in cp else 'Put' if 'PUT' in cp else 'Mixed',
            'Spread': n_long > 0, 'Is Credit': is_credit, 'Days Held': days_held,
            'Open Date': open_date, 'Close Date': close_date, 'Premium Rcvd': open_credit,
            'Net P/L': net_pnl, 'Capture %': net_pnl / open_credit * 100 if is_credit else None,
            'Capital Risk': capital_risk,
            'Ann Return %': max(min(net_pnl / capital_risk * 365 / days_held * 100, 500), -500)
                if (is_credit and capital_risk > 0) else None,
            'Prem/Day': open_credit / days_held if is_credit else None,
            'Won': net_pnl > 0, 'DTE Open': dte_open,
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

        current_chain = []
        net_qty = 0
        last_close_date = None

        for _, row in legs.iterrows():
            sub = str(row['Sub Type']).lower()
            qty = row['Net_Qty_Row']
            event = {
                'date': row['Date'], 'sub_type': row['Sub Type'],
                'strike': row['Strike Price'],
                'exp': pd.to_datetime(row['Expiration Date']).strftime('%d/%m/%y') if pd.notna(row['Expiration Date']) else '',
                'qty': qty, 'total': row['Total'], 'cp': cp_type,
                'desc': str(row['Description'])[:55],
            }
            if 'to open' in sub and qty < 0:
                if last_close_date is not None and net_qty == 0:
                    if (row['Date'] - last_close_date).days > 3 and current_chain:
                        chains.append(current_chain)
                        current_chain = []
                net_qty += abs(qty)
                current_chain.append(event)
                last_close_date = None
            elif net_qty > 0 and ('to close' in sub or 'expiration' in sub or 'assignment' in sub):
                net_qty = max(net_qty - abs(qty), 0)
                current_chain.append(event)
                if net_qty == 0:
                    last_close_date = row['Date']

        if current_chain:
            chains.append(current_chain)
    return chains

# ── MAIN APP ───────────────────────────────────────────────────────────────────

st.title('📟 TastyMechanics v25.3')

with st.sidebar:
    st.header('⚙️ Data Control')
    uploaded_file = st.file_uploader('Upload TastyTrade History CSV', type='csv')
    st.markdown('---')
    st.header('🎯 Campaign Settings')
    use_lifetime = st.toggle('Show Lifetime "House Money"', value=False,
        help='If ON, combines ALL history for a ticker into one campaign. If OFF, resets breakeven every time shares hit zero.')

if not uploaded_file:
    st.info('🛰️ **TastyMechanics v25 Ready.** Upload your TastyTrade CSV to begin.')
    st.stop()

# ── load ───────────────────────────────────────────────────────────────────────

df = pd.read_csv(uploaded_file)
df['Date'] = pd.to_datetime(df['Date'], utc=True)
for col in ['Total', 'Quantity', 'Commissions', 'Fees']: df[col] = df[col].apply(clean_val)
df['Ticker']      = df['Underlying Symbol'].fillna(df['Symbol'].str.split().str[0]).fillna('CASH')
df['Net_Qty_Row'] = df.apply(get_signed_qty, axis=1)
df = df.sort_values('Date').reset_index(drop=True)

latest_date = df['Date'].max()

# ── Time window selector — top right ──────────────────────────────────────────
time_options = ['YTD', 'Last 5 Days', 'Last Month', 'Last 3 Months', 'Half Year', '1 Year', 'All Time']
_hdr_left, _hdr_right = st.columns([3, 1])
with _hdr_right:
    selected_period = st.selectbox('Time Window', time_options, index=6, label_visibility='collapsed')

if   selected_period == 'All Time':      start_date = df['Date'].min()
elif selected_period == 'YTD':           start_date = pd.Timestamp(latest_date.year, 1, 1, tz='UTC')
elif selected_period == 'Last 5 Days':   start_date = latest_date - timedelta(days=5)
elif selected_period == 'Last Month':    start_date = latest_date - timedelta(days=30)
elif selected_period == 'Last 3 Months': start_date = latest_date - timedelta(days=90)
elif selected_period == 'Half Year':     start_date = latest_date - timedelta(days=182)
elif selected_period == '1 Year':        start_date = latest_date - timedelta(days=365)

# Cap start at first transaction — prevents 1 Year / Half Year going before data exists
# which would inflate window_days and deflate per-day metrics
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
           selected_period), unsafe_allow_html=True)

# ── build open positions ledger ────────────────────────────────────────────────

trade_df = df[df['Type'].isin(['Trade', 'Receive Deliver'])].copy()
groups   = trade_df.groupby(['Ticker', 'Symbol', 'Instrument Type', 'Call or Put',
     'Expiration Date', 'Strike Price', 'Root Symbol'], dropna=False)
open_records = []
for name, group in groups:
    net_qty = group['Net_Qty_Row'].sum()
    if abs(net_qty) > 0.001:
        open_records.append({'Ticker': name[0], 'Symbol': name[1],
            'Instrument Type': name[2], 'Call or Put': name[3],
            'Expiration Date': name[4], 'Strike Price': name[5],
            'Root Symbol': name[6], 'Net_Qty': net_qty,
            'Cost Basis': group['Total'].sum() * -1})
df_open = pd.DataFrame(open_records)

# ── expiry alert data (computed here, rendered after metrics) ─────────────────
_expiry_alerts = []
if not df_open.empty:
    _opts_open = df_open[df_open['Instrument Type'].str.contains('Option', na=False)].copy()
    if not _opts_open.empty and _opts_open['Expiration Date'].notna().any():
        _opts_open['_exp_dt'] = pd.to_datetime(_opts_open['Expiration Date'], format='mixed', errors='coerce')
        _opts_open = _opts_open.dropna(subset=['_exp_dt'])
        _opts_open['_dte'] = (_opts_open['_exp_dt'] - latest_date.replace(tzinfo=None)).dt.days.clip(lower=0)
        for _, r in _opts_open[_opts_open['_dte'] <= 21].sort_values('_dte').iterrows():
            cp   = str(r.get('Call or Put','')).upper()
            side = 'C' if 'CALL' in cp else 'P'
            _expiry_alerts.append({
                'ticker': r['Ticker'],
                'label':  '%.0f%s' % (r['Strike Price'], side),
                'dte':    int(r['_dte']),
                'qty':    int(r['Net_Qty']),
            })

# ── wheel campaigns ────────────────────────────────────────────────────────────

wheel_tickers = []
for t in df['Ticker'].unique():
    if t == 'CASH': continue
    if not df[(df['Ticker']==t) & (df['Instrument Type'].str.strip()=='Equity') &
              (df['Net_Qty_Row'] >= WHEEL_MIN_SHARES)].empty:
        wheel_tickers.append(t)

all_campaigns = {}
for ticker in wheel_tickers:
    camps = build_campaigns(df, ticker, use_lifetime=use_lifetime)
    if camps: all_campaigns[ticker] = camps

all_tickers          = [t for t in df['Ticker'].unique() if t != 'CASH']
pure_options_tickers = [t for t in all_tickers if t not in wheel_tickers]

# ── derivatives metrics ────────────────────────────────────────────────────────

_camp_windows = {}
for _t, _camps in all_campaigns.items():
    _camp_windows[_t] = [(_c["start_date"], _c["end_date"] or latest_date) for _c in _camps]

closed_trades_df = build_closed_trades(df, campaign_windows=_camp_windows)
window_trades_df = closed_trades_df[closed_trades_df['Close Date'] >= start_date].copy() \
    if not closed_trades_df.empty else pd.DataFrame()

# ── P/L accounting ─────────────────────────────────────────────────────────────

closed_camp_pnl      = sum(realized_pnl(c, use_lifetime) for camps in all_campaigns.values()
                           for c in camps if c['status'] == 'closed')
open_premiums_banked = sum(realized_pnl(c, use_lifetime) for camps in all_campaigns.values()
                           for c in camps if c['status'] == 'open')
capital_deployed     = sum(c['total_shares'] * c['blended_basis'] for camps in all_campaigns.values()
                           for c in camps if c['status'] == 'open')

pure_opts_pnl = 0.0
extra_capital_deployed = 0.0  # Cost of fractional/standalone share holdings

for t in pure_options_tickers:
    t_df = df[df['Ticker'] == t]
    mask = (df['Ticker']==t) & (df['Type'].isin(['Trade','Receive Deliver']))
    total_flow = df.loc[mask, 'Total'].sum()
    s_mask = t_df['Instrument Type'].str.contains('Equity', na=False) & \
             ~t_df['Instrument Type'].str.contains('Option', na=False)
    eq_rows = t_df[s_mask & t_df['Type'].isin(['Trade','Receive Deliver'])]
    net_shares = eq_rows['Net_Qty_Row'].sum()
    if net_shares > 0.0001:
        # Use net_shares x avg cost so Capital Deployed reflects only shares still held
        total_bought   = eq_rows[eq_rows['Net_Qty_Row'] > 0]['Net_Qty_Row'].sum()
        total_buy_cost = eq_rows[eq_rows['Net_Qty_Row'] > 0]['Total'].apply(abs).sum()
        avg_cost = total_buy_cost / total_bought if total_bought > 0 else 0
        deployed = net_shares * avg_cost
        equity_flow = eq_rows['Total'].sum()
        if equity_flow < 0:
            pure_opts_pnl += (total_flow + abs(equity_flow))
            extra_capital_deployed += deployed
        else:
            pure_opts_pnl += total_flow
    else:
        pure_opts_pnl += total_flow

for ticker, camps in all_campaigns.items():
    pure_opts_pnl += pure_options_pnl(df, ticker, camps)

total_realized_pnl = closed_camp_pnl + open_premiums_banked + pure_opts_pnl
capital_deployed  += extra_capital_deployed

# ── Windowed P/L (respects time window selector) ──────────────────────────────
# Options: sum all option cash flows in the window (credits + debits)
# Equity: FIFO cost basis via calculate_windowed_equity_pnl() — oldest lot first,
#         partial lot splits handled correctly, pre-window buys tracked
_w_opts = df_window[df_window['Instrument Type'].isin(['Equity Option','Future Option']) &
                    (df_window['Type'].isin(['Trade','Receive Deliver']))]

_eq_pnl = calculate_windowed_equity_pnl(df, start_date)

window_realized_pnl = _w_opts['Total'].sum() + _eq_pnl

# ── Prior period P/L (for WoW / MoM comparison card) ─────────────────────────
_window_span = latest_date - start_date
_prior_end   = start_date
_prior_start = _prior_end - _window_span
_df_prior    = df[(df['Date'] >= _prior_start) & (df['Date'] < _prior_end)].copy()
_prior_opts  = _df_prior[_df_prior['Instrument Type'].isin(['Equity Option','Future Option']) &
                          _df_prior['Type'].isin(['Trade','Receive Deliver'])]['Total'].sum()
_prior_eq    = calculate_windowed_equity_pnl(df, _prior_start, end_date=_prior_end)
prior_period_pnl = _prior_opts + _prior_eq
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
div_income = df_window[df_window['Sub Type']=='Dividend']['Total'].sum()
int_net    = df_window[df_window['Sub Type'].isin(['Credit Interest','Debit Interest'])]['Total'].sum()
deb_int    = df_window[df_window['Sub Type']=='Debit Interest']['Total'].sum()
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

# ── TOP METRICS ────────────────────────────────────────────────────────────────

st.markdown('### 📊 Portfolio Overview')
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
m2.caption('Realized P/L as a %% of net deposits. How hard your deposited capital is working.')

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

with st.expander('💡 Realized P/L Breakdown', expanded=False):
    b1, b2, b3, b4 = st.columns(4)
    if _is_all_time:
        b1.metric('Closed Campaign P/L',    '$%.2f' % closed_camp_pnl)
        b1.caption('P/L from fully closed wheel campaigns — shares bought, options traded, shares sold. Complete cycles only.')
        b2.metric('Open Campaign Premiums', '$%.2f' % open_premiums_banked)
        b2.caption('Premiums banked so far in campaigns still running. Shares not yet sold so overall campaign P/L not finalised.')
        b3.metric('Standalone Trades P/L', '$%.2f' % pure_opts_pnl)
        b3.caption('Everything outside wheel campaigns — standalone options, futures options, index trades, pre/post-campaign options on wheel tickers.')
        b4.metric('Total Realized',         '$%.2f' % total_realized_pnl)
        b4.caption('Sum of all three above. The single number that matters — real cash generated by your trading.')
    else:
        _w_opts_only = _w_opts['Total'].sum()
        b1.metric('Options P/L',      '$%.2f' % _w_opts_only)
        b1.caption('Net cash from all option transactions in the window — credits received minus buyback costs, expirations, assignments.')
        b2.metric('Equity Sales P/L', '$%.2f' % _eq_pnl)
        b2.caption('Net profit from share sales in the window (FIFO cost basis applied). Purchases excluded — unrealised until sold.')
        b3.metric('Div + Interest',   '$%.2f' % (div_income + int_net))
        b3.caption('Dividends received plus net interest in the window.')
        b4.metric('Total',            '$%.2f' % _pnl_display)
        b4.caption('Sum of options and equity P/L in the selected window.')

# ── Expiry Alert Strip ─────────────────────────────────────────────────────────
if _expiry_alerts:
    def _dte_chip(a):
        dte = a['dte']
        if dte <= 5:
            bg, fg = 'rgba(239,85,59,0.15)', '#ef553b'
            label = '🔴 %dd' % dte
        elif dte <= 14:
            bg, fg = 'rgba(255,165,0,0.12)', '#ffa500'
            label = '🟡 %dd' % dte
        else:
            bg, fg = 'rgba(0,204,150,0.1)', '#00cc96'
            label = '🟢 %dd' % dte
        return (
            f'<span style="display:inline-flex;align-items:center;gap:6px;'
            f'background:{bg};border:1px solid {fg}33;border-radius:8px;'
            f'padding:5px 12px;margin:3px 4px;font-size:0.82rem;">'
            f'<span style="color:{fg};font-weight:600;font-family:monospace;">{label}</span>'
            f'<span style="color:#8b949e;">{a["ticker"]}</span>'
            f'<span style="color:#c9d1d9;font-family:monospace;">{a["label"]}</span>'
            f'</span>'
        )

    chips = ''.join(_dte_chip(a) for a in _expiry_alerts)
    st.markdown(
        f'<div style="background:#0f1520;border:1px solid #1f2937;border-radius:10px;'
        f'padding:10px 14px;margin:12px 0 20px 0;">'
        f'<div style="color:#6b7280;font-size:0.72rem;text-transform:uppercase;'
        f'letter-spacing:0.06em;margin-bottom:6px;">⏰ Expiring within 21 days</div>'
        f'<div style="display:flex;flex-wrap:wrap;">{chips}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

# ── Period Comparison Card ─────────────────────────────────────────────────────
if selected_period != 'All Time' and not _df_prior.empty:
    _pnl_delta  = _pnl_display - prior_period_pnl
    _delta_sign = '+' if _pnl_delta >= 0 else ''
    _delta_col  = '#00cc96' if _pnl_delta >= 0 else '#ef553b'
    _arrow      = '▲' if _pnl_delta >= 0 else '▼'
    _period_lbl = selected_period.replace('Last ','').replace('YTD','Year-to-date')

    def _cmp_block(label, curr, prev, is_pct=False):
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

    _curr_wr, _prev_wr = 0.0, 0.0
    if not closed_trades_df.empty:
        _cw = closed_trades_df[closed_trades_df['Close Date'] >= start_date]
        _pw = closed_trades_df[(closed_trades_df['Close Date'] >= _prior_start) &
                               (closed_trades_df['Close Date'] < _prior_end)]
        _curr_wr = _cw['Won'].mean() * 100 if not _cw.empty else 0.0
        _prev_wr = _pw['Won'].mean() * 100 if not _pw.empty else 0.0

    _curr_div = df_window[df_window['Sub Type']=='Dividend']['Total'].sum()
    _prev_div = _df_prior[_df_prior['Sub Type']=='Dividend']['Total'].sum()

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

# ── TABS ───────────────────────────────────────────────────────────────────────
tab0, tab1, tab2, tab3, tab4 = st.tabs([
    '📡 Open Positions',
    '📈 Derivatives Performance',
    '🎯 Wheel Campaigns',
    '🔍 All Trades',
    '💰 Income & Fees'
])

# ── Tab 0: Active Positions ────────────────────────────────────────────────────
with tab0:
    st.subheader('📡 Open Positions')
    if df_open.empty:
        st.info('No active positions.')
    else:
        df_open['Status']  = df_open.apply(identify_pos_type, axis=1)
        df_open['Details'] = df_open.apply(translate_readable, axis=1)

        def calc_dte(row):
            if not is_option_row(str(row['Instrument Type'])) or pd.isna(row['Expiration Date']): return 'N/A'
            try:
                exp = pd.to_datetime(row['Expiration Date']).tz_localize(None).tz_localize(latest_date.tzinfo)
                return '%dd' % max((exp - latest_date).days, 0)
            except: return 'N/A'

        df_open['DTE'] = df_open.apply(calc_dte, axis=1)
        tickers_open = [t for t in sorted(df_open['Ticker'].unique()) if t != 'CASH']

        # Summary strip — count of positions and strategies
        n_options = df_open[df_open['Instrument Type'].str.contains('Option', na=False)].shape[0]
        n_shares  = df_open[df_open['Instrument Type'].str.strip() == 'Equity'].shape[0]
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
        all_cdf    = window_trades_df if not window_trades_df.empty else closed_trades_df
        credit_cdf = all_cdf[all_cdf['Is Credit']].copy() if not all_cdf.empty else pd.DataFrame()
        has_credit = not credit_cdf.empty
        has_data   = not all_cdf.empty

        st.info(window_label)
        st.markdown('#### 🎯 Premium Selling Scorecard')
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
                df_window['Instrument Type'].isin(['Equity Option','Future Option']) &
                df_window['Type'].isin(['Trade','Receive Deliver'])
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
            r5.caption('Total fees as a percentage of net realized P/L. Under 10%% is healthy. High on 0DTE or frequent small trades — fees eat a larger slice of smaller credits.')
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
                    _lay = chart_layout('Premium Capture % Distribution', height=320, margin_t=40)
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
                    st.markdown('##### 📊 Call vs Put Performance')
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

                    strat_df = all_cdf.groupby('Trade Type').agg(
                        Trades=('Won','count'),
                        Win_Rate=('Won', lambda x: x.mean()*100),
                        Total_PNL=('Net P/L','sum'),
                        Med_Capture=('Capture %','median'),
                        Med_Days=('Days Held','median'),
                        Med_DTE=('DTE Open','median'),
                    ).reset_index().sort_values('Total_PNL', ascending=False).round(1)
                    strat_df.columns = ['Strategy','Trades','Win %','P/L','Capture %','Days','DTE']
                    st.markdown('##### 🧩 Defined vs Undefined Risk — by Strategy')
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
            st.markdown('#### Performance by Ticker')
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

            def color_pnl_cell(val):
                if not isinstance(val, (int, float)): return ''
                return 'color: #00cc96' if val > 0 else 'color: #ef553b' if val < 0 else ''

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

            st.markdown('---')
            # ── Week-over-Week / Month-over-Month P/L bar chart ───────────────
            st.markdown('<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">📅 Options P/L by Week &amp; Month</div>', unsafe_allow_html=True)
            st.markdown('<div style="font-size:0.8rem;color:#6b7280;margin-bottom:12px;line-height:1.5;"><b style="color:#58a6ff;">Options trades only</b> — net P/L from closed equity &amp; futures options, grouped by the date the trade closed. Excludes share sales, dividends, and interest. See the <b>All Trades</b> tab for total portfolio P/L by period.</div>', unsafe_allow_html=True)

            _period_df = all_cdf.copy()
            _period_df['CloseDate'] = pd.to_datetime(_period_df['Close Date']).dt.tz_localize(None)
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
                    hovertemplate='Week of %{x|%d %b}<br><b>$%{y:,.2f}</b><extra></extra>'
                ))
                _fig_wk.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
                _wk_lay = chart_layout('Weekly P/L', height=280, margin_t=36)
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
                    textposition='outside',
                    textfont=dict(size=10, family='IBM Plex Mono', color='#8b949e'),
                    hovertemplate='%{x}<br><b>$%{y:,.2f}</b><extra></extra>'
                ))
                _fig_mo.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
                _mo_lay = chart_layout('Monthly P/L', height=280, margin_t=36)
                _mo_lay['yaxis']['tickprefix'] = '$'
                _mo_lay['yaxis']['tickformat'] = ',.0f'
                _mo_lay['bargap'] = 0.35
                _fig_mo.update_layout(**_mo_lay)
                st.plotly_chart(_fig_mo, width='stretch', config={'displayModeBar': False})

            st.markdown('---')
            st.markdown('<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">🗓 P/L by Ticker &amp; Month</div>', unsafe_allow_html=True)
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
            _eq_lay = chart_layout('Cumulative Realized P/L', height=300, margin_t=40)
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
                _cap2_lay = chart_layout('Rolling Avg Capture % · 10-trade window', height=260, margin_t=40)
                _cap2_lay['yaxis']['ticksuffix'] = '%'
                fig_cap2.update_layout(**_cap2_lay)
                st.plotly_chart(fig_cap2, width='stretch', config={'displayModeBar': False})

            st.markdown('---')
            st.markdown('<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">📊 Win / Loss Distribution</div>', unsafe_allow_html=True)
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
            bcol, wcol = st.columns(2)
            with bcol:
                st.markdown('##### 🏆 Best 5 Trades')
                best = all_cdf.nlargest(5, 'Net P/L')[['Ticker','Trade Type','Type','Days Held','Premium Rcvd','Net P/L']].copy()
                best.columns = ['Ticker','Strategy','C/P','Days','Credit','P/L']
                st.dataframe(best.style.format({
                    'Credit': lambda x: '${:.2f}'.format(x),
                    'P/L': lambda x: '${:.2f}'.format(x)
                }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)
            with wcol:
                st.markdown('##### 💀 Worst 5 Trades')
                worst = all_cdf.nsmallest(5, 'Net P/L')[['Ticker','Trade Type','Type','Days Held','Premium Rcvd','Net P/L']].copy()
                worst.columns = ['Ticker','Strategy','C/P','Days','Credit','P/L']
                st.dataframe(worst.style.format({
                    'Credit': lambda x: '${:.2f}'.format(x),
                    'P/L': lambda x: '${:.2f}'.format(x)
                }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)

            with st.expander('📋 Full Closed Trade Log', expanded=False):
                log = all_cdf[['Ticker','Trade Type','Type','Open Date','Close Date',
                               'Days Held','Premium Rcvd','Net P/L','Capture %',
                               'Capital Risk','Ann Return %']].copy()
                log['Open Date']  = pd.to_datetime(log['Open Date']).dt.strftime('%d/%m/%y')
                log['Close Date'] = pd.to_datetime(log['Close Date']).dt.strftime('%d/%m/%y')
                log.rename(columns={
                    'Trade Type':'Strategy','Type':'C/P','Open Date':'Open','Close Date':'Close',
                    'Days Held':'Days','Premium Rcvd':'Credit','Net P/L':'P/L',
                    'Capital Risk':'Risk','Ann Return %':'Ann Ret %'
                }, inplace=True)
                log = log.sort_values('Close', ascending=False)
                st.dataframe(log.style.format({
                    'Credit':     lambda x: '${:.2f}'.format(x),
                    'P/L':        lambda x: '${:.2f}'.format(x),
                    'Risk':       lambda x: '${:,.0f}'.format(x),
                    'Capture %':  lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                    'Ann Ret %':  lambda v: '{:.0f}%'.format(v) if pd.notna(v) else '—',
                }).map(color_pnl_cell, subset=['P/L']),
                width='stretch', hide_index=True)

# ── Tab 2: Wheel Campaigns ─────────────────────────────────────────────────────
with tab2:
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
                dur  = (c['end_date'] or latest_date) - c['start_date']
                rows.append({'Ticker': ticker, 'Status': '✅ Closed' if c['status']=='closed' else '🟢 Open',
                    'Qty': int(c['total_shares']), 'Avg Price': c['blended_basis'],
                    'Eff. Basis': effb, 'Premiums': c['premiums'],
                    'Divs': c['dividends'], 'Exit': c['exit_proceeds'],
                    'P/L': rpnl, 'Days': dur.days,
                    'Opened': c['start_date'].strftime('%d/%m/%y')})
        summary_df = pd.DataFrame(rows)
        def color_pnl(val):
            if not isinstance(val, float): return ''
            return 'color: #00cc96' if val > 0 else 'color: #ef553b' if val < 0 else ''
        st.dataframe(summary_df.style.format({
            'Avg Price': lambda x: '${:,.2f}'.format(x),
            'Eff. Basis': lambda x: '${:,.2f}'.format(x),
            'Premiums': lambda x: '${:,.2f}'.format(x),
            'Divs': lambda x: '${:,.2f}'.format(x),
            'Exit': lambda x: '${:,.2f}'.format(x),
            'P/L': lambda x: '${:,.2f}'.format(x)
        }).map(color_pnl, subset=['P/L']), width='stretch', hide_index=True)
        st.markdown('---')

        for ticker, camps in sorted(all_campaigns.items()):
            for i, c in enumerate(camps):
                rpnl = realized_pnl(c, use_lifetime); effb = effective_basis(c, use_lifetime)
                is_open  = c['status'] == 'open'
                status_badge = '🟢 OPEN' if is_open else '✅ CLOSED'
                pnl_color    = '#00cc96' if rpnl >= 0 else '#ef553b'
                basis_reduction = c['blended_basis'] - effb
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
                    ticker=ticker, camp_n=i+1, status=status_badge,
                    badge_bg='rgba(0,204,150,0.15)' if is_open else 'rgba(100,100,100,0.2)',
                    badge_col='#00cc96' if is_open else '#888',
                    shares=int(c['total_shares']),
                    entry_basis=c['blended_basis'], eff_basis=effb,
                    reduction=basis_reduction if basis_reduction > 0 else 0,
                    premiums=c['premiums'], pnl=rpnl, pnl_color=pnl_color
                )
                st.markdown(card_html, unsafe_allow_html=True)
                with st.expander('📊 Detail — Chains & Events', expanded=is_open):
                    ticker_opts = df[(df['Ticker']==ticker) &
                        df['Instrument Type'].str.contains('Option', na=False)].copy()
                    camp_start = c['start_date']
                    camp_end   = c['end_date'] or latest_date
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
                            n_rolls = sum(1 for l in chain if 'to close' in str(l['sub_type']).lower())
                            status_icon = '🟢' if is_open_chain else '✅'
                            cp_icon = '📞' if cp == 'CALL' else '📉'
                            chain_label = '%s %s %s Chain %d — %d roll(s) | Net: $%.2f' % (
                                status_icon, cp_icon, cp.title(), ci+1, n_rolls, ch_pnl)
                            with st.expander(chain_label, expanded=is_open_chain):
                                chain_rows = []
                                for leg_i, leg in enumerate(chain):
                                    sub = str(leg['sub_type']).lower()
                                    if 'to open' in sub:       action = '↪️ Sell to Open'
                                    elif 'to close' in sub:    action = '↩️ Buy to Close'
                                    elif 'expir' in sub:       action = '⏹️ Expired'
                                    elif 'assign' in sub:      action = '📋 Assigned'
                                    else:                      action = leg['sub_type']
                                    dte_str = ''
                                    if 'to open' in sub:
                                        try:
                                            exp_dt = pd.to_datetime(leg['exp'], dayfirst=True)
                                            dte_str = '%dd' % max((exp_dt - leg['date'].replace(tzinfo=None)).days, 0)
                                        except: dte_str = ''
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
                                def _style_chain_row(row):
                                    if row.get('_open', False):
                                        return ['background-color: rgba(0,204,150,0.12); font-weight:600'] * len(row)
                                    return [''] * len(row)
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
                    ev_df = pd.DataFrame(c['events'])
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

# ── Tab 3: All Trades ──────────────────────────────────────────────────────────
with tab3:
    st.subheader('🔍 Realized P/L — All Tickers')
    rows = []
    for ticker, camps in sorted(all_campaigns.items()):
        tr = sum(realized_pnl(c, use_lifetime) for c in camps)
        td = sum(c['total_cost'] for c in camps if c['status']=='open')
        tp = sum(c['premiums'] for c in camps)
        tv = sum(c['dividends'] for c in camps)
        po = pure_options_pnl(df, ticker, camps)
        oc = sum(1 for c in camps if c['status']=='open')
        cc = sum(1 for c in camps if c['status']=='closed')
        rows.append({'Ticker': ticker, 'Type': '🎡 Wheel',
            'Campaigns': '%d open, %d closed'%(oc,cc),
            'Premiums': tp, 'Divs': tv,
            'Options P/L': po, 'Deployed': td, 'P/L': tr+po})
    for ticker in sorted(pure_options_tickers):
        mask = (df['Ticker']==ticker) & (df['Type'].isin(['Trade','Receive Deliver']))
        total_val = df.loc[mask,'Total'].sum()
        t_df = df[df['Ticker'] == ticker]
        s_mask = t_df['Instrument Type'].str.contains('Equity', na=False) & \
                 ~t_df['Instrument Type'].str.contains('Option', na=False)
        net_shares = t_df[s_mask]['Net_Qty_Row'].sum()
        cap_dep = 0.0; pnl = total_val
        if net_shares > 0.0001:
            eq_flow = t_df[(t_df['Instrument Type'].str.contains('Equity', na=False)) &
                           (t_df['Type'].isin(['Trade','Receive Deliver']))]['Total'].sum()
            if eq_flow < 0:
                cap_dep = abs(eq_flow)
                pnl = total_val + cap_dep
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
        def color_pnl2(val):
            if not isinstance(val, (int, float)): return ''
            return 'color: #00cc96' if val > 0 else 'color: #ef553b' if val < 0 else ''
        st.dataframe(deep_df.style.format({
            'Premiums': lambda x: '${:,.2f}'.format(x),
            'Divs': lambda x: '${:,.2f}'.format(x),
            'Options P/L': lambda x: '${:,.2f}'.format(x),
            'Deployed': lambda x: '${:,.2f}'.format(x),
            'P/L': lambda x: '${:,.2f}'.format(x)
        }).map(color_pnl2, subset=['P/L']), width='stretch', hide_index=True)

    # ── Total Portfolio P/L by Week & Month ───────────────────────────────────
    st.markdown('---')
    st.markdown('<div style="font-size:1.05rem;font-weight:600;color:#e6edf3;margin:28px 0 2px 0;letter-spacing:0.01em;">📅 Total Realized P/L by Week &amp; Month</div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.8rem;color:#6b7280;margin-bottom:12px;line-height:1.5;">'
        '<b style="color:#00cc96;">Whole portfolio — realized flows only</b>: '
        'options credits &amp; debits, share <em>sales</em> (FIFO gains/losses), dividends, and interest. '
        '<b>Share purchases are excluded</b> — they are capital deployment, not realized losses. '
        'This matches the <b>Realized P/L</b> top-line metric. Filtered to selected time window.'
        '</div>',
        unsafe_allow_html=True
    )

    # Build daily realized P/L using same FIFO logic as top-line metric
    _daily_pnl = calculate_daily_realized_pnl(df, start_date)
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
                hovertemplate='Week of %{x|%d %b}<br><b>$%{y:,.2f}</b><extra></extra>'
            ))
            _fig_pw.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
            _pw_lay = chart_layout('Weekly Total P/L', height=280, margin_t=36)
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
                textposition='outside',
                textfont=dict(size=10, family='IBM Plex Mono', color='#8b949e'),
                hovertemplate='%{x}<br><b>$%{y:,.2f}</b><extra></extra>'
            ))
            _fig_pm.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
            _pm_lay = chart_layout('Monthly Total P/L', height=280, margin_t=36)
            _pm_lay['yaxis']['tickprefix'] = '$'
            _pm_lay['yaxis']['tickformat'] = ',.0f'
            _pm_lay['bargap'] = 0.35
            _fig_pm.update_layout(**_pm_lay)
            st.plotly_chart(_fig_pm, width='stretch', config={'displayModeBar': False})
    else:
        st.info('No cash flow data in the selected window.')

# ── Tab 4: Income & Fees ───────────────────────────────────────────────────────
with tab4:
    st.subheader('💰 Non-Trade Cash Flows')
    ic1, ic2, ic3, ic4 = st.columns(4)
    ic1.metric('Deposited',      '$%.2f' % total_deposited)
    ic2.metric('Withdrawn',      '$%.2f' % abs(total_withdrawn))
    ic3.metric('Dividends',      '$%.2f' % div_income)
    ic4.metric('Interest (net)', '$%.2f' % int_net)
    income_df = df_window[df_window['Sub Type'].isin(
        ['Dividend','Credit Interest','Debit Interest','Balance Adjustment']
    )][['Date','Ticker','Sub Type','Description','Total']].sort_values('Date', ascending=False)
    if not income_df.empty:
        st.dataframe(income_df.style.format({'Total': lambda x: '${:,.2f}'.format(x)}),
            width='stretch', hide_index=True)
    else:
        st.info('No income / fee events in this window.')