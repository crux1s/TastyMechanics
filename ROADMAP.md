# TastyMechanics Roadmap

Ideas and planned improvements, loosely prioritised. Not a commitment — just a record so nothing gets lost.

---

## In Progress / Next

Nothing active right now.

---

## UX Improvements

---

## 0DTE Support

### Quick wins (existing tabs)
- ~~Suppress `Ann Return %` when median days held < 2~~ — done v26.11: Median Ann. Return removed entirely (was degenerate on mixed weekly/swing books, not just 0DTE; per-trade column kept)
- Suppress `Med Premium/Day` when median hold < 1 day — same reasoning
- Add a callout banner when >50% of closed trades are 0DTE

### New metrics / charts
- P/L by expiry date (not close date) — crucial for 0DTE to see which calendar days were winners
- 0DTE vs non-0DTE split throughout the scorecard — separate row or toggle
- Win rate and avg P/L breakdown by underlying for 0DTE trades (SPX, SPY, QQQ etc.)

### Structural
- **Strategy mode selector** in sidebar: `Wheel / Theta / 0DTE`
  - Hides the Wheel Campaigns tab for 0DTE mode
  - Adjusts which metrics are prominent in the scorecard
  - Streamlit dynamic tab visibility makes this achievable

---

## Tests Needing Real Data

Waiting on the right CSV scenarios to appear naturally:

- **Stock split test** — forward or reverse split. Verify FIFO lot adjustment and correct post-split cost basis.
- **Futures open position test** — an open /MES or /ZS position. Verify it appears in open positions and does not distort equity P/L.

---

## Parked

- **Vectorise `get_signed_qty`** — row-by-row `df.apply()` during CSV parsing. Only matters at 5+ years / tens of thousands of rows. Not a priority until someone reports slow load times.
- **Scroll-to on Wheel Campaign table click** — not achievable cleanly in Streamlit (iframe sandboxing). Revisit if the app moves to a custom web framework.
