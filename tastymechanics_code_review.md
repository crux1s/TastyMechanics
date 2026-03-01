# TastyMechanics v25.9 — Code Review
**Scope:** readability, maintainability, potential bugs and edge cases  
**Files reviewed:** `mechanics.py`, `tastymechanics.py`, `ingestion.py`, `config.py`, `models.py`, `ui_components.py`

---

## Overall Verdict

The codebase is in genuinely good shape for a project at this stage. The architecture is clean, the dependency chain is correctly one-way, the docstrings are detailed, and the test suite tests against real data rather than mocks. The issues below are real but none of them are showstoppers — most are edge cases that won't bite on a normal account but could produce wrong numbers or silent failures on unusual data.

---

## 🐛 Potential Bugs & Edge Cases

### 1. `_iter_fifo_sells` — division by zero on a zero-quantity row  
**File:** `mechanics.py`, lines 123 and 147  
**Severity:** Medium — would crash with a ZeroDivisionError on certain corporate action rows.

```python
pps = abs(total) / qty          # line 123 — BUY path
pps = abs(total) / remaining    # line 147 — SELL path
```

`get_signed_qty()` returns `0` for split rows and some corporate actions, but those rows are supposed to be filtered out upstream. If a row slips through with `qty == 0` and `total != 0` (e.g. a fee row misclassified as equity), you get `ZeroDivisionError`. A simple guard would prevent a silent crash:

```python
pps = abs(total) / qty if qty != 0 else 0.0
```

---

### 2. `build_campaigns` — split ratio computed from wrong variable  
**File:** `mechanics.py`, lines 318–331  
**Severity:** Medium — produces a wrong split ratio if a ticker has had multiple splits.

```python
split_qty = row.Quantity          # raw CSV quantity (always positive)
if running_shares > 0.001 and split_qty > 0:
    ratio = split_qty / running_shares   # ← uses running_shares BEFORE the split
```

`running_shares` is the post-previous-split count. If this is the second split on a ticker, `running_shares` is already the post-first-split number, so `ratio` is correct. But if the "addition" row in TastyTrade does not exactly equal the post-split share count (e.g. due to fractional rounding on a reverse split), `running_shares` could be wrong. Worth adding an assertion or a comment explaining why you trust TastyTrade's addition row quantity over `running_shares` here.

---

### 3. `pure_options_pnl` — window boundary uses `<=` not `<`  
**File:** `mechanics.py`, line 450  
**Severity:** Low — double-counts an option that closes exactly on a campaign end date.

```python
in_any_window |= (dates >= s) & (dates <= e)
```

Campaign end date is set to the date shares hit zero (the sale date). An option that also closes on that exact same date — while plausible in real trading — gets counted as *inside* the campaign window AND potentially as standalone P/L. Should almost certainly be `< e` (exclusive end), consistent with how `calculate_windowed_equity_pnl` handles the `end_date` parameter (line 187: `date < end_date`).

---

### 4. `build_closed_trades` — `open_date` derived from `opens['Date'].min()` may pick the wrong leg  
**File:** `mechanics.py`, line 493  
**Severity:** Low — affects `DTE Open` and `Ann Return %` on rolled trades.

```python
open_date = opens['Date'].min()
```

For a rolled position, all legs across all rolls get grouped by the Union-Find into one "trade group." The earliest open date across all rolls is used as `open_date`. This makes `days_held` span the entire roll chain (first open to last close), which inflates `days_held` and suppresses `Ann Return %` for trades that were actively rolled. This is likely intentional as a conservative estimate, but it is not documented — a short comment would clarify.

---

### 5. `compute_app_data` — extra capital deployed uses average cost, not FIFO remainder  
**File:** `mechanics.py`, lines 855–859  
**Severity:** Low — overstates capital deployed when a ticker has partial sells.

```python
bought_rows    = t_eq_rows[t_eq_rows['Net_Qty_Row'] > 0]
total_bought   = bought_rows['Net_Qty_Row'].sum()
total_buy_cost = bought_rows['Total'].apply(abs).sum()
avg_cost       = total_buy_cost / total_bought if total_bought > 0 else 0
extra_capital_deployed += net_shares * avg_cost
```

For a pure-options ticker where some shares have been sold, the remaining `net_shares` are costed at the average buy price across *all* lots (including already-sold ones). The FIFO engine has already consumed those lots — using average cost here overstates remaining capital deployed. To be consistent with the FIFO engine, you would need to track which lots remain in the queue, which is more complex. At minimum this should be documented as a known approximation.

---

