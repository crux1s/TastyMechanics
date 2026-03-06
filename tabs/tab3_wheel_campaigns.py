"""
tabs/tab3_wheel_campaigns.py — Tab3 Wheel Campaigns tab renderer.
"""

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
from mechanics import (
    _iter_fifo_sells, build_option_chains,
    effective_basis, realized_pnl, calc_dte,
)


def render_tab3(all_campaigns, df, latest_date, start_date, use_lifetime):
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
            effb = effective_basis(c, use_lifetime)
            dur  = (c.end_date or latest_date) - c.start_date
            rows.append({
                'Ticker': ticker,
                'Status': '✅ Closed' if c.status == 'closed' else '🟢 Open',
                'Qty': int(c.total_shares), 'Avg Price': c.blended_basis,
                'Eff. Basis': effb, 'Premiums': c.premiums,
                'Divs': c.dividends, 'Exit': c.exit_proceeds,
                'P/L': rpnl, 'Days': dur.days,
                'Opened': c.start_date.strftime('%d/%m/%y'),
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
            'Avg Price': fmt_dollar, 'Eff. Basis': fmt_dollar,
            'Premiums': fmt_dollar, 'Divs': fmt_dollar,
            'Exit': fmt_dollar, 'P/L': fmt_dollar,
        }).map(color_pnl_cell, subset=['P/L']), width='stretch', hide_index=True)

    # Pre-compute open rows once — reused by both the export button and the table.
    _open_rows = _summary_rows(open_camps) if open_camps else []

    # ── Header: title | CSV export | House Money toggle ───────────────────────
    _col_hdr, _col_csv, _col_tog = st.columns([4, 1, 1])
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

    # ── Closed campaigns summary table (collapsed) ────────────────────────────
    if closed_camps:
        with st.expander(f'📁 {len(closed_camps)} Closed Campaign{"s" if len(closed_camps) != 1 else ""}', expanded=False):
            _render_summary(_summary_rows(closed_camps))

    st.markdown('---')

    # ── Open campaign cards ───────────────────────────────────────────────────
    for ticker, i, c in open_camps:
        rpnl = realized_pnl(c, use_lifetime)
        effb = effective_basis(c, use_lifetime)
        is_open         = True
        pnl_color       = COLOURS['green'] if rpnl >= 0 else COLOURS['red']
        basis_reduction = c.blended_basis - effb
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
            '<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px;text-align:center;">'
            '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">SHARES</div>'
            '<div style="font-size:1.0em;font-weight:600;">{shares}</div></div>'
            '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">ENTRY BASIS</div>'
            '<div style="font-size:1.0em;font-weight:600;">${entry_basis:.2f}/sh</div></div>'
            '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">EFF. BASIS</div>'
            '<div style="font-size:1.0em;font-weight:600;">${eff_basis:.2f}/sh</div>'
            '<div style="font-size:0.7em;color:#00cc96;">▼ ${reduction:.2f} saved</div></div>'
            '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">PREMIUMS</div>'
            '<div style="font-size:1.0em;font-weight:600;">${premiums:.2f}</div></div>'
            '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">REALIZED P/L</div>'
            '<div style="font-size:1.1em;font-weight:700;color:{pnl_color};">${pnl:+.2f}</div></div>'
            '</div></div>'
        ).format(
            border=COLOURS['green'] if is_open else '#444',
            ticker=xe(ticker), camp_n=i + 1,
            status=xe('🟢 OPEN' if is_open else '✅ CLOSED'),
            badge_bg='rgba(0,204,150,0.15)' if is_open else 'rgba(100,100,100,0.2)',
            badge_col=COLOURS['green'] if is_open else '#888',
            shares=int(c.total_shares),
            entry_basis=c.blended_basis, eff_basis=effb,
            reduction=basis_reduction if basis_reduction > 0 else 0,
            premiums=c.premiums, pnl=rpnl, pnl_color=pnl_color,
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
                    last   = chain[-1]
                    is_open_chain = 'to open' in str(last['sub_type']).lower()
                    n_rolls       = sum(1 for leg in chain
                                        if PAT_CLOSE in str(leg['sub_type']).lower())
                    chain_label = '%s %s %s Chain %d — %d roll(s) | Net: $%.2f' % (
                        '🟢' if is_open_chain else '✅',
                        '📞' if cp == 'CALL' else '📉',
                        cp.title(), ci + 1, n_rolls, ch_pnl
                    )
                    with st.expander(chain_label, expanded=is_open_chain):
                        chain_rows = []
                        last_open_date = None
                        for leg_i, leg in enumerate(chain):
                            sub = str(leg['sub_type']).lower()
                            if 'to open' in sub:
                                action = '↪️ Sell to Open'
                                last_open_date = leg['date']
                                dit_str = ''
                            elif PAT_CLOSE in sub:
                                action = '↩️ Buy to Close'
                                dit_str = '%dd' % (leg['date'] - last_open_date).days if last_open_date else ''
                                last_open_date = None
                            elif PAT_EXPIR in sub:
                                action = '⏹️ Expired'
                                dit_str = '%dd' % (leg['date'] - last_open_date).days if last_open_date else ''
                                last_open_date = None
                            elif PAT_ASSIGN in sub:
                                action = '📋 Assigned'
                                dit_str = '%dd' % (leg['date'] - last_open_date).days if last_open_date else ''
                                last_open_date = None
                            else:
                                action = leg['sub_type']
                                dit_str = ''
                            dte_str = ''
                            if 'to open' in sub:
                                try:
                                    exp_dt  = pd.to_datetime(leg['exp'], dayfirst=True)
                                    dte_str = '%dd' % max((exp_dt - leg['date']).days, 0)
                                except (ValueError, TypeError):
                                    dte_str = ''
                            is_open_leg = is_open_chain and leg_i == len(chain) - 1
                            chain_rows.append({
                                'Date':   leg['date'].strftime('%d/%m/%y'),
                                'Action': ('🟢 ' + action) if is_open_leg else action,
                                'Strike': '%.1f%s' % (leg['strike'], cp[0]),
                                'Expiry': leg['exp'], 'DTE': dte_str, 'Days Held': dit_str,
                                'Credit/Debit Rcvd': leg['total'], '_open': is_open_leg,
                            })
                        ch_df = pd.DataFrame(chain_rows)
                        ch_df = pd.concat([ch_df, pd.DataFrame([{
                            'Date': '', 'Action': '━━ Chain Total',
                            'Strike': '', 'Expiry': '', 'DTE': '', 'Days Held': '',
                            'Credit/Debit Rcvd': ch_pnl, '_open': False,
                        }])], ignore_index=True)
                        st.dataframe(
                            ch_df[['Date', 'Action', 'Strike', 'Expiry', 'DTE', 'Days Held', 'Credit/Debit Rcvd', '_open']]
                            .style.apply(_style_chain_row, axis=1)
                            .format({'Credit/Debit Rcvd': lambda x: '${:.2f}'.format(x)})
                            .map(lambda v: 'color: #00cc96' if isinstance(v, float) and v > 0
                                else ('color: #ef553b' if isinstance(v, float) and v < 0 else ''),
                                subset=['Credit/Debit Rcvd']),
                            width='stretch', hide_index=True,
                            column_config={'_open': None}
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
                effb = effective_basis(c, use_lifetime)
                is_open         = False
                pnl_color       = COLOURS['green'] if rpnl >= 0 else COLOURS['red']
                basis_reduction = c.blended_basis - effb
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
                    '<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px;text-align:center;">'
                    '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">SHARES</div>'
                    '<div style="font-size:1.0em;font-weight:600;">{shares}</div></div>'
                    '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">ENTRY BASIS</div>'
                    '<div style="font-size:1.0em;font-weight:600;">${entry_basis:.2f}/sh</div></div>'
                    '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">EFF. BASIS</div>'
                    '<div style="font-size:1.0em;font-weight:600;">${eff_basis:.2f}/sh</div>'
                    '<div style="font-size:0.7em;color:#00cc96;">▼ ${reduction:.2f} saved</div></div>'
                    '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">PREMIUMS</div>'
                    '<div style="font-size:1.0em;font-weight:600;">${premiums:.2f}</div></div>'
                    '<div><div style="font-size:0.7em;color:#888;margin-bottom:2px;">REALIZED P/L</div>'
                    '<div style="font-size:1.1em;font-weight:700;color:{pnl_color};">${pnl:+.2f}</div></div>'
                    '</div></div>'
                ).format(
                    border='#444',
                    ticker=xe(ticker), camp_n=i + 1,
                    badge_bg='rgba(100,100,100,0.2)', badge_col='#888',
                    shares=int(c.total_shares),
                    entry_basis=c.blended_basis, eff_basis=effb,
                    reduction=basis_reduction if basis_reduction > 0 else 0,
                    premiums=c.premiums, pnl=rpnl, pnl_color=pnl_color,
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
                            ch_col = COLOURS['green'] if ch_pnl >= 0 else COLOURS['red']
                            for pos in chain:
                                st.markdown(
                                    render_position_card(ticker, pd.DataFrame([pos])),
                                    unsafe_allow_html=True
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


