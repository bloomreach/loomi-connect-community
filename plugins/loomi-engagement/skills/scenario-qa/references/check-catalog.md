# Scenario QA check catalog

Apply these checks in steps 2 and 3 of the skill. Report a finding only when the evidence supports it, and list anything you couldn't check under "couldn't verify".

## Links (all channels)

- Extract every href and URL: email modules and rendered HTML, image sources, SMS body, push deep links and web fallbacks. Note which ones are **primary**: the main call-to-action button, the hero image and its link, and the push primary action. Skip `{{ email.unsubscribe }}` and other Bloomreach system links, which only exist at send time.
- Render Jinja in URLs against a sample profile before checking them. If a URL can't be rendered, report the template; don't guess.
- Remove duplicates before checking. Check at most about 150 unique URLs per run, primary links first, and say so if you hit the cap.

### Static checks (run on every link, no web access needed)

- **Missing scheme:** an href with no `https://` or `http://` (for example `bloomreach.com`) is treated as a relative link and goes nowhere. **Blocker** on a primary link, **warning** elsewhere.
- **No TLS:** an `http://` link or image = **warning**.
- **Placeholder destination:** `example.com`, `#` or an empty href = **blocker** on a primary link, **warning** elsewhere.
- **Placeholder words** in the path or query, such as `test`, `placeholder`, `todo`, `tbd`, `example`, `dummy`, `lorem`, `changeme`, `xxx`, `broken`, `wontwork` or `fixme` = **warning** ("looks like a placeholder; confirm the real URL").
- **Near-miss host:** a host one or two characters, or a different top-level domain, away from a host used elsewhere in the scenario or in project variables (for example `brxcdn.co` where every other image uses `brxcdn.com`) = **blocker** on a primary link or image, **warning** elsewhere. Name the host it probably should be.
- **Tracking-path consistency:** if most links use one tracking path pattern and a few use another (for example `/?qs=` against `/u/?qs=`) = **warning** ("confirm this is intentional").

### Loading links

Try each method in turn, per link, and record which one worked:

1. **Web-fetch tool.** Try `HEAD`, then fall back to `GET` if the tool supports it. Follow redirects, including link shorteners and click-tracking domains, to the final destination and record the chain.
2. **Browser tool**, if the web-fetch tool is missing or refuses the URL (for example "not on allowlist", a blocked domain, or a tool error). Open the link in a new tab, then:
   - **Read the real HTTP status when the browser tool can run JavaScript.** Run this on the page:

     ```js
     ({status: (performance.getEntriesByType('navigation')[0] || {}).responseStatus, title: document.title, url: location.href, type: document.contentType})
     ```

     `status` is the server's response code: 200 is fine, 404 or 410 is broken, 5xx is a server error. `url` shows where redirects ended up, and `type` confirms an image URL really returned an image. Trust the status over the page text.
   - **Otherwise, or if `status` is empty or 0, read the page title and text.** Treat it as **broken** if:
     - the title or main text says "404", "not found", "page not found", "doesn't exist", "no longer available" or "error"
     - the page redirects to a generic error path
     - an image URL shows an error page instead of an image
   - **Check other links on the same host from the open page** to save time and approval prompts. Once one page on a host is loaded, run a same-origin `fetch(url, {method: 'HEAD'})` for each remaining URL on that host and record each `status` and `content-type`. Browsers block this for other hosts, so load each new host on its own.
   - **Bot challenges are "not checked", never broken.** These are pages titled "Just a moment…", "Attention Required", "Checking your browser" or "Verify you are human", or any CAPTCHA. Never try to solve or bypass one.
   - **If navigation fails outright** (no page loads, "denied or failed"), record "couldn't load". Treat it as a supporting signal for any static finding on that link, such as a near-miss host, not as a confirmed 404.

   The client may ask the user to approve each new site in the browser. Wait for each approval, don't work around it, and if one is declined mark that host's links **not checked**. Never click, sign in, accept cookies or submit anything. Close the tab when done.
3. **Not checked**, only when no method could load the link.

### Results

- 404, 410 or 5xx (or a browser-detected error page) on a primary link or image = **blocker**. On a secondary or footer link = **warning**.
- 401, 403, 429, bot challenge, declined site approval or timeout = **not checked**. Never call it broken.
- Add a short **link check results** table to the report (link, method used, result) so the reader can see what was really loaded.
- **Not checked, primary link:** its own **warning** row in the triage table: "Not checked: click before launch", with the reason (for example "web tool blocked this domain; no browser available").
- **Not checked, other links:** one grouped **warning** row listing them.
- Any not-checked link caps the verdict at **GO WITH CAUTION** and adds `· N links not checked` to the banner.

