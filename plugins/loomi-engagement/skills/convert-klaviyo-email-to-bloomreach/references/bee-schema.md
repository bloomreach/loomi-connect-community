# BEE template schema (reference)

`scripts/klaviyo_to_bloomreach.py build` generates all of this. Use this file only to debug a push error
or a Visual Builder error. It is extracted from the production-validated `email-to-engagement` schema,
with the corrections below.

## Corrections vs. the original email-to-engagement schema

- **Vouchers:** `{{ vouchers['pool'].assign_available() }}`. `{{ voucher('pool') }}` is invalid.
- **Jinja in BEE:** `href`/`src` stay static in `beefree_template`; live tokens go only in `jinja_html`.
  Visible text tokens (greeting, names) go in both. Control flow (`{% for %}`, `{% if %}`) goes in a
  **custom HTML module** in both.
- **API push shape** (not clipboard): `design.data` carries `beefree_template` (string), `jinja_html`, `subject`,
  `preheader`, `sender_name`, `sender_email`, `reply_to`, `file_ids`, `translations`, `provider`. There is no
  `appVersion` wrapper.

## Custom HTML module (used for Jinja loops/conditionals)

Verified Oct 2026: pushed, opened and saved in the Visual Builder, and the loop rendered in preview.

```json
{"type": "mailup-bee-newsletter-modules-html", "locked": false, "uuid": "<uuid4>",
 "descriptor": {"computedStyle": {"hideContentOnMobile": false},
                "html": {"html": "{% for product in event.product_list %}…{% endfor %}"},
                "style": {"padding-top": "9px", "padding-right": "18px", "padding-bottom": "9px", "padding-left": "18px"}}}
```
No `align` at the module root.

## Other corrections from the Visual Builder round-trip (Oct 2026)

- **Button `computedStyle`:** `{width, widthType: "px", height}`, where `height = font-size × 1.2 + padding-top +
  padding-bottom` (e.g. 24px font, 20px/20px padding → 69) and width ≈ label width + horizontal padding. The builder
  recalculates both on save; "height is always 35" was wrong.
- **Image module:** `image.width`/`image.height` = the file's natural size (e.g. `228px`/`66px`);
  `computedStyle.width` = display width; `percWidth` = display width ÷ column width × 100 (a 170px logo in a 600px
  column → 28). Use `height: "auto"` only when the size is unknown.
- **Heading module:** used for single-heading blocks. `heading.text` = `<span class="tinyMce-placeholder">…</span>`,
  typography in `heading.style`, no root `align`.
- **Web fonts:** `page.body.webFonts: [{"fontFamily": "'Poppins', sans-serif", "name": "Poppins",
  "url": "https://fonts.googleapis.com/css?family=Poppins:300,400,500,600,700,800,900"}]`. Without it, the editor
  strips the font from spans.
- **Line height:** the builder stores percentages (`150%`). Unitless values are converted on save.

## 4: THE `beefree_template` — FULL BEE EDITOR JSON STRUCTURE

The value of `beefree_template` is the JSON.stringify'd version of this object:

```json
{
  "page": {
    "body": {
      "container": {
        "style": { "background-color": "transparent" }
      },
      "content": {
        "computedStyle": {
          "linkColor": "[extracted from source — brand link color, e.g. #140F0F; NOT defaulted to #0000FF]",
          "messageBackgroundColor": "transparent",
          "messageWidth": "[extracted from source — commonly 600px or 620px; match the row content width]"
        },
        "style": {
          "color": "[extracted from source — global text color, often #000000 or brand dark like #140F0F]",
          "font-family": "[extracted from source — global font stack, e.g. Helvetica Neue, Arial, sans-serif]"
        }
      },
      "type": "mailup-bee-page-properties",
      "webFonts": [/* add web font objects here if source email uses Google Fonts or custom fonts */]
    },
    "description": "[human-readable description of email content, e.g. email subject/theme]",
    "title": "[email name — use the email campaign name]",
    "rows": [ /* array of row objects — SEE PART 4a */ ],
    "template": {
      "name": "template-base",
      "type": "basic",
      "version": "2.0.0"
    },
    "title": "[Email Name]"
  },
  "comments": {}
}
```

---

## 4a: ROW OBJECT STRUCTURE

Each visual section of the email becomes one row:

```json
{
  "columns": [ /* array of column objects — SEE PART 4b */ ],
  "container": {
    "style": {
      "background-color": "[extract from HTML — use transparent if none]",
      "background-image": "none",
      "background-position": "top left",
      "background-repeat": "no-repeat"
    }
  },
  "content": {
    "computedStyle": {
      "hideContentOnDesktop": false,
      "hideContentOnMobile": false,
      "rowColStackOnMobile": true,
      "rowReverseColStackOnMobile": false,
      "verticalAlign": "top"
    },
    "style": {
      "background-color": "[extract from HTML — NEVER default to white without checking]",
      "background-image": "none",
      "background-position": "top left",
      "background-repeat": "no-repeat",
      "color": "#000000",
      "width": "[match messageWidth — extracted from source, e.g. 600px or 620px]"
    }
  },
  "empty": false,
  "locked": false,
  "metadata": {
    "_id": "[generate a UUID v4 — format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx]",
    "name": "[descriptive row name e.g. 'Birthday Club Banner']",
    "tags": [],
    "bee_assets_migrated": true,
    "initiative_id": null,
    "is_global_object": false,
    "parentInitiativeId": null
  },
  "synced": false,
  "type": "one-column-empty",
  "uuid": "[generate a UUID v4]"
}
```

**Metadata rules (confirmed from working production references):**
- `metadata._id` must be **UUID v4 format** (`xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx`) — NOT a 24-char hex string
- `metadata` must include all 7 keys: `_id`, `name`, `tags`, `bee_assets_migrated`, `initiative_id`, `is_global_object`, `parentInitiativeId`
- Values: `bee_assets_migrated: true`, `initiative_id: null`, `is_global_object: false`, `parentInitiativeId: null`
- `tags` must be an **array** `[]` — not a string

---

## 4b: COLUMN OBJECT STRUCTURE

```json
{
  "grid-columns": 12,
  "modules": [ /* array of module objects — SEE PART 4c */ ],
  "style": {
    "background-color": "transparent",
    "border-bottom": "0px solid transparent",
    "border-left": "0px solid transparent",
    "border-right": "0px solid transparent",
    "border-top": "0px solid transparent",
    "padding-bottom": "[extracted from source — see rules below]",
    "padding-left": "[extracted from source — see rules below]",
    "padding-right": "[extracted from source — see rules below]",
    "padding-top": "[extracted from source — see rules below]"
  },
  "uuid": "[generate a UUID v4]"
}
```

**Multi-column rows:**
- 2-column layout: set row `"type"` to `"two-columns-6-6-empty"` or `"two-columns-4-8-empty"`, set `"grid-columns"` to `6`/`6` or `4`/`8`
- 3-column layout: set row `"type"` to `"three-columns-empty"`, set `"grid-columns"` to `4` on each column
- 4-column nav: set row `"type"` to `"four-columns-empty"`, set `"grid-columns"` to `3` on each column

**Multi-module columns (confirmed production pattern):**
A single column can contain multiple modules stacked vertically — e.g. an image module followed
by a text module in the same column. This is the correct approach for product cards with a
caption, or image+link-text combinations. Simply add both module objects to the column's
`modules` array in order (top to bottom). Example: a 2-up row where each column has an image
module (product photo) and a text module (product name/link below it):
```json
"modules": [
  { "type": "mailup-bee-newsletter-modules-image", ... },
  { "type": "mailup-bee-newsletter-modules-text", ... }
]
```

**⚠️ COLUMN PADDING EXTRACTION RULES — padding is the #1 layout fidelity issue:**

Column `style` padding controls two distinct visual properties:
- `padding-left` / `padding-right` → **horizontal gutter between adjacent columns** (e.g. gap between left and right images in a 2×2 grid)
- `padding-top` / `padding-bottom` → **vertical spacing between rows of content**

**How to extract column padding from source HTML:**

1. Find the `<td>` elements that correspond to each column in the source email table layout
2. Extract `padding`, `padding-left`, `padding-right`, `padding-top`, `padding-bottom` from the `<td>` `style=` attribute or `cellpadding` on the parent `<table>`
3. Also check `<style>` block classes applied to those `<td>` elements
4. Map source `<td>` padding directly to column `style` padding values

**Default values when nothing is found in source (use these, not hardcoded guesses):**
- Single-column rows: `padding-left: "0px"`, `padding-right: "0px"`, `padding-top: "0px"`, `padding-bottom: "0px"`
- Multi-column rows (gutters): `padding-left: "5px"`, `padding-right: "5px"` for interior columns; outer columns keep `0px` on their outer edge
- Never default top/bottom to `5px` unless the source has visible vertical spacing between rows

**Multi-column gutter rules — critical for image grids:**

The gutter between two adjacent columns comes from the INNER edges only:
- Left column: `padding-right: "[half the gutter width]"`, `padding-left: "0px"`
- Right column: `padding-left: "[half the gutter width]"`, `padding-right: "0px"`

Example — source HTML has `<td style="padding:0 8px">` on each cell in a 2-col grid:
```json
// Left column
"style": { "padding-left": "0px", "padding-right": "8px", "padding-top": "0px", "padding-bottom": "0px" }
// Right column  
"style": { "padding-left": "8px", "padding-right": "0px", "padding-top": "0px", "padding-bottom": "0px" }
```

Example — source has `<table cellspacing="10">` with no `<td>` padding:
→ Use `padding-left: "5px"` and `padding-right: "5px"` on each column (half of cellspacing on each side)

Example — source images are flush/borderless with no spacing:
→ Use `padding-left: "0px"` and `padding-right: "0px"` on all columns — do NOT add a default gutter

**Row-to-row vertical spacing:**

Vertical spacing between rows comes from THREE sources — extract all three:
1. **Column `padding-top` / `padding-bottom`**: from the source `<td>` vertical padding
2. **Module `descriptor.style.padding-top` / `padding-bottom`**: from padding on the content element inside the `<td>` (e.g. the `<img>` wrapper or text container)
3. **Spacer rows**: if the source has an explicit spacer `<tr>` or `<td height="N">`, create a BEE spacer module with that height instead of inflating column padding

When source rows are flush (no visible gap between them):
→ Column: `padding-top: "0px"`, `padding-bottom: "0px"` AND module: `padding-top: "0px"`, `padding-bottom: "0px"`
→ Do NOT add `5px` defaults — they accumulate across multiple rows and create visible gaps that weren't in the original

---

## 4c: MODULE TYPES — COMPLETE VALIDATED SCHEMAS

### ⚠️ CRITICAL MODULE RULES (confirmed from production):

1. **`"align": "left"` at the module root level**: ONLY on `image`, `text`, `paragraph`, `button`, `social` modules. NEVER on `spacer`, `divider`, or `heading` modules.
2. **Text module HTML**: MUST be wrapped in `<div class="txtTinyMce-wrapper" style="..." data-mce-style="...">`. Without this wrapper, BEE's TinyMCE editor refuses to load and throws a 400 error.
3. **`data-mce-style` mirroring**: Every `style="X"` attribute inside text/paragraph HTML must have a matching `data-mce-style="X"` attribute on the SAME element. The BEE multiparser uses `data-mce-style` to generate Outlook-compatible HTML and throws 422 without it.

---