### 6. `tastymechanics.py` — `realized_ror` computed from `total_realized_pnl` before the income add  
**File:** `tastymechanics.py`, lines 644–649  
**Severity:** Low — `realized_ror` stored in snapshot is inconsistent with `total_realized_pnl` displayed.

```python
# total_realized_pnl += _all_time_income - _wheel_divs_in_camps  ← happens at line 423
# ...but realized_ror is computed at line 645 BEFORE this line runs ...
# Wait, actually line 409 builds total_realized_pnl, then 423 adjusts it.
# Then realized_ror at 645 is computed AFTER 423 — this is fine in normal flow.
```

Actually the ordering is fine in normal (non-excluded) flow. However when `_zc_excluded` is non-empty, `total_realized_pnl` is **recomputed** at line 487, but `realized_ror` at line 645 is not recomputed — it was already computed at line 644 with the pre-filter value. This means the snapshot and the displayed ROR card (`_ror_display`) are on different bases when the zero-cost exclusion toggle is on.

Fix: move the `realized_ror` calculation to after the `_zc_excluded` block.

---

### 7. `build_option_chains` — long BTO events silently dropped  
**File:** `mechanics.py`, lines 702–712  
**Severity:** Low — chain log incomplete for spread legs.

The loop only handles `'to open' in sub and qty < 0` (short opens) and `net_qty > 0` close events. A long BTO leg (`qty > 0`, `'to open' in sub`) falls through the entire `if/elif` chain with no action. It does not appear in the chain event log. For spreads this means the long wing never shows up in the roll chain visualisation. This appears to be a deliberate simplification (chains are modelled as short-premium positions), but is worth documenting.

---

### 8. `ingestion.py` — `detect_corporate_actions` iterates rows after groupby  
**File:** `ingestion.py`, lines 104–126  
**Severity:** Very Low — performance only, not a correctness issue.

The second loop after the groupby uses `itertuples` which is fine, but reads `row.Description` via attribute access and then manually calls `.upper()` again, because `_dsc` column is renamed by `itertuples` (it prepends `_` to columns starting with `_`). This is already noted in a comment. A cleaner fix would be to rename the column to something without a leading underscore (e.g. `_dsc` → `dsc_upper`) before the loop.

---

## 🔍 Readability Issues

### 9. `mechanics.py` imports `is_share_row` / `is_option_row` from `ui_components`  
**File:** `mechanics.py`, line 44  

```python
from ui_components import is_share_row, is_option_row
```

`mechanics.py` is documented as the pure analytics layer with no UI dependency. `is_share_row` and `is_option_row` are simple string checks — they belong in `ingestion.py` or `config.py`, not in `ui_components`. This is the only place the dependency chain is violated. Moving these two functions to `ingestion.py` (they are already closely related to `equity_mask` and `option_mask`) would restore the clean one-way chain.

---

### 10. `tastymechanics.py` — private UI helpers imported with leading underscore  
**File:** `tastymechanics.py`, line 31  

```python
from ui_components import (
    _fmt_ann_ret, _style_ann_ret, _style_chain_row,
    _color_cash_row, _color_cash_total,
    ...
)
```

Functions with a leading underscore conventionally mean "internal, do not import." If these are genuinely needed in the app layer, either rename them (drop the underscore) or group them into a small public API in `ui_components.py`. The current import list reads as "we're reaching into private internals," which undermines the module boundary.

---

### 11. `mechanics.py` — `current: Campaign = None` is not type-safe  
**File:** `mechanics.py`, line 299  

```python
current: Campaign  = None
```

The type annotation says `Campaign` but the value is `None`. This should be `Optional[Campaign] = None` (or `Campaign | None = None` in Python 3.10+). As-is, any type checker will flag this.

---

### 12. `build_closed_trades` — Union-Find functions defined inside a function  
**File:** `mechanics.py`, lines 469–473  

```python
parent = {}
def find(x): ...
def union(a, b): ...
```

Defining functions inside another function makes them invisible to tests and the stack frame is recreated on every call to `build_closed_trades`. These could be extracted to module-level (or at least to named inner helpers). This is a minor style point but it does make the algorithm harder to unit-test in isolation.

---

### 13. `tastymechanics.py` — inline `elif` chains for time window selection  
**File:** `tastymechanics.py`, lines 559–566  

The time window mapping is a flat if/elif chain. A lookup dict would be cleaner, more extensible, and easier to scan:

