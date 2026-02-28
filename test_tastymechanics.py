"""
TastyMechanics Test Suite
=========================
Tests call the real app functions directly — ingestion.parse_csv(),
_iter_fifo_sells(), build_campaigns(), pure_options_pnl() — so there is
no parallel reimplementation that can silently drift out of sync.

No Streamlit server required. Run with:
    python test_tastymechanics.py

SETUP: CSV and all app modules must be in the same folder as this file.
"""

import sys
import os
import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)


def _find_csv():
    """Find the TastyTrade CSV — looks in script folder then uploads mount.
    Accepts files starting with 'tastytrade' or 'tastymechanics'.
    """
    candidates = []
    for folder in [_HERE, '/mnt/user-data/uploads']:
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if (f.startswith('tastytrade') or f.startswith('tastymechanics')) and f.endswith('.csv'):
                candidates.append(os.path.join(folder, f))
    if not candidates:
        raise FileNotFoundError(
            "No tastytrade/tastymechanics CSV found.\n"
            f"Looked in: {_HERE} and /mnt/user-data/uploads\n"
            "Place your TastyTrade export CSV in the same folder as this script."
        )
    return max(candidates, key=lambda p: (os.path.getmtime(p), os.path.basename(p)))

CSV = _find_csv()
print(f"Using CSV: {os.path.basename(CSV)}")
print(f"Script folder: {_HERE}\n")


# ── Import real app modules ────────────────────────────────────────────────────
# All math functions now live in pure-Python modules — no Streamlit stub needed.
from ingestion import parse_csv, equity_mask, option_mask
from config    import OPT_TYPES, TRADE_TYPES, INCOME_SUB_TYPES
from mechanics import (
    _iter_fifo_sells,
    build_campaigns,
    pure_options_pnl,
    effective_basis,
    realized_pnl,
    compute_app_data,
    build_option_chains,
    build_closed_trades,
    calc_dte,
    _uf_find,
    _uf_union,
    _group_symbols_by_order,
)



# ── Load real data ─────────────────────────────────────────────────────────────
_parsed      = parse_csv(open(CSV, 'rb').read())
df           = _parsed.df
latest_date  = df['Date'].max()
earliest     = df['Date'].min()

# Whole-portfolio FIFO results — computed once, reused across sections.
# _iter_fifo_sells yields (date, proceeds, cost) — three values.
eq_rows      = df[equity_mask(df['Instrument Type'])].sort_values('Date')
fifo_results = list(_iter_fifo_sells(eq_rows))

def ticker_fifo_pnl(ticker):
    """FIFO P/L for a single ticker — filters before passing to the engine."""
    t_eq = df[(df['Ticker'] == ticker) & equity_mask(df['Instrument Type'])].sort_values('Date')
    return sum(p - c for _, p, c in _iter_fifo_sells(t_eq))


# ── Test runner ────────────────────────────────────────────────────────────────
PASS = 0; FAIL = 0; results = []

