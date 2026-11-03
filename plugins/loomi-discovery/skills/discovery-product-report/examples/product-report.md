# Example: one-product report

Illustrative output for a made-up product in a made-up account. Every name, ID and number is invented.

**Prompt:** "How is the Northwind rain jacket (p100) doing?"

## Northwind Rain jacket (p100): 30-day report

**In short:** it gets typical traffic but converts at less than half the rate of similar jackets, and it's boosted to #2 for "jacket" while stock is low.

| Metric | This product | Category peers (median) | Before |
|---|---|---|---|
| Visits | 1,000 | 975 | 900 |
| Add-to-cart rate | 10.0% | 30.5% | 29.0% |
| Conversion rate | 2.0% | 5.3% | 3.0% |
| Revenue per visit | $1.50 | $3.25 | $2.90 |
| Revenue | $1,500 | $2,850 | $2,100 |

**Where it ranks:** "jacket" #2 · "rain jacket" off page one (#30) · Women > Jackets #4
**Rules:** 501: boosted on "jacket" (top products) · 502: buried on "coat" for the Mobile audience, in an A/B test
**Stock:** available, stock level low · 2 of 3 variants in stock · Missing fields: description

**Next actions**
1. [high] It's low on stock but boosted on "jacket", so shoppers may be sent to a product that sells out → `discovery-change-qa`: remove it from rule 501 or swap in an in-stock jacket, and check the change before switching it on.
2. [medium] Off page one for "rain jacket" (#30) → `discovery-product-visibility`: explain its position for "rain jacket" and get the smallest fix.
3. [medium] Add-to-cart and conversion rates below its peers: shoppers see it but don't buy → `product-data-enhancer`: improve its title, description, images and attributes.

**Couldn't check:** queries outside the top three checked; personalised ranking.
