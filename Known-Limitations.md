# Known Limitations

Scenarios where TastyMechanics may produce incorrect results or has not been fully tested. Verify manually against your TastyTrade statements if any apply to your account.

P&L figures are cash-flow based (what actually hit your account) and use FIFO cost basis for equity. They do not account for unrealised gains/losses, wash sale rules, or tax adjustments. Always reconcile against your official TastyTrade statements. This tool is not financial advice.

---

## Trade Classification

### Complex multi-leg structures
PMCC, diagonals, ratio spreads, and rolled calendars may not be classified with the correct strategy label. **P&L totals are correct** — only the Trade Type label in the closed trades table may be wrong. Specific known gaps are listed below — all untested with real data, verify on first occurrence.

### Long Straddle
Classified as **'Long Strangle'** — the classifier detects long call + long put but does not check whether the strikes are identical. A straddle (same strike) and a strangle (different strikes) both return 'Long Strangle'. P&L is correct.

### Collar
Classified as **'Put Debit Spread'** — a collar (short call + long put against long stock) has one long leg and one short leg with no strike width, so it routes to the vertical spread fallback. No campaign/stock-ownership check is applied for collars. P&L is correct.

### Call Condor / Put Condor (4-leg single-type)
Classified as a **2-leg spread label** (e.g. 'Call Debit Spread') — a 4-leg all-call or all-put condor has two long legs and two short legs, but the classifier treats the width detection as a simple spread. Verify the Trade Type label on first occurrence. P&L is correct.

### Diagonal Spreads (PMCC, Long/Short Call/Put Diagonal)
Classified as a **vertical spread label** — diagonals have different strikes AND different expirations, so the calendar check (same strike required) fails and the trade falls through to the call/put credit/debit spread branch. Partially covered by the general 'Complex multi-leg structures' note above. P&L is correct.

### Ratio Spreads (Back Spreads / Front Spreads)
Now classified as **'Call Ratio Spread'**, **'Put Ratio Spread'**, or **'Ratio Lizard'** (short put + unequal call spread). Capital risk is computed from the highest short strike × 100 minus credit received. These labels have not yet been verified against real TastyTrade CSV data — confirm on first occurrence. P&L is correct.

### Calendar Spread direction not preserved
All **Calendar Spread** variants (long/short, call/put) are labelled 'Calendar Spread' with no direction or type distinction. P&L is correct.

### Reverse Jade Lizard
Detected as a Jade Lizard but capital risk may be understated — max loss is on the call side, not the put side. Verify if you trade this structure.

### 0DTE trades
P&L is correct. Med Premium/Day and Wheel Campaigns are less meaningful for same-day holds. The per-trade Ann Ret % column on the trade tables is also distorted (the `365 / days_held` extrapolation degenerates on short holds); it is no longer aggregated anywhere in the scorecard for that reason. Median Daily θ % remains valid because it now uses DTE-at-open as the divisor (entry-yield, independent of hold time).

---

## Campaign Detection

### Covered calls assigned away (full position)
If your entire share position is called away by a covered call assignment, the campaign closes and exit P&L is recorded. Supported but untested with real data — verify on first occurrence.

### Covered calls assigned away (partial position)
If a covered call assigns away only some of your shares (e.g., 100 of 200 SOFI shares), the campaign stays open but the card metrics will be stale: SHARES, ENTRY BASIS, and COST BASIS continue to reflect the peak shares ever acquired, not the current reduced holding. Exit proceeds accumulate correctly for when the campaign eventually closes, but they are not shown in the open-campaign P&L display (realized P&L for open campaigns shows premiums + dividends only). Verify share count and per-share basis figures manually after any partial covered call assignment. Untested with real data — first occurrence to confirm.

### Multiple assignments on the same ticker
Each buy-in starts a new campaign. If assigned, shares sold, then assigned again on the same ticker, you will have two separate campaigns. Blended basis across campaigns is not combined.

