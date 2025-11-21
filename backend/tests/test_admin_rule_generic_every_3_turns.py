from src.proactive_admin_rules import load_proactive_rules_for_tenant


def test_generic_every_3_turns_rule_present_and_shaped_correctly():
    # Load default (global) rules
    rules = load_proactive_rules_for_tenant(None)

    # Find rule by id (module uses "id" field)
    found = None
    for r in rules:
        if r.get("id") == "generic_every_3_turns":
            found = r
            break

    assert found is not None, "generic_every_3_turns rule must be present in admin rules"

    # Validate critical fields
    assert found.get("id") == "generic_every_3_turns"
    assert found.get("category") == "soft_followup"
    assert found.get("template_key") == "tip_every_3_turns_v1"

    conditions = found.get("conditions") or {}
    assert conditions.get("every_n_turns") == 3
    assert conditions.get("requires_context") is False

    flags = found.get("flags") or {}
    assert flags.get("soft_skip") is True


def test_evaluate_admin_rules_every_n_turns():
    from src.proactive_admin_rules import evaluate_admin_rules

    # Minimal rule list (avoid global DEFAULT rules)
    generic_rule = {
        "id": "generic_every_3_turns",
        "name": "Every 3 turns helpful tip",
        "active": True,
        "event": "AFTER_ANSWER",
        "priority": 10,
        "category": "soft_followup",
        "conditions": {"every_n_turns": 3, "requires_context": False},
        "template_key": "tip_every_3_turns_v1",
        "flags": {"soft_skip": True},
    }

    # turn 0 -> skip
    session_state = {"turnCount": 0}
    runtime_context = {"event": "AFTER_ANSWER"}
    assert evaluate_admin_rules(session_state, runtime_context, [generic_rule]) is None

    # turn 1 -> not a multiple of 3 -> skip
    session_state["turnCount"] = 1
    assert evaluate_admin_rules(session_state, runtime_context, [generic_rule]) is None

    # turn 3 -> multiple of 3 -> should select rule
    session_state["turnCount"] = 3
    selected = evaluate_admin_rules(session_state, runtime_context, [generic_rule])
    assert selected is not None and selected.get("id") == "generic_every_3_turns"

    # turn 6 -> also multiple of 3 -> should select rule
    session_state["turnCount"] = 6
    selected = evaluate_admin_rules(session_state, runtime_context, [generic_rule])
    assert selected is not None and selected.get("id") == "generic_every_3_turns"