### IMAGE MODULE
```json
{
  "type": "mailup-bee-newsletter-modules-image",
  "locked": false,
  "uuid": "[UUID v4]",
  "align": "left",
  "descriptor": {
    "computedStyle": {
      "class": "center fixedwidth",
      "width": "[display width e.g. 600px]"
    },
    "image": {
      "alt": "[alt text from HTML]",
      "href": "[link URL or empty string]",
      "src": "[image URL — verbatim from HTML src attribute]",
      "dynamicSrc": "[ONLY include when this image slot is powered by a rec model — see note below]",
      "target": "_blank",
      "width": "[natural width]",
      "height": "[actual pixel height of source image, e.g. \"686px\", \"2160px\" — use real dimensions from source; the jinja_html <img> tag uses height=\"auto\" but the BEE JSON descriptor uses actual pixel dimensions]",
      "prefix": "",
      "percWidth": [100 for full-width single-column images; 94 for 2-up (two-column) images; 96 for 3-up (three-column) images]
    },
    "style": {
      "padding-bottom": "[extracted from source — default 0px for images, never add padding that isn't in source]",
      "padding-left": "[extracted from source — default 0px]",
      "padding-right": "[extracted from source — default 0px]",
      "padding-top": "[extracted from source — default 0px for images]",
      "width": "100%"
    }
  }
}
```

**Image rules:**
- `percWidth` must be a number (not a string)
- Every image-only section in the source HTML (banners, GIFs, product images, icon rows, barcode images, category buttons) MUST become its own image module row — never skip these
- Image module `descriptor.style` padding should default to `0px` on all sides — images are flush by default. Only add padding if the source `<img>` or its wrapper `<td>` explicitly has it.
- Do NOT use image module padding to create column gutters — gutter belongs in column `style` padding
- **`percWidth` by column count (confirmed production values):**
  - Full-width / one-column: `percWidth: 100`
  - 2-up / two-columns: `percWidth: 94` (leaves ~3% breathing room each side)
  - 3-up / three-columns: `percWidth: 96`
  - 4-up / four-columns: `percWidth: 94`
  - `computedStyle.width` should reflect the actual rendered pixel width after percWidth is applied (e.g. 620px × 0.96 ≈ 595px → use `"595px"` or the nearest whole number)

**`dynamicSrc` — recommendation-powered image slots (confirmed production pattern):**

When an image module slot is powered by a Bloomreach recommendation engine, add `dynamicSrc`
alongside `src` in the `beefree_template`. The `src` remains a real static product image
as a preview fallback; `dynamicSrc` holds the Jinja token:

```json
"image": {
  "src": "https://[static-product-image-url]",
  "dynamicSrc": "{{ recommendations('<model_id>')[N].image }}",
  "href": "[static product URL — NOT replaced with rec URL]",
  "alt": "[product name]",
  "width": "1800px",
  "height": "2160px",
  "percWidth": 96,
  "prefix": "",
  "target": "_blank"
}
```

Key rules for `dynamicSrc`:
- Syntax is `recommendations()` (plural) with array index `[N]`, accessing `.image` field
- Index `N` starts at 0 for the first product slot and increments by 1 per slot
- `href` is NEVER replaced with a dynamic rec URL — it stays as the static URL from source
- `src` stays as a real product image URL for BEE editor preview — not a placeholder string
- In `jinja_html`, the `<img src="...">` attribute is replaced with `{{ recommendations('model_id')[N].image }}` directly — `dynamicSrc` is a BEE editor field only, it does not appear in `jinja_html`
- Omit `dynamicSrc` entirely for non-rec image modules (logos, hero banners, static images)

---

### TEXT MODULE
```json
{
  "type": "mailup-bee-newsletter-modules-text",
  "locked": false,
  "uuid": "[UUID v4]",
  "align": "left",
  "descriptor": {
    "computedStyle": { "hideContentOnMobile": false },
    "style": {
      "padding-bottom": "[extracted or 10px]",
      "padding-left": "[extracted or 10px]",
      "padding-right": "[extracted or 10px]",
      "padding-top": "[extracted or 10px]"
    },
    "text": {
      "computedStyle": { "linkColor": "[extracted link color or #0000FF]" },
      "html": "<div class=\"txtTinyMce-wrapper\" style=\"font-size:[extracted]px;font-family:[extracted];font-weight:[extracted];line-height:[extracted];\" data-mce-style=\"font-size:[extracted]px;font-family:[extracted];font-weight:[extracted];line-height:[extracted];\"><p style=\"font-size:[extracted]px;line-height:[extracted];word-break:break-word;text-align:[extracted];font-weight:[extracted];\" data-mce-style=\"font-size:[extracted]px;line-height:[extracted];word-break:break-word;text-align:[extracted];font-weight:[extracted];\"><span style=\"color:[extracted];font-weight:[extracted];\" data-mce-style=\"color:[extracted];font-weight:[extracted];\">[content]</span></p></div>",
      "style": {
        "color": "[extracted from source]",
        "font-family": "[extracted from source]",
        "font-weight": "[extracted from source — default 400 if not found, never default 700]",
        "line-height": "[extracted from source — e.g. 150%, 1.5]"
      }
    }
  }
}
```