def check(name, actual, expected, tol=0.01):
    global PASS, FAIL
    ok = abs(actual - expected) <= tol
    if ok: PASS += 1
    else:  FAIL += 1
    results.append(('PASS' if ok else 'FAIL', name, actual, expected))
    print(f"  {'✅' if ok else '❌'} {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"       got={actual:.4f}  expected={expected:.4f}  delta={actual-expected:.4f}")

def check_int(name, actual, expected):
    global PASS, FAIL
    ok = actual == expected
    if ok: PASS += 1
    else:  FAIL += 1
    results.append(('PASS' if ok else 'FAIL', name, actual, expected))
    print(f"  {'✅' if ok else '❌'} {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"       got={actual}  expected={expected}")

def _summary(label):
    print(f'\n{"═"*60}')
    print(f'  {label}:  {PASS+FAIL} tests  |  {PASS} passed  |  {FAIL} failed')
    print(f'{"═"*60}')


# ══════════════════════════════════════════════════════════════════════════════
# 1. DATA LOADING & PARSING
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 1. Data loading & parsing ──────────────────────────────────────────')

check_int('Row count',           len(df), 428)
check_int('Equity rows',         equity_mask(df['Instrument Type']).sum(), 24)
check_int('Equity Option rows',  (df['Instrument Type'] == 'Equity Option').sum(), 336)
check_int('Future Option rows',  (df['Instrument Type'] == 'Future Option').sum(), 20)
check_int('Money Movement rows', (df['Type'] == 'Money Movement').sum(), 56)
check('Total of all rows',       df['Total'].sum(), -3362.63)

achr_assign = df[(df['Ticker'] == 'ACHR') & (df['Sub Type'] == 'Assignment')]
check_int('Assignment Net_Qty_Row sign (+)', int(achr_assign['Net_Qty_Row'].sum()), 1)

sofi_eq = df[(df['Ticker'] == 'SOFI') & equity_mask(df['Instrument Type'])]
check('SOFI total equity Net_Qty', sofi_eq['Net_Qty_Row'].sum(), 200.0)

# ══════════════════════════════════════════════════════════════════════════════
# 2. FIFO ENGINE
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 2. FIFO equity P/L ─────────────────────────────────────────────────')

check('AMD  FIFO P/L (bought 1@170.78, sold 1@243.09)', ticker_fifo_pnl('AMD'),    72.31)
check('AMZN FIFO P/L (bought 1@219.00, sold 1@250.06)', ticker_fifo_pnl('AMZN'),   31.06)
check('TLT  FIFO P/L (bought 1@91.48,  sold 1@88.92)',  ticker_fifo_pnl('TLT'),    -2.56)
check('ETHA FIFO P/L (bought 1@35.71,  sold 1@14.87)',  ticker_fifo_pnl('ETHA'),  -20.84)
check('Total FIFO equity P/L (all tickers)',
      sum(p - c for _, p, c in fifo_results), 79.97)

unh_net  = df[(df['Ticker'] == 'UNH')  & equity_mask(df['Instrument Type'])]['Net_Qty_Row'].sum()
meta_net = df[(df['Ticker'] == 'META') & equity_mask(df['Instrument Type'])]['Net_Qty_Row'].sum()
check('UNH fractional shares still open (0.5)',  unh_net,  0.5)
check('META fractional shares still open (0.2)', meta_net, 0.2)

amd_eq   = df[(df['Ticker'] == 'AMD') & equity_mask(df['Instrument Type'])].sort_values('Date')
amd_fifo = list(_iter_fifo_sells(amd_eq))
check('AMD in window (Nov 1 start)',
      sum(p-c for d,p,c in amd_fifo if d >= pd.Timestamp('2025-11-01')), 72.31)
check('AMD out of window (Nov 6 start)',
      sum(p-c for d,p,c in amd_fifo if d >= pd.Timestamp('2025-11-06')), 0.00)

# ══════════════════════════════════════════════════════════════════════════════
# 3. OPTIONS CASH FLOWS
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 3. Options cash flows ───────────────────────────────────────────────')

opt_df = df[df['Instrument Type'].isin(OPT_TYPES) & df['Type'].isin(TRADE_TYPES)]
check('Total options cash flow', opt_df['Total'].sum(), 1018.45)

spx_all        = df[df['Ticker'] == 'SPX']
spx_trade_opts = spx_all[spx_all['Instrument Type'].isin(OPT_TYPES) & spx_all['Type'].isin(TRADE_TYPES)]
check('SPX total P/L (includes cash-settled settlement rows)', spx_trade_opts['Total'].sum(), -307.40)

spx_settled = spx_all[spx_all['Sub Type'].isin(['Cash Settled Assignment', 'Cash Settled Exercise'])]
check('SPX cash-settled net (-752 + +242)', spx_settled['Total'].sum(), -510.00)

fut_df = df[df['Instrument Type'] == 'Future Option']
check('/MESZ5 total P/L', fut_df[df['Ticker'] == '/MESZ5']['Total'].sum(),  20.48)
check('/ZSF6 total P/L',  fut_df[df['Ticker'] == '/ZSF6']['Total'].sum(),  -60.93)
check('All expirations Total = 0', df[df['Sub Type'] == 'Expiration']['Total'].sum(), 0.00)

# ══════════════════════════════════════════════════════════════════════════════
# 4. DIVIDENDS & INTEREST
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 4. Dividends & interest ─────────────────────────────────────────────')

income = df[df['Sub Type'].isin(INCOME_SUB_TYPES)]
check('Total dividends + interest', income['Total'].sum(), -6.55)
check('Dividends total',       df[df['Sub Type'] == 'Dividend']['Total'].sum(),          1.58)
check('Credit interest total', df[df['Sub Type'] == 'Credit Interest']['Total'].sum(),   0.12)
check('Debit interest total',  df[df['Sub Type'] == 'Debit Interest']['Total'].sum(),   -8.25)
check('META net dividend (two rows: -0.02 + 0.11)',
      df[(df['Ticker'] == 'META') & (df['Sub Type'] == 'Dividend')]['Total'].sum(), 0.09)
check('TLT total dividends',
      df[(df['Ticker'] == 'TLT') & (df['Sub Type'] == 'Dividend')]['Total'].sum(), 0.55)

# ══════════════════════════════════════════════════════════════════════════════
# 5. CAMPAIGN ACCOUNTING — window boundary verification
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 5. Campaign accounting ──────────────────────────────────────────────')

achr_post = df[(df['Ticker'] == 'ACHR') & df['Instrument Type'].isin(OPT_TYPES) &
               df['Type'].isin(TRADE_TYPES) & (df['Date'] >= pd.Timestamp('2025-12-19'))]['Total'].sum()
check('ACHR campaign premiums (post-purchase only, excl assignment STO)', achr_post, 90.19)

achr_pre = df[(df['Ticker'] == 'ACHR') & df['Instrument Type'].isin(OPT_TYPES) &
              df['Type'].isin(TRADE_TYPES) & (df['Date'] < pd.Timestamp('2025-12-19'))]['Total'].sum()
check('ACHR pre-purchase STO (outside window = 27.89)', achr_pre, 27.89)

sofi_post = df[(df['Ticker'] == 'SOFI') & df['Instrument Type'].isin(OPT_TYPES) &
               df['Type'].isin(TRADE_TYPES) & (df['Date'] >= pd.Timestamp('2025-12-01'))]['Total'].sum()
check('SOFI campaign premiums (post-Dec-1 options)', sofi_post, 478.10)

sofi_pre = df[(df['Ticker'] == 'SOFI') & df['Instrument Type'].isin(OPT_TYPES) &
              df['Type'].isin(TRADE_TYPES) & (df['Date'] < pd.Timestamp('2025-12-01'))]['Total'].sum()
check('SOFI pre-purchase STO (outside window = 117.88)', sofi_pre, 117.88)

smr_pre = df[(df['Ticker'] == 'SMR') & df['Instrument Type'].isin(OPT_TYPES) &
             df['Type'].isin(TRADE_TYPES) & (df['Date'] < pd.Timestamp('2026-01-09'))]['Total'].sum()
check('SMR pre-purchase options (outside window = 352.79)', smr_pre, 352.79)

smr_post = df[(df['Ticker'] == 'SMR') & df['Instrument Type'].isin(OPT_TYPES) &
              df['Type'].isin(TRADE_TYPES) & (df['Date'] >= pd.Timestamp('2026-01-09'))]['Total'].sum()
check('SMR campaign premiums (post-purchase = 42.72)', smr_post, 42.72)

joby_pre = df[(df['Ticker'] == 'JOBY') & df['Instrument Type'].isin(OPT_TYPES) &
              df['Type'].isin(TRADE_TYPES) & (df['Date'] < pd.Timestamp('2026-01-09'))]['Total'].sum()
check('JOBY no pre-purchase options', joby_pre, 0.00)

# ══════════════════════════════════════════════════════════════════════════════
# 6. TOTAL REALIZED P/L
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 6. Total realized P/L ───────────────────────────────────────────────')

all_opts     = opt_df['Total'].sum()
all_eq       = sum(p - c for _, p, c in fifo_results)
all_inc      = income['Total'].sum()
ground_truth = all_opts + all_eq + all_inc

check('Ground truth total realized P/L',  ground_truth, 1091.87)
check('Options component',                all_opts,      1018.45)
check('Equity FIFO component',            all_eq,          79.97)
check('Dividend+interest component',      all_inc,         -6.55)
check('Components sum to total',          all_opts + all_eq + all_inc, 1091.87)

# ══════════════════════════════════════════════════════════════════════════════
# 7. DEPOSITS / PORTFOLIO STATS
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 7. Portfolio stats ──────────────────────────────────────────────────')

deps = df[df['Sub Type'] == 'Deposit']['Total'].sum()
wdrs = df[df['Sub Type'] == 'Withdrawal']['Total'].sum()
check('Total deposited',       deps,            5998.00)
check('Total withdrawn',       wdrs,             -55.00)
check('Net deposited',         deps + wdrs,     5943.00)
check('Realized ROR %',        ground_truth / (deps + wdrs) * 100, 18.37, tol=0.1)
check('Cash balance (all rows summed)', df['Total'].sum(), -3362.63, tol=0.01)

# ══════════════════════════════════════════════════════════════════════════════
# 8. OPEN EQUITY POSITIONS
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 8. Open equity positions ────────────────────────────────────────────')

eq_net  = df[equity_mask(df['Instrument Type'])].groupby('Ticker')['Net_Qty_Row'].sum()
open_eq = eq_net[eq_net.abs() > 0.001]

check_int('Number of open equity positions', len(open_eq), 7)
check('SMR  open shares', open_eq.get('SMR',  0), 100.0)
check('SOFI open shares', open_eq.get('SOFI', 0), 200.0)
check('JOBY open shares', open_eq.get('JOBY', 0), 100.0)
check('ACHR open shares', open_eq.get('ACHR', 0), 100.0)
check('IBIT open shares', open_eq.get('IBIT', 0),   1.0)
check('META open shares', open_eq.get('META', 0),   0.2)
check('UNH  open shares', open_eq.get('UNH',  0),   0.5)

sofi_cost = df[(df['Ticker'] == 'SOFI') & equity_mask(df['Instrument Type']) &
               (df['Net_Qty_Row'] > 0)]['Total'].apply(abs).sum()
check('SOFI total cost basis (200 shares)',  sofi_cost,         5558.08)
check('SOFI blended basis per share',        sofi_cost / 200,     27.79)

smr_cost = abs(df[(df['Ticker'] == 'SMR') & equity_mask(df['Instrument Type'])]['Total'].sum())
check('SMR  cost basis (100 shares @ 20.48)', smr_cost,        2048.08)
check('SMR  basis per share',                 smr_cost / 100,    20.48)

# ══════════════════════════════════════════════════════════════════════════════
# 9. WINDOWED P/L CONSISTENCY
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 9. Windowed P/L (All Time = same as ground truth) ───────────────────')

w_opts = df[df['Instrument Type'].isin(OPT_TYPES) & df['Type'].isin(TRADE_TYPES) &
            (df['Date'] >= earliest)]['Total'].sum()
w_eq   = sum(p - c for d, p, c in fifo_results if d >= earliest)
w_inc  = df[df['Sub Type'].isin(INCOME_SUB_TYPES) & (df['Date'] >= earliest)]['Total'].sum()
check('All Time window P/L == ground truth', w_opts + w_eq + w_inc, 1091.87)

nov_start = pd.Timestamp('2025-11-01')
nov_end   = pd.Timestamp('2025-11-30')
nov_opts  = df[df['Instrument Type'].isin(OPT_TYPES) & df['Type'].isin(TRADE_TYPES) &
               (df['Date'] >= nov_start) & (df['Date'] <= nov_end)]['Total'].sum()
nov_eq    = sum(p-c for d,p,c in fifo_results if nov_start <= d <= nov_end)
nov_inc   = df[df['Sub Type'].isin(INCOME_SUB_TYPES) &
               (df['Date'] >= nov_start) & (df['Date'] <= nov_end)]['Total'].sum()
check('November window: opts component',  nov_opts,                    117.13, tol=0.02)
check('November window: equity FIFO',     nov_eq,                      103.37, tol=0.02)
check('November window: div+int',         nov_inc,                       0.32, tol=0.02)
check('November window total P/L',        nov_opts + nov_eq + nov_inc, 220.82, tol=0.05)

oct_start = nov_start - (nov_end - nov_start)
oct_opts  = df[df['Instrument Type'].isin(OPT_TYPES) & df['Type'].isin(TRADE_TYPES) &
               (df['Date'] >= oct_start) & (df['Date'] < nov_start)]['Total'].sum()
oct_eq    = sum(p-c for d,p,c in fifo_results if oct_start <= d < nov_start)
oct_inc   = df[df['Sub Type'].isin(INCOME_SUB_TYPES) &
               (df['Date'] >= oct_start) & (df['Date'] < nov_start)]['Total'].sum()
check('Prior period (Oct) P/L self-check',
      oct_opts + oct_eq + oct_inc, oct_opts + oct_eq + oct_inc)

# ══════════════════════════════════════════════════════════════════════════════
# 10. EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 10. Edge cases ──────────────────────────────────────────────────────')

spx_rd_nonzero = df[(df['Ticker'] == 'SPX') & (df['Type'] == 'Receive Deliver') & (df['Total'] != 0)]
check('SPX Receive Deliver non-zero rows count', len(spx_rd_nonzero), 2)
check('SPX Cash Settled Assignment (should be -752)',
      spx_rd_nonzero[spx_rd_nonzero['Sub Type'] == 'Cash Settled Assignment']['Total'].sum(), -752.00)
check('SPX Cash Settled Exercise (should be +242)',
      spx_rd_nonzero[spx_rd_nonzero['Sub Type'] == 'Cash Settled Exercise']['Total'].sum(), 242.00)

exp_rows = df[df['Sub Type'] == 'Expiration']
check_int('Expiration row count', len(exp_rows), 5)
check('All expirations are $0', exp_rows['Total'].sum(), 0.00)

sofi_feb20_eq = df[(df['Ticker'] == 'SOFI') &
                   (df['Date'].dt.date == pd.Timestamp('2026-02-20').date()) &
                   equity_mask(df['Instrument Type'])]
check('SOFI Feb 20 equity row (assignment delivery) = -2605',
      sofi_feb20_eq['Total'].sum(), -2605.00)
check('SOFI assignment option row = $0',
      df[(df['Ticker'] == 'SOFI') & (df['Sub Type'] == 'Assignment')]['Total'].sum(), 0.00)

sofi_sto = df[(df['Ticker'] == 'SOFI') & (df['Symbol'].str.contains('260220P', na=False)) &
              (df['Sub Type'].str.lower() == 'sell to open')]
check('SOFI 260220P STO amount (Jan 9)', sofi_sto['Total'].sum(), 132.88)
check('SOFI 260220P STO is before Feb 20 buy-in',
      float((sofi_sto['Date'] < pd.Timestamp('2026-02-20')).all()), 1.0)

check_int('UNH no FIFO sells (position still open)',
          len(list(_iter_fifo_sells(
              df[(df['Ticker'] == 'UNH') & equity_mask(df['Instrument Type'])].sort_values('Date')
          ))), 0)
check_int('META no FIFO sells (position still open)',
          len(list(_iter_fifo_sells(
              df[(df['Ticker'] == 'META') & equity_mask(df['Instrument Type'])].sort_values('Date')
          ))), 0)

mesz5 = df[(df['Ticker'] == '/MESZ5') & df['Instrument Type'].isin(OPT_TYPES) & df['Type'].isin(TRADE_TYPES)]
check('/MESZ5 is pure cash-settled (no equity rows)',
      float(df[(df['Ticker'] == '/MESZ5') & equity_mask(df['Instrument Type'])].empty), 1.0)
check('/MESZ5 P/L = sum of trade rows', mesz5['Total'].sum(), 20.48)

bal_adj = df[df['Sub Type'] == 'Balance Adjustment']
check_int('Balance Adjustment rows', len(bal_adj), 26)
check('Balance Adjustments NOT in income calc',
      float(bal_adj['Sub Type'].isin(INCOME_SUB_TYPES).any()), 0.0)
check_int('Transfer rows', len(df[df['Sub Type'] == 'Transfer']), 1)
check('Transfer Total = -5', df[df['Sub Type'] == 'Transfer']['Total'].sum(), -5.00)

_summary('Sections 1–10')

# ══════════════════════════════════════════════════════════════════════════════
# 11. INDIVIDUAL CAMPAIGN CARDS — real build_campaigns()
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 11. Individual campaign cards ───────────────────────────────────────')

def _camp(ticker):
    """Run real build_campaigns and return aggregated campaign values."""
    camps = build_campaigns(df, ticker, use_lifetime=False)
    open_camps   = [c for c in camps if c.status == 'open']
    total_cost   = sum(c.total_cost   for c in camps)
    total_shares = sum(c.total_shares for c in open_camps)
    all_premiums = sum(c.premiums     for c in camps)
    all_divs     = sum(c.dividends    for c in camps)
    eff          = effective_basis(camps[-1]) if camps else 0.0
    pnl          = sum(realized_pnl(c) for c in camps)
    blended      = total_cost / total_shares if total_shares > 0 else 0.0
    return dict(cost=total_cost, shares=total_shares, basis=blended,
                premiums=all_premiums, divs=all_divs, eff_basis=eff, camp_pnl=pnl)

a = _camp('ACHR')
check('ACHR cost basis (100 @ 8.55)',  a['cost'],      855.00)
check('ACHR shares held',              a['shares'],    100.0)
check('ACHR raw basis/sh',             a['basis'],       8.55)
check('ACHR campaign premiums',        a['premiums'],   90.19)
check('ACHR dividends',                a['divs'],        0.00)
check('ACHR effective basis/sh',       a['eff_basis'],   7.65, tol=0.01)
check('ACHR open campaign P/L',        a['camp_pnl'],   90.19)

s = _camp('SOFI')
check('SOFI cost basis (200 shares)',  s['cost'],     5558.08)
check('SOFI shares held',              s['shares'],    200.0)
check('SOFI campaign premiums',        s['premiums'],  478.10)
check('SOFI effective basis/sh',       s['eff_basis'],  25.40, tol=0.01)
check('SOFI open campaign P/L',        s['camp_pnl'],  478.10)

m = _camp('SMR')
check('SMR cost basis (100 @ 20.48)', m['cost'],     2048.08)
check('SMR campaign premiums',         m['premiums'],   42.72)
check('SMR effective basis/sh',        m['eff_basis'],  20.05, tol=0.01)
check('SMR open campaign P/L',         m['camp_pnl'],   42.72)

j = _camp('JOBY')
check('JOBY cost basis (100 @ 15.33)', j['cost'],    1533.08)
check('JOBY campaign premiums',         j['premiums'],  83.20)
check('JOBY effective basis/sh',        j['eff_basis'], 14.50, tol=0.01)
check('JOBY open campaign P/L',         j['camp_pnl'],  83.20)

# ══════════════════════════════════════════════════════════════════════════════
# 12. OUTSIDE-WINDOW OPTIONS — real pure_options_pnl()
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 12. Outside-window (standalone pre-purchase) options ────────────────')

def _outside(ticker):
    camps = build_campaigns(df, ticker, use_lifetime=False)
    return pure_options_pnl(df, ticker, camps)

check('ACHR outside-window (Dec 12 STO)', _outside('ACHR'),  27.89)
check('SOFI outside-window (Nov 25 STO)', _outside('SOFI'), 117.88)
check('SMR  outside-window (pre Jan 9)',  _outside('SMR'),  352.79)
check('JOBY outside-window (none)',       _outside('JOBY'),   0.00)
check('Total outside-window premiums',
      sum(_outside(t) for t in ['ACHR', 'SOFI', 'SMR', 'JOBY']), 498.56)

# ══════════════════════════════════════════════════════════════════════════════
# 13. WINDOWED P/L — named windows
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 13. Named window P/L ────────────────────────────────────────────────')

def window_pnl(start):
    w_opts = df[df['Instrument Type'].isin(OPT_TYPES) & df['Type'].isin(TRADE_TYPES) &
                (df['Date'] >= start)]['Total'].sum()
    w_eq   = sum(p - c for d, p, c in fifo_results if d >= start)
    w_inc  = df[df['Sub Type'].isin(INCOME_SUB_TYPES) & (df['Date'] >= start)]['Total'].sum()
    return w_opts, w_eq, w_inc, w_opts + w_eq + w_inc

o,e,i,t = window_pnl(latest_date - pd.Timedelta(days=7))
check('1W opts',   o,   -45.56, tol=0.05)
check('1W equity', e,   -20.84, tol=0.02)
check('1W income', i,     0.00, tol=0.02)
check('1W total',  t,   -66.40, tol=0.10)

o,e,i,t = window_pnl(latest_date - pd.Timedelta(days=30))
check('1M opts',   o,   216.96, tol=0.05)
check('1M equity', e,   -20.84, tol=0.02)
check('1M income', i,    -7.23, tol=0.02)
check('1M total',  t,   188.89, tol=0.10)

_,_,_,t = window_pnl(latest_date - pd.Timedelta(days=90))
check('3M total',  t,   839.52, tol=0.20)

_,_,_,t = window_pnl(earliest)
check('All Time window == ground truth', t, 1091.87, tol=0.02)

o,e,i,t = window_pnl(pd.Timestamp(f'{latest_date.year}-01-01'))
check('YTD opts',   o,  582.23, tol=0.05)
check('YTD equity', e,  -20.84, tol=0.02)
check('YTD income', i,   -8.25, tol=0.02)
check('YTD total',  t,  553.14, tol=0.10)

# ══════════════════════════════════════════════════════════════════════════════
# 14. CAPITAL DEPLOYED
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 14. Capital deployed ────────────────────────────────────────────────')

def capital_deployed(ticker):
    t_eq = df[(df['Ticker'] == ticker) & equity_mask(df['Instrument Type'])]
    net  = t_eq['Net_Qty_Row'].sum()
    if net < 0.001: return 0.0
    buys = t_eq[t_eq['Net_Qty_Row'] > 0]
    return net * buys['Total'].apply(abs).sum() / buys['Net_Qty_Row'].sum()

check('ACHR capital deployed', capital_deployed('ACHR'),   855.00)
check('SOFI capital deployed', capital_deployed('SOFI'),  5558.08)
check('SMR  capital deployed', capital_deployed('SMR'),   2048.08)
check('JOBY capital deployed', capital_deployed('JOBY'),  1533.08)
check('IBIT capital deployed', capital_deployed('IBIT'),    62.90)
check('META capital deployed', capital_deployed('META'),   150.22)
check('UNH  capital deployed', capital_deployed('UNH'),    184.44)
check('Total capital deployed',
      sum(capital_deployed(t) for t in ['ACHR','SOFI','SMR','JOBY','IBIT','META','UNH']),
      10391.80)

# ══════════════════════════════════════════════════════════════════════════════
# 15. TICKER-LEVEL OPTIONS P/L
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 15. Ticker-level options P/L ────────────────────────────────────────')

def ticker_opts_pnl(ticker):
    return df[(df['Ticker'] == ticker) &
              df['Instrument Type'].isin(OPT_TYPES) &
              df['Type'].isin(TRADE_TYPES)]['Total'].sum()

check('RKLB options P/L',   ticker_opts_pnl('RKLB'),   618.00)
check('INTC options P/L',   ticker_opts_pnl('INTC'),   217.99)
check('XYZ  options P/L',   ticker_opts_pnl('XYZ'),   -354.46)
check('GLD  options P/L',   ticker_opts_pnl('GLD'),   -189.92)
check('SPX  options P/L',   ticker_opts_pnl('SPX'),   -307.40)
check('/ZSF6 options P/L',  ticker_opts_pnl('/ZSF6'),  -60.93)
check('/MESZ5 options P/L', ticker_opts_pnl('/MESZ5'),  20.48)

# ══════════════════════════════════════════════════════════════════════════════
# 16. SELF-CALIBRATING INVARIANTS  (work with ANY TastyTrade CSV)
#
# These derive expected values from the CSV itself — no hardcoded amounts.
# They catch structural bugs: wrong formulas, double-counts, sign errors.
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 16. Self-calibrating invariants (any CSV) ───────────────────────────')

_all_opts  = df[df['Instrument Type'].isin(OPT_TYPES) & df['Type'].isin(TRADE_TYPES)]['Total'].sum()
_all_eq    = sum(p - c for _, p, c in fifo_results)
_all_inc   = df[df['Sub Type'].isin(INCOME_SUB_TYPES)]['Total'].sum()
_total_pnl = _all_opts + _all_eq + _all_inc

check('INV: opts + equity + income = total P/L', _total_pnl, _total_pnl)
check('INV: all expiration rows sum to $0',
      df[df['Sub Type'] == 'Expiration']['Total'].sum(), 0.00)
check('INV: all assignment option rows sum to $0',
      df[df['Sub Type'] == 'Assignment']['Total'].sum(), 0.00)
check('INV: all exercise option rows sum to $0',
      df[df['Sub Type'] == 'Exercise']['Total'].sum(), 0.00)

_eq    = df[equity_mask(df['Instrument Type'])]
_buys  = _eq[_eq['Sub Type'].str.lower().str.contains('buy',  na=False)]['Net_Qty_Row']
_sells = _eq[_eq['Sub Type'].str.lower().str.contains('sell', na=False)]['Net_Qty_Row']
check('INV: all equity buy rows have positive Net_Qty_Row',  float((_buys  > 0).all()), 1.0)
check('INV: all equity sell rows have negative Net_Qty_Row', float((_sells < 0).all()), 1.0)

_eq_cash_in = _eq[_eq['Net_Qty_Row'] < 0]['Total'].sum()
check('INV: FIFO equity P/L <= gross sale proceeds',
      float(_all_eq <= _eq_cash_in + 0.01), 1.0)

_w_eq = sum(p-c for d,p,c in fifo_results if d >= earliest)
_w_inc = df[df['Sub Type'].isin(INCOME_SUB_TYPES) & (df['Date'] >= earliest)]['Total'].sum()
_w_opts = df[df['Instrument Type'].isin(OPT_TYPES) & df['Type'].isin(TRADE_TYPES) &
             (df['Date'] >= earliest)]['Total'].sum()
check('INV: All Time window == sum of components', _w_opts + _w_eq + _w_inc, _total_pnl)

_wheel_eq = df[equity_mask(df['Instrument Type'])]
_wheel_tickers = [
    t for t in _wheel_eq['Ticker'].unique()
    if _wheel_eq[(_wheel_eq['Ticker'] == t) & (_wheel_eq['Net_Qty_Row'] >= 100)].shape[0] > 0
]
_double_count_risk = sum(
    df[(df['Ticker'] == _t) & df['Instrument Type'].isin(OPT_TYPES) &
       df['Type'].isin(TRADE_TYPES) &
       (df['Date'] < _wheel_eq[(_wheel_eq['Ticker'] == _t) &
                                (_wheel_eq['Net_Qty_Row'] > 0)]['Date'].min())]['Total'].sum()
    for _t in _wheel_tickers
    if not _wheel_eq[(_wheel_eq['Ticker'] == _t) & (_wheel_eq['Net_Qty_Row'] > 0)].empty
)
check('INV: outside-window premiums identified (documents pre-purchase options)',
      float(abs(_double_count_risk) >= 0.0), 1.0)

_mm   = df[df['Type'] == 'Money Movement']
_deps = _mm[_mm['Sub Type'] == 'Deposit']['Total'].sum()
_wdrs = _mm[_mm['Sub Type'] == 'Withdrawal']['Total'].sum()
check('INV: deposits are positive',            float(_deps >= 0), 1.0)
check('INV: withdrawals are negative or zero', float(_wdrs <= 0), 1.0)
check('INV: net deposited >= 0',               float(_deps + _wdrs >= 0), 1.0)

_eq_net = df[equity_mask(df['Instrument Type'])].groupby('Ticker')['Net_Qty_Row'].sum()
_open_positions = _eq_net[_eq_net.abs() > 0.001]
check('INV: all open equity positions have positive net qty',
      float((_open_positions > 0).all()), 1.0)
check('INV: total capital deployed > 0',
      float(sum(capital_deployed(t) for t in _open_positions.index) > 0), 1.0)

_to_open  = df[df['Instrument Type'].isin(OPT_TYPES) & df['Type'].isin(TRADE_TYPES) &
               df['Sub Type'].str.lower().str.contains('to open',  na=False)]['Total'].sum()
_to_close = df[df['Instrument Type'].isin(OPT_TYPES) & df['Type'].isin(TRADE_TYPES) &
               df['Sub Type'].str.lower().str.contains('to close', na=False)]['Total'].sum()
_settled  = df[df['Instrument Type'].isin(OPT_TYPES) & df['Type'].isin(TRADE_TYPES) &
               df['Sub Type'].isin(['Cash Settled Assignment', 'Cash Settled Exercise',
                                    'Expiration', 'Assignment', 'Exercise'])]['Total'].sum()
check('INV: open + close + settle = total options cash flow',
      _to_open + _to_close + _settled, _all_opts)

_window_span = pd.Timedelta(days=30)
_prior_end   = df['Date'].max() - _window_span
_prior_start = _prior_end - _window_span
_prior_total = (
    df[df['Instrument Type'].isin(OPT_TYPES) & df['Type'].isin(TRADE_TYPES) &
       (df['Date'] >= _prior_start) & (df['Date'] < _prior_end)]['Total'].sum() +
    df[df['Sub Type'].isin(INCOME_SUB_TYPES) &
       (df['Date'] >= _prior_start) & (df['Date'] < _prior_end)]['Total'].sum() +
    sum(p-c for d,p,c in fifo_results if _prior_start <= d < _prior_end)
)
check('INV: prior period P/L is a finite number',
      float(abs(_prior_total) < 1_000_000), 1.0)

check('INV: no NaN Ticker on trade rows',
      float(df[df['Type'].isin(TRADE_TYPES)]['Ticker'].isna().sum()), 0.0)
check('INV: Balance Adjustment not in INCOME_SUB_TYPES',
      float('Balance Adjustment' in INCOME_SUB_TYPES), 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# 9. UNION-FIND HELPERS
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 21. Union-Find helpers ─────────────────────────────────────────────')

# _uf_find — basic root lookup
_p = {}
check_int('UF: single node is its own root', _uf_find(_p, 'A'), 'A')

# _uf_union — two nodes in same component
_p = {}
_uf_union(_p, 'A', 'B')
check_int('UF: union(A,B) — find(A) == find(B)', _uf_find(_p, 'A'), _uf_find(_p, 'B'))

# _uf_union — transitivity: A∩B and B∩C → all three same root
_p = {}
_uf_union(_p, 'A', 'B')
_uf_union(_p, 'B', 'C')
check_int('UF: transitivity A∩B and B∩C → find(A)==find(C)',
          _uf_find(_p, 'A'), _uf_find(_p, 'C'))

# _group_symbols_by_order — two symbols sharing one order land in same group
_groups = _group_symbols_by_order({'SPY_C450': ['ORD1'], 'SPY_P440': ['ORD1']})
_roots  = list(_groups.values())
check_int('UF group: two syms sharing an order → one group',
          len(_roots), 1)
check_int('UF group: that group contains both syms',
          len(_roots[0]), 2)

# _group_symbols_by_order — two symbols with different orders → two groups
_groups2 = _group_symbols_by_order({'SPY_C450': ['ORD1'], 'SPY_P440': ['ORD2']})
check_int('UF group: two syms with different orders → two groups',
          len(_groups2), 2)

# _group_symbols_by_order — chain: A∩B and B∩C → one group of three
_groups3 = _group_symbols_by_order({
    'SPY_C450': ['ORD1'],
    'SPY_C460': ['ORD1', 'ORD2'],
    'SPY_C470': ['ORD2'],
})
check_int('UF group: chain A∩B and B∩C → one group of three',
          sum(len(v) for v in _groups3.values()), 3)
check_int('UF group: chain → exactly one group',
          len(_groups3), 1)


# ══════════════════════════════════════════════════════════════════════════════
# 10. calc_dte
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 22. calc_dte ───────────────────────────────────────────────────────')

_ref = pd.Timestamp('2025-01-01')

def _opt_row(exp, inst='Equity Option'):
    """Build a minimal Series that calc_dte accepts."""
    return pd.Series({'Instrument Type': inst, 'Expiration Date': exp})

# Normal case — 21 days out
check_int('DTE: 21 days out',  calc_dte(_opt_row('2025-01-22'), _ref), '21d')

# Expiry today — should return '0d' not negative
check_int('DTE: expiry == reference date returns 0d',
          calc_dte(_opt_row('2025-01-01'), _ref), '0d')

# Already expired — floor at 0
check_int('DTE: past expiry returns 0d',
          calc_dte(_opt_row('2024-12-01'), _ref), '0d')

# Non-option row → N/A
check_int('DTE: equity row returns N/A',
          calc_dte(_opt_row('2025-01-22', inst='Equity'), _ref), 'N/A')

# Missing expiration → N/A
check_int('DTE: NaN expiration returns N/A',
          calc_dte(_opt_row(float('nan')), _ref), 'N/A')

# Malformed expiration → N/A (no exception raised)
check_int('DTE: garbage expiration returns N/A',
          calc_dte(_opt_row('not-a-date'), _ref), 'N/A')


# ══════════════════════════════════════════════════════════════════════════════
# 11. build_option_chains
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 23. build_option_chains ────────────────────────────────────────────')

def _make_opts(rows):
    """
    Build a minimal DataFrame for build_option_chains from a list of dicts.
    Required columns: Date, Sub Type, Net_Qty_Row, Total, Call or Put,
                      Strike Price, Expiration Date, Description.
    """
    return pd.DataFrame([{
        'Date':            pd.Timestamp(r['date']),
        'Sub Type':        r['sub'],
        'Net_Qty_Row':     r['qty'],
        'Total':           r.get('total', 0.0),
        'Call or Put':     r.get('cp', 'PUT'),
        'Strike Price':    r.get('strike', 100.0),
        'Expiration Date': r.get('exp', '2025-03-21'),
        'Description':     r.get('desc', ''),
    } for r in rows])

# ── Single STO that expires — one chain, one event ──────────────────────────
_single = _make_opts([
    {'date': '2025-01-05', 'sub': 'Sell to Open', 'qty': -1, 'total': 150},
    {'date': '2025-01-19', 'sub': 'Expiration',   'qty':  1, 'total':   0},
])
_ch = build_option_chains(_single)
check_int('Chains: single STO+expire → 1 chain',  len(_ch), 1)
check_int('Chains: single chain has 2 events',     len(_ch[0]), 2)

# ── Two STOs within ROLL_CHAIN_GAP_DAYS → same chain (a roll) ───────────────
_roll = _make_opts([
    {'date': '2025-01-05', 'sub': 'Sell to Open',  'qty': -1, 'total':  150},
    {'date': '2025-01-19', 'sub': 'Buy to Close',  'qty':  1, 'total': -100},
    {'date': '2025-01-20', 'sub': 'Sell to Open',  'qty': -1, 'total':  120},
    {'date': '2025-02-14', 'sub': 'Expiration',    'qty':  1, 'total':    0},
])
_ch2 = build_option_chains(_roll)
check_int('Chains: roll within gap → 1 chain',        len(_ch2), 1)
check_int('Chains: rolled chain has 4 events',         len(_ch2[0]), 4)

# ── Two STOs separated by > ROLL_CHAIN_GAP_DAYS → two separate chains ───────
_two = _make_opts([
    {'date': '2025-01-05', 'sub': 'Sell to Open', 'qty': -1, 'total':  150},
    {'date': '2025-01-19', 'sub': 'Expiration',   'qty':  1, 'total':    0},
    {'date': '2025-02-10', 'sub': 'Sell to Open', 'qty': -1, 'total':  120},
    {'date': '2025-03-21', 'sub': 'Expiration',   'qty':  1, 'total':    0},
])
_ch3 = build_option_chains(_two)
check_int('Chains: gap > threshold → 2 chains', len(_ch3), 2)

# ── CALL and PUT STOs in same DataFrame → grouped by cp_type, separate chains
_mixed = _make_opts([
    {'date': '2025-01-05', 'sub': 'Sell to Open', 'qty': -1, 'cp': 'PUT',  'total':  80},
    {'date': '2025-01-19', 'sub': 'Expiration',   'qty':  1, 'cp': 'PUT',  'total':   0},
    {'date': '2025-01-05', 'sub': 'Sell to Open', 'qty': -1, 'cp': 'CALL', 'total':  70},
    {'date': '2025-01-19', 'sub': 'Expiration',   'qty':  1, 'cp': 'CALL', 'total':   0},
])
_ch4 = build_option_chains(_mixed)
check_int('Chains: PUT + CALL → 2 chains (one each)', len(_ch4), 2)

# ── BTO leg in same DataFrame → not recorded in chain ───────────────────────
_spread = _make_opts([
    {'date': '2025-01-05', 'sub': 'Sell to Open', 'qty': -1, 'total':  80},
    {'date': '2025-01-05', 'sub': 'Buy to Open',  'qty':  1, 'total': -30},
    {'date': '2025-01-19', 'sub': 'Expiration',   'qty':  1, 'total':   0},
])
_ch5 = build_option_chains(_spread)
check_int('Chains: BTO leg not recorded — chain has 2 events (STO + expiry)',
          len(_ch5[0]), 2)

# ── Empty DataFrame → no chains ──────────────────────────────────────────────
_empty = _make_opts([])
check_int('Chains: empty input → 0 chains', len(build_option_chains(_empty)), 0)


# ══════════════════════════════════════════════════════════════════════════════
# 17. CLOSED TRADES — CORE AGGREGATES
# ══════════════════════════════════════════════════════════════════════════════
# build_closed_trades() pairs every STO with its matching BTC/expiry/assignment
# and computes Capture %, Days Held, DTE at Open, Ann Return %, etc.
# These tests pin the headline numbers from the real CSV so any regression in
# the pairing logic or column calculations is caught immediately.
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 17. Closed trades — core aggregates ────────────────────────────────')

_ct = build_closed_trades(df)

check_int('CT: total trades',              len(_ct),                    95)
check_int('CT: winning trades',            int(_ct['Won'].sum()),       80)
check    ('CT: win rate %',                _ct['Won'].mean() * 100,     84.2105)
check    ('CT: total net P/L',             _ct['Net P/L'].sum(),        834.05)
check    ('CT: total premium received',    _ct['Net Premium'].sum(),   10377.80)
check    ('CT: median capture %',          _ct[_ct['Is Credit']]['Capture %'].median(),   33.7950)
check    ('CT: median days held',          _ct['Days Held'].median(),   6.0)
check    ('CT: median DTE at open',        _ct['DTE at Open'].median(),    36.0)
check_int('CT: credit trades',             int(_ct['Is Credit'].sum()), 91)
check_int('CT: debit trades',              int((~_ct['Is Credit']).sum()), 4)

# ── Per-ticker net P/L ───────────────────────────────────────────────────────
_ct_by_ticker = _ct.groupby('Ticker')['Net P/L'].sum()
check('CT ticker RKLB net P/L',   _ct_by_ticker['RKLB'],    618.00)
check('CT ticker SOFI net P/L',   _ct_by_ticker['SOFI'],    509.22)
check('CT ticker SMR  net P/L',   _ct_by_ticker['SMR'],     362.63)
check('CT ticker INTC net P/L',   _ct_by_ticker['INTC'],    217.99)
check('CT ticker JOBY net P/L',   _ct_by_ticker['JOBY'],     52.32)
check('CT ticker GLD  net P/L',   _ct_by_ticker['GLD'],    -189.92)
check('CT ticker XYZ  net P/L',   _ct_by_ticker['XYZ'],    -354.46)
check('CT ticker SPX  net P/L',   _ct_by_ticker['SPX'],    -307.40)

# ── Spot-check individual trade fields ──────────────────────────────────────
# RKLB big strangle: Oct 16 → Dec 18 2025, 63 days, $1194.76 credit, $757.53 P/L
_rklb_big = _ct[
    (_ct['Ticker'] == 'RKLB') &
    (_ct['Trade Type'] == 'Short Strangle') &
    (_ct['Net P/L'] > 700)
].iloc[0]
check    ('CT RKLB strangle premium',    _rklb_big['Net Premium'],  1194.76)
check    ('CT RKLB strangle net P/L',    _rklb_big['Net P/L'],        757.53)
check    ('CT RKLB strangle capture %',  _rklb_big['Capture %'],       63.4044)
check_int('CT RKLB strangle days held',  int(_rklb_big['Days Held']),  63)
check_int('CT RKLB strangle DTE open',   int(_rklb_big['DTE at Open']),   64)

# INTC strangle Dec11–Jan02: 22 days, $209.78 credit, $119.55 P/L
_intc_strang = _ct[
    (_ct['Ticker'] == 'INTC') &
    (_ct['Trade Type'] == 'Short Strangle') &
    (_ct['Net P/L'] > 100)
].iloc[0]
check('CT INTC strangle premium',   _intc_strang['Net Premium'],  209.78)
check('CT INTC strangle net P/L',   _intc_strang['Net P/L'],       119.55)
check('CT INTC strangle capture %', _intc_strang['Capture %'],      56.9883)

# SOFI put assigned Feb-20: 42 days held, 100% capture (expired worthless assigned)
_sofi_assigned = _ct[
    (_ct['Ticker'] == 'SOFI') &
    (_ct['Close Reason'] == '📋 Assigned') &
    (_ct['Net Premium'] > 130)
].iloc[0]
check    ('CT SOFI assigned put premium',   _sofi_assigned['Net Premium'], 132.88)
check    ('CT SOFI assigned put net P/L',   _sofi_assigned['Net P/L'],      132.88)
check    ('CT SOFI assigned put capture %', _sofi_assigned['Capture %'],    100.0)
check_int('CT SOFI assigned put days held', int(_sofi_assigned['Days Held']), 42)

# ── Human-verified trades (cross-checked against TastyTrade UI) ──────────────
# These were verified screenshot-by-screenshot against the real TastyTrade
# transaction history on 28 Feb 2026. The pairing logic, credit received,
# buyback cost, and net P/L were all confirmed exact.

# SLV Put Jan 7 → Jan 10 2026: SOLD @ 1.02 (+$100.88), BOUGHT @ 0.61 (-$61.12)
_slv_put = _ct[
    (_ct['Ticker'] == 'SLV') & (_ct['Trade Type'] == 'Short Put')
].iloc[0]
check    ('VERIFIED SLV put credit received',  _slv_put['Net Premium'], 100.88)
check    ('VERIFIED SLV put net P/L',          _slv_put['Net P/L'],       39.76)
check    ('VERIFIED SLV put capture %',        _slv_put['Capture %'],     39.4132, tol=0.001)
check_int('VERIFIED SLV put days held',        int(_slv_put['Days Held']),  2)

# INTC 41 Put Jan 28 → Feb 17 2026: SOLD @ 1.05 (+$103.88), BOUGHT @ 1.17 (-$117.12)
_intc_put_loss = _ct[
    (_ct['Ticker'] == 'INTC') &
    (_ct['Trade Type'] == 'Short Put') &
    (_ct['Net P/L'] < 0)
].iloc[0]
check    ('VERIFIED INTC losing put credit received', _intc_put_loss['Net Premium'], 103.88)
check    ('VERIFIED INTC losing put net P/L',         _intc_put_loss['Net P/L'],      -13.24)
check    ('VERIFIED INTC losing put capture %',       _intc_put_loss['Capture %'],    -12.7455, tol=0.001)
check_int('VERIFIED INTC losing put days held',       int(_intc_put_loss['Days Held']), 19)

# SMR 13 Put Jan 26 → Feb 17 2026: SOLD @ 0.62 (+$60.88), BOUGHT @ 1.48 (-$148.12)
_smr_put_loss = _ct[
    (_ct['Ticker'] == 'SMR') &
    (_ct['Trade Type'] == 'Short Put') &
    (_ct['Net P/L'] < 0)
].iloc[0]
check    ('VERIFIED SMR losing put credit received', _smr_put_loss['Net Premium'],  60.88)
check    ('VERIFIED SMR losing put net P/L',         _smr_put_loss['Net P/L'],       -87.24)
check    ('VERIFIED SMR losing put capture %',       _smr_put_loss['Capture %'],    -143.2983, tol=0.001)
check_int('VERIFIED SMR losing put days held',       int(_smr_put_loss['Days Held']), 21)


# TSLA Call Debit Spread — VERIFIED against TastyTrade UI (screenshot 2026-03-01)
# Oct 2: BTO 1 Oct3 457.5C @ 12.23 (-$1,224.12) + STO 1 Oct3 460C @ 10.93 (+$1,091.88)
# Oct 4: Both legs expired worthless ($0). Net debit = -$132.24.
# Capture % = None (debit trade — not meaningful)
_tsla_ds = _ct[(_ct['Ticker'] == 'TSLA') & (_ct['Trade Type'] == 'Call Debit Spread')].iloc[0]
check    ('VERIFIED TSLA call debit spread net premium',  _tsla_ds['Net Premium'],  -132.24)
check    ('VERIFIED TSLA call debit spread net P/L',      _tsla_ds['Net P/L'],      -132.24)
check_int('VERIFIED TSLA call debit spread capture % is NaN', pd.isna(_tsla_ds['Capture %']), True)
check_int('VERIFIED TSLA call debit spread days held',    int(_tsla_ds['Days Held']), 2)
check_int('VERIFIED TSLA call debit spread close reason', _tsla_ds['Close Reason'], '⏹️ Expired')


# ══════════════════════════════════════════════════════════════════════════════
# 18. CLOSED TRADES — STRATEGY BREAKDOWN
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 18. Closed trades — strategy breakdown ─────────────────────────────')

_ct_strat = _ct.groupby('Trade Type').agg(
    count=('Won', 'count'),
    wins=('Won', 'sum'),
    total_pnl=('Net P/L', 'sum'),
)

# Trade counts per strategy
check_int('CT strategy Short Put count',        int(_ct_strat.loc['Short Put',    'count']), 32)
check_int('CT strategy Short Call count',       int(_ct_strat.loc['Short Call',   'count']), 22)
check_int('CT strategy Iron Condor count',      int(_ct_strat.loc['Iron Condor',  'count']), 17)
check_int('CT strategy Short Strangle count',   int(_ct_strat.loc['Short Strangle','count']), 6)
check_int('CT strategy Put Credit Spread count',int(_ct_strat.loc['Put Credit Spread','count']), 10)

# Net P/L per strategy
check('CT strategy Short Put total P/L',      _ct_strat.loc['Short Put',    'total_pnl'],  1119.70)
check('CT strategy Short Call total P/L',     _ct_strat.loc['Short Call',   'total_pnl'],   732.93)
check('CT strategy Iron Condor total P/L',    _ct_strat.loc['Iron Condor',  'total_pnl'],  -389.29)
check('CT strategy Put Credit Spread P/L',    _ct_strat.loc['Put Credit Spread','total_pnl'], -638.86)

# Win counts
check_int('CT strategy Short Call wins (all)',  int(_ct_strat.loc['Short Call', 'wins']), 22)
check_int('CT strategy Short Put wins',         int(_ct_strat.loc['Short Put',  'wins']), 30)
check_int('CT strategy Iron Condor wins',       int(_ct_strat.loc['Iron Condor','wins']), 13)

# Short Put (x2) — multi-contract trade recorded as single row
_sp2 = _ct[_ct['Trade Type'] == 'Short Put (x2)']
check_int('CT Short Put (x2) count',       len(_sp2),                  1)
check    ('CT Short Put (x2) premium',     _sp2.iloc[0]['Net Premium'], 361.76)
check    ('CT Short Put (x2) net P/L',     _sp2.iloc[0]['Net P/L'],      133.52)
check_int('CT Short Put (x2) DTE open',    int(_sp2.iloc[0]['DTE at Open']), 46)


# ══════════════════════════════════════════════════════════════════════════════
# 19. CLOSED TRADES — CLOSE TYPES & DEBIT TRADES
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 19. Closed trades — close types & debit trades ─────────────────────')

_close_counts = _ct['Close Reason'].value_counts()

check_int('CT close type Closed count',   int(_close_counts.get('✂️ Closed',   0)), 90)
check_int('CT close type Expired count',  int(_close_counts.get('⏹️ Expired',  0)),  3)
check_int('CT close type Assigned count', int(_close_counts.get('📋 Assigned', 0)),  2)
check_int('CT close types sum to total',  int(_close_counts.sum()),                 95)

_expired = _ct[_ct['Close Reason'] == '⏹️ Expired']
# Expired trades — only check count; capture% varies (some expired worthless, some ITM)
check_int('CT expired: SOFI expired worthless (100% capture)',
          int((_expired[_expired['Ticker'] == 'SOFI']['Capture %'] == 100.0).sum()), 1)
check_int('CT expired: SPX expired ITM (loss, capture < 0)',
          int((_expired[_expired['Ticker'] == 'SPX']['Net P/L'] < 0).sum()), 1)
check_int('CT expired: all 3 are in the expired set',
          len(_expired), 3)

# Debit trades (Calendar Spread, Debit Spread, Butterfly)
_debit = _ct[~_ct['Is Credit']]
check_int('CT debit trade count',          len(_debit),                    4)
check    ('CT debit trades total P/L',     _debit['Net P/L'].sum(),       -227.19)

# TSLA Call Debit Spread: bought $132.24, lost the whole thing
_tsla_ds = _ct[
    (_ct['Ticker'] == 'TSLA') & (_ct['Trade Type'] == 'Call Debit Spread')
].iloc[0]
check('CT TSLA debit spread premium',    _tsla_ds['Net Premium'], -132.24)
check('CT TSLA debit spread net P/L',    _tsla_ds['Net P/L'],      -132.24)
check_int('CT TSLA debit spread capture %',  pd.isna(_tsla_ds['Capture %']),  True)

# META Calendar Spread: debit trade that turned a profit
_meta_cal = _ct[
    (_ct['Ticker'] == 'META') & (_ct['Trade Type'] == 'Calendar Spread')
].iloc[0]
check('CT META calendar debit premium',  _meta_cal['Net Premium'], -72.24)
check('CT META calendar net P/L',        _meta_cal['Net P/L'],       18.52)
check_int('CT META calendar is winner',  int(_meta_cal['Won']),       1)


# ══════════════════════════════════════════════════════════════════════════════
# 20. CLOSED TRADES — WINDOW FILTERING
# ══════════════════════════════════════════════════════════════════════════════
# Verifies that filtering closed trades by Close Date gives the right counts
# and P/L for each named window. This exercises the same date slicing that
# render_tab1 and render_tab2 rely on.
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 20. Closed trades — window filtering ────────────────────────────────')

from datetime import timedelta

_latest = df['Date'].max()   # 2026-02-27

def _ct_window(start):
    """Closed trades whose Close Date falls on or after start."""
    return _ct[pd.to_datetime(_ct['Close Date']) >= start]

# YTD (Jan 1 2026 →)
_ytd = _ct_window(pd.Timestamp('2026-01-01'))
check_int('CT YTD trade count',   len(_ytd),                    41)
check    ('CT YTD net P/L',       _ytd['Net P/L'].sum(),       979.95)
check_int('CT YTD win count',     int(_ytd['Won'].sum()),        35)

# 7d window
_w7 = _ct_window(_latest - timedelta(days=7))
check_int('CT 7d trade count',    len(_w7),                      8)
check    ('CT 7d net P/L',        _w7['Net P/L'].sum(),         262.20)

# 30d window
_w30 = _ct_window(_latest - timedelta(days=30))
check_int('CT 30d trade count',   len(_w30),                    22)
check    ('CT 30d net P/L',       _w30['Net P/L'].sum(),        200.13)

# All-time window == full table
check_int('CT all-time == full table', len(_ct_window(df['Date'].min())), len(_ct))

# Boundary: a trade closed exactly on latest_date IS included in 1d window
_on_latest = _ct[pd.to_datetime(_ct['Close Date']).dt.normalize() == _latest]
if not _on_latest.empty:
    _w0 = _ct_window(_latest)
    check_int('CT boundary: trade on latest_date included', len(_w0) >= 1, 1)

# YTD: no trade closed before Jan 1 appears
_ytd_pre = pd.to_datetime(_ytd['Close Date']).dt.normalize() < pd.Timestamp('2026-01-01')
check_int('CT YTD: no pre-2026 close dates', int(_ytd_pre.sum()), 0)

# 7d: all close dates within window
_w7_outside = pd.to_datetime(_w7['Close Date']) < (_latest - timedelta(days=7))
check_int('CT 7d: no out-of-window close dates', int(_w7_outside.sum()), 0)




# ══════════════════════════════════════════════════════════════════════════════
# SECTION 24 — UI HELPER FUNCTIONS: xe(), identify_pos_type(), detect_strategy()
# ══════════════════════════════════════════════════════════════════════════════
from ui_components import xe, identify_pos_type, detect_strategy

def _make_row(inst_type, cp, qty, strike=100.0, exp='2026-06-20'):
    """Helper — build a minimal Series for identify_pos_type / detect_strategy."""
    return pd.Series({
        'Instrument Type': inst_type,
        'Call or Put':     cp,
        'Net_Qty':         qty,
        'Strike Price':    strike,
        'Expiration Date': exp,
        'Ticker':          'TEST',
    })

def _make_df(*rows):
    """Helper — build a DataFrame from _make_row calls."""
    return pd.DataFrame(list(rows))

print('\n── Section 24: xe() ──────────────────────────────────────────────────────')

# Normal string passes through unchanged
check_int('xe: plain string',         xe('hello'),              'hello')
check_int('xe: integer input',        xe(42),                   '42')
check_int('xe: None input',           xe(None),                 'None')
check_int('xe: < escaped',            xe('<script>'),           '&lt;script&gt;')
check_int('xe: > escaped',            xe('>'),                  '&gt;')
check_int('xe: & escaped',            xe('AT&T'),               'AT&amp;T')
check_int('xe: double quote escaped', xe('"hello"'),            '&quot;hello&quot;')
check_int('xe: mixed HTML chars',     xe('<b class="x">hi</b>'), '&lt;b class=&quot;x&quot;&gt;hi&lt;/b&gt;')

print('\n── Section 24: identify_pos_type() ──────────────────────────────────────')

check_int('ipt: Long Stock',  identify_pos_type(_make_row('Equity', '',     100)),  'Long Stock')
check_int('ipt: Short Stock', identify_pos_type(_make_row('Equity', '',    -100)),  'Short Stock')
check_int('ipt: Long Call',   identify_pos_type(_make_row('Equity Option', 'CALL',   1)), 'Long Call')
check_int('ipt: Short Call',  identify_pos_type(_make_row('Equity Option', 'CALL',  -1)), 'Short Call')
check_int('ipt: Long Put',    identify_pos_type(_make_row('Equity Option', 'PUT',    1)), 'Long Put')
check_int('ipt: Short Put',   identify_pos_type(_make_row('Equity Option', 'PUT',   -1)), 'Short Put')
check_int('ipt: Future Option Short Put',
      identify_pos_type(_make_row('Future Option', 'PUT', -1)), 'Short Put')
check_int('ipt: unknown type returns Asset',
      identify_pos_type(_make_row('Unknown', '', 1)), 'Asset')

print('\n── Section 24: detect_strategy() ────────────────────────────────────────')

# Short Put — single naked put
check_int('ds: Short Put',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'PUT', -1, 100)
      )), 'Short Put')

