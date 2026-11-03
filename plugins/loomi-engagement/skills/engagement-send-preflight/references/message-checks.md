# Message check catalog

The checks for one email, SMS/MMS or mobile push message, whether it's a standalone campaign or a scenario step. campaign-qa, scenario-qa and engagement-send-preflight share this file, `scripts/message_checks.py` and `references/rules.json`; keep the three copies identical.

Checks marked **(script)** are done by `message_checks.py`, with thresholds from `references/rules.json`. Use its findings as they are, then do the rest by hand: load the links, render the Jinja against sample profiles, and judge what the script only flags. Where the script can't run, do every check by hand. Report a finding only when the evidence supports it, and list anything you couldn't check under "couldn't verify".

## Links (all channels)

- Extract every href and URL: email modules and rendered HTML, image sources, SMS body, push deep links and web fallbacks. Note which are **primary**: the main call-to-action button, the hero image and its link, and the push primary action. The script lists them in `links_to_load`, primary first (a guess: buttons, the linked hero image and the first SMS link). Skip `{{ email.unsubscribe }}` and other Bloomreach system links, which only exist at send time.
- Render Jinja in URLs against a sample profile before checking them (`links_needing_render`). If a URL can't be rendered, report the template; don't guess.
- **Never send a customer's data to a website.** Before loading a rendered URL, replace any personal value in it (email, name, phone, customer ID, address) with a dummy such as `test@example.invalid`, and show rendered URLs in the report with personal values masked.
- **Don't trigger actions.** Load unsubscribe, confirm, verify, opt-in and other links carrying a token with `HEAD` only (web-fetch tool), never in a browser; if `HEAD` isn't possible, mark them **not checked**.
- **(script)** `javascript:`, `data:`, `file:` and app links are never loaded: they're reported as findings and left out of `links_to_load`.
- Check at most about 150 unique URLs per run, primary links first, and say so if you hit the cap.

### Static checks (script)

- **Missing scheme:** an href with no `https://` (for example `www.brand.com`) is treated as a relative link and goes nowhere. **Blocker** on a primary link, **warning** elsewhere.
- **No TLS:** an `http://` link or image = **warning**.
- **Placeholder destination:** `example.com`, `#`, an empty href or another tool's merge tag (`*|UNSUB|*`) = **blocker** on a primary link, **warning** elsewhere (merge tags are always a blocker).
- **Placeholder words** in the path or query (`test`, `todo`, `dummy` and the others in `rules.json`) = **warning**: "looks like a placeholder; confirm the real URL".
- **Near-miss host:** a host one or two characters, or only a top-level domain, away from a host used elsewhere in the same message (for example `brxcdn.co` where every other image uses `brxcdn.com`) = **blocker** on a primary link or image, **warning** elsewhere. Also compare by hand with hosts in other messages of the same campaign or scenario, and with project variables.
- **Public shortener in SMS** (bit.ly, tinyurl and similar) = **warning**: carriers filter them. A brand-owned domain is fine.
- **Tracking-path consistency (by hand):** if most links use one tracking path pattern and a few use another (for example `/?qs=` against `/u/?qs=`) = **warning** ("confirm this is intentional").

### Loading links

Try each method in turn, per link, and record which one worked:

1. **Web-fetch tool.** Try `HEAD`, then fall back to `GET` if the tool supports it. Follow redirects, including link shorteners and click-tracking domains, to the final destination and record the chain.
2. **Browser tool**, if the web-fetch tool is missing or refuses the URL (for example "not on allowlist", a blocked domain, or a tool error). This is a browser tool the client offers, for example Claude in Chrome or the built-in browser in the Claude desktop app. Open the link in a new tab, then:
   - **Read the real HTTP status when the browser tool can run JavaScript.** Run this on the page:

     ```js
     ({status: (performance.getEntriesByType('navigation')[0] || {}).responseStatus, title: document.title, url: location.href, type: document.contentType})
     ```

     `status` is the server's response code: 200 is fine, 404 or 410 is broken, 5xx is a server error. `url` shows where redirects ended up, and `type` confirms an image URL really returned an image. Trust the status over the page text.
   - **Otherwise, or if `status` is empty or 0, read the page title and text.** Treat it as **broken** if the title or main text says "404", "not found", "page not found", "doesn't exist", "no longer available" or "error", if the page redirects to a generic error path, or if an image URL shows an error page instead of an image.
   - **Check other links on the same host from the open page** to save time and approval prompts: run a same-origin `fetch(url, {method: 'HEAD'})` for each remaining URL on that host and record each `status` and `content-type`. Browsers block this for other hosts, so load each new host on its own.
   - **Bot challenges are "not checked", never broken.** These are pages titled "Just a moment…", "Attention Required", "Checking your browser" or "Verify you are human", or any CAPTCHA. Never try to solve or bypass one.
   - **If navigation fails outright** (no page loads, "denied or failed"), record "couldn't load". Treat it as a supporting signal for a static finding on that link, such as a near-miss host, not as a confirmed 404.

   The client may ask the user to approve each new site in the browser. Wait for each approval, don't work around it, and if one is declined mark that host's links **not checked**. Never click, sign in, accept cookies or submit anything. Close the tab when done.
3. **Not checked**, only when no method could load the link.

A tool that refuses one domain doesn't prove the others will fail, so keep trying the next method for each link.

### Results

- 404, 410 or 5xx (or a browser-detected error page) on a primary link or image = **blocker**. On a secondary or footer link = **warning**.
- 401, 403, 429, bot challenge, declined site approval or timeout = **not checked**. Never call it broken.
- Add a short **link check results** table to the report (link, method used, result).
- **Not checked, primary link:** its own **warning** row in the triage table: "Not checked: click before launch", with the reason.
- **Not checked, other links:** one grouped **warning** row listing them.
- Any not-checked link caps the verdict at **GO WITH CAUTION** and adds `· N links not checked` to the banner.

## Jinja and personalization (all channels)

- **(script)** Merge tags from other tools or unfinished copy (`[First Name]`, `*|FNAME|*`, `{{FNAME}}`, `%%Name%%`, Klaviyo `person.first_name` or `|default:'x'`, `[URL]`, "Lorem ipsum", a push titled "Notification title") = **blocker**.
- **(script)** An unclosed `{{` or `{%`, or a block tag that's never closed or closes the wrong block = **blocker**.
- **(script)** `| default(x)` without `true` = **warning**: it replaces only undefined values, not `None` or `''`. Use `| default(x, true)`.
- **(script)** A customer property with no fallback = **warning** in the subject, preheader, push title or SMS, **nitpick** in the email body. Then render against a sparse profile: if it prints `None` or empty in the subject or first line, it's a **blocker**.
- **(script)** A loop over an aggregate with no `!= 'None'` guard = **warning**: an empty aggregate renders as the string `'None'`, so the loop runs over its letters.
- **(script)** `event.*` in a campaign that isn't triggered by an event = **blocker**: there's no event, so it renders empty.
- **By hand:** confirm each referenced variable (`customer.*`, `event.*`, `aggregates[...]`, `catalogs[...]`, `recommendations(...)`, `block(...)`) exists in the schema or the project's assets. Some references, such as saved metrics, have no read tool: report them as "not verified", not as broken.
- **By hand:** render against each sample profile and read the result. A missing attribute with no fallback in visible copy = **warning**; in the subject or first line = **blocker**.

## Email: compliance

- **(script)** Unsubscribe or preference-centre link (`{{ email.unsubscribe }}`, `{{ consent.page }}` or a link reading unsubscribe or preferences). Missing = **blocker**.
- **(script)** Physical postal address. The script looks for a street address, US ZIP or UK postcode, or an address project variable, and says **warning** when it finds none: read the footer, and if it's really missing that's a **blocker** (CAN-SPAM).
- **(script)** **Canada (CASL)**, when `--regions` includes `CA`: at least one other way to reach the sender (phone number, email address or contact link). Missing = **blocker**. Confirm by hand that any website link reaches the sender's contact details.
- **(script)** Consent category set (unless the project sends this channel under general consent). Missing = **blocker**.
- **(script)** View-in-browser link. Missing = **nitpick**.

## Email: rendering and deliverability

- **(script)** Subject present. Missing = **blocker**. Longer than `subject_max_chars` = **nitpick**, or **warning** (by hand) if the key message falls after the cut.
- **(script)** Preheader empty = **warning**. Too long, or the same as the subject = **nitpick**.
- **(script)** Alt text on images. Missing on a linked or hero image = **warning**, elsewhere **nitpick**.
- **(script)** Image-only or nearly image-only email = **warning**.
- **(script)** HTML larger than about 102 KB (Gmail clips it, which can hide the unsubscribe link) = **warning**. Over about 90 KB = **nitpick**.
- **(script)** Sender name or email not set on the message = **warning** (confirm whether the project default applies).
- **By hand:** dark mode problems, such as dark text on transparent backgrounds or logos with no padding = **nitpick**.

## Email: spam risk

**(script)** The script scores all-caps words, repeated `!` or `$` and trigger phrases in the subject, trigger phrases in the body, heavy emoji, text hidden with font size 0, and link text that shows one domain but points to another. It rates the risk low, medium or high (`stats.spam`) with its reasons; high = **warning**. More than about 50 unique links = **nitpick**.

**By hand:** a subject or sender that misrepresents the content = **blocker**.

## SMS and MMS: compliance

- **(script)** Opt-out language ("Reply STOP to opt out" or equivalent) in a marketing message. Missing = **blocker**; give the corrected body, ready to paste. Ignore it only for a purely transactional message.
- **(script)** Brand or sender named at the start (pass `--brand`; without it the script accepts a "Name:" opening). Missing = **warning**, or **blocker** when the audience can include Texas or Canada (`--regions` with `US-TX` or `CA`).
- **(script)** HELP language. Missing = **nitpick** (**warning** in regulated industries, by hand).
- **(script)** Consent category set. Missing = **blocker**. Confirm by hand that it's a marketing SMS category.
- **(script)** Length: the script estimates GSM-7 or UCS-2 encoding and the number of segments (counting each `{{ }}` as `jinja_estimate_chars` characters) and flags more than the step's `max_message_parts` = **warning**. Curly quotes or dashes that force UCS-2 = **nitpick**.
- **By hand:** regulated industries (finance, healthcare, insurance, alcohol and similar): missing STOP, HELP or brand name = **blocker**.

