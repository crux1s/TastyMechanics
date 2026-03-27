# Time Windows

The time window selector filters almost every metric in the app. Understanding how it works prevents misreading your numbers.

---

## Available windows

| Window | Date range |
|---|---|
| YTD | January 1 of the current year to the latest transaction date |
| Last 7 Days | Rolling 7 calendar days |
| Last Month | Rolling 30 calendar days |
| Last 3 Months | Rolling 90 calendar days |
| Half Year | Rolling 182 calendar days |
| 1 Year | Rolling 365 calendar days |
| All Time | Full CSV history |

The window selector appears at the top-right corner of the Derivatives Performance, Discipline & Patterns, and Portfolio P/L tabs. Changing it updates all tabs simultaneously.

---

## What the window affects

| Metric | Windowed? |
|---|---|
| Realized P&L | ✅ Yes |
| Realized ROR | ✅ Yes (uses windowed P&L) |
| Capital Efficiency | ✅ Yes (uses windowed P&L and window days) |
| Div + Interest | ✅ Yes |
| Closed trades table | ✅ Yes — filtered by close date |
| Derivatives Performance scorecard | ✅ Yes |
| Discipline & Patterns charts | ✅ Yes |
| Capital Deployed | ❌ No — always shows current open positions |
| Account Age | ❌ No — always shows full history |
| Campaign cards | ❌ No — campaigns always show full lifetime |

---

## Capital Efficiency and short windows

Capital Efficiency is an **annualised** return figure:

```
Cap Efficiency = (Window P&L ÷ Capital Deployed ÷ Window Days) × 365 × 100
```

Short windows (Last 7 Days, Last Month, Last 3 Months) will produce dramatically higher or lower annualised rates than your true long-run figure. A great week can show 200%+ annualised. A bad week can show deeply negative. This is mathematically correct but should be interpreted with caution.

The All Time window gives the most reliable Capital Efficiency reading.

---

## Period comparison card

The **Portfolio P/L** tab shows a comparison between the current window and the prior equivalent period. For example, with Last Month selected, it compares the last 30 days against the 30 days before that, showing absolute and percentage deltas for each metric. This card is not shown when All Time is selected.

---

## How filtering works

The window filters on the **transaction date** stored in the CSV (UTC). For options, this is the trade execution date. For equity sales, this is the settlement date as recorded by TastyTrade.

FIFO equity P&L in a window only includes sales whose execution date falls within the window. The cost basis for those sales is still calculated from the full history — a sale in the Last 7 Days window will correctly use a purchase cost from 6 months ago.