### Odd-lot shares and partial sales (basis display)
Since v26.20, share buys below 100 are pooled and folded into the next campaign entry, and mid-campaign adds of any size count — so the campaign share count matches your broker position. However, a **partial sale keeps the carry-full-cost convention**: the remaining shares carry all remaining acquisition cost, so the displayed per-share basis *rises* after selling part of the position below basis (e.g. sell 13 of 105 at a loss → the 92 remaining shares show a higher $/sh figure than the broker's average cost). This is deliberate cash-recovery accounting — premiums and dividends grind the effective basis back down, and the sale's P/L settles in full when the campaign closes. Reconcile per-share basis against your broker statement, not the campaign card.

### Long options exercised by you
Exercising a long call or put into a share position is untested. Check the resulting position and cost basis carefully.

### Rolled pre-purchase put followed by assignment: only final leg folds in
When the first shares of a ticker arrive via put assignment, the assigning put's credit is folded into the campaign premiums and reduces effective basis (v26.23 — natural wheel accounting). If you rolled that put one or more times before it was assigned, each roll created a new option symbol, and **only the opening credit of the final (assigned) contract folds in** — earlier roll legs remain in the pre-purchase (pure options) P/L bucket. Total P/L is correct either way; only the effective-basis display understates the reduction by the earlier roll legs' net credit. Verify on first occurrence of a multi-roll pre-purchase assignment.

### Pre-purchase option closed after shares are purchased
If a put (or call) opened before you owned shares is closed on or after the day you buy shares, the closing transaction falls inside the campaign window and appears as a negative premium entry from day one of the campaign. The opening credit stays in pre-purchase P/L. Net P/L across both legs is correct. First observed: SOFI Dec 2025 (Nov 26 STO, Dec 2 BTC on same day as share purchase).

### Multiple puts assigned simultaneously
If two puts on the same ticker are both assigned on the same date (e.g., both expire ITM at the same expiry), both opening credits are summed into the campaign. Untested — verify share count and cost basis on first occurrence.

---

## Corporate Actions

### Stock splits
Forward and reverse splits are detected and FIFO-adjusted. However, TastyTrade-issued post-split option symbols are not automatically stitched to pre-split contracts — option chains may appear broken across the split date.

### Spin-offs and zero-cost deliveries
Shares received at $0 cost (spin-offs, ACATS transfers) trigger a ⚠️ Basis Warning in the sidebar. Use the toggle to exclude those tickers from P&L metrics if the inflated basis distorts your numbers.

### Mergers and acquisitions
If a held ticker is acquired or merged, the original campaign may be orphaned with no exit recorded. P&L for that position will be incomplete — reconcile manually.

---

## Futures

### In-the-money futures options expiry
Cash-settled futures options (/MES, /ZS etc.) are included in P&L totals. Cash-settled expiry is handled correctly. In-the-money expiry that delivers a futures contract (not cash) is not handled and will produce incorrect P&L for that position.

### Futures options — Capital at Risk multiplier coverage
Capital at Risk and Ann Return % for futures options depend on a per-product dollar multiplier stored in `FUTURES_MULTIPLIERS` in `config.py`. Products not in that table silently fall back to the equity multiplier (100), which will produce a wrong Capital at Risk figure.

Products confirmed correct (verified against real CSV data or CME spec): /MES, /ES, /MNQ, /NQ, /M2K, /RTY, /MYM, /YM, /VX, /CL, /MCL, /NG, /GC, /MGC, /SI, /SIL, /ZB, /ZN, /ZF, /ZT, /ZC, /ZS, /ZW, /6E, /6B, /6A, /6C, /6S, /6N.

Products added from spec but not yet verified against a real trade: /RB, /HO, /HG, /ZL, /ZM, /HE, /LE, /GF, /6J, /6M. Confirm Capital at Risk on the first trade from any of these before relying on it. To add a missing product, append its root symbol and CME contract multiplier (dollars per full price point) to `FUTURES_MULTIPLIERS` in `config.py`.

---

## Performance Metrics

### Time-weighted return (TWR) and true Sharpe are not computed
The Long-Term Performance panel (Tab 4) shows **MWR (money-weighted return / XIRR)** as the headline, plus CAGR, max drawdown, Calmar, and monthly stats. It deliberately does **not** show a time-weighted return or a true Sharpe ratio: both require the portfolio's market value (NLV) at each point in time, and a TastyTrade transactions CSV contains only cash flows and trade fills — no daily account-value history. Rather than fabricate those metrics from realized P/L (which would be misleading), they are omitted. A faithful TWR / Sharpe would need a daily NLV feed, available only via the TastyTrade API.

### Realized-P/L basis of drawdown and XIRR terminal
Max Drawdown is measured on the **cumulative realized-P/L curve**, not on account NLV, so it does not reflect intra-trade mark-to-market swings on open positions. The XIRR terminal value is `net deposited + realized P/L` by default; it switches to a mark-to-market value (adding open-position unrealized P/L) only when the Live price toggle has fetched quotes.

### Mark-to-Market precision on partial sales inside open wheels (v26.21)
Since v26.21 the All-Time **Realized P/L** headline recognizes the equity P/L of partial share sales inside still-open wheel campaigns, so it reconciles with the Portfolio-tab chart. The **Mark-to-Market** figure (Live-prices toggle) was deliberately left unchanged, because its unrealized side marks the remaining shares against the carry-full-cost blended basis — which already absorbs the sold shares' cost — and recognizing the sale in both places would double-count it. As a result, MTM understates a still-open wheel by the *cash proceeds already received* from an earlier partial sale until the campaign closes. A fully precise MTM would require marking the remaining shares against their true FIFO basis in `compute_unrealized_pnl` — a documented follow-up. The realized figures (headline, ROR, MWR-realized) are unaffected and correct.

## Other

### Non-US accounts
Built and tested on a US TastyTrade account only. CSV format differences, currency handling, and tax treatment for non-US accounts are unknown.

### UTC date offset
All dates are stored in UTC. Trades placed after market hours US Eastern time will appear as the next calendar day. This is consistent across all trades and does not affect P&L bucketing meaningfully.
