# 📟 TastyMechanics v24

**Personal TastyTrade analytics dashboard built with Streamlit and pandas.**

Upload your TastyTrade transaction history CSV and get a comprehensive breakdown of your options trading — wheel campaigns, roll chains, strategy performance, and premium selling metrics. Built around TastyTrade mechanics and terminology, not generic broker analytics.

No subscription. No data leaves your machine. Drop in your CSV and go.

---

## Screenshots

> *Upload your TastyTrade CSV to see your dashboard*

---

## Features

### 📊 Portfolio Overview
- Realized P/L, Realized ROR, Capital Deployed, Margin Loan, Dividends + Interest, Account Age
- Cumulative P/L sparkline that updates with the selected time window
- Realized P/L breakdown — closed campaigns, open campaign premiums, standalone trades

### 🎯 Wheel Campaign Tracker
- Automatically detects wheel campaigns from your share purchase/sale history
- Tracks blended cost basis across multiple share purchases (DCA)
- Calculates **effective basis per share** — your entry price minus all premiums collected
- Shows how much premium has reduced your break-even over time
- **Option roll chains** — groups related covered calls and puts into chains, showing each roll within a campaign
- Calls and puts tracked as separate chains — covered strangles appear as two parallel chains, making it easy to see when you leg out of one side
- **Lifetime mode** — combines all history for a ticker into one continuous campaign
- Campaign cards showing key metrics at a glance, with expandable detail for chains and share events

### 📈 Derivatives Performance
- **Premium Selling Scorecard** — Win Rate, Median Capture %, Median Days Held, Median Ann. Return, Med Premium/Day, Actual $/Day (gross and net)
- **Call vs Put Performance** — compares your call and put trading side by side
- **Defined vs Undefined Risk by Strategy** — see which structures are actually working
- **Performance by Ticker** — Win %, Total P/L, Median Days, Median Capture %, Median Ann. Return, Total Credit Received
- Cumulative P/L equity curve and rolling capture % chart
- Best 5 and Worst 5 trades
- Colour-coded Win % cells (green ≥70%, amber 50–69%, red <50%)
- Time window filter — All Time, YTD, Last 5 Days, Last Month, Last 3 Months, Half Year, 1 Year

### 📡 Open Positions
- Full open positions table with strategy detection
- Shows current exposure across all open options and share positions

### 🔍 All Trades (Realized P/L)
- Ticker-level P/L summary across all wheel campaigns
- Drills into each campaign's contribution

### 💰 Income & Fees
- Deposits, withdrawals, dividends, interest, regulatory fees
- Net cash flow overview

---

## Strategy Detection

TastyMechanics automatically identifies 19 trade structures from your transaction history:

| Undefined Risk | Defined Risk | Directional |
|---|---|---|
| Short Put | Put Credit Spread | Long Call |
| Short Call | Call Credit Spread | Long Put |
| Covered Call | Iron Condor | Long Strangle |
| Short Strangle | Put Debit Spread | Call Butterfly |
| Short Straddle | Call Debit Spread | Put Butterfly |
| Covered Strangle | Calendar Spread | Jade Lizard |
| Covered Straddle | | |

Equity options and **futures options** (`/MES`, `/ZS`, `/GC` etc.) are both supported.

---

## Installation

**Requirements:** Python 3.9+

```bash
# Clone the repo
git clone https://github.com/yourusername/tastymechanics.git
cd tastymechanics

# Install dependencies
pip install streamlit pandas plotly

# Run
streamlit run Tastytrade_CSV_Dashboard.py
```

Then open `http://localhost:8501` in your browser.

---

## Usage

1. Log in to TastyTrade
2. Go to **History** → export your transaction history as CSV
3. Open TastyMechanics in your browser
4. Upload the CSV using the sidebar uploader
5. Adjust campaign settings if needed (minimum shares threshold, lifetime mode)
6. Select your time window from the sidebar

### Campaign Settings

| Setting | Default | Description |
|---|---|---|
| Min Shares for Campaign | 100 | Minimum share purchase to start a wheel campaign |
| Lifetime Mode | Off | Combines all history for a ticker into one campaign rather than resetting when shares hit zero |

---

## How Metrics Are Calculated

### Effective Basis
```
Effective Basis/sh = (Total Share Cost − All Premiums Banked) / Shares Held
```
Premiums from covered calls, short puts, and covered strangles are all credited against your cost basis. The lower your effective basis, the more your wheel is working.

### Capture %
```
Capture % = Net P/L / Opening Credit × 100
```
TastyTrade targets closing credit trades at 50% of max profit. A Capture % of 50% means you collected half the premium and closed the position. Higher means you let it run longer; lower means you took profits early.

### Actual $/Day (gross vs net)
- **Gross** = Total credit received on closed trades ÷ days in selected window. Cash that flowed into your account when opening positions.
- **Net** = Total P/L ÷ days in selected window. What you actually kept after all buybacks. The honest number for income planning.

### Median vs Mean
All capture %, days held, DTE, and premium/day metrics use **median** rather than mean throughout. A single 0DTE trade or one large strangle rolled for a big debit would skew averages significantly — median gives you the typical trade.

### Roll Chains
Options are grouped into chains based on same-day or near-same-day activity (within 3 days). A covered call sold, bought back, and re-sold the next day stays in one chain showing the full roll history. A gap of more than 3 days starts a new chain.

---

## Notes & Limitations

- **Covered strangles** appear as two separate chains (one call, one put). This is intentional — it makes it easy to see when you leg out of one side independently.
- **Complex structures inside a campaign** (PMCC, Diagonals, Iron Condors, Butterflies) are not fully decomposed in the chain view. Their P/L is correct in the campaign total, but chains may show as fragments.
- **Defined vs Undefined Risk** classification may be approximate for trades where legs were opened separately at different times (e.g. a covered call and a short put added days apart).
- **Med Ann. Return** is capped at ±500% to prevent 0DTE trades from producing meaningless annualised figures. Treat this metric cautiously for tickers with few trades.
- The dashboard is designed for **NZ date formatting** (DD/MM/YYYY) throughout.

---

## Testing with Synthetic Data

A synthetic CSV generator is included for testing without using real account data:

```bash
python3 generate_tastytrade_csv.py
```

This produces `tastytrade_synthetic_sample.csv` with 179 rows covering:
- 3 wheel campaigns (NVDA, MSTR, PLTR) including assignment, rolling, and a covered strangle
- Short puts, strangles, spreads, iron condors, butterfly, 0DTE index trades
- Futures options (/MES, /GC)
- Deposits, dividends, interest, regulatory fees

---

## Built With

- [Streamlit](https://streamlit.io) — dashboard framework
- [pandas](https://pandas.pydata.org) — data processing
- [Plotly](https://plotly.com/python/) — charts

---

## Roadmap

- [ ] P/L heatmap by ticker and month
- [ ] Roll chain timeline visualisation
- [ ] Win/loss distribution histogram
- [ ] Trade log with filters
- [ ] Mobile-friendly layout

---

## Contributing

Pull requests welcome. If you find a bug with a specific TastyTrade CSV structure or trade type, open an issue with a anonymised sample of the relevant rows.

---

## Disclaimer

TastyMechanics is a personal analytics tool. It is not affiliated with or endorsed by Tastytrade Inc. All calculations are for informational purposes only and should not be considered financial advice. Always verify your own numbers.

---

*Built for theta gang traders who want to understand their wheel, not just run it.*
