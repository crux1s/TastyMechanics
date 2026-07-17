# TastyMechanics — Codex Context

A Streamlit dashboard for wheel traders and theta harvesters on TastyTrade. Analyzes CSV transaction exports to produce realized P/L, wheel campaign tracking, premium selling scorecard, and portfolio analytics.

---

## Development Environment

Always use the virtual environment's Python to run commands (e.g., `python3 -m streamlit run` or `.venv/bin/streamlit`) instead of calling tools like `streamlit` directly, as they may not be on PATH.

---

## Running the App

```bash
python3 -m streamlit run tastymechanics.py
```

The `streamlit` binary is not on PATH — always invoke via `python3 -m streamlit`.

---

## Running the Test Suite

Always run after any change:

```bash
PYTHONIOENCODING=utf-8 python3 test_tastymechanics.py
```

Expected: `431 tests | 431 passed | 0 failed` (31 sections, with section 0 = end-to-end smoke check)

The `PYTHONIOENCODING=utf-8` prefix is required on Windows — omitting it causes a `charmap` codec error on the Unicode characters in test output.

To debug a failing section, scan stdout for the section header (e.g., `── 17.`) — the test file has no per-section runner.

Syntax check all files before presenting output:

```bash
python3 -c "import ast; ast.parse(open('mechanics.py').read()); print('OK')"
```

---

## Data Flow

```
CSV bytes
  → parse_csv()       → ParsedData(df, split_events, zero_cost_rows)   [ingestion.py]
  → build_all_data()  → AppData(all_campaigns, closed_trades_df, …)    [mechanics.py]
  → window slice      → df_window, windowed P/L figures                 [tastymechanics.py]
  → tab renderers     → display                                          [tabs/]
```

`load_and_parse` and `build_all_data` are Streamlit-cached. `get_daily_pnl` is cached separately with an explicit `_file_hash` (hashlib md5 of raw bytes) so it invalidates on new uploads.

`ingestion.py` raises `CSVParseError` (base) → `CSVEncodingError`, `CSVStructureError`, `CSVDateParseError`. The Streamlit layer catches `CSVParseError` and surfaces the message to the user.

---

## Module Structure

Strict one-way dependency chain — no module imports from above it:

```
config.py              Constants, COLOURS palette, thresholds, known indexes
models.py              Dataclasses — Campaign, AppData, ParsedData
ingestion.py           CSV parsing — no Streamlit dependency
mechanics.py           FIFO engine, campaign logic, trade classification
ui_components.py       Formatters, colour functions, chart helpers
market_data.py         Live price fetcher — yfinance wrapper, 5-min cache, opt-in only
                       Also exposes bs_greeks() and returns iv/beta per ticker
report.py              HTML report export — self-contained tabbed dashboard, no Streamlit/Plotly dependency
position_snapshot.py   Plain-text position snapshot for AI review — no Streamlit dependency
tabs/landing.py        Landing page renderer (shown before CSV upload)
tabs/tab0–tab5         One renderer per tab, imported by tastymechanics.py
tastymechanics.py      Streamlit wiring — sidebar, cache, tab orchestration
```

---

## Key Conventions

**COLOURS** — all colours come from `config.py COLOURS` dict. Never add hardcoded hex values anywhere outside the CSS block in `tastymechanics.py`. Single source of truth.

**FIFO_EPSILON** — use `abs(qty) > FIFO_EPSILON` not `qty != 0` for zero-quantity guards. Consistent with the FIFO engine throughout.

**Cache keys** — `build_all_data` and `get_daily_pnl` take `_parsed`/`_df` with underscore prefix (Streamlit skips hashing). Always pass `_file_hash` (hashlib.md5 of raw bytes) as an explicit argument so the cache invalidates on new file upload. Never use `hash()` — not stable across processes.

**Campaign aggregation** — always use `_aggregate_campaign_pnl(all_campaigns, use_lifetime)` from `mechanics.py`. Never inline the three generator expressions — they existed in two places and caused a bug.

**Trade classification** — `_classify_trade_type()` and `_calculate_capital_risk()` are pure module-level functions in `mechanics.py`. Do not embed classification logic back into `build_closed_trades()`.

**DTE thresholds** — `DTE_ALERT_CRIT = 5` and `DTE_ALERT_WARN = 14` live in `config.py`. Never hardcode 5 or 14 in UI code.

**xe()** — `xe(s)` in `ui_components.py` escapes strings for HTML. Every dynamic value interpolated into an f-string HTML template must pass through `xe()`.

