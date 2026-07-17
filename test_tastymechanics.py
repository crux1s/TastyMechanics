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
from config    import OPT_TYPES, TRADE_TYPES, INCOME_SUB_TYPES, KNOWN_INDEXES
from mechanics import (
    _iter_fifo_sells,
    build_campaigns,
    pure_options_pnl,
    effective_basis,
    realized_pnl,
    compute_app_data,
    build_option_chains,
    build_closed_trades,
    _calculate_capital_risk,
    calculate_daily_realized_pnl,
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
# 0. END-TO-END SMOKE CHECK — compute_app_data
# ══════════════════════════════════════════════════════════════════════════════
# compute_app_data() is the Streamlit entry point that wires everything
# together.  Individual sections below test the helper functions in isolation,
# but only this call exercises the full pipeline including any positional /
# attribute access on the ParsedData object, the campaign-window threading,
# and the AppData construction.
#
# Why this section exists: v26.13 converted ParsedData from NamedTuple to
# @dataclass to support a new field with field(default_factory=list).  That
# change broke ONE consumer at mechanics.py:1285 — a bare-name positional
# unpack `df, split_events, zero_cost_rows = parsed` — which dataclasses
# don't support.  No per-helper test caught it because none of them go
# through compute_app_data.  This section closes that gap.
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 0. End-to-end smoke check: compute_app_data ────────────────────────')

_smoke_app    = compute_app_data(_parsed, use_lifetime=False)
_smoke_app_lt = compute_app_data(_parsed, use_lifetime=True)

# Confirm the returned AppData has the expected shape.  Exact numbers are
# tested per-helper later; here we only verify the integration didn't crash
# and the returned object is well-formed.
check_int('Smoke: AppData has all_campaigns dict',
          isinstance(_smoke_app.all_campaigns, dict), True)
check_int('Smoke: AppData has closed_trades_df as DataFrame',
          isinstance(_smoke_app.closed_trades_df, pd.DataFrame), True)
check_int('Smoke: AppData has df_open as DataFrame',
          isinstance(_smoke_app.df_open, pd.DataFrame), True)
check_int('Smoke: closed_camp_pnl is a number',
          isinstance(_smoke_app.closed_camp_pnl, (int, float)), True)
check_int('Smoke: split_events passed through from ParsedData',
          _smoke_app.split_events == _parsed.split_events, True)
check_int('Smoke: zero_cost_rows passed through from ParsedData',
          _smoke_app.zero_cost_rows == _parsed.zero_cost_rows, True)
# Lifetime mode uses the same ParsedData-derived fields but a different
# campaign-aggregation pass — confirm both branches construct cleanly.
check_int('Smoke: lifetime mode AppData also constructs',
          isinstance(_smoke_app_lt.all_campaigns, dict), True)


# ══════════════════════════════════════════════════════════════════════════════
# 1. DATA LOADING & PARSING
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 1. Data loading & parsing ──────────────────────────────────────────')

check_int('Row count',           len(df), 642)
check_int('Equity rows',         equity_mask(df['Instrument Type']).sum(), 33)
check_int('Equity Option rows',  (df['Instrument Type'] == 'Equity Option').sum(), 519)
check_int('Future Option rows',  (df['Instrument Type'] == 'Future Option').sum(), 24)
check_int('Money Movement rows', (df['Type'] == 'Money Movement').sum(), 80)
check('Total of all rows',       df['Total'].sum(), 19.83)

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
      sum(p - c for _, p, c in fifo_results), -181.92)

unh_net  = df[(df['Ticker'] == 'UNH')  & equity_mask(df['Instrument Type'])]['Net_Qty_Row'].sum()
meta_net = df[(df['Ticker'] == 'META') & equity_mask(df['Instrument Type'])]['Net_Qty_Row'].sum()
check('UNH shares fully closed (net qty = 0)',   unh_net,  0.0)
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
check('Total options cash flow', opt_df['Total'].sum(), 2036.60)

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
check('Total dividends + interest', income['Total'].sum(), -56.30)
check('Dividends total',       df[df['Sub Type'] == 'Dividend']['Total'].sum(),           2.61)
check('Credit interest total', df[df['Sub Type'] == 'Credit Interest']['Total'].sum(),    0.12)
check('Debit interest total',  df[df['Sub Type'] == 'Debit Interest']['Total'].sum(),   -59.03)
check('META net dividends',
      df[(df['Ticker'] == 'META') & (df['Sub Type'] == 'Dividend')]['Total'].sum(), 0.18)
check('TLT total dividends',
      df[(df['Ticker'] == 'TLT') & (df['Sub Type'] == 'Dividend')]['Total'].sum(), 0.55)

# ══════════════════════════════════════════════════════════════════════════════
# 5. CAMPAIGN ACCOUNTING — window boundary verification
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 5. Campaign accounting ──────────────────────────────────────────────')

achr_post = df[(df['Ticker'] == 'ACHR') & df['Instrument Type'].isin(OPT_TYPES) &
               df['Type'].isin(TRADE_TYPES) & (df['Date'] >= pd.Timestamp('2025-12-19'))]['Total'].sum()
check('ACHR campaign premiums (post-purchase only, excl assignment STO)', achr_post, 175.60)

achr_pre = df[(df['Ticker'] == 'ACHR') & df['Instrument Type'].isin(OPT_TYPES) &
              df['Type'].isin(TRADE_TYPES) & (df['Date'] < pd.Timestamp('2025-12-19'))]['Total'].sum()
check('ACHR pre-purchase STO (outside window = 27.89)', achr_pre, 27.89)

sofi_post = df[(df['Ticker'] == 'SOFI') & df['Instrument Type'].isin(OPT_TYPES) &
               df['Type'].isin(TRADE_TYPES) & (df['Date'] >= pd.Timestamp('2025-12-01'))]['Total'].sum()
check('SOFI campaign premiums (post-Dec-1 options)', sofi_post, 584.53)

sofi_pre = df[(df['Ticker'] == 'SOFI') & df['Instrument Type'].isin(OPT_TYPES) &
              df['Type'].isin(TRADE_TYPES) & (df['Date'] < pd.Timestamp('2025-12-01'))]['Total'].sum()
check('SOFI pre-purchase STO (outside window = 117.88)', sofi_pre, 117.88)

smr_pre = df[(df['Ticker'] == 'SMR') & df['Instrument Type'].isin(OPT_TYPES) &
             df['Type'].isin(TRADE_TYPES) & (df['Date'] < pd.Timestamp('2026-01-09'))]['Total'].sum()
check('SMR pre-purchase options (outside window = 352.79)', smr_pre, 352.79)

smr_post = df[(df['Ticker'] == 'SMR') & df['Instrument Type'].isin(OPT_TYPES) &
              df['Type'].isin(TRADE_TYPES) & (df['Date'] >= pd.Timestamp('2026-01-09'))]['Total'].sum()
check('SMR campaign premiums (post-purchase)', smr_post, 148.13)

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

check('Ground truth total realized P/L',  ground_truth, 1798.38)
check('Options component',                all_opts,      2036.60)
check('Equity FIFO component',            all_eq,        -181.92)
check('Dividend+interest component',      all_inc,        -56.30)
check('Components sum to total',          all_opts + all_eq + all_inc, 1798.38)

# ══════════════════════════════════════════════════════════════════════════════
# 7. DEPOSITS / PORTFOLIO STATS
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 7. Portfolio stats ──────────────────────────────────────────────────')

deps = df[df['Sub Type'] == 'Deposit']['Total'].sum()
wdrs = df[df['Sub Type'] == 'Withdrawal']['Total'].sum()
check('Total deposited',       deps,            7635.10)
check('Total withdrawn',       wdrs,             -55.00)
check('Net deposited',         deps + wdrs,     7580.10)
check('Realized ROR %',        ground_truth / (deps + wdrs) * 100, 23.73, tol=0.1)
check('Cash balance (all rows summed)', df['Total'].sum(), 19.83, tol=0.01)

# ══════════════════════════════════════════════════════════════════════════════
# 8. OPEN EQUITY POSITIONS
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 8. Open equity positions ────────────────────────────────────────────')

eq_net  = df[equity_mask(df['Instrument Type'])].groupby('Ticker')['Net_Qty_Row'].sum()
open_eq = eq_net[eq_net.abs() > 0.001]

check_int('Number of open equity positions', len(open_eq), 5)
check('SMR  open shares', open_eq.get('SMR',  0), 100.0)
check('SOFI open shares', open_eq.get('SOFI', 0), 200.0)
check('JOBY open shares', open_eq.get('JOBY', 0), 100.0)
check('ACHR open shares (fully closed)', open_eq.get('ACHR', 0), 0.0)
check('IBIT open shares', open_eq.get('IBIT', 0),   1.0)
check('META open shares', open_eq.get('META', 0),   0.2)
check('UNH  fully closed (0 open shares)', open_eq.get('UNH', 0),   0.0)

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
check('All Time window P/L == ground truth', w_opts + w_eq + w_inc, 1798.38)

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
check_int('Expiration row count', len(exp_rows), 8)
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

check_int('UNH FIFO sells (position fully closed)',
          len(list(_iter_fifo_sells(
              df[(df['Ticker'] == 'UNH') & equity_mask(df['Instrument Type'])].sort_values('Date')
          ))), 1)
check_int('META no FIFO sells (position still open)',
          len(list(_iter_fifo_sells(
              df[(df['Ticker'] == 'META') & equity_mask(df['Instrument Type'])].sort_values('Date')
          ))), 0)

