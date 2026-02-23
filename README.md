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
- **Sparkline equity curve** — visual P/L trajectory across the window
- **Realized P/L Breakdown** — Options / Equity / Campaign split

### ⏰ Expiry Alert Strip
Chips showing every open option expiring within 21 days, colour-coded:
- 🟢 Green — more than 14 days
- 🟡 Amber — 7–14 days
- 🔴 Red — 5 days or fewer

### 📅 Period Comparison Card
Side-by-side comparison of the current window vs the prior equivalent window:
- Realized P/L, Trades Closed, Win Rate, Dividends — each with a +/- delta
- Automatically mirrors your selected time window (e.g. Last Month vs the month before)
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
- **Defined vs Undefined Risk** — by strategy
- **Performance by Ticker** table
- **Options P/L by Week & Month** — colour-coded bar charts (options trades only)
- **P/L by Ticker & Month** heatmap
- **Cumulative Realized P/L** curve
- **Rolling Avg Capture %** (10-trade window) with 50% target line
- **Win/Loss Distribution** histogram with median annotation
- **Best 5 / Worst 5 trades**
- **Full Closed Trade Log** (expandable)

### Tab: 🎯 Wheel Campaigns
- Tracks each share-holding period as a campaign — entry → covered calls/strangles → exit
- **Effective basis** — blended cost reduced by premiums and dividends banked
- **Campaign summary table** — Qty, Avg Price, Effective Basis, Premiums, Divs, P/L, Days
- **Roll chain view** — each covered call chain broken into legs with strike, DTE, cash flow
- Open chains highlighted in green; closed chains show roll count and net P/L
- **Share & Dividend Events** log per campaign
- Toggle: **Lifetime "House Money" mode** — combines all history into one campaign

### Tab: 🔍 All Trades
- Realized P/L summary across all tickers — Wheel and Standalone
- **Total Realized P/L by Week & Month** — whole portfolio bar charts using true FIFO equity P/L (share purchases excluded, share sales counted at net gain/loss vs cost basis)

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

**FIFO equity accounting** — when you sell shares, the oldest lot is consumed first. Partial lot splits are handled correctly. Pre-window purchases are tracked so cost basis is always accurate regardless of when the time window starts.

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

---

## Wheel Campaign Logic

A **campaign** starts when you buy 100+ shares of a ticker. It tracks:
- All covered calls, covered strangles, and short puts written against the position
- All dividends received during the holding period
- The final share sale (if closed)

Effective basis = `(Cost of shares − Premiums banked − Dividends received) ÷ Share count`

Campaigns reset when shares hit zero. Use **Lifetime mode** (sidebar toggle) to view your full history as one continuous position — useful for seeing your true "house money" basis after years of wheeling the same ticker.

---

## Changelog

### v25.3
- Expiry Alert Strip (21-day window, colour-coded DTE chips)
- Period Comparison Card (current vs prior window, with deltas)
- Options P/L by Week & Month bar charts (Derivatives Performance tab)
- Total Realized P/L by Week & Month bar charts (All Trades tab) — FIFO-correct
- `calculate_daily_realized_pnl()` — daily bucketed FIFO P/L engine for charts
- `calculate_windowed_equity_pnl()` gains `end_date` parameter — fixes prior-period double-counting bug
- Negative currency formatting — `-$308` not `$-308` throughout
- Timezone-safe DTE calculation — handles both date strings and full timestamps from TastyTrade CSV
- Strict `<` boundary on FIFO window — prevents double-counting on exact boundary timestamps

### v25.2
- Open Positions tab fully redesigned — 2-column card grid with inline styles (Streamlit CSS class workaround)
- Strategy badges colour-coded by directional bias
- DTE progress bar per option leg
- `chart_layout()` helper — consistent dark theme, IBM Plex fonts, subtle grid across all charts
- Cumulative P/L, Rolling Capture %, Win/Loss histogram, Heatmap all upgraded

### v25.1
- FIFO cost basis fix — `calculate_windowed_equity_pnl()` using deque, oldest lot first, correct partial lot splits

### v25
- Win/Loss histogram, P/L heatmap by ticker & month
- Time window selector moved to top-right
- Window start capped at first transaction date
- Banked $/Day metric replacing Actual $/Day
- Short window warning
- pandas 2.1+ and Streamlit deprecation fixes

### v24
- TastyMechanics branding
- Sparkline equity curve
- Win % colour coding
- Campaign cards
- Banked $/Day metric

---

## Notes

- **No data leaves your machine** — the CSV is processed entirely in your local Streamlit session
- **Options margin not included** in Capital Deployed — only share positions
- **Assignment and expiration** are handled correctly in campaign and chain tracking
- Complex multi-leg structures (PMCC, Diagonals, Iron Condors) show correct P/L totals in campaigns; the roll chain view may show fragments for these

---

## License

MIT — do whatever you like with it.
