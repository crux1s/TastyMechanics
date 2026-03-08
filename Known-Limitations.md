# Known Limitations

Scenarios where TastyMechanics may produce incorrect results or has not been fully tested. Verify manually against your TastyTrade statements if any apply to your account.

P&L figures are cash-flow based (what actually hit your account) and use FIFO cost basis for equity. They do not account for unrealised gains/losses, wash sale rules, or tax adjustments. Always reconcile against your official TastyTrade statements. This tool is not financial advice.

---

## Trade Classification

### Complex multi-leg structures
PMCC, diagonals, ratio spreads, and rolled calendars may not be classified with the correct strategy label. **P&L totals are correct** — only the Trade Type label in the closed trades table may be wrong. Specific known gaps are listed below — all untested with real data, verify on first occurrence.

### Long Straddle
Classified as **'Long Strangle'** — the classifier detects long call + long put but does not check whether the strikes are identical. A straddle (same strike) and a strangle (different strikes) both return 'Long Strangle'. P&L is correct.

### Iron Butterfly / Reverse Iron Butterfly
Both classified as **'Iron Condor'** — the 4-leg detection path fires on any combination of short call + short put + long call + long put, regardless of whether the inner strikes are the same (butterfly) or different (condor). Distinguish manually by checking strike prices. P&L is correct.

### Reverse Iron Condor
Classified as **'Iron Condor'** — the debit (long volatility) variant has the same 4-leg structure as the credit variant. No debit/credit distinction is applied at the Iron Condor detection branch. P&L is correct.

### Collar
Classified as **'Put Debit Spread'** — a collar (short call + long put against long stock) has one long leg and one short leg with no strike width, so it routes to the vertical spread fallback. No campaign/stock-ownership check is applied for collars. P&L is correct.

### Call Condor / Put Condor (4-leg single-type)
Classified as a **2-leg spread label** (e.g. 'Call Debit Spread') — a 4-leg all-call or all-put condor has two long legs and two short legs, but the classifier treats the width detection as a simple spread. Verify the Trade Type label on first occurrence. P&L is correct.

### Diagonal Spreads (PMCC, Long/Short Call/Put Diagonal)
Classified as a **vertical spread label** — diagonals have different strikes AND different expirations, so the calendar check (same strike required) fails and the trade falls through to the call/put credit/debit spread branch. Partially covered by the general 'Complex multi-leg structures' note above. P&L is correct.

### Ratio Spreads (Back Spreads / Front Spreads)
Likely classified as **'Short (other)'** or misrouted — ratio spreads have unequal quantities (e.g. sell 1, buy 2), which breaks the classifier's assumption of matched leg quantities. Verify label and capital risk on first occurrence. P&L is correct.

### Butterfly and Calendar direction not preserved
Both **Long and Short Butterfly** variants are labelled identically ('Call Butterfly' / 'Put Butterfly') with no long/short prefix. All **Calendar Spread** variants (long/short, call/put) are labelled 'Calendar Spread' with no direction or type distinction. P&L is correct in both cases.

### Reverse Jade Lizard
Detected as a Jade Lizard but capital risk may be understated — max loss is on the call side, not the put side. Verify if you trade this structure.

### 0DTE trades
P&L is correct. Ann Return %, Med Premium/Day, and Wheel Campaigns are less meaningful for same-day holds.

---

## Campaign Detection

### Covered calls assigned away (full position)
If your entire share position is called away by a covered call assignment, the campaign closes and exit P&L is recorded. Supported but untested with real data — verify on first occurrence.

### Covered calls assigned away (partial position)
If a covered call assigns away only some of your shares (e.g., 100 of 200 SOFI shares), the campaign stays open but the card metrics will be stale: SHARES, ENTRY BASIS, and COST BASIS continue to reflect the peak shares ever acquired, not the current reduced holding. Exit proceeds accumulate correctly for when the campaign eventually closes, but they are not shown in the open-campaign P&L display (realized P&L for open campaigns shows premiums + dividends only). Verify share count and per-share basis figures manually after any partial covered call assignment. Untested with real data — first occurrence to confirm.

### Multiple assignments on the same ticker
Each buy-in starts a new campaign. If assigned, shares sold, then assigned again on the same ticker, you will have two separate campaigns. Blended basis across campaigns is not combined.

### Long options exercised by you
Exercising a long call or put into a share position is untested. Check the resulting position and cost basis carefully.

### Assignment-entered campaign: put premium not in effective basis
When the very first shares of a ticker arrive via put assignment (no prior outright purchase), the opening credit of that put is counted as pre-purchase options P/L — it is **not** included in campaign premiums or effective basis. The campaign card effective basis reflects only post-delivery option income. Total P/L is unaffected. Verify this matches your expectations on first occurrence of a new assignment-entered ticker.

### Rolled pre-purchase put followed by assignment: only final leg folds in
If you rolled a put one or more times before it was ultimately assigned, each roll creates a new option symbol. Only the opening credit of the final (assigned) contract is attributable to the delivery event. Earlier roll legs remain in the pre-purchase options P/L bucket. Net P/L is correct — only effective basis display is affected. Verify on first occurrence of a multi-roll pre-purchase assignment.

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

---

## Other

### Non-US accounts
Built and tested on a US TastyTrade account only. CSV format differences, currency handling, and tax treatment for non-US accounts are unknown.

### UTC date offset
All dates are stored in UTC. Trades placed after market hours US Eastern time will appear as the next calendar day. This is consistent across all trades and does not affect P&L bucketing meaningfully.
