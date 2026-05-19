"""
tabs/tab3_wheel_campaigns.py — Tab3 Wheel Campaigns tab renderer.
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta

from config import (
    OPT_TYPES, EQUITY_TYPE, TRADE_TYPES, MONEY_TYPES,
    SUB_SELL_OPEN, SUB_ASSIGNMENT, SUB_DIVIDEND, SUB_CREDIT_INT, SUB_DEBIT_INT,
    INCOME_SUB_TYPES, DEPOSIT_SUB_TYPES,
    PAT_CLOSE, PAT_EXPIR, PAT_ASSIGN, PAT_EXERCISE, PAT_CLOSING,
    WHEEL_MIN_SHARES, LEAPS_DTE_THRESHOLD, ROLL_CHAIN_GAP_DAYS,
    ANN_RETURN_CAP, COLOURS,
)
from ui_components import (
    xe, is_share_row, is_option_row,
    identify_pos_type, translate_readable, format_cost_basis, detect_strategy,
    fmt_dollar, color_win_rate, color_pnl_cell,
    _pnl_chip, _cmp_block, _dte_chip,
    _fmt_ann_ret, _style_ann_ret, _style_chain_row,
    _color_cash_row, _color_cash_total,
    chart_layout, _badge_inline_style, render_position_card,
)
from ingestion import equity_mask, option_mask
from market_data import fetch_live_prices
from mechanics import (
    _iter_fifo_sells, build_option_chains,
    effective_basis, realized_pnl, calc_dte,
)
from models import Campaign


def render_tab3(
    all_campaigns: dict[str, list[Campaign]],
    df: pd.DataFrame,
    latest_date: pd.Timestamp,
    start_date: pd.Timestamp,
    use_lifetime: bool,
    capital_deployed: float = 0.0,
) -> None:
    """Tab 3 — Wheel Campaigns: summary table, per-campaign cards, roll chains, waterfall."""
    # Read toggle state early — required for data computation and the CSV export button.
    # Session state already holds the user's last toggle interaction before any widget renders.
    use_lifetime = st.session_state.get('use_lifetime', False)

    # ── Split into open / closed ──────────────────────────────────────────────
    # Computed here (before the header) so the CSV export button can reference
    # the open-campaign rows without a second pass over the data later.
    open_camps   = [(t, i, c) for t, cs in sorted(all_campaigns.items())
                    for i, c in enumerate(cs) if c.status == 'open'] if all_campaigns else []
    closed_camps = [(t, i, c) for t, cs in sorted(all_campaigns.items())
                    for i, c in enumerate(cs) if c.status == 'closed'] if all_campaigns else []

    # ── Data helpers ──────────────────────────────────────────────────────────

    def _summary_rows(camp_list):
        rows = []
        for ticker, i, c in camp_list:
            rpnl = realized_pnl(c, use_lifetime)
            if use_lifetime and c.total_shares > 0:
                avg_price = (c.total_cost + c.premiums + c.dividends) / c.total_shares
                effb      = c.blended_basis
            else:
                avg_price = c.blended_basis
                effb      = effective_basis(c)
            dur  = (c.end_date or latest_date) - c.start_date

            rows.append({
                'Ticker': ticker,
                'Status': '✅ Closed' if c.status == 'closed' else '🟢 Open',
                'Qty': int(c.total_shares), 'Avg Price': avg_price,
                'Cost Basis': effb, 'Premiums': c.premiums,
                'Divs': c.dividends, 'Exit': c.exit_proceeds,
                'P/L': rpnl, 'Days': dur.days,
                'Entry': c.start_date.strftime('%d/%m/%y'),
                'Time to B/E': '—',
            })
        return rows

    def _open_camps_csv(rows):
        """Convert open campaign summary rows to a UTF-8 CSV string for download.

        Emojis are stripped from the Status column so spreadsheet software
        (Excel, Google Sheets) receives plain text rather than Unicode symbols.
        Numeric columns are kept as raw values — no dollar formatting — so the
        file is immediately usable for further analysis.
        """
        df_csv = pd.DataFrame(rows)
        df_csv['Status'] = (
            df_csv['Status']
            .str.replace('🟢 ', '', regex=False)
            .str.replace('✅ ', '', regex=False)
        )
        return df_csv.to_csv(index=False)

    def _render_summary(rows):
        df = pd.DataFrame(rows)
        st.dataframe(df.style.format({
            'Avg Price': fmt_dollar, 'Cost Basis': fmt_dollar,
            'Premiums': fmt_dollar, 'Divs': fmt_dollar,
            'Exit': fmt_dollar, 'P/L': fmt_dollar,
        }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)

    # Pre-compute open rows once — reused by both the export button and the table.
    _open_rows = _summary_rows(open_camps) if open_camps else []

    # ── Header: title | CSV export | House Money toggle ───────────────────────
    _col_hdr, _col_csv, _col_live, _col_tog = st.columns([4, 1, 1, 1])
    with _col_hdr:
        st.subheader('🎯 Wheel Campaign Tracker')
    with _col_csv:
        if _open_rows:
            st.download_button(
                label='⬇️ Export CSV',
                data=_open_camps_csv(_open_rows),
                file_name='open_wheel_campaigns.csv',
                mime='text/csv',
                use_container_width=True,
                help='Download the open Wheel Campaigns table as a CSV file.',
            )
    with _col_live:
        wheel_live_on = st.toggle(
            '📡 Live',
            key='wheel_live_prices',
            help=(
                'Fetch current equity prices from Yahoo Finance to show '
                'each campaign vs its cost basis. Cached 5 min. '
                'Ticker symbols sent to Yahoo Finance servers.'
            ),
        )
    with _col_tog:
        st.toggle(
            'Lifetime "House Money"',
            key='use_lifetime',
            help='ON — combines ALL history for a ticker into one campaign. '
                 'OFF — resets breakeven every time shares hit zero.',
        )
    if use_lifetime:
        st.info('💡 **Lifetime mode** — all history for a ticker combined into one campaign.')
    else:
        st.caption(
            ('Tracks each share-holding period as a campaign — starting when you buy %d+ shares, '
             'ending when you exit. Premiums banked from covered calls, covered strangles, and '
             'short puts are credited against your cost basis. Campaigns reset when shares hit '
             'zero — toggle Lifetime mode to see your full history as one continuous position.')
            % WHEEL_MIN_SHARES
        )
    if not all_campaigns:
        st.info('No wheel campaigns found.')
        return

    # ── Open campaigns summary table ──────────────────────────────────────────
    if _open_rows:
        _render_summary(_open_rows)
    else:
        st.info('No open wheel campaigns.')

    # ── Capital Deployed + Cap Efficiency summary ─────────────────────────────
    if open_camps and capital_deployed > 0:
        _total_premiums = sum((c.premiums + c.dividends) for _, _, c in open_camps)
        _earliest_start = min(c.start_date for _, _, c in open_camps)
        _days_active    = max((latest_date - _earliest_start).days, 1)
        _wheel_eff      = _total_premiums / capital_deployed / _days_active * 365 * 100
        _cd1, _cd2      = st.columns(2)
        _cd1.metric(
            'Capital Deployed',
            fmt_dollar(capital_deployed),
            help='Cash tied up in open wheel positions (shares × entry price). Options margin not included.',
        )
        _cd2.metric(
            'Wheel Cap Efficiency',
            '%.1f%%' % _wheel_eff,
            help=(
                'Annualised premium + dividend income as a % of capital deployed in open campaigns. '
                'Benchmark: S&P ~10%/yr. Note: options margin is excluded from the denominator — '
                'treat as a directional indicator, not a precise risk-adjusted return.'
            ),
        )

    # ── Closed campaigns summary table (collapsed) ────────────────────────────
    if closed_camps:
        with st.expander(f'📁 {len(closed_camps)} Closed Campaign{"s" if len(closed_camps) != 1 else ""}', expanded=False):
            _render_summary(_summary_rows(closed_camps))

    # ── Live equity prices for campaign cards ────────────────────────────────
    live_prices: dict = {}
    if wheel_live_on:
        _wheel_tickers = frozenset(
            ticker for ticker, _, c in open_camps if c.total_shares > 0
        )
        if _wheel_tickers:
            with st.spinner('Fetching live prices…'):
                _raw = fetch_live_prices(_wheel_tickers, frozenset())
            if _raw and any(v['last'] > 0 for v in _raw.values()):
                live_prices = {t: d for t, d in _raw.items()}
                st.caption(
                    '📡 Prices: Yahoo Finance — near real-time during market hours. '
                    'Cached 5 min. Ticker symbols sent to Yahoo Finance servers.'
                )

    st.markdown('---')

    # ── Open campaign cards ───────────────────────────────────────────────────
    for _camp_idx, (ticker, i, c) in enumerate(open_camps):
        rpnl = realized_pnl(c, use_lifetime)
        if use_lifetime and c.total_shares > 0:
            _entry_basis_card = (c.total_cost + c.premiums + c.dividends) / c.total_shares
            effb = c.blended_basis
        else:
            _entry_basis_card = c.blended_basis
            effb = effective_basis(c)
        is_open         = True
        pnl_color       = COLOURS['green'] if rpnl >= 0 else COLOURS['red']
        basis_reduction = _entry_basis_card - effb
        _camp_deployed  = c.total_shares * c.blended_basis
        _camp_days      = max((latest_date - c.start_date).days, 1)
        _camp_eff       = (
            (c.premiums + c.dividends) / _camp_deployed / _camp_days * 365 * 100
            if _camp_deployed > 0 else None
        )
        _camp_eff_str   = '%.1f%%' % _camp_eff if _camp_eff is not None else '—'
        _camp_eff_color = COLOURS['green'] if (_camp_eff or 0) >= 10 else '#ffa421' if (_camp_eff or 0) >= 0 else COLOURS['red']
        _asgn_events = [e for e in c.events if str(e.get('type', '')).startswith('Assignment Put')]
        if _asgn_events:
            _excl = sum(e.get('cash', 0) for e in _asgn_events)
            _assignment_note = (
                '<div style="margin-top:10px;padding:6px 10px;'
                'background:rgba(240,165,0,0.08);border-radius:6px;'
                'font-size:0.72em;color:#f0a500;text-align:left;">'
                '&#9888;&#65039; Entered via put assignment \u2014 put credit '
                '($%.2f) is in pre-purchase P/L and is not included in Cost Basis.'
                '</div>' % abs(_excl)
            )
        else:
            _assignment_note = ''
        _mid_asgn_events = [e for e in c.events if str(e.get('type', '')).startswith('Mid-campaign Assignment')]
        if _mid_asgn_events:
            _mid_dates = ', '.join(e['date'].strftime('%d/%m/%y') for e in _mid_asgn_events)
            _mid_asgn_note = (
                '<div style="margin-top:6px;padding:6px 10px;'
                'background:rgba(99,110,250,0.08);border-radius:6px;'
                'font-size:0.72em;color:#636efa;text-align:left;">'
                'ℹ️ Shares added via put assignment on %s \u2014 premium already included in Cost Basis.'
                '</div>' % _mid_dates
            )
        else:
            _mid_asgn_note = ''
        if c.pre_campaign_close_net != 0.0:
            _pre_camp_note = (
                '<div style="margin-top:6px;padding:6px 10px;'
                'background:rgba(240,165,0,0.08);border-radius:6px;'
                'font-size:0.72em;color:#f0a500;text-align:left;">'
                '&#9888;&#65039; Premiums include <b>$%.2f</b> in closing debits from options opened '
                'before the share purchase. Their opening credits are in pre-purchase P/L.'
                '</div>' % c.pre_campaign_close_net
            )
        else:
            _pre_camp_note = ''
        # ── Time to Breakeven (requires live prices) ──────────────────────────
        # B/E means effective basis = current market price.
        # Additional income needed = (effb - current_price) × shares.
        _ticker_live_early = live_prices.get(ticker)
        if _ticker_live_early and _ticker_live_early.get('last', 0.0) and c.total_shares > 0:
            _be_price       = float(_ticker_live_early['last'])
            _be_days_active = max(1, (latest_date - c.start_date).days)
            _be_income      = c.premiums + c.dividends
            _be_rate        = _be_income / _be_days_active
            _be_gap         = (effb - _be_price) * c.total_shares  # positive = still underwater
            if effb <= _be_price:
                _time_to_be = '✅ B/E'
            elif _be_rate > 0:
                _time_to_be = '~%dd' % int(_be_gap / _be_rate)
            else:
                _time_to_be = '—'
        else:
            _time_to_be = '—'

        # ── Live price strip ──────────────────────────────────────────────────
        _ticker_live = live_prices.get(ticker)
        if _ticker_live and _ticker_live.get('last', 0.0) and c.total_shares > 0:
            _lp_last    = float(_ticker_live['last'])
            _lp_prev    = float(_ticker_live.get('prev_close', _lp_last))
            _lp_chg     = _lp_last - _lp_prev
            _lp_chg_pct = (_lp_chg / _lp_prev * 100) if _lp_prev else 0.0
            _lp_chg_sgn = '+' if _lp_chg >= 0 else ''
            _lp_chg_col = COLOURS['green'] if _lp_chg >= 0 else COLOURS['red']
            _lp_gap     = _lp_last - effb
            _lp_gap_pct = (_lp_gap / effb * 100) if effb else 0.0
            _lp_above   = _lp_gap >= 0
            _lp_accent  = COLOURS['green'] if _lp_above else COLOURS['red']
            _lp_gap_sgn = '+' if _lp_above else ''
            _lp_unreal  = _lp_gap * c.total_shares
            _lp_u_col   = COLOURS['green'] if _lp_unreal >= 0 else COLOURS['red']
            _lp_u_sgn   = '+' if _lp_unreal >= 0 else ''
            _lp_label   = 'ABOVE BASIS' if _lp_above else 'BELOW BASIS'
            _mut        = COLOURS['text_muted']
            _dim        = COLOURS['text_dim']
            _txt        = COLOURS['text']
            live_strip = (
                f'<div style="margin-top:10px;padding:8px 14px;'
                f'background:rgba(255,255,255,0.03);border-radius:6px;'
                f'border-left:3px solid {_lp_accent};'
                f'display:flex;flex-wrap:wrap;align-items:center;gap:8px 24px;">'
                f'<div><div style="font-size:0.7em;color:{_mut};margin-bottom:1px;">LIVE</div>'
                f'<div style="font-family:monospace;font-size:1.0em;font-weight:700;color:{_txt};">${_lp_last:,.2f}</div>'
                f'<div style="font-family:monospace;font-size:0.75em;color:{_lp_chg_col};">{_lp_chg_sgn}{_lp_chg:.2f} ({_lp_chg_sgn}{_lp_chg_pct:.2f}%)</div></div>'
                f'<div style="width:1px;height:38px;background:rgba(255,255,255,0.07);flex-shrink:0;"></div>'
                f'<div><div style="font-size:0.7em;color:{_mut};margin-bottom:1px;">VS COST BASIS</div>'
                f'<div style="font-family:monospace;font-size:1.0em;font-weight:700;color:{_lp_accent};">{_lp_label}</div>'
                f'<div style="font-size:0.7em;color:{_dim};">basis ${effb:.2f}/sh</div></div>'
                f'<div style="width:1px;height:38px;background:rgba(255,255,255,0.07);flex-shrink:0;"></div>'
                f'<div><div style="font-size:0.7em;color:{_mut};margin-bottom:1px;">GAP TO B/E</div>'
                f'<div style="font-family:monospace;font-size:1.0em;font-weight:700;color:{_lp_accent};">{_lp_gap_sgn}${abs(_lp_gap):.2f}/sh</div>'
                f'<div style="font-family:monospace;font-size:0.75em;color:{_lp_accent};">{_lp_gap_sgn}{abs(_lp_gap_pct):.1f}%</div></div>'
                f'<div style="width:1px;height:38px;background:rgba(255,255,255,0.07);flex-shrink:0;"></div>'
                f'<div><div style="font-size:0.7em;color:{_mut};margin-bottom:1px;">UNREALISED</div>'
                f'<div style="font-family:monospace;font-size:1.0em;font-weight:700;color:{_lp_u_col};">{_lp_u_sgn}${abs(_lp_unreal):,.2f}</div>'
                f'<div style="font-size:0.7em;color:{_dim};">{int(c.total_shares)} sh × {_lp_gap_sgn}${abs(_lp_gap):.2f}</div></div>'
                f'</div>'
            )
        else:
            live_strip = ''

        card_html = (
            '<div style="border:1px solid {border};border-radius:10px;padding:16px 20px 12px 20px;'
            'margin-bottom:12px;background:rgba(255,255,255,0.03);">'
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">'
            '<span style="font-size:1.2em;font-weight:700;">{ticker}'
            '<span style="font-size:0.75em;font-weight:400;color:#888;margin-left:8px;">Campaign {camp_n}</span>'
            '</span>'
            '<span style="font-size:0.8em;font-weight:600;padding:3px 10px;border-radius:20px;'
            'background:{badge_bg};color:{badge_col};">{status}</span>'
            '</div>'
            '<div style="display:grid;grid-template-columns:repeat(8,1fr);gap:12px;text-align:center;">'
            '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">ENTRY</div>'
            '<div style="font-size:1.0em;font-weight:600;">{acquired}</div></div>'
            '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">SHARES</div>'
            '<div style="font-size:1.0em;font-weight:600;">{shares}</div></div>'
            '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">ENTRY BASIS</div>'
            '<div style="font-size:1.0em;font-weight:600;">${entry_basis:.2f}/sh</div></div>'
            '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">COST BASIS</div>'
            '<div style="font-size:1.0em;font-weight:600;">${eff_basis:.2f}/sh</div>'
            '<div style="font-size:0.7em;color:#00cc96;">▼ ${reduction:.2f} saved</div></div>'
            '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">TIME TO B/E</div>'
            '<div style="font-size:1.0em;font-weight:600;">{free_in}</div>'
            '<div style="font-size:0.7em;color:#888;">vs live price</div></div>'
            '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">PREMIUMS</div>'
            '<div style="font-size:1.0em;font-weight:600;">${premiums:.2f}</div></div>'
            '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">CAP EFF (ann)</div>'
            '<div style="font-size:1.0em;font-weight:600;color:{camp_eff_color};">{camp_eff}</div>'
            '<div style="font-size:0.7em;color:#888;">vs S&P ~10%</div></div>'
            '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">REALIZED P/L</div>'
            '<div style="font-size:1.1em;font-weight:700;color:{pnl_color};">${pnl:+.2f}</div></div>'
            '</div>{live_strip}{assignment_note}{mid_asgn_note}{pre_camp_note}</div>'
        ).format(
            border=COLOURS['green'] if is_open else '#444',
            ticker=xe(ticker), camp_n=i + 1,
            status=xe('🟢 OPEN' if is_open else '✅ CLOSED'),
            badge_bg='rgba(0,204,150,0.15)' if is_open else 'rgba(100,100,100,0.2)',
            badge_col=COLOURS['green'] if is_open else '#888',
            acquired=c.start_date.strftime('%d/%m/%y'),
            shares=int(c.total_shares),
            entry_basis=_entry_basis_card, eff_basis=effb,
            reduction=basis_reduction if basis_reduction > 0 else 0,
            free_in=_time_to_be,
            premiums=c.premiums, pnl=rpnl, pnl_color=pnl_color,
            camp_eff=_camp_eff_str, camp_eff_color=_camp_eff_color,
            live_strip=live_strip,
            assignment_note=_assignment_note,
            mid_asgn_note=_mid_asgn_note,
            pre_camp_note=_pre_camp_note,
        )
        st.markdown(card_html, unsafe_allow_html=True)

        with st.expander('📊 Detail — Chains & Events', expanded=is_open):
            ticker_opts = df[
                (df['Ticker'] == ticker) & option_mask(df['Instrument Type'])
            ].copy()
            camp_end = c.end_date or latest_date
            ticker_opts = ticker_opts[
                (ticker_opts['Date'] >= c.start_date) & (ticker_opts['Date'] <= camp_end)
            ]

            chains = build_option_chains(ticker_opts)
            if chains:
                st.markdown('**📎 Option Roll Chains**')
                st.caption(
                    'Calls and puts tracked as separate chains. Rolls within ~3 days stay in '
                    'the same chain; longer gaps start a new one. Complex structures '
                    '(PMCC, Jade Lizards, Iron Condors) are not fully decomposed — P/L is '
                    'correct in the campaign total, but the chain view may show fragments.'
                )
                for ci, chain in enumerate(chains):
                    cp     = chain[0]['cp']
                    ch_pnl = sum(leg['total'] for leg in chain)
                    # Replay net_qty to determine open/closed status. Checking only
                    # the last event's sub_type is wrong when an STO has an earlier
                    # timestamp than its paired BTC (rapid rolls in the same second
                    # or same minute sort STO before BTC, leaving BTC as the final leg).
                    _net = 0
                    _last_sto_idx = -1
                    for _i, _leg in enumerate(chain):
                        _sub = str(_leg['sub_type']).lower()
                        if 'to open' in _sub and _leg['qty'] < 0:
                            _net += abs(_leg['qty'])
                            _last_sto_idx = _i
                        elif _net > 0 and (PAT_CLOSE in _sub or 'expiration' in _sub or 'assignment' in _sub):
                            _net = max(_net - abs(_leg['qty']), 0)
                    is_open_chain = _net > 0
                    n_rolls       = sum(1 for leg in chain
                                        if PAT_CLOSE in str(leg['sub_type']).lower())
                    chain_label = '%s %s %s Chain %d — %d roll(s) | Net: $%.2f' % (
                        '🟢' if is_open_chain else '✅',
                        '📞' if cp == 'CALL' else '📉',
                        cp.title(), ci + 1, n_rolls, ch_pnl
                    )
                    with st.expander(chain_label, expanded=is_open_chain):
                        chain_rows = []
                        _open_dates    = {}   # (strike, exp) -> open date for days-held lookup
                        _open_pair_idx = {}   # (strike, exp) -> pair_idx so BTC shares its STO's colour
                        pair_idx = -1
                        for leg_i, leg in enumerate(chain):
                            sub  = str(leg['sub_type']).lower()
                            _key = (leg['strike'], leg['exp'])
                            if 'to open' in sub:
                                pair_idx += 1
                                action = '↪️ Sell to Open'
                                _open_dates[_key]    = leg['date']
                                _open_pair_idx[_key] = pair_idx
                                dit_str  = ''
                                row_pair = pair_idx
                            elif PAT_CLOSE in sub:
                                action   = '↩️ Buy to Close'
                                _od      = _open_dates.pop(_key, None)
                                dit_str  = '%dd' % (leg['date'] - _od).days if _od else ''
                                row_pair = _open_pair_idx.pop(_key, pair_idx)
                            elif PAT_EXPIR in sub:
                                action   = '⏹️ Expired'
                                _od      = _open_dates.pop(_key, None)
                                dit_str  = '%dd' % (leg['date'] - _od).days if _od else ''
                                row_pair = _open_pair_idx.pop(_key, pair_idx)
                            elif PAT_ASSIGN in sub:
                                action   = '📋 Assigned'
                                _od      = _open_dates.pop(_key, None)
                                dit_str  = '%dd' % (leg['date'] - _od).days if _od else ''
                                row_pair = _open_pair_idx.pop(_key, pair_idx)
                            else:
                                action   = leg['sub_type']
                                dit_str  = ''
                                row_pair = pair_idx
                            dte_str = ''
                            if 'to open' in sub:
                                try:
                                    exp_dt  = pd.to_datetime(leg['exp'], dayfirst=True)
                                    dte_str = '%dd' % max((exp_dt - leg['date']).days, 0)
                                except (ValueError, TypeError):
                                    dte_str = ''
                            is_open_leg = is_open_chain and leg_i == _last_sto_idx
                            chain_rows.append({
                                'Date':   leg['date'].strftime('%d/%m/%y'),
                                'Action': ('🟢 ' + action) if is_open_leg else action,
                                'Strike': '%.1f%s' % (leg['strike'], cp[0]),
                                'Expiry': leg['exp'], 'DTE': dte_str, 'Days Held': dit_str,
                                'Credit/Debit Rcvd': leg['total'], '_open': is_open_leg,
                                '_pair': row_pair,
                            })
                        ch_df = pd.DataFrame(chain_rows)
                        ch_df = pd.concat([ch_df, pd.DataFrame([{
                            'Date': '', 'Action': '━━ Chain Total',
                            'Strike': '', 'Expiry': '', 'DTE': '', 'Days Held': '',
                            'Credit/Debit Rcvd': ch_pnl, '_open': False, '_pair': -1,
                        }])], ignore_index=True)
                        st.dataframe(
                            ch_df[['Date', 'Action', 'Strike', 'Expiry', 'DTE', 'Days Held', 'Credit/Debit Rcvd', '_open', '_pair']]
                            .style.apply(_style_chain_row, axis=1)
                            .format({'Credit/Debit Rcvd': lambda x: '${:.2f}'.format(x)})
                            .map(lambda v: 'color: #00cc96' if isinstance(v, float) and v > 0
                                else ('color: #ef553b' if isinstance(v, float) and v < 0 else ''),
                                subset=['Credit/Debit Rcvd']),
                            width='stretch', hide_index=True,
                            column_config={'_open': None, '_pair': None}
                        )

            st.markdown('**📋 Share & Dividend Events**')
            ev_df    = pd.DataFrame(c.events)
            ev_share = ev_df[~ev_df['type'].str.lower().str.contains(
                'to open|to close|expir|assign', na=False
            )]
            if not ev_share.empty:
                ev_share = ev_share.copy()
                ev_share['date'] = pd.to_datetime(ev_share['date']).dt.strftime('%d/%m/%y %H:%M')
                ev_share.columns = ['Date', 'Type', 'Detail', 'Amount']
                st.dataframe(
                    ev_share.style.format({'Amount': fmt_dollar})
                    .map(lambda v: 'color: #00cc96' if isinstance(v, float) and v > 0
                        else ('color: #ef553b' if isinstance(v, float) and v < 0 else ''),
                        subset=['Amount']),
                    width='stretch', hide_index=True
                )
            else:
                st.caption('No share/dividend events.')

    # ── Closed campaign cards (collapsed) ─────────────────────────────────────
    if closed_camps:
        st.markdown('---')
        with st.expander(f'📁 {len(closed_camps)} Closed Campaign{"s" if len(closed_camps) != 1 else ""} — click to expand cards', expanded=False):
            for ticker, i, c in closed_camps:
                rpnl = realized_pnl(c, use_lifetime)
                if use_lifetime and c.total_shares > 0:
                    _entry_basis_card = (c.total_cost + c.premiums + c.dividends) / c.total_shares
                    effb = c.blended_basis
                else:
                    _entry_basis_card = c.blended_basis
                    effb = effective_basis(c)
                is_open         = False
                pnl_color       = COLOURS['green'] if rpnl >= 0 else COLOURS['red']
                basis_reduction = _entry_basis_card - effb
                _asgn_events = [e for e in c.events if str(e.get('type', '')).startswith('Assignment Put')]
                if _asgn_events:
                    _excl = sum(e.get('cash', 0) for e in _asgn_events)
                    _assignment_note = (
                        '<div style="margin-top:10px;padding:6px 10px;'
                        'background:rgba(240,165,0,0.08);border-radius:6px;'
                        'font-size:0.72em;color:#f0a500;text-align:left;">'
                        '&#9888;&#65039; Entered via put assignment \u2014 put credit '
                        '($%.2f) is in pre-purchase P/L and is not included in Cost Basis.'
                        '</div>' % abs(_excl)
                    )
                else:
                    _assignment_note = ''
                _mid_asgn_events = [e for e in c.events if str(e.get('type', '')).startswith('Mid-campaign Assignment')]
                if _mid_asgn_events:
                    _mid_dates = ', '.join(e['date'].strftime('%d/%m/%y') for e in _mid_asgn_events)
                    _mid_asgn_note = (
                        '<div style="margin-top:6px;padding:6px 10px;'
                        'background:rgba(99,110,250,0.08);border-radius:6px;'
                        'font-size:0.72em;color:#636efa;text-align:left;">'
                        'ℹ️ Shares added via put assignment on %s \u2014 premium already included in Cost Basis.'
                        '</div>' % _mid_dates
                    )
                else:
                    _mid_asgn_note = ''
                if c.pre_campaign_close_net != 0.0:
                    _pre_camp_note = (
                        '<div style="margin-top:6px;padding:6px 10px;'
                        'background:rgba(240,165,0,0.08);border-radius:6px;'
                        'font-size:0.72em;color:#f0a500;text-align:left;">'
                        '&#9888;&#65039; Premiums include <b>$%.2f</b> in closing debits from options opened '
                        'before the share purchase. Their opening credits are in pre-purchase P/L.'
                        '</div>' % c.pre_campaign_close_net
                    )
                else:
                    _pre_camp_note = ''
                card_html = (
                    '<div style="border:1px solid {border};border-radius:10px;padding:16px 20px 12px 20px;'
                    'margin-bottom:12px;background:rgba(255,255,255,0.03);">'
                    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">'
                    '<span style="font-size:1.2em;font-weight:700;">{ticker}'
                    '<span style="font-size:0.75em;font-weight:400;color:#888;margin-left:8px;">Campaign {camp_n}</span>'
                    '</span>'
                    '<span style="font-size:0.8em;font-weight:600;padding:3px 10px;border-radius:20px;'
                    'background:{badge_bg};color:{badge_col};">✅ CLOSED</span>'
                    '</div>'
                    '<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:12px;text-align:center;">'
                    '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">ENTRY</div>'
                    '<div style="font-size:1.0em;font-weight:600;">{acquired}</div></div>'
                    '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">SHARES</div>'
                    '<div style="font-size:1.0em;font-weight:600;">{shares}</div></div>'
                    '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">ENTRY BASIS</div>'
                    '<div style="font-size:1.0em;font-weight:600;">${entry_basis:.2f}/sh</div></div>'
                    '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">COST BASIS</div>'
                    '<div style="font-size:1.0em;font-weight:600;">${eff_basis:.2f}/sh</div>'
                    '<div style="font-size:0.7em;color:#00cc96;">▼ ${reduction:.2f} saved</div></div>'
                    '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">PREMIUMS</div>'
                    '<div style="font-size:1.0em;font-weight:600;">${premiums:.2f}</div></div>'
                    '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">REALIZED P/L</div>'
                    '<div style="font-size:1.1em;font-weight:700;color:{pnl_color};">${pnl:+.2f}</div></div>'
                    '</div>{assignment_note}{mid_asgn_note}{pre_camp_note}</div>'
                ).format(
                    border='#444',
                    ticker=xe(ticker), camp_n=i + 1,
                    badge_bg='rgba(100,100,100,0.2)', badge_col='#888',
                    acquired=c.start_date.strftime('%d/%m/%y'),
                    shares=int(c.total_shares),
                    entry_basis=_entry_basis_card, eff_basis=effb,
                    reduction=basis_reduction if basis_reduction > 0 else 0,
                    premiums=c.premiums, pnl=rpnl, pnl_color=pnl_color,
                    assignment_note=_assignment_note,
                    mid_asgn_note=_mid_asgn_note,
                    pre_camp_note=_pre_camp_note,
                )
                st.markdown(card_html, unsafe_allow_html=True)

                with st.expander('📊 Detail — Chains & Events', expanded=False):
                    ticker_opts = df[
                        (df['Ticker'] == ticker) & option_mask(df['Instrument Type'])
                    ].copy()
                    camp_end = c.end_date or latest_date
                    ticker_opts = ticker_opts[
                        (ticker_opts['Date'] >= c.start_date) & (ticker_opts['Date'] <= camp_end)
                    ]
                    chains = build_option_chains(ticker_opts)
                    if chains:
                        st.markdown('**📎 Option Roll Chains**')
                        st.caption(
                            'Calls and puts tracked as separate chains. Rolls within ~3 days stay in '
                            'the same chain; longer gaps start a new one.'
                        )
                        for ci, chain in enumerate(chains):
                            cp     = chain[0]['cp']
                            ch_pnl = sum(leg['total'] for leg in chain)
                            _net = 0
                            _last_sto_idx = -1
                            for _i, _leg in enumerate(chain):
                                _sub = str(_leg['sub_type']).lower()
                                if 'to open' in _sub and _leg['qty'] < 0:
                                    _net += abs(_leg['qty'])
                                    _last_sto_idx = _i
                                elif _net > 0 and (PAT_CLOSE in _sub or 'expiration' in _sub or 'assignment' in _sub):
                                    _net = max(_net - abs(_leg['qty']), 0)
                            is_open_chain = _net > 0
                            n_rolls       = sum(1 for leg in chain
                                                if PAT_CLOSE in str(leg['sub_type']).lower())
                            chain_label = '%s %s %s Chain %d — %d roll(s) | Net: $%.2f' % (
                                '🟢' if is_open_chain else '✅',
                                '📞' if cp == 'CALL' else '📉',
                                cp.title(), ci + 1, n_rolls, ch_pnl
                            )
                            with st.expander(chain_label, expanded=is_open_chain):
                                chain_rows = []
                                _open_dates    = {}
                                _open_pair_idx = {}
                                pair_idx = -1
                                for leg_i, leg in enumerate(chain):
                                    sub  = str(leg['sub_type']).lower()
                                    _key = (leg['strike'], leg['exp'])
                                    if 'to open' in sub:
                                        pair_idx += 1
                                        action = '↪️ Sell to Open'
                                        _open_dates[_key]    = leg['date']
                                        _open_pair_idx[_key] = pair_idx
                                        dit_str  = ''
                                        row_pair = pair_idx
                                    elif PAT_CLOSE in sub:
                                        action   = '↩️ Buy to Close'
                                        _od      = _open_dates.pop(_key, None)
                                        dit_str  = '%dd' % (leg['date'] - _od).days if _od else ''
                                        row_pair = _open_pair_idx.pop(_key, pair_idx)
                                    elif PAT_EXPIR in sub:
                                        action   = '⏹️ Expired'
                                        _od      = _open_dates.pop(_key, None)
                                        dit_str  = '%dd' % (leg['date'] - _od).days if _od else ''
                                        row_pair = _open_pair_idx.pop(_key, pair_idx)
                                    elif PAT_ASSIGN in sub:
                                        action   = '📋 Assigned'
                                        _od      = _open_dates.pop(_key, None)
                                        dit_str  = '%dd' % (leg['date'] - _od).days if _od else ''
                                        row_pair = _open_pair_idx.pop(_key, pair_idx)
                                    else:
                                        action   = leg['sub_type']
                                        dit_str  = ''
                                        row_pair = pair_idx
                                    dte_str = ''
                                    if 'to open' in sub:
                                        try:
                                            exp_dt  = pd.to_datetime(leg['exp'], dayfirst=True)
                                            dte_str = '%dd' % max((exp_dt - leg['date']).days, 0)
                                        except (ValueError, TypeError):
                                            dte_str = ''
                                    is_open_leg = is_open_chain and leg_i == _last_sto_idx
                                    chain_rows.append({
                                        'Date':   leg['date'].strftime('%d/%m/%y'),
                                        'Action': ('🟢 ' + action) if is_open_leg else action,
                                        'Strike': '%.1f%s' % (leg['strike'], cp[0]),
                                        'Expiry': leg['exp'], 'DTE': dte_str, 'Days Held': dit_str,
                                        'Credit/Debit Rcvd': leg['total'], '_open': is_open_leg,
                                        '_pair': row_pair,
                                    })
                                ch_df = pd.DataFrame(chain_rows)
                                ch_df = pd.concat([ch_df, pd.DataFrame([{
                                    'Date': '', 'Action': '━━ Chain Total',
                                    'Strike': '', 'Expiry': '', 'DTE': '', 'Days Held': '',
                                    'Credit/Debit Rcvd': ch_pnl, '_open': False, '_pair': -1,
                                }])], ignore_index=True)
                                st.dataframe(
                                    ch_df[['Date', 'Action', 'Strike', 'Expiry', 'DTE', 'Days Held', 'Credit/Debit Rcvd', '_open', '_pair']]
                                    .style.apply(_style_chain_row, axis=1)
                                    .format({'Credit/Debit Rcvd': lambda x: '${:.2f}'.format(x)})
                                    .map(lambda v: 'color: #00cc96' if isinstance(v, float) and v > 0
                                        else ('color: #ef553b' if isinstance(v, float) and v < 0 else ''),
                                        subset=['Credit/Debit Rcvd']),
                                    width='stretch', hide_index=True,
                                    column_config={'_open': None, '_pair': None}
                                )

                    st.markdown('**📋 Share & Dividend Events**')
                    ev_df    = pd.DataFrame(c.events)
                    ev_share = ev_df[~ev_df['type'].str.lower().str.contains(
                        'to open|to close|expir|assign', na=False
                    )]
                    if not ev_share.empty:
                        ev_share = ev_share.copy()
                        ev_share['date'] = pd.to_datetime(ev_share['date']).dt.strftime('%d/%m/%y %H:%M')
                        ev_share.columns = ['Date', 'Type', 'Detail', 'Amount']
                        st.dataframe(
                            ev_share.style.format({'Amount': fmt_dollar})
                            .map(lambda v: 'color: #00cc96' if isinstance(v, float) and v > 0
                                else ('color: #ef553b' if isinstance(v, float) and v < 0 else ''),
                                subset=['Amount']),
                            width='stretch', hide_index=True
                        )
                    else:
                        st.caption('No share/dividend events.')


