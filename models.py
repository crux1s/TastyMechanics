"""
TastyMechanics — Data Models
==============================
Single source of truth for all dataclasses and named tuples used across
the application. No Streamlit dependency — fully importable from any
module including tests and ingestion.

Classes
-------
  ParsedData   Output of ingestion.parse_csv() — cleaned DataFrame + corporate action lists
  Campaign     One continuous wheel campaign for a ticker (open or closed)
  AppData      All heavy-computed data from build_all_data() — typed, named fields
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, NamedTuple, Literal

import pandas as pd


# ── Ingestion output ──────────────────────────────────────────────────────────

class ParsedData(NamedTuple):
    """
    Output of ingestion.parse_csv() — bundles the cleaned DataFrame with
    the corporate action lists so callers don't need to re-scan.

    Fields
    ------
    df             Cleaned, date-sorted DataFrame ready for analysis.
    split_events   [{ticker, date, ratio, pre_qty, post_qty}]
                   One entry per detected stock split.
    zero_cost_rows [{ticker, date, qty, description}]
                   Share deliveries with $0 cost basis (spin-offs, ACATS, etc.)
                   that will overstate P/L on eventual sale.
    """
    df:             pd.DataFrame
    split_events:   list[dict]
    zero_cost_rows: list[dict]


# ── Campaign model ────────────────────────────────────────────────────────────

@dataclass
class Campaign:
    """
    A single wheel campaign — one continuous share-holding period for a ticker.

    Created in build_campaigns() when shares >= WHEEL_MIN_SHARES are bought,
    closed when shares reach zero. Multiple campaigns per ticker are possible
    (e.g. bought, fully exited, then re-entered).

    Fields
    ------
    ticker         Underlying symbol, e.g. 'NVDA'
    total_shares   Current share count (updated on adds, exits, splits)
    total_cost     Cash paid to acquire shares (absolute value, always >= 0)
    blended_basis  total_cost / total_shares — average cost per share
    premiums       Net option premium collected while campaign is open (can be negative)
    dividends      Dividends received during the campaign
    exit_proceeds  Cash received from share sales (positive when sold)
    start_date     Date of first share purchase / assignment entry
    end_date       Date shares hit zero (None while still open)
    status         'open' or 'closed'
    events         Ordered list of dicts — {date, type, detail, cash} for the UI log
    """
    ticker:         str
    total_shares:   float
    total_cost:     float
    blended_basis:  float
    premiums:       float
    dividends:      float
    exit_proceeds:  float
    start_date:     pd.Timestamp
    end_date:       Optional[pd.Timestamp]
    status:         Literal['open', 'closed']
    events:         list[dict] = field(default_factory=list)


# ── Computation output ────────────────────────────────────────────────────────

@dataclass
class AppData:
    """
    Typed container for all heavy-computed data from build_all_data().

    Replaces a fragile positional tuple — fields are named, self-documenting,
    and safe to reorder or extend without breaking callers.
    """
    all_campaigns:          dict[str, list[Campaign]]
    wheel_tickers:          list[str]
    pure_options_tickers:   list[str]
    closed_trades_df:       pd.DataFrame
    df_open:                pd.DataFrame
    closed_camp_pnl:        float
    open_premiums_banked:   float
    capital_deployed:       float
    pure_opts_pnl:          float
    extra_capital_deployed: float
    pure_opts_per_ticker:   dict[str, float]
    split_events:           list[dict]
    zero_cost_rows:         list[dict]