## SMS and MMS: prohibited and restricted content

**(script)** flags terms by category from `rules.json`. Judge each one by hand. Say plainly that final carrier approval is outside this skill's control.

- Firearms or weapons, illegal drugs, sexual or adult content, hate content = **blocker**.
- Alcohol, tobacco or vaping without an age gate = **warning**.
- Cannabis or CBD, gambling, high-risk finance (payday loans, debt relief, multi-level marketing, crypto schemes), prescription drugs = **warning**, or **blocker** when unambiguous.
- Phishing patterns (urgent account or security language with a link, masked links) = **blocker**.

## SMS and MMS: North America (US and Canada)

Rules as of October 2026. These checks flag risk for a person to confirm; they are not legal advice, and state laws change often. Say so once in the report whenever a finding from this section appears.

### Where recipients are

Several checks depend on the audience. Work it out in this order:

1. Read the campaign's customer filter, or the scenario's trigger, conditions and segment filters, for `country`, `state`, `region`, `postal` or phone-prefix filters.
2. If nothing limits the audience, ask the user once: "Which countries and US states can receive this?"
3. If you can't ask or there's no answer, assume **every US state plus Canada**, and say so at the top of the report.

Pass the result to the script as `--regions`, for example `--regions US,US-TX,CA`.

### Checks

1. **Quiet hours exist.** Every marketing SMS or MMS must be held to a send-time window. A **campaign** needs silent hours or a throughput policy with time restrictions **(script)**. A **scenario step** needs a silent-hours wait (`wait-action-silent-hours`), an optimal-time wait with limits, or a time-restricted throughput policy placed directly before the send, with nothing in between that could push it outside the window (by hand). Federal baseline: 8 a.m.–9 p.m. in the **recipient's** local time. No time gating on a marketing SMS = **blocker**.
2. **Recipient time zone.** The window must use the customer's local time zone, not the project's or a single fixed zone. Project or fixed time zone with a multi-time-zone audience = **warning**.
3. **Strictest-state window.** Compare the window with this cover-everything window for the US: **9 a.m.–8 p.m. recipient local time, Monday–Saturday, no Sunday sends.** Anything wider = **warning**, naming the states it conflicts with:

   | Window setting | States affected |
   |---|---|
   | Starts before 9 a.m. | Texas, Minnesota, Rhode Island |
   | Ends after 8 p.m. | Florida, Oklahoma, Maryland, Washington, Oregon, Alabama, Louisiana, Mississippi |
   | Sends on Sunday | Florida, Alabama, Louisiana, Mississippi (no Sunday contact); Texas (noon–9 p.m. only) |
   | Ends after 5 p.m. Saturday or 6 p.m. weekdays | Rhode Island (9 a.m.–6 p.m. weekdays, 9 a.m.–5 p.m. Saturday) |

   Only list states the audience can include. A campaign scheduled for a fixed time: check that time in each time zone the audience covers.
4. **Three-per-24-hours limit.** Florida, Oklahoma and Maryland limit marketing contact to 3 messages per 24 hours on the same subject. Work out the most SMS or MMS messages one customer can receive in any 24-hour span (from waits between steps and re-entry in a scenario; from other sends to the same audience for a campaign). More than 3 possible = **warning** when the audience can include those states.
5. **Canada (CASL) identification.** When the audience can include Canada, each commercial SMS or MMS must identify the sender and give a mailing address plus a phone number, email address or website, or link to a page with them **(script: no link = blocker)**. It also needs a working opt-out (replying STOP qualifies).
6. **Texas SB 140 reminder.** Since September 1, 2025, Texas telephone-solicitation law covers marketing texts. Senders must register yearly with the Texas Secretary of State unless exempt; exemptions include public companies, some texts to current or former customers, and businesses whose sales are mostly in physical stores. Consumers can sue for texts to numbers on the Texas no-call list. Neither can be checked from Bloomreach, so when the audience can include Texas, add one **warning** row: "Texas: confirm SB 140 registration or exemption, and that numbers are checked against the Texas no-call list."

## Mobile push

- **(script)** Empty body = **blocker**. Title or body likely to be truncated = **nitpick**.
- **(script)** A browser or deep-link tap action with no URL = **blocker**. **By hand:** the deep link resolves and has a web fallback; broken on the primary action = **blocker**.
- **(script)** Consent category missing = **warning**.
- Image URL resolves (load it with the other links).

## Other channels

WhatsApp, RCS, web push, app inbox and webhook steps aren't checked by the script (`not_checked`). Check them by hand where you can (links, Jinja, consent), and list them under "couldn't verify" otherwise. Never repeat webhook headers or payloads: they often hold API tokens.

## Send configuration (all channels)

- **(script)** Frequency policy `unlimited-policy` on a marketing send = **nitpick**, or **warning** (by hand) if customers can receive it often.
- SMS quiet hours, send windows and frequency: see "SMS and MMS: North America".