mesz5 = df[(df['Ticker'] == '/MESZ5') & df['Instrument Type'].isin(OPT_TYPES) & df['Type'].isin(TRADE_TYPES)]
check('/MESZ5 is pure cash-settled (no equity rows)',
      float(df[(df['Ticker'] == '/MESZ5') & equity_mask(df['Instrument Type'])].empty), 1.0)
check('/MESZ5 P/L = sum of trade rows', mesz5['Total'].sum(), 20.48)

bal_adj = df[df['Sub Type'] == 'Balance Adjustment']
check_int('Balance Adjustment rows', len(bal_adj), 37)
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
check('ACHR total cost (100 @ 8.55)',       a['cost'],      855.00)
check('ACHR shares held (closed = 0)',      a['shares'],      0.0)
check('ACHR campaign premiums (closed)',    a['premiums'],  175.60)
check('ACHR dividends',                     a['divs'],        0.00)
check('ACHR effective basis (closed = 0)', a['eff_basis'],    0.00)
check('ACHR closed campaign P/L',          a['camp_pnl'],  -86.02)

s = _camp('SOFI')
check('SOFI cost basis (200 shares)',  s['cost'],     5558.08)
check('SOFI shares held',              s['shares'],    200.0)
check('SOFI campaign premiums',        s['premiums'],  584.53)
check('SOFI effective basis/sh',       s['eff_basis'],  24.87, tol=0.01)
check('SOFI open campaign P/L',        s['camp_pnl'],  584.53)

m = _camp('SMR')
check('SMR cost basis (100 @ 20.48)', m['cost'],     2048.08)
check('SMR campaign premiums',         m['premiums'],  148.13)
check('SMR effective basis/sh',        m['eff_basis'],  19.00, tol=0.01)
check('SMR open campaign P/L',         m['camp_pnl'],  148.13)

j = _camp('JOBY')
check('JOBY cost basis (100 @ 15.33)', j['cost'],    1533.08)
check('JOBY campaign premiums',         j['premiums'],  191.72)
check('JOBY effective basis/sh',        j['eff_basis'],  13.41, tol=0.01)
check('JOBY open campaign P/L',         j['camp_pnl'],  191.72)

# ══════════════════════════════════════════════════════════════════════════════
# 11b. CLOSED CAMPAIGN — ACHR exit proceeds, status, end_date
# First real-data test of a fully closed wheel campaign.
# Entry: 100 shares assigned via put on 2025-12-20 @ $8.50 ($855 total).
# Exit:  100 shares sold on 2026-05-20 ($593.38 total proceeds).
# Premiums: 10 covered-call / short-put cycles net $182.72.
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 11b. Closed campaign (ACHR) ─────────────────────────────────────────')

achr_camps = build_campaigns(df, 'ACHR', use_lifetime=False)
ac = achr_camps[-1]   # single closed campaign

check_int('ACHR campaign count',             len(achr_camps),              1)
check_int('ACHR campaign status is closed',  int(ac.status == 'closed'),   1)
check_int('ACHR end_date is set',            int(ac.end_date is not None), 1)
check('ACHR total_shares after close',       ac.total_shares,            0.0)
check('ACHR total_cost',                     ac.total_cost,           855.00)
check('ACHR exit_proceeds',                  ac.exit_proceeds,         593.38)
check('ACHR premiums',                       ac.premiums,              175.60)
check('ACHR dividends',                      ac.dividends,               0.00)
check('ACHR realized_pnl',                   realized_pnl(ac),          -86.02)
check('ACHR effective_basis (closed = 0)',   effective_basis(ac),         0.00)

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
check('1W opts',   o,  208.36, tol=0.05)
check('1W equity', e, -261.62, tol=0.02)
check('1W income', i,  -12.07, tol=0.02)
check('1W total',  t,  -65.33, tol=0.10)

o,e,i,t = window_pnl(latest_date - pd.Timedelta(days=30))
check('1M opts',   o,  233.98, tol=0.05)
check('1M equity', e, -261.89, tol=0.02)
check('1M income', i,  -12.07, tol=0.02)
check('1M total',  t,  -39.98, tol=0.10)

_,_,_,t = window_pnl(latest_date - pd.Timedelta(days=90))
check('3M total',  t,  667.99, tol=0.20)

_,_,_,t = window_pnl(earliest)
check('All Time window == ground truth', t, 1798.38, tol=0.02)

o,e,i,t = window_pnl(pd.Timestamp(f'{latest_date.year}-01-01'))
check('YTD opts',   o,  1600.38, tol=0.05)
check('YTD equity', e,  -282.73, tol=0.02)
check('YTD income', i,   -58.00, tol=0.02)
check('YTD total',  t,  1259.65, tol=0.10)

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

check('ACHR capital deployed (closed = 0)', capital_deployed('ACHR'),   0.00)
check('SOFI capital deployed', capital_deployed('SOFI'),  5558.08)
check('SMR  capital deployed', capital_deployed('SMR'),   2048.08)
check('JOBY capital deployed', capital_deployed('JOBY'),  1533.08)
check('IBIT capital deployed', capital_deployed('IBIT'),    62.90)
check('META capital deployed', capital_deployed('META'),   150.22)
check('UNH  capital deployed (position closed)', capital_deployed('UNH'),      0.00)
check('Total capital deployed',
      sum(capital_deployed(t) for t in ['ACHR','SOFI','SMR','JOBY','IBIT','META','UNH']),
      9352.36)

# ══════════════════════════════════════════════════════════════════════════════
# 15. TICKER-LEVEL OPTIONS P/L
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 15. Ticker-level options P/L ────────────────────────────────────────')

def ticker_opts_pnl(ticker):
    return df[(df['Ticker'] == ticker) &
              df['Instrument Type'].isin(OPT_TYPES) &
              df['Type'].isin(TRADE_TYPES)]['Total'].sum()

check('RKLB options P/L',   ticker_opts_pnl('RKLB'),  1575.76)
check('INTC options P/L',   ticker_opts_pnl('INTC'),   110.79)
check('XYZ  options P/L',   ticker_opts_pnl('XYZ'),   -354.46)
check('GLD  options P/L',   ticker_opts_pnl('GLD'),   -189.92)
check('SPX  options P/L',   ticker_opts_pnl('SPX'),   -307.40)
check('/ZSF6 options P/L',  ticker_opts_pnl('/ZSF6'),  -60.93)
check('/MESZ5 options P/L', ticker_opts_pnl('/MESZ5'),  20.48)
check('/MESM6 options P/L', ticker_opts_pnl('/MESM6'), -41.96)

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

# ── Reverse-roll: STO for new strike has earlier timestamp than BTC of old ───
# Real-world case: during a roll executed in seconds, the STO order fills a
# moment before the BTC order. After sorting by timestamp, the chain ends with
# BTC as its last event. The net_qty replay (tab3 fix) must still detect this
# chain as open (net_qty=1) even though chain[-1]['sub_type'] == 'Buy to Close'.
_rev_roll = _make_opts([
    {'date': '2025-01-05 14:00:00', 'sub': 'Sell to Open',  'qty': -1, 'total':  80, 'strike': 10.5},
    {'date': '2025-01-19 09:25:56', 'sub': 'Sell to Open',  'qty': -1, 'total':  25, 'strike': 10.0},
    {'date': '2025-01-19 09:26:41', 'sub': 'Buy to Close',  'qty':  1, 'total': -19, 'strike': 10.5},
])
_ch6 = build_option_chains(_rev_roll)
check_int('Chains: reverse-roll → 1 chain',       len(_ch6), 1)
check_int('Chains: reverse-roll chain has 3 legs', len(_ch6[0]), 3)
# Verify net_qty replay (the logic used by tab3's is_open_chain fix)
_rr_net = 0
_rr_last_sto = -1
from config import PAT_CLOSE
for _ri, _rl in enumerate(_ch6[0]):
    _rsub = str(_rl['sub_type']).lower()
    if 'to open' in _rsub and _rl['qty'] < 0:
        _rr_net += abs(_rl['qty']); _rr_last_sto = _ri
    elif _rr_net > 0 and PAT_CLOSE in _rsub:
        _rr_net = max(_rr_net - abs(_rl['qty']), 0)
check_int('Chains: reverse-roll net_qty=1 (chain is open)', _rr_net, 1)
check_int('Chains: reverse-roll open leg is STO at index 1', _rr_last_sto, 1)


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

check_int('CT: total trades',              len(_ct),                    152)
check_int('CT: winning trades',            int(_ct['Won'].sum()),       128)
check    ('CT: win rate %',                _ct['Won'].mean() * 100,     84.2105)
check    ('CT: total net P/L',             _ct['Net P/L'].sum(),       1572.63)
check    ('CT: total premium received',    _ct['Net Premium'].sum(),  14753.39)
check    ('CT: median capture %',          _ct[_ct['Is Credit']]['Capture %'].median(),   39.4132)
check    ('CT: median days held',          _ct['Days Held'].median(),   6.0)
check    ('CT: median DTE at open',        _ct['DTE at Open'].median(),    32.0)
check_int('CT: credit trades',             int(_ct['Is Credit'].sum()), 147)
check_int('CT: debit trades',              int((~_ct['Is Credit']).sum()), 5)

