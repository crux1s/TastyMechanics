# Architecture

TastyMechanics is split into focused modules with a strict one-way dependency chain. No module imports from the one above it in the chain.

---

## Module structure

```
config.py                    Constants + COLOURS palette — OPT_TYPES, TRADE_TYPES, KNOWN_INDEXES, thresholds, patterns
models.py                    Dataclasses — Campaign, AppData, ParsedData
ingestion.py                 CSV parsing — pure Python, no Streamlit dependency
mechanics.py                 Analytics engine — FIFO, campaigns, trade classification
ui_components.py             Visual helpers — formatters, colour functions, chart builders
market_data.py               Live price fetcher — yfinance wrapper, 5-min cache, opt-in only
report.py                    HTML report export — self-contained, no Streamlit dependency
report_prompt.py             AI review prompt generator — portfolio summary for LLM analysis
tabs/landing.py              Landing page renderer (shown before CSV upload)
tabs/tab0_open_positions.py  Open Positions tab renderer
tabs/tab1_derivatives.py     Derivatives Performance tab renderer
tabs/tab2_trade_analysis.py  Discipline & Patterns tab renderer
tabs/tab3_wheel_campaigns.py Wheel Campaigns tab renderer
tabs/tab4_all_trades.py      Portfolio P/L tab renderer
tabs/tab5_deposits.py        Deposits, Dividends & Fees tab renderer
tastymechanics.py            Streamlit wiring — sidebar, cache wrappers, tab orchestration
```

**Dependency direction (one way only):**
```
tastymechanics.py
    └── tabs/landing.py
    └── tabs/tab0_open_positions.py
    └── tabs/tab1_derivatives.py
    └── tabs/tab2_trade_analysis.py
    └── tabs/tab3_wheel_campaigns.py
    └── tabs/tab4_all_trades.py
    └── tabs/tab5_deposits.py
    └── report.py
    └── report_prompt.py
    └── market_data.py
    └── ui_components.py
    └── mechanics.py
            └── ingestion.py
                    └── models.py
                            └── config.py
```

---

## Data flow

```
CSV upload (bytes)
  └── load_and_parse(file_bytes)          @st.cache_data(max_entries=2)
        └── parse_csv() → ParsedData      ingestion.py
              └── compute_app_data()      mechanics.py → AppData
                    └── window slices     recomputed on selector change (fast, uncached)
```

---

## Tab structure

| Tab | File | Description |
|---|---|---|
| 📡 Open Positions | tab0_open_positions.py | Active positions, live prices, expiry alerts |
| 📈 Derivatives Performance | tab1_derivatives.py | Premium-selling scorecard, call/put breakdown |
| 🔬 Discipline & Patterns | tab2_trade_analysis.py | ThetaGang metrics, equity curves, DTE discipline, trade log |
| 🎯 Wheel Campaigns | tab3_wheel_campaigns.py | Campaign cards, roll chains, effective basis |
| 📊 Portfolio P/L | tab4_all_trades.py | Cumulative equity curve, per-ticker P/L, period comparison |
| 💰 Deposits, Dividends & Fees | tab5_deposits.py | Cash movements for selected window |

---

## Key design decisions

### Pure analytics layer
`mechanics.py` has zero Streamlit imports. Every function is independently importable and testable without a running server. This is what makes the test suite possible.

### Thin cache wrappers
`@st.cache_data` lives only in `tastymechanics.py`. DataFrame and `ParsedData` parameters are prefixed with `_` to skip hashing — hashing a large DataFrame on every rerun is more expensive than running the math cold. Only small scalar arguments like `use_lifetime: bool` are hashed.

### main() entry point
All rendering code runs inside `main()` so figure objects, intermediate DataFrames, and local variables are freed when the function returns, rather than persisting as module globals for the lifetime of the server process.

### COLOURS palette
`config.py` defines a 13-colour `COLOURS` dict (`green`, `red`, `orange`, `blue`, `text`, `text_muted`, `text_dim`, `border`, `card_bg`, `card_bg2`, `tan`, `white`, `header_text`). `ui_components.py` references these by name throughout. Changing the whole UI colour scheme requires editing only `config.py`.

### KNOWN_INDEXES
`config.py` contains an explicit `KNOWN_INDEXES` set — `{SPX, SPXW, NDX, RUT, VIX, XSP, NANOS, DJX, OEX}` — used to correctly calculate Capital Risk for cash-settled index options. This prevents high-priced equities (MSTR, NFLX, AVGO) from being misclassified as indexes based on strike price alone.

### Naive UTC everywhere
TastyTrade exports UTC timestamps. These are parsed as UTC then immediately stripped to naive (no timezone). No conversion to US/Eastern is performed. All dates are consistently offset by the same amount — calculations are unaffected, and DST complexity is avoided entirely.

### Single FIFO engine
`_iter_fifo_sells()` in `mechanics.py` is the sole source of truth for equity cost basis. It maintains a separate deque per ticker and yields `(date, proceeds, cost_basis)` tuples. Callers apply their own window filtering and bucketing.

### AppData dataclass
`compute_app_data()` returns a typed `AppData` dataclass, not a positional tuple. Fields are named and self-documenting. Safe to extend without breaking callers.

### Union-Find trade grouping
Multi-leg option trades are grouped using a Union-Find (disjoint set) algorithm on order IDs. Legs sharing an order ID are unioned into one group. This correctly handles iron condors, strangles, and spreads placed as a single order, regardless of how many individual rows TastyTrade generates.

### LEAPS separation
Trades with DTE > 90 at open are excluded from ThetaGang short-premium metrics and surfaced as a separate callout. This prevents long-dated positions from distorting win rate, capture %, and management rate statistics.

### Candlestick P/L charts
Weekly and monthly P/L charts use `go.Candlestick` rather than bar charts. Open/High/Low/Close are computed from the running cumulative P/L equity curve within each period — open = where the curve stood at period start, close = where it stood at period end, high/low = the intra-period extremes. This reveals intra-period volatility invisible in simple bar charts.

### HTML report export
`build_html_report()` produces a fully self-contained HTML file. Plotly figures are embedded via `fig.to_html(include_plotlyjs='cdn')` on the first chart, `False` on subsequent ones (CDN loaded once, reused). The report has two scorecard sections: Portfolio Overview (total P&L, dividends, interest, fees, net deposited) and Options Trading — Credit Trades Only (win rate, capture, profit factor etc.). This distinction prevents trading metrics being misread as portfolio-level numbers.

### Python version compatibility
f-strings in `ui_components.py` use pre-extracted local variables (`_g = COLOURS['green']`) rather than dict key lookups inside the f-string braces. This avoids a Python 3.12-only syntax feature (same-quote dict keys in f-string expressions) and ensures the app runs on Python 3.10+.

---

## Adding a new metric

1. Add the calculation to `mechanics.py` — keep it pure Python, no Streamlit
2. Add the result to the `AppData` dataclass in `models.py` if it needs to be passed to the UI
3. Add rendering in the appropriate `tabs/tabN_*.py` file
4. Add tests to `test_tastymechanics.py` using real CSV values

---

## Adding a new config constant

Add to `config.py` only. Import in `mechanics.py` or `ingestion.py` as needed. Never hardcode thresholds inline — all tunable values belong in `config.py`.
