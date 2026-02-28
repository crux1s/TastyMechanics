"""
TastyMechanics — Configuration & Constants
===========================================
All tuneable parameters and TastyTrade CSV field values live here.
Change a value once and it applies everywhere.
"""

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

# ── Display caps ──────────────────────────────────────────────────────────────
# Annualised return is capped at ±ANN_RETURN_CAP % to prevent a 1-day trade
# from producing a meaningless 50,000 % figure in the trade log.
ANN_RETURN_CAP = 500
