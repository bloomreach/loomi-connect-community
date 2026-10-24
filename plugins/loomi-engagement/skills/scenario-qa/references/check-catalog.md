# Scenario QA check catalog

Apply these checks in steps 2 and 3 of the skill. Report a finding only when the evidence supports it, and list anything you couldn't check under "couldn't verify".

## Links (all channels)

- Extract every href and URL: email modules and rendered HTML, SMS body, push deep links and web fallbacks.
- Render Jinja in URLs against a sample profile before requesting them. If a URL can't be rendered, report the template; don't guess.
- Remove duplicates before requesting. Try `HEAD`, then fall back to `GET`. Follow redirects, including link shorteners and click-tracking domains, to the final destination and record the chain.
- Check at most about 150 unique URLs per run, and say so if you hit the cap.
- 404, 410 or 5xx on a primary call to action or hero image = **blocker**. On a secondary or footer link = **warning**.
- 401, 403, 429, bot challenge or timeout = **couldn't verify**. List it, never call it broken, never count it as a blocker.
- `http://` (no TLS) destination = **warning**. Placeholder destinations (`example.com`, `#`, empty href) = **blocker** on a call to action, **warning** elsewhere.
- **Tracking-path consistency:** if most links use one tracking path pattern and a few use another (for example `/?qs=` against `/u/?qs=`) = **warning** ("confirm this is intentional").

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
- Brand or sender named at the start. Missing = **warning**.
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

## Mobile push

- Title or body likely to be truncated = **nitpick**. Empty body = **blocker**.
- Deep link resolves and has a web fallback. Broken on the primary action = **blocker**.
- Consent category and frequency policy set.
- Image URL resolves.

## Send configuration (all channels)

- Frequency policy `unlimited-policy` on a marketing send = **nitpick**, or **warning** if customers can re-enter the scenario often.
- No throughput policy or quiet hours on SMS = **warning** (local-time sending rules).

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
