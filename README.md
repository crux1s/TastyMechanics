# 📟 TastyMechanics

A local Streamlit dashboard for analysing your TastyTrade options trading history. Upload your CSV export and get a full breakdown of P/L, wheel campaigns, trade analytics, and portfolio health — all running in your browser, no data leaves your machine.

![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![Streamlit](https://img.shields.io/badge/streamlit-1.30%2B-red) ![License](https://img.shields.io/badge/license-MIT-green)

---

## Features

**Portfolio Overview**
- Realized P/L, Return on Capital, Capital Efficiency Score (annualised)
- Capital deployed, margin loan, dividends + interest
- Inline P/L breakdown chips (by campaign type or windowed components)
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

## Getting Started

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
streamlit run Tastytrade_CSV_Dashboard_v25.6.py
```

Then open `http://localhost:8501` in your browser.

### Getting your CSV from TastyTrade

1. Log in to TastyTrade
2. Go to **History → Transactions**
3. Set your date range (export the full history for best results)
4. Click **Download CSV**
5. Upload the file in the dashboard sidebar

---

## Architecture Notes

**Data flow**

```
CSV upload
  └── load_and_parse()          cached on raw bytes — re-runs only on new upload
        └── build_all_data()    cached on (df, use_lifetime) — re-runs on toggle
              └── window slices re-computed on every time window change (fast)
```

**Key design decisions**

- **Naive UTC everywhere** — TastyTrade exports UTC timestamps. Dates are parsed as UTC then immediately stripped to naive. All downstream comparisons, groupby, and charts use naive datetimes. No browser-local timezone conversion, no mixing.
- **FIFO engine** — `_iter_fifo_sells()` is the single source of truth for equity cost basis. Handles both long and short positions via parallel `long_queues` / `short_queues` deques per ticker.
- **AppData dataclass** — `build_all_data()` returns a typed dataclass, not a positional tuple. Safe to extend without breaking callers.
- **LEAPS separation** — trades with DTE > 90 at open are excluded from ThetaGang DTE metrics (which are meaningful only for short-premium strategies) and surfaced as a separate callout.

---

## Limitations

- **Options data only** — futures and futures options cash flows are included in P/L totals but strategy classification is limited to equity options.
- **Margin tracking** — margin requirements on short equity positions are not tracked. Short shares appear in Open Positions correctly but do not contribute to the Capital Deployed metric.
- **Roll chain heuristic** — chains are split when a position goes flat and the next open is >3 days later. Complex structures inside a campaign (PMCC, diagonals) may show as fragments.
- **No real-time data** — the dashboard is a static analysis tool. It does not connect to TastyTrade's API.

---

## Changelog

See the changelog block at the top of the source file for full version history.

**Current: v25.6** — FIFO short equity fix, LEAPS handling, naked long classification, timezone architecture unification, full code review pass.

---

## License

MIT — do what you like with it, no warranty implied.