**⚠️ TEXT MODULE FONT EXTRACTION RULES:**
- Extract `font-weight` from the source `<td>`, `<p>`, `<span>`, or `<div>` — whichever is most specific.
- Include `font-weight` in ALL THREE places it appears: `descriptor.text.style`, the `txtTinyMce-wrapper` div style, and each inner `<p>`/`<span>` style (with matching `data-mce-style`).
- If no font-weight found in source: use `400` as default, never `700`.
- Extract `font-family` faithfully — if the source uses a web font (e.g. `'Helvetica Neue', Helvetica, Arial`) preserve the full stack.
- `letter-spacing`, `text-transform`, `font-style` (italic) should also be extracted if present and included in both the `style=` and `data-mce-style=` attributes.

---

### BUTTON MODULE
```json
{
  "type": "mailup-bee-newsletter-modules-button",
  "locked": false,
  "uuid": "[UUID v4]",
  "align": "left",
  "descriptor": {
    "button": {
      "label": "<div class=\"txtTinyMce-wrapper\" style=\"\" data-mce-style=\"\"><p style=\"word-break:break-word;\"><span class=\"tinyMce-placeholder\" style=\"\" data-mce-style=\"\">[Button Text]</span></p></div>",
      "style": {
        "background-color": "[extracted BG color]",
        "border-bottom": "0px solid transparent",
        "border-left": "0px solid transparent",
        "border-radius": "4px",
        "border-right": "0px solid transparent",
        "border-top": "0px solid transparent",
        "color": "[extracted text color]",
        "direction": "ltr",
        "font-family": "Arial, Helvetica Neue, Helvetica, sans-serif",
        "font-size": "16px",
        "font-weight": "[extracted from source — default 400 if not found, never default 700]",
        "letter-spacing": "1px",
        "line-height": "120%",
        "padding-bottom": "12px",
        "padding-left": "20px",
        "padding-right": "20px",
        "padding-top": "12px",
        "text-align": "center",
        "width": "auto"
      },
      "target": "_self"
    },
    "computedStyle": {
      "width": 200,
      "widthType": "px",
      "height": 35
    },
    "href": {
      "name": "[button link URL]",
      "target": "_blank",
      "type": "web"
    },
    "style": {
      "padding-bottom": "20px",
      "padding-left": "10px",
      "padding-right": "10px",
      "padding-top": "15px",
      "text-align": "center"
    }
  }
}
```

**⚠️ BUTTON NOTES (confirmed working):**
- `href` is a **sibling of `button` inside `descriptor`** — as shown in the schema above. Do NOT nest `href` inside the `button` object.
- `computedStyle` must have shape `{width: N, widthType: "px", height: N}` — height = font-size × 1.2 + vertical padding (see corrections at the top), width ≈ label width + horizontal padding. Do NOT use `{height, hideContentOnMobile, width}` format.
- Button label HTML MUST use the `txtTinyMce-wrapper` div with matching `data-mce-style` — same rule as text modules.
- `"target": "_self"` lives inside the `button` object; `"target": "_blank"` lives inside `href`.
- Missing or wrong `computedStyle` shape on button → `bee-multiparser 422`.
- `href` nested inside `button` instead of as a sibling → `bee-multiparser 422`.

---

### DIVIDER MODULE
```json
{
  "type": "mailup-bee-newsletter-modules-divider",
  "locked": false,
  "uuid": "[UUID v4]",
  "descriptor": {
    "computedStyle": { "align": "center", "hideContentOnMobile": false },
    "divider": { "style": { "border-top": "1px solid #BBBBBB", "width": "100%" } },
    "style": {
      "padding-bottom": "10px",
      "padding-left": "10px",
      "padding-right": "10px",
      "padding-top": "10px"
    }
  }
}
```
**Note: NO `"align"` at module root level for dividers.**

