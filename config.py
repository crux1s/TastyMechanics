"""
TastyMechanics — Configuration & Constants
===========================================
All tuneable parameters and TastyTrade CSV field values live here.
Change a value once and it applies everywhere.
"""

import re as _re

_FUTURES_CONTRACT_RE = _re.compile(r'[FGHJKMNQUVXZ]\d+$')

# ── TastyTrade instrument type strings ────────────────────────────────────────
OPT_TYPES   = ['Equity Option', 'Future Option']
EQUITY_TYPE = 'Equity'

# ── TastyTrade transaction type strings ───────────────────────────────────────
TRADE_TYPES = ['Trade', 'Receive Deliver']
MONEY_TYPES = ['Trade', 'Receive Deliver', 'Money Movement']

# ── TastyTrade sub-type strings (exact-match values) ─────────────────────────
SUB_SELL_OPEN  = 'sell to open'
SUB_ASSIGNMENT = 'assignment'
SUB_DIVIDEND   = 'Dividend'
SUB_CREDIT_INT = 'Credit Interest'
SUB_DEBIT_INT  = 'Debit Interest'

INCOME_SUB_TYPES  = [SUB_DIVIDEND, SUB_CREDIT_INT, SUB_DEBIT_INT]
DEPOSIT_SUB_TYPES = [
    'Deposit', 'Withdrawal',
    SUB_DIVIDEND, SUB_CREDIT_INT, SUB_DEBIT_INT,
    'Balance Adjustment',
]

# ── Sub-type pattern fragments (for .str.contains() matching) ─────────────────
PAT_CLOSE    = 'to close'
PAT_EXPIR    = 'expir'
PAT_ASSIGN   = 'assign'
PAT_EXERCISE = 'exercise'
PAT_CLOSING  = f'{PAT_CLOSE}|{PAT_EXPIR}|{PAT_ASSIGN}|{PAT_EXERCISE}'

# ── Wheel strategy ────────────────────────────────────────────────────────────
# Minimum share purchase that starts a wheel campaign.
WHEEL_MIN_SHARES = 100

# ── LEAPS separation ──────────────────────────────────────────────────────────
# Trades with DTE at open above this threshold are classified as LEAPS and
# excluded from ThetaGang short-premium metrics (management rate, median DTE).
LEAPS_DTE_THRESHOLD = 90

# ── Roll chain heuristic ──────────────────────────────────────────────────────
# If a position goes flat and the next STO is more than this many days later,
# a new roll chain starts rather than continuing the existing one.
ROLL_CHAIN_GAP_DAYS = 3

