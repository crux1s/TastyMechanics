"""
TastyMechanics — Data Ingestion
================================
Pure Python CSV parsing pipeline. No Streamlit dependency — fully importable
and testable without a running server.

Public API
----------
  parse_csv(file_bytes)         → ParsedData(df, split_events, zero_cost_rows)
  validate_columns(file_bytes)  → set of missing column names (empty = OK)

Internal helpers (also importable for use in analysis functions)
  clean_val(val)                → float
  get_signed_qty(row)           → float
  equity_mask(series)           → bool Series
  option_mask(series)           → bool Series
  detect_corporate_actions(df)  → (split_events, zero_cost_rows)
  apply_split_adjustments(df)   → df
"""

from __future__ import annotations

import io as _io
from typing import Any

import pandas as pd

from config import (
    SPLIT_DSC_PATTERNS,
    REQUIRED_COLUMNS,
)

from models import ParsedData


# ── Row-level helpers ─────────────────────────────────────────────────────────

def clean_val(val: Any) -> float:
    """Parse a TastyTrade currency string like '$1,234.56' to float."""
    if pd.isna(val) or val == '--':
        return 0.0
    return float(str(val).replace('$', '').replace(',', ''))


def get_signed_qty(row: pd.Series) -> float:
    """
    Return signed share/contract quantity: positive = buy, negative = sell.

    TastyTrade stores quantity as an absolute value in the Quantity column
    and encodes direction in the Action and Description fields. This function
    reads the direction and returns a signed quantity so downstream code can
    use simple arithmetic (sum, cumsum) rather than conditional branches.

    Special cases:
    - Assignment REMOVAL: shares are delivered, so positive (a buy-equivalent).
    - Split REMOVAL: share count change is handled separately by
      apply_split_adjustments(); returning 0 here prevents the removal row
      from triggering a false sale.
    - Other REMOVALs (spin-offs, ACATS): treated as exits (negative) so
      the FIFO queue empties correctly.
    """
    act = str(row['Action']).upper()
    dsc = str(row['Description']).upper()
    qty = row['Quantity']
    if 'BUY'  in act or 'BOUGHT' in dsc: return  qty
    if 'SELL' in act or 'SOLD'   in dsc: return -qty
    if 'REMOVAL' in dsc:
        if 'ASSIGNMENT' in dsc:                          return  qty
        if any(p in dsc for p in SPLIT_DSC_PATTERNS):   return  0
        return -qty
    return 0


def equity_mask(series: pd.Series) -> pd.Series:
    """Vectorised test for plain equity rows — True for 'Equity', not options."""
    return series.str.strip() == 'Equity'


def option_mask(series: pd.Series) -> pd.Series:
    """Vectorised test for option rows — True for 'Equity Option' or 'Future Option'."""
    return series.str.contains('Option', na=False)


# ── Corporate action detection ────────────────────────────────────────────────

def detect_corporate_actions(df: pd.DataFrame) -> tuple[list, list]:
    """
    Scan the DataFrame for corporate actions that affect cost-basis correctness.
    Must be called after Net_Qty_Row is assigned and the DataFrame is date-sorted.

    Returns
    -------
    split_events : list of dicts
        {ticker, date, ratio, pre_qty, post_qty}
        Detected by pairing a zero-Total Receive Deliver REMOVAL containing a
        split keyword with a matching addition on the same ticker and date.
        ratio = post_qty / pre_qty (e.g. 2.0 for a 2-for-1 forward split).

    zero_cost_rows : list of dicts
        {ticker, date, qty, description}
        Any zero-Total Receive Deliver share addition not matched to a split
        pair and not an assignment. Includes spin-offs, ACATS transfers, and
        mergers. The $0 cost basis means P/L on eventual sale will be overstated
        until corrected — these are surfaced as UI warnings.
    """
    split_events   = []
    zero_cost_rows = []

    rd = df[
        (df['Type'] == 'Receive Deliver') &
        (equity_mask(df['Instrument Type'])) &
        (df['Total'] == 0.0)
    ].copy()

    if rd.empty:
        return split_events, zero_cost_rows

    rd['_dsc'] = rd['Description'].fillna('').str.upper()

    def _is_split_row(dsc):
        return any(p in dsc for p in SPLIT_DSC_PATTERNS)

    processed_indices = set()
    for (ticker, date), grp in rd.groupby(['Ticker', 'Date']):
        removals  = grp[grp['_dsc'].apply(lambda d: 'REMOVAL'     in d and _is_split_row(d))]
        additions = grp[grp['_dsc'].apply(lambda d: 'REMOVAL' not in d and _is_split_row(d))]
        if not removals.empty and not additions.empty:
            pre_qty  = removals['Quantity'].sum()
            post_qty = additions['Quantity'].sum()
            if pre_qty > 0:
                split_events.append({
                    'ticker':   ticker,
                    'date':     date,
                    'ratio':    round(post_qty / pre_qty, 6),
                    'pre_qty':  pre_qty,
                    'post_qty': post_qty,
                })
                processed_indices.update(removals.index)
                processed_indices.update(additions.index)

    # Zero-cost additions not matched to a split pair
    for row in rd[~rd.index.isin(processed_indices)].itertuples(index=False):
        # itertuples renames columns starting with _ (e.g. _dsc → _N),
        # so read Description directly and uppercase it here.
        dsc = str(row.Description).upper()
        if 'ASSIGNMENT' in dsc:
            continue
        if row.Quantity > 0:
            zero_cost_rows.append({
                'ticker':      row.Ticker,
                'date':        row.Date,
                'qty':         row.Quantity,
                'description': str(row.Description)[:80],
            })

    return split_events, zero_cost_rows


