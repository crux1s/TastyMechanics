import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from collections import defaultdict

# ==========================================
# TastyMechanics v24
# ==========================================
# Updates:
#   - RENAMED: App is now TastyMechanics.
#   - FIXED: Added Covered Strangle & Covered Straddle detection to closed trades.
#   - RETAINED: Fractional share cost basis logic and 5-tab layout.
#   - FIXED: Realized P/L now excludes the cost of open fractional shares 
#     (UNH, META, etc.) and correctly treats them as Capital Deployed.
# ==========================================

st.set_page_config(page_title="TastyMechanics", layout="wide")
st.markdown("""
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    div[data-testid="stMetricValue"] { font-size: 1.35rem !important; color: #00cc96; }
    .stTable { font-size: 0.85rem !important; }
    [data-testid="stExpander"] { background: #161b22; border-radius: 8px;
        border: 1px solid #30363d; margin-bottom: 5px; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { background-color: #111418;
        border-radius: 4px 4px 0px 0px; padding: 8px 16px; }
    .sync-header { color: #8b949e; font-size: 0.95rem;
        margin-top: -15px; margin-bottom: 25px; line-height: 1.5; }
    .highlight-range { color: #58a6ff; font-weight: bold; }
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

def detect_strategy(ticker_df):
    types = [identify_pos_type(r) for _, r in ticker_df.iterrows()]
    ls = types.count('Long Stock');  sc = types.count('Short Call')
    lc = types.count('Long Call');   sp = types.count('Short Put')
    lp = types.count('Long Put')
    strikes  = ticker_df['Strike Price'].dropna().unique()
    exps     = ticker_df['Expiration Date'].dropna().unique()
    # Calendar: same strike, different expirations
    if lc > 0 and sc > 0 and len(exps) >= 2 and len(strikes) == 1: return 'Calendar Spread'
    if lp > 0 and sp > 0 and len(exps) >= 2 and len(strikes) == 1: return 'Calendar Spread'
    # Butterfly: 2 long + 1 short (x2), 3 strikes, same expiry
    if lc == 2 and sc == 1 and len(strikes) == 3 and len(exps) == 1: return 'Call Butterfly'
    if lp == 2 and sp == 1 and len(strikes) == 3 and len(exps) == 1: return 'Put Butterfly'
    if ls > 0 and sc > 0 and sp > 0:    return 'Covered Strangle'
    if ls > 0 and sc > 0:               return 'Covered Call'
    if sp >= 1 and sc >= 1 and lc >= 1: return 'Jade Lizard'
    if sc >= 1 and sp >= 1 and lp >= 1: return 'Big Lizard'
    if sc >= 1 and sp >= 1:             return 'Short Strangle'
    if lc >= 1 and sp >= 1:             return 'Risk Reversal'
    if lc > 1  and sc > 0:             return 'Call Debit Spread'
    if sp > 0:  return 'Short Put'
    if lc > 0:  return 'Long Call'
    if ls > 0:  return 'Long Stock'
    return 'Custom/Mixed'

# ── WHEEL CAMPAIGN ENGINE ──────────────────────────────────────────────────────

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

            # Calendar spread: same strike(s), different expirations
            expirations = grp['Expiration Date'].dropna().unique()
            strikes_all = grp['Strike Price'].dropna().unique()
            is_calendar = len(expirations) >= 2 and len(strikes_all) == 1

            # Butterfly: 2 long legs + 1 short leg (x2 qty), same type, 3 strikes, equal wings
            short_opens_sp = opens[opens['Net_Qty_Row'] < 0]
            long_opens_sp  = opens[opens['Net_Qty_Row'] > 0]
            n_short_legs   = len(short_opens_sp)
            n_long_legs    = len(long_opens_sp)
            short_qty_total = abs(short_opens_sp['Net_Qty_Row'].sum())
            long_qty_total  = long_opens_sp['Net_Qty_Row'].sum()
            is_butterfly = (n_long_legs == 2 and n_short_legs == 1 and
                            short_qty_total == 2 and long_qty_total == 2 and
                            len(strikes_all) == 3 and len(expirations) == 1)

            # Jade Lizard: short put + short call spread (sc + lc at higher strike), no put spread
            # Structure: 1 short put (no long put) + 1 short call + 1 long call above it
            short_cp = short_opens_sp['Call or Put'].dropna().str.upper().tolist()
            long_cp  = long_opens_sp['Call or Put'].dropna().str.upper().tolist()
            has_short_put_only  = any('PUT'  in c for c in short_cp) and not any('PUT'  in c for c in long_cp)
            has_call_spread_leg = any('CALL' in c for c in short_cp) and any('CALL' in c for c in long_cp)
            is_jade_lizard = has_short_put_only and has_call_spread_leg and len(put_strikes) == 1

            if is_butterfly:
                if len(call_strikes.unique()) == 3:
                    trade_type = 'Call Butterfly'
                else:
                    trade_type = 'Put Butterfly'
                wing_width = (strikes_all.max() - strikes_all.min()) * 100 / 2
                capital_risk = max(abs(open_credit), wing_width, 1)
            elif is_jade_lizard:
                trade_type   = 'Jade Lizard'
                spread_width = w_call
                capital_risk = max(spread_width - abs(open_credit), 1)
            elif is_calendar:
                trade_type   = 'Calendar Spread'
                capital_risk = max(abs(open_credit), 1)
            elif w_call > 0 and w_put > 0:
                trade_type, spread_width = 'Iron Condor', max(w_call, w_put)
                capital_risk = max(spread_width - abs(open_credit), 1)
            elif w_call > 0:
                trade_type   = 'Call Credit Spread' if is_credit else 'Call Debit Spread'
                spread_width = w_call
                capital_risk = max(spread_width - abs(open_credit), 1)
            else:
                trade_type   = 'Put Credit Spread' if is_credit else 'Put Debit Spread'
                spread_width = w_put
                capital_risk = max(spread_width - abs(open_credit), 1)
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
                # Debit single-leg longs
                if has_lc and not has_lp: trade_type = 'Long Call'
                elif has_lp and not has_lc: trade_type = 'Long Put'
                else: trade_type = 'Long Strangle'
            else:
                if has_sc and has_sp:
                    all_strikes = grp['Strike Price'].dropna().unique()
                    trade_type = 'Short Straddle' if len(all_strikes) == 1 else 'Short Strangle'

                    # Check if we hold shares to make it a 'Covered' Strangle/Straddle
                    windows = campaign_windows.get(ticker, [])
                    in_campaign = any(s <= open_date <= e for s, e in windows)
                    if in_campaign:
                        trade_type = 'Covered Straddle' if 'Straddle' in trade_type else 'Covered Strangle'
                elif has_sc:
                    windows = campaign_windows.get(ticker, [])
                    in_campaign = any(s <= open_date <= e for s, e in windows)
                    if in_campaign:
                        trade_type = 'Covered Call'
                    else:
                        trade_type = 'Short Call' if n_contracts == 1 else 'Short Call (x%d)' % n_contracts
                elif has_sp:
                    trade_type = 'Short Put' if n_contracts == 1 else 'Short Put (x%d)' % n_contracts
                else:
                    trade_type = 'Short (other)'

        # DTE at open: days from open_date to nearest expiration of the opening legs
        try:
            exp_dates = opens['Expiration Date'].dropna()
            if not exp_dates.empty:
                nearest_exp = pd.to_datetime(exp_dates.iloc[0])
                dte_open = max((nearest_exp - open_date.replace(tzinfo=None)).days, 0)
            else:
                dte_open = None
        except: dte_open = None

        closed_list.append({
            'Ticker': ticker, 'Trade Type': trade_type, 'Type': 'Call' if 'CALL' in cp else 'Put' if 'PUT' in cp else 'Mixed',
            'Spread': n_long > 0, 'Is Credit': is_credit, 'Days Held': days_held,
            'Open Date': open_date, 'Close Date': close_date, 'Premium Rcvd': open_credit,
            'Net P/L': net_pnl, 'Capture %': net_pnl / open_credit * 100 if is_credit else None,
            'Capital Risk': capital_risk, 'Ann Return %': max(min(net_pnl / capital_risk * 365 / days_held * 100, 500), -500) if (is_credit and capital_risk > 0) else None,
            'Prem/Day': open_credit / days_held if is_credit else None, 'Won': net_pnl > 0,
            'DTE Open': dte_open,
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
                'strike': row['Strike Price'], 'exp': pd.to_datetime(row['Expiration Date']).strftime('%d/%m/%y') if pd.notna(row['Expiration Date']) else '',
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

st.title('📟 TastyMechanics v24')

with st.sidebar:
    st.header('⚙️ Data Control')
    uploaded_file = st.file_uploader('Upload TastyTrade History CSV', type='csv')
    st.markdown('---')
    time_options = ['YTD', 'Last 5 Days', 'Last Month', 'Last 3 Months', 'Half Year', '1 Year', 'All Time']
    selected_period = st.selectbox('Time Window', time_options, index=6)
    
    st.markdown('---')
    st.header('🎯 Campaign Settings')
    use_lifetime = st.toggle('Show Lifetime "House Money"', value=False, 
        help='If ON, combines ALL history for a ticker into one campaign. If OFF, resets breakeven every time shares hit zero.')

if not uploaded_file:
    st.info('🛰️ **TastyMechanics v24 Ready.** Upload your TastyTrade CSV to begin.')
    st.stop()

# ── load ───────────────────────────────────────────────────────────────────────

df = pd.read_csv(uploaded_file)
df['Date'] = pd.to_datetime(df['Date'], utc=True)
for col in ['Total', 'Quantity', 'Commissions', 'Fees']: df[col] = df[col].apply(clean_val)
df['Ticker']      = df['Underlying Symbol'].fillna(df['Symbol'].str.split().str[0]).fillna('CASH')
df['Net_Qty_Row'] = df.apply(get_signed_qty, axis=1)
df = df.sort_values('Date').reset_index(drop=True)

latest_date = df['Date'].max()

if   selected_period == 'All Time':      start_date = df['Date'].min()
elif selected_period == 'YTD':           start_date = pd.Timestamp(latest_date.year, 1, 1, tz='UTC')
elif selected_period == 'Last 5 Days':   start_date = latest_date - timedelta(days=5)
elif selected_period == 'Last Month':    start_date = latest_date - timedelta(days=30)
elif selected_period == 'Last 3 Months': start_date = latest_date - timedelta(days=90)
elif selected_period == 'Half Year':     start_date = latest_date - timedelta(days=182)
elif selected_period == '1 Year':        start_date = latest_date - timedelta(days=365)

df_window = df[df['Date'] >= start_date].copy()
window_label = '🗓 Window: %s → %s (%s)' % (
    start_date.strftime('%d/%m/%Y'), latest_date.strftime('%d/%m/%Y'), selected_period)

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

all_tickers           = [t for t in df['Ticker'].unique() if t != 'CASH']
pure_options_tickers = [t for t in all_tickers if t not in wheel_tickers]

# ── derivatives metrics ────────────────────────────────────────────────────────


# Build campaign windows for covered call detection
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
capital_deployed     = sum(c['total_cost'] for camps in all_campaigns.values()
                           for c in camps if c['status'] == 'open')

pure_opts_pnl = 0.0
extra_capital_deployed = 0.0 # NEW: Capture cost of fractional shares

for t in pure_options_tickers:
    # UPDATED LOGIC: Check if we hold shares. If so, move cost to Capital Deployed.
    t_df = df[df['Ticker'] == t]
    mask = (df['Ticker']==t) & (df['Type'].isin(['Trade','Receive Deliver']))
    total_flow = df.loc[mask, 'Total'].sum()
    
    # Check net shares for this "pure" ticker
    s_mask = t_df['Instrument Type'].str.contains('Equity', na=False) & ~t_df['Instrument Type'].str.contains('Option', na=False)
    net_shares = t_df[s_mask]['Net_Qty_Row'].sum()
    
    if net_shares > 0.0001:
        # We hold shares. Calculate the cost (negative equity flow)
        equity_flow = t_df[(t_df['Instrument Type'].str.contains('Equity', na=False)) & (t_df['Type'].isin(['Trade','Receive Deliver']))]['Total'].sum()
        if equity_flow < 0:
            # Add back the cost to P/L (so it's not a loss)
            pure_opts_pnl += (total_flow + abs(equity_flow))
            # Add the cost to Capital Deployed
            extra_capital_deployed += abs(equity_flow)
        else:
            pure_opts_pnl += total_flow
    else:
        pure_opts_pnl += total_flow

# Also add extra capital to the wheel campaigns cost if needed, but wheel campaigns handle it internally.
# But pure_options_pnl loop above handles tickers NOT in wheel_tickers list.
# What about pre-campaign options for wheel tickers?
for ticker, camps in all_campaigns.items():
    pure_opts_pnl += pure_options_pnl(df, ticker, camps)

total_realized_pnl = closed_camp_pnl + open_premiums_banked + pure_opts_pnl
capital_deployed += extra_capital_deployed

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
m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric('Realized P/L',    '$%.2f' % total_realized_pnl)
m1.caption('All cash actually banked — premiums collected, campaigns closed, standalone trades. Unrealised share P/L not included.')
m2.metric('Realized ROR',    '%.1f%%' % realized_ror)
m2.caption('Realized P/L as a %% of net deposits. How hard your deposited capital is working.')
m3.metric('Capital Deployed','$%.2f' % capital_deployed)
m3.caption('Cash tied up in open share positions (wheel campaigns + any fractional holdings). Options margin not included.')
m4.metric('Margin Loan',     '$%.2f' % margin_loan)
m4.caption('Negative cash balance — what you currently owe the broker. Zero is ideal unless deliberately leveraging.')
m5.metric('Div + Interest',  '$%.2f' % (div_income + int_net))
m5.caption('Dividends received plus net interest (credit earned minus debit charged on margin). Filtered to selected time window.')
m6.metric('Account Age',     '%d days' % account_days)
m6.caption('Days since your first transaction. Useful context for how long your track record covers.')

with st.expander('💡 Realized P/L Breakdown', expanded=False):
    b1, b2, b3, b4 = st.columns(4)
    b1.metric('Closed Campaign P/L',    '$%.2f' % closed_camp_pnl)
    b1.caption('P/L from fully closed wheel campaigns — shares bought, options traded, shares sold. Complete cycles only.')
    b2.metric('Open Campaign Premiums', '$%.2f' % open_premiums_banked)
    b2.caption('Premiums banked so far in campaigns still running. Shares not yet sold so overall campaign P/L not finalised.')
    b3.metric('Standalone Trades P/L', '$%.2f' % pure_opts_pnl)
    b3.caption('Everything outside wheel campaigns — standalone options, futures options, index trades, pre/post-campaign options on wheel tickers.')
    b4.metric('Total Realized',         '$%.2f' % total_realized_pnl)
    b4.caption('Sum of all three above. The single number that matters — real cash generated by your trading.')

# ── Sparkline equity curve ───────────────────────────────────────────────────
if not closed_trades_df.empty:
    _spark_df = closed_trades_df[closed_trades_df['Close Date'] >= start_date].sort_values('Close Date').copy()
    if _spark_df.empty:
        _spark_df = closed_trades_df.sort_values('Close Date').copy()
    _spark_df['Cum P/L'] = _spark_df['Net P/L'].cumsum()
    _spark_color = '#00cc96' if _spark_df['Cum P/L'].iloc[-1] >= 0 else '#ef553b'
    _fill_color  = 'rgba(0,204,150,0.15)' if _spark_color == '#00cc96' else 'rgba(239,85,59,0.15)'
    import plotly.graph_objects as go
    _fig_spark = go.Figure()
    _fig_spark.add_trace(go.Scatter(
        x=_spark_df['Close Date'], y=_spark_df['Cum P/L'],
        mode='lines', line=dict(color=_spark_color, width=1.5),
        fill='tozeroy', fillcolor=_fill_color,
        hovertemplate='%{x|%d/%m/%y}<br>$%{y:,.2f}<extra></extra>'
    ))
    _fig_spark.add_hline(y=0, line_color='rgba(255,255,255,0.15)', line_width=1)
    _fig_spark.update_layout(
        height=80, margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        showlegend=False
    )
    st.plotly_chart(_fig_spark, width='stretch', config={'displayModeBar': False})

st.markdown('---')

# ── TABS (full width) ──────────────────────────────────────────────────────────
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
                exp  = pd.to_datetime(row['Expiration Date']).tz_localize(latest_date.tzinfo)
                return '%dd' % max((exp - latest_date).days, 0)
            except: return 'N/A'

        df_open['DTE'] = df_open.apply(calc_dte, axis=1)
        tickers_open = [t for t in sorted(df_open['Ticker'].unique()) if t != 'CASH']
        cols = st.columns(3)
        for i, ticker in enumerate(tickers_open):
            with cols[i % 3]:
                t_df = df_open[df_open['Ticker'] == ticker].copy()
                with st.expander('%s — %s' % (ticker, detect_strategy(t_df)), expanded=True):
                    show = t_df[['Status','Details','DTE','Cost Basis']].sort_values('Status')
                    show.columns = ['Type','Position','DTE','Basis']
                    st.dataframe(show.style.format({'Basis': format_cost_basis}),
                        width='stretch', hide_index=True)


# ── Tab 1: Derivatives Performance ────────────────────────────────────────
with tab1:
    if closed_trades_df.empty:
        st.info('No closed trades found.')
    else:
        all_cdf = window_trades_df if not window_trades_df.empty else closed_trades_df
        credit_cdf = all_cdf[all_cdf['Is Credit']].copy() if not all_cdf.empty else pd.DataFrame()
        has_credit = not credit_cdf.empty
        has_data = not all_cdf.empty

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
            total_credit_rcvd = credit_cdf['Premium Rcvd'].sum()
            total_net_pnl_closed = credit_cdf['Net P/L'].sum()
            window_days = max((latest_date - start_date).days, 1)
            dm1.metric('Win Rate', '%.1f%%' % (credit_cdf['Won'].mean() * 100))
            dm2.metric('Median Capture %', '%.1f%%' % credit_cdf['Capture %'].median())
            dm3.metric('Median Days Held', '%.0f' % credit_cdf['Days Held'].median())
            dm4.metric('Median Ann. Return', '%.0f%%' % credit_cdf['Ann Return %'].median())
            dm5.metric('Med Premium/Day', '$%.2f' % credit_cdf['Prem/Day'].median())
            dm6.metric('Banked $/Day', '$%.2f' % (total_net_pnl_closed / window_days),
                delta='vs $%.2f gross' % (total_credit_rcvd / window_days),
                delta_color='normal')
        else:
            st.info('No closed credit trades in this window.')

        if has_data:
            st.markdown('---')
            col1, col2 = st.columns(2)
            with col1:
                if has_credit:
                    bins = [-999, 0, 25, 50, 75, 100, 999]
                    labels = ['Loss', '0–25%', '25–50%', '50–75%', '75–100%', '>100%']
                    credit_cdf['Bucket'] = pd.cut(credit_cdf['Capture %'], bins=bins, labels=labels)
                    bucket_df = credit_cdf.groupby('Bucket', observed=False).agg(
                        Trades=('Net P/L', 'count')).reset_index()
                    colors = ['#ef553b','#ffa421','#ffe066','#7ec8e3','#00cc96','#58a6ff']
                    fig_cap = px.bar(bucket_df, x='Bucket', y='Trades', color='Bucket',
                        color_discrete_sequence=colors,
                        title='Premium Capture % Distribution (Credit Trades)', text='Trades')
                    fig_cap.update_layout(template='plotly_dark', height=300, showlegend=False)
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
                    type_df.columns = ['Type','Trades','Win %','Med Capture %','Total P/L','$/Day','Med Days','Med DTE']
                    st.markdown('##### 📊 Call vs Put Performance')
                    st.caption('Do you perform better selling calls or puts? Skew, IV rank and stock direction all affect which side pays more. Mixed = multi-leg trades with both calls and puts (strangles, iron condors, lizards). Knowing your edge by type helps you lean into your strengths.')
                    st.dataframe(type_df.style.format({
                        'Win %': lambda x: '{:.1f}%'.format(x),
                        'Med Capture %': lambda x: '{:.1f}%'.format(x),
                        'Total P/L': lambda x: '${:,.2f}'.format(x),
                        '$/Day': lambda x: '${:.2f}'.format(x),
                        'Med Days': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                        'Med DTE': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                    }).map(color_win_rate, subset=['Win %'])
                    .map(lambda v: 'color: #00cc96' if isinstance(v,(int,float)) and v>0
                        else ('color: #ef553b' if isinstance(v,(int,float)) and v<0 else ''),
                        subset=['Total P/L']),
                    width='stretch', hide_index=True)
                    strat_df = all_cdf.groupby('Trade Type').agg(
                        Trades=('Won','count'),
                        Win_Rate=('Won', lambda x: x.mean()*100),
                        Total_PNL=('Net P/L','sum'),
                        Med_Capture=('Capture %','median'),
                        Med_Days=('Days Held','median'),
                        Med_DTE=('DTE Open','median'),
                    ).reset_index().sort_values('Total_PNL', ascending=False).round(1)
                    strat_df.columns = ['Strategy','Trades','Win %','Total P/L','Med Capture %','Med Days','Med DTE']
                    st.markdown('##### 🧩 Defined vs Undefined Risk — by Strategy')
                    st.caption('All closed trades — credit and debit. Naked = undefined risk, higher premium. Spreads/Condors = defined max loss, less credit. Debit spreads show P/L but no capture % (not applicable). Are your defined-risk trades worth the premium you give up for the protection?')
                    st.dataframe(strat_df.style.format({
                        'Win %': lambda x: '{:.1f}%'.format(x),
                        'Med Capture %': lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                        'Total P/L': lambda x: '${:,.2f}'.format(x),
                        'Med Days': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                        'Med DTE': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                    }).map(color_win_rate, subset=['Win %'])
                    .map(lambda v: 'color: #00cc96' if isinstance(v,(int,float)) and v>0
                        else ('color: #ef553b' if isinstance(v,(int,float)) and v<0 else ''),
                        subset=['Total P/L']),
                    width='stretch', hide_index=True)

            st.markdown('---')
            st.markdown('#### Performance by Ticker')
            st.caption(
                'All closed trades — credit and debit — grouped by underlying. '
                '**Win %** counts any trade that closed positive, regardless of size. '
                '**Total P/L** is your actual net result after all opens and closes on that ticker. '
                '**Med Days** = median holding period across all trades — typical time in the trade, resistant to outliers like a single long-dated position or 0DTE skewing the average. '
                '**Med Capture %** = median percentage of opening credit you kept at close — credit trades only. '
                'TastyTrade targets 50% capture; higher means you let trades run longer, lower means you took profits early. '
                'Debit trades show — as capture % is not applicable. '
                '**Med Ann Ret %** = median annualised return on capital at risk — normalises trades of different sizes and durations so you can compare efficiency across tickers. '
                'Capped at ±500% to prevent 0DTE trades producing meaningless astronomical figures. '
                'Treat this number cautiously on tickers with few trades — small sample sizes make it unreliable. '
                '**Total Credit Rcvd** = gross cash received when opening credit trades, before buyback costs. '
                'The gap between this and Total P/L is your total spend closing positions.'
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
            ticker_df.columns = ['Ticker','Trades','Win %','Total P/L','Med Days',
                                 'Med Capture %','Med Ann Ret %','Total Credit Rcvd']

            st.dataframe(
                ticker_df.style.format({
                    'Win %': lambda x: '{:.1f}%'.format(x),
                    'Total P/L': lambda x: '${:,.2f}'.format(x),
                    'Med Days': lambda v: '{:.0f}d'.format(v) if pd.notna(v) else '—',
                    'Med Capture %': lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                    'Med Ann Ret %': lambda v: '{:.0f}%'.format(v) if pd.notna(v) else '—',
                    'Total Credit Rcvd': lambda v: '${:.2f}'.format(v) if pd.notna(v) else '—'
                }).map(color_win_rate, subset=['Win %'])
                .map(color_pnl_cell, subset=['Total P/L']),
                width='stretch', hide_index=True
            )

            st.markdown('---')
            st.markdown('#### 🗓 P/L by Ticker & Month')
            st.caption(
                'Net P/L per ticker per calendar month, based on close date. '
                'Green = profitable month for that ticker, red = losing month. '
                'Intensity shows size — dark green is a big win, dark red is a big loss. '
                'Grey = no closed trades that month.'
            )
            _hm_df = all_cdf.copy()
            _hm_df['Month'] = pd.to_datetime(_hm_df['Close Date']).dt.strftime('%b %Y')
            _hm_df['MonthSort'] = pd.to_datetime(_hm_df['Close Date']).dt.strftime('%Y-%m')
            _hm_pivot = _hm_df.groupby(['Ticker','MonthSort','Month'])['Net P/L'].sum().reset_index()
            _months_sorted = sorted(_hm_pivot['MonthSort'].unique())
            _month_labels  = [_hm_pivot[_hm_pivot['MonthSort']==m]['Month'].iloc[0] for m in _months_sorted]
            _tickers_sorted = sorted(_hm_pivot['Ticker'].unique(), 
                key=lambda t: _hm_pivot[_hm_pivot['Ticker']==t]['Net P/L'].sum(), reverse=True)

            # Build matrix
            import numpy as np
            _z  = []
            _text = []
            for tkr in _tickers_sorted:
                row_z, row_t = [], []
                for ms in _months_sorted:
                    val = _hm_pivot[(_hm_pivot['Ticker']==tkr) & (_hm_pivot['MonthSort']==ms)]['Net P/L'].sum()
                    row_z.append(val if val != 0 else None)
                    row_t.append('$%.0f' % val if val != 0 else '')
                _z.append(row_z)
                _text.append(row_t)

            _fig_hm = go.Figure(data=go.Heatmap(
                z=_z, x=_month_labels, y=_tickers_sorted,
                text=_text, texttemplate='%{text}',
                colorscale=[
                    [0.0,  '#7f1d1d'], [0.35, '#ef553b'],
                    [0.5,  '#1a1a2e'],
                    [0.65, '#00cc96'], [1.0,  '#004d3a'],
                ],
                zmid=0,
                showscale=True,
                colorbar=dict(title='P/L ($)', tickformat='$,.0f'),
                hoverongaps=False,
                hovertemplate='%{y} — %{x}<br>P/L: $%{z:,.2f}<extra></extra>',
            ))
            _fig_hm.update_layout(
                template='plotly_dark',
                height=max(280, len(_tickers_sorted) * 28),
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis=dict(side='top'),
                yaxis=dict(autorange='reversed'),
            )
            st.plotly_chart(_fig_hm, width='stretch', config={'displayModeBar': False})

            st.markdown('---')
            cum_df = all_cdf.sort_values('Close Date').copy()
            cum_df['Cumulative P/L'] = cum_df['Net P/L'].cumsum()
            fig_eq = px.line(cum_df, x='Close Date', y='Cumulative P/L',
                title='Cumulative Realized P/L', height=260)
            fig_eq.update_traces(line_color='#00cc96', fill='tozeroy')
            fig_eq.update_layout(template='plotly_dark')
            st.plotly_chart(fig_eq, width='stretch', config={'displayModeBar': False})

            if has_credit:
                roll_df = credit_cdf.sort_values('Close Date').copy()
                roll_df['Rolling Capture'] = roll_df['Capture %'].rolling(10, min_periods=1).mean()
                fig_cap2 = px.line(roll_df, x='Close Date', y='Rolling Capture',
                    title='Rolling Avg Capture % (10-trade window)', height=220)
                fig_cap2.update_traces(line_color='#58a6ff')
                fig_cap2.add_hline(y=50, line_dash='dash', line_color='#ffa421')
                fig_cap2.update_layout(template='plotly_dark')
                st.plotly_chart(fig_cap2, width='stretch', config={'displayModeBar': False})

            st.markdown('---')
            st.markdown('##### 📊 Win / Loss Distribution')
            st.caption(
                'Each bar is one trade — green bars are winners, red are losers. '
                'A healthy theta engine shows many small green bars clustered near zero and at the 50% capture target, '
                'with losses contained and not wider than the win cluster. '
                'Fat red tails mean losses are outsized relative to wins — the key risk to manage.'
            )
            _hist_df = all_cdf.copy()
            _hist_df['Colour'] = _hist_df['Net P/L'].apply(lambda x: 'Win' if x >= 0 else 'Loss')
            _fig_hist = px.histogram(
                _hist_df, x='Net P/L', color='Colour',
                color_discrete_map={'Win': '#00cc96', 'Loss': '#ef553b'},
                nbins=40, height=280,
                labels={'Net P/L': 'Trade P/L ($)', 'count': 'Trades'},
                barmode='overlay', opacity=0.85
            )
            _fig_hist.add_vline(x=0, line_color='rgba(255,255,255,0.3)', line_width=1)
            _fig_hist.add_vline(
                x=all_cdf['Net P/L'].median(),
                line_dash='dash', line_color='#ffa421', line_width=1.5,
                annotation_text='median $%.0f' % all_cdf['Net P/L'].median(),
                annotation_position='top right', annotation_font_color='#ffa421'
            )
            _fig_hist.update_layout(
                template='plotly_dark', showlegend=True,
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                margin=dict(t=30, b=0)
            )
            st.plotly_chart(_fig_hist, width='stretch', config={'displayModeBar': False})

            st.markdown('---')
            bcol, wcol = st.columns(2)
            with bcol:
                st.markdown('##### 🏆 Best 5 Trades')
                best = all_cdf.nlargest(5, 'Net P/L')[['Ticker','Trade Type','Type','Days Held','Premium Rcvd','Net P/L']].copy()
                st.dataframe(best.style.format({
                    'Premium Rcvd': lambda x: '${:.2f}'.format(x),
                    'Net P/L': lambda x: '${:.2f}'.format(x)
                }), width='stretch', hide_index=True)
            with wcol:
                st.markdown('##### 💀 Worst 5 Trades')
                worst = all_cdf.nsmallest(5, 'Net P/L')[['Ticker','Trade Type','Type','Days Held','Premium Rcvd','Net P/L']].copy()
                st.dataframe(worst.style.format({
                    'Premium Rcvd': lambda x: '${:.2f}'.format(x),
                    'Net P/L': lambda x: '${:.2f}'.format(x)
                }), width='stretch', hide_index=True)

            with st.expander('📋 Full Closed Trade Log', expanded=False):
                log = all_cdf[['Ticker','Trade Type','Type','Open Date','Close Date',
                               'Days Held','Premium Rcvd','Net P/L','Capture %',
                               'Capital Risk','Ann Return %','Won']].copy()
                log['Open Date']  = pd.to_datetime(log['Open Date']).dt.strftime('%d/%m/%y')
                log['Close Date'] = pd.to_datetime(log['Close Date']).dt.strftime('%d/%m/%y')
                log = log.sort_values('Close Date', ascending=False)
                st.dataframe(log.style.format({
                    'Premium Rcvd': lambda x: '${:.2f}'.format(x),
                    'Net P/L':      lambda x: '${:.2f}'.format(x),
                    'Capital Risk': lambda x: '${:,.0f}'.format(x),
                    'Capture %':    lambda v: '{:.1f}%'.format(v) if pd.notna(v) else '—',
                    'Ann Return %': lambda v: '{:.0f}%'.format(v) if pd.notna(v) else '—',
                }).map(color_pnl_cell, subset=['Net P/L']),
                width='stretch', hide_index=True)

# ── Tab 2: Wheel Campaigns ─────────────────────────────────────────────────
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
                    'Shares': int(c['total_shares']), 'Entry Basis': c['blended_basis'],
                    'Eff. Basis/sh': effb, 'Premiums Banked': c['premiums'],
                    'Dividends': c['dividends'], 'Exit Proceeds': c['exit_proceeds'],
                    'Realized P/L': rpnl, 'Days Active': dur.days,
                    'Started': c['start_date'].strftime('%d/%m/%y')})
        summary_df = pd.DataFrame(rows)
        def color_pnl(val):
            if not isinstance(val, float): return ''
            return 'color: #00cc96' if val > 0 else 'color: #ef553b' if val < 0 else ''
        st.dataframe(summary_df.style.format({
            'Entry Basis': lambda x: '${:,.2f}'.format(x),
            'Eff. Basis/sh': lambda x: '${:,.2f}'.format(x),
            'Premiums Banked': lambda x: '${:,.2f}'.format(x),
            'Dividends': lambda x: '${:,.2f}'.format(x),
            'Exit Proceeds': lambda x: '${:,.2f}'.format(x),
            'Realized P/L': lambda x: '${:,.2f}'.format(x)
        }).map(color_pnl, subset=['Realized P/L']), width='stretch', hide_index=True)
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
                    
                    # ── Option Roll Chains ──────────────────────────────────────
                    ticker_opts = df[(df['Ticker']==ticker) & 
                        df['Instrument Type'].str.contains('Option', na=False)].copy()
                    # Filter to campaign window only
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
                            'but the chain view may show fragments. The Strategy table in Derivatives Performance '
                            'may also approximate these — campaign P/L is always the source of truth.'
                        )
                        for ci, chain in enumerate(chains):
                            cp      = chain[0]['cp']
                            ch_pnl  = sum(l['total'] for l in chain)
                            last    = chain[-1]
                            is_open = 'to open' in str(last['sub_type']).lower()
                            n_rolls = sum(1 for l in chain if 'to close' in str(l['sub_type']).lower())
                            status_icon = '🟢' if is_open else '✅'
                            cp_icon = '📞' if cp == 'CALL' else '📉'
                            chain_label = '%s %s %s Chain %d — %d roll(s) | Net: $%.2f' % (
                                status_icon, cp_icon, cp.title(), ci+1, n_rolls, ch_pnl)
                            with st.expander(chain_label, expanded=is_open):
                                chain_rows = []
                                for leg in chain:
                                    sub = str(leg['sub_type']).lower()
                                    if 'to open' in sub:
                                        action = '↪️ Sell to Open'
                                    elif 'to close' in sub:
                                        action = '↩️ Buy to Close'
                                    elif 'expir' in sub:
                                        action = '⏹️ Expired'
                                    elif 'assign' in sub:
                                        action = '📋 Assigned'
                                    else:
                                        action = leg['sub_type']
                                    # DTE at open — only meaningful for STO legs
                                    dte_str = ''
                                    if 'to open' in sub:
                                        try:
                                            exp_dt = pd.to_datetime(leg['exp'], dayfirst=True)
                                            dte_str = '%dd' % max((exp_dt - leg['date'].replace(tzinfo=None)).days, 0)
                                        except: dte_str = ''
                                    chain_rows.append({
                                        'Action': action,
                                        'Date': leg['date'].strftime('%d/%m/%y'),
                                        'Strike': '%.1f%s' % (leg['strike'], cp[0]),
                                        'Exp': leg['exp'],
                                        'DTE': dte_str,
                                        'Cash': leg['total'],
                                    })
                                ch_df = pd.DataFrame(chain_rows)
                                # Add total row
                                ch_df = pd.concat([ch_df, pd.DataFrame([{
                                    'Action': '━━ Chain Total', 'Date': '',
                                    'Strike': '', 'Exp': '', 'DTE': '', 'Cash': ch_pnl
                                }])], ignore_index=True)
                                st.dataframe(ch_df.style.format({'Cash': lambda x: '${:.2f}'.format(x)})
                                    .map(lambda v: 'color: #00cc96' if isinstance(v,float) and v>0
                                        else ('color: #ef553b' if isinstance(v,float) and v<0 else ''),
                                        subset=['Cash']),
                                    width='stretch', hide_index=True)

                    # ── Share + Dividend events ──────────────────────────────
                    st.markdown('**📋 Share & Dividend Events**')
                    ev_df = pd.DataFrame(c['events'])
                    ev_share = ev_df[~ev_df['type'].str.lower().str.contains('to open|to close|expir|assign', na=False)]
                    if not ev_share.empty:
                        ev_share = ev_share.copy()
                        ev_share['date'] = pd.to_datetime(ev_share['date']).dt.strftime('%d/%m/%y %H:%M')
                        ev_share.columns = ['Date','Type','Detail','Cash']
                        st.dataframe(ev_share.style.format({'Cash': lambda x: '${:,.2f}'.format(x)})
                            .map(lambda v: 'color: #00cc96' if isinstance(v,float) and v>0
                                else ('color: #ef553b' if isinstance(v,float) and v<0 else ''),
                                subset=['Cash']),
                            width='stretch', hide_index=True)
                    else:
                        st.caption('No share/dividend events.')

# ── Tab 3: All Trades ──────────────────────────────────────────────────────
with tab3:
    st.subheader('🔍 Realized P/L — All Tickers')
    st.info(window_label)
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
            'Premiums Banked': tp, 'Dividends': tv,
            'Standalone Trades': po, 'Capital Deployed': td, 'Realized P/L': tr+po})
    for ticker in sorted(pure_options_tickers):
        # Recalculate pure P/L logic here too for display consistency
        mask = (df['Ticker']==ticker) & (df['Type'].isin(['Trade','Receive Deliver']))
        total_val = df.loc[mask,'Total'].sum()
        
        # Check for share holding to display Capital Deployed correctly in table
        t_df = df[df['Ticker'] == ticker]
        s_mask = t_df['Instrument Type'].str.contains('Equity', na=False) & ~t_df['Instrument Type'].str.contains('Option', na=False)
        net_shares = t_df[s_mask]['Net_Qty_Row'].sum()
        
        cap_dep = 0.0
        pnl = total_val
        
        if net_shares > 0.0001:
             eq_flow = t_df[(t_df['Instrument Type'].str.contains('Equity', na=False)) & (t_df['Type'].isin(['Trade','Receive Deliver']))]['Total'].sum()
             if eq_flow < 0:
                 cap_dep = abs(eq_flow)
                 pnl = total_val + cap_dep
        
        rows.append({'Ticker': ticker, 'Type': '📊 Standalone',
            'Campaigns': '—', 'Premiums Banked': pnl, 'Dividends': 0.0,
            'Standalone Trades': 0.0, 'Capital Deployed': cap_dep, 'Realized P/L': pnl})
    if rows:
        deep_df = pd.DataFrame(rows)
        total_row = {'Ticker': 'TOTAL', 'Type': '', 'Campaigns': '',
            'Premiums Banked': deep_df['Premiums Banked'].sum(),
            'Dividends': deep_df['Dividends'].sum(),
            'Standalone Trades': deep_df['Standalone Trades'].sum(),
            'Capital Deployed': deep_df['Capital Deployed'].sum(),
            'Realized P/L': deep_df['Realized P/L'].sum()}
        deep_df = pd.concat([deep_df, pd.DataFrame([total_row])], ignore_index=True)
        def color_pnl2(val):
            if not isinstance(val, (int, float)): return ''
            return 'color: #00cc96' if val > 0 else 'color: #ef553b' if val < 0 else ''
        st.dataframe(deep_df.style.format({
            'Premiums Banked': lambda x: '${:,.2f}'.format(x),
            'Dividends': lambda x: '${:,.2f}'.format(x),
            'Standalone Trades': lambda x: '${:,.2f}'.format(x),
            'Capital Deployed': lambda x: '${:,.2f}'.format(x),
            'Realized P/L': lambda x: '${:,.2f}'.format(x)
        }).map(color_pnl2, subset=['Realized P/L']), width='stretch', hide_index=True)

# ── Tab 4: Income & Fees ───────────────────────────────────────────────────
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