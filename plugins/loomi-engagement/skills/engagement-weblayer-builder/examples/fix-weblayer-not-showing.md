# Example: fixing a weblayer that doesn't show (illustrative)

**This example is illustrative.** The weblayer name, ID and code are placeholders. No project was changed.

**Prompt:** "Our 'Spring sign-up' weblayer is active but never appears on the site. The console says `Cannot read properties of null (reading 'querySelector')`. Can you fix it?"

---

The assistant resolves the project, finds two weblayers named "Spring sign-up" with `search_banners`, and asks which one. The user picks `<banner_id>`. It reads the source `script` of the only variant, finds the cause, and returns the JavaScript block only, because the HTML and CSS don't change. The script also had old triggering code (a `Trigger` parameter set to "On entry" and a 2-second `ShowDelay`), so that comes out too.

```javascript
let config = {
  PARAM_parentElement: "[[ {name: 'ParentElement', tooltip: 'CSS selector of the parent element', category: 'Layout', orderIndex: '1001', isJsonParam: true} : string | body ]]",
  PARAM_removeAfter: parseInt("[[ {name: 'AutoRemove', tooltip: 'Remove after (ms), 0 = never', category: 'Behavior', orderIndex: '1007', isJsonParam: true} : number | 0 ]]", 10)
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
  const banner = placeholder.querySelector(".su")
  self.banner = banner

  banner.querySelector(".su-close").onclick = utils.handleCloseButtonClick.bind(utils)
  banner.insertAdjacentHTML("afterbegin", "<style>" + self.style + "</style>")
  banner.querySelectorAll("a").forEach((link) => utils.trackLink(link, "click", true))

  const input = banner.querySelector(".su-email")
  banner.querySelector(".su-form").addEventListener("submit", (e) => {
    e.preventDefault()
    const email = input.value.trim().toLowerCase()
    if (!utils.validateEmail(email)) {
      input.classList.add("su-error")
      return
    }
    const eventProperties = utils.getEventProperties("subscribe")
    eventProperties.email = email
    self.sdk.track("banner", eventProperties)
    self.sdk.identify({ email_id: email })
    banner.querySelector(".su-form").hidden = true
    banner.querySelector(".su-thanks").hidden = false
  })

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

**What was wrong:** `createBanner()` found the root with `document.querySelector(".su")`. The weblayer's HTML isn't in the page yet at that point, so it returned `null` and the next line failed (hard rule 2: query from the weblayer, not the document). It now uses `placeholder.querySelector(".su")`. The other parameter values the marketer set are kept.

**Parameters:** removed `Trigger` and `ShowDelay` (Behavior). Their saved values are dropped.

**Smart triggering:** set Total time on page `>=` 2 seconds in the weblayer's **Settings > Smart triggering** to keep the old delay. This needs Web SDK v3.57.0 or later on the site; older versions show the weblayer on page load.

**How to test it:** paste the JavaScript into the weblayer in Bloomreach, check the editor preview, then load the site with the weblayer active for a test audience. The console should show no errors, and a `banner` event with `action: "show"` should be tracked.
