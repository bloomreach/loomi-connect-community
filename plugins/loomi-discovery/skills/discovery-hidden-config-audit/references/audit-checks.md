# Hidden configuration checks

What each check means, its priority and the fix. `scripts/hidden_config_audit.py` runs them, with thresholds and word lists from [rules.json](rules.json); apply them by hand if the script can't run. Report a finding only when the evidence supports it.

## How audiences match

An audience is a set of dimensions (`url`, `ref_url`, `geo`, `device`, or an Engagement segmentation). Each dimension has one or more values, each with a match type: IS (`EXACT_MATCH`), CONTAINS (`CONTAIN_MATCH`) or IS NOT. The checks treat values in one dimension as alternatives (any one matches) and different dimensions as all required. URL values are matched against the page URL or referral URL as the browser sends it, so spaces and accented characters arrive percent-encoded.

## Audiences

| Check | Priority |
|---|---|
| Can't match (a URL value with a leading or trailing space or a space inside, an empty value, no conditions, or IS and IS NOT the same value) and enabled rules use it | **High**: those rules never fire, or fire for everyone |
| Can't match, rules use it, but none were traced | **High** |
| Can't match and nothing uses it | **Low** |
| Identical conditions to another audience, and more than one is in use | **High**: rules for the same shoppers are split across two audiences |
| Identical conditions, only one in use | **Low** the unused copies |
| Unused (`rulesAffected` 0) and older than `unused_min_age_days` | **Low** (test-like names first) |
| Unused and newer than `unused_min_age_days` | **Medium**: it may be about to be used |
| In use, but every traced rule is disabled or expired | **Low** the rules and the audience, or re-enable what's wanted |
| A CONTAINS value shorter than `min_contains_chars` on a URL dimension | **Medium**: "ZZ" also matches "/buzz" |
| A URL value starting with `&` | **Medium**: it misses URLs where that parameter comes first, after `?` |
| A URL value with accented characters | **Medium**: the URL carries them percent-encoded |
| One audience's CONTAINS value is inside another's value | **Medium**: "gold" also catches every "gold_tier" visitor |
| A pair where one is IS X and the other IS NOT X | Fine: that's a deliberate split |
| Depends on an Engagement segmentation | **Couldn't verify** from Discovery; check it in Engagement |

Names containing a protected phrase ("do not delete") are listed as **protected** and never recommended for deletion.

## Personalised rules

Rule lists show `audienceName: null` even for targeted rules, so the steps trace each audience with the lists' `audience_ids` filter. The script returns the map of rule → queries → audience. Two rules on the same query with different audiences are personalisation, not duplicates: hand the map to `discovery-rule-audit`. `rulesAffected` also counts facet rules and redirects, which the lists can't filter by audience; the script reports any gap.

## API parameter overrides

| Check | Priority |
|---|---|
| Enabled but `durationTag` is expired | **High**: disable it |
| Enabled override of a parameter in `override_high_params` (`q`, `request_type`, `search_type`, debug parameters) | **High** |
| The same parameter overridden by more than one enabled override | **High**: keep one |
| Enabled override of a parameter in `override_medium_params` (`sort`, `fq`, `efq`, `rows`, `start`, `fl`, facet settings, `view_id`, `widget_id`) | **Medium**: confirm it's still wanted. A `sort` override can leave ranking rules with no effect; an `fq` or `efq` override hides products from every matching search |
| Enabled, no name, unchanged for `stale_days` | **Medium**: name it or remove it |
| The parameters can't be read from the record | **Medium** in the dashboard |
| Disabled and unchanged for `stale_days` | **Low** |

An override with no queries, or the query `*`, applies to every search and category request; the evidence says which.