## Jinja and personalization (all channels)

- For each referenced variable (`customer.*`, `event.*`, `aggregates[...]`, `catalogs[...]`, `recommendations(...)`, `block(...)`), confirm it exists in the schema or the project's assets.
- Some references, such as saved metrics, have no read tool. Report them as "not verified", not as broken.
- Simulate the render for each sample profile:
  - A missing attribute with no `| default(...)` in visible copy = **warning**.
  - The same in the subject line or first line, where it would print empty or broken = **blocker**.
- A catalog lookup (`item_by_id`) fed by an aggregate that can be empty, with no guard = **warning**.
- Unbalanced tags or syntax errors = **blocker**.
- Raw placeholders from other tools (`[First Name]`, `{{FNAME}}`, other ESP syntax) = **blocker**.

## Email: compliance

- An unsubscribe link (`{{ email.unsubscribe }}` or a working preference-centre link) is required. Missing = **blocker**.
- Physical postal address in the footer. Missing = **blocker**.
- **Canada (CASL):** when the audience can include Canada, the email must also give at least one other way to reach the sender (phone number, email address or website), or link to a page that does. Missing = **blocker**.
- Consent category set on the step. Missing = **blocker**.
- View-in-browser link. Missing = **nitpick**.

## Email: rendering and deliverability

- Subject present. Missing = **blocker**. Longer than about 60 characters (desktop) or 30–40 (mobile) = **nitpick**, or **warning** if the key message falls after the cut.
- Preheader empty = **warning** (the inbox preview falls back to body text). Too long, or the same as the subject = **nitpick**.
- Alt text on every image. Missing on a call-to-action or hero image = **warning**, elsewhere **nitpick**.
- Image-only or nearly image-only email = **warning**.
- Rendered HTML larger than about 102 KB (Gmail clips it, which can hide the unsubscribe link) = **warning**. Over about 90 KB = **nitpick**.
- Dark mode: dark text on transparent backgrounds, logos with no padding = **nitpick**.
- Sender name and email set and plausible, sensible reply-to. Missing = **warning**.

## Email: spam risk

Rate the risk low, medium or high, with specific reasons.

- Subject: all-caps words, `!!!` or `$$$`, trigger phrases (FREE, ACT NOW, 100%, RISK-FREE, GUARANTEE, WINNER, CLICK HERE, URGENT, CASH), excessive emoji, high share of capitals.
- Body: density of trigger phrases, blocks of capitals, hidden text (font size 0, text the same colour as the background, `display:none` content), link text that shows one domain but points to another.
- Subject or sender that misrepresents the content = **blocker**.
- More than about 50 unique links = **nitpick**. Almost no text = **warning**.
- High overall risk on an email about to launch = **warning**.

## SMS and MMS: compliance

- Opt-out language ("Reply STOP to opt out" or equivalent) in a marketing message. Missing = **blocker**; give the corrected body, ready to paste.
- Brand or sender named at the start. Missing = **warning**, or **blocker** when the audience can include Texas or Canada (see "SMS and MMS: North America").
- HELP language. Missing = **nitpick** (**warning** in regulated industries).
- Consent category set to marketing SMS or equivalent. Wrong or missing = **blocker**.
- Link shorteners: a brand-owned domain is fine. Public shorteners (bit.ly, tinyurl and similar) = **warning**, because carriers filter them.
- Length: estimate GSM-7 or UCS-2 encoding and flag a rendered length beyond the step's `max_message_parts`.
- Regulated industries (finance, healthcare, insurance, alcohol and similar): missing STOP, HELP or brand name = **blocker**.

## SMS and MMS: prohibited and restricted content

Say plainly that final carrier approval is outside this skill's control.

- Firearms or weapons, illegal drugs, sexual or adult content, hate content = **blocker**.
- Alcohol, tobacco or vaping without an age gate = **warning**.
- Cannabis or CBD, gambling, high-risk finance (payday loans, debt relief, multi-level marketing, crypto schemes), prescription drugs = **warning**, or **blocker** when unambiguous.
- Phishing patterns (urgent account or security language with a link, masked links) = **blocker**.

## SMS and MMS: North America (US and Canada)

Rules as of October 2026. These checks flag risk for a person to confirm; they are not legal advice, and state laws change often. Say so once in the report whenever a finding from this section appears.

### Where recipients are

Several checks depend on the audience. Work it out in this order:

1. Read the scenario's trigger, conditions and any segment filters for `country`, `state`, `region`, `postal` or phone-prefix filters.
2. If nothing limits the audience, ask the user once: "Which countries and US states can receive this scenario?"
3. If you can't ask or there's no answer, assume **every US state plus Canada**, and say so at the top of the report.

### Checks

