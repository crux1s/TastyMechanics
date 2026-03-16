"""
tabs/landing.py — Landing page renderer (shown before a CSV is uploaded).
"""

import streamlit as st
from config import COLOURS


def render_landing(app_version: str) -> None:
    _ht = COLOURS["header_text"]; _tm = COLOURS["text_muted"]
    _td = COLOURS["text_dim"];    _bl = COLOURS["blue"]
    _cb = COLOURS["card_bg"];     _cb2 = COLOURS["card_bg2"]
    _or = COLOURS["orange"] + "55"; _gr = COLOURS["green"]
    _bd = COLOURS["border"]
    st.markdown(f"""
    <div style="max-width:860px;margin:2rem auto 0 auto;">

    <!-- Hero tagline -->
    <p style="color:{_tm};font-size:1.05rem;line-height:1.8;margin-bottom:0.25rem;">
    Built for <b style="color:{_ht};">wheel traders and theta harvesters</b> — short puts,
    covered calls, strangles, iron condors, and the full wheel cycle. Upload your
    TastyTrade CSV and get a complete picture of your realized P/L, premium selling
    performance, wheel campaigns, and portfolio health.
    </p>
    <p style="margin:0 0 2rem 0;">
    <span style="display:inline-flex;align-items:center;gap:0.4rem;background:{_cb};border:1px solid {_bd};border-radius:20px;padding:4px 12px;font-size:0.8rem;color:{_gr};">
    🔒 Your transaction data is processed locally and never sent anywhere. If you enable Live Prices, ticker symbols are sent to Yahoo Finance's public API.
    </span>
    </p>

    <!-- Upload CTA -->
    <div style="background:linear-gradient(135deg,{_cb},{_cb2});border:1px solid {_bl}33;border-radius:10px;padding:1rem 1.4rem;margin-bottom:2rem;display:flex;align-items:center;gap:1rem;">
    <span style="font-size:2rem;">⬆️</span>
    <div>
        <div style="color:{_ht};font-weight:600;font-size:0.95rem;">Ready to start?</div>
        <div style="color:{_tm};font-size:0.85rem;">Use the <b style="color:{_bl};">⚙️ Data Control</b> panel in the sidebar to upload your TastyTrade history CSV.</div>
    </div>
    </div>

    <!-- Feature cards grid -->
    <h3 style="color:{_ht};margin:0 0 1rem 0;">What you get</h3>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin-bottom:2rem;">

    <div style="background:linear-gradient(135deg,{_cb},{_cb2});border:1px solid {_bd};border-radius:10px;padding:1rem 1.2rem;">
        <div style="font-size:1.4rem;margin-bottom:0.4rem;">📡</div>
        <div style="color:{_ht};font-weight:600;font-size:0.9rem;margin-bottom:0.3rem;">Open Positions</div>
        <div style="color:{_tm};font-size:0.82rem;line-height:1.6;">Open options and equity positions with DTE countdown, strategy label, and expiry alerts. Toggle live market prices to see last price, day change, and unrealised P/L per leg.</div>
    </div>

    <div style="background:linear-gradient(135deg,{_cb},{_cb2});border:1px solid {_bd};border-radius:10px;padding:1rem 1.2rem;">
        <div style="font-size:1.4rem;margin-bottom:0.4rem;">🎯</div>
        <div style="color:{_ht};font-weight:600;font-size:0.9rem;margin-bottom:0.3rem;">Premium Selling Performance</div>
        <div style="color:{_tm};font-size:0.82rem;line-height:1.6;">Win rate, capture %, annualised return, and profit factor broken down by ticker and strategy.</div>
    </div>

    <div style="background:linear-gradient(135deg,{_cb},{_cb2});border:1px solid {_bd};border-radius:10px;padding:1rem 1.2rem;">
        <div style="font-size:1.4rem;margin-bottom:0.4rem;">🔬</div>
        <div style="color:{_ht};font-weight:600;font-size:0.9rem;margin-bottom:0.3rem;">Discipline &amp; Patterns</div>
        <div style="color:{_tm};font-size:0.82rem;line-height:1.6;">Cumulative equity curve, DTE discipline charts, win/loss distribution, rolling capture %, and a ticker &times; month heatmap. Full closed trade log with best/worst highlights.</div>
    </div>

    <div style="background:linear-gradient(135deg,{_cb},{_cb2});border:1px solid {_bd};border-radius:10px;padding:1rem 1.2rem;">
        <div style="font-size:1.4rem;margin-bottom:0.4rem;">🎡</div>
        <div style="color:{_ht};font-weight:600;font-size:0.9rem;margin-bottom:0.3rem;">Wheel Campaigns</div>
        <div style="color:{_tm};font-size:0.82rem;line-height:1.6;">Per-ticker cards with entry basis, effective basis, premiums banked, and P/L. "Days to Free" projects when your cost basis reaches $0 at the current collection rate.</div>
    </div>

    <div style="background:linear-gradient(135deg,{_cb},{_cb2});border:1px solid {_bd};border-radius:10px;padding:1rem 1.2rem;">
        <div style="font-size:1.4rem;margin-bottom:0.4rem;">💼</div>
        <div style="color:{_ht};font-weight:600;font-size:0.9rem;margin-bottom:0.3rem;">Portfolio Realized P/L</div>
        <div style="color:{_tm};font-size:0.82rem;line-height:1.6;">Stacked cash-flow charts by week and month — Options, Equity, and Income breakdown. Equity curve, drawdown, Sharpe, and capital efficiency.</div>
    </div>

    <div style="background:linear-gradient(135deg,{_cb},{_cb2});border:1px solid {_bd};border-radius:10px;padding:1rem 1.2rem;">
        <div style="font-size:1.4rem;margin-bottom:0.4rem;">💵</div>
        <div style="color:{_ht};font-weight:600;font-size:0.9rem;margin-bottom:0.3rem;">Deposits, Dividends &amp; Fees</div>
        <div style="color:{_tm};font-size:0.82rem;line-height:1.6;">Complete cash flow ledger with deposited capital, dividend income, and fee summary.</div>
    </div>

    </div>

    <!-- Export instructions -->
    <h3 style="color:{_ht};margin:0 0 0.75rem 0;">How to export from TastyTrade</h3>
    <div style="background:linear-gradient(135deg,{_cb},{_cb2});border:1px solid {_bd};border-radius:10px;padding:1rem 1.4rem;margin-bottom:2rem;">
    <div style="display:flex;align-items:flex-start;gap:1rem;margin-bottom:0.85rem;">
        <div style="display:flex;flex-direction:column;gap:0.6rem;flex:1;">
        <div style="display:flex;align-items:center;gap:0.75rem;">
            <span style="background:{_bl}22;color:{_bl};font-weight:700;font-size:0.75rem;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">1</span>
            <span style="color:{_tm};font-size:0.88rem;">In TastyTrade, go to <b style="color:{_ht};">History → Transactions</b></span>
        </div>
        <div style="display:flex;align-items:center;gap:0.75rem;">
            <span style="background:{_bl}22;color:{_bl};font-weight:700;font-size:0.75rem;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">2</span>
            <span style="color:{_tm};font-size:0.88rem;">Set the date range to cover your <b style="color:{_ht};">full account history</b></span>
        </div>
        <div style="display:flex;align-items:center;gap:0.75rem;">
            <span style="background:{_bl}22;color:{_bl};font-weight:700;font-size:0.75rem;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">3</span>
            <span style="color:{_tm};font-size:0.88rem;">Click <b style="color:{_ht};">Download CSV</b> and upload the file here</span>
        </div>
        </div>
    </div>
    <div style="background:{_or};border-radius:6px;padding:0.6rem 0.9rem;font-size:0.82rem;color:{_tm};line-height:1.6;">
        ⚠️ Always export your <b style="color:{_ht};">full account history</b>, not just a recent window.
        FIFO cost basis requires all prior buy transactions. A partial export produces incorrect
        basis and P/L for positions with earlier lots outside the date range.
    </div>
    </div>

    <!-- Disclaimer -->
    <h3 style="color:{_ht};margin:0 0 0.75rem 0;">⚠️ Disclaimer &amp; Known Limitations</h3>
    <div style="background:{_cb};border:1px solid {_or};border-radius:8px;padding:1.2rem 1.4rem;font-size:0.88rem;color:{_tm};line-height:1.75;">

    <p style="margin:0 0 0.75rem 0;color:{_ht};font-weight:600;">
    This tool is for personal record-keeping only. It is not financial advice.
    </p>

    <p style="margin:0 0 0.5rem 0;color:{_tm};">
    P/L figures are cash-flow based (what actually hit your account) and use FIFO cost
    basis for equity. They do not account for unrealised gains/losses, wash sale rules,
    or tax adjustments. Always reconcile against your official TastyTrade statements.
    </p>

    <b style="color:{_ht};">Verify these scenarios manually:</b>
    <ul style="margin:0.5rem 0 0.75rem 0;padding-left:1.2rem;">
    <li><b style="color:{_ht};">Covered calls assigned away</b> — if your shares are called away, verify the campaign closes and P/L is recorded correctly.</li>
    <li><b style="color:{_ht};">Multiple assignments on the same ticker</b> — each new buy-in starts a new campaign. Blended basis across campaigns is not combined.</li>
    <li><b style="color:{_ht};">Long options exercised by you</b> — exercising a long call or put into shares is untested. Check the resulting position and cost basis.</li>
    <li><b style="color:{_ht};">Futures options delivery</b> — cash-settled futures (/MES, /ZS etc.) are included in P/L totals, but in-the-money expiry into a futures contract is not handled.</li>
    <li><b style="color:{_ht};">Stock splits</b> — forward and reverse splits are detected and adjusted, but post-split option symbols are not automatically stitched to pre-split contracts.</li>
    <li><b style="color:{_ht};">Spin-offs and zero-cost deliveries</b> — shares received at $0 cost trigger a warning. Use the sidebar toggle to exclude those tickers if the inflated basis distorts your numbers.</li>
    <li><b style="color:{_ht};">Mergers and acquisitions</b> — if a ticker is acquired or merged, the campaign may be orphaned with no exit recorded. Reconcile manually.</li>
    <li><b style="color:{_ht};">Complex multi-leg structures</b> — PMCC, diagonals, calendars, and ratio spreads may not be labelled correctly. P/L totals are correct; trade type labels may not be.</li>
    <li><b style="color:{_ht};">Rolled calendars</b> — front-month expiry rolls may appear as separate closed trades rather than one continuous position. Needs real data to verify.</li>
    <li><b style="color:{_ht};">Reverse Jade Lizard</b> — detected as a Jade Lizard but capital risk may be understated (max loss is on the call side). Verify if you trade this structure.</li>
    <li><b style="color:{_ht};">0DTE trades</b> — P/L is correct, but Ann Return %, Med Premium/Day, and Wheel Campaigns are less meaningful for same-day holds.</li>
    <li><b style="color:{_ht};">Non-US accounts</b> — built and tested on a US TastyTrade account. Currency, tax treatment, and CSV format differences for other regions are unknown.</li>
    </ul>
    </div>

    <p style="color:{_td};font-size:0.78rem;margin-top:1.5rem;text-align:center;">
    TastyMechanics {app_version} · Open source · AGPL-3.0 ·
    <a href="https://github.com/crux1s/TastyMechanics" style="color:{_bl};">GitHub</a> ·
    <a href="https://tastytrade.com/welcome/?referralCode=NT57Z3P85B" style="color:{_bl};">Open a TastyTrade account</a>
    </p>
    <p style="text-align:center;margin-top:0.75rem;">
    <span style="font-size:0.82rem;color:{_td};font-style:italic;">Like the app? No pressure, but...</span><br><br>
    <a href="https://www.buymeacoffee.com/Cruxis" target="_blank" style="display:inline-block;padding:6px 16px;background:#40DCA5;color:#000000;font-weight:700;font-size:0.85rem;border-radius:8px;text-decoration:none;font-family:Cookie,cursive;letter-spacing:0.3px;">😅 Cover my margin call</a>
    </p>

    </div>
    """, unsafe_allow_html=True)