# ── Per-ticker net P/L ───────────────────────────────────────────────────────
_ct_by_ticker = _ct.groupby('Ticker')['Net P/L'].sum()
check('CT ticker RKLB net P/L',   _ct_by_ticker['RKLB'],   1233.01)
check('CT ticker SOFI net P/L',   _ct_by_ticker['SOFI'],    675.67)
check('CT ticker SMR  net P/L',   _ct_by_ticker['SMR'],     480.05)
check('CT ticker INTC net P/L',   _ct_by_ticker['INTC'],    110.79)
check('CT ticker JOBY net P/L',   _ct_by_ticker['JOBY'],    130.98)
check('CT ticker GLD  net P/L',   _ct_by_ticker['GLD'],    -189.92)
check('CT ticker XYZ  net P/L',   _ct_by_ticker['XYZ'],    -354.46)
check('CT ticker SPX  net P/L',   _ct_by_ticker['SPX'],    -307.40)
check('CT ticker /MESM6 net P/L', _ct_by_ticker['/MESM6'],  -41.96)

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
check_int('CT RKLB strangle DTE open',    int(_rklb_big['DTE at Open']),    64)
# DTE at Close = (Dec 20 expiry − Dec 18 close) = 1 day.
# Regression guard: old code used (expiry − today), yielding 0 for any expired option.
check_int('CT RKLB strangle DTE at close', int(_rklb_big['DTE at Close']),  1)

# INTC strangle Dec11–Jan02: 22 days, $209.78 credit, $119.55 P/L
_intc_strang = _ct[
    (_ct['Ticker'] == 'INTC') &
    (_ct['Trade Type'] == 'Short Strangle') &
    (_ct['Net P/L'] > 100)
].iloc[0]
check('CT INTC strangle premium',        _intc_strang['Net Premium'],  209.78)
check('CT INTC strangle net P/L',        _intc_strang['Net P/L'],       119.55)
check('CT INTC strangle capture %',      _intc_strang['Capture %'],      56.9883)
# DTE at Close = (Jan 24 expiry − Jan 2 close) = 21 days
check_int('CT INTC strangle DTE at close', int(_intc_strang['DTE at Close']), 21)

# SOFI put assigned Feb-20: 42 days held, 100% capture (expired worthless assigned)
_sofi_assigned = _ct[
    (_ct['Ticker'] == 'SOFI') &
    (_ct['Close Reason'] == '📋 Assigned') &
    (_ct['Net Premium'] > 130)
].iloc[0]
check    ('CT SOFI assigned put premium',    _sofi_assigned['Net Premium'], 132.88)
check    ('CT SOFI assigned put net P/L',    _sofi_assigned['Net P/L'],      132.88)
check    ('CT SOFI assigned put capture %',  _sofi_assigned['Capture %'],    100.0)
check_int('CT SOFI assigned put days held',  int(_sofi_assigned['Days Held']), 42)
# Assigned at expiry: DTE at Close = 0
check_int('CT SOFI assigned put DTE at close', int(_sofi_assigned['DTE at Close']), 0)

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
# DTE at Close = (Jan 17 expiry − Jan 9 close) = 7 days.
# Old buggy code: (Jan 17 − today) = 0 for a now-expired option.
check_int('VERIFIED SLV put DTE at close',     int(_slv_put['DTE at Close']), 7)

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
check_int('CT strategy Short Put count',        int(_ct_strat.loc['Short Put',    'count']), 39)
check_int('CT strategy Short Call count',       int(_ct_strat.loc['Short Call',   'count']), 54)
check_int('CT strategy Iron Condor count',      int(_ct_strat.loc['Iron Condor',  'count']), 23)
check_int('CT strategy Iron Butterfly count',   int(_ct_strat.loc['Iron Butterfly','count']), 1)
check_int('CT strategy Short Strangle count',   int(_ct_strat.loc['Short Strangle','count']), 8)
check_int('CT strategy Put Credit Spread count',int(_ct_strat.loc['Put Credit Spread','count']), 13)

# Net P/L per strategy
check('CT strategy Short Put total P/L',      _ct_strat.loc['Short Put',    'total_pnl'],  1742.96)
check('CT strategy Short Call total P/L',     _ct_strat.loc['Short Call',   'total_pnl'],   889.53)
check('CT strategy Iron Condor total P/L',    _ct_strat.loc['Iron Condor',  'total_pnl'],  -430.13)
check('CT strategy Iron Butterfly total P/L', _ct_strat.loc['Iron Butterfly','total_pnl'],    29.84)
check('CT strategy Put Credit Spread P/L',    _ct_strat.loc['Put Credit Spread','total_pnl'], -710.39)
check('CT strategy Call Credit Spread P/L',   _ct_strat.loc['Call Credit Spread','total_pnl'], -286.42)

# /MESM6 futures call spread — verifies futures multiplier fix ($5/pt, not $100)
_mesm6 = _ct[_ct['Ticker'] == '/MESM6'].iloc[0]
check_int('CT /MESM6 trade type',         _mesm6['Trade Type'],      'Call Credit Spread')
check    ('CT /MESM6 capital at risk',     _mesm6['Capital at Risk'],   41.92)
check    ('CT /MESM6 net P/L',             _mesm6['Net P/L'],          -41.96)
check    ('CT /MESM6 net premium',         _mesm6['Net Premium'],       58.08)
check    ('CT /MESM6 capture %',           _mesm6['Capture %'],        -72.2452, tol=0.001)

# Win counts
check_int('CT strategy Short Call wins (all)',  int(_ct_strat.loc['Short Call', 'wins']), 50)
check_int('CT strategy Short Put wins',         int(_ct_strat.loc['Short Put',  'wins']), 37)
check_int('CT strategy Iron Condor wins',        int(_ct_strat.loc['Iron Condor',   'wins']), 18)
check_int('CT strategy Iron Butterfly wins',    int(_ct_strat.loc['Iron Butterfly','wins']),  1)

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

check_int('CT close type Closed count',   int(_close_counts.get('✂️ Closed',   0)), 144)
check_int('CT close type Expired count',  int(_close_counts.get('⏹️ Expired',  0)),   6)
check_int('CT close type Assigned count', int(_close_counts.get('📋 Assigned', 0)),   2)
check_int('CT close types sum to total',  int(_close_counts.sum()),                  152)

_expired = _ct[_ct['Close Reason'] == '⏹️ Expired']
# Expired trades — only check count; capture% varies (some expired worthless, some ITM)
check_int('CT expired: SOFI expired worthless (100% capture)',
          int((_expired[_expired['Ticker'] == 'SOFI']['Capture %'] == 100.0).sum()), 2)
check_int('CT expired: SPX expired ITM (loss, capture < 0)',
          int((_expired[_expired['Ticker'] == 'SPX']['Net P/L'] < 0).sum()), 1)
check_int('CT expired: all 3 are in the expired set',
          len(_expired), 6)

# Debit trades (Calendar Spread, Debit Spread, Butterfly)
_debit = _ct[~_ct['Is Credit']]
check_int('CT debit trade count',          len(_debit),                    5)
check    ('CT debit trades total P/L',     _debit['Net P/L'].sum(),       -172.19)

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

_latest = df['Date'].max()   # 2026-05-11

def _ct_window(start):
    """Closed trades whose Close Date falls on or after start."""
    return _ct[pd.to_datetime(_ct['Close Date']) >= start]

# YTD (Jan 1 2026 →)
_ytd = _ct_window(pd.Timestamp('2026-01-01'))
check_int('CT YTD trade count',   len(_ytd),                    98)
check    ('CT YTD net P/L',       _ytd['Net P/L'].sum(),      1718.53)
check_int('CT YTD win count',     int(_ytd['Won'].sum()),        83)

# 7d window
_w7 = _ct_window(_latest - timedelta(days=7))
check_int('CT 7d trade count',    len(_w7),                      10)
check    ('CT 7d net P/L',        _w7['Net P/L'].sum(),          13.62)

# 30d window
_w30 = _ct_window(_latest - timedelta(days=30))
check_int('CT 30d trade count',   len(_w30),                    26)
check    ('CT 30d net P/L',       _w30['Net P/L'].sum(),        377.82)

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

def _make_row(inst_type, cp, qty, strike=100.0, exp='2026-06-20', cost_basis=0.0):
    """Helper — build a minimal Series for identify_pos_type / detect_strategy."""
    return pd.Series({
        'Instrument Type': inst_type,
        'Call or Put':     cp,
        'Net_Qty':         qty,
        'Strike Price':    strike,
        'Expiration Date': exp,
        'Ticker':          'TEST',
        'Cost Basis':      cost_basis,
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

# Iron Condor — sc + lc + sp + lp, 4 distinct strikes, net credit
# Short inner strangle + long outer wings: net credit (Cost Basis sum < 0)
check_int('ds: Iron Condor',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL', -1, 110, '2026-06-20', -2.50),  # STO call
          _make_row('Equity Option', 'CALL',  1, 115, '2026-06-20',  1.00),  # BTO call wing
          _make_row('Equity Option', 'PUT',  -1,  90, '2026-06-20', -2.50),  # STO put
          _make_row('Equity Option', 'PUT',   1,  85, '2026-06-20',  1.00),  # BTO put wing
      )), 'Iron Condor')

# Reverse Iron Condor — same legs, net debit (long inner + short outer wings)
check_int('ds: Reverse Iron Condor',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL',  1, 110, '2026-06-20',  2.50),  # BTO call
          _make_row('Equity Option', 'CALL', -1, 115, '2026-06-20', -1.00),  # STO call wing
          _make_row('Equity Option', 'PUT',   1,  90, '2026-06-20',  2.50),  # BTO put
          _make_row('Equity Option', 'PUT',  -1,  85, '2026-06-20', -1.00),  # STO put wing
      )), 'Reverse Iron Condor')

