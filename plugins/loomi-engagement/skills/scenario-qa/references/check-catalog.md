# Scenario QA flow checks

Apply these checks in step 3 of the skill, after the message checks in `references/message-checks.md`. Report a finding only when the evidence supports it, and list anything you couldn't check under "couldn't verify".

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
