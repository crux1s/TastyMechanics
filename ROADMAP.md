# TastyMechanics Roadmap

Ideas and planned improvements, loosely prioritised. Not a commitment — just a record so nothing gets lost.

---

## In Progress / Next

Nothing active right now.

---

## Readability & Maintainability

- **FIFO branch comments** (`mechanics.py` ~123–175) — the preamble docstring is excellent but the actual `if qty > 0` / `elif qty < 0` branches have no signpost. Add 1–2 lines before each branch: `# BUY: cover shorts first (FIFO), then open/add long` and `# SELL: close longs first (FIFO), then open/add short`. Low priority.

- **Type hints on tab render functions** (`tabs/tab0`–`tab5`) — each takes 8–12 positional arguments with no hints. Add signatures like `def render_tab1(closed_trades_df: pd.DataFrame, ...) -> None`. Low priority.

- **Old-style `%` formatting** (`mechanics.py:347`, `ui_components.py:53–55`) — not a bug, inconsistent with f-strings used everywhere else. Standardise on f-strings when those lines are touched for other reasons. Not worth a dedicated pass.

---

## 0DTE Support

### Quick wins (existing tabs)
- Suppress `Ann Return %` when median days held < 2 — replace metric card with a note explaining why
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

- **Closed campaign test** — a ticker where shares were fully exited. Verify campaign P/L, exit proceeds, effective basis at close.
- **Stock split test** — forward or reverse split. Verify FIFO lot adjustment and correct post-split cost basis.
- **Futures open position test** — an open /MES or /ZS position. Verify it appears in open positions and does not distort equity P/L.

---

## Parked

- **Vectorise `get_signed_qty`** — row-by-row `df.apply()` during CSV parsing. Only matters at 5+ years / tens of thousands of rows. Not a priority until someone reports slow load times.
- **Scroll-to on Wheel Campaign table click** — not achievable cleanly in Streamlit (iframe sandboxing). Revisit if the app moves to a custom web framework.

---

## Completed

- ✅ Docstrings for `effective_basis()` and `realized_pnl()` — full formula explanation, house money concept, when each branch fires
- ✅ `_aggregate_campaign_pnl()` extracted to mechanics.py — eliminates duplicate aggregation between `compute_app_data()` and zero-cost exclusion path
- ✅ `_classify_trade_type()` and `_calculate_capital_risk()` extracted to module-level pure functions in mechanics.py
- ✅ Streamlit Cloud stale cache bug fixed — `hashlib.md5` replaces `hash()` for cross-process stable cache key
- ✅ Report "Deposited" figure corrected — was net (deposits minus withdrawals), now gross deposits
- ✅ DTE alert thresholds (5d/14d) moved to `config.py` as `DTE_ALERT_CRIT` / `DTE_ALERT_WARN`
- ✅ `.iloc[0]` unguarded calls guarded in mechanics.py
- ✅ `qty != 0` → `abs(qty) > FIFO_EPSILON` for consistency with FIFO engine
- ✅ `import io as _io` / `import html as _html` aliases removed
- ✅ Silent `except: pass` blocks commented
- ✅ COLOURS migration complete — all hardcoded hex removed from tastymechanics.py and ui_components.py
- ✅ Welcome screen rewritten — who it's for, what each tab does, updated limitations list
- ✅ "Options Trading — Credit Trades Only" renamed to "Premium Selling Performance" throughout
- ✅ ROADMAP.md added to repo
- ✅ High-priced equity index misclassification fixed — `KNOWN_INDEXES` explicit list
- ✅ Wheel Campaigns waterfall chart removed
- ✅ Closed campaigns hidden behind collapsed expander
- ✅ File-per-tab split — `tabs/tab0`–`tab5` extracted from `tastymechanics.py`
- ✅ `report.py` extracted — HTML export has no Streamlit dependency
- ✅ HTML report export (Portfolio Overview + Premium Selling Performance)
- ✅ Candlestick charts replace bar charts for weekly/monthly P/L
- ✅ Lifetime "House Money" toggle moved into Wheel Campaigns tab header
- ✅ f-string Python 3.10/3.11 compatibility fix
- ✅ `datetime.utcnow()` deprecation warning fixed
- ✅ `COLOURS` 13-colour palette added to `config.py`
- ✅ Test suite expanded to 294 tests (24 sections)
- ✅ `detect_strategy()` Call Butterfly and Long Call false positives fixed
- ✅ Six tab render functions extracted from `main()`
- ✅ Union-Find helpers extracted to module level
- ✅ Pure analytics layer extracted to `mechanics.py`
