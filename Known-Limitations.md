# Known Limitations

Scenarios where TastyMechanics may produce incorrect results or has not been fully tested. Verify manually against your TastyTrade statements if any apply to your account.

P&L figures are cash-flow based (what actually hit your account) and use FIFO cost basis for equity. They do not account for unrealised gains/losses, wash sale rules, or tax adjustments. Always reconcile against your official TastyTrade statements. This tool is not financial advice.

---

## Trade Classification

### Complex multi-leg structures
PMCC, diagonals, ratio spreads, and rolled calendars may not be classified with the correct strategy label. **P&L totals are correct** — only the Trade Type label in the closed trades table may be wrong.

### Reverse Jade Lizard
Detected as a Jade Lizard but capital risk may be understated — max loss is on the call side, not the put side. Verify if you trade this structure.

### 0DTE trades
P&L is correct. Ann Return %, Med Premium/Day, and Wheel Campaigns are less meaningful for same-day holds.

---

## Campaign Detection

### Covered calls assigned away
If your shares are called away by a covered call assignment, verify that the campaign closes correctly and exit P&L is recorded. Supported but untested with real data — verify on first occurrence.

### Multiple assignments on the same ticker
Each buy-in starts a new campaign. If assigned, shares sold, then assigned again on the same ticker, you will have two separate campaigns. Blended basis across campaigns is not combined.

### Long options exercised by you
Exercising a long call or put into a share position is untested. Check the resulting position and cost basis carefully.

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
