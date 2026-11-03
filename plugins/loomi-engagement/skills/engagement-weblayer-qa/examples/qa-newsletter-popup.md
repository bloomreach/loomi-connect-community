# Example: QA a newsletter pop-up before launch

Synthetic example. The weblayer, IDs and URLs are made up.

**Prompt**

> QA the "Spring sign-up pop-up" weblayer before we turn it on. Smart triggering is Active time on page >= 20 seconds.

**Output**

━━━ STEP 1 / FIND THE WEBLAYER ━━━
QA'ing weblayer `Spring sign-up pop-up` (`000000000000000000000003`) in project `Example Retail`. Read-only.

━━━ STEP 2 / STATIC CHECKS ━━━ … ━━━ STEP 4 / LINKS ━━━

🔴 NO-GO — Spring sign-up pop-up · 1 blocker · 4 warnings · 2 nitpicks · 2 variants · 0 links not checked

| # | Severity | Variant | Area | Issue | Fix |
|---|---|---|---|---|---|
| 1 | 🔴 Blocker | Variant B | Unsafe code | The discount code from the page URL is put in with `innerHTML` | Set it with `textContent` |
| 2 | 🟡 Warning | Both | Triggering | `showAfter` parameter (3000 ms) on top of Smart triggering | Remove it; Smart triggering already waits 20 s |
| 3 | 🟡 Warning | Both | Jinja | `{{ customer.first_name }}` has no fallback: anonymous visitors see "Hi None" | `{{ customer.first_name \| default('there', true) }}` |
| 4 | 🟡 Warning | Variant B | Links | Privacy link is `#` | Link the real privacy policy page |
| 5 | 🟡 Warning | Variant B | Accessibility | Close icon has no `aria-label` | Add `aria-label="Close"` |
| 6 | ⚪ Nitpick | Both | Parameters | 3 colours hard-coded (`#1A1A1A`, `#F5F5F5`, `#E91E8C`) | Make them color parameters |
| 7 | ⚪ Nitpick | Variant A | Leftovers | 2 `console.log` calls | Remove them |

```
[BLOCKER] Variant B · JavaScript
Checked:  how values reach the page
Found:    banner.querySelector(".code").innerHTML = new URLSearchParams(location.search).get("code")
Fix:      banner.querySelector(".code").textContent = new URLSearchParams(location.search).get("code") || ""
```

```
[WARNING] Both variants · parameters
Checked:  triggering code
Found:    showAfter parameter (3000 ms) and PARAM_showAfter in the config
Fix:      remove both; Smart triggering (Active time on page >= 20 s) already decides when it shows.
          Removing the parameter drops its saved value.
```

**External loads and storage:** `/brstatic/utils.js` (the skeleton, expected). No other scripts, stylesheets or network calls. `localStorage`: none.

**Link check results**

| Link | Method | Result |
|---|---|---|
| https://www.shop.invalid/spring (call-to-action) | web fetch | 200 |
| https://cdn.shop.invalid/spring-hero.jpg (hero image) | web fetch | 200, image/jpeg |

**Passed:** skeleton (both variants on the current `utils` skeleton, render and start calls in place, `return { remove: removeBanner }` last), tracking through `utils.getEventProperties()`, traffic split 50/50, page targeting (collections pages), schedule (ends 2026-11-30), no external loads, every image a parameter with alt text.

**Couldn't verify:** nothing. Smart triggering was given: Active time on page >= 20 s is fine on its own (Web SDK v3.57.0 or later needed).

**How to test it:** preview each variant in the weblayer editor, then activate it for a test audience only and check the browser console shows no errors and tracks `banner` events (`show`, `click`, `close`).