# ── Futures options multipliers (dollars per index/price point) ───────────────
# Used by _calculate_capital_risk() to convert strike-width to dollar risk.
# Strip the contract month (e.g. /MESM6 → /MES) before looking up.
# Equity options always use 100; futures use their contract spec multiplier.
#
# TODO: if you trade a futures product not listed here, Capital at Risk will
# silently fall back to the equity multiplier (100), which will be wrong.
# Add the root symbol and its CME contract spec multiplier ($/point) below
# and verify against a known trade in your CSV before relying on the figure.
FUTURES_MULTIPLIERS = {
    # ── Equity index ──────────────────────────────────────────────────────────
    '/MES':  5,        # Micro E-mini S&P 500        (5 × index)
    '/ES':   50,       # E-mini S&P 500              (50 × index)
    '/MNQ':  2,        # Micro E-mini Nasdaq-100     (2 × index)
    '/NQ':   20,       # E-mini Nasdaq-100           (20 × index)
    '/M2K':  5,        # Micro E-mini Russell 2000   (5 × index)
    '/RTY':  50,       # E-mini Russell 2000         (50 × index)
    '/MYM':  0.5,      # Micro E-mini Dow Jones      (0.50 × index)
    '/YM':   5,        # E-mini Dow Jones            (5 × index)
    # ── Volatility ────────────────────────────────────────────────────────────
    '/VX':   1_000,    # CBOE VIX Futures            (1,000 × VIX)
    # ── Energy ────────────────────────────────────────────────────────────────
    '/CL':   1_000,    # WTI Crude Oil               (1,000 bbl; strikes in $/bbl)
    '/MCL':  100,      # Micro WTI Crude Oil         (100 bbl)
    '/NG':   10_000,   # Natural Gas                 (10,000 MMBtu; strikes in $/MMBtu)
    '/RB':   42_000,   # RBOB Gasoline               (42,000 gal; strikes in $/gal) — verify on first use
    '/HO':   42_000,   # Heating Oil / ULSD          (42,000 gal; strikes in $/gal) — verify on first use
    # ── Metals ────────────────────────────────────────────────────────────────
    '/GC':   100,      # Gold                        (100 troy oz; strikes in $/oz)
    '/MGC':  10,       # Micro Gold                  (10 troy oz)
    '/SI':   5_000,    # Silver                      (5,000 troy oz; strikes in $/oz)
    '/SIL':  1_000,    # Micro Silver                (1,000 troy oz) — verify ticker on first use
    '/MSI':  1_000,    # Micro Silver (alt ticker)
    '/HG':   25_000,   # Copper                      (25,000 lb; strikes in $/lb) — verify on first use
    # ── Interest rates ────────────────────────────────────────────────────────
    '/ZB':   1_000,    # 30-yr T-Bond                ($100K face; 1 pt = $1,000)
    '/ZN':   1_000,    # 10-yr T-Note                ($100K face; 1 pt = $1,000)
    '/ZF':   1_000,    # 5-yr T-Note                 ($100K face; 1 pt = $1,000)
    '/ZT':   2_000,    # 2-yr T-Note                 ($200K face; 1 pt = $2,000)
    # ── Agriculture (grain strikes quoted in cents/bushel; 1 cent = $50) ─────
    '/ZC':   50,       # Corn                        (5,000 bu; 1¢/bu = $50)
    '/ZS':   50,       # Soybeans                    (5,000 bu; 1¢/bu = $50)
    '/ZW':   50,       # Wheat                       (5,000 bu; 1¢/bu = $50)
    '/ZL':   600,      # Soybean Oil                 (60,000 lb; 1¢/lb = $600)
    '/ZM':   100,      # Soybean Meal                (100 short tons; $1/ton = $100)
    '/HE':   400,      # Lean Hogs                   (40,000 lb; 1¢/lb = $400)
    '/LE':   400,      # Live Cattle                 (40,000 lb; 1¢/lb = $400)
    '/GF':   500,      # Feeder Cattle               (50,000 lb; 1¢/lb = $500)
    # ── Currencies (strikes in USD per foreign unit) ──────────────────────────
    '/6E':   125_000,  # Euro FX                     (€125,000)
    '/6B':   62_500,   # British Pound               (£62,500)
    '/6J':   1_250_000, # Japanese Yen              (¥12,500,000; quoted per ¥100 = ×100 reduction, net ×1.25M) — verify on first use
    '/6A':   100_000,  # Australian Dollar           (A$100,000)
    '/6C':   100_000,  # Canadian Dollar             (C$100,000)
    '/6S':   125_000,  # Swiss Franc                 (CHF 125,000)
    '/6N':   100_000,  # New Zealand Dollar          (NZD 100,000)
    '/6M':   500_000,  # Mexican Peso                (MXN 500,000) — verify on first use
}


def get_opt_multiplier(ticker: str, instrument_type: str) -> float:
    """Return the dollars-per-point multiplier for one option leg.

    For equity options always returns 100.  For future options, strips the
    contract-month suffix (e.g. /MESM6 → /MES) and looks up FUTURES_MULTIPLIERS,
    falling back to 100 if the root is not in the table.
    """
    if instrument_type != 'Future Option':
        return 100
    root = _FUTURES_CONTRACT_RE.sub('', ticker.strip())
    return FUTURES_MULTIPLIERS.get(root, 100)


# ── Index option detection ────────────────────────────────────────────────────
# Strikes above this threshold are treated as index underlyings (SPX, NDX,
# RUT, VIX etc.) rather than equity options. Used in capital_risk calculation
# for naked shorts: equity options use strike × 100 (theoretical max loss);
# index options use premium received (margin-based, not theoretical zero).
# $500 sits safely above the highest-priced equity options (BRK.A aside) and
# well below the lowest common index strike (RUT ~2000, SPX ~5000).
# Explicit list of cash-settled index underlyings.
# Using a known list instead of a strike price heuristic prevents
# high-priced equities (MSTR, NFLX, AVGO etc.) being misclassified as indexes.
KNOWN_INDEXES = {'SPX', 'SPXW', 'NDX', 'RUT', 'VIX', 'XSP', 'NANOS', 'DJX', 'OEX'}

# ── Corporate action detection ────────────────────────────────────────────────
# TastyTrade Description field patterns for stock splits and zero-cost deliveries.
SPLIT_DSC_PATTERNS   = ['FORWARD SPLIT', 'REVERSE SPLIT', 'STOCK SPLIT', 'SPLIT']
ZERO_COST_WARN_TYPES = [
    'SPINOFF', 'SPIN-OFF', 'SPIN OFF', 'TRANSFER',
    'ACATS', 'MERGER', 'ACQUISITION', 'RIGHTS', 'WARRANT',
]