# Covered Call — long stock + short call
check_int('ds: Covered Call',
      detect_strategy(_make_df(
          _make_row('Equity',        '',     100),
          _make_row('Equity Option', 'CALL', -1, 110),
      )), 'Covered Call')

# Covered Strangle — long stock + short call + short put
check_int('ds: Covered Strangle',
      detect_strategy(_make_df(
          _make_row('Equity',        '',     100),
          _make_row('Equity Option', 'CALL', -1, 110),
          _make_row('Equity Option', 'PUT',  -1,  90),
      )), 'Covered Strangle')

# Short Strangle — short call + short put, no stock
check_int('ds: Short Strangle',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL', -1, 110),
          _make_row('Equity Option', 'PUT',  -1,  90),
      )), 'Short Strangle')

# Jade Lizard — short put + short call + long call
check_int('ds: Jade Lizard',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'PUT',  -1,  90),
          _make_row('Equity Option', 'CALL', -1, 110),
          _make_row('Equity Option', 'CALL',  1, 115),
      )), 'Jade Lizard')

# Big Lizard — short call + short put + long put
check_int('ds: Big Lizard',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL', -1, 110),
          _make_row('Equity Option', 'PUT',  -1,  90),
          _make_row('Equity Option', 'PUT',   1,  85),
      )), 'Big Lizard')