```python
# Current
if   selected_period == 'All Time':      start_date = df['Date'].min()
elif selected_period == 'YTD':           start_date = pd.Timestamp(latest_date.year, 1, 1)
# ...

# Suggested
_WINDOW_MAP = {
    'All Time':       lambda: df['Date'].min(),
    'YTD':            lambda: pd.Timestamp(latest_date.year, 1, 1),
    'Last 7 Days':    lambda: latest_date - timedelta(days=7),
    # ...
}
start_date = _WINDOW_MAP.get(selected_period, lambda: df['Date'].min())()
```

---

### 14. `tastymechanics.py` — `APP_VERSION` not bumped  
**File:** `tastymechanics.py`, line 146  

```python
APP_VERSION = "v25.9"
```

The journal entry says "Version bump to v25.10 pending." This is the only remaining mechanical task from the last session.

---

## 🏗️ Maintainability Notes

### 15. `_write_test_snapshot` signature has 22 positional parameters  
**File:** `tastymechanics.py`, line 177  

The snapshot helper takes 22 positional arguments. If a new metric is added to the snapshot, it's easy to shift an argument out of position silently. Consider passing a single dict or dataclass (most of these variables are already assembled by that point in `main()`).

---

### 16. `tastymechanics.py` is 2,147 lines — consider splitting tabs  
The app file has grown significantly. Each tab is largely self-contained. Splitting into `tabs/tab_overview.py`, `tabs/tab_derivatives.py` etc. (each returning a renderable function) would make individual features much easier to navigate and test. This is medium-effort work but pays dividends as complexity grows.

---

### 17. No test coverage for `build_option_chains` or `calc_dte`  
**File:** `test_tastymechanics.py`  
The test suite covers FIFO, campaigns, windowed P/L, and P/L totals well. `build_option_chains` and `calc_dte` have no tests. Edge cases to add: expired-same-day options (`dte = 0`), chain gap detection across the `ROLL_CHAIN_GAP_DAYS` boundary, and chains where the long BTO leg appears.

---

## Summary Table

| # | File | Severity | Category | One-liner |
|---|------|----------|----------|-----------|
| 1 | mechanics.py | Medium | Bug | Division by zero if a zero-qty equity row reaches FIFO |
| 2 | mechanics.py | Medium | Bug | Split ratio wrong if TastyTrade addition qty differs from running_shares |
| 3 | mechanics.py | Low | Bug | `pure_options_pnl` window is `<=` not `<` — potential double-count on campaign close date |
| 4 | mechanics.py | Low | Bug | Rolled trade `open_date` uses earliest leg — undocumented, suppresses Ann Return % |
| 5 | mechanics.py | Low | Bug | Extra capital deployed uses average cost, not FIFO remainder |
| 6 | tastymechanics.py | Low | Bug | `realized_ror` not recomputed after zero-cost exclusion filter |
| 7 | mechanics.py | Low | Bug | BTO chain legs silently dropped — chain log incomplete for spreads |
| 8 | ingestion.py | Trivial | Perf | `_dsc` rename workaround — rename column to avoid leading underscore |
| 9 | mechanics.py | Medium | Readability | `is_share_row`/`is_option_row` imported from ui_components — breaks dependency chain |
| 10 | tastymechanics.py | Low | Readability | Private `_` functions imported from ui_components |
| 11 | mechanics.py | Low | Readability | `current: Campaign = None` missing `Optional` annotation |
| 12 | mechanics.py | Low | Readability | Union-Find defined inside function — untestable |
| 13 | tastymechanics.py | Trivial | Readability | if/elif window chain — dict lookup would be cleaner |
| 14 | tastymechanics.py | Trivial | Maintainability | `APP_VERSION` not bumped to v25.10 |
| 15 | tastymechanics.py | Low | Maintainability | 22-param snapshot function — fragile positional args |
| 16 | tastymechanics.py | Low | Maintainability | 2,147-line app file — consider tab splitting |
| 17 | test_tastymechanics.py | Low | Maintainability | No tests for `build_option_chains` or `calc_dte` |

---

## Recommended Fix Order

1. **Fix #6 first** — `realized_ror` inconsistency when zero-cost exclusion is active is a silent wrong number in a displayed metric.  
2. **Fix #3** — `<=` vs `<` in `pure_options_pnl` is a correctness issue that could affect any account where an option and share sale land on the same date.  
3. **Fix #9** — moving `is_share_row`/`is_option_row` to `ingestion.py` restores the clean architecture and is a low-risk refactor.  
4. **Fix #1** — add zero-qty guard to FIFO engine (one-liner).  
5. **Fix #14** — bump version to v25.10.
