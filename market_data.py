"""
market_data.py — Live market price fetcher via Yahoo Finance (yfinance).

Isolated here so tab renderers can import it without touching ui_components
or mechanics. Results are cached for 300 s (5 min) to avoid hammering Yahoo
Finance across Streamlit rerenders.

Tickers are the only data sent externally — no transaction amounts or account
details leave the app.
"""

import math
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
                    'beta': float | None,
                    'options': {(expiry_ymd, strike, cp): {'bid', 'ask', 'mark', 'iv'}}}}

    Betas are computed from 90-day rolling returns vs SPY (more reliable than
    yfinance .info which is frequently rate-limited). SPY should be included in
    tickers for beta computation; if absent all betas will be None.

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
            # Attribute access (not .get()) triggers the actual network fetch;
            # .get() may return None silently when the network is unreachable.
            last = float(fi.last_price or 0.0)
            if not last:
                continue  # no price data — skip rather than store zeros
            try:
                prev = float(fi.previous_close or last)
            except Exception:
                prev = last

            opts: dict = {}
            available_expiries: tuple = yf_t.options  # cached by yfinance
            for expiry, _specs in opt_lookup.get(ticker, {}).items():
                try:
                    # TastyTrade exports Saturday OCC settlement dates; yfinance
                    # lists options under the Friday last-trading-day.  Try the
                    # exact date first, then fall back to the prior calendar day.
                    yf_expiry = expiry
                    if expiry not in available_expiries:
                        prev_day = (
                            pd.Timestamp(expiry) - pd.Timedelta(days=1)
                        ).strftime('%Y-%m-%d')
                        if prev_day in available_expiries:
                            yf_expiry = prev_day
                        else:
                            continue  # Neither date available — skip
                    chain   = yf_t.option_chain(yf_expiry)
                    all_legs = pd.concat(
                        [chain.calls.assign(cp='CALL'), chain.puts.assign(cp='PUT')],
                        ignore_index=True,
                    )
                    for _, row in all_legs.iterrows():
                        bid  = float(row.get('bid', 0.0) or 0.0)
                        ask  = float(row.get('ask', 0.0) or 0.0)
                        iv   = row.get('impliedVolatility', None)
                        iv   = float(iv) if iv is not None and iv == iv else None  # nan-safe
                        # Key by the original expiry string so the remapping in
                        # tab0 can match it back to the CSV value.
                        opts[(expiry, float(row['strike']), str(row['cp']))] = {
                            'bid': bid, 'ask': ask, 'mark': (bid + ask) / 2, 'iv': iv,
                        }
                except Exception:
                    pass  # Expiry not available in yfinance — skip silently

            result[ticker] = {'last': last, 'prev_close': prev, 'options': opts, 'beta': None}
        except Exception:
            pass  # Ticker lookup failed — skip silently

    # ── Beta computation from 90-day rolling returns vs SPY ──────────────────
    # yfinance .info is frequently rate-limited; yf.download() is more reliable.
    # SPY must be in the tickers set (added by tab0) for beta to be computed.
    if result and _YF_AVAILABLE:
        try:
            _beta_tickers = sorted(result.keys())
            if 'SPY' not in _beta_tickers:
                _beta_tickers.append('SPY')
            hist = yf.download(
                _beta_tickers, period='3mo', interval='1d',
                progress=False, auto_adjust=True,
            )
            if not hist.empty:
                # MultiIndex when multiple tickers, flat when single
                if isinstance(hist.columns, pd.MultiIndex):
                    closes = hist['Close']
                else:
                    closes = hist[['Close']].rename(columns={'Close': _beta_tickers[0]})
                if 'SPY' in closes.columns:
                    spy_ret = closes['SPY'].pct_change().dropna()
                    for ticker in list(result.keys()):
                        if ticker == 'SPY' or ticker not in closes.columns:
                            continue
                        tkr_ret = closes[ticker].pct_change().dropna()
                        aligned = pd.concat([tkr_ret, spy_ret], axis=1).dropna()
                        if len(aligned) > 15:
                            cov = float(aligned.iloc[:, 0].cov(aligned.iloc[:, 1]))
                            var = float(aligned.iloc[:, 1].var())
                            if var > 0:
                                result[ticker]['beta'] = round(cov / var, 2)
        except Exception:
            pass  # Beta computation failed — betas remain None (snapshot defaults to 1.0)

    return result


# ── Black-Scholes Greeks ───────────────────────────────────────────────────────

def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, cp: str) -> dict:
    """Compute Black-Scholes Greeks for a European option.

    Parameters
    ----------
    S     : current stock price
    K     : strike price
    T     : time to expiry in years  (DTE / 365)
    r     : risk-free rate as a decimal  (e.g. 0.045)
    sigma : implied volatility as a decimal  (e.g. 0.35 for 35 %%)
    cp    : 'CALL' or 'PUT'

    Returns
    -------
    dict with keys: delta, gamma, theta, vega
      delta — per-share directional exposure  (−1 to +1)
      gamma — per-share rate of delta change
      theta — $/day per contract  (×100 shares; negative = time value decays against holder)
      vega  — $ per 1 %% move in IV per contract  (×100 shares)
    """
    if T <= 0 or sigma is None or sigma <= 0 or S <= 0 or K <= 0:
        return {'delta': 0.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0}
    try:
        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
        d2 = d1 - sigma * sqrt_T

        def _N(x):
            return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

        def _n(x):
            return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

        gamma_ps = _n(d1) / (S * sigma * sqrt_T)          # per share
        vega_ps  = S * _n(d1) * sqrt_T * 0.01             # per share, per 1%% IV move

        if cp.upper() == 'CALL':
            delta = _N(d1)
            theta_ps = (
                -(S * _n(d1) * sigma) / (2.0 * sqrt_T)
                - r * K * math.exp(-r * T) * _N(d2)
            ) / 365.0
        else:
            delta = _N(d1) - 1.0
            theta_ps = (
                -(S * _n(d1) * sigma) / (2.0 * sqrt_T)
                + r * K * math.exp(-r * T) * _N(-d2)
            ) / 365.0

        return {
            'delta': delta,
            'gamma': gamma_ps,
            'theta': theta_ps * 100.0,   # per contract
            'vega':  vega_ps  * 100.0,   # per contract
        }
    except Exception:
        return {'delta': 0.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0}
