<p align="center">
  <img src="icon.png" width="120" alt="TastyMechanics icon"/>
</p>

# 📟 TastyMechanics

A Streamlit dashboard for **theta and wheel strategy traders** on TastyTrade. Built around premium selling — short puts, covered calls, strangles, and the wheel — with metrics that matter for multi-day holds: capture %, daily theta yield, banked $/day, effective basis, and campaign tracking.

Upload your CSV export and get a full breakdown of realized P/L, wheel campaigns, trade analytics, and portfolio health — all running locally or on Streamlit Community Cloud. Your data is never sent anywhere.

> **Heads up for 0DTE traders:** the app works but some metrics (Med Premium/Day, Wheel Campaigns) are less meaningful for same-day trades. 0DTE-specific analytics are on the roadmap.


> **Personal project.** TastyMechanics is built around how I trade — wheel strategies, theta harvesting, and premium selling on TastyTrade. It works well for my account and my style. It may not fit yours out of the box, and that is intentional. If you trade differently — 0DTE, futures, spreads-heavy, non-US — the numbers may not tell the full story. You are welcome to fork the repo and customise it to match your trading style. The codebase is modular by design: analytics live in `mechanics.py`, display in `tabs/`, constants in `config.py`. Changing a metric or adding a new one is usually a small, contained change.

---

## Welcome Screen