---

### SPACER MODULE
```json
{
  "type": "mailup-bee-newsletter-modules-spacer",
  "locked": false,
  "uuid": "[UUID v4]",
  "descriptor": {
    "computedStyle": { "hideContentOnMobile": false },
    "spacer": { "style": { "height": "20px" } }
  }
}
```
**Note: NO `"align"` at module root level for spacers.**

---

### HEADING MODULE
```json
{
  "type": "mailup-bee-newsletter-modules-heading",
  "locked": false,
  "uuid": "[UUID v4]",
  "descriptor": {
    "computedStyle": {
      "hideContentOnDesktop": false,
      "hideContentOnMobile": false
    },
    "heading": {
      "title": "[h1/h2/h3 — match heading level from source HTML]",
      "text": "<span class=\"tinyMce-placeholder\">[heading text]</span>",
      "style": {
        "color": "[extracted from source — e.g. #000000]",
        "direction": "ltr",
        "font-family": "[extracted from source — e.g. Georgia, serif]",
        "font-size": "[extracted from source — e.g. 28px]",
        "font-weight": "[extracted from source — e.g. 300, 400, 500, 600, 700, or normal/bold]",
        "letter-spacing": "[extracted from source — e.g. 0px, 1px, -0.5px]",
        "line-height": "[extracted from source — e.g. 120%, 1.2]",
        "link-color": "#0000FF",
        "text-align": "[extracted from source — left/center/right]",
        "text-transform": "[extracted from source — none/uppercase/lowercase — omit if not set]"
      }
    },
    "style": {
      "padding-bottom": "[extracted or 10px]",
      "padding-left": "[extracted or 0px]",
      "padding-right": "[extracted or 0px]",
      "padding-top": "[extracted or 10px]",
      "text-align": "[extracted from source]",
      "width": "100%"
    }
  }
}
```

**⚠️ HEADING FONT EXTRACTION RULES — font-weight is the #1 fidelity issue:**
- NEVER default `font-weight` to `700` or `bold`. Always extract from the source HTML.
- Thin/light headings use `font-weight: 300` or `font-weight: 400` — these are common in modern brand emails.
- Check `font-weight` on: the `<h1>`/`<h2>`/`<h3>` tag itself, any wrapping `<td>`, the parent `<table>`, and any inline `<span>` or `<div>` inside the heading.
- If font-weight is set in a `<style>` block in the `<head>`, extract it from there.
- If no font-weight is found anywhere in the source for that element: use `400` (normal) as the safe default — NOT `700`.
- Same rule applies to `font-family`: extract from source. Do not default to Arial if the source uses a different font.
- `letter-spacing` significantly affects how "heavy" text feels — extract it faithfully (negative values create tighter, more elegant type; positive values create lighter, more spaced type).

**Note: NO `"align"` at module root level for headings.**

**Heading level (`title`) assignment:**
- Assign h-levels based on **visual hierarchy and font size**, NOT DOM order in the source HTML
- The largest/most prominent heading → `h1` or `h2`
- Section headings → `h3` or `h4`
- Sub-labels → `h5` or `h6`
- H-levels in a single email do not need to be sequential (h2 → h4 → h3 is valid if it reflects visual weight)
- Never default all headings to `h2` — inspect the source and assign levels by prominence

---

