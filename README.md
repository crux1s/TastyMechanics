# 📟 TastyMechanics

A local Streamlit dashboard for analysing your TastyTrade trading history. Upload your account CSV and get a full breakdown of your wheel campaigns, options performance, realized P/L, and income — all in one place.

![Python](https://img.shields.io/badge/Python-3.9+-blue) ![Streamlit](https://img.shields.io/badge/Streamlit-1.30+-red) ![Plotly](https://img.shields.io/badge/Plotly-5.x-purple)

---

## Features

### 📊 Portfolio Overview
- **Realized P/L** — all cash actually banked, filtered to selected time window
- **Realized ROR** — return on net deposits
- **Capital Efficiency** — annualised return on deployed capital vs S&P ~10% benchmark
- **Capital Deployed, Margin Loan, Div + Interest, Account Age**
- **Inline P/L breakdown chips** — always visible below metrics, no expander:
  - *All Time:* Closed Wheel Campaigns · Open Wheel Premiums · General Standalone Trading
  - *Windowed:* Wheel & Options Trading · Equity Sales · Div + Interest
- **Window date label** — blue inline text on every window-sensitive header showing e.g. `24/01/2026 → 23/02/2026 (Last Month)`

### ⏰ Expiry Alert Strip
Chips showing every open option expiring within 21 days, colour-coded:
- 🟢 Green — more than 14 days
- 🟡 Amber — 7–14 days
- 🔴 Red — 5 days or fewer

### 📅 Period Comparison Card
Side-by-side comparison of the current window vs the prior equivalent window:
- Realized P/L, Trades Closed, Win Rate, Dividends — each with a +/- delta
- Automatically mirrors your selected time window
- Hidden on All Time view

---

### Tab: 📡 Open Positions
- **Strategy cards** per ticker — detected strategy badge, per-leg breakdown, cost basis chip
- **DTE progress bar** — green → amber → red as expiry approaches
- **Summary strip** — total tickers, option legs, share positions, active strategy pills
- Strategy detection covers: Covered Call, Covered Strangle, Short Strangle, Short Put, Jade Lizard, Big Lizard, Risk Reversal, Iron Condor, Calendar Spread, Call/Put Butterfly, and more

### Tab: 📈 Derivatives Performance
- **Premium Selling Scorecard** — Win Rate, Median Capture %, Median Days Held, Median Ann. Return, Med Premium/Day, Banked $/Day
- **Avg Winner / Avg Loser / Win-Loss Ratio / Fees analysis**
- **Call vs Put performance** breakdown
- **Defined vs Undefined Risk** — by strategy, full-width
- **Performance by Ticker** table
- **Options P/L by Week & Month** — options trades only (labelled clearly), colour-coded bars
- **Cumulative Realized P/L** curve
- **Rolling Avg Capture %** (10-trade window) with 50% target line
- **Win/Loss Distribution** histogram with median annotation
- **P/L by Ticker & Month** heatmap — sits below Win/Loss Distribution
- **Best 5 / Worst 5 trades**
- **Full Closed Trade Log** — with **How Closed** column (⏹️ Expired / 📋 Assigned / 🏋️ Exercised / ✂️ Closed), sortable date columns

### Tab: 🎯 Wheel Campaigns
- Tracks each share-holding period as a campaign — entry → covered calls/strangles → exit
- **Effective basis** — blended cost reduced by premiums and dividends banked (post-purchase only)
- **Campaign summary table** — Qty, Avg Price, Effective Basis, Premiums, Divs, P/L, Days
- **Roll chain view** — each covered call chain broken into legs with strike, DTE, cash flow
- Open chains highlighted in green; closed chains show roll count and net P/L
- **Share & Dividend Events** log per campaign
- Toggle: **Lifetime "House Money" mode** — combines all history into one campaign

### Tab: 🔍 All Trades
- Realized P/L summary across all tickers — Wheel and Standalone
- **Sparkline equity curve** — cumulative options P/L over the selected window
- **Total Realized P/L by Week & Month** — whole portfolio FIFO-correct bar charts
  (options + FIFO equity gains/losses + dividends + interest; share purchases excluded)

### Tab: 💰 Income & Fees
- Deposits, Withdrawals, Dividends, Net Interest
- Full income event log filtered to selected time window

---

## How P/L is Calculated

TastyMechanics is careful about what counts as "realized":

| Source | Counted? | Method |
|---|---|---|
| Options credits/debits | ✅ Yes | Full cash flow at close/expiry date |
| Share sales | ✅ Yes | Net proceeds minus **FIFO cost basis** |
| Dividends | ✅ Yes | Cash received on settlement date |
| Interest (net) | ✅ Yes | Credit minus debit interest |
| Share purchases | ❌ No | Capital deployment, not P/L |
| Unrealised share gains | ❌ No | Not included anywhere |
| Pre-purchase options | ✅ Yes | Counted as standalone P/L, **not** credited against campaign basis |

**FIFO equity accounting** — when you sell shares, the oldest lot is consumed first. Partial lot splits are handled correctly. Pre-window purchases are tracked so cost basis is always accurate regardless of when the time window starts.

**Campaign effective basis** — only options traded *after* the share purchase date are credited against the wheel campaign basis. Options traded before buying shares (e.g. short puts while waiting to get assigned) flow to General Standalone Trading instead.

---

## Getting Started

### Requirements

```
streamlit
pandas
plotly
```

Install with:

```bash
pip install streamlit pandas plotly
```

### Running the app

```bash
streamlit run Tastytrade_CSV_Dashboard.py
```

Then open `http://localhost:8501` in your browser.

### Getting your CSV from TastyTrade

1. Log in to TastyTrade
2. Go to **History** → **Transactions**
3. Set your date range (go back as far as possible for best results)
4. Click **Download CSV**
5. Upload the file in the dashboard sidebar

If you upload the wrong file the app will tell you exactly which columns are missing rather than crashing.

---

## Time Windows

| Window | Description |
|---|---|
| Last 5 Days | Very short — P/L can be misleading (see warning) |
| Last Month | ~30 days |
| Last 3 Months | ~90 days |
| Half Year | ~182 days |
| YTD | 1 Jan to latest transaction |
| 1 Year | ~365 days, capped at first transaction |
| All Time | Full account history |

> ⚠️ **Short window warning** — if a trade was opened in a previous window and closed in the current one, only the buyback cost appears in this window. The original credit is in an earlier window. YTD or All Time give the most reliable P/L picture.

Every window-sensitive section header shows the exact date range in blue: `24/01/2026 → 23/02/2026 (Last Month)`.

---

## Wheel Campaign Logic

A **campaign** starts when you buy 100+ shares of a ticker. It tracks:
- All covered calls, covered strangles, and short puts written **after** the share purchase date
- All dividends received during the holding period
- The final share sale (if closed)

Effective basis = `(Cost of shares − Post-purchase Premiums − Dividends) ÷ Share count`

Options traded on a ticker *before* you buy the shares (e.g. short puts you closed for a profit while waiting for assignment) are correctly classified as **General Standalone Trading**, not credited against your basis.

Campaigns reset when shares hit zero. Use **Lifetime mode** (sidebar toggle) to view your full history as one continuous position.

---

## Changelog

### v25.4
**Bug fixes:**
- Campaign premiums date guard — pre-purchase options no longer reduce effective basis. Real-world fix: SMR corrected from $16.72 → $20.25/share
- `calculate_windowed_equity_pnl()` gains `end_date` parameter — fixes prior-period double-counting of equity sales
- CSV validation — wrong file shows friendly error with missing column list instead of crashing
- Negative currency formatting — `-$308` not `$-308` throughout
- Timezone-safe DTE calculation — handles TastyTrade full timestamp exports
- Full Closed Trade Log date sorting — dates sort chronologically not alphabetically

**New features:**
- **How Closed** column in Full Closed Trade Log: ⏹️ Expired / 📋 Assigned / 🏋️ Exercised / ✂️ Closed
- **Total Realized P/L by Week & Month** charts in All Trades tab — FIFO-correct whole-portfolio view via new `calculate_daily_realized_pnl()` engine
- **Window date label** on all window-sensitive section headers
- **Period Comparison Card** — current vs prior equivalent window with deltas

**Layout & polish:**
- Realized P/L Breakdown expander → inline chip line below metrics
- Sparkline moved to top of All Trades tab
- P/L by Ticker & Month heatmap moved to below Win/Loss Distribution
- Defined vs Undefined Risk table is now full-width (was crammed in col2)
- Options P/L charts clearly labelled as options-only

### v25.3
- Expiry Alert Strip (21-day window, colour-coded DTE chips)
- Options P/L by Week & Month bar charts (Derivatives Performance tab)
- Open Positions redesign — 2-column card grid, strategy badges, DTE progress bars
- `chart_layout()` helper — consistent dark theme across all charts
- IBM Plex Sans + IBM Plex Mono typography

### v25.1
- FIFO cost basis fix — `calculate_windowed_equity_pnl()` using deque, oldest lot first

### v25
- Win/Loss histogram, P/L heatmap by ticker & month
- Time window selector moved to top-right, capped at first transaction date
- Banked $/Day metric, short window warning
- pandas 2.1+ and Streamlit deprecation fixes

### v24
- TastyMechanics branding, sparkline equity curve
- Win % colour coding, campaign cards, Banked $/Day metric

---

## Notes

- **No data leaves your machine** — the CSV is processed entirely in your local Streamlit session
- **Options margin not included** in Capital Deployed — only share positions
- **Assignment and expiration** are handled correctly in campaign and chain tracking
- Complex multi-leg structures (PMCC, Diagonals, Iron Condors) show correct P/L totals in campaigns; the roll chain view may show fragments for these

---

## License

MIT — do whatever you like with it.
