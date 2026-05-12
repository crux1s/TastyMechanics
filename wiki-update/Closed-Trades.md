# Closed Trades

The closed trades table pairs every opening transaction (Sell to Open) with its matching closing transaction (Buy to Close, Expiration, or Assignment) and computes per-trade metrics.

---

## How trades are paired

Multi-leg trades (strangles, iron condors, spreads) are grouped by **order ID** using a Union-Find algorithm. All legs that share an order ID, or share a ticker and are placed within a short time window of each other, are treated as a single trade.

Each group is then matched:
- **Sell to Open** rows establish the opening credit
- **Buy to Close**, **Expiration**, or **Assignment** rows close the position
- The net cash flow across all legs = Net P&L

---

## Columns

| Column | Description |
|---|---|
| Ticker | Underlying symbol |
| Trade Type | Strategy classification (see below) |
| Open Date | Date of the first STO leg |
| Close Date | Date of the final closing leg |
| Days Held | Calendar days from open to close |
| DTE Open | Days to expiry at time of opening |
| Premium Rcvd | Total credit received (negative for debit trades) |
| Net P/L | Premium received minus buyback cost |
| Capture % | Net P&L ÷ Premium Received × 100 (blank for debit trades) |
| Ann Return % | Net P&L ÷ Capital Risk × 365 ÷ Days Held × 100 (capped at ±500%) |
| Prem/Day | Premium Received ÷ Days Held (credit trades only) |
| Daily θ % | Prem/Day ÷ Capital Risk × 100 — entry quality score: daily credit yield per unit of max risk (capped at 5%, credit trades only) |
| Capital Risk | Maximum potential loss (see below) |
| Close Type | How the position was closed |
| Won | True if Net P&L > 0 |
| Is Credit | True if Premium Received > 0 |

---

## Capital Risk calculation

Capital Risk is used to compute Ann Return % and Daily θ %, and gives context for position sizing.

| Strategy | Capital Risk |
|---|---|
| Short Put | Strike × 100 |
| Short Call (covered) | Share cost basis |
| Spread (defined risk) | Width of spread × 100 − credit received |
| Index options (SPX, XSP, NDX etc.) | Premium received (cash-secured not applicable) |
| Iron Condor | Width of wider spread × 100 |

Index options are identified using an explicit `KNOWN_INDEXES` set in `config.py` (`SPX`, `SPXW`, `NDX`, `RUT`, `VIX`, `XSP`, `NANOS`, `DJX`, `OEX`). This prevents high-priced equities (MSTR, NFLX, AVGO) from being misclassified as indexes based on strike price alone.

---

## Close types

| Icon | Type | Meaning |
|---|---|---|
| ✂️ Closed | Manual close | Bought back before expiry |
| ⏹️ Expired | Expiration | Expired worthless (full capture) |
| 📋 Assigned | Assignment | Option exercised — shares delivered |

---

## Strategy classification

Trades are classified based on the combination of option types, strikes, and expiries in the group:

| Strategy | Description |
|---|---|
| Short Put | 1 put, STO |
| Short Call | 1 call, STO |
| Covered Call | Short call with underlying shares held |
| Covered Strangle | Short put + short call with shares held |
| Short Strangle | 1 put + 1 call, same expiry, no shares |
| Jade Lizard | Short put + call credit spread |
| Iron Condor | 2 puts + 2 calls, defined risk, short legs at different strikes |
| Iron Butterfly | 2 puts + 2 calls, short legs share the same ATM strike |
| Reverse Iron Condor | Debit version — long legs at different strikes |
| Reverse Iron Butterfly | Debit version — long legs share the same ATM strike |
| Put Credit Spread | 2 puts, defined risk, net credit |
| Call Credit Spread | 2 calls, defined risk, net credit |
| Put Debit Spread | 2 puts, net debit |
| Call Debit Spread | 2 calls, net debit |
| Long Call/Put Butterfly | 3 legs — buy wings, sell body |
| Short Call/Put Butterfly | 3 legs — sell wings, buy body ×2 |
| Calendar Spread | Same strike, different expiries |
| Long Call | 1 call, BTO |
| Long Put | 1 put, BTO |
| Long Strangle | Long put + long call |
| Risk Reversal | Long call + short put (or vice versa) |

---

## Capture %

Capture % measures how much of the opening premium was kept:

- **100%** — expired worthless, full premium captured
- **50%** — bought back at half the opening credit (TastyTrade's recommended management target)
- **0%** — bought back at exactly the opening credit, breakeven
- **Negative** — bought back for more than the opening credit, a loss

Capture % is blank for debit trades — the concept does not apply when you paid to open the position.

---

## LEAPS exclusion

Trades with DTE > 90 at open are excluded from the ThetaGang scorecard metrics (win rate, capture %, management rate etc.) and shown as a separate callout in the Discipline & Patterns tab. They are still included in P&L totals and the closed trades table.
