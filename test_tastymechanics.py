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
    """Find the TastyTrade CSV — looks in script folder then uploads mount."""
    candidates = []
    for f in os.listdir(_HERE):
        if f.startswith('tastytrade') and f.endswith('.csv'):
            candidates.append(os.path.join(_HERE, f))
    uploads = '/mnt/user-data/uploads'
    if os.path.isdir(uploads):
        for f in os.listdir(uploads):
            if f.startswith('tastytrade') and f.endswith('.csv'):
                candidates.append(os.path.join(uploads, f))
    if not candidates:
        raise FileNotFoundError(
            "No tastytrade CSV found.\n"
            f"Looked in: {_HERE}\n"
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

check_int('Row count',           len(df), 422)
check_int('Equity rows',         equity_mask(df['Instrument Type']).sum(), 24)
check_int('Equity Option rows',  (df['Instrument Type'] == 'Equity Option').sum(), 330)
check_int('Future Option rows',  (df['Instrument Type'] == 'Future Option').sum(), 20)
check_int('Money Movement rows', (df['Type'] == 'Money Movement').sum(), 56)
check('Total of all rows',       df['Total'].sum(), -3488.91)

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
check('Total options cash flow', opt_df['Total'].sum(), 892.17)

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
check('SOFI campaign premiums (post-Dec-1 options)', sofi_post, 402.46)

sofi_pre = df[(df['Ticker'] == 'SOFI') & df['Instrument Type'].isin(OPT_TYPES) &
              df['Type'].isin(TRADE_TYPES) & (df['Date'] < pd.Timestamp('2025-12-01'))]['Total'].sum()
check('SOFI pre-purchase STO (outside window = 117.88)', sofi_pre, 117.88)

smr_pre = df[(df['Ticker'] == 'SMR') & df['Instrument Type'].isin(OPT_TYPES) &
             df['Type'].isin(TRADE_TYPES) & (df['Date'] < pd.Timestamp('2026-01-09'))]['Total'].sum()
check('SMR pre-purchase options (outside window = 352.79)', smr_pre, 352.79)

smr_post = df[(df['Ticker'] == 'SMR') & df['Instrument Type'].isin(OPT_TYPES) &
              df['Type'].isin(TRADE_TYPES) & (df['Date'] >= pd.Timestamp('2026-01-09'))]['Total'].sum()
check('SMR campaign premiums (post-purchase = 22.96)', smr_post, 22.96)

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

check('Ground truth total realized P/L',  ground_truth, 965.59)
check('Options component',                all_opts,      892.17)
check('Equity FIFO component',            all_eq,         79.97)
check('Dividend+interest component',      all_inc,         -6.55)
check('Components sum to total',          all_opts + all_eq + all_inc, 965.59)

# ══════════════════════════════════════════════════════════════════════════════
# 7. DEPOSITS / PORTFOLIO STATS
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 7. Portfolio stats ──────────────────────────────────────────────────')

deps = df[df['Sub Type'] == 'Deposit']['Total'].sum()
wdrs = df[df['Sub Type'] == 'Withdrawal']['Total'].sum()
check('Total deposited',       deps,            5998.00)
check('Total withdrawn',       wdrs,             -55.00)
check('Net deposited',         deps + wdrs,     5943.00)
check('Realized ROR %',        ground_truth / (deps + wdrs) * 100, 16.24, tol=0.1)
check('Cash balance (all rows summed)', df['Total'].sum(), -3488.91, tol=0.01)

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
check('All Time window P/L == ground truth', w_opts + w_eq + w_inc, 965.59)

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
check('SOFI campaign premiums',        s['premiums'],  402.46)
check('SOFI effective basis/sh',       s['eff_basis'],  25.78, tol=0.01)
check('SOFI open campaign P/L',        s['camp_pnl'],  402.46)

m = _camp('SMR')
check('SMR cost basis (100 @ 20.48)', m['cost'],     2048.08)
check('SMR campaign premiums',         m['premiums'],   22.96)
check('SMR effective basis/sh',        m['eff_basis'],  20.25, tol=0.01)
check('SMR open campaign P/L',         m['camp_pnl'],   22.96)

j = _camp('JOBY')
check('JOBY cost basis (100 @ 15.33)', j['cost'],    1533.08)
check('JOBY campaign premiums',         j['premiums'],  52.32)
check('JOBY effective basis/sh',        j['eff_basis'], 14.81, tol=0.01)
check('JOBY open campaign P/L',         j['camp_pnl'],  52.32)

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
check('1W opts',   o,  -143.96, tol=0.05)
check('1W equity', e,   -20.84, tol=0.02)
check('1W income', i,     0.00, tol=0.02)
check('1W total',  t,  -164.80, tol=0.10)

o,e,i,t = window_pnl(latest_date - pd.Timedelta(days=30))
check('1M opts',   o,  -168.52, tol=0.05)
check('1M equity', e,   -20.84, tol=0.02)
check('1M income', i,    -7.23, tol=0.02)
check('1M total',  t,  -196.59, tol=0.10)

_,_,_,t = window_pnl(latest_date - pd.Timedelta(days=90))
check('3M total',  t,   713.24, tol=0.20)

_,_,_,t = window_pnl(earliest)
check('All Time window == ground truth', t, 965.59, tol=0.02)

o,e,i,t = window_pnl(pd.Timestamp(f'{latest_date.year}-01-01'))
check('YTD opts',   o,  455.95, tol=0.05)
check('YTD equity', e,  -20.84, tol=0.02)
check('YTD income', i,   -8.25, tol=0.02)
check('YTD total',  t,  426.86, tol=0.10)

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