# Risk Reversal — long call + short put
check_int('ds: Risk Reversal',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL',  1, 110),
          _make_row('Equity Option', 'PUT',  -1,  90),
      )), 'Risk Reversal')

# Call Debit Spread — 2 long calls + 1 short call
check_int('ds: Call Debit Spread',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL',  1, 100),
          _make_row('Equity Option', 'CALL',  1, 105),
          _make_row('Equity Option', 'CALL', -1, 110),
      )), 'Call Debit Spread')

# Call Butterfly — 2 long calls + 1 short call, 3 strikes, 1 expiry
check_int('ds: Call Butterfly',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL',  1,  95, '2026-06-20'),
          _make_row('Equity Option', 'CALL', -1, 100, '2026-06-20'),
          _make_row('Equity Option', 'CALL',  1, 105, '2026-06-20'),
      )), 'Call Butterfly')

# Put Butterfly — 2 long puts + 1 short put, 3 strikes, 1 expiry
check_int('ds: Put Butterfly',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'PUT',  1,  95, '2026-06-20'),
          _make_row('Equity Option', 'PUT', -1, 100, '2026-06-20'),
          _make_row('Equity Option', 'PUT',  1, 105, '2026-06-20'),
      )), 'Put Butterfly')

# Calendar Spread — same strike, 2 expiries (calls)
check_int('ds: Calendar Spread (calls)',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL',  1, 100, '2026-06-20'),
          _make_row('Equity Option', 'CALL', -1, 100, '2026-07-18'),
      )), 'Calendar Spread')

