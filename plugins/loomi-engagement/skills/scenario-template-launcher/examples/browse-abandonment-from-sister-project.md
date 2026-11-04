# Example: fill a browse abandonment gap from a sister project

Illustrative. Project names, scenario names, IDs and counts are made up.

## Prompt

> lifecycle-coverage-map says we have no browse abandonment flow in "Example Store UK". The EU team has one that works. Copy it over.

## Before the clone

```
## New flow: Browse abandonment (clone 2026-11-05) (draft) in Example Store UK

**From:** 'Browse abandonment' in Example Store EU (active, 6 steps)
**Dependencies:** 2 created (the scenario, recommendation engine "Similar items"), 2 reused from the target (aggregate "Last viewed products", expression "Hour of day"), 0 copied

### Fix before launch
| Priority | What | Used in | Fix |
|---|---|---|---|
| high | consent category `newsletter` | Not bought, newsletter consent; Still looking? | Pick the UK project's marketing email category on both steps |
| high | engine "Similar items" uses catalog `products_eu` | recommendation engine | Point the engine at the UK `products` catalog |
| high | webhook integration | Notify CRM | Pick the UK project's authentication integration on the step |
| medium | event `purchase` | Not bought, newsletter consent | The UK project tracks no `purchase` event yet; track it, or change the condition |
| medium | project variable `brand_name` | Still looking? | Add it in the UK project's settings |

Source: 'Browse abandonment' (active, 6 steps) in Example Store EU, organisation Example Retail Group
Target: Example Store UK, organisation Example Retail Group
Will create ONE scenario, as a draft that doesn't run:
  Name:     Browse abandonment (clone 2026-11-05)
  Steps:    6 (starts when a customer views a product; email, SMS and a webhook)
  Creates in the target: recommendation engine "Similar items"
  Reuses the target's:   aggregate "Last viewed products", expression "Hour of day"
  Copies as new items:   none
  Webhooks: 1 step; cloning copies its headers and body, which can hold API tokens, into the target
  Won't resolve in the target: 5 (3 high priority); fix them in the draft before anyone switches it on
  Warnings: the UK aggregate "Last viewed products" differs from the EU one, and the clone uses the UK version
Clone it? (yes / no)
```

## After "yes"

```
**Cloned:** scenario 0123456789abcdef01234567 (verified: in_place). It's a draft: nothing runs until someone switches it on in Engagement.
**Webhooks:** 1 step cloned with its headers and body; check the credentials belong in this project.
**Next:** run scenario-qa on the draft; make the consent and event changes with engagement-scenario-builder.
```

## When nothing fits

> Start a browse abandonment flow. We don't have one anywhere.

No project the user can access has a scenario that does the job, so the skill lists the predefined templates tagged "Abandoned Browse" (two emails and three SMS messages, by name), hands the outline (trigger on product view, a 2-hour wait, a purchase check, one email) to `engagement-scenario-builder`, and says to pick the messages in the Asset Manager under "Predefined templates".
