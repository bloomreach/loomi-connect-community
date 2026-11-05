# Example: a client leaving Klaviyo

Illustrative only: the project, scenario IDs and all numbers are made up.

**Session 1 (5 November).** "We're moving this client off Klaviyo. Here are their email exports: migrate them and rebuild the flows."

`convert-klaviyo-email-to-bloomreach` analyses six exports (three campaign emails, three abandoned-cart flow emails), audits the project, confirms the mapping table once, then shows its write plan: 23 images and six draft scenarios. After its yes it rehosts the images, builds and render-checks each email, and pushes them one at a time:

```
- C1: create scenario 6a5e00000000000000000001 on 2026-11-05 (in place)
- C2: create media files for scenario 6a5e00000000000000000001 on 2026-11-05 (in place)
...
- C12: create media files for scenario 6a5e00000000000000000006 on 2026-11-05 (in place)
```

Its report: **migrated with gaps**. The cart emails read the trigger event because the project has no cart aggregate, and one campaign uses a static code.

`engagement-jinja-writer` writes the cart loop against an aggregate (the user creates "last cart_update.product_list" in Engagement) and a voucher-pool line for the code. The user pastes both into the Visual Builder and saves.

`scenario-qa` on each draft: five GO, one NO-GO (a footer link to the old Klaviyo preference page). The user fixes it in the Visual Builder; QA again: GO. **all_go**.

**Session 2 (6 November).** `lifecycle-coverage-map` against the user's list of Klaviyo flows (welcome, abandoned cart, browse abandonment, post-purchase):

```
- F1 (chosen, high): flow cart_abandonment migrated email only; three single-email drafts. Next: scenario-template-launcher
- F2 (open, high): flow browse_abandonment missing; about 7,500 browsers a month. Next: scenario-template-launcher
- F3 (open, medium): flow welcome missing; ... Next: scenario-template-launcher
```

`scenario-template-launcher` finds the three migrated cart drafts and offers to build on them: **existing flow**. `engagement-scenario-builder` creates one draft flow: the cart trigger, then the three emails copied from the migrated drafts with 4-hour, 24-hour and 72-hour waits and a did-not-purchase condition before each (C13, create). `scenario-qa`: GO. The user switches it on and turns off the Klaviyo flow the same day:

```
- C14: start scenario 6a5e00000000000000000007 on 2026-11-06 (in place, live)
```

The run is finished. F2 is next, as a `playbook-lifecycle-gap` run.
