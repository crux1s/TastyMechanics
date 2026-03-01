# TastyMechanics Roadmap

Ideas and planned improvements, loosely prioritised. Not a commitment — just a record so nothing gets lost.

---

## In Progress / Next

Nothing active right now.

---

## 0DTE Support

### Quick wins (existing tabs)
- Suppress `Ann Return %` when median days held < 2 — replace metric card with a note explaining why it is not shown for same-day trades
- Suppress `Med Premium/Day` when median hold < 1 day — same reasoning
- Add a callout banner when >50% of closed trades are 0DTE: *"This account has significant 0DTE activity — some metrics are less meaningful for same-day trades"*

### New metrics / charts
- P/L by expiry date (not close date) — crucial for 0DTE to see which calendar days were winners vs losers
- 0DTE vs non-0DTE split throughout the scorecard — separate row or toggle showing metrics for each group independently
- Win rate and avg P/L breakdown by underlying for 0DTE trades specifically (SPX, SPY, QQQ etc.)

### Structural
- **Strategy mode selector** in sidebar: `Wheel / Theta / 0DTE`
  - Hides the Wheel Campaigns tab for 0DTE mode (irrelevant)
  - Adjusts which metrics are prominent in the scorecard
  - Streamlit dynamic tab visibility makes this achievable
  - Would make the app feel purpose-built for each trading style rather than a one-size-fits-all dashboard

---

---

## Tests Needing Real Data

These tests are scoped and ready to write — just waiting for the right CSV data:

- **Closed campaign test** — a ticker where shares were fully exited. Verify campaign P/L, exit proceeds, effective basis at close.
- **Stock split test** — a ticker that underwent a forward or reverse split. Verify FIFO lot adjustment and correct post-split cost basis.
- **Futures open position test** — an open /MES or /ZS position. Verify it appears correctly in open positions and does not distort equity P/L.

---

## Performance

- **Vectorise `get_signed_qty`** — currently called row-by-row via `df.apply()` during CSV parsing. Only relevant for very large exports (5+ years, tens of thousands of rows). Not a priority until someone reports slow load times.

---

## Cosmetic / Theme

- **Convert remaining CSS/HTML inline strings in `tastymechanics.py` to use `COLOURS` dict** — paves the way for full dark/light theme switching. The `COLOURS` palette is already in `config.py`; the main app still has some hardcoded hex values in HTML strings.

---

## Parked / Uncertain

- **Scroll-to on Wheel Campaign table click** — clicking a ticker in the summary table to jump to its card. Not achievable cleanly in Streamlit (iframe sandboxing blocks anchor navigation). Revisit if the app ever moves to a custom web framework.

---

## Completed

- ✅ High-priced equity index misclassification fixed — `KNOWN_INDEXES` explicit list in `config.py` replaces strike > $500 heuristic
- ✅ Wheel Campaigns waterfall chart removed (was redundant with card metrics)
- ✅ Closed campaigns hidden behind collapsed expander in Wheel Campaigns tab
- ✅ File-per-tab split — `tabs/tab0`–`tab5` extracted from `tastymechanics.py`
- ✅ `report.py` extracted from `tastymechanics.py`
- ✅ HTML report export with two scorecard sections (Portfolio Overview + Options Trading)
- ✅ Weekly/monthly P/L bar charts replaced with candlestick charts
- ✅ Lifetime "House Money" toggle moved from sidebar into Wheel Campaigns tab header
- ✅ f-string Python 3.10/3.11 compatibility fix (`ui_components.py`)
- ✅ `datetime.utcnow()` deprecation warning fixed
- ✅ `COLOURS` 13-colour palette added to `config.py`, `ui_components.py` fully migrated
- ✅ Test suite expanded to 294 tests (24 sections)
- ✅ `detect_strategy()` Call Butterfly and Long Call false positives fixed
- ✅ Six tab render functions extracted from `main()` (v25.11)
- ✅ Union-Find helpers extracted to module level (v25.11)
- ✅ Pure analytics layer extracted to `mechanics.py` (v25.9)