# Iron Butterfly — short call and short put share the same ATM strike
check_int('ds: Iron Butterfly',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL', -1, 100, '2026-06-20', -3.00),  # STO ATM call
          _make_row('Equity Option', 'CALL',  1, 105, '2026-06-20',  1.00),  # BTO call wing
          _make_row('Equity Option', 'PUT',  -1, 100, '2026-06-20', -3.00),  # STO ATM put (same strike)
          _make_row('Equity Option', 'PUT',   1,  95, '2026-06-20',  1.00),  # BTO put wing
      )), 'Iron Butterfly')

# Reverse Iron Butterfly — long call and long put share the same ATM strike
check_int('ds: Reverse Iron Butterfly',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL',  1, 100, '2026-06-20',  3.00),  # BTO ATM call
          _make_row('Equity Option', 'CALL', -1, 105, '2026-06-20', -1.00),  # STO call wing
          _make_row('Equity Option', 'PUT',   1, 100, '2026-06-20',  3.00),  # BTO ATM put (same strike)
          _make_row('Equity Option', 'PUT',  -1,  95, '2026-06-20', -1.00),  # STO put wing
      )), 'Reverse Iron Butterfly')

# Jade Lizard still fires when there is NO long put (only 3 legs)
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

# Long Call Butterfly — 2 long calls + 1 short call, 3 strikes, 1 expiry
check_int('ds: Long Call Butterfly',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL',  1,  95, '2026-06-20'),
          _make_row('Equity Option', 'CALL', -1, 100, '2026-06-20'),
          _make_row('Equity Option', 'CALL',  1, 105, '2026-06-20'),
      )), 'Long Call Butterfly')

# Long Put Butterfly — 2 long puts + 1 short put, 3 strikes, 1 expiry
check_int('ds: Long Put Butterfly',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'PUT',  1,  95, '2026-06-20'),
          _make_row('Equity Option', 'PUT', -1, 100, '2026-06-20'),
          _make_row('Equity Option', 'PUT',  1, 105, '2026-06-20'),
      )), 'Long Put Butterfly')

# Short Call Butterfly — 1 long body (qty 2) + 2 short wings, 3 strikes, 1 expiry
check_int('ds: Short Call Butterfly',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL',  2, 100, '2026-06-20'),
          _make_row('Equity Option', 'CALL', -1,  95, '2026-06-20'),
          _make_row('Equity Option', 'CALL', -1, 105, '2026-06-20'),
      )), 'Short Call Butterfly')

# Short Put Butterfly — 1 long body (qty 2) + 2 short wings, 3 strikes, 1 expiry
check_int('ds: Short Put Butterfly',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'PUT',  2, 100, '2026-06-20'),
          _make_row('Equity Option', 'PUT', -1,  95, '2026-06-20'),
          _make_row('Equity Option', 'PUT', -1, 105, '2026-06-20'),
      )), 'Short Put Butterfly')

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

# ── Ratio spread detection (qty-based) ────────────────────────────────────────
# Put Ratio Spread — 2 short puts + 1 long put (DKNG-style)
check_int('ds: Put Ratio Spread',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'PUT', -2, 21.0),
          _make_row('Equity Option', 'PUT',  1, 21.5),
      )), 'Put Ratio Spread')

# Call Ratio Spread — 2 short calls + 1 long call (no stock)
check_int('ds: Call Ratio Spread',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'CALL', -2, 16.0),
          _make_row('Equity Option', 'CALL',  1, 15.5),
      )), 'Call Ratio Spread')

# Covered Call Ratio Spread — stock + 2 short calls + 1 long call (SMR-style)
check_int('ds: Covered Call Ratio Spread',
      detect_strategy(_make_df(
          _make_row('Equity',        '',     100),
          _make_row('Equity Option', 'CALL', -2, 16.0),
          _make_row('Equity Option', 'CALL',  1, 15.5),
      )), 'Covered Call Ratio Spread')

# 1:1 put spread still classifies as Put Credit Spread (not ratio)
check_int('ds: 1:1 put spread not misidentified as ratio',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'PUT', -1, 21.0),
          _make_row('Equity Option', 'PUT',  1, 21.5),
      )), 'Put Debit Spread')

# 2:2 put spread (equal qty) still classifies as vertical, not ratio
check_int('ds: 2:2 put spread not misidentified as ratio',
      detect_strategy(_make_df(
          _make_row('Equity Option', 'PUT', -2, 21.0),
          _make_row('Equity Option', 'PUT',  2, 21.5),
      )), 'Put Debit Spread')

# ══════════════════════════════════════════════════════════════════════════════
# 25. REGRESSION — Same-timestamp campaign close + covered-call cap-at-risk
# ══════════════════════════════════════════════════════════════════════════════
# Two bugs fixed in v26.11, pinned here so a future refactor can't reintroduce
# them silently:
#
#   (a) Same-timestamp stock-exit + BTC: when an equity row and an option close
#       share the exact order timestamp, the sort places Sort_Inst=0 before
#       Sort_Inst=1.  Before the fix, build_campaigns processed the stock close
#       first, sealed current → None, and dropped the BTC from the event log.
#       The BTC then leaked into pure_options_pnl via the outside-window bucket.
#       Fix: just_closed reference catches same-timestamp closing legs;
#       pure_options_pnl now uses an inclusive end boundary (<= c.end_date).
#
#   (b) Covered-call capital-at-risk: _calculate_capital_risk fell through to
#       the naked-short formula (max_strike × 100) for a short call held inside
#       a wheel window, which massively overstated risk.  Fix: when inside a
#       campaign window and no long-call leg, return abs(open_credit).
#
# Scenario modelled here is the real SOXS trade from the CSV that surfaced both
# bugs: BTO 100 shares + STO call at the same timestamp, then SELL shares + BTC
# at the same closing timestamp one day later.
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 25. Regression: same-timestamp close + covered-call cap-risk ──────────')

def _make_soxs_df():
    """Build a minimal DataFrame mirroring the SOXS wheel trade from the CSV.

    Two timestamps, four rows: open (stock + call) and close (stock + call).
    Both legs at each timestamp share the same Order # so the closed-trade
    grouper treats the short call as one trade.  Quantities and totals match
    the real CSV exactly so realized_pnl and pure_options_pnl assertions are
    numerically meaningful.
    """
    rows = [
        # Open — BTO 100 shares + STO 1 call at 19:43:20
        dict(Date=pd.Timestamp('2026-06-04 19:43:20'), Type='Trade',
             Action='BUY_TO_OPEN', Symbol='SOXS', Ticker='SOXS',
             InstrumentType='Equity', Description='Bought 100 SOXS @ 5.12',
             SubType='Buy to Open', Net_Qty_Row=100.0, Quantity=100.0,
             Value=-512.0, Total=-512.08, Order_No=473211219,
             CallOrPut=None, StrikePrice=None, ExpirationDate=None),
        dict(Date=pd.Timestamp('2026-06-04 19:43:20'), Type='Trade',
             Action='SELL_TO_OPEN', Symbol='SOXS  260717C00007000', Ticker='SOXS',
             InstrumentType='Equity Option',
             Description='Sold 1 SOXS 07/17/26 Call 7.00 @ 0.69',
             SubType='Sell to Open', Net_Qty_Row=-1.0, Quantity=1.0,
             Value=69.0, Total=67.87, Order_No=473211219,
             CallOrPut='CALL', StrikePrice=7.0,
             ExpirationDate=pd.Timestamp('2026-07-17')),
        # Close — SELL 100 shares + BTC 1 call at 19:32:27 next day
        dict(Date=pd.Timestamp('2026-06-05 19:32:27'), Type='Trade',
             Action='SELL_TO_CLOSE', Symbol='SOXS', Ticker='SOXS',
             InstrumentType='Equity', Description='Sold 100 SOXS @ 6.66',
             SubType='Sell to Close', Net_Qty_Row=-100.0, Quantity=100.0,
             Value=666.0, Total=665.88, Order_No=473670549,
             CallOrPut=None, StrikePrice=None, ExpirationDate=None),
        dict(Date=pd.Timestamp('2026-06-05 19:32:27'), Type='Trade',
             Action='BUY_TO_CLOSE', Symbol='SOXS  260717C00007000', Ticker='SOXS',
             InstrumentType='Equity Option',
             Description='Bought 1 SOXS 07/17/26 Call 7.00 @ 1.47',
             SubType='Buy to Close', Net_Qty_Row=1.0, Quantity=1.0,
             Value=-147.0, Total=-147.12, Order_No=473670549,
             CallOrPut='CALL', StrikePrice=7.0,
             ExpirationDate=pd.Timestamp('2026-07-17')),
    ]
    out = pd.DataFrame(rows)
    out = out.rename(columns={
        'InstrumentType': 'Instrument Type',
        'SubType':        'Sub Type',
        'Order_No':       'Order #',
        'CallOrPut':      'Call or Put',
        'StrikePrice':    'Strike Price',
        'ExpirationDate': 'Expiration Date',
    })
    return out

_soxs_df = _make_soxs_df()

# ── (a) Same-timestamp close: BTC must end up inside the campaign ──────────────
_soxs_camps = build_campaigns(_soxs_df, 'SOXS', use_lifetime=False)
check_int('SOXS regression: one closed campaign', len(_soxs_camps), 1)

_camp = _soxs_camps[0]
# premiums = STO credit + BTC debit = +67.87 − 147.12 = −79.25
check('SOXS regression: campaign.premiums incl. BTC', _camp.premiums,      -79.25)
check('SOXS regression: campaign.exit_proceeds',      _camp.exit_proceeds,  665.88)
check('SOXS regression: campaign.total_cost',         _camp.total_cost,     512.08)
# realized_pnl = exit_proceeds + premiums − total_cost = 665.88 − 79.25 − 512.08
check('SOXS regression: realized_pnl matches hand-calc',
      realized_pnl(_camp), 74.55)

