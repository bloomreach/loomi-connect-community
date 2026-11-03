# Example: price anomaly report

Illustrative output. Every product, price and figure is invented; it matches the script's output on the synthetic test fixtures.

**Prompt:** "Find wrong prices in our catalog."

---

## Price anomalies: example home store, whole catalog, last 30 days

**Headline:** 20 products checked in 1 group: 2 high, 4 medium, 6 low. $1,250 of 30-day revenue sits on products with high findings, all of it on one likely ×100 error.

### Fix first (high)

| Product (ID) | Group | Price | Problem | 30-day revenue | Owner |
|---|---|---|---|---|---|
| Stoneware mug tall (MUG-X100) | Mugs | 1,599.00 | 96.9× the Mugs median of 16.50 (typical 15.00-19.00, n=18); ÷100 gives 15.99, inside the typical range: likely a unit or decimal error | $1,250 | Feed team |
| Latte mug (MUG-ZERO) | Mugs | 0.00 | Price is 0.00; it's on page one for "mug" | — | Feed team |

### Then (medium and low)

- **Sale price above the regular price (feed team):** MUG-SALEUP (sale 19.50, price 16.00); variant MUG-VAR-3 (sale 2,200.00, price 2,100.00).
- **Outlier to confirm (pricing team):** Artisan mug (MUG-OUT) at 75.00 is 4.55× the Mugs median (robust z 8.6); $90 of revenue. If it's right, check it belongs in Mugs.
- **Variant spread (feed team):** Mug set (MUG-VAR) variants run from 20.00 to 2,100.00, about ×100: variant MUG-VAR-3 may have a unit error.
- **Deep discount (pricing team):** Espresso cup (MUG-DEEP) is 90% off (1.80 against 18.00): a missing digit?
- **Duplicates:** MUG-03 is in the feed twice, at 15.00 and 30.00; "Diner Mug" is listed as MUG-DUP-A at 15.00 and MUG-DUP-B at 19.00.
- **Missing price:** Soup mug (MUG-NONE) has no price.

### Catalog notes

- 13 of 18 priced products have a sale price equal to the regular price: the feed fills `sale_price` by default. One fix (leave it empty when there's no discount) keeps "on sale" badges and filters honest.

### Not checked

- Nothing else in this example. On a real catalog, expect a list of groups with fewer than 8 priced products.

### Next steps

1. Feed team: MUG-X100's price unit, MUG-ZERO and MUG-NONE, the two sale prices, and the default sale price (findings CSV attached).
2. Pricing team: confirm MUG-OUT and MUG-DEEP.
3. Page-one view: run `discovery-variant-health` on the top searches for stock, swatches and SKUs.
