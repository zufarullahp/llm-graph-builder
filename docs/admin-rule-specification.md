# Admin Rule Specification

## Section 1 — Overview

What Admin Rules are
- Admin Rules are declarative metadata entries that describe candidate proactive behaviors the system may emit after a user turn. They do not perform actions themselves; instead, they describe: when a proactive behavior is relevant, how to present it (template), and optional hints for policy (priority, cooldown_hint, category).

Role in the proactive engine
- Admin Rules are inputs to the Decision Policy Engine (DPE). The DPE evaluates rules against session state, retrieval context, and guards. If the DPE allows a rule, the Composer generates the follow-up content, and the Controller persists a `RuleInstance` to track the lifecycle.

Where Admin Rules are defined
- Admin Rules are defined as a static list/dictionary in a single source file. Place the canonical definition in a central module so tooling and tests can import it.

How Admin Rules interact with other components
- DPE: Receives rules and applies evaluation logic (eligibility, priority, short-circuit rules).
- Guards: Small, focused checks (e.g., `has_collected_email`) invoked by the DPE to veto or modify a rule decision.
- Composer: Uses the rule's `template_key` and candidate context to generate the final follow-up text.
- RuleInstance lifecycle: The Controller creates a `RuleInstance` when a follow-up is emitted so the system can track WAITING, COMPLETED, or EXPIRED states.

## Section 2 — Anatomy of an Admin Rule

Each Admin Rule is a small dictionary with a fixed set of fields. Keep metadata declarative and side-effect free.

Required and optional fields (semantic):

- `rule_id` (string, required): Unique identifier for the rule (e.g., `ask_email_if_missing`).
- `description` (string, required): Human-friendly summary of the rule's purpose.
- `priority` (integer, optional): Higher values mean higher precedence when multiple rules compete.
- `category` (string, optional): e.g., `data_collection`, `soft_followup`, `clarification`.
- `conditions` (dict / high-level descriptor, required): High-level trigger description used by the DPE. Keep it declarative (e.g., `{'min_turn':1,'requires_context':True}`).
- `template_key` (string, required): Key to map into Composer templates (e.g., `ask_for_email_v1`).
- `cooldown_hint` (string/integer, optional): Suggested cooldown (e.g., `"1_turn"` or minutes) for RuleInstance enforcement.
- `flags` (dict, optional): Additional hints (e.g., `{'ask_only_once': True, 'soft_skip': True}`).

Example (pseudocode only):

```yaml
- rule_id: ask_email_if_missing
  description: Ask the user for their email if none is recorded
  priority: 50
  category: data_collection
  conditions:
    min_turn: 1
    requires_context: true
    only_when: 'session_has_no_email'
  template_key: ask_for_email_v1
  cooldown_hint: '1_turn'
  flags:
    ask_only_once: true
```

## Section 3 — How a Rule Is Evaluated

High-level evaluation flow

1. Controller loads the Admin Rules for the session.
2. For each rule, the Decision Policy Engine (DPE) performs an eligibility check combining:
   - rule metadata (conditions, priority)
   - session state (turn count, existing profile data)
   - retrieval_info and context completeness
   - guard results (e.g., `has_collected_email`)
3. If the DPE returns `ALLOW` for a rule, the Composer generates follow-up text using the rule's `template_key` and available context.
4. The Controller emits the follow-up and persists a `RuleInstance` in the graph with status `WAITING` (or `CREATED`).
5. If the user responds with requested data, the NID handlers parse the response and the Action Layer (e.g., `store_email_and_notify`) persists data, marks `RuleInstance` as `COMPLETED`, and expires sibling `WAITING` instances.

Notes
- Guards should be fast and side-effect free — they only read state to veto rules or provide soft-skip hints.
- RuleInstance lifecycle and cooldown enforcement live outside the Admin Rule metadata (in the Controller / RuleInstance helpers).

## Section 4 — Steps to Add a New Rule

1. Add rule metadata
   - Add a new entry to the admin rules file (the shared list of rule definitions).
2. DPE evaluation
   - Ensure the DPE understands the new rule's `conditions` keys (or add mapping logic to translate the high-level `conditions` to the DPE checks).
3. Add guard logic if needed
   - If the rule requires a new guard (e.g., check external service or specific profile field), add a small guard function and call it from the DPE.
4. Composer template
   - Add a template keyed by `template_key` used by Composer. Keep templates localized and parameterized.
5. RuleInstance handling
   - If the rule uses multi-step flows (pending contact, confirm), ensure Action Layer handlers update `RuleInstance` statuses appropriately.
6. Tests
   - Unit tests: DPE evaluation, guard, Composer template formatting.
   - Integration tests: full path with FakeGraph to validate RuleInstance lifecycle.
7. Telemetry
   - Add logging in Controller/DPE/Composer for rule emissions and decisions.

## Section 5 — Example: Adding a Generic “Every 3 Turns” Follow-up Rule (Pseudocode)

Rule definition (pseudocode):

```yaml
- rule_id: generic_every_3_turns
  description: Minor helpful tip every 3 user turns
  priority: 10
  category: soft_followup
  conditions:
    every_n_turns: 3
    requires_context: false
  template_key: tip_every_3_turns_v1
  cooldown_hint: '3_turns'
```

DPE evaluation pseudocode:

```
if (session.turn_index % rule.conditions.every_n_turns) == 0:
    if not guard_skip(rule, session):
        allow
    else:
        skip
```

Composer template example (pseudocode):

```
"Hey — quick tip to get more from this bot: you can also ask about <featureX>. Want to see examples?"
```

## Section 6 — Best Practices

- Keep rule logic simple and declarative. Avoid embedding heavy logic in the rule metadata.
- One responsibility per rule — do not combine unrelated nudges in the same rule.
- Prefer guards over in-rule boolean checks for cross-cutting vetoes (PII, consent).
- Use cooldowns and idempotency to prevent repeated asks; prefer `soft_skip` messaging when a guard detects partial coverage.
- Always include unit tests for DPE evaluation and Composer templates.
- Document provenance when persisting PII (store `collected_by`, `collected_at` on the Profile node).

## Section 7 — Testing Matrix

Unit tests (fast, FakeGraph)
- Rule eligible → DPE returns `ALLOW`
- Guard returns veto → DPE returns `SKIP`
- DPE soft-skip path (returns `soft_skip`) and Composer uses soft template
- Composer template parameterization correctness
- RuleInstance creation on emission and state transitions (WAITING → COMPLETED → EXPIRED)

Integration tests (graph-backed)
- End-to-end flow: emit rule, user provides data, Action Layer persists Profile, RuleInstance completes, subsequent turns skip rule
- Outbox enqueue + worker for notification actions

Edge cases
- Multiple near-simultaneous emissions: RuleInstance dedup/expiry
- Missing context (Composer should still be resilient)

## Section 8 — Changelog Notes (Template)

When adding or modifying Admin Rules, include an entry in the changelog template below.

```
Date: YYYY-MM-DD
Author: <name>
Rule ID: <rule_id>
Change: added | modified | removed
Summary: One-line summary of the change
Reasoning: Why this change was needed
Testing: Tests added/updated and manual verification steps
Notes: Migration steps, rollout flags, or special considerations
```

---

## Closing

This document is intended to be a clear guide for engineers and product owners to add or adjust Admin Rules safely. Place this file in the repository's `/docs/` folder so it can be reviewed in PRs and referenced during onboarding and rule design.

If you want, I can also:
- add a skeleton `proactive_admin_rules.py` example file with the example rules shown above
- add test templates under `backend/tests/` that mirror the testing matrix

Pick one and I will implement it next.