def apply_split_adjustments(df: pd.DataFrame, split_events: list) -> pd.DataFrame:
    """
    Rescale pre-split equity lot quantities so the FIFO engine sees correct
    post-split share counts and per-share cost basis.

    For each split event (ratio = post/pre, e.g. 2.0 for a 2:1 forward split):
      - Equity rows for that ticker with Date < split_date have Quantity and
        Net_Qty_Row multiplied by the ratio.
      - Total (cash paid/received) is unchanged — basis per share is halved.
      - The split rows themselves (Total=0, Net_Qty_Row=0) are untouched.

    Returns a new DataFrame (the original is not modified).

    NOTE: Option strikes are NOT adjusted. TastyTrade issues new symbols for
    post-split contracts — that is a known limitation documented in the README.
    """
    if not split_events:
        return df
    df = df.copy()
    for ev in split_events:
        mask = (
            (df['Ticker'] == ev['ticker']) &
            (equity_mask(df['Instrument Type'])) &
            (df['Date'] < ev['date']) &
            (df['Net_Qty_Row'] != 0)
        )
        df.loc[mask, 'Quantity']    = (df.loc[mask, 'Quantity']    * ev['ratio']).round(9)
        df.loc[mask, 'Net_Qty_Row'] = (df.loc[mask, 'Net_Qty_Row'] * ev['ratio']).round(9)
    return df


# ── Public entry points ───────────────────────────────────────────────────────

def validate_columns(file_bytes: bytes) -> set[str]:
    """
    Return the set of required columns missing from the CSV header.
    An empty set means the file looks like a valid TastyTrade export.
    Reads only the header row — fast and does not parse the full file.
    """
    header_df = pd.read_csv(_io.BytesIO(file_bytes), nrows=0)
    return REQUIRED_COLUMNS - set(header_df.columns)


def parse_csv(file_bytes: bytes) -> ParsedData:
    """
    Read and clean a TastyTrade history CSV export.

    Steps
    -----
    1. Parse raw bytes into a DataFrame.
    2. Normalise Date to naive UTC timestamps (strips TastyTrade's +00:00).
    3. Parse currency columns (Total, Quantity, Commissions, Fees) to float.
    4. Derive Ticker from Underlying Symbol (falls back to first word of Symbol).
    5. Compute Net_Qty_Row (signed quantity) via get_signed_qty().
    6. Sort by Date ascending.
    7. Detect corporate actions (splits, zero-cost deliveries).
    8. Apply split quantity rescaling to pre-split lots.

    Returns ParsedData — a NamedTuple of (df, split_events, zero_cost_rows).
    The corporate action lists are bundled here so callers don't need to
    re-scan the DataFrame.
    """
    df = pd.read_csv(_io.BytesIO(file_bytes))

    # Normalise dates — TastyTrade exports include a +00:00 UTC offset.
    # Strip the timezone so all downstream code works with naive timestamps
    # and there is no risk of mixed-tz comparisons.
    df['Date'] = pd.to_datetime(df['Date'], utc=True).dt.tz_localize(None)

    for col in ['Total', 'Quantity', 'Commissions', 'Fees']:
        df[col] = df[col].apply(clean_val)

    df['Ticker'] = (
        df['Underlying Symbol']
        .fillna(df['Symbol'].str.split().str[0])
        .fillna('CASH')
    )

    df['Net_Qty_Row'] = df.apply(get_signed_qty, axis=1)
    df = df.sort_values('Date').reset_index(drop=True)

    # Corporate action detection must run after Net_Qty_Row is set and the
    # DataFrame is date-sorted. split_events feeds into apply_split_adjustments;
    # both lists are returned in ParsedData for UI warning banners.
    split_events, zero_cost_rows = detect_corporate_actions(df)
    df = apply_split_adjustments(df, split_events)

    return ParsedData(df=df, split_events=split_events, zero_cost_rows=zero_cost_rows)
