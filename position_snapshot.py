"""
position_snapshot.py — Builds a structured AI review prompt from current open positions.

No Streamlit dependency. Pure function — takes AppData fields + live prices, returns a
plain-text string ready to paste into any LLM (Claude, ChatGPT, Gemini, etc.).

Options are presented in TastyTrade-style human-readable notation:
    SOFI  15 Aug 25  $12.50 Put   (short, ×1)

Portfolio Greeks (Section 5):
  - Net Δ, Γ, θ, ν  — summed across all open option positions.
  - Beta-weighted Δ to SPY — uses Yahoo Finance betas; requires SPY to be in live_prices.
  - Buying power usage requires the TastyTrade API and is not shown.
"""

import math
import pandas as pd

from config import OPT_TYPES, EQUITY_TYPE
from ui_components import fmt_dollar
from mechanics import realized_pnl, effective_basis
from market_data import bs_greeks


_RISK_FREE_RATE = 0.045   # approximate 3-month T-bill rate; update periodically


# ── helpers ───────────────────────────────────────────────────────────────────

def _opt_label(ticker, expiry_str, strike, cp, net_qty):
    """Return TastyTrade-style option label, e.g. 'SOFI  15 Aug 25  $12.50 Put   (short, ×2)'"""
    try:
        exp_dt  = pd.to_datetime(expiry_str, format='mixed', errors='coerce')
        exp_fmt = exp_dt.strftime('%d %b %y') if not pd.isnull(exp_dt) else expiry_str
    except Exception:
        exp_fmt = str(expiry_str)

    direction = 'short' if net_qty < 0 else 'long'
    qty       = abs(int(round(net_qty)))
    type_str  = 'Call' if str(cp).upper() == 'CALL' else 'Put'
    return f'{ticker:<6}  {exp_fmt}  ${strike:.2f} {type_str:<4}  ({direction}, ×{qty})'


def _dte(expiry_str, as_of):
    """Days to expiry from as_of date. Returns int or None."""
    try:
        exp_dt = pd.to_datetime(expiry_str, format='mixed', errors='coerce').normalize()
        return max(0, (exp_dt - as_of).days)
    except Exception:
        return None


def _pct(n, d, decimals=1):
    if not d:
        return '—'
    return f'{n / d * 100:.{decimals}f}%'


def _fmt_greek(v, fmt='+.2f'):
    if v == 0.0:
        return '—'
    return format(v, fmt)


def _fmt_delta(v):
    """Format delta with sign, 2 dp."""
    return _fmt_greek(v, '+.2f')


# ── main builder ──────────────────────────────────────────────────────────────