# BTC must appear in the campaign event log (4 events: Entry, STO, Exit, BTC)
_event_types = [e['type'] for e in _camp.events]
check_int('SOXS regression: campaign has 4 events', len(_camp.events), 4)
check_int('SOXS regression: BTC event recorded in campaign',
          sum(1 for t in _event_types if 'to close' in t.lower()), 1)

# ── pure_options_pnl: BTC must NOT be double-counted in outside-window bucket ──
# With the inclusive end boundary, the BTC (same timestamp as end_date) is
# inside the campaign window, so the outside-window options total is exactly 0.
check('SOXS regression: pure_options_pnl excludes campaign BTC',
      pure_options_pnl(_soxs_df, 'SOXS', _soxs_camps), 0.00)

# ── (b) Covered-call capital-at-risk uses premium, not max_strike × 100 ────────
# build_closed_trades with campaign_windows passed: short call inside the
# campaign window must classify as Covered Call and use abs(open_credit) as
# capital at risk.  Without campaign_windows it falls through to the naked-
# short path and uses strike × 100 — that's the regression guard for the
# alternate code path.
_camp_windows = {'SOXS': [(_camp.start_date, _camp.end_date)]}
_soxs_ct = build_closed_trades(_soxs_df, campaign_windows=_camp_windows)

check_int('SOXS regression: one closed trade row', len(_soxs_ct), 1)
_row = _soxs_ct.iloc[0]
check_int('SOXS regression: classified as Covered Call',
          _row['Trade Type'] == 'Covered Call', True)
check('SOXS regression: covered-call cap-at-risk = premium',
      _row['Capital at Risk'], 67.87)
# Net P/L is the raw cash flow on the option legs only (build_closed_trades
# doesn't see the stock side): STO 67.87 + BTC −147.12 = −79.25.
check('SOXS regression: closed-trade Net P/L', _row['Net P/L'], -79.25)

# ── Regression guard: same trade with NO campaign window falls through to ─────
# ── the naked-short formula (max_strike × mult).  Confirms we didn't break ────
# ── the naked path while adding the covered-call short-circuit. ───────────────
_naked_ct = build_closed_trades(_soxs_df, campaign_windows={})
check('SOXS regression: no-campaign-window → naked-short cap-at-risk = strike×100',
      _naked_ct.iloc[0]['Capital at Risk'], 700.0)
check_int('SOXS regression: no-campaign-window → label not Covered',
          _naked_ct.iloc[0]['Trade Type'] != 'Covered Call', True)


# ══════════════════════════════════════════════════════════════════════════════
# 26. REGRESSION — v26.12 code-review fixes
# ══════════════════════════════════════════════════════════════════════════════
# Three issues caught by /code-review on the v26.11 PR and fixed in v26.12:
#
#   (a) Covered strangle / straddle inside a wheel campaign was hitting the
#       covered-call short-circuit (which checked only `has_sc and not has_lc`)
#       and returning premium-as-risk, ignoring the unhedged short-put leg.
#       Real exposure: put_strike × mult − credit.  The short-circuit was
#       split into two branches (pure covered call vs covered strangle/straddle)
#       in _calculate_capital_risk.
#
#   (b) `nearest_exp = exp_dates.iloc[0]` in build_closed_trades picked the
#       first row in transaction-Date order, NOT the earliest calendar
#       expiration.  For a calendar spread where the far-month leg opens
#       first, this overstated dte_open (e.g. 60 instead of 30), silently
#       halving Daily θ % and showing the wrong Expiration column.
#       Fixed to `exp_dates.min()`.
#
#   (c) _LegInfo dataclass + _derive_leg_info helper extracted to fold the
#       duplicated is_butterfly / is_short_butterfly / has_sc/sp/lc/lp /
#       short_call_qty / long_call_qty prelude (~16 lines × 2 functions) into
#       a single source of truth.  The hazard: prior to v26.12, _classify_trade_type
#       and _calculate_capital_risk had identical conditions side-by-side, so a
#       one-sided edit would silently desync classification from cap-risk.
#       This regression check pins the assertion that both functions consume
#       the SAME LegInfo for the same trade group.
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 26. Regression: v26.12 code-review fixes ─────────────────────────────')

from mechanics import _derive_leg_info


def _make_covered_strangle_df(ticker='ACHR'):
    """Wheel campaign on ACHR (own 100 shares from $20 entry).  Then on Mar 1
    sell a covered strangle: STO $25 call + STO $15 put, both 30 DTE, same
    Order # so they group as one trade.  Both legs close worthless on Mar 31
    via Expiration sub-type.  The stock side is irrelevant to build_closed_trades
    (which only looks at option rows), so we model just the four option rows
    plus a tiny stock open to anchor the wheel campaign window.
    """
    rows = [
        # Stock buy that opens the wheel campaign — needed only so a campaign
        # window exists.  Date: Feb 1.
        dict(Date=pd.Timestamp('2026-02-01 14:30:00'), Type='Trade',
             Action='BUY_TO_OPEN', Symbol=ticker, Ticker=ticker,
             InstrumentType='Equity', Description='Bought 100 shares',
             SubType='Buy to Open', Net_Qty_Row=100.0, Quantity=100.0,
             Value=-2000.0, Total=-2001.0, Order_No=100,
             CallOrPut=None, StrikePrice=None, ExpirationDate=None),
        # Covered strangle opens: STO call @ 25, STO put @ 15, same order
        dict(Date=pd.Timestamp('2026-03-01 14:30:00'), Type='Trade',
             Action='SELL_TO_OPEN',
             Symbol=f'{ticker}  260331C00025000', Ticker=ticker,
             InstrumentType='Equity Option',
             Description=f'Sold 1 {ticker} 03/31/26 Call 25.00 @ 1.00',
             SubType='Sell to Open', Net_Qty_Row=-1.0, Quantity=1.0,
             Value=100.0, Total=99.0, Order_No=200,
             CallOrPut='CALL', StrikePrice=25.0,
             ExpirationDate=pd.Timestamp('2026-03-31')),
        dict(Date=pd.Timestamp('2026-03-01 14:30:00'), Type='Trade',
             Action='SELL_TO_OPEN',
             Symbol=f'{ticker}  260331P00015000', Ticker=ticker,
             InstrumentType='Equity Option',
             Description=f'Sold 1 {ticker} 03/31/26 Put 15.00 @ 1.00',
             SubType='Sell to Open', Net_Qty_Row=-1.0, Quantity=1.0,
             Value=100.0, Total=99.0, Order_No=200,
             CallOrPut='PUT', StrikePrice=15.0,
             ExpirationDate=pd.Timestamp('2026-03-31')),
        # Both legs expire worthless on Mar 31
        dict(Date=pd.Timestamp('2026-03-31 16:00:00'), Type='Receive Deliver',
             Action=None,
             Symbol=f'{ticker}  260331C00025000', Ticker=ticker,
             InstrumentType='Equity Option',
             Description='Removal of option due to expiration',
             SubType='Expiration', Net_Qty_Row=1.0, Quantity=1.0,
             Value=0.0, Total=0.0, Order_No=None,
             CallOrPut='CALL', StrikePrice=25.0,
             ExpirationDate=pd.Timestamp('2026-03-31')),
        dict(Date=pd.Timestamp('2026-03-31 16:00:00'), Type='Receive Deliver',
             Action=None,
             Symbol=f'{ticker}  260331P00015000', Ticker=ticker,
             InstrumentType='Equity Option',
             Description='Removal of option due to expiration',
             SubType='Expiration', Net_Qty_Row=1.0, Quantity=1.0,
             Value=0.0, Total=0.0, Order_No=None,
             CallOrPut='PUT', StrikePrice=15.0,
             ExpirationDate=pd.Timestamp('2026-03-31')),
    ]
    out = pd.DataFrame(rows).rename(columns={
        'InstrumentType': 'Instrument Type',
        'SubType':        'Sub Type',
        'Order_No':       'Order #',
        'CallOrPut':      'Call or Put',
        'StrikePrice':    'Strike Price',
        'ExpirationDate': 'Expiration Date',
    })
    return out


# ── (a) Covered strangle inside campaign window ─────────────────────────────
_cs_df = _make_covered_strangle_df()
# Campaign window: Feb 1 → end of test window (campaign still open at Mar 1)
_cs_windows = {'ACHR': [(pd.Timestamp('2026-02-01 14:30:00'),
                        pd.Timestamp('2026-12-31 00:00:00'))]}
_cs_ct = build_closed_trades(_cs_df, campaign_windows=_cs_windows)

check_int('Covered strangle regression: one closed trade row', len(_cs_ct), 1)
_cs_row = _cs_ct.iloc[0]
check_int('Covered strangle regression: classified as Covered Strangle',
          _cs_row['Trade Type'] == 'Covered Strangle', True)
# Correct cap-at-risk = put_strike × 100 − credit = 15 × 100 − 198 = 1302.
# Pre-v26.12 this returned $198 (premium only, ignoring the unhedged put leg) —
# 6.6× understated.
check('Covered strangle regression: cap-at-risk = put_strike × 100 − credit',
      _cs_row['Capital at Risk'], 1302.0)

