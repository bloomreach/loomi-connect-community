# Weblayer reference

The platform parts of a Bloomreach Engagement weblayer: smart triggering, the parameter syntax, the `self` object, the JavaScript skeleton, the `utils` helper library and phone input. For Jinja that pulls in data (recommendations, aggregates, catalogs, reports, personalisation), use the `engagement-jinja-writer` skill.

Checked against the Bloomreach documentation on 2026-10-30 (pages: smart-triggering-in-weblayers, configure-smart-triggering, using-template-parameters, weblayer-design, weblayer-reference, advanced-weblayers-use, exit-popup, web-tracking). The `utils` library, `self.inPreview` and the phone-input setup come from Bloomreach's built-in weblayer templates and aren't in the public docs; the `utils` methods below were checked against the published `/brstatic/utils.js` on the same date.

## Smart triggering: when the weblayer appears

**When** a weblayer appears is set in the weblayer's **Settings** tab, under **Smart triggering**, not in code. The Web SDK measures the visitor's engagement in the browser and runs the weblayer once the conditions are met. The weblayer's other settings (**Show on**, **Target devices**, **Audience**) still decide **whether** it appears at all. The same section is on the weblayer node in the scenario editor.

| Condition | Measures | Operator and value |
|---|---|---|
| Active time on page | Time spent scrolling, clicking, typing or moving the mouse. Idle and background-tab time don't count | `>=` or `<`, seconds or minutes |
| Total time on page | Time since the page loaded, idle included | `>=` or `<`, seconds or minutes |
| Idle time | Time with no interaction | `>=` or `<`, seconds or minutes |
| Click count | Clicks on the current page | `>=` or `<`, a number |
| Scroll position | Furthest point scrolled, in pixels (never goes down) | `>=` or `<`, pixels |
| Section in view | Whether one CSS selector has come into view | One selector |
| Visitor returned | The visitor came back after switching tabs, minimising or locking the screen | Yes or no |
| Exit intent | The cursor left toward the address bar or tabs. **Desktop only** | Yes or no |

- Up to **four** conditions, each signal once, and **all** must be true at the same moment. There's no OR.
- Signals reset on every page load, so nothing can span pages or sessions. Exit intent and Visitor returned fire at most once per page view.
- Check the conditions can be true together: `Total time on page < 10` with `Active time on page >= 30` never shows.
- The site needs **Web SDK v3.57.0 or later**. Older versions ignore the conditions and show the weblayer on page load.
- Leave the section empty and the weblayer shows as soon as its other settings allow.

**What this means for the code:** never put timing in the JavaScript. No trigger, delay or show-after parameters, no `setTimeout` before showing, and no exit-intent, scroll or idle listeners. A weblayer with both triggering code and smart triggering conditions behaves unpredictably. Give the user the conditions to set instead.

Older weblayers (older built-in templates, saved assets and Use Case Center weblayers) still carry this code, often in a **Triggering** or **Behavior** parameter category. When you edit one, remove it and map it to conditions:

| Old code | Smart triggering condition |
|---|---|
| `PARAM_trigger` "On entry" with `PARAM_showAfter` of N ms | Total time on page `>=` N/1000 seconds, or Active time on page if it should wait for attention. None if N is 0 |
| "On exit", or a `mouseout` listener | Exit intent, ideally with Active time on page `>=` 10 to 20 seconds. Desktop only |
| "On scroll", or a `scroll` listener | Scroll position `>=` a pixel value, or Section in view with a selector |
| An idle or inactivity timer | Idle time `>=` N |

Loomi Connect doesn't return smart triggering conditions: `search_banners` only shows page targeting under `trigger`. Ask the user what's set if it matters.

## Parameters

Parameters show up in the weblayer's **Parameters** panel, so a marketer can change them without editing code.

```
[[ {name: 'ParamName', tooltip: 'Description', category: 'Category', orderIndex: '1000', isJsonParam: true} : type | default ]]
```

- `name` and `isJsonParam: true` are required: without `isJsonParam: true`, the whole `{...}` shows as the parameter's name. `tooltip`, `category` and `orderIndex` are optional, but always give them so the panel is grouped and sorted (`orderIndex` sorts ascending; use 1000 and up, as a string).
- Types: `string` (the default), `text` (multi-line copy), `number`, `color`, `image`, `boolean`, `enum(Option1,Option2)`, `date`, `time`, `datetime`, `metric` and `recommendation` (an engine picker, used through `engagement-jinja-writer`). There's no `url`, `html` or `font` type: use `string` for URLs and an `enum` for a choice of fonts.
- Use `color` for every colour, so the panel shows a colour picker, and `image` for every image.
- Parameters are swapped for their values as plain text **before** Jinja or JavaScript runs. In JavaScript, wrap them in quotes and cast numbers: `parseInt("[[ ... : number | 1000 ]]", 10)`.
- Keep a parameter's `name` unchanged when you edit a weblayer. The stored value is keyed on it.

