# Weblayer QA check catalog

What each check means, its severity and the fix. `scripts/weblayer_checks.py` runs the static checks; the word lists and thresholds are in [rules.json](rules.json). If the script can't run, apply the same rules by hand. Report a finding only when the evidence supports it, and list anything you couldn't check under "couldn't verify".

The rules come from the platform skeleton that `engagement-weblayer-builder` writes to. Weblayers built from older templates (their own `attachBannerToDom()` function, no `utils`) are still valid: check them against the runtime rules only, and note once (nitpick) that they predate the current skeleton.

## Whole weblayer

| Check | Severity |
|---|---|
| No variant enabled | Blocker |
| Enabled variants' percentages don't total 100 | Blocker |
| Schedule (`date_filter`) enabled with an end date in the past | Blocker |
| Schedule enabled with no end date, or no schedule at all | Nitpick (it runs until someone turns it off) |
| No pages included in **Show on** | Warning |
| Shows on every page with no exclusions | Nitpick: confirm checkout and account pages are intended |
| No customer filter | Information only: every visitor is eligible |

The banner details may not include the schedule. Then check it with `search_banners` and `serving_status` (see the skill's step 2), or list it under "couldn't verify". Smart triggering conditions are never returned: always ask the user, or list them under "couldn't verify".

A disabled variant never shows. Report its findings, but they don't change the verdict.

## Skeleton (current `utils` skeleton)

| Check | Severity |
|---|---|
| The JavaScript doesn't end with `return { remove: ... }` (both skeletons) | Blocker |
| `utils` redeclared with `const`, `let` or `var` | Blocker: breaks silently |
| `utils.setConfig()` or `utils.registerStartTrigger()` never called | Blocker: the weblayer never starts |
| No `createBanner()`, or it never calls `utils.attachBannerToDom(banner)` | Blocker: nothing renders |
| `utils.attachBannerToDom(banner)` isn't the last line of `createBanner()` | Warning |
| `placeholder.querySelector('.x')` matches no element in the HTML | Blocker |
| `<html>`, `<head>` or `<body>` tags in the HTML | Blocker |
| `document.querySelector()` or `getElementById()` outside the skeleton's `loadScript()` | Warning: can hit the host page |

Older templates: nothing inserts the weblayer into the page = **blocker**; no `banner` events tracked = **warning**.

## Tracking

| Check | Severity |
|---|---|
| A `banner` event built by hand (`self.sdk.track("banner", { ... })`) | Warning: loses the banner and variant IDs. Use `utils.getEventProperties()` |
| Close button not wired to `utils.handleCloseButtonClick` | Warning: `close` may not be tracked |
| `self.sdk.identify(email)` with a plain value | Warning: sets the `registered` hard ID. Confirm the project uses it, or pass `{email_id: email}` |

## Triggering

When a weblayer appears belongs in **Settings > Smart triggering**, not in code. With both, it shows unpredictably.

| Check | Severity |
|---|---|
| Parameters for old triggering code (`trigger`, `showAfter`, exit-intent and scroll thresholds, `PARAM_trigger`, `PARAM_showAfter`) | Warning |
| `scroll`, `mouseout`, `mouseleave` or `visibilitychange` listeners | Warning to review: often exit-intent or scroll triggering |

Auto-close (`removeAfter`, `AutoHideDelay`) isn't triggering and is fine.

## Unsafe code and leftovers

| Check | Severity |
|---|---|
| `eval()`, `document.write()` or `new Function()` | Blocker |
| A value put in with `innerHTML`, `outerHTML` or `insertAdjacentHTML` (other than the skeleton's `self.html` and `self.style`) | Warning: stored cross-site scripting if the value comes from Jinja, a catalog, the URL or a form |
| A `debugger` statement | Warning |
| `console.log`, `console.debug` or `console.info` | Nitpick (`console.error` in a catch block is fine) |

## External loads, network calls and storage

The skeleton needs only `/brstatic/utils.js` (and, for a phone input, the platform's intl-tel-input files plus its utilities on jsDelivr). Any other script, stylesheet, `@import`, `fetch`, XHR, `sendBeacon` or dynamic `import` is a **warning**: third-party code on the storefront that the weblayer's owner must confirm. List every load, and every `document.cookie`, `localStorage` and `sessionStorage` access, in the report, even the expected ones.

## Template parameters

Syntax: `[[ {name: 'Name', tooltip: '…', category: '…', orderIndex: '1000', isJsonParam: true} : type | default ]]`. Types: `string`, `text`, `number`, `color`, `image`, `boolean`, `enum(A,B)`, `date`, `time`, `datetime`, `metric`, `recommendation`.

| Check | Severity |
|---|---|
| A `[[` with no `]]` | Blocker |
| `{...}` form without `isJsonParam: true` (the panel shows the whole object as the name) | Warning |
| Unknown type | Warning (nitpick for `url`, `html` or `font`, which should be `string` or `enum`) |
| A `number` with a non-numeric default | Warning |
| A `string` or `text` default containing `"` | Warning: ends the JavaScript string or `{% set %}` early |
| One name used with different types | Warning |
| An image URL hard-coded in the HTML or CSS | Warning: every image should be an `image` parameter |
| Hard-coded copy, colours or font family | Nitpick: list a few examples |
| An `image` parameter with no image set | Nitpick |
| Saved values for parameters no longer in the code | Nitpick: harmless leftovers |

## Jinja

| Check | Severity |
|---|---|
| A `{% if %}`, `{% for %}` or other block never closed, or an end tag with no opener, or an unclosed `{{` or `{%` | Blocker |
| `{{ customer.x }}` with no `default(…, true)` | Warning: most weblayer visitors are anonymous, so it prints `None` or nothing |
| `default('x')` without `true` | Warning: doesn't replace `None` or `''` |
| A loop over `aggregates[...]` with no `!= 'None'` guard | Warning: an empty aggregate renders as the string `'None'` |

For more than a quick fix, hand the Jinja to `engagement-jinja-writer`.

## Closing and accessibility

| Check | Severity |
|---|---|
| A full-screen fixed pop-up (`100vh`, `inset: 0`, `height: 100%`) with no close or dismiss control | Blocker: traps visitors |
| Any other fixed weblayer with no close control | Warning |
| An icon-only close button with no `aria-label` or `title` | Warning |
| An `<img>` with no `alt` attribute (`alt=""` is fine for decorative images) | Nitpick |

## Links

The script fills each link's parameters with the variant's current values, then runs the static checks:

| Check | Severity |
|---|---|
| `javascript:` URL | Blocker |
| Empty or `#` | Warning (close buttons excluded) |
| No scheme (`www.shop.com/x`) | Warning: treated as a relative link |
| `http://` | Warning: blocked or flagged on an https site |
| Placeholder host (`example.com` and the others in rules.json) | Warning |
| Placeholder word in the path or query (`test`, `todo`, `lorem` …) | Warning |

Then load every link in `links_to_load`, trying each method in turn, per link. Two rules first:

- **Never send a customer's data to a website.** If a link holds Jinja, render it with dummy values (`test@example.invalid`, "Test"), never a real customer's, and mask personal values wherever you show a URL.
- **Don't trigger actions.** Load subscribe, unsubscribe, confirm, verify and other links carrying a token with `HEAD` only (web-fetch tool), never in a browser; if `HEAD` isn't possible, mark them **not checked**.

1. **A web-fetch tool.** `HEAD`, falling back to `GET`, following redirects.
2. **A browser tool**, if the web-fetch tool is missing or refuses the URL. Open the link in a new tab. Where the tool can run JavaScript, read the real status with `({status: (performance.getEntriesByType('navigation')[0] || {}).responseStatus, url: location.href, type: document.contentType})`; otherwise read the title and text. Never click, sign in, accept cookies, submit anything or solve a CAPTCHA. Wait for any site approval the client asks for; a declined approval means **not checked**.
3. **Not checked**, only when nothing could load it.

Results: 404, 410 or 5xx on the main call-to-action or hero image = **blocker**, elsewhere **warning**. 401, 403, 429, bot challenges ("Just a moment…", "Verify you are human") and timeouts = **not checked**, never broken. An unchecked call-to-action gets its own warning row ("Not checked: click before launch"); group the others in one row. Any unchecked link caps the verdict at **GO WITH CAUTION**.

## Size

| Check | Severity |
|---|---|
| An inline `data:` URI over 50 KB | Warning: it loads on every page the weblayer runs on |
| Code over 150 KB in total | Nitpick |