**report.py (the dashboard)** — `build_html_report()` emits a self-contained tabbed dashboard (Overview / Performance / Wheel & Discipline / Trade Log) with hand-rolled inline-SVG equity curve + OHLC candlesticks, sortable tables, and vanilla JS — no Plotly, no CDN, no Streamlit. The big HTML/CSS/JS lives in the `_TEMPLATE` string (token `__NAME__` substitution, NOT f-strings, so CSS/JS braces need no escaping). `_dashboard_data()` derives the single `DATA` dict it bakes in, computed from the args `build_html_report` already receives — ThetaGang management rate from `all_cdf['Close Reason']`, concentration from premium-by-ticker in `credit_cdf`, so there's no raw-df dependency. The hero **MWR pill** comes from the optional `portfolio_perf` kwarg (the `portfolio_metrics()` dict the app already computes); `_dashboard_data` resolves `mwr_mtm` else `mwr_realized` and keeps it `None` (not `_r`-zeroed) when XIRR is undefined so the pill renders `—`. All-time-vs-window split: scorecard / breakdowns / candles / per-ticker / Trade Log reflect the window-sliced `all_cdf`/`credit_cdf`; the Portfolio Realized P/L curve uses full-history `daily_pnl_all`. The **Trade Log** tab (`DATA.trades`) is a faithful port of the app's "📋 Full Closed Trade Log" expander in `tabs/tab2_trade_analysis.py` — same 16 columns, same order, same most-recent-close-first default sort; if you change the columns in one place, change both. The **Short Calls vs Short Puts** card renderer (`DATA.cvp`) handles three `Type` values — `Call`/`Put`/`Mixed` (strangles, straddles, jade lizards, etc.); the JS labels by explicit `PUT`/`CALL` substring so `Mixed` gets its own 🎭 card rather than falling through to a second "Short Puts" card. Signature is append-only — new inputs go on as trailing optional kwargs (e.g. `portfolio_perf=None`); `tastymechanics.py` calls it with fixed kwargs.

**Long-term performance (`portfolio_metrics` + `xirr`)** — `portfolio_metrics()` in `mechanics.py` is pure/Streamlit-free and returns the dict the Tab 4 "Long-Term Performance" section displays (MWR/XIRR, CAGR on deposits, max drawdown, Calmar, monthly stats). `xirr()` is a hand-rolled bisection solver (no numpy/scipy; bracket from `XIRR_*` constants in `config.py`); returns `None` for <2 flows, all-same-sign, or an unbracketed root — never fabricates a rate. Cash flows are dated deposits/withdrawals, sign convention money-out-of-pocket negative; the terminal flow is `net_deposited + total_realized_pnl` (realized) or `+ unrealized_total` (MTM, when the Live toggle supplied it). `tastymechanics.py` builds `_cash_flows` near `net_deposited` (~:652) and computes `_perf` **after the MTM block** so the MTM terminal can use `_mtm.total`. **TWR and a true Sharpe are deliberately not computed** — they need a daily account-value (NLV) series the CSV lacks; don't add a faked version.

**realized_pnl()** — for closed campaigns includes `exit_proceeds`. For open campaigns it's premiums + dividends only. `use_lifetime=True` always returns premiums + dividends regardless of status (strips equity component for House Money mode).

**effective_basis()** — `use_lifetime=True` returns raw `blended_basis` (no premium offset). Default returns `(total_cost - premiums - dividends) / total_shares`.

**Campaign event types** — `c.events` is a list of dicts `{date, type, detail, cash}`. Known types: `'Entry'`, `'Add'`, `'Exit'`, `'Assignment Put (STO)'` (entry via put assignment — put credit excluded from cost basis, triggers amber card banner in tab3), `'Mid-campaign Assignment'` (shares added mid-campaign via put assignment — premium IS already in basis, triggers blue card banner). The Share & Dividend Events table filters out any event type containing 'assign' (case-insensitive), so assignment events are card-only. Detection in `build_campaigns()`: `_find_assignment_premium(t, row)` is called on both the entry branch and the add-to-existing branch.

