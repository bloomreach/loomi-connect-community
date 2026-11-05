# Example: prices drifting between the site and emails

Illustrative only: the account, project, catalog and item IDs and all numbers are made up.

**Session 1 (5 November).** "Our emails show prices that don't match the site. Find what's out of sync and fix it."

The parity check samples 40 random Discovery products, 30 top sellers and 50 Engagement items. The price check finds a cents-for-dollars error, and the variant check finds out-of-stock products on page one. Each failing check becomes one finding:

```
- F1 (open, high): check price_mismatch engagement fix; 6 of 40 random (15.0%, 7.1-29.1%). Next: engagement-catalog-fixer
- F2 (open, high): check stock_out_on_site_in_engagement engagement fix; 3 of 40 random (7.5%, 2.6-19.9%). Next: engagement-catalog-fixer
- F3 (open, high): check unit_error feed team; 4 products, 2 on page one of top searches
- F4 (open, medium): check out_of_stock feed team; 5 page-one products out of stock in every size
```

The user fixes F1 and F2. `engagement-catalog-fixer` reads 9 items, plans 9 updates in one batch, writes them after the yes and verifies each:

```
- C1: update item P200 on 2026-11-05 (in place, live)
- ...
- C9: update item P871 on 2026-11-05 (in place, live)

**Next:** recheck with catalog-parity-check, not before 2026-11-12.
```

The feed and pricing list (F3, F4, with `price-findings.csv`) goes to the feed team the same day.

**Session 2 (13 November).** The parity check runs again: the price mismatches are back on 4 of the 6 items, after the nightly import. Outcome **overwritten**: the Engagement import doesn't carry the sale price field, so the fix is in the import, not the catalog. The stock fixes held.