### Reusing a parameter in CSS

When a parameter appears in more than one CSS rule, declare it once at the top of the CSS and reference the variable:

```css
{% set primaryColor = "[[ {name: 'PrimaryColor', tooltip: 'Primary brand colour', category: 'Branding', orderIndex: '1000', isJsonParam: true} : color | #E91E8C ]]" %}
{% set fontFamily = "[[ {name: 'FontFamily', tooltip: 'Font family', category: 'Branding', orderIndex: '1010', isJsonParam: true} : string | 'Poppins', sans-serif ]]" %}

.heading { color: {{ primaryColor }}; font-family: {{ fontFamily }}; }
.label { color: {{ primaryColor }}; font-family: {{ fontFamily }}; }
```

- All `{% set %}` lines go at the very top, before any rule.
- Use camelCase variable names that match the parameter name.
- Parameters used once can go straight into the rule.
- HTML and JavaScript use `[[ ... ]]` directly.

### Personalisation

Put personalisation in the HTML as Jinja, not inside a parameter's default: Jinja in parameter defaults isn't documented. Even a greeting such as `{{ customer.first_name | default('there') }}` goes through `engagement-jinja-writer`, which checks the attribute name against the project.

## The `self` object

| Property | What it is |
|---|---|
| `self.html` | The weblayer's HTML |
| `self.style` | The weblayer's CSS |
| `self.sdk` | The Bloomreach Web SDK: `.track()`, `.identify()`, `.configuration` |
| `self.inPreview` | `true` in the Bloomreach editor preview (used by the built-in templates, not in the public docs) |
| `self.data` | Weblayer metadata, for example `self.data.banner_id` |
| `self.banner` | The weblayer element, set in `createBanner()` |

## JavaScript skeleton

Every weblayer uses this structure. Build what you need inside `createBanner()`, and do all positioning in CSS. It has no timing code: smart triggering decides when the SDK runs it, and `utils.registerStartTrigger()` then shows the weblayer straight away.

```javascript
let config = {
  PARAM_parentElement: "[[ {name: 'ParentElement', tooltip: 'CSS selector of the parent element', category: 'Layout', orderIndex: '1001', isJsonParam: true} : string | body ]]",
  PARAM_removeAfter: parseInt("[[ {name: 'AutoRemove', tooltip: 'Remove after (ms), 0 = never', category: 'Behavior', orderIndex: '1007', isJsonParam: true} : number | 0 ]]", 10),
  PARAM_weblayerType: "[[ {name: 'WeblayerType', tooltip: 'Pop-up overlays the page, Inline sits in the content', category: 'Layout', orderIndex: '1000', isJsonParam: true} : enum(Pop-up,Inline) | Pop-up ]]"
}

const self = (config.self = this)
const bannerSemiId = (config.bannerSemiId = Math.random().toString(36).substring(5))
window["__exp_triggered-" + bannerSemiId] = false

let apiUrl = "https://api.exponea.com"
if (!self.inPreview) {
  apiUrl = self.sdk.configuration.target
}
let utilsSource = apiUrl + "/brstatic/utils.js"

if (self.inPreview) {
  config.PARAM_parentElement = "body"
}
config.apiBaseURL = apiUrl

window["__exp_load_init-" + bannerSemiId] = Promise.all([loadScript(utilsSource)])

function loadScript(src) {
  return new Promise((resolve) => {
    setTimeout(() => {
      let el = document.querySelector(`body > script[src='${src}']`)
      if (el) return el.loaded ? resolve(true) : el.addEventListener("load", () => resolve((el.loaded = true)))
      el = document.createElement("script")
      el.src = src
      el.defer = true
      el.loaded = false
      el.addEventListener("load", () => resolve((el.loaded = true)))
      document.body.appendChild(el)
    })
  })
}

function removeBanner() {
  if (self.banner && self.banner?.parentNode) {
    self.banner.parentNode.removeChild(self.banner)
  }
}

function createBanner() {
  const placeholder = document.createElement("div")
  placeholder.insertAdjacentHTML("afterbegin", self.html)
  const banner = placeholder.querySelector(".weblayer")
  self.banner = banner

  banner.querySelector(".close-btn").onclick = utils.handleCloseButtonClick.bind(utils)

  if (config.PARAM_weblayerType === "Inline") {
    banner.style.position = "static"
  }

  banner.insertAdjacentHTML("afterbegin", "<style>" + self.style + "</style>")
  banner.querySelectorAll("a").forEach((link) => utils.trackLink(link, "click", true))

  // Event handlers, form logic and step navigation go here.

  utils.attachBannerToDom(banner)
}

window["__exp_load_init-" + bannerSemiId]
  .then(function () {
    config.createBannerFunction = createBanner
    config.removeBannerFunction = removeBanner
    utils.setConfig(config)
    utils.registerStartTrigger(false)
  })
  .catch(function (error) {
    console.error("Error loading resources: ", error)
  })

return { remove: removeBanner }
```

- The section from `const self` to `config.apiBaseURL`, `loadScript()` and `removeBanner()` don't change between weblayers.
- Don't add `PARAM_trigger` or `PARAM_showAfter`. `utils` still reads them, and if they're set it waits for them on top of the smart triggering conditions.
- `PARAM_removeAfter` (auto-close) isn't triggering and can stay. Leave it out if the weblayer shouldn't close itself.
- If `PARAM_parentElement` doesn't match an element on the page, `utils.attachBannerToDom()` silently does nothing.
- `utils.registerStartTrigger(true)` when the weblayer has a phone input (see below).
- The `.weblayer` and `.close-btn` class names are examples. Use your own, but keep the JavaScript and HTML in step.

## `utils` API

`utils` is a global loaded from `/brstatic/utils.js` by the skeleton. It's Bloomreach's shared helper library for the built-in weblayer templates, not a publicly documented API, so stick to the methods below. **Never redeclare it** with `const`, `let` or `var`: the weblayer then breaks without an obvious error.

| Method | What it does |
|---|---|
| `utils.setConfig(config)` | Passes the config object. Call once |
| `utils.registerStartTrigger(usePhone)` | Loads the platform's weblayer CSS (and the phone-input files if `usePhone` is `true`), tracks the `show` event and calls `createBanner()`. Don't track `show` yourself |
| `utils.attachBannerToDom(banner)` | Inserts the weblayer at the start of `PARAM_parentElement`. **Last line of `createBanner()`** |
| `utils.handleCloseButtonClick(event)` | Removes the weblayer and tracks `close`. Bind it: `.onclick = utils.handleCloseButtonClick.bind(utils)` |
| `utils.getEventProperties(action, interactive)` | Event properties with `banner_id`, `banner_name`, `banner_type`, `variant_id`, `variant_name` and `interaction` filled in. **Always use this to track** |
| `utils.trackLink(link, action, interactive)` | Tracks clicks on a link through `self.sdk.trackLink` |
| `utils.validateEmail(email)` | Basic email check |
| `utils.toggleInvalidState(invalid, banner, input, message)` | Shows or clears the browser's validation message on an input |
| `utils.loadStylesheet(href)` | Loads external CSS. Returns a Promise |
| `utils.loadScript(src)` | Loads external JavaScript. Returns a Promise |

## Tracking and identifying

```javascript
const email = input.value.trim().toLowerCase()
const eventProperties = utils.getEventProperties("subscribe")
eventProperties.email = email
self.sdk.track("banner", eventProperties)
self.sdk.identify({ email_id: email })
```

- The `banner` event's `action` is `show`, `click` or `close` for the standard interactions, and `subscribe` for a sign-up. Use `"continue"` for the steps before it in a multi-step weblayer.
- Trim and lowercase the email before you track or identify with it.
- Identify straight after capturing the email address, so later events join the right profile. **Which hard ID to use depends on the project:**
  - `self.sdk.identify(email)` with a plain string sets the default hard ID, `registered`. Only use it if the project stores email addresses in `registered`.
  - `self.sdk.identify({ email_id: email })` sets the `email_id` hard ID. Use the ID the project actually has, and ask the user if you don't know.
  - To set two IDs, pass both in one call, for example `{ registered: ..., email_id: ... }`. Separate calls can create a second profile.
- The `email` on a `subscribe` event is stored on the event only, not as a customer attribute, and `identify` only sets the ID. To save the attribute, also call `self.sdk.update({ email: email })`, or use a scenario triggered on the `subscribe` event.

## Phone input

Custom weblayers with a phone field use intl-tel-input v25. This is how the built-in templates do it; the library isn't in the public docs. The phone number is tracked as the `phone` attribute.

- `utils.registerStartTrigger(true)` loads its CSS and JavaScript from the platform. Alternatively, load them yourself with `utils.loadStylesheet(...)` and `utils.loadScript(...)` in a promise chain before `createBanner()`.
- Initialise: `banner.phoneInput = window.intlTelInput(input, { initialCountry, preferredCountries, loadUtils: () => import("https://cdn.jsdelivr.net/npm/intl-tel-input@25.12.5/build/js/utils.js") })`. `loadUtils` must be an arrow function, not a string.
- Validate with `banner.phoneInput.isValidNumber()`.
- Never put `padding: ... !important` on `.iti input`: it breaks the country flag's position.