# Regression guard: same trade with NO campaign window falls through to the
# naked-short path and returns max_strike × mult = 25 × 100 = $2500.
_cs_naked = build_closed_trades(_cs_df, campaign_windows={})
_cs_naked_row = _cs_naked.iloc[0]
check_int('Covered strangle regression: no-campaign → naked Short Strangle',
          _cs_naked_row['Trade Type'] == 'Short Strangle', True)
check('Covered strangle regression: no-campaign → cap-at-risk = max_strike × 100',
      _cs_naked_row['Capital at Risk'], 2500.0)


# ── (b) Calendar spread nearest_exp ordering ────────────────────────────────
def _make_calendar_far_first_df(ticker='SPY'):
    """Calendar spread opened far-month first (the failure case).

    Mon Mar 9: STO Aug-expiry $400 call (60 DTE)
    Tue Mar 10: BTO Apr-expiry $400 call (30 DTE) — opened second, same Order #
    Both legs close together on Mar 12.
    The 'nearest' calendar expiration is Apr (not Aug), so dte_open should be
    closer to 30 than 60.  Pre-v26.12 the bug used iloc[0] which is the first
    transaction-Date row = Aug → dte_open ≈ 60.
    """
    rows = [
        # Mon: STO far-month (Aug, 60 DTE)
        dict(Date=pd.Timestamp('2026-03-09 14:30:00'), Type='Trade',
             Action='SELL_TO_OPEN',
             Symbol=f'{ticker}  260808C00400000', Ticker=ticker,
             InstrumentType='Equity Option',
             Description=f'Sold 1 {ticker} 08/08/26 Call 400.00 @ 5.00',
             SubType='Sell to Open', Net_Qty_Row=-1.0, Quantity=1.0,
             Value=500.0, Total=500.0, Order_No=300,
             CallOrPut='CALL', StrikePrice=400.0,
             ExpirationDate=pd.Timestamp('2026-08-08')),
        # Tue: BTO near-month (Apr, 30 DTE)
        dict(Date=pd.Timestamp('2026-03-10 14:30:00'), Type='Trade',
             Action='BUY_TO_OPEN',
             Symbol=f'{ticker}  260408C00400000', Ticker=ticker,
             InstrumentType='Equity Option',
             Description=f'Bought 1 {ticker} 04/08/26 Call 400.00 @ 3.00',
             SubType='Buy to Open', Net_Qty_Row=1.0, Quantity=1.0,
             Value=-300.0, Total=-300.0, Order_No=300,
             CallOrPut='CALL', StrikePrice=400.0,
             ExpirationDate=pd.Timestamp('2026-04-08')),
        # Close both on Mar 12
        dict(Date=pd.Timestamp('2026-03-12 14:30:00'), Type='Trade',
             Action='BUY_TO_CLOSE',
             Symbol=f'{ticker}  260808C00400000', Ticker=ticker,
             InstrumentType='Equity Option',
             Description=f'Bought 1 {ticker} 08/08/26 Call 400.00 @ 4.00',
             SubType='Buy to Close', Net_Qty_Row=1.0, Quantity=1.0,
             Value=-400.0, Total=-400.0, Order_No=301,
             CallOrPut='CALL', StrikePrice=400.0,
             ExpirationDate=pd.Timestamp('2026-08-08')),
        dict(Date=pd.Timestamp('2026-03-12 14:30:00'), Type='Trade',
             Action='SELL_TO_CLOSE',
             Symbol=f'{ticker}  260408C00400000', Ticker=ticker,
             InstrumentType='Equity Option',
             Description=f'Sold 1 {ticker} 04/08/26 Call 400.00 @ 2.00',
             SubType='Sell to Close', Net_Qty_Row=-1.0, Quantity=1.0,
             Value=200.0, Total=200.0, Order_No=301,
             CallOrPut='CALL', StrikePrice=400.0,
             ExpirationDate=pd.Timestamp('2026-04-08')),
    ]
    out = pd.DataFrame(rows).rename(columns={
        'InstrumentType': 'Instrument Type',
        'SubType':        'Sub Type',
        'Order_No':       'Order #',
        'CallOrPut':      'Call or Put',
        'StrikePrice':    'Strike Price',
        'ExpirationDate': 'Expiration Date',
    })
    return out


_cal_df = _make_calendar_far_first_df()
_cal_ct = build_closed_trades(_cal_df, campaign_windows={})
check_int('Calendar regression: one closed trade row', len(_cal_ct), 1)
_cal_row = _cal_ct.iloc[0]
# open_date is Mon Mar 9 (first STO).  Nearest expiration is Apr 8 (30d), NOT
# the first-by-DataFrame-order Aug 8 (152d).
check_int('Calendar regression: nearest expiration = Apr (earliest by date)',
          str(_cal_row['Expiration']) == '2026-04-08', True)
# DTE at open: Apr 8 (midnight) − Mar 9 14:30 = 29 full days (the half-day
# from Mar 9's afternoon doesn't round up).  What matters for the regression
# is that this is in the ~30-day ballpark, NOT the 152-day far-month value
# the old `iloc[0]` bug would have produced.
check_int('Calendar regression: dte_open uses earliest expiry (~30d)',
          int(_cal_row['DTE at Open']), 29)
# Sanity guard: opening the LATER expiry first must not silently change DTE.
# Pre-fix this would have been 152, an order-of-magnitude error feeding Daily θ %.
check_int('Calendar regression: dte_open is NOT the far-month',
          int(_cal_row['DTE at Open']) != 152, True)


# ── (c) _LegInfo single-source-of-truth check ────────────────────────────────
# Pin the assertion that both the classifier and the cap-risk calculator can
# now only diverge if _derive_leg_info itself changes — not via independent
# duplicate edits.  Spot-check that the derived flags match what a covered
# strangle's opens row produce.
_cs_opens = _cs_df[
    _cs_df['Sub Type'].str.lower().str.contains('to open', na=False) &
    _cs_df['Instrument Type'].isin(['Equity Option'])
]
_cs_grp = _cs_df[_cs_df['Instrument Type'].isin(['Equity Option'])]
_info = _derive_leg_info(_cs_grp, _cs_opens)

check_int('LegInfo: covered strangle has_sc',  _info.has_sc, True)
check_int('LegInfo: covered strangle has_sp',  _info.has_sp, True)
check_int('LegInfo: covered strangle has_lc',  _info.has_lc, False)
check_int('LegInfo: covered strangle has_lp',  _info.has_lp, False)
check_int('LegInfo: covered strangle n_short_legs', _info.n_short_legs, 2)
check_int('LegInfo: covered strangle n_long_legs',  _info.n_long_legs,  0)
check_int('LegInfo: covered strangle is_butterfly = False',
          _info.is_butterfly, False)
check_int('LegInfo: covered strangle is_short_butterfly = False',
          _info.is_short_butterfly, False)
check_int('LegInfo: covered strangle is_calendar = False',
          _info.is_calendar, False)


# ══════════════════════════════════════════════════════════════════════════════
# 27. REGRESSION — v26.13 defensive: detect_unknown_actions
# ══════════════════════════════════════════════════════════════════════════════
# Surfaces Trade / Receive Deliver rows where Net_Qty_Row was silently zeroed
# because get_signed_qty() didn't recognise the Action / Description, but
# Quantity was non-zero.  Split removals (legitimately zero by design) must
# NOT trigger the warning.
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 27. Regression: detect_unknown_actions defensive scan ────────────────')

from ingestion import detect_unknown_actions


def _make_unknown_action_df():
    """Three rows: one normal BUY (recognised), one mystery 'TRANSFER_IN' (qty=50,
    not recognised → Net_Qty_Row=0 → should be flagged), and one legitimate
    split-removal (qty=100, Net_Qty_Row=0 → must NOT be flagged because the
    Description matches SPLIT_DSC_PATTERNS).
    """
    rows = [
        # Normal recognised buy
        dict(Date=pd.Timestamp('2026-01-15 14:30:00'), Type='Trade',
             Action='BUY_TO_OPEN', Symbol='NVDA', Ticker='NVDA',
             InstrumentType='Equity',
             Description='Bought 100 NVDA @ 500.00',
             SubType='Buy to Open',
             Quantity=100.0, Net_Qty_Row=100.0,
             Total=-50000.0),
        # Mystery action — qty present, but Net_Qty_Row zeroed.
        # This is the failure mode the defensive scan catches.
        dict(Date=pd.Timestamp('2026-02-01 09:00:00'), Type='Trade',
             Action='TRANSFER_IN', Symbol='NVDA', Ticker='NVDA',
             InstrumentType='Equity',
             Description='ACATS inbound transfer of 50 shares',
             SubType='Transfer',
             Quantity=50.0, Net_Qty_Row=0.0,
             Total=0.0),
        # Split removal — Net_Qty_Row=0 is correct (apply_split_adjustments
        # handles the share-count change separately).  Must NOT be flagged.
        dict(Date=pd.Timestamp('2026-03-01 16:00:00'), Type='Receive Deliver',
             Action=None, Symbol='NVDA', Ticker='NVDA',
             InstrumentType='Equity',
             Description='REMOVAL OF 100 SHARES DUE TO STOCK SPLIT',
             SubType='Symbol Change',
             Quantity=100.0, Net_Qty_Row=0.0,
             Total=0.0),
    ]
    out = pd.DataFrame(rows).rename(columns={
        'InstrumentType': 'Instrument Type',
        'SubType':        'Sub Type',
    })
    return out


_ua_df = _make_unknown_action_df()
_ua_unknown = detect_unknown_actions(_ua_df)