def build_position_snapshot(
    df_open,
    all_campaigns,
    all_cdf,
    credit_cdf,
    live_prices,
    latest_date,
    total_realized_pnl,
    capital_deployed,
    open_premiums_banked,
    use_lifetime=False,
):
    """
    Build a plain-text AI position review prompt populated with current open positions
    and live market data. Returns a str.

    Parameters
    ----------
    df_open              : AppData.df_open — open positions DataFrame
    all_campaigns        : {ticker: list[Campaign]}
    all_cdf              : closed trades DataFrame (for condensed scorecard)
    credit_cdf           : credit trades DataFrame (for capture %, DTE stats)
    live_prices          : fetch_live_prices() return value — may be empty dict
                           Should include 'SPY' for beta-weighted delta.
    latest_date          : pd.Timestamp (today / last CSV date)
    total_realized_pnl   : float
    capital_deployed     : float
    open_premiums_banked : float
    use_lifetime         : bool
    """
    lines = []
    add   = lines.append
    as_of = pd.Timestamp(latest_date).normalize()

    has_live = bool(live_prices)

    add('# TastyMechanics — Open Position Snapshot')
    add(f'As of: {as_of.strftime("%d %b %Y")}  '
        f'({"live prices; ~15 min delay" if has_live else "no live prices — enable the Live toggle in the Open Positions tab"})')
    add('')
    add('⚠️  IVR and buying power usage require TastyTrade API access and are not shown here.')
    add('   Beta-weighted delta uses Yahoo Finance betas (may differ slightly from TastyTrade).')
    add('')

    # ── 1. Account Summary ────────────────────────────────────────────────────
    add('## 1. Account Summary')
    add(f'- Realized P/L (all-time):         {fmt_dollar(total_realized_pnl)}')
    add(f'- Capital deployed (shares):        {fmt_dollar(capital_deployed)}')
    add(f'- Premiums banked (open wheels):    {fmt_dollar(open_premiums_banked)}')
    add('')

    # ── identify wheel vs standalone equity ───────────────────────────────────
    _wheel_tickers = {
        ticker
        for ticker, camps in (all_campaigns.items() if hasattr(all_campaigns, 'items') else [])
        for c in camps
        if c.status == 'open' and c.total_shares > 0
    }

    # ── 2. Open Wheel Campaigns ───────────────────────────────────────────────
    add('## 2. Open Wheel Campaigns')
    open_camps = [
        (ticker, c)
        for ticker, camps in (all_campaigns.items() if hasattr(all_campaigns, 'items') else [])
        for c in camps
        if c.status == 'open'
    ]
    add('Note: "Gross Unreal" is vs entry price (no premium offset). '
        '"Net Unreal" is vs effective basis (entry minus premiums collected).')
    add('')
    if open_camps:
        add(f'{"Ticker":<7} {"Shares":>6}  {"Entry":>7}  {"Premiums":>9}  {"Eff Basis":>9}  '
            f'{"Last":>7}  {"Gross Unreal":>12}  {"Net Unreal":>10}  {"Δ equity":>9}  {"Days":>5}')
        add('-' * 107)
        for ticker, c in open_camps:
            effb = effective_basis(c, use_lifetime)
            days = (as_of - pd.Timestamp(c.start_date)).days

            live_tk  = live_prices.get(ticker, {}) if has_live else {}
            last     = live_tk.get('last', None)

            if last and c.total_shares > 0:
                gross_unreal = (last - c.blended_basis) * c.total_shares
                net_unreal   = (last - effb) * c.total_shares
                last_str     = f'${last:>6.2f}'
                eq_delta_str = f'{c.total_shares:+.0f}'    # long stock = positive delta
            else:
                gross_unreal = None
                net_unreal   = None
                last_str     = '—'
                eq_delta_str = f'{c.total_shares:+.0f}' if c.total_shares else '—'

            gross_str = fmt_dollar(gross_unreal) if gross_unreal is not None else '—'
            net_str   = fmt_dollar(net_unreal)   if net_unreal   is not None else '—'
            add(f'{ticker:<7} {int(c.total_shares):>6}  ${c.blended_basis:>6.2f}  '
                f'{fmt_dollar(c.premiums):>9}  ${effb:>8.2f}  '
                f'{last_str:>7}  {gross_str:>12}  {net_str:>10}  {eq_delta_str:>9}  {days:>4}d')
    else:
        add('No open wheel campaigns.')
    add('')

    # ── 2b. Standalone equity positions (non-wheel) ───────────────────────────
    _equity_rows = pd.DataFrame()
    if not df_open.empty and 'Instrument Type' in df_open.columns:
        _eq_mask     = df_open['Instrument Type'] == EQUITY_TYPE
        _equity_rows = df_open[_eq_mask & ~df_open['Ticker'].isin(_wheel_tickers)].copy()

    if not _equity_rows.empty:
        add('## 2b. Other Long Stock Positions')
        add(f'{"Ticker":<7} {"Shares":>8}  {"Cost Basis":>10}  {"Last":>7}  {"Unreal $":>9}  {"Δ equity":>9}')
        add('-' * 62)
        for _, row in _equity_rows.iterrows():
            tkr      = str(row.get('Ticker', '?'))
            shares   = float(row.get('Net_Qty', 0.0) or 0.0)
            cost_b   = float(row.get('Cost Basis', 0.0) or 0.0)
            live_tk  = live_prices.get(tkr, {}) if has_live else {}
            last     = live_tk.get('last', None)
            unreal_s = fmt_dollar((last - cost_b / shares) * shares) if (last and shares) else '—'
            last_s   = f'${last:.2f}' if last else '—'
            # Show fractional shares with 2 dp when < 1, whole number otherwise
            shares_s = f'{shares:.2f}' if shares < 1 else f'{shares:.0f}'
            add(f'{tkr:<7} {shares_s:>8}  {fmt_dollar(cost_b):>10}  {last_s:>7}  {unreal_s:>9}  {shares:>+9.2f}')
        add('')

    # ── 3. Open Option Positions ──────────────────────────────────────────────
    add('## 3. Open Option Positions')

    _opt_rows = pd.DataFrame()
    if not df_open.empty and 'Instrument Type' in df_open.columns:
        _opt_mask = df_open['Instrument Type'].isin(OPT_TYPES)
        _opt_rows = df_open[_opt_mask].copy()

    # Accumulate data for portfolio metrics
    _port_opts = []   # {ticker, net_qty, delta, theta, gamma, vega, S, beta}

    if _opt_rows.empty:
        add('No open option positions.')
    else:
        _opt_rows = _opt_rows.sort_values(['Ticker', 'Expiration Date', 'Strike Price'], na_position='last')
        for _, row in _opt_rows.iterrows():
            ticker  = str(row.get('Ticker', '?'))
            cp      = str(row.get('Call or Put', '')).upper()
            expiry  = row.get('Expiration Date', '')
            strike  = float(row.get('Strike Price', 0.0) or 0.0)
            net_qty = float(row.get('Net_Qty', 0.0) or 0.0)
            cost_b  = float(row.get('Cost Basis', 0.0) or 0.0)

            label = _opt_label(ticker, expiry, strike, cp, net_qty)
            add(label)

            # Live data
            dte_val  = _dte(expiry, as_of)
            dte_str  = f'{dte_val}d' if dte_val is not None else '—'

            opt_key  = None
            mark_str = bid_str = ask_str = iv_str = '—'
            iv_raw   = None

            if has_live:
                live_tk = live_prices.get(ticker, {})
                for (exp_k, str_k, cp_k), opt_data in live_tk.get('options', {}).items():
                    if cp_k == cp and abs(str_k - strike) < 0.01:
                        try:
                            exp_date = pd.to_datetime(expiry, format='mixed', errors='coerce').normalize()
                            key_date = pd.to_datetime(exp_k, errors='coerce').normalize()
                            if abs((exp_date - key_date).days) <= 1:
                                opt_key = opt_data
                                break
                        except Exception:
                            pass

            if opt_key:
                bid    = opt_key.get('bid', 0.0) or 0.0
                ask    = opt_key.get('ask', 0.0) or 0.0
                mark   = opt_key.get('mark', 0.0) or 0.0
                iv_raw = opt_key.get('iv', None)

                mark_str = f'${mark:.2f}'
                bid_str  = f'${bid:.2f}'
                ask_str  = f'${ask:.2f}'
                iv_str   = f'{iv_raw*100:.1f}%' if iv_raw else '—'

            # Stock price, OTM/ITM, P/L
            live_tk  = live_prices.get(ticker, {}) if has_live else {}
            S        = live_tk.get('last', 0.0) or 0.0
            beta_raw = live_tk.get('beta', None)

            stock_str = f'${S:.2f}' if S else '—'
            if S and strike:
                pct = (S - strike) / strike * 100
                if cp == 'CALL':
                    otm_str = f'{abs(pct):.1f}% OTM' if pct < 0 else f'{pct:.1f}% ITM'
                else:
                    otm_str = f'{pct:.1f}% OTM' if pct > 0 else f'{abs(pct):.1f}% ITM'
            else:
                otm_str = '—'

            n_contracts = abs(int(round(net_qty))) or 1
            is_short    = net_qty < 0

            if is_short:
                basis_label = f'Prem rcvd {fmt_dollar(abs(cost_b))}'
            else:
                basis_label = f'Cost paid {fmt_dollar(cost_b)}'

            if opt_key:
                mark_val   = opt_key.get('mark', 0.0) or 0.0
                mark_total = mark_val * 100 * n_contracts
                if is_short:
                    open_pnl = abs(cost_b) - mark_total
                else:
                    open_pnl = mark_total - cost_b
                open_pnl_str = fmt_dollar(open_pnl)
            else:
                open_pnl_str = '—'

            add(f'  Stock {stock_str} ({otm_str})  |  Mark {mark_str}  |  Bid {bid_str}  Ask {ask_str}')
            add(f'  IV {iv_str}  |  DTE {dte_str}  |  {basis_label}  |  Open P/L {open_pnl_str}')

            # Per-position Greeks + accumulate portfolio data
            if iv_raw and iv_raw > 0 and dte_val and dte_val > 0 and S > 0:
                T        = dte_val / 365.0
                greeks   = bs_greeks(S, strike, T, _RISK_FREE_RATE, iv_raw, cp)
                # All Greeks shown as position-adjusted (direction × raw):
                #   short put  → Δ positive, Γ negative, θ positive, ν negative
                #   short call → Δ negative, Γ negative, θ positive, ν negative
                #   long put   → Δ negative, Γ positive, θ negative, ν positive
                display_dir = -1 if is_short else 1
                delta_s = _fmt_greek(greeks['delta'] * display_dir, '+.2f')
                gamma_s = _fmt_greek(greeks['gamma'] * display_dir, '+.4f')
                theta_s = _fmt_greek(greeks['theta'] * display_dir, '+.2f')
                vega_s  = _fmt_greek(greeks['vega']  * display_dir, '+.2f')
                add(f'  Δ {delta_s}  Γ {gamma_s}  θ {theta_s}/day  ν {vega_s}')
                # Store for portfolio aggregation
                _port_opts.append({
                    'ticker':  ticker,
                    'net_qty': net_qty,
                    'delta':   greeks['delta'],
                    'theta':   greeks['theta'],
                    'gamma':   greeks['gamma'],
                    'vega':    greeks['vega'],
                    'S':       S,
                    'beta':    beta_raw,
                })
            elif not has_live:
                add('  (enable live data for Greeks)')

            add('')

    # ── 4. Condensed Historical Scorecard ─────────────────────────────────────
    add('## 4. Historical Scorecard (condensed)')
    if not all_cdf.empty:
        n_trades  = len(all_cdf)
        n_wins    = all_cdf['Won'].sum() if 'Won' in all_cdf.columns else 0
        win_rate  = n_wins / n_trades * 100 if n_trades else 0
        avg_pnl   = all_cdf['Net P/L'].mean()
        winners   = all_cdf[all_cdf['Net P/L'] >= 0]['Net P/L']
        losers    = all_cdf[all_cdf['Net P/L'] < 0]['Net P/L']
        pf_denom  = abs(losers.sum())
        prof_fac  = f'{winners.sum() / pf_denom:.2f}' if pf_denom > 0 else '∞'

        avg_cap = (
            f'{credit_cdf["Capture %"].mean():.0f}%'
            if 'Capture %' in credit_cdf.columns and not credit_cdf.empty else '—'
        )
        med_dte_o = (
            f'{credit_cdf["DTE at Open"].median():.0f}d'
            if 'DTE at Open' in credit_cdf.columns and not credit_cdf.empty else '—'
        )

        add(f'Win rate: {win_rate:.0f}%  ({int(n_wins)}/{n_trades})  |  '
            f'Avg P/L: {fmt_dollar(avg_pnl)}  |  Profit factor: {prof_fac}')
        add(f'Avg capture: {avg_cap}  |  Med DTE at open: {med_dte_o}')
    else:
        add('No closed trade history available.')
    add('')

    # ── 5. Portfolio Greeks Summary ───────────────────────────────────────────
    add('## 5. Portfolio Greeks Summary')
    add('(Options only for Greeks; equity positions included in delta and BWD.)')
    add('')

    # Option Greeks aggregation
    # net_delta_shares = Σ(delta × net_qty × 100)   — delta × net_qty gives position sign
    # net_theta        = Σ(theta × net_qty)          — theta is negative/buyer; × neg qty = positive for short
    # net_gamma        = Σ(gamma × net_qty × 100)    — negative for net short gamma book
    # net_vega         = Σ(vega  × net_qty)          — already per-contract (×100 inside bs_greeks)
    net_delta_opt = sum(p['delta'] * p['net_qty'] * 100 for p in _port_opts)
    net_theta     = sum(p['theta'] * p['net_qty']       for p in _port_opts)
    net_gamma     = sum(p['gamma'] * p['net_qty'] * 100 for p in _port_opts)
    net_vega      = sum(p['vega']  * p['net_qty']       for p in _port_opts)

    # Equity delta (each share = 1 delta)
    net_delta_eq = 0.0
    _eq_items = []   # {ticker, shares, S, beta}

    # Wheel campaign shares
    for ticker, c in open_camps:
        if c.total_shares > 0:
            live_tk = live_prices.get(ticker, {}) if has_live else {}
            S_eq    = live_tk.get('last', 0.0) or 0.0
            b_eq    = live_tk.get('beta', None)
            net_delta_eq += c.total_shares
            _eq_items.append({'ticker': ticker, 'shares': c.total_shares, 'S': S_eq, 'beta': b_eq})

    # Standalone equity
    if not _equity_rows.empty:
        for _, row in _equity_rows.iterrows():
            tkr    = str(row.get('Ticker', '?'))
            shares = float(row.get('Net_Qty', 0.0) or 0.0)
            live_tk = live_prices.get(tkr, {}) if has_live else {}
            S_eq    = live_tk.get('last', 0.0) or 0.0
            b_eq    = live_tk.get('beta', None)
            net_delta_eq += shares
            _eq_items.append({'ticker': tkr, 'shares': shares, 'S': S_eq, 'beta': b_eq})

    net_delta_total = net_delta_opt + net_delta_eq

    add(f'Net Δ (options):   {net_delta_opt:+.1f} share-equivalents')
    add(f'Net Δ (equity):    {net_delta_eq:+.1f} shares')
    add(f'Net Δ (total):     {net_delta_total:+.1f} share-equivalents')
    add(f'Net θ/day:         {net_theta:+.2f}  ({"positive = net theta collector" if net_theta >= 0 else "negative = net theta payer"})')
    add(f'Net Γ:             {net_gamma:+.4f}  ({"negative = short gamma book" if net_gamma < 0 else "positive = long gamma book"})')
    add(f'Net ν (per 1% IV): {net_vega:+.2f}  ({"negative = short vega — IV rise hurts" if net_vega < 0 else "positive = long vega — IV rise helps"})')
    add('')

    # Beta-weighted delta to SPY
    spy_price = live_prices.get('SPY', {}).get('last', 0.0) if has_live else 0.0
    if spy_price:
        bwd_opts = sum(
            p['delta'] * p['net_qty'] * 100 * p['S'] * (p['beta'] or 1.0) / spy_price
            for p in _port_opts if p['S']
        )
        bwd_eq   = sum(
            e['shares'] * e['S'] * (e['beta'] or 1.0) / spy_price
            for e in _eq_items if e['S']
        )
        bwd_total = bwd_opts + bwd_eq

        # Gather betas for display
        beta_notes = []
        seen_tickers = set()
        for p in _port_opts:
            if p['ticker'] not in seen_tickers and p['beta'] is not None:
                beta_notes.append(f"{p['ticker']} β{p['beta']:.2f}")
                seen_tickers.add(p['ticker'])
        for e in _eq_items:
            if e['ticker'] not in seen_tickers and e['beta'] is not None:
                beta_notes.append(f"{e['ticker']} β{e['beta']:.2f}")
                seen_tickers.add(e['ticker'])
        # tickers where beta defaulted to 1.0
        missing_beta = [
            p['ticker'] for p in _port_opts + _eq_items
            if p.get('beta') is None and p['ticker'] not in seen_tickers
        ]

        bwd_note = ''
        if missing_beta:
            bwd_note = f"  (β defaulted to 1.0 for: {', '.join(sorted(set(missing_beta)))})"
        beta_str = '  |  '.join(beta_notes) if beta_notes else '(all defaulted to 1.0)'

        add(f'Beta-weighted Δ to SPY (${spy_price:.2f}): {bwd_total:+.1f} SPY-equivalent deltas{bwd_note}')
        add(f'  Betas used: {beta_str}')
    else:
        add('Beta-weighted Δ to SPY: — (SPY price not available; ensure Live toggle is on)')
    add('')
    add('⚠ Buying power usage requires the TastyTrade API (account margin structure not calculable from CSV data).')

    return '\n'.join(lines)
