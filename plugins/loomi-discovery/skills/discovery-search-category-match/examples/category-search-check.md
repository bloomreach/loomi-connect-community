# Example: search and category match

Illustrative output for a made-up apparel store. All names and numbers are invented.

**Prompt:** "Do searches for our category names land on the right products?"

---

**12 category searches checked (last 30 days): 1 to redirect, 1 to align, 2 ambiguous, 8 fine.**

### Act on these

| Query | Category | Overlap | Conversion (search → category) | Main flag | Recommendation |
|---|---|---|---|---|---|
| skirt (8,000 sessions) | /women/skirts | 17% | 12.0% → 18.0% | Search shows another brand at 3× the price | Exact-match redirect "skirt" → /women/skirts |
| jackets (2,500) | /outerwear/jackets | 17% | 10.0% → 16.0% | Similar result counts (35 vs 30), different order | Ranking rule on "jackets": boost category_id = 40100 |

Search for "skirt" finds 120 products, four times the category's 30, and only 4 of the category's first 24 appear on the search page. The curated page converts 50% better.

### Ambiguous

| Query | Sessions | Categories |
|---|---|---|
| pants | 7,000 | /men/pants, /women/pants |
| tops | 6,000 | /men/tops, /women/tops, /kids/tops |

A redirect would send some shoppers to the wrong department. Leave these to search, or consider a department choice on the results page.

### Fine as they are

- **dress → /women/dresses:** aligned (83% overlap).
- **tops (men) → /men/tops:** leave; search is broader and converts better (22% vs 15%).
- **summer sale:** already redirects; see `discovery-redirect-audit`.

### Not checked

- Stock: the catalog has no stock field in the grid.

### Next steps

Check the "skirt" redirect and the "jackets" rule with `discovery-change-qa` before switching either on. Discovery changes are live immediately.