![Welcome Screen](https://github.com/crux1s/TastyMechanics/blob/main/docs/SS.png?raw=true)

![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![Streamlit](https://img.shields.io/badge/streamlit-1.31%2B-red) ![License](https://img.shields.io/badge/license-AGPL--3.0-blue)

<a href="https://www.buymeacoffee.com/Cruxis" target="_blank">
  <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="45">
</a>

---

## Try it online

Hosted on Streamlit Community Cloud — upload your CSV and explore without installing anything:

https://tastymechanics-76dxruw38qjhqc2bdxgfrc.streamlit.app/

---

## Features

**Open Positions tab**
- Position cards per ticker: strategy badge, DTE progress bar, cost basis per leg
- Live market prices via Yahoo Finance (opt-in toggle) — last price, day change %, mark (bid/ask) for each option leg, unrealised P/L per leg and card total
- Per-share unrealised breakdown on stock legs (e.g. `-$620.08 / -$6.20/sh`)
- % of premium captured on single-leg short options (e.g. `23% captured`)
- Spread context row for vertical spreads — net credit/debit, max loss/profit, % of max profit
- Strategy detection covers Iron Condor, Reverse Iron Condor, Iron Butterfly, Reverse Iron Butterfly, Jade Lizard, Big Lizard, Short Strangle, Risk Reversal, vertical spreads, butterflies, calendars, covered structures
- Expiry alert strip — all options expiring within 21 days, colour-coded by urgency
- Wheel Campaign basis strip — cost-basis summary per active campaign
- **Position Snapshot** download button — generates a plain-text snapshot with live marks, IV, Black-Scholes Greeks (Δ, Γ, θ, ν), OTM/ITM distance, open P/L, and portfolio-level metrics (net Δ/Γ/θ/ν, beta-weighted delta to SPY) ready to paste into any LLM for a position review

**Portfolio Overview**
- Realized P/L, Return on Capital, Capital Efficiency Score (annualised)
- Capital deployed, margin loan, dividends + interest
- Inline P/L breakdown chips (campaign type and windowed components)
- Period comparison card — current vs prior equivalent window with deltas

**Derivatives Performance tab**
- Premium selling scorecard: win rate, median capture %, median days held, median premium/day, banked $/day, **Med Daily θ %** (entry quality score — credit ÷ DTE-at-open ÷ capital)
- Avg winner / loser, win/loss ratio, total fees and fees as % of P/L
- Call vs Put performance table
- Defined vs Undefined Risk breakdown by strategy
- Performance by ticker table — includes **Daily θ %** per ticker (median entry quality)
- DTE at open distribution, rolling win rate chart
- Options P/L by week and month (candlestick — shows equity curve OHLC per period)

**Discipline & Patterns tab**
- ThetaGang scorecard: management rate, median DTE at open/close, top-3 concentration, assignment rate, early management rate
- LEAPS automatically separated from short-premium metrics (DTE > 90 threshold)
- Cumulative P/L equity curve, weekly and monthly candlestick curves
- DTE Discipline section — win rate and avg P/L by DTE at open, close distribution with TastyTrade target zone
- Trade Quality section — win/loss P/L histogram, rolling 10-trade capture % and win rate
- Timing & Concentration — P/L by day of week and hour, ticker × month heatmap
- Best/Worst 5 trades and full closed trade log — includes **Daily θ %** column (entry quality, coloured green/orange/red)

**Wheel Campaigns tab**
- Per-ticker campaign cards: entry basis, effective basis, premiums banked, realised P/L, live price strip
- Held-share basis stays honest after a call-away — a below-basis partial exit shows the FIFO cost of the shares you still hold, not the sold lot's cost carried forward (display only; P/L unchanged)
- **Net (MTM)** — summary-table column and card chip showing each open campaign's P/L if closed at the live price, so a premium-green but underwater wheel reads true (📡 Live only)
- **"Days to Free"** — projected days until effective cost basis reaches $0 at current premium/dividend rate
- Pre-purchase option attribution note when pre-campaign closing debits affect the premium total
- Option roll chain visualisation — calls and puts tracked as separate chains
- Share and dividend event log per campaign — call-aways are labelled with the assigned strike
- Lifetime "House Money" mode toggle (in-tab, right of heading)

**Portfolio Realized P/L tab**
- Full ticker breakdown: premiums, dividends, options P/L, capital deployed
- **Stacked cash-flow bar charts** by week and month — Options / Equity / Income breakdown
- Volatility metrics: avg week P/L, weekly std dev, Sharpe-equivalent, profitable weeks %, max drawdown + recovery

**Deposits, Dividends & Fees tab**
- Full income and cash movement log with colour-coded row types

**HTML Report Export**
- Download button in sidebar generates a self-contained, interactive fintech dark-theme dashboard (`#111827` bg, teal brand, Inter font) — no Streamlit, no Plotly, no CDN, opens and prints anywhere
- Four tabs: **Overview** (Account Health traffic-lights + full Premium Selling Scorecard with circular progress rings and colour-accented cards), **Performance** (Portfolio Realized P/L curve, weekly/monthly options candlesticks, capture distribution, strategy breakdown, Short Calls vs Short Puts, Performance by Ticker), **Wheel & Discipline** (ThetaGang metrics + Wheel Campaigns table), and **Trade Log** (full closed trade log, same 16 columns as the in-app expander, colour-coded Close Reason badges)
- Hero band shows the headline P/L, a sign-aware shimmer accent, and an **MWR (XIRR) pill** when Long-Term Performance data is available
- Hand-rolled inline-SVG equity curve (with S&P-proxy benchmark overlay and live hover crosshair) and OHLC candlesticks; sortable tables; count-up hero numbers
- Reflects the currently selected time window; no external dependencies

---

## Getting Started (local)

### Requirements

```
python >= 3.10
streamlit >= 1.31
pandas >= 2.0
plotly >= 5.0
yfinance >= 0.2   # optional — only required for live market prices
```

### Install

```bash
pip install -r requirements.txt
```

### Run

```bash
streamlit run tastymechanics.py
```

Then open `http://localhost:8501` in your browser.

### Getting your CSV from TastyTrade

> Don't have a TastyTrade account yet? [Open one here](https://tastytrade.com/welcome/?referralCode=NT57Z3P85B) — this app was built and tested exclusively on TastyTrade exports.

1. Log in to TastyTrade
2. Go to **History → Transactions**
3. Set your date range — **export your full account history, not just a recent window**
4. Click **Download CSV**
5. Upload the file in the dashboard sidebar

> **Why full history matters:** FIFO cost basis for equity P/L requires all prior buy transactions to be present, even if the shares were purchased years ago. A partial export will produce incorrect basis and P/L figures for any position that has earlier lots outside the selected date range.

---

## Deploying to Streamlit Community Cloud

1. Fork this repository
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub
3. Click **New app** → select your fork → set main file to `tastymechanics.py`
4. Deploy — no secrets or environment variables required

---

## Docker

A standard Python slim image works. Ensure Python 3.10+ is used:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
EXPOSE 8501
CMD ["streamlit", "run", "tastymechanics.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

> **Note:** Python 3.10 and 3.11 are supported. Python 3.12 is recommended.

---

## Disclaimer

This tool is for personal record-keeping only. It is not financial advice.

**Known limitations — verify these manually if they apply to your account:**

- **Covered calls assigned away** — if your shares are called away by assignment, verify the campaign closes and P/L records correctly.
- **Multiple assignments on the same ticker** — each new buy-in starts a new campaign. Blended basis across campaigns is not combined.
- **Long options exercised by you** — exercising a long call or put into shares is untested. Check the resulting position and cost basis.
- **Futures options delivery** — cash-settled futures options (/MES, /ZS etc.) are included in P/L totals, but in-the-money expiry into a futures contract is not handled.
- **Stock splits** — forward and reverse splits are detected and FIFO-adjusted, but TastyTrade-issued post-split option symbols are not stitched to pre-split contracts.
- **Spin-offs and zero-cost deliveries** — shares received at $0 cost (spin-offs, ACATS transfers) trigger a warning. A sidebar toggle lets you exclude those tickers from all P/L metrics so the inflated basis doesn't distort Realized ROR or Capital Efficiency.
- **Mergers and acquisitions** — if a held ticker is acquired or merged, the original campaign may be orphaned with no exit recorded and incomplete P/L. Reconcile manually against your broker statement.
- **Complex multi-leg structures** — PMCC, diagonals, calendars, and ratio spreads may not be classified correctly in the trade log. P/L totals are correct; trade type labels may not be.
- **Non-US accounts** — built and tested on a US TastyTrade account. CSV format and field differences for other regions are unknown.

P/L figures are cash-flow based (what actually hit your account) and use FIFO cost basis for equity. They do not account for unrealised gains/losses, wash sale rules, or tax adjustments. Always reconcile against your official TastyTrade statements for tax purposes.

---

## Architecture

The codebase is split into focused modules with a strict one-way dependency chain. No module imports from the one above it.

```
config.py          Constants + COLOURS palette — OPT_TYPES, TRADE_TYPES, thresholds, patterns
models.py          Dataclasses — Campaign, AppData, ParsedData
ingestion.py       CSV parsing — pure Python, no Streamlit dependency
mechanics.py       Analytics engine — FIFO, campaigns, trade classification
ui_components.py   Visual helpers — formatters, colour functions, chart layout
market_data.py     Live price fetcher — yfinance wrapper, 5-min cache, opt-in only
report.py          HTML report export — self-contained, no Streamlit dependency
tabs/              One renderer per tab (tab0–tab5) + landing.py — imported by tastymechanics.py
tastymechanics.py  Streamlit wiring — sidebar, cache wrappers, tab orchestration
```

**Data flow**

```
CSV upload
  └── load_and_parse(_file_bytes)        cached on raw bytes — reruns only on new file
        └── build_all_data(_parsed, use_lifetime)
                                          cached on use_lifetime bool only (DataFrame unhashed)
              └── window slices recomputed on time window change (fast, uncached)
```

See the [Architecture wiki page](https://github.com/crux1s/TastyMechanics/wiki/Architecture) for full detail.

---

## Changelog

**v26.26 — Honest held-share basis after a call-away, and a Net (MTM) view** (2026-08-23)
- **A below-basis call-away no longer inflates the displayed cost basis.** With the carry-full-cost convention, a partial exit inside an open wheel left the *sold* lot's cost riding on the shares you still hold — so after 100 of 200 SOFI shares were called away at $18, the campaign's cost basis read **$47.88** when the 100 shares actually held cost ~$26. The Wheel card + summary table, the Open-Positions basis strip, the HTML report, and the AI snapshot now show the FIFO cost of the shares **still held** (**$26.05** gross / **$18.35** after premiums). `blended_basis` / `total_cost` stay carry-full internally, so P/L, mark-to-market, capital, and the Overview↔chart reconcile are byte-identical — this is a display fix only. New `Campaign.remaining_lot_cost` field and `remaining_lot_basis()` helper.
- **Called-away shares are now labelled.** A share sale whose timestamp matches a CALL assignment reads **"Sold 100 @ $17.95/sh (Called away — $18 Call)"** in the Share & Dividend Events log, instead of a bare "Sold" line that didn't read as an assignment. Put assignments (share *buys*) never match, so entries are unaffected.
- **New Net (MTM) column and split P/L chip** on the Wheel tab (📡 Live prices only). An open campaign's green premiums-only "Realized P/L" hides that it can be net underwater once the deferred call-away loss and the mark on held shares are folded in. A **Net (MTM)** column in the summary table, plus a card chip that splits into **Premiums Banked** and **Net (MTM)** ("if closed at live"), surface the true result — SOFI reads **+$769.65** banked but **−$1,102** net at $18.91. New pure `campaign_net_mtm()` helper. Both are display-only and appear only with Live on; nothing changes when it's off.
- Test suite at **477 tests** (23 new: remaining-lot basis, call-away labelling, the Net (MTM) guards, and an end-to-end Overview↔chart reconcile guard).

**v26.25 — Option roll chains handle multi-leg spreads** (2026-08-12)
- **The Wheel-tab roll chain now shows every leg of a spread and marks the long wings.** Previously the chain engine modeled pure short-premium rolls: it dropped long opens entirely and tracked a single net count, so a debit-spread-plus-short-call laid over a wheel (e.g. RKLB long 70 / short 75 / short 90) rendered wrong — the long leg's open was invisible, its close showed orphaned, and one of the short buybacks got dropped. Legs are now classified by direction (open/close × quantity sign) with short and long tracked separately, so nothing is dropped and long wings are labeled **🔷 · long wing** with a distinct row tint.
- Display-only — P/L, effective basis, and campaign totals were always correct and are unchanged (all legs were already in campaign premiums). The two duplicated chain-render blocks were consolidated into one shared helper. Test suite at **454 tests** (8 new for spread chains).

**v26.24 — MTM figure on Wheel Cap Efficiency** (2026-07-27)
- **Wheel Cap Efficiency now shows a mark-to-market companion** when the Wheel tab's 📡 Live prices toggle is on. The tile keeps the realized premium-yield % (annualised premium + dividend income on deployed capital), and a line beneath adds unrealised share P/L on top — so a position that's collected lots of premium but is underwater no longer reads as a high-efficiency winner. Red when negative, green when positive; disappears when Live is off (nothing changes without live prices).
- Uses the same blended-basis mark as the Overview MTM pill, so the two views are consistent. Realized number and all totals are unchanged.

**v26.23 — Assigning put's credit folds into the wheel campaign** (2026-07-27)
- **Entry-via-assignment campaigns now credit the assigning put against basis.** When the first shares of a ticker arrive via put assignment, that put's premium is the first rung of the wheel — it now reduces the campaign's effective basis and shows in premiums banked, matching how wheel traders think ("basis = strike − put premium − call premiums"). Previously it sat in a separate pre-purchase bucket and only surfaced via the lifetime/House-Money toggle, making basis and "Days to Free" read worse than reality.
- **Portfolio totals are unchanged** — the credit *moves* buckets (into campaign premiums, out of standalone options P/L), it isn't newly added, so Realized P/L, ROR, MWR, and the Portfolio-tab chart are byte-identical. The now-obsolete "put credit is in pre-purchase P/L / not in Cost Basis" card banner is removed.
- The House-Money toggle no longer changes *whether* the assigning put counts against the position (non-lifetime and lifetime now agree) — it only toggles the equity component, as intended. Rolled-put caveat unchanged: only the final assigned contract's credit folds in.
- New `Campaign.assignment_option_symbols` field (excluded from `pure_options_pnl` to keep the total balanced). Test suite at **446 tests**.

**v26.22 — Stricter open-position strategy classification** (2026-07-22)
- **Butterfly labels no longer misfire on covered / ratio structures.** The open-position strategy classifier (`detect_strategy`) tagged any 3-strike, 1-expiry structure with the right leg counts as a butterfly — even a covered call plus an unrelated call spread (e.g. 100 shares + long 70 / short 75 / short 90 calls, which was showing as "Short Call Butterfly"). Butterfly detection now requires an options-only position (no stock) and the long/short body leg to sit on the **middle** of the three strikes. The RKLB-style position now correctly reads as a **Covered Call Ratio Spread**.
- **Unclassifiable positions now say "Custom/Mixed" instead of guessing.** The single-leg fallbacks (Short Put / Short Call / Long Call / Long Put / Long Stock) previously fired even when *other* unmatched legs were present, labelling a mixed position by one leg and hiding the rest. They now fire only for a homogeneous position; a genuinely unrecognised combination (a diagonal, stock plus an unmatched long option, etc.) falls through to Custom/Mixed.
- Display-only change; P/L and campaign accounting were never affected. Test suite at **444 tests** (7 new guarding the misclassifications).

**v26.21 — Overview Realized P/L reconciles with the Portfolio-tab chart** (2026-07-22)
- **All-Time Realized P/L now matches the Portfolio-tab chart.** The Overview headline used campaign accounting, which defers the equity P/L of a partial share sale inside a still-open wheel until the campaign closes; the chart books it via FIFO on the sale date. The two disagreed by exactly that deferred amount (on the sample book, −$381.72 from a partial RKLB sale). The headline — and the Realized ROR, Capital Efficiency, money-weighted return, HTML report, and position snapshot derived from it — now recognizes that settled equity, so the first-glance number equals the chart and your broker's realized figure.
- **New "Open Wheel Share Sales" breakdown chip** on the All-Time Overview makes the reconciliation visible.
- **Wheel campaign cards and Mark-to-Market are unchanged.** The card keeps the carry-full-cost basis convention (equity settles at campaign close), and the MTM number is held byte-identical — the reconciled term is netted back out where it would otherwise double-count against the carry-full basis.
- New pure helper `open_campaign_equity()` in `mechanics.py`. Test suite at **437 tests** (6 new in section 31 covering the reconciliation invariant, closed-only tickers, and no-sale open campaigns).

**v26.20 — Odd-lot shares now count in wheel campaigns** (2026-07-18)
- **Odd-lot buys fold into campaigns** — share purchases below 100 while no campaign is open are pooled and folded into the next qualifying entry, so the campaign share count matches your broker position. Previously they were silently ignored while sales still deducted full quantities: 5 shares held + 100 assigned − 13 sold showed 87 shares instead of 92, and the odd shares' cost was missing from the campaign (future closed-campaign P/L would have been overstated by that cost).
- **Mid-campaign top-ups of any size now register as Adds** — e.g. buying 8 shares to get back to a covered 100-lot blends into basis; the old ≥100 gate ignored them.
- **Accumulation entries start campaigns** — cumulative buys crossing 100 (e.g. 60 + 60) now open a campaign; the wheel-ticker scan matches (cumulative bought shares, not a single 100-lot row).
- Campaign `start_date` stays the qualifying-entry date, so option-premium windowing and outside-window P/L bucketing are unchanged. Partial sales keep the existing carry-full-cost basis convention.
- Test suite at **431 tests** (17 new in section 30 covering pool fold-in, sub-threshold pools, small adds, pre-campaign pool sales, and accumulation entries).

**v26.19 — WealthUIUX-inspired scorecard rings, icons, card accents, badge colours** (2026-06-26)
- **Circular SVG progress rings** on the Win Rate, Median Capture %, Net Prem Kept %, and Fees % scorecard cards in the HTML export — pos/neg/neutral colour scheme (emerald/rose/teal), pure SVG `stroke-dasharray` arc, no charting library.
- **Emoji icon + ring/icon layout** on every scorecard metric card (`.mcard-r` flex layout) for quicker visual scanning.
- **Left-border colour accents** on section cards — teal on the Scorecard and Per-Ticker table, amber on Strategy Performance, emerald on Wheel Campaigns.
- **Colour-coded Close Reason badges** in the Trade Log tab — emerald for Expired, amber for Assigned/Exercised, gray for Closed.
- Strategy Performance and Wheel Campaigns table headings/values centred for readability.

**v26.18 — HTML export: Trade Log tab, hero MWR pill, Mixed-card fix, theta-engine styling** (2026-06-26)
- **Trade Log tab** in the HTML dashboard export — a faithful port of the app's "Full Closed Trade Log" expander (same 16 columns, same order, most-recent-close-first default sort), horizontally scrollable so the wide table never clips.
- **Hero MWR pill** — surfaces the money-weighted return (XIRR) from `portfolio_metrics()` via a new trailing optional `portfolio_perf` kwarg on `build_html_report()`. Prefers mark-to-market MWR over realized when the Live toggle supplied it; renders `—` rather than a fabricated 0.0% when XIRR is undefined.
- **Mixed-card fix** — Short Calls vs Short Puts now gives Mixed credit trades (strangles, straddles, jade lizards) their own labelled card instead of silently duplicating "Short Puts".
- **Styling pass** — gradient-clipped wordmark, sign-aware hero P/L number, shimmer accent bar and soft accent glow on the hero card, active-tab underline glow.

**v26.17 — Long-Term Performance panel (money-weighted return)** (2026-06-12)
- **New "🏁 Long-Term Performance" section in the Portfolio P/L tab** — account-lifetime metrics that answer "how is the whole portfolio doing over time": **MWR (XIRR)** as the headline, **CAGR** on deposited capital, **Max Drawdown** ($/%/recovery), **Calmar**, **% Profitable Months**, plus a monthly realized-P/L bar chart.
- **MWR = money-weighted return (XIRR)** via a hand-rolled bisection solver (pure stdlib, no numpy/scipy). Cash flows are your dated deposits/withdrawals; the terminal value is `net deposited + realized P/L`, switching to a mark-to-market value (adding open-position unrealized P/L) when the Live price toggle is on. Returns nothing rather than a fabricated number when undefined (no deposits, unbracketed root).
- **TWR and a true Sharpe are intentionally not shown** — both need a daily account-value (NLV) series a transactions CSV doesn't contain. Documented in Known-Limitations / ROADMAP rather than approximated, consistent with the project's metric-honesty stance.
- New pure helpers `xirr()` and `portfolio_metrics()` in `mechanics.py`; `XIRR_*` solver constants in `config.py`. Test suite at **414 tests** (26 new in section 29 covering XIRR with known answers, CAGR, max drawdown, monthly stats, MTM terminal, and a real-CSV smoke).

**v26.16 — HTML report rebuilt as an interactive dashboard** (2026-06-12)
- **`report.py` is now a self-contained tabbed dashboard** — the HTML export was rewritten from a flat single-scroll report into a three-tab layout (Overview / Performance / Wheel & Discipline) with a pinned hero P/L band. Overview carries Account Health traffic-lights + the full Premium Selling Scorecard; Performance holds the Portfolio Realized P/L curve, weekly + monthly options candlesticks, capture distribution, strategy breakdown, Short Calls vs Short Puts, and Performance by Ticker; Wheel & Discipline holds ThetaGang metrics + the Wheel Campaigns table.
- **Hand-rolled inline-SVG charts — no Plotly, no CDN** — the equity curve (with the 10%/yr S&P-proxy benchmark and a live hover crosshair) and the weekly/monthly OHLC candlesticks (cumulative options P/L by close date, matching the in-app Tab 2 logic) are drawn directly in SVG. The report now has zero charting-library or network dependency and opens/prints anywhere.
- **Interactive, still a single file** — count-up hero numbers, animated capture bars, sortable strategy/ticker/campaign tables, and per-tab lazy chart rendering, all in vanilla JS embedded in one HTML document.
- **`build_html_report()` signature unchanged** — derives a single `DATA` dict from the arguments it already receives (`_dashboard_data()`); ThetaGang management rate comes from `Close Reason` and concentration from premium-by-ticker, so no new inputs were needed. The Streamlit "Download HTML Report" button is untouched and now yields the dashboard for the uploaded CSV and selected window.
- Test suite unchanged at **388 tests** (`report.py` has no direct tests; the end-to-end smoke check and full import chain pass).

**v26.15 — Covered-call capital base: stock basis, not premium** (2026-06-11)
- **Covered-call Capital at Risk now uses the campaign's average acquisition cost per share × 100** — the stock actually pinned by the position, on the same scale as a CSP's strike × 100. The v26.12 premium-as-capital interim fix made `Daily θ %` degenerate to `100 ÷ DTE` (the premium cancels out of credit ÷ DTE ÷ capital) and pegged `Ann Return %` at ±500% on virtually every covered call. With covered calls at 38% of the book, the scorecard's Med Daily θ % was reading ~2.2%/day — an artifact of DTE choice, not entry quality. It now reads ~0.13%/day, back in the regime the green/orange thresholds (0.10% / 0.05%) were calibrated for, and directly comparable to short-put yields. For context, tastylive guidance: portfolio theta ≈ 0.1–0.5% of net liq per day; CSP entry yield ≈ 0.03–0.07%/day on committed capital.
- **New `Campaign.shares_acquired` field** — cumulative shares bought (split-adjusted, never reduced by sales), so `total_cost ÷ shares_acquired` survives campaign close where `blended_basis` is zeroed. `compute_app_data` builds a `campaign_basis` dict from it and threads it through `build_closed_trades` → `_calculate_capital_risk`. Premium-as-capital remains as the fallback when no basis is supplied (e.g. direct calls in tests).
- **Windowed Realized P/L chips split open vs closed** — the single "Wheel & Options Trading" chip is now "Options — Closed Trades" plus "Options — Open Positions ⏳" (premium banked, position still open, buyback/expiry lands in a future window), with an inline legend. Stops a heavy premium-selling month from reading as fully locked-in profit.
- Test suite at **388 tests** (7 new in section 28 covering `shares_acquired` survival, stock-basis cap-at-risk, Daily θ % as genuine yield, and the no-basis fallback).

**v26.14 — Documentation, table/chart accuracy audit + HTML report enhancements** (2026-06-07)
- **Help-text and docstring audit** — six accuracy fixes: Realized P/L help now mentions interest; Capital Deployed help says "blended cost basis" not "entry price"; landing-page Tab 1 pitch dropped stale "annualised return" reference; `parse_csv` and `models.py` docstrings updated to reflect the v26.13 `@dataclass` conversion; `mechanics.py` Ann Return % comment pins the per-trade-only intent so a future maintainer can't accidentally re-add the dropped aggregate.
- **Tables and charts audit (5 fixes)** — Tab 1 Call vs Put `Prem/Day` switched to median throughout (was mean per-row but median in totals) and renamed `Med Prem/Day` to match the scorecard; the dead `Time to B/E` column removed from the Wheel summary table (data still surfaced in the per-campaign cards when live prices are on); Lifetime-mode basis columns renamed `Gross /sh` and `Blended /sh` so the same labels don't mean different things across modes; `Exit` column shows `—` instead of `$0.00` on open campaigns; Tab 2 "Cumulative Realized P/L" chart renamed "Cumulative Options Realized P/L" so it doesn't collide with Tab 4's portfolio-wide curve under the same label.
- **Short Calls vs Short Puts** — the in-app Tab 1 heading and HTML report card retitled from `Call vs Put Performance` to `Short Calls vs Short Puts` to make the credit-only scope explicit (every trade in the card is net-short by definition; long/debit trades land in Strategy Breakdown).
- **HTML report — `Call vs Put` and `Strategy Breakdown` split into own cards** — were previously a two-column block inside a single `Trade Breakdown` card; now each gets its own visually distinct section with independent gating.
- **HTML report — Account Health strip** — 4 traffic-light cards at the top of the report (Win Rate, Median Capture %, Net Premium Kept, Win/Loss Ratio) with ✅/⚠️/❌ verdict notes derived from TastyTrade-style thresholds. Lets a reader form the account verdict in 5 seconds without reading 20+ metric tiles.
- **HTML report — DTE Discipline mini-section** — new card between Scorecard and Capture Distribution showing Med DTE at Open, Med DTE at Close, Early Mgmt Rate (% closed at ≥21 DTE), and Assignment Rate. Replicates the Tab 2 ThetaGang scorecard which had no report counterpart.
- **HTML report — Reconciliation strip above footer** — exposes the additive breakdown of the headline Total P/L (Closed Wheel + Open Wheel Premiums + Pure Options + Dividends + Interest) with a `✓` when components match within $0.01 and a flagged warning otherwise. Makes the headline number transparent and debuggable.
- **HTML report — Benchmark overlay on the equity curve** — faint dotted line showing constant 10%/yr growth on net deposited capital (long-run S&P proxy). Deterministic, no network calls, configurable via `benchmark_annual_pct` kwarg.
- **HTML report — Version + CSV fingerprint in footer** — reports now stamp `v26.14 · CSV <md5 first 6> · <timestamp>` so regenerated reports are reproducibly identifiable; if numbers shift later, you can tell whether the data changed or the analytics did.

**v26.13 — Defensive: detect silently-zeroed trade rows** (2026-06-06)
- **Parser-drift early warning** — `parse_csv` now runs `detect_unknown_actions(df)` after `Net_Qty_Row` is computed and surfaces any `Trade` / `Receive Deliver` row whose `Quantity > 0` but `Net_Qty_Row == 0` (i.e. `get_signed_qty()` didn't recognise the Action / Description and silently zeroed the row). Almost always returns `[]` — a non-empty result means TastyTrade may have introduced a new Action enum, a localised export, or the CSV was manually edited. A red banner in the UI flags affected rows so the user can investigate before trusting the resulting P/L.
- **Allow-list for legitimate zero-share rows** — split removals, cash-settled SPX exercises / assignments, and corporate symbol changes are filtered out of the detector (Sub Type fragment match against `_LEGITIMATE_ZERO_SUB_TYPE_FRAGMENTS`). The canonical test CSV has two SPX cash-settled rows that prompted this list.
- **`ParsedData` converted from `NamedTuple` to `@dataclass`** so the new `unknown_action_rows` field can use `field(default_factory=list)` without the shared-mutable-default trap. All existing callers use named-attribute access; no positional unpacking, no breaking change.
- Test suite at **374 tests** (9 new in section 27 covering the detector, the allow-list, the empty-df guard, and a canonical-CSV ground-truth zero check).

**v26.12 — Code-review follow-ups: covered strangle cap-risk, calendar DTE ordering, `_LegInfo` extraction, hot-path speedup** (2026-06-06)
- **Covered strangle / straddle capital-at-risk** — the v26.11 covered-call short-circuit only checked `has_sc and not has_lc`, so a covered strangle (short call + short put inside a wheel) was returning premium-as-risk and ignoring the unhedged put leg. Real exposure is `put_strike × mult − credit`. The branch now splits explicitly: pure covered call uses premium-as-risk; covered strangle/straddle uses put-strike-as-risk less credit. Caught in the v26.11 PR `/code-review` pass.
- **Calendar spread `nearest_exp` ordering** — `build_closed_trades` was picking `exp_dates.iloc[0]` (first row in transaction-Date order), so a calendar spread where the far-month leg opened first reported the wrong expiration. For a far-then-near calendar this overstated `DTE at Open` by ~5× (e.g. 152 days instead of 30) and silently halved Daily θ %. Fixed to `exp_dates.min()`.
- **`_LegInfo` extraction** — ~16 lines of identical prelude (leg partitions, has-sc/sp/lc/lp flags, butterfly/jade-lizard/ratio detection) were duplicated byte-for-byte between `_classify_trade_type` and `_calculate_capital_risk`. CLAUDE.md flagged it as a known drift hazard. Both functions now consume a single `_LegInfo` dataclass built by `_derive_leg_info(grp, opens)` — structure-detection logic has one source of truth and cannot desynchronise.
- **`build_closed_trades` hot-path speedup** — the `all_closed` check re-filtered `equity_opts` once per symbol inside the trade-group loop, O(T × S × E). On the 700-row test CSV this was ~21M row comparisons; on a 5000-row CSV it scaled to ~1.4B. Now precomputes `sym_net_qty = equity_opts.groupby('Symbol')['Net_Qty_Row'].sum().abs()` once before the loop and looks up per symbol — O(E + T×S), roughly 3000× cheaper on real data.
- Test suite at **365 tests** (18 new synthetic-data regression checks in section 26 covering all three fixes plus a `_LegInfo` consistency spot-check).

**v26.11 — Scorecard cleanup: drop Median Ann Return, fix Daily θ %, covered call accounting** (2026-06-06)
- **Dropped Median Ann. Return from the scorecard** — with a mixed weekly/swing book, more than half of credit trades were pegged at the ±500% cap, making the median equal to the cap and conveying no information. The per-trade Ann Ret % column remains on closed-trade tables for sortable inspection; only the aggregates (scorecard tile, per-ticker summary, HTML report) were removed.
- **Daily θ % now uses DTE-at-open instead of days-held** — converts the metric from "what did I earn per day I held it" (which inflated when closing winners fast) into a setup-quality score: "at the moment I opened the trade, what theoretical theta yield was I buying per unit of capital?" Independent of close timing. Median Daily θ % is now the headline trade-quality number alongside Capture %.
- **Covered call capital-at-risk** — `_calculate_capital_risk` now detects shorts opened inside a wheel campaign window and uses the option premium as the capital base, not `max_strike × 100`. The naked-call formula was misrepresenting covered calls as $700–$5,000 of standalone risk.
- **Wheel campaign same-timestamp close** — a stock exit and option BTC sharing the exact order timestamp (sort order placed equity row before option row) caused the BTC to be dropped from the campaign event log and routed to the outside-window options bucket. A `just_closed` reference now captures it on the campaign side, and `pure_options_pnl` uses an inclusive end boundary to avoid double-counting. Visible bug: SOXS covered-call campaign was reporting +$221.67 instead of the correct +$74.55.
- Test suite at **347 tests** (14 new synthetic-data regression checks pinning the same-timestamp close and covered-call cap-at-risk behaviour).

**Earlier releases (v25.12 – v26.10, Mar–Jun 2026)** — HTML report export and fintech dark theme; live Yahoo Finance prices on Open Positions and Wheel Campaign cards; Position Snapshot download (marks, IV, Black-Scholes Greeks, beta-weighted delta); TastyTrade-style date-range picker with custom windows; Daily θ % metric introduced; strategy detection expanded (Iron Condor variants, ratio spreads, Ratio Lizard, vertical-spread fixes); per-ticker P/L redesign with Options / Equity / Income split; stacked cash-flow charts and candlesticks; "Days to Free" estimate on campaign cards. v25.3 – v25.11 covered the initial modular refactor (mechanics.py, ingestion.py, tabs/, config.py), FIFO engine fixes, stock split handling, LEAPS separation, and the test suite build-out. Full notes in the git log.

---

## License

[AGPL-3.0](./LICENSE) — free to use, modify, and distribute. If you run a modified version as a public web service you must open source your changes under the same licence.

---

## Support the Project

TastyMechanics is free and open source. If it's saved you time or helped you trade smarter, a coffee goes a long way toward covering the 5-sigma moves.

<a href="https://www.buymeacoffee.com/Cruxis" target="_blank">
  <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="50">
</a>
&nbsp;&nbsp;
<a href="https://tastytrade.com/welcome/?referralCode=NT57Z3P85B" target="_blank">
  <img src="https://img.shields.io/badge/Open%20a%20TastyTrade%20Account-1a1a2e?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0iI2ZmNjYwMCIgZD0iTTEyIDJDNi40OCAyIDIgNi40OCAyIDEyczQuNDggMTAgMTAgMTAgMTAtNC40OCAxMC0xMFMxNy41MiAyIDEyIDJ6bTEgMTVoLTJ2LTZoMnY2em0wLThoLTJWN2gydjJ6Ii8+PC9zdmc+" alt="Open a TastyTrade Account" height="35">
</a>