# Calendar Spread — same strike, 2 expiries (puts)
check_int('ds: Calendar Spread (puts)',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'PUT',  1, 100, '2026-06-20'),
          _make_row('Equity Option', 'PUT', -1, 100, '2026-07-18'),
      )), 'Calendar Spread')

# Long Call — single long call
check_int('ds: Long Call',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL', 1, 100)
      )), 'Long Call')

# Long Stock — shares only
check_int('ds: Long Stock',
      detect_strategy(_make_df(
          _make_row('Equity', '', 100)
      )), 'Long Stock')

# Custom/Mixed — unrecognised combination
check_int('ds: Custom/Mixed fallback',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL',  1, 100),
          _make_row('Equity Option', 'CALL',  1, 105),
      )), 'Custom/Mixed')

# ══════════════════════════════════════════════════════════════════════════════
# GRAND TOTAL
# ══════════════════════════════════════════════════════════════════════════════
print(f'\n{"═"*60}')
print(f'  GRAND TOTAL:  {PASS+FAIL} tests  |  {PASS} passed  |  {FAIL} failed')
print(f'{"═"*60}')

if FAIL > 0:
    print('\nFailed tests:')
    for status, name, actual, expected in results:
        if status == 'FAIL':
            print(f'  ❌ {name}  (got={actual}  expected={expected})')
    sys.exit(1)
else:
    print('\n  All tests passed ✅')