**Strategy classifier labels** — `_classify_trade_type()` returns direction-aware butterfly labels: `'Long Call/Put Butterfly'` (buy wings, sell body) and `'Short Call/Put Butterfly'` (sell wings, buy body ×2). Iron Condor variants: `'Iron Butterfly'` (short legs share same ATM strike), `'Reverse Iron Butterfly'` (long legs share same ATM strike), `'Iron Condor'` (credit, short legs at different strikes), `'Reverse Iron Condor'` (debit). Both `_classify_trade_type()` and `_calculate_capital_risk()` now consume the same `_LegInfo` dataclass built by `_derive_leg_info(grp, opens)` — any structure-detection change (butterfly flags, jade/ratio lizard conditions, leg-quantity aggregates) must happen in `_derive_leg_info` only. Never re-derive `has_sc`/`has_sp`/`is_butterfly` inline in either consumer.

**Covered call capital at risk** — `_calculate_capital_risk()` takes optional `campaign_windows`, `open_date`, and `campaign_basis` (`{ticker: [(start, end, basis_per_share)]}`). Inside an active wheel window: a pure covered call (`has_sc and not has_lc and not has_sp`) uses `basis_per_share × mult` — the stock actually pinned by the position, same scale as a CSP's `strike × mult`. Premium-as-capital (the v26.12 interim fix) made `Daily θ %` degenerate to `100/dte_open` (premium cancels out) and pegged `Ann Return %` at ±cap on every covered call; it remains only as the fallback when no basis is supplied. A covered strangle / straddle (`has_sc and has_sp` with no longs) uses `put_strike × mult − abs(open_credit)`. `compute_app_data` builds `_camp_basis` from `total_cost / shares_acquired` — the `Campaign.shares_acquired` field (cumulative buys, split-adjusted, never reduced by sales) exists precisely because `blended_basis` is zeroed when a campaign closes.

**`unknown_action_rows` defensive scan** — `parse_csv` runs `detect_unknown_actions(df)` after `Net_Qty_Row` is computed and surfaces any `Trade` / `Receive Deliver` row that has non-zero `Quantity` but `Net_Qty_Row == 0`. Split removals and cash-settled / symbol-change Sub Types are allow-listed (`_LEGITIMATE_ZERO_SUB_TYPE_FRAGMENTS` in `ingestion.py`). The list is exposed on `ParsedData.unknown_action_rows` (defaults to `[]`) and shown as a red banner in `tastymechanics.py main()` ahead of the corporate-action expander. If a new TastyTrade format adds a legitimate zero-share Sub Type that isn't a split or cash-settled, append the fragment to that allow-list — don't widen the detector.

**Daily θ % uses DTE-at-open, not days-held** — formula is `open_credit / max(dte_open, 1) / capital_risk * 100`, capped at `DAILY_THETA_CAP`. This is a setup-quality / entry-yield metric. Using `days_held` would make closing winners fast inflate the number, which was the original bug. `Ann Return %` (which still uses days-held) is kept on the per-trade row but is no longer aggregated anywhere — its medians are mathematically degenerate on mixed-duration books.

**Odd-lot share pool** — `build_campaigns()` (non-lifetime path) pools share buys below `WHEEL_MIN_SHARES` while no campaign is open (`pool_shares`/`pool_cost`/`pool_events`) and folds them into the next qualifying entry — trigger is `qty + pool_shares >= WHEEL_MIN_SHARES`, so accumulation entries (60+60) start a campaign. `start_date` stays the qualifying-entry row's date so option-premium windowing and `pure_options_pnl()` bucketing are unchanged; pool events carry their real (earlier) dates in the event log. Mid-campaign adds accept any size (`qty > FIFO_EPSILON`) — an 8-share top-up blends in. Sales while only the pool is held shrink it proportionally. A pool that never reaches a campaign stays invisible (wheel = 100-lot intent). The wheel-ticker candidate filter in `compute_app_data` matches: cumulative positive equity `Net_Qty_Row` per ticker ≥ threshold, not a single 100-lot row. Partial sales inside a campaign keep the carry-full-cost convention — remaining shares carry all remaining `total_cost` (basis display rises after a below-basis partial sale; the sale's P/L settles at campaign close via `exit_proceeds`).

**Campaign same-timestamp close** — when a stock exit and option BTC share the exact order timestamp, `Sort_Inst=0` processes the equity row first and seals `current → None`, so naively the BTC won't see a campaign. `build_campaigns()` keeps a `just_closed` reference and routes same-timestamp closing legs into it. `pure_options_pnl()` uses an **inclusive** end boundary (`<= c.end_date`) so the same row isn't double-counted in the outside-window bucket. If you change either side, change both.