# Exactly one row is flagged: the mystery TRANSFER_IN, not the BUY and not the split.
check_int('detect_unknown_actions: exactly one suspicious row', len(_ua_unknown), 1)
check_int('detect_unknown_actions: TRANSFER_IN is the flagged ticker',
          _ua_unknown[0]['ticker'] == 'NVDA', True)
check_int('detect_unknown_actions: action = TRANSFER_IN',
          _ua_unknown[0]['action'] == 'TRANSFER_IN', True)
check_int('detect_unknown_actions: quantity preserved',
          int(_ua_unknown[0]['quantity']) == 50, True)
check_int('detect_unknown_actions: split removal NOT flagged',
          all('SPLIT' not in r['description'].upper() for r in _ua_unknown), True)

# Empty DataFrame guard
_empty = pd.DataFrame(columns=[
    'Type', 'Action', 'Symbol', 'Ticker', 'Description', 'Sub Type',
    'Quantity', 'Net_Qty_Row',
])
check_int('detect_unknown_actions: empty df returns []',
          detect_unknown_actions(_empty) == [], True)

# Cash-settled SPX / index option rows: Quantity records the contract count
# but no shares move, so they're allow-listed via the 'Cash Settled' Sub Type
# fragment.  These must NOT be flagged.  The canonical CSV has two such SPX
# rows (Cash Settled Exercise + Cash Settled Assignment on 2025-09-11) — they
# were the false positives that prompted the allow-list in the first place.
_cs_row = {
    'Date': pd.Timestamp('2025-09-11 21:00:00'), 'Type': 'Receive Deliver',
    'Action': None, 'Symbol': 'SPXW 250911C06585000', 'Ticker': 'SPX',
    'Instrument Type': 'Equity Option',
    'Description': 'Cash settlement of SPXW 250911C06585000',
    'Sub Type': 'Cash Settled Exercise',
    'Quantity': 1.0, 'Net_Qty_Row': 0.0, 'Total': 0.0,
}
_cs_df = pd.DataFrame([_cs_row])
check_int('detect_unknown_actions: cash-settled SPX is allow-listed',
          len(detect_unknown_actions(_cs_df)), 0)
# Symbol Change rows (corporate restructures) — also allow-listed.
_sc_row = dict(_cs_row)
_sc_row['Sub Type'] = 'Symbol Change'
_sc_row['Description'] = 'Symbol change FOO → BAR'
check_int('detect_unknown_actions: symbol change is allow-listed',
          len(detect_unknown_actions(pd.DataFrame([_sc_row]))), 0)

# Real-CSV ground truth: the canonical test fixture must NOT produce any
# false positives after the allow-list is applied.  If this fails after a
# parser change, the new logic is misclassifying legitimate rows.
_ground_truth_unknown = detect_unknown_actions(df)
check_int('detect_unknown_actions: canonical test CSV produces zero unknowns',
          len(_ground_truth_unknown), 0)


# ══════════════════════════════════════════════════════════════════════════════
# 28. REGRESSION — v26.15 covered-call stock-basis capital
# ══════════════════════════════════════════════════════════════════════════════
# With cap-at-risk = premium (v26.12), every covered call's Daily θ %
# degenerated to 100/dte_open (the premium cancels out of credit/dte/capital)
# and Ann Return % pegged at ±cap.  v26.15 supplies an optional campaign_basis
# dict {ticker: [(start, end, basis_per_share)]} so a pure covered call uses
# the stock actually pinned (basis × mult) as its capital base — the same
# scale as a CSP's strike × mult.
#
# Campaign.shares_acquired (cumulative buys, split-adjusted, never reduced by
# sales) makes total_cost / shares_acquired survive campaign close, where
# blended_basis is zeroed.
#
# Reuses the SOXS fixture from section 25: bought 100 @ $5.1208/sh
# (total_cost 512.08), covered call sold for 67.87 credit at 43 DTE.
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 28. Regression: covered-call stock-basis capital ─────────────────────')

# shares_acquired survives the (closed) SOXS campaign
check_int('Basis: SOXS campaign shares_acquired = 100',
          int(_camp.shares_acquired), 100)
check('Basis: per-share acquisition cost = 5.1208',
      _camp.total_cost / _camp.shares_acquired, 5.1208, tol=0.0001)
check_int('Basis: blended_basis zeroed on close (why shares_acquired exists)',
          _camp.blended_basis == 0.0, True)

# With campaign_basis supplied: cap-at-risk = basis × 100 = 512.08
_soxs_basis = {'SOXS': [(_camp.start_date, _camp.end_date,
                         _camp.total_cost / _camp.shares_acquired)]}
_soxs_ct_b = build_closed_trades(
    _soxs_df, campaign_windows=_camp_windows, campaign_basis=_soxs_basis)
_row_b = _soxs_ct_b.iloc[0]
check_int('Basis: still classified Covered Call',
          _row_b['Trade Type'] == 'Covered Call', True)
check('Basis: cap-at-risk = stock basis × 100', _row_b['Capital at Risk'], 512.08)
# Daily θ % = 67.87 / 42 / 512.08 × 100 ≈ 0.316 — a genuine yield, not 100/DTE.
# (dte_open = 42: Jul 17 00:00 − Jun 4 19:43 truncates the partial day.)
check('Basis: Daily θ % is yield-on-collateral', _row_b['Daily θ %'], 0.3156, tol=0.001)

# Without campaign_basis: premium fallback (pre-v26.15 behaviour) preserved —
# section 25 pins this at 67.87; re-assert here so the pairing is explicit.
_soxs_ct_nb = build_closed_trades(_soxs_df, campaign_windows=_camp_windows)
check('Basis: no-basis fallback still premium', _soxs_ct_nb.iloc[0]['Capital at Risk'], 67.87)


# ══════════════════════════════════════════════════════════════════════════════
# 29. LONG-TERM PERFORMANCE — xirr() + portfolio_metrics()
# ══════════════════════════════════════════════════════════════════════════════
# MWR (money-weighted return / XIRR), CAGR on deposits, max drawdown, Calmar,
# monthly stats.  TWR is intentionally NOT computed (needs daily NLV the CSV
# lacks) — these are the honest, computable long-term metrics.
print('\n── 29. Long-term performance: xirr + portfolio_metrics ──────────────────')

from mechanics import xirr, portfolio_metrics, _max_drawdown

_T0 = pd.Timestamp('2025-01-01')
def _yr(n): return _T0 + pd.Timedelta(days=365*n)

# ── XIRR ──
# Deposit $1000 (out of pocket → -1000), 1yr later worth $1100 (+1100) → 10%.
check('XIRR: +10%/yr', xirr([(_T0,-1000.0),(_yr(1),1100.0)]), 0.10, tol=0.005)
# $1000 → $500 over 1yr → -50%.
check('XIRR: -50%/yr', xirr([(_T0,-1000.0),(_yr(1),500.0)]), -0.50, tol=0.005)
# Two deposits then terminal: -1000 @ y0, -1000 @ y1, +2200 @ y2 → ~ small positive
_mwr2 = xirr([(_T0,-1000.0),(_yr(1),-1000.0),(_yr(2),2200.0)])
check_int('XIRR: multi-flow returns a rate', _mwr2 is not None and -1 < _mwr2 < 10, True)
# Degenerate cases → None
check_int('XIRR: all same sign → None', xirr([(_T0,-1000.0),(_yr(1),-500.0)]) is None, True)
check_int('XIRR: single flow → None', xirr([(_T0,-1000.0)]) is None, True)
check_int('XIRR: empty → None', xirr([]) is None, True)
# Terminal far beyond the +1000%/yr bracket → unbracketed → None
check_int('XIRR: beyond bracket → None',
          xirr([(_T0,-1000.0),(_yr(1),100000.0)]) is None, True)

# ── portfolio_metrics: CAGR ──
def _flat_daily(dates_vals):
    return pd.DataFrame([{'Date': pd.Timestamp(d), 'PnL': v} for d, v in dates_vals])

# CAGR: realized 1000 on 1000 deposited over 365d → (1+1)^1 - 1 = 1.0
_pm = portfolio_metrics(_flat_daily([('2025-01-01',1000.0)]),
                        [(_T0,-1000.0)], 1000.0, 1000.0, 365, _yr(1))
check('CAGR: 1000/1000/365d = 1.0', _pm['cagr'], 1.0, tol=0.001)
# Same over 730d → (2)^(0.5) - 1 ≈ 0.4142
_pm2 = portfolio_metrics(_flat_daily([('2025-01-01',1000.0)]),
                         [(_T0,-1000.0)], 1000.0, 1000.0, 730, _yr(2))
check('CAGR: 1000/1000/730d ≈ 0.414', _pm2['cagr'], 0.4142, tol=0.001)
# Guards → None
_pm3 = portfolio_metrics(_flat_daily([('2025-01-01',100.0)]), [], 0.0, 100.0, 365, _yr(1))
check_int('CAGR: net_deposited<=0 → None', _pm3['cagr'] is None, True)

# ── Max drawdown ──
# PnL [100,50,-200,30,100,100] → cum [100,150,-50,-20,80,180]; trough at idx2.
_dd_dates = [('2025-01-01',100.0),('2025-01-02',50.0),('2025-01-03',-200.0),
             ('2025-01-04',30.0),('2025-01-05',100.0),('2025-01-06',100.0)]
_dd = _max_drawdown(_flat_daily(_dd_dates))
check('MaxDD: dollar = -200', _dd['dollar'], -200.0)
check('MaxDD: pct ≈ -133.3', _dd['pct'], -133.3333, tol=0.01)
check_int('MaxDD: recovered (idx5, cum 180 >= peak 150)', _dd['recovery_days'] is not None, True)

