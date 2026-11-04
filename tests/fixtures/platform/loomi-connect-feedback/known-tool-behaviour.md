# Loomi Connect tool behaviour

## General

- A general note with no marker.

## Discovery

**Query performance** (`get_discovery_query_performance`)
- `get_discovery_category_performance_table` with `filter_preset="lowest_converting"` returns 0 rows. **(bug?)**
- `get_discovery_trend` leaves out days with no data.
- A rule list shows `audienceName: null`. **(bug?)**

## Engagement

- `create_email_campaign` always creates a draft.
  - Its description says one thing, the guide another. **(bug?)** Use the inline form.
- Something about `search_scenarios` that isn't marked.
