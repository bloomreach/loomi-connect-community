# Test spec format

`scripts/ab_split_plan.py plan --spec <file>` reads one JSON object describing the test. Write it with your file-writing tool; names go in this file, never in a command.

| Field | Required | Meaning |
|---|---|---|
| `test` | yes | `message`, `holdout` or `timing` (below) |
| `scenario_id` | no | The scenario's ID; if given, it must match the `--scenario` file |
| `edge` | yes | The connection the split goes on: `{"from_node": <id>, "from_output": <connector_index>, "to_node": <id>}`, exactly as in the scenario's `connections` |
| `split_name` | yes | The split node's name, for example "A/B: cart reminder discount" |
| `control` | yes | `{"name", "percentage"}`: the branch that keeps today's path (variant `id` 1, output 1) |
| `variant` | yes | `{"name", "percentage"}`: the branch with the change, or the holdout (variant `id` 2, output 2). The two percentages add up to 100, each at least `min_variant_percentage` in [rules.json](rules.json). The names must differ: `engagement-experiment-readout` tells the branches apart by the variant name on the `campaign` split events |
| `timing` | timing only | The variant's wait: `{"units": "minutes|hours|days|weeks", "count": <whole number>}` |
| `copy_name` | no | Only for a running scenario: the name of a new draft copy that gets the split. Without it, a running scenario is blocked |
| `metric` | no | `conversion`, `revenue` or `click`: recorded in the plan for the readout |
| `planned_end` | no | `YYYY-MM-DD`: recorded in the plan for the readout |

## The three tests

**message**: two versions of one message. `to_node` must be a message step (`message_node_types` in rules.json).

```
before:  from_node --(from_output)--> message --> next
after:   from_node --> split --1 (control)--> message --------> next
                             --2 (variant)--> message copy ---> next
```

Variant B is a copy of the control message (same channel, same settings), or the message step given with `--variant-node` (a `search_scenario_nodes` node detail fetched with `include_design=true`, from this or another scenario, same channel). A copy has the same content: the user changes it in Engagement before switching the flow on. The copy's outputs lead where the control message's outputs lead.

**holdout**: the message (or the rest of the flow) against nothing. `to_node` can be any step.

```
after:   from_node --> split --1 (control)--> to_node --> ...
                             --2 (holdout)--> (nothing: the customer leaves the flow)
```

`engagement-experiment-readout` reads a split branch with no outgoing step as a holdout.

**timing**: the same next steps after two different waits. `to_node` must be a `wait-action`.

```
after:   from_node --> split --1 (control)--> wait (as today)  --> next
                             --2 (variant)--> wait (new time)  --> next
```

## What the plan does

- New node IDs follow the highest of `last_node_id` and the existing IDs: the split, then variant B's step. `last_node_id` is the new highest.
- The split node: `{"type": "ab-split", "name", "variants": [{"id": 1, ...}, {"id": 2, ...}], "highest_variant_id_used": 2, "variants_immutable": false, "touched": false}`, the shape seen on saved scenarios (engagement-scenario-builder's `references/node-config.md`). Outputs are numbered by variant `id`; with ids 1 and 2 they are 1 and 2.
- The removed connection is the `edge`; the new ones are listed in the plan's `after.edges_added`.
- New nodes sit below the step they split around; tidy the layout in Engagement if needed.
- Backend-managed fields (`managed_fields`) are removed; existing nodes keep their `id` and `version`. A copied node drops `version`. For a new draft copy, every node drops `version`.

## Blocked when

- the scenario's status isn't in `writable_statuses` (and there's no `copy_name` for a running one);
- any message step has no `design` (fetch again with `include_node_designs=true`);
- the `edge` isn't in the scenario, or `to_node` is the wrong type for the test;
- the shares don't add up to 100, a share is below `min_variant_percentage`, or the names are missing or equal;
- a timing test's wait is the same as today's.

Warnings: a split already in the scenario; a holdout above `max_holdout_percentage`; variant B copied from the control (identical content); variant B taken from another step (check its consent category, sender and personalisation); a new copy of a running flow (stop the old one when the copy goes live).
