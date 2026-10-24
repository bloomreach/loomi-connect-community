# Example: QA of an abandoned-cart scenario

Illustrative output. The project, scenario, node IDs, links and profiles are invented.

**Prompt:** "QA the Abandoned Cart scenario before we launch it."

---

🔴 NO-GO — Abandoned Cart · 2 blockers · 3 warnings · 2 nitpicks · Channels: Email, SMS

## Triage

| # | Severity | Channel | Step | Issue | Fix |
|---|---|---|---|---|---|
| 1 | 🔴 Blocker | SMS | node 9 "Cart SMS reminder" | No opt-out language | Append "Reply STOP to opt out" |
| 2 | 🔴 Blocker | Email | node 6 "Cart email 1" | Subject renders as "Hi , you left something behind" for Profile B | Add `\| default('there')` to the first-name variable |
| 3 | 🟡 Warning | Email | node 6 "Cart email 1" | Preheader empty | Add a 40–90 character preheader |
| 4 | 🟡 Warning | Email | node 12 "Cart email 2" | Secondary "Size guide" link returns 404 | Update the link to the live size guide |
| 5 | 🟡 Warning | Flow | — | No purchase check before the second email | Add a "Purchased since cart update?" condition after the 24-hour wait |
| 6 | 🟢 Nitpick | Email | node 6 "Cart email 1" | No view-in-browser link | Add one to the header |
| 7 | 🟢 Nitpick | Email | node 12 "Cart email 2" | Rendered HTML is 94 KB | Trim unused modules to stay well under Gmail's 102 KB clip |

## Issue detail

```
[BLOCKER] SMS · node 9 "Cart SMS reminder"
Checked:  marketing SMS opt-out language
Found:    no STOP or opt-out text anywhere in the rendered body
Where:    message body
Fix:      paste-ready corrected body:
          {{ brand_name }}: Your cart is waiting! Finish checking out: {{ cart_url }} Reply STOP to opt out.
```

```
[BLOCKER] Email · node 6 "Cart email 1"
Checked:  subject line render against sample profiles
Found:    Profile B (sparse) has no first_name; subject renders "Hi , you left something behind"
Where:    subject
Fix:      Hi {{ customer.first_name | default('there') }}, you left something behind
```

## Flow-level issues

- After the 24-hour wait, customers who have already bought still go on to "Cart email 2". Add a purchase check before it.

## Passed checks

- Unsubscribe link and postal address present in both emails.
- Consent categories set on every send.
- All 23 unique links resolved except the one listed above.
- Every referenced event and property exists in the project schema.
- A/B split percentages total 100.

## Couldn't verify

- `https://www.example-store.com/account` returned 403 (bot protection). Check it manually.
