# 📟 TastyMechanics

A Streamlit dashboard for analysing your TastyTrade options trading history. Upload your CSV export and get a full breakdown of realized P/L, wheel campaigns, trade analytics, and portfolio health — all running locally or on Streamlit Community Cloud. Your data is never sent anywhere.

![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![Streamlit](https://img.shields.io/badge/streamlit-1.30%2B-red) ![License](https://img.shields.io/badge/license-MIT-green)

---

## Try it online

Hosted on Streamlit Community Cloud — upload your CSV and explore without installing anything:

**[→ tastymechanics.streamlit.app]([https://tastymechanics.streamlit.app](https://tastymechanics-v6mwejh3jtdmaz5aw7rxzk.streamlit.app/))**

---

## Features

**Portfolio Overview**
- Realized P/L, Return on Capital, Capital Efficiency Score (annualised)
- Capital deployed, margin loan, dividends + interest
- Inline P/L breakdown chips (campaign type and windowed components)
- Period comparison card — current vs prior equivalent window with deltas
- Expiry alert strip — all options expiring within 21 days, colour-coded by urgency

**Derivatives Performance tab**
- Premium selling scorecard: win rate, median capture %, median days held, annualised return, banked $/day
- Avg winner / loser, win/loss ratio, total fees and fees as % of P/L
- Call vs Put performance table
- Defined vs Undefined Risk breakdown by strategy
- Performance by ticker table
- DTE at open distribution, rolling win rate chart
- Options P/L by week and month

**Trade Analysis tab**
- ThetaGang metrics: management rate, median DTE at open/close, top-3 concentration score
- LEAPS automatically separated from short-premium metrics (DTE > 90 threshold)
- DTE at close distribution chart with TastyTrade target zone highlighted
- Rolling 10-trade win rate over time
- Win/Loss P/L histogram
- P/L heatmap by ticker and month

**Wheel Campaigns tab**
- Per-ticker campaign cards: entry basis, effective basis, premiums banked, realised P/L
- Option roll chain visualisation — calls and puts tracked as separate chains
- Share and dividend event log per campaign
- Lifetime "House Money" mode toggle

**All Trades tab**
- Full ticker breakdown: premiums, dividends, options P/L, capital deployed
- Total portfolio P/L by week and month (FIFO-correct, includes equity sales)
- Volatility metrics: avg week P/L, weekly std dev, Sharpe-equivalent, profitable weeks %, max drawdown + recovery

**Deposits, Dividends & Fees tab**
- Full income and cash movement log with colour-coded row types

---

## Getting Started (local)

### Requirements

```
python >= 3.10
streamlit >= 1.30
pandas >= 2.0
plotly >= 5.0
```

### Install

```bash
pip install streamlit pandas plotly
```

### Run

```bash
streamlit run Tastytrade_CSV_Dashboard_v25.9.py
```

Then open `http://localhost:8501` in your browser.

### Getting your CSV from TastyTrade

1. Log in to TastyTrade
2. Go to **History → Transactions**
3. Set your date range (export your full history for best results)
4. Click **Download CSV**
5. Upload the file in the dashboard sidebar

---

## Deploying to Streamlit Community Cloud

1. Fork this repository
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub
3. Click **New app** → select your fork → set main file to `Tastytrade_CSV_Dashboard_v25.9.py`
4. Deploy — no secrets or environment variables required

---

## Disclaimer

This tool is for personal record-keeping only. It is not financial advice.

**Known limitations — verify these manually if they apply to your account:**

- **Covered calls assigned away** — if your shares are called away by assignment, verify the campaign closes and P/L records correctly.
- **Multiple assignments on the same ticker** — each new buy-in starts a new campaign. Blended basis across campaigns is not combined.
- **Long options exercised by you** — exercising a long call or put into shares is untested. Check the resulting position and cost basis.
- **Futures options delivery** — cash-settled futures options (/MES, /ZS etc.) are included in P/L totals, but in-the-money expiry into a futures contract is not handled.
- **Stock splits** — forward and reverse splits are detected and FIFO-adjusted, but TastyTrade-issued post-split option symbols are not stitched to pre-split contracts.
- **Spin-offs and zero-cost deliveries** — shares received at $0 cost (spin-offs, ACATS transfers) trigger a warning. The $0 basis means P/L on eventual sale will be overstated until corrected.
- **Complex multi-leg structures** — PMCC, diagonals, calendars, and ratio spreads may not be classified correctly in the trade log.
- **Non-US accounts** — built and tested on a US TastyTrade account. CSV format and field differences for other regions are unknown.

P/L figures are cash-flow based (what actually hit your account) and use FIFO cost basis for equity. They do not account for unrealised gains/losses, wash sale rules, or tax adjustments. Always reconcile against your official TastyTrade statements for tax purposes.

---

## Architecture

**Data flow**

```
CSV upload
  └── load_and_parse()       cached on raw bytes — reruns only on new file
        └── build_all_data() cached on (df, use_lifetime) — reruns on toggle
              └── window slices recomputed on time window change (fast)
```

**Key design decisions**

- **Naive UTC everywhere** — TastyTrade exports UTC timestamps. Parsed as UTC then immediately stripped to naive. No browser-local timezone conversion.
- **Single FIFO engine** — `_iter_fifo_sells()` is the sole source of truth for equity cost basis. Handles long and short positions via parallel deques per ticker.
- **AppData dataclass** — `build_all_data()` returns a typed dataclass, not a positional tuple. Safe to extend without breaking callers.
- **LEAPS separation** — trades with DTE > 90 at open are excluded from ThetaGang metrics and surfaced as a separate callout.
- **Campaign accounting** — options traded before the first share purchase (pre-campaign) are classified as standalone P/L, not campaign premiums. Assignment STOs stay in the outside-window bucket to prevent double-counting.

**Test suite**

`test_tastymechanics.py` contains 180 tests covering all P/L figures, campaign accounting, windowed views, FIFO edge cases, and structural invariants. All expected values were derived independently from raw CSV data — the test suite does not use any app code. Run with:

```bash
python test_tastymechanics.py
```

To also verify the app's displayed values against ground truth, generate a snapshot first:

```bash
# Windows PowerShell
$env:TASTYMECHANICS_TEST="1"
python -m streamlit run Tastytrade_CSV_Dashboard_v25.9.py
# Upload your CSV, then run the tests
python test_tastymechanics.py
```

---

## Changelog

**v25.9** (2026-02-26) — Assignment STO double-count fix, windowed P/L income fix, standalone equity FIFO fix, 180-test suite added. All P/L figures verified against real account data.

**v25.6** (2026-02-26) — Stock split handling, zero-cost delivery warnings, short equity FIFO fix, LEAPS separation, timezone architecture unification, full code review.

**v25.4** (2026-02-24) — Pre-purchase option campaign fix (SMR basis $16.72 → $20.25), prior period double-count fix, How Closed column, weekly/monthly P/L charts.

**v25.3** (2026-02-23) — Expiry alert strip, period comparison card, open positions card grid, dark theme.

---

## License

MIT — do what you like with it, no warranty implied.
