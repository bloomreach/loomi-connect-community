# Data Hub collection checks

What each check in `scripts/datahub_collection_audit.py` looks for, why it matters and who fixes it. Thresholds, word lists and owners are keys in `rules.json`; this file names the key, never its value.

## Shapes the checks read

- **Collections** (`search_item_collections` list): `name`, `_id`, and item types as `types` (`name`, `item_class`, `destinations` grouped as `engagement` and `discovery`) or the older `item_types` (`type`, `relationships`). `destinations: null` means unknown, not empty.
- **Configuration** (`get_item_collection_configuration`): `schema.attributes[]` (`name`, `family`, `level`, `data_type` such as `String`, `Float`, `Boolean`, `List.String`), `schema.identifiers[]` (`family`, `level` and the identifier field), `destinations`, `etag`. One call per item type (`item_type`, default the product type).
- **Fields** (`search_item_collection_fields`, summary mode): fields observed in imports, with `currently_present` (false: in an earlier import, not the latest one) and `examples[]` carrying an inferred `field_data_type`. The script uses the inferred type only, never `field_value`.
- **Records** (`search_item_collection_records`): raw records as dicts; field names follow the schema. Pages hold up to 100 records and are in storage order, so the sample isn't random.
- **System model** (`get_datahub_system_configuration`): the built-in fields (`title`, `price`, `brand` …) allowed for the product item class, so they aren't reported as unconfigured. Custom item classes return an empty list.
- **Jobs** (`search_datahub_jobs`): `type` (`records-update`, `items-update`, `configuration-update`, destination syncs), `state` and timing. For one collection, filter with `resource_type="item-collection"` and `resource_id=<collection name>` (the name, not the UUID).
- **Catalogs** (`search_datahub_catalogs`, project scope): `item_collection_*` fields name the collection and item type that back each catalog; `null` when Data Hub doesn't manage it.

## Checks

| Check | Priority | When | Fix | Owner |
|---|---|---|---|---|
| Required field missing | High | An identifier, or an attribute marked `required` (or `nullable: false`), is filled on fewer than `required_min_fill` of sampled records | Fix the feed | `feed` |
| Field stopped arriving | High (identifier or required) / Medium | `currently_present` is false for a configured field | Find why the feed dropped it | `feed` |
| Key field sparse | Medium | A `key_fields` field that is configured or present in the data is filled on fewer than `key_min_fill` | Send it for every item | `feed` |
| Type mismatch | High (identifier) / Medium | At least `type_mismatch_share` of a field's filled sample values (or, with no sample, import examples) don't match its declared `data_type` via `type_map` | Fix the values, or change the type | `feed` |
| No records | Medium | An item type's records sample is empty | Send it, or remove the type | `feed` |
| Unused field | Low | A configured parent-level attribute is never filled in the sample | Remove it if nothing sends or uses it | `config` |
| Sparse field | Low | A configured attribute is filled on fewer than `sparse_fill` | Fill or remove | `feed` |
| Unconfigured field | Low | A field arrives in the data with no attribute, identifier or system definition | Configure it if it should be used | `config` |
| Configuration drift | High (identifiers) / Medium (attributes added, removed or retyped) / Low (other attribute settings, destinations) | Two paired collections' configurations differ for the same item type | Align the pair or confirm it's intended | `config` |
| Job failing | High (data job) / Medium (other) | The latest job of a type ended in a `failed_states` state | Read the error in Data Hub, fix, re-run | `pipeline` |
| Job failed earlier | Low | Failures followed by a success | Watch for recurrence | `pipeline` |
| No recent records | Medium / Low | The latest successful `data_job_types` job is older than `stale_days`; none succeeded; or (low) no jobs for the collection were read | Check the feed schedule | `feed` |
| Collection without item types | Medium | A collection has no item types | Add one or retire it | `config` |
| Item type feeds nothing | Low | An item type's destinations are all empty | Add a destination or remove it | `config` |
| Catalog without collection | Medium | A Data Hub catalog points at a collection this workspace doesn't have | Relink or retire the catalog | `downstream` |
| Item type without collection | Medium | A catalog expects an item type its collection doesn't have | Recreate the type or relink | `downstream` |
| Collection unused downstream | Low | No catalog links to it and no item type has a destination | Retire it if nothing else reads it | `downstream` |

Variant-level attributes aren't fill-checked from parent records; fetch variant records by `record_id` and `variant_id` if they matter.

## Pairing

Collections are paired automatically when their names match after removing `pair_tokens` (staging, prod, dev, v2 …) and locale-like parts (`locale_pattern`: en, en_us, de-de). The production-looking one is the base. Give pairs explicitly with `--pair A,B`, and turn automatic pairing off with `--no-auto-pair`.

`compare_item_collection_configurations` can also diff two collections server-side: call it with `collection_name` = A, `compare_configuration_id` = `LATEST`, `compare_reference_collection_name` = B and `compare_reference_item_type` = the item type, and pass the result with `--compare A,B=<file>`. It returns a change-list in the shape the write tool takes; this skill only reads it and never applies it. Destination differences aren't in its output, so the script's own configuration diff is still worth running.

## Validating a proposed type change

`validate_item_collection_attribute` checks an attribute **definition** (name, family, level, data type) without writing anything; it doesn't look at record values. Use it only to check a proposed definition before the user changes the type in Data Hub. Never call `update_item_collection_configuration`.