### SOCIAL MODULE
```json
{
  "type": "mailup-bee-newsletter-modules-social",
  "locked": false,
  "uuid": "[UUID v4]",
  "align": "left",
  "descriptor": {
    "computedStyle": {
      "height": 32,
      "hideContentOnMobile": false,
      "iconsDefaultWidth": 32,
      "padding": "0 2.5px 0 2.5px",
      "width": 120
    },
    "iconsList": {
      "icons": [
        {
          "id": "[UUID v4]",
          "name": "Facebook",
          "type": "follow",
          "text": "",
          "image": {
            "alt": "Facebook",
            "href": "[extracted URL]",
            "prefix": "https://www.facebook.com/",
            "src": "https://app-rsrc.getbee.io/public/resources/social-networks-icon-sets/t-only-logo-dark-gray/facebook@2x.png",
            "target": "_self",
            "title": "Facebook"
          }
        }
      ]
    },
    "style": {
      "padding-bottom": "10px",
      "padding-left": "10px",
      "padding-right": "10px",
      "padding-top": "10px",
      "text-align": "center"
    }
  }
}
```

## Failure modes
All 12 failure modes confirmed against a live Bloomreach Engagement instance:

| Symptom | Root Cause | Fix |
|---|---|---|
| Email body is **completely blank** when opened | `design.type: "beefree"` missing | Add `"type": "beefree"` as direct child of `design` object |
| Email node **pastes but is not savable** | `design` object has extra keys beyond `type` and `data` | Remove `file_ids`, `jinja_html`, `preheader`, `provider`, `reply_to`, `sender_email`, `sender_name`, `subject`, `translations` from `design` — working JSONs have ONLY `type` and `data` |
| `bee-bumper 400` on open | Text module HTML missing `txtTinyMce-wrapper` div | Wrap ALL text HTML in `<div class="txtTinyMce-wrapper" style="..." data-mce-style="...">` |
| `bee-bumper 400` on open | `"align": "left"` on Heading, Spacer, or Divider module | Remove `align` from root of Heading, Spacer, Divider modules — only Image, Text, Paragraph, Button, Social get `"align": "left"` |
| `bee-multiparser 422` on save | `data-mce-style` missing from inline styles in text HTML | Every `style="X"` in text HTML needs matching `data-mce-style="X"` on same element |
| `bee-multiparser 422` on save | Button `href` nested inside `button` object | Move `href` to be a sibling of `button` inside `descriptor` |
| `bee-multiparser 422` on save | Button `computedStyle` has wrong shape | Must be `{width: N, widthType: "px", height: N}` — see the button formula at the top. Not `{hideContentOnMobile, align}` |
| `bee-multiparser 422` on save | `"align": "left"` on Spacer module | Remove `align` from Spacer modules entirely |
| `bee-multiparser 422` on save | `beefree_template` is a raw object, not a string | JSON.stringify the template object — all internal quotes must be `\"` |
| Node pastes but **disappears on save** | Missing required node-level fields | Verify all 25 fields from Part 2 are present |
| **Sections missing** from output | Image-only rows skipped during HTML parsing | Every `<img>` that is full-width or standalone MUST become an image module row |
| **Wrong sections** shown | Gmail proxy URLs used instead of real image URLs | Extract real URL from after `#` in `ci3.googleusercontent.com/meips/...#https://realurl.com/image.jpg` |
| `Canvas2D: willReadFrequently` warning | BEE canvas performance warning | Ignore — this is a browser-level warning unrelated to your JSON |
| **"incompatible app version"** error on paste | `appVersion` in JSON does not match the Bloomreach instance version | Error message format: "nodes have incompatible app version [JSON] and [INSTANCE]". Use the **second** version string (the instance version) as the new `appVersion` value and regenerate |
| `bee-multiparser 422` | `descriptor.text` is a plain string or missing `style`/`computedStyle` keys | `descriptor.text` must be an object: `{html, style, computedStyle}` — never a plain string |
| `bee-bumper 400` + "0Row" canvas label | `empty`/`locked`/`synced` set as integers (`0`/`1`) instead of booleans | Use `false` (boolean) not `0` (integer) for these row fields |
| `bee-bumper 400` | Row `type` set to `"row-1-columns-12"` format | Use `"one-column-empty"` / `"three-columns-empty"` / `"two-columns-6-6-empty"` |
| Email body **completely blank** after paste | `beefree_template` populated with BeeFree Simple Schema instead of full BEE editor JSON | `beefree_template` must always be full BEE JSON (with `page.body`, `page.rows[]`, full module `descriptor` objects) — never use BeeFree Simple Schema |
| `bee-multiparser 400` (text block worker error 4211) | `mobileStyle: {}` added to module descriptors | Remove `mobileStyle` from all module descriptors — not supported in Bloomreach's BEE integration |
| **Email preview spins indefinitely** | `bee-multiparser 422` firing on preview render (same root causes as save-time 422, but triggered earlier) | Fix all 422 causes: `data-mce-style` pairing on every `style=`, correct `descriptor.text` object shape, correct button `computedStyle`, `href` as sibling not nested. Preview uses the same multiparser endpoint as save. |
| `bee-multiparser 422` on preview or save | `href` nested inside `button` object instead of as sibling in `descriptor` | Move `href` out of `button` to be a direct sibling: `descriptor: { button: {...}, href: {...}, computedStyle: {...}, style: {...} }` |
| `bee-multiparser 422` on preview or save | Button `computedStyle` wrong shape | Must be `{"width": N, "widthType": "px", "height": N}` — see the button formula at the top. Not `{height, hideContentOnMobile, width}` |
| `bee-multiparser 422` on preview or save | `data-mce-style` missing on ANY styled element inside text/button HTML | Every single `style="X"` attribute — including on `<td>`, `<span>`, `<p>`, `<a>`, wrapper divs, button label divs — needs a matching `data-mce-style="X"` on the same element. This is the most common cause of the spinning preview. |
| `bee-multiparser 422` on preview or save | Jinja inside BEE `href`/`src` fields, or control flow inside a text module | Keep `href`/`src` static in `beefree_template` (tokens only in `jinja_html`). Visible text tokens such as the greeting may appear in BEE text modules. Put `{% for %}`/`{% if %}` blocks in a custom HTML module. |
| **Images in multi-column grid touching each other (no gutter)** | Column `padding-left`/`padding-right` both `0px` — no inter-column gutter set | Extract horizontal `<td>` padding from source. Split across inner edges: left column gets `padding-right`, right column gets `padding-left`. Outer edges stay `0px`. |
| **Too much vertical space between rows vs. source** | Column padding defaulted to `5px` top/bottom AND module padding defaulted to `10px`, stacking to 30px+ per row boundary | Set column `padding-top`/`padding-bottom` to `0px` for flush rows. Set image module `descriptor.style` padding to `0px`. Only use non-zero values when source has explicit vertical spacing. |
| **`[First Name]` or bracket placeholder in sent email** | Placeholder detected in Step 1 but never replaced in `jinja_html` — detection without injection | Every bracket placeholder and ESP merge tag found in the source MUST be replaced in `jinja_html`. Run pre-output scan: search for `[`, `%%`, `*|`, `@WORD@` before generating final JSON. `[First Name]` is valid ONLY in `beefree_template` as a preview stand-in — never in `jinja_html`. |
| **Layout spacing doesn't match source** | Padding extracted at wrong layer — module padding used where column padding was needed, or vice versa | Column padding = `<td>` level spacing. Module padding = inner content spacing. Extract each from its correct HTML counterpart. |
| **Product grid shows static content, no recs injected** | `dynamicSrc` set in `beefree_template` but `jinja_html` `<img src>` not updated, OR token missing entirely | In `jinja_html` each `<img src="static-url">` must be replaced with `<img src="{{ recommendations('model_id')[N].image }}">`. The `dynamicSrc` in `beefree_template` is a BEE editor preview field only — it does NOT automatically populate `jinja_html`. Both must be set independently. |
| **All 6 product grid images show the same item** | Every image module using index `[0]` instead of `[0]`–`[5]` | Each slot needs a unique index: `[0]`, `[1]`, `[2]`, `[3]`, `[4]`, `[5]`. Verify both `dynamicSrc` in `beefree_template` and `<img src>` in `jinja_html`. |
| **Wrong rec syntax used** | Singular `recommendation()` with `{% for %}` loop instead of plural `recommendations()[N]` | Correct email rec syntax is `recommendations('model_id')[N].image` — plural, array-indexed, no loop. The `{% for item in recommendation() %}` loop pattern does not apply to image-only BEE grids. |
