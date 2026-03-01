# Known Limitations

These are scenarios where TastyMechanics may produce incorrect results or has not been tested. Verify manually against your TastyTrade statements if any apply to your account.

---

## Trade classification

### High-priced equity options misclassified as indexes
**Status: Fixed**

Index options (SPX, XSP, NDX, RUT, VIX etc.) are identified by an explicit `KNOWN_INDEXES` set in `config.py` rather than a strike price threshold. High-priced equities (MSTR, NFLX, AVGO etc.) are correctly classified as equity options and use `strike × 100` for Capital Risk.

### Complex multi-leg structures
PMCC (Poor Man's Covered Call), diagonals, ratio spreads, and jade lizards may not be classified with the correct strategy label. **P&L totals are correct** — only the Trade Type label in the closed trades table may be wrong.

---

## Campaign detection

### Covered calls assigned away
If your shares are called away by a covered call assignment, verify that the campaign closes correctly and the exit P&L is recorded. This scenario is supported but verify manually on first occurrence.

### Multiple assignments on the same ticker
Each buy-in starts a new campaign. If you are assigned, sell the shares, then are assigned again on the same ticker, you will have two separate campaigns. Blended basis across campaigns is not combined unless House Money mode is enabled.

### Long options exercised by you
Exercising a long call or put yourself (not assignment) into a share position is untested. Check the resulting position cost basis carefully.

---

## Corporate actions

### Stock splits
Forward and reverse splits are detected and FIFO-adjusted — share quantities and cost basis are restated. However, TastyTrade-issued post-split option symbols are not automatically stitched to pre-split contracts in the closed trades table. Option chains may appear broken across the split date.

### Spin-offs and zero-cost deliveries
Shares received at $0 cost (spin-offs, ACATS transfers) will appear as a ⚠️ Basis Warning in the sidebar. A toggle lets you exclude those tickers from all P&L metrics so the inflated basis doesn't distort Realized ROR or Capital Efficiency. Toggle this on if affected.

### Mergers and acquisitions
If a held ticker is acquired or merged, the original campaign may be orphaned with no exit recorded. P&L for that position will be incomplete. Reconcile manually against your broker statement.

---

## Futures

### Cash-settled futures options
Futures options (/MES, /ZS, /ZC etc.) are included in P&L totals. Cash-settled expiry is handled correctly. However, in-the-money expiry that delivers a futures contract (not cash) is not handled and will produce incorrect P&L for that position.

---

## Dates and timezones

### UTC date offset
All dates are stored in UTC. Trades placed after market hours US Eastern time will appear as the next calendar day. This is consistent across all trades and does not affect weekly or monthly P&L bucketing in any meaningful way.

---

## Non-US accounts

TastyMechanics was built and tested exclusively on a US TastyTrade account. CSV format differences, currency handling, and tax treatment for non-US accounts (Australia, UK, Canada etc.) are unknown. Results may be incorrect.

---

## General

P&L figures are cash-flow based (what actually hit your account) and use FIFO cost basis for equity. They do not account for unrealised gains/losses, wash sale rules, or tax adjustments. Always reconcile against your official TastyTrade statements for tax purposes. This tool is not financial advice.
