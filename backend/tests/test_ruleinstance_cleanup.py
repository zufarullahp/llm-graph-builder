import json
from datetime import datetime

from src.rule_instance import create_rule_instance, get_active_rule_instances
from src.proactive_actions import store_email_and_notify


def test_reuse_rule_instance(fake_graph):
    graph = fake_graph
    session_id = "sess-reuse-1"
    rule_id = "ask_email_if_missing"

    # First creation
    id1 = create_rule_instance(graph, session_id, rule_id, asked_at_turn=1)
    # Second creation attempt should return the same id (reuse)
    id2 = create_rule_instance(graph, session_id, rule_id, asked_at_turn=2)

    assert id1 == id2

    # Ensure there's only one active WAITING instance for this rule/session
    active = get_active_rule_instances(graph, session_id)
    matching = [r for r in active if r.get("rule_id") == rule_id]
    assert len(matching) == 1


def test_sibling_cleanup_on_store_email(fake_graph):
    graph = fake_graph
    session_id = "sess-cleanup-1"
    rule_id = "ask_email_if_missing"

    # Simulate existing dangling WAITING instances (old data)
    graph.rule_instances.clear()
    graph.rule_instances.append({
        "id": "ri-old-1",
        "rule_id": rule_id,
        "status": "WAITING",
        "asked_at_turn": 1,
        "metadata": {},
    })
    graph.rule_instances.append({
        "id": "ri-old-2",
        "rule_id": rule_id,
        "status": "WAITING",
        "asked_at_turn": 2,
        "metadata": {},
    })
    # Primary RuleInstance that will be completed
    graph.rule_instances.append({
        "id": "ri-primary",
        "rule_id": rule_id,
        "status": "WAITING",
        "asked_at_turn": 3,
        "metadata": {},
    })

    # Call the action with the primary rule instance
    primary = {"id": "ri-primary", "rule_id": rule_id, "asked_at_turn": 3}
    result = store_email_and_notify(graph, session_id, {"email": "user@example.com"}, primary)

    # action should report success
    assert result.get("ok") is True

    # primary should be marked COMPLETED
    prim = next((r for r in graph.rule_instances if r["id"] == "ri-primary"), None)
    assert prim is not None and prim.get("status") == "COMPLETED"

    # other siblings should be expired and have metadata set
    sib1 = next((r for r in graph.rule_instances if r["id"] == "ri-old-1"), None)
    sib2 = next((r for r in graph.rule_instances if r["id"] == "ri-old-2"), None)

    assert sib1 and sib1.get("status") == "EXPIRED"
    assert sib2 and sib2.get("status") == "EXPIRED"

    # metadata should include expired_by and expired_reason
    assert sib1.get("metadata") and sib1["metadata"].get("expired_by") == "store_email_and_notify"
    assert sib1["metadata"].get("expired_reason") == "superseded_by_primary_rule"