# ── CSV validation ─────────────────────────────────────────────────────────────
REQUIRED_COLUMNS = {
    'Date', 'Action', 'Description', 'Type', 'Sub Type',
    'Instrument Type', 'Symbol', 'Underlying Symbol',
    'Quantity', 'Total', 'Commissions', 'Fees',
    'Strike Price', 'Call or Put', 'Expiration Date', 'Root Symbol', 'Order #',
}

# ── FIFO arithmetic precision ─────────────────────────────────────────────────
# Floating-point epsilon used to test whether a lot quantity is effectively zero.
# Values below this threshold are treated as fully consumed. Also used as the
# rounding precision for lot remainder arithmetic so accumulated floating-point
# error doesn't leave ghost lots in the queue.
FIFO_EPSILON  = 1e-9
FIFO_ROUND    = 9

# ── Trade log row highlighting ───────────────────────────────────────────────
# Trades with P/L below this threshold get a full red row tint in the trade log.
# Trades above the absolute value get a full green row tint.
TRADE_LOSS_HIGHLIGHT = -200   # dollars

# ── Display caps ──────────────────────────────────────────────────────────────
# Annualised return is capped at ±ANN_RETURN_CAP % to prevent a 1-day trade
# from producing a meaningless 50,000 % figure in the trade log.
ANN_RETURN_CAP = 500
# Daily θ % = Prem/Day ÷ Capital at Risk × 100 — measures entry quality at trade open.
# Cap suppresses distorted 0DTE figures; thresholds drive green/orange/red colouring.
DAILY_THETA_CAP    = 5     # % per day hard cap
DAILY_THETA_GREEN  = 0.10  # % per day → solid (≈36% ARR equivalent on max risk)
DAILY_THETA_ORANGE = 0.05  # % per day → acceptable (≈18% ARR equivalent)

# MTM ROR colour thresholds — applied to the hero MTM ROR stat in Portfolio Overview:
#   > MTM_ROR_GREEN  → green  (strong total return)
#   >= MTM_ROR_ORANGE → orange (positive but modest)
#   <  MTM_ROR_ORANGE → red    (net loss when marking to market)
MTM_ROR_GREEN  = 10.0  # %
MTM_ROR_ORANGE = 0.0   # %

# ── XIRR / money-weighted return solver ───────────────────────────────────────
# Bisection bracket + convergence for the money-weighted return (XIRR) used in
# the Long-Term Performance panel. Annual rate as a decimal: -0.9999 = near-total
# loss floor, 10.0 = 1000%/yr ceiling. A root outside this bracket returns None
# (we don't fabricate a rate we can't bracket).
XIRR_RATE_LO  = -0.9999
XIRR_RATE_HI  = 10.0
XIRR_MAX_ITER = 200
XIRR_TOL      = 1e-6

# ── Scorecard colour thresholds ───────────────────────────────────────────────
# Win rate colouring in Performance by Ticker table:
#   >= WIN_RATE_GREEN  → green  (strong edge)
#   >= WIN_RATE_ORANGE → orange (acceptable)
#   <  WIN_RATE_ORANGE → red    (below target)
WIN_RATE_GREEN  = 70   # %
WIN_RATE_ORANGE = 50   # %

# ── DTE progress bar ──────────────────────────────────────────────────────────
# Max DTE shown as full bar in the open positions DTE progress widget.
# 45 DTE is TastyTrade's standard short-premium entry target.
DTE_PROGRESS_MAX = 45  # days — TastyTrade standard short-premium entry target
DTE_ALERT_WARN   = 14  # days — orange warning threshold on DTE progress bar
DTE_ALERT_CRIT   =  5  # days — red critical threshold on DTE progress bar

# ── Close reason labels ───────────────────────────────────────────────────────
CLOSE_EXPIRED    = '⏹️ Expired'
CLOSE_ASSIGNED   = '📋 Assigned'
CLOSE_EXERCISED  = '🏋️ Exercised'
CLOSE_CLOSED     = '✂️ Closed'

# ── UI colour palette ─────────────────────────────────────────────────────────
# Dark-mode GitHub-inspired theme used throughout ui_components.py
COLOURS = {
    'green':       '#00cc96',   # profit, win, bullish
    'red':         '#ef553b',   # loss, warning, bearish
    'orange':      '#ffa500',   # caution, near-limit, covered
    'blue':        '#58a6ff',   # neutral highlight, default badge
    'text':        '#e6edf3',   # primary text
    'text_muted':  '#8b949e',   # labels, secondary text
    'text_dim':    '#6b7280',   # captions, tertiary text
    'border':      '#1f2937',   # card borders, dividers
    'card_bg':     '#111827',   # card background start
    'card_bg2':    '#0f1520',   # card background end (gradient)
    'tan':         '#8b7355',   # short < 4 days held asterisk
    'white':       '#f0f6fc',   # ticker symbol text
    'header_text': '#c9d1d9',   # chart header text
}