**Time window** — `TIME_OPTIONS` is a module-level constant in `tastymechanics.py` (10 presets). `_render_date_picker()` is a module-level helper using `st.popover` (requires Streamlit ≥ 1.31). In `main()`, `end_date` equals `latest_date` for all presets except Custom — all window slices, `calculate_windowed_equity_pnl()`, `_daily_pnl`, and tab render calls use `end_date` as the upper bound, not `latest_date`. The old `tw_tab1/2/4/5` session state keys and the pre-sync loop no longer exist.

**market_data.py** — `fetch_live_prices()` returns `'iv'` (implied volatility) and `'beta'` per ticker alongside `last`/`prev_close`/`options`. Beta is computed from `yf.download()` 90-day rolling returns vs SPY — **do not use `yf.Ticker().info`** for beta, it is rate-limited and returns None silently. `bs_greeks(S,K,T,r,sigma,cp)` returns `{delta, gamma, theta, vega}` per-contract using pure `math` stdlib.

**live_prices remap strips keys** — the remap loop in `tab0_open_positions.py` rebuilds the dict field-by-field. Any new key added to `fetch_live_prices()` output must be explicitly passed through or it is silently dropped. Current keys: `last`, `prev_close`, `options`, `beta`.

**position_snapshot.py** — `build_position_snapshot()` takes `df_open`, `all_campaigns`, `all_cdf`, `credit_cdf`, `live_prices`, `latest_date`, and scalar P/L fields. Called from `tab0_open_positions.py` with the `live_prices` already fetched by the Live toggle (SPY always included via `| {'SPY'}` in `tickers_frozen`). Greeks are shown position-adjusted (short put → +Δ, −Γ, +θ, −ν) to match TastyTrade's convention.

---

## Important Files

- `ROADMAP.md` — pending work, prioritised
- `Known-Limitations.md` — what doesn't work or is untested
- `test_tastymechanics.py` — 431 tests, 31 sections (section 0 = compute_app_data end-to-end smoke check; gates the rest)
- `config.py` — `KNOWN_INDEXES`, `COLOURS`, `DTE_*`, `WIN_RATE_*`, `FIFO_EPSILON`

---

## Things NOT to Do

- Don't add hardcoded hex colours — use `COLOURS` dict
- Don't use `hash()` for cache keys — use `hashlib.md5(...).hexdigest()`
- Don't inline campaign aggregation — use `_aggregate_campaign_pnl()`
- Don't embed trade classification in `build_closed_trades()` — use the pure helpers
- Don't use `qty != 0` — use `abs(qty) > FIFO_EPSILON`
- Don't add bullet point lists to prose responses — project owner prefers clean prose
- Don't use `yf.Ticker().info` for beta — it is rate-limited; use `yf.download()` rolling returns
- Don't add new keys to `fetch_live_prices()` return dict without also passing them through the remap loop in `tab0_open_positions.py`
- Don't add `.iloc[0]` without an empty guard
- Don't implement external file formats by guessing — ask for a real sample first (column names, ordering, and value formats can differ from what seems obvious)
- Don't reintroduce a `Median Ann. Return` aggregate — its formula extrapolates `365/days_held` and the median pegs at the cap on any mixed weekly/swing book. Per-trade column only.
- Don't compute `Daily θ %` using `days_held` — use `dte_open`. Closing winners fast must not inflate the entry-quality score.
- Don't open PRs or run `gh pr create` unless the user explicitly asks. After finishing work, stop at "ready to PR" and wait for the user to invoke `/create-pr` or say "open a PR". This applies even when the work is clearly PR-shaped (full feature, all tests passing, changelog updated). Same rule for `gh pr merge` — never merge without explicit instruction.

---

## What's Left (from ROADMAP.md)

**Waiting on real CSV data:**
- Stock split test
- Futures open position test

**Features (parked):**
- 0DTE support — quick wins, new metrics, strategy mode selector
- Scroll-to on Wheel Campaign table — not achievable in Streamlit
- Beta-weighted delta accuracy — yfinance rolling beta is a reasonable approximation; TastyTrade API would give exact real-time betas and account-level NLV/BP
- IVR (IV Rank) — requires 52-week IV history; not available from yfinance; TastyTrade API only

---

## Trading Style Context

Built for **wheel trading and theta harvesting** on TastyTrade — short puts, covered calls, strangles, iron condors, multi-day holds. General options trading supported. 0DTE works but some metrics are less meaningful for same-day trades.

This is a personal project that works for the owner's trading style. Others are welcome to fork and customise. Not built for feature requests.
