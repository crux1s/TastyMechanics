# Getting Started

## Try it online

No installation required — upload your CSV and explore instantly:

**https://tastymechanics-76dxruw38qjhqc2bdxgfrc.streamlit.app/**

---

## Run locally

### Requirements

```
python >= 3.10
streamlit >= 1.30
pandas >= 2.0
plotly >= 5.0
yfinance >= 0.2   # optional — only required for live market prices
```

### Install

```bash
pip install -r requirements.txt
```

### Run

```bash
python3 -m streamlit run tastymechanics.py
```

Then open `http://localhost:8501` in your browser.

> **Note:** Use `python3 -m streamlit run` rather than calling `streamlit` directly — the binary may not be on your PATH depending on your environment.

---

## Getting your CSV from TastyTrade

1. Log in to TastyTrade
2. Go to **History → Transactions**
3. Set your date range — **export your full account history, not just a recent window**
4. Click **Download CSV**
5. Upload the file using the sidebar in the dashboard

> **Why full history matters:** FIFO cost basis for equity P&L requires all prior buy transactions to be present, even if the shares were purchased years ago. A partial export will produce incorrect basis and P&L figures for any position that has earlier lots outside the date range.

---

## What the CSV must contain

TastyMechanics expects the standard TastyTrade transaction history export. The following columns are required:

| Column | Used for |
|---|---|
| Date | All date filtering and windowed P&L |
| Type | Distinguishing trades from money movements |
| Sub Type | Strategy classification, income detection |
| Symbol | Option symbol parsing (strike, expiry, type) |
| Instrument Type | Separating equity from options from futures |
| Quantity | Position sizing, FIFO lot matching |
| Total | Cash flow — the actual dollar amount after fees |
| Commissions | Displayed in fee metrics |
| Fees | Displayed in fee metrics |

The file must be named `tastytrade_*.csv` or `tastymechanics_*.csv` for the local test suite to find it automatically. The Streamlit app accepts any filename via the file uploader.

---

## First upload checklist

- [ ] Full account history exported (not just recent months)
- [ ] CSV downloaded directly from TastyTrade — do not open and re-save in Excel (can corrupt date formats)
- [ ] Upload via sidebar file uploader
- [ ] Check the **Portfolio Overview** date range shown — confirm it matches your account age
- [ ] If you see a ⚠️ Basis Warning, read the [Known Limitations](Known-Limitations) page