1. **Quiet hours exist.** Every marketing SMS or MMS step must be held to a send-time window, by a silent-hours wait (`wait-action-silent-hours`), an optimal-time wait with limits, or a throughput policy with time restrictions, placed directly before the send with nothing in between that could push it outside the window. Federal baseline: 8 a.m.–9 p.m. in the **recipient's** local time. No time gating on a marketing SMS = **blocker**.
2. **Recipient time zone.** The window must use the customer's local time zone, not the project's or a single fixed zone. Project or fixed time zone with a multi-time-zone audience = **warning**.
3. **Strictest-state window.** Compare the window with this cover-everything window for the US: **9 a.m.–8 p.m. recipient local time, Monday–Saturday, no Sunday sends.** Anything wider = **warning**, naming the states it conflicts with:

   | Window setting | States affected |
   |---|---|
   | Starts before 9 a.m. | Texas, Minnesota, Rhode Island |
   | Ends after 8 p.m. | Florida, Oklahoma, Maryland, Washington, Oregon, Alabama, Louisiana, Mississippi |
   | Sends on Sunday | Florida, Alabama, Louisiana, Mississippi (no Sunday contact); Texas (noon–9 p.m. only) |
   | Ends after 5 p.m. Saturday or 6 p.m. weekdays | Rhode Island (9 a.m.–6 p.m. weekdays, 9 a.m.–5 p.m. Saturday) |

   Only list states the audience can include.
4. **Three-per-24-hours limit.** Florida, Oklahoma and Maryland limit marketing contact to 3 messages per 24 hours on the same subject. Using the waits between steps, work out the most SMS or MMS messages one customer can receive from this scenario in any 24-hour span, including re-entry if the trigger can fire again. More than 3 possible = **warning** when the audience can include those states.
5. **Brand name at the start.** Each marketing SMS or MMS should open with the brand name. Missing = **warning**, or **blocker** when the audience can include Texas (concealing the sender's identity is a claim under Texas law) or Canada (CASL requires sender identification).
6. **Canada (CASL) identification.** When the audience can include Canada, each commercial SMS or MMS must identify the sender and give a mailing address plus a phone number, email address or website, or a link to a page with them. It also needs a working opt-out (replying STOP qualifies). Missing = **blocker**.
7. **Texas SB 140 reminder.** Since September 1, 2025, Texas telephone-solicitation law covers marketing texts. Senders must register yearly with the Texas Secretary of State unless exempt; exemptions include public companies, some texts to current or former customers, and businesses whose sales are mostly in physical stores. Consumers can sue for texts to numbers on the Texas no-call list. Neither registration nor the no-call list can be checked from Bloomreach, so when the audience can include Texas, add one **warning** row: "Texas: confirm SB 140 registration or exemption, and that numbers are checked against the Texas no-call list."

## Mobile push

- Title or body likely to be truncated = **nitpick**. Empty body = **blocker**.
- Deep link resolves and has a web fallback. Broken on the primary action = **blocker**.
- Consent category and frequency policy set.
- Image URL resolves.

## Send configuration (all channels)

- Frequency policy `unlimited-policy` on a marketing send = **nitpick**, or **warning** if customers can re-enter the scenario often.
- SMS quiet hours, send windows and frequency: see "SMS and MMS: North America".

## Flow-level checks

- **Dead end:** a wait, condition or split with no outgoing connection = **warning**. Customers sent there stop silently; it's often an unfinished branch.
- **Orphan:** a node with no incoming connection, other than the trigger = **warning**. It never runs.
- **Unreachable branch or unused split variant:** a condition or A/B output with no connection = **nitpick**, or **warning** if it's the main path. An A/B control group with no connection is usually an intentional holdout: note it, don't flag it.
- **Connection from a removed variant:** an `ab-split` connection whose `connector_index` matches no variant `id` (or `id + 1` on `ab-split-contextual`) = **warning**.
- **Unresolved reference:** an event, property, aggregate, catalog or recommendation that isn't in the schema or project = **blocker**.
- **Archived reference:** a condition or send that points at an archived segmentation, aggregate or expression (`archived: true`) = **warning**.
- **No exit or suppression:** an abandonment-style flow that doesn't re-check conversion just before the send, after a long wait = **warning**.
- **Waits and time zones:** a long wait followed by a send with no send-time window = **nitpick**. A fixed clock-time wait with no time zone = **warning**.
- **Re-entry:** a trigger that fires often (for example session events) with no re-entry guard and unlimited frequency = **warning**.
- **A/B split:** variant percentages that don't total 100 = **blocker**.
- **Schedule with no days:** a weekly or monthly `repeated-trigger` with `days: []` = **warning** (Engagement saves it, but it may never run).
