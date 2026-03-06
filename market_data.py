"""
market_data.py — Live market price fetcher via Yahoo Finance (yfinance).

Isolated here so tab renderers can import it without touching ui_components
or mechanics. Results are cached for 300 s (5 min) to avoid hammering Yahoo
Finance across Streamlit rerenders.

Tickers are the only data sent externally — no transaction amounts or account
details leave the app.
"""

import pandas as pd
import streamlit as st

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False


@st.cache_data(ttl=300, show_spinner=False)
def fetch_live_prices(tickers: frozenset, option_specs: frozenset) -> dict:
    """Fetch live equity quotes and option marks for the given tickers.

    Parameters
    ----------
    tickers      : frozenset of ticker strings
    option_specs : frozenset of (ticker, expiry_ymd, strike, cp) tuples
                   expiry_ymd is 'YYYY-MM-DD', strike is float, cp is 'CALL'/'PUT'

    Returns
    -------
    dict  {ticker: {'last': float,
                    'prev_close': float,
                    'options': {(expiry_ymd, strike, cp): {'bid', 'ask', 'mark'}}}}

    Failed lookups are silently omitted so a bad ticker never crashes the UI.
    """
    if not _YF_AVAILABLE or not tickers:
        return {}

    # {ticker: {expiry_ymd: [(strike, cp)]}}
    opt_lookup: dict = {}
    for tkr, expiry, strike, cp in option_specs:
        opt_lookup.setdefault(tkr, {}).setdefault(expiry, []).append((strike, cp))

    result: dict = {}
    for ticker in tickers:
        try:
            yf_t = yf.Ticker(ticker)
            fi   = yf_t.fast_info
            last = float(fi.get('last_price') or fi.get('regularMarketPrice') or 0.0)
            prev = float(fi.get('previous_close') or fi.get('regularMarketPreviousClose') or last)

            opts: dict = {}
            for expiry, _specs in opt_lookup.get(ticker, {}).items():
                try:
                    chain   = yf_t.option_chain(expiry)
                    all_legs = pd.concat(
                        [chain.calls.assign(cp='CALL'), chain.puts.assign(cp='PUT')],
                        ignore_index=True,
                    )
                    for _, row in all_legs.iterrows():
                        bid  = float(row.get('bid', 0.0) or 0.0)
                        ask  = float(row.get('ask', 0.0) or 0.0)
                        opts[(expiry, float(row['strike']), str(row['cp']))] = {
                            'bid': bid, 'ask': ask, 'mark': (bid + ask) / 2,
                        }
                except Exception:
                    pass  # Expiry not available in yfinance — skip silently

            result[ticker] = {'last': last, 'prev_close': prev, 'options': opts}
        except Exception:
            pass  # Ticker lookup failed — skip silently

    return result
