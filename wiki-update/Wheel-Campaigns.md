# Wheel Campaigns

A wheel campaign is a continuous period of share ownership for a single ticker, during which options are sold against the position. TastyMechanics automatically detects and tracks these campaigns from your CSV.

---

## How campaigns are detected

A campaign starts when you buy **100 or more shares** of a ticker (controlled by `WHEEL_MIN_SHARES = 100` in `config.py`). It ends when your share count reaches zero via a sale or assignment.

If you exit and re-enter the same ticker, each ownership period becomes a separate campaign. Multiple campaigns per ticker are supported.

---

## Effective basis

Effective basis is your true cost per share after accounting for all premiums collected:

```
Effective Basis = (Total Share Cost − Campaign Premiums − Dividends) ÷ Shares Held
```

A lower effective basis than your purchase price means your option selling has already reduced your break-even point.

---

## Realized P&L (open campaigns)

For open campaigns (shares still held):

```
Realized P&L = Campaign Premiums + Dividends
```

Share unrealised gain/loss is not included — only cash actually banked.

For closed campaigns (shares sold):

```
Realized P&L = Premiums + Dividends + Share Exit Proceeds − Share Cost
```

---

## Pre-campaign options

Options sold **before** your first share purchase on a ticker are classified as standalone P&L, not campaign premiums. This prevents pre-purchase speculation from inflating your effective basis calculation.

Example: if you sold a put on SMR in October, got assigned in January, and then sold covered calls — only the post-assignment covered calls count as campaign premiums. The October put P&L is standalone.

---

## House Money mode

The **Lifetime "House Money"** toggle is available in the sidebar and affects all tabs. It changes how multiple campaigns on the same ticker are combined.

| Mode | Behaviour |
|---|---|
| OFF (default) | Each campaign is independent. Basis resets to zero on re-entry. |
| ON | All campaigns for a ticker are combined. Premiums from previous campaigns reduce the basis of the current one. |

---

## Campaign summary table

The Wheel Campaigns tab shows a summary table for all open campaigns with these columns:

| Column | Description |
|---|---|
| Status | Open or Closed |
| Qty | Shares currently held |
| Avg Price | Average cost per share |
| Cost Basis | Total share cost |
| Premiums | Campaign option premiums collected |
| Divs | Dividends received |
| Exit | Exit proceeds (closed campaigns) |
| P/L | Realized P&L to date |
| Days | Days campaign has been active |
| Entry | Campaign start date |
| Free In | Projected days until effective basis reaches $0 at current income rate — shows ✅ Free when already at zero, ~Xd as an estimate, or — if no income rate is available |

---

## Campaign cards

Each open campaign gets a detailed card showing:

- Shares held, average price, effective basis
- Basis reduction amount and daily pace
- Realized P&L, days active, annualized return

Cards may show coloured banners for notable conditions:

- **Amber banner** — entry was via put assignment. The put credit is excluded from the cost basis (it was collected before the shares were delivered), so the effective basis is higher than the raw assignment price.
- **Blue banner** — shares were added mid-campaign via put assignment. The premium is already included in the cost basis for that lot.
- **Amber banner** — closing debits from pre-purchase options landed inside the campaign window. These are attributed to pre-campaign P&L, not campaign premiums.

---

## Option roll chains

Within each campaign card, calls and puts are tracked as separate chains. A new chain starts when there is a gap of more than `ROLL_CHAIN_GAP_DAYS` (default: 3) days between the close of one position and the open of the next on the same option type.

This lets you visualise your roll history — how many times you rolled a put down, or extended a covered call out in time.

---

## Waterfall chart

Each campaign card includes a waterfall chart showing how the opening share cost flows through premiums, dividends, and exit proceeds to arrive at the final P&L.
