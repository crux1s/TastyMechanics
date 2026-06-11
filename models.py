"""
TastyMechanics — Data Models
==============================
Single source of truth for all dataclasses used across the application.
No Streamlit dependency — fully importable from any module including
tests and ingestion.

Classes
-------
  ParsedData   Output of ingestion.parse_csv() — cleaned DataFrame + corporate action lists
  Campaign     One continuous wheel campaign for a ticker (open or closed)
  AppData      All heavy-computed data from build_all_data() — typed, named fields
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# ── Ingestion output ──────────────────────────────────────────────────────────

@dataclass
class ParsedData:
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
    unknown_action_rows  [{ticker, date, action, sub_type, description, quantity}]
                   Trade / Receive Deliver rows whose Action and Description
                   didn't match any of the BUY/SELL/REMOVAL patterns in
                   get_signed_qty(), so Net_Qty_Row was silently set to 0
                   despite Quantity being non-zero.  Almost always empty;
                   non-empty means the upstream CSV format may have drifted
                   (a new TastyTrade Action enum, a localised export, etc.)
                   and the trade is invisible to FIFO/campaign tracking.
                   Surfaced as a UI warning so the user can investigate
                   before trusting the resulting P/L.
    """
    df:                  pd.DataFrame
    split_events:        list
    zero_cost_rows:      list
    unknown_action_rows: list = field(default_factory=list)


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
    shares_acquired  Cumulative shares BOUGHT over the campaign (split-adjusted,
                   never reduced by sales).  total_cost / shares_acquired gives
                   the average acquisition cost per share, which survives
                   campaign close (blended_basis is zeroed when shares hit 0).
                   Used as the covered-call capital base in
                   _calculate_capital_risk.
    """
    ticker:                  str
    total_shares:            float
    total_cost:              float
    blended_basis:           float
    premiums:                float
    dividends:               float
    exit_proceeds:           float
    start_date:              pd.Timestamp
    end_date:                Optional[pd.Timestamp]
    status:                  str                     # 'open' | 'closed'
    events:                  list = field(default_factory=list)
    pre_campaign_close_net:  float = 0.0             # net cash from closes of pre-purchase options
    shares_acquired:         float = 0.0             # cumulative shares bought (split-adjusted)


# ── Computation output ────────────────────────────────────────────────────────

@dataclass
class AppData:
    """
    Typed container for all heavy-computed data from build_all_data().

    Replaces a fragile positional tuple — fields are named, self-documenting,
    and safe to reorder or extend without breaking callers.
    """
    all_campaigns:          dict            # {ticker: list[Campaign]}
    wheel_tickers:          list
    pure_options_tickers:   list
    closed_trades_df:       pd.DataFrame
    df_open:                pd.DataFrame
    closed_camp_pnl:        float
    open_premiums_banked:   float
    capital_deployed:       float
    pure_opts_pnl:          float
    extra_capital_deployed: float
    pure_opts_per_ticker:   dict            # {ticker: float} options P/L outside campaign windows
    split_events:           list            # [{ticker,date,ratio,...}] detected stock splits
    zero_cost_rows:         list            # [{ticker,date,qty,...}] zero-cost deliveries
