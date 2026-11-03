# Example: variant health report

Illustrative output. Every product, price and figure is invented; it matches the script's output on the synthetic test fixtures.

**Prompt:** "Are any of our top products out of stock or broken on page one?"

---

**27 products checked** (25 on page one of "rain jacket" and one category, plus the top sellers): 4 high, 7 medium, 3 low. $5,900 of 30-day revenue sits on products with high findings.

**Fix first**

| Product | Check | Where | 30-day revenue | Issue | Who fixes it |
|---|---|---|---|---|---|
| P1 Storm rain jacket | out of stock | "rain jacket" #1 ($12,000/30 days) | $5,000 | Out of stock on every variant, but ranked first | Bury it (check with `discovery-change-qa`), or fix the stock feed (`data-feed-health`) |
| P3 Trail rain jacket | zero price | "rain jacket" #3 | $900 | Variant SHARED-1 has a price of 0 | Feed team |
| P2 Packable rain shell | zero price | "rain jacket" #2 | — | The product price is 0 | Feed team |

**Then**

- **Prices (feed team):** P3's sale price 95 is above its price 90, and its variant P3_1's sale price 120 is above 110. P3's grid price 90 is outside its variants' prices (100-120).
- **SKUs (feed team):** SKU SHARED-1 belongs to both P3 and P6. P4 has the SKU P4_3 twice.
- **Images (`product-data-enhancer`):** P3's thumbnail uses `http://`; 1 of its 3 variants has no swatch. 1 of P4's variants has no thumbnail.
- **Colours (low):** P4's green has a single variant while red and blue have a size range.
- **Top seller out of stock (medium):** P8 Out of stock tee isn't on a page we checked, but sold $700 and is out of stock.

**Not checked**

- P4: 6 of 7 variants fetched.
- Stock wasn't checked for 21 products with no catalog record (the filler products on page one).
