# Test Suite

`test_tastymechanics.py` contains 299 tests across 24 sections. Tests run directly against real CSV data with no Streamlit server required.

---

## Running the tests

```bash
PYTHONIOENCODING=utf-8 python3 test_tastymechanics.py
```

Place your TastyTrade CSV (named `tastytrade_*.csv` or `tastymechanics_*.csv`) in the same folder as the script. The suite will find it automatically.

A passing run looks like:

```
GRAND TOTAL:  299 tests  |  299 passed  |  0 failed
All tests passed ✅
```

A failing run exits with code 1 and prints every failed test with the actual vs expected value.

---

## What is tested

| Section | Coverage |
|---|---|
| 1. Data loading & parsing | Row counts, column types, date parsing |
| 2. FIFO engine | Per-ticker realised gains, fractional shares, lot matching |
| 3. Options cash flows | Total options P&L, SPX settlement, futures |
| 4. Dividends & interest | Income component totals |
| 5. Campaign accounting | Window boundary verification — pre vs post-purchase option attribution |
| 6. Total realized P&L | All three components summed correctly |
| 7. Deposits / portfolio stats | Deposits, withdrawals, ROR, cash balance |
| 8. Open equity positions | Share counts, cost basis, blended basis |
| 9. Windowed P&L consistency | Consistency check against ground truth |
| 10. Edge cases | Assignments, expirations, cash-settled index, transfers |
| 11. Individual campaign cards | Per-ticker premiums, effective basis, campaign P&L |
| 12. Outside-window options | Pre-purchase standalone option P&L |
| 13. Windowed P&L — named windows | YTD, Last 7 Days, Last Month, Last 3 Months, All Time values |
| 14. Capital deployed | Per-ticker and total capital in shares |
| 15. Ticker-level options P&L | Per-ticker option cash flows |
| 16. Self-calibrating invariants | Structural checks that work on any CSV |
| 17. Closed trades — core | Total count, win rate, P&L, per-ticker, spot trades |
| 18. Closed trades — strategy | Count and P&L per strategy type |
| 19. Closed trades — close types | Expired/assigned/closed counts, debit trades |
| 20. Closed trades — windows | YTD/7d/30d filtering, boundary checks |
| 21. Union-Find helpers | _uf_find, _uf_union, _group_symbols_by_order |
| 22. calc_dte | DTE calculation, edge cases, non-option rows |
| 23. build_option_chains | Chain detection, rolls, multi-type, empty input |
| 24. UI helpers | xe() HTML escaping, identify_pos_type(), detect_strategy() |

---

## VERIFIED tests

Four tests are marked **VERIFIED** — the exact values were cross-checked screenshot-by-screenshot against the live TastyTrade transaction history UI:

- **SLV Put** — Jan 7 → Jan 10 2026, credit $100.88, net P&L $39.76
- **INTC Losing Put** — Jan 28 → Feb 17 2026, credit $103.88, net P&L -$13.24
- **SMR Losing Put** — Jan 26 → Feb 17 2026, credit $60.88, net P&L -$87.24
- **TSLA Call Debit Spread** — Oct 2 BTO 457.5C/$12.23 + STO 460C/$10.93, both expired worthless Oct 4. Net -$132.24, Capture % = None (not -100%)

These tests confirm trade pairing logic, debit trade display, and that Capture % is correctly suppressed for non-credit trades.

---

## Section 16 — Self-calibrating invariants

Section 16 contains tests that are valid for **any** CSV — they check structural correctness rather than specific values:

- All expiration rows sum to $0
- All assignment option rows sum to $0
- All equity buy rows have positive Net_Qty_Row
- All equity sell rows have negative Net_Qty_Row
- FIFO equity P&L is less than or equal to gross sale proceeds
- All Time window P&L equals the sum of components
- Net deposited is >= 0
- Total capital deployed is > 0

These never need updating and will catch structural bugs on any account's CSV.

---

## Section 24 — UI helpers

Three functions tested in Section 24:

**`xe(value)`** — HTML-escapes strings passed into rendered HTML. Tests confirm `<`, `>`, `&`, `"` are all escaped correctly, non-string types pass through unchanged, and `None` returns `None`.

**`identify_pos_type(row)`** — classifies a position row as Long/Short Stock, Long/Short Call, Long/Short Put, Future Option Short Put, or Asset. Tests cover all branches including unknown instrument types.

**`detect_strategy(df)`** — classifies a group of legs into a strategy name. Tests cover: Short Put, Covered Call, Covered Strangle, Short Strangle, Jade Lizard, Big Lizard, Risk Reversal, Call Butterfly, Put Butterfly, Calendar Spread, Call Debit Spread, Long Call, Long Stock, and Custom/Mixed fallback.

Two bugs were found and fixed during this section:

- **Call Butterfly false positive** — was incorrectly matching Call Debit Spread when `lc==2, sc==1` with 3 strikes. Fixed by verifying the short call is the middle strike.
- **Long Call false positive** — `lc>0` matched groups with 2+ unmatched long calls. Fixed to `lc==1`.

---

## Updating tests after a new CSV export

When you export a fresh CSV with new trades, some aggregate tests will fail because the snapshot values have changed. To update:

1. Run the tests and note which fail
2. The failures will be aggregate counts and totals (row count, total P&L, window P&L etc.)
3. Update the expected values in the relevant `check()` calls
4. The **VERIFIED** tests and **invariant** tests (section 16) will not need updating — they are structural

---

## Adding new tests

When adding a new feature or fixing a bug, add tests at the same time:

1. Find the real values from your CSV using a quick Python snippet
2. Add `check()` or `check_int()` calls in the appropriate section
3. If you manually verified a value against the TastyTrade UI, prefix the test name with `VERIFIED`
4. Run the full suite to confirm all 299 (+ your new ones) pass
