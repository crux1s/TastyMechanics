"""
position_snapshot.py — Builds a structured AI review prompt from current open positions.

No Streamlit dependency. Pure function — takes AppData fields + live prices, returns a
plain-text string ready to paste into any LLM (Claude, ChatGPT, Gemini, etc.).

Options are presented in TastyTrade-style human-readable notation:
    SOFI  15 Aug 25  $12.50 Put   (short, ×1)
"""

import math
import pandas as pd

from config import OPT_TYPES, INCOME_SUB_TYPES, PAT_CLOSING, LEAPS_DTE_THRESHOLD
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
    add(f'As of: {as_of.strftime("%d %b %Y")}  ({"live prices; ~15 min delay" if has_live else "no live prices — upload CSV and enable live data"})')
    add('')
    add('⚠️  IVR and portfolio-level Greeks require TastyTrade API access.')
    add('   NLV, buying power, and beta-weighted delta are not shown here.')
    add('')

    # ── 1. Account Summary ────────────────────────────────────────────────────
    add('## 1. Account Summary')
    add(f'- Realized P/L (all-time):         {fmt_dollar(total_realized_pnl)}')
    add(f'- Capital deployed (shares):        {fmt_dollar(capital_deployed)}')
    add(f'- Premiums banked (open wheels):    {fmt_dollar(open_premiums_banked)}')
    add('')

    # ── 2. Open Wheel Campaigns ───────────────────────────────────────────────
    add('## 2. Open Wheel Campaigns')
    open_camps = [
        (ticker, c)
        for ticker, camps in (all_campaigns.items() if hasattr(all_campaigns, 'items') else [])
        for c in camps
        if c.status == 'open'
    ]
    if open_camps:
        add(f'{"Ticker":<7} {"Shares":>6}  {"Entry":>7}  {"Eff Basis":>9}  {"Last":>7}  '
            f'{"Unreal $":>9}  {"Unreal %":>8}  {"Premiums":>9}  {"Days":>5}')
        add('-' * 80)
        for ticker, c in open_camps:
            effb = effective_basis(c, use_lifetime)
            days = (as_of - pd.Timestamp(c.start_date)).days

            live_tk  = live_prices.get(ticker, {}) if has_live else {}
            last     = live_tk.get('last', None)

            if last and c.total_shares > 0:
                unreal   = (last - effb) * c.total_shares
                unreal_p = _pct(unreal, effb * c.total_shares)
                last_str = f'${last:>6.2f}'
            else:
                unreal   = None
                unreal_p = '—'
                last_str = '—'

            unreal_str = fmt_dollar(unreal) if unreal is not None else '—'
            add(f'{ticker:<7} {int(c.total_shares):>6}  ${c.blended_basis:>6.2f}  ${effb:>8.2f}  '
                f'{last_str:>7}  {unreal_str:>9}  {unreal_p:>8}  '
                f'{fmt_dollar(c.premiums):>9}  {days:>4}d')
    else:
        add('No open wheel campaigns.')
    add('')

    # ── 3. Open Option Positions ──────────────────────────────────────────────
    add('## 3. Open Option Positions')

    _opt_rows = pd.DataFrame()
    if not df_open.empty and 'Instrument Type' in df_open.columns:
        _opt_mask = df_open['Instrument Type'].isin(OPT_TYPES)
        _opt_rows = df_open[_opt_mask].copy()

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
                # Try to find a matching key — strike may have float precision differences
                for (exp_k, str_k, cp_k), opt_data in live_tk.get('options', {}).items():
                    if cp_k == cp and abs(str_k - strike) < 0.01:
                        # expiry key match — check date proximity
                        try:
                            exp_date = pd.to_datetime(expiry, format='mixed', errors='coerce').normalize()
                            key_date = pd.to_datetime(exp_k, errors='coerce').normalize()
                            if abs((exp_date - key_date).days) <= 1:
                                opt_key = opt_data
                                break
                        except Exception:
                            pass

            if opt_key:
                bid  = opt_key.get('bid', 0.0) or 0.0
                ask  = opt_key.get('ask', 0.0) or 0.0
                mark = opt_key.get('mark', 0.0) or 0.0
                iv_raw = opt_key.get('iv', None)

                mark_str = f'${mark:.2f}'
                bid_str  = f'${bid:.2f}'
                ask_str  = f'${ask:.2f}'
                iv_str   = f'{iv_raw*100:.1f}%' if iv_raw else '—'

            # Stock price context + open P/L
            live_tk = live_prices.get(ticker, {}) if has_live else {}
            S = live_tk.get('last', 0.0) or 0.0

            stock_str = f'${S:.2f}' if S else '—'
            if S and strike:
                otm_pct = (S / strike - 1) * 100 if cp == 'CALL' else (strike / S - 1) * 100
                otm_str = f'{otm_pct:+.1f}%% OTM' if otm_pct >= 0 else f'{abs(otm_pct):.1f}%% ITM'
            else:
                otm_str = '—'

            if opt_key:
                mark_val = opt_key.get('mark', 0.0) or 0.0
                open_pnl = (cost_b + mark_val * 100) if net_qty < 0 else (mark_val * 100 - cost_b)
                open_pnl_str = fmt_dollar(open_pnl)
            else:
                open_pnl_str = '—'

            add(f'  Stock {stock_str} ({otm_str})  |  Mark {mark_str}  |  Bid {bid_str}  Ask {ask_str}')
            add(f'  IV {iv_str}  |  DTE {dte_str}  |  Cost basis {fmt_dollar(cost_b)}  |  Open P/L {open_pnl_str}')

            # Greeks — theta sign flipped for short positions (seller collects decay)
            if iv_raw and iv_raw > 0 and dte_val and dte_val > 0 and S > 0:
                T        = dte_val / 365.0
                greeks   = bs_greeks(S, strike, T, _RISK_FREE_RATE, iv_raw, cp)
                direction = -1 if net_qty < 0 else 1   # short = collect theta (positive)
                delta_s  = _fmt_greek(greeks['delta'],            '.2f')
                gamma_s  = _fmt_greek(greeks['gamma'],            '.4f')
                theta_s  = _fmt_greek(greeks['theta'] * direction, '+.2f')
                vega_s   = _fmt_greek(greeks['vega'],              '.2f')
                add(f'  Δ {delta_s}  Γ {gamma_s}  θ {theta_s}/day  ν {vega_s}')
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

        avg_cap   = (
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

    return '\n'.join(lines)
