# Example report (synthetic data)

**Prompt:** "Clean up our Discovery banners for the Acme account."

---

**7 assets: 3 live, 1 used only by disabled or expired rules, 3 unused (unverified: 1 rule not fetched). 2 problems on live pages.**

### Fix now (live pages)

| # | Severity | Asset or rule | Problem | Fix |
|---|---|---|---|---|
| 1 | High | Rule "Dress hero" (2001) | Uses asset 9999, which isn't in the library | Pick a current asset, or retire the rule |
| 2 | High | Rule "Dress hero" (2001) | Grid slot 7 used by "Partner tile" and "Hero copy" | Move "Hero copy" to a free slot |
| 3 | Medium | Rule "Dress hero" (2001) | Placement in slot 80 (slots go up to 72) | Use a slot in range |
| 4 | Medium | Asset "Partner tile" (1002) | Image on `http://images.partner.test/…` | Re-upload over https |
| 5 | Medium | Asset "Hero copy" (1006) | Switched off, but "Dress hero" uses it | Switch it on, or remove it from the rule |

### Safe to delete (after fetching rule 2004 in detail)

- "Note text" (1003): a banner URL asset holding plain text, last changed 2023-11-14.
- "Countdown" (1005): weblayer targeting `yourdomain.com`.
- "Broken" (1007): content can't be read.
- "HTML promo" (1004): used only by the disabled "Old promo" and the expired "Summer"; delete those rules first (`discovery-rule-audit`).

### Tidy up

- "Partner tile" (1002) is hot-linked from a partner site; upload it.
- "Autumn hero" (1001) and "Hero copy" (1006) use the same image; keep one.
- "Autumn hero" (1001) has a hotspot link with no alt text.

### Not checked

- Rule 2004 wasn't fetched in detail, so "unused" can't be confirmed yet.
- "Dress hero" has 2 A/B variants; only one was returned.
- Links: 3 loaded, all 200.
