# TastyMechanics — Claude Context

A Streamlit dashboard for wheel traders and theta harvesters on TastyTrade. Analyzes CSV transaction exports to produce realized P/L, wheel campaign tracking, premium selling scorecard, and portfolio analytics.

---

## Running the Test Suite

Always run after any change:

```bash
python3 test_tastymechanics.py
```

Expected: `294 tests | 294 passed | 0 failed` (24 sections)

Syntax check all files before presenting output:

```bash
python3 -c "import ast; ast.parse(open('mechanics.py').read()); print('OK')"
```

---

## Module Structure

Strict one-way dependency chain — no module imports from above it:

```
config.py           Constants, COLOURS palette, thresholds, known indexes
models.py           Dataclasses — Campaign, AppData, ParsedData
ingestion.py        CSV parsing — no Streamlit dependency
mechanics.py        FIFO engine, campaign logic, trade classification
ui_components.py    Formatters, colour functions, chart helpers
report.py           HTML report export — no Streamlit dependency
tabs/tab0–tab5      One renderer per tab, imported by tastymechanics.py
tastymechanics.py   Streamlit wiring — sidebar, cache, tab orchestration
```

---

## Key Conventions

**COLOURS** — all colours come from `config.py COLOURS` dict. Never add hardcoded hex values anywhere outside the CSS block in `tastymechanics.py`. Single source of truth.

**FIFO_EPSILON** — use `abs(qty) > FIFO_EPSILON` not `qty != 0` for zero-quantity guards. Consistent with the FIFO engine throughout.

**Cache keys** — `build_all_data` and `get_daily_pnl` take `_parsed`/`_df` with underscore prefix (Streamlit skips hashing). Always pass `_file_hash` (hashlib.md5 of raw bytes) as an explicit argument so the cache invalidates on new file upload. Never use `hash()` — not stable across processes.

**Campaign aggregation** — always use `_aggregate_campaign_pnl(all_campaigns, use_lifetime)` from `mechanics.py`. Never inline the three generator expressions — they existed in two places and caused a bug.

**Trade classification** — `_classify_trade_type()` and `_calculate_capital_risk()` are pure module-level functions in `mechanics.py`. Do not embed classification logic back into `build_closed_trades()`.

**DTE thresholds** — `DTE_ALERT_CRIT = 5` and `DTE_ALERT_WARN = 14` live in `config.py`. Never hardcode 5 or 14 in UI code.

**realized_pnl()** — for closed campaigns includes `exit_proceeds`. For open campaigns it's premiums + dividends only. `use_lifetime=True` always returns premiums + dividends regardless of status (strips equity component for House Money mode).

**effective_basis()** — `use_lifetime=True` returns raw `blended_basis` (no premium offset). Default returns `(total_cost - premiums - dividends) / total_shares`.

---

## Important Files

- `ROADMAP.md` — pending work, prioritised
- `Known-Limitations.md` — what doesn't work or is untested
- `Architecture.md` — full dependency chain and data flow
- `test_tastymechanics.py` — 294 tests, 24 sections
- `config.py` — `KNOWN_INDEXES`, `COLOURS`, `DTE_*`, `WIN_RATE_*`, `FIFO_EPSILON`

---

## Things NOT to Do

- Don't add hardcoded hex colours — use `COLOURS` dict
- Don't use `hash()` for cache keys — use `hashlib.md5(...).hexdigest()`
- Don't inline campaign aggregation — use `_aggregate_campaign_pnl()`
- Don't embed trade classification in `build_closed_trades()` — use the pure helpers
- Don't use `qty != 0` — use `abs(qty) > FIFO_EPSILON`
- Don't add bullet point lists to prose responses — project owner prefers clean prose
- Don't add `.iloc[0]` without an empty guard

---

## What's Left (from ROADMAP.md)

**Low priority — code quality:**
- FIFO branch comments (`mechanics.py` ~123–175) — `# BUY:` and `# SELL:` signposts
- Type hints on tab render functions (`tabs/tab0–tab5`)
- `%` formatting → f-strings on contact only, not a dedicated pass

**Waiting on real CSV data:**
- Closed campaign test
- Stock split test
- Futures open position test

**Features (parked):**
- 0DTE support — quick wins, new metrics, strategy mode selector
- Scroll-to on Wheel Campaign table — not achievable in Streamlit

---

## Trading Style Context

Built for **wheel trading and theta harvesting** on TastyTrade — short puts, covered calls, strangles, iron condors, multi-day holds. General options trading supported. 0DTE works but some metrics are less meaningful for same-day trades.

This is a personal project that works for the owner's trading style. Others are welcome to fork and customise. Not built for feature requests.