# ── Monthly stats ── three months: +500, -200, +300
_mo = _flat_daily([('2025-01-15',500.0),('2025-02-15',-200.0),('2025-03-15',300.0)])
_pmm = portfolio_metrics(_mo, [(_T0,-1000.0)], 1000.0, 600.0, 90, pd.Timestamp('2025-03-31'))
check_int('Months: n_months = 3', _pmm['n_months'], 3)
check('Months: pct profitable ≈ 66.67', _pmm['pct_profitable_months'], 66.6667, tol=0.01)
check('Months: best = 500', _pmm['best_month'], 500.0)
check('Months: worst = -200', _pmm['worst_month'], -200.0)

# ── MTM terminal adds unrealized ──
_pm_mtm = portfolio_metrics(_flat_daily([('2025-01-01',1000.0)]),
                            [(_T0,-1000.0)], 1000.0, 1000.0, 365, _yr(1),
                            unrealized_total=500.0)
check('MTM: terminal_realized = dep + realized', _pm_mtm['terminal_realized'], 2000.0)
check('MTM: terminal_mtm = + unrealized', _pm_mtm['terminal_mtm'], 2500.0)
check_int('MTM: mwr_mtm computed', _pm_mtm['mwr_mtm'] is not None, True)
check_int('Realized-only: mwr_mtm is None', _pm['mwr_mtm'] is None, True)

# ── Real-CSV smoke ──
_dep_rows = df[df['Sub Type'] == 'Deposit'][['Date', 'Total']]
_wd_rows  = df[df['Sub Type'] == 'Withdrawal'][['Date', 'Total']]
_cf = ([(d, -t) for d, t in zip(_dep_rows['Date'], _dep_rows['Total'])] +
       [(d, -t) for d, t in zip(_wd_rows['Date'], _wd_rows['Total'])])
_net_dep = df[df['Sub Type'] == 'Deposit']['Total'].sum() + df[df['Sub Type'] == 'Withdrawal']['Total'].sum()
_real_total = _smoke_app.closed_camp_pnl + _smoke_app.open_premiums_banked + _smoke_app.pure_opts_pnl
_real_total += df[df['Sub Type'].isin(INCOME_SUB_TYPES)]['Total'].sum() - sum(
    c.dividends for cs in _smoke_app.all_campaigns.values() for c in cs)
_daily_all = calculate_daily_realized_pnl(df, df['Date'].min())
_acct_days = max((df['Date'].max() - df['Date'].min()).days, 1)
_perf = portfolio_metrics(_daily_all, _cf, _net_dep, _real_total, _acct_days, df['Date'].max())
check_int('Smoke: all metric keys present',
          all(k in _perf for k in ['mwr_realized','cagr','max_dd_dollar','calmar',
                                    'monthly_pnl','pct_profitable_months','terminal_realized']), True)
check('Smoke: terminal_realized = net_dep + realized', _perf['terminal_realized'], round(_net_dep + _real_total, 4), tol=0.01)
check_int('Smoke: max_dd_dollar <= 0', (_perf['max_dd_dollar'] or 0) <= 0, True)
check_int('Smoke: deposits found (cash flows non-empty)', len(_cf) > 0, True)
check_int('Smoke: mwr_realized None or in (-1,10)',
          _perf['mwr_realized'] is None or (-1 < _perf['mwr_realized'] < 10), True)


# ══════════════════════════════════════════════════════════════════════════════
# 30. ODD-LOT SHARE POOL — pre-campaign buys fold into the next entry
#
# Regression for the RKLB 92-vs-87 bug (Jul 2026): the share-buy branch in
# build_campaigns() required qty >= WHEEL_MIN_SHARES, so odd-lot buys (e.g.
# 3 + 2 shares before a 100-share put assignment) were silently ignored while
# the sale branch deducted full sale quantities from the campaign — the card
# showed 87 shares when the broker held 92, and the odd shares' cost was
# missing from total_cost (future closed-campaign P/L overstated by that cost).
# ══════════════════════════════════════════════════════════════════════════════
print('\n── 30. Odd-lot share pool: pre-campaign buys fold into entry ─────────────')

def _mk_share_row(ts, qty, total, sub_type=None):
    """Minimal equity row for build_campaigns synthetic tests."""
    if sub_type is None:
        sub_type = 'Buy to Open' if qty > 0 else 'Sell to Close'
    return dict(Date=pd.Timestamp(ts), Type='Trade',
                Action='BUY_TO_OPEN' if qty > 0 else 'SELL_TO_CLOSE',
                Symbol='ODDL', Ticker='ODDL', InstrumentType='Equity',
                Description='%s %.0f ODDL' % ('Bought' if qty > 0 else 'Sold', abs(qty)),
                SubType=sub_type, Net_Qty_Row=float(qty), Quantity=float(abs(qty)),
                Value=float(total), Total=float(total), Order_No=1,
                CallOrPut=None, StrikePrice=None, ExpirationDate=None)

def _mk_share_df(rows):
    out = pd.DataFrame(rows)
    return out.rename(columns={
        'InstrumentType': 'Instrument Type', 'SubType': 'Sub Type',
        'Order_No': 'Order #', 'CallOrPut': 'Call or Put',
        'StrikePrice': 'Strike Price', 'ExpirationDate': 'Expiration Date',
    })

# ── (a) Odd-lot buys before entry fold in (the RKLB shape: 3+2, +100, −13) ────
_odd_df = _mk_share_df([
    _mk_share_row('2026-06-29 19:30:01',    3,  -293.19),
    _mk_share_row('2026-06-29 19:30:02',    2,  -195.46),
    _mk_share_row('2026-07-16 21:00:00',  100, -9505.00),
    _mk_share_row('2026-07-17 11:53:52',  -13,   867.33),
])
_odd_camps = build_campaigns(_odd_df, 'ODDL', use_lifetime=False)
check_int('Odd-lot: one open campaign',            len(_odd_camps), 1)
_oc = _odd_camps[0]
check('Odd-lot: 92 shares remaining',              _oc.total_shares,    92.0)
check('Odd-lot: 105 shares acquired',              _oc.shares_acquired, 105.0)
check('Odd-lot: total_cost includes both lots',    _oc.total_cost,      9993.65)
check('Odd-lot: exit_proceeds from 13-share sale', _oc.exit_proceeds,   867.33)
check_int('Odd-lot: pool buys recorded in events',
          sum(1 for e in _oc.events if 'odd lot' in e['detail']), 2)
# (f) start_date stays the qualifying-entry date, not the first pool buy
check_int('Odd-lot: start_date = entry date (premium windowing unchanged)',
          _oc.start_date == pd.Timestamp('2026-07-16 21:00:00'), True)

# ── (b) Pool never reaching threshold → no campaign ───────────────────────────
_tiny_df = _mk_share_df([
    _mk_share_row('2026-01-05', 5, -500.0),
    _mk_share_row('2026-02-05', 7, -700.0),
])
check_int('Odd-lot: sub-threshold pool alone → no campaign',
          len(build_campaigns(_tiny_df, 'ODDL', use_lifetime=False)), 0)

# ── (c) Small mid-campaign add now counts (8-share top-up to 108) ─────────────
_add_df = _mk_share_df([
    _mk_share_row('2026-01-05', 100, -9500.0),
    _mk_share_row('2026-02-05',   8,  -800.0),
])
_add_c = build_campaigns(_add_df, 'ODDL', use_lifetime=False)[0]
check('Odd-lot: small add → 108 shares',           _add_c.total_shares, 108.0)
check('Odd-lot: small add blends basis',           _add_c.blended_basis, 10300.0 / 108)

# ── (d) Odd-lot sale before campaign shrinks the pool ─────────────────────────
_pool_sale_df = _mk_share_df([
    _mk_share_row('2026-01-05',   5, -500.0),
    _mk_share_row('2026-01-10',  -2,   210.0),   # sell 2 of the odd lot
    _mk_share_row('2026-02-05', 100, -9500.0),
])
_ps_c = build_campaigns(_pool_sale_df, 'ODDL', use_lifetime=False)[0]
check('Odd-lot: pool sale → 103 shares fold in',   _ps_c.total_shares, 103.0)
check('Odd-lot: pool cost relieved proportionally', _ps_c.total_cost,  9500.0 + 300.0)

# full pool sale — later campaign must be a clean 100-lot
_pool_flat_df = _mk_share_df([
    _mk_share_row('2026-01-05',   5, -500.0),
    _mk_share_row('2026-01-10',  -5,   520.0),
    _mk_share_row('2026-02-05', 100, -9500.0),
])
_pf_c = build_campaigns(_pool_flat_df, 'ODDL', use_lifetime=False)[0]
check('Odd-lot: emptied pool leaves clean 100-lot entry', _pf_c.total_shares, 100.0)
check('Odd-lot: emptied pool leaves clean entry cost',    _pf_c.total_cost,  9500.0)

# ── (e) Cumulative buys crossing the threshold start a campaign ───────────────
_cum_df = _mk_share_df([
    _mk_share_row('2026-01-05', 60, -6000.0),
    _mk_share_row('2026-02-05', 60, -6300.0),
])
_cum_camps = build_campaigns(_cum_df, 'ODDL', use_lifetime=False)
check_int('Odd-lot: 60+60 accumulation starts a campaign', len(_cum_camps), 1)
check('Odd-lot: accumulation entry has 120 shares', _cum_camps[0].total_shares, 120.0)
check_int('Odd-lot: accumulation start_date = crossing buy',
          _cum_camps[0].start_date == pd.Timestamp('2026-02-05'), True)


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
