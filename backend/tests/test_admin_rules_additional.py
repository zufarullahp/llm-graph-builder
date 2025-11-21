import logging

import pytest

from src.proactive_admin_rules import evaluate_admin_rules, load_proactive_rules_for_tenant
from src.proactive_controller import maybe_trigger_proactive_followup


class FakeGraph:
    def __init__(self, session_email=None, profile_email=None):
        self.sessions = {}
        self.profiles = {}
        if session_email:
            self.sessions["s1"] = {"email": session_email}
        if profile_email:
            self.profiles["s1"] = {"email": profile_email}


def test_evaluate_admin_rules_return_ordered_and_backcompat():
    # two rules with different priorities
    r_low = {"id": "low", "active": True, "event": "AFTER_ANSWER", "priority": 5}
    r_high = {"id": "high", "active": True, "event": "AFTER_ANSWER", "priority": 10}

    session_state = {"turnCount": 1}
    runtime_context = {"event": "AFTER_ANSWER"}

    # Backwards compatible: default call returns single best
    best = evaluate_admin_rules(session_state, runtime_context, [r_low, r_high])
    assert isinstance(best, dict)
    assert best.get("id") == "high"

    # return_all True returns ordered list
    ordered = evaluate_admin_rules(session_state, runtime_context, [r_low, r_high], return_all=True)
    assert isinstance(ordered, list)
    assert ordered[0].get("id") == "high"
    assert ordered[1].get("id") == "low"


def test_hard_block_prevents_fallback(monkeypatch, caplog):
    """If a higher-priority rule is denied by DPE and it is NOT soft-skip,
    controller should treat it as a hard block and not allow lower-priority candidates.
    """
    caplog.set_level(logging.DEBUG)

    # Create two candidate rules where first is high priority and NOT soft_skip
    r_block = {"id": "blocker", "active": True, "event": "AFTER_ANSWER", "priority": 50, "flags": {}}
    r_fallback = {"id": "fallback", "active": True, "event": "AFTER_ANSWER", "priority": 10, "flags": {"soft_skip": True}}

    # Monkeypatch load_proactive_rules_for_tenant to return our list
    monkeypatch.setattr("src.proactive_controller.load_proactive_rules_for_tenant", lambda tid: [r_block, r_fallback])

    # Fake DPE: deny blocker, allow fallback if reached
    calls = []

    def fake_dpe(llm, session_state, question, standalone_question, primary_answer, retrieval_info, mode, graph, session_id):
        admin_hint = (retrieval_info or {}).get("admin_rule_candidate")
        rid = admin_hint.get("id") if admin_hint else None
        calls.append(rid)
        if rid == "blocker":
            return False, "denied_blocker", None, []
        if rid == "fallback":
            return True, "allowed_fallback", None, []
        return False, "unknown", None, []

    monkeypatch.setattr("src.proactive_controller.evaluate_proactive_decision_v1", fake_dpe)

    # Composer should not be called because blocker denies with hard block
    monkeypatch.setattr("src.proactive_controller.compose_followup_message_v1", lambda *a, **k: "SHOULD_NOT_BE_CALLED")

    # Monkeypatch session state to satisfy cooldown/turns
    monkeypatch.setattr("src.proactive_controller.get_session_state", lambda g, s: {"proactive_enabled": True, "turnCount": 1, "lastProactiveTurn": 0, "lastProactiveTimestamp": None})

    graph = FakeGraph()

    followup = maybe_trigger_proactive_followup(
        graph=graph,
        session_id="s1",
        mode="test",
        primary_answer="A",
        retrieval_info={},
        llm=None,
        question="Q",
        standalone_question="Q",
        tenant_id=None,
    )

    # DPE should have been called for the blocker and stopped; fallback should not have been used
    assert calls[0] == "blocker"
    assert followup is None


def test_ask_email_emitted_when_missing(monkeypatch):
    """When the session has no email, ask_email_if_missing should be considered and may emit."""
    # Ensure default rules are present
    rules = load_proactive_rules_for_tenant(None)
    ids = {r.get("id") for r in rules}
    assert "ask_email_if_missing" in ids

    # Fake graph without email
    graph = FakeGraph()

    # Sanity-check: ensure evaluate_admin_rules would include ask_email_if_missing for turnCount=3
    candidates = evaluate_admin_rules({"turnCount": 3}, {"event": "AFTER_ANSWER"}, load_proactive_rules_for_tenant(None), return_all=True)
    assert any((c.get("id") == "ask_email_if_missing") for c in (candidates or [])), f"ask_email_if_missing not in candidates: {candidates}"

    # DPE allows ask_email_if_missing
    calls = []

    def fake_dpe(llm, session_state, question, standalone_question, primary_answer, retrieval_info, mode, graph, session_id):
        admin_hint = (retrieval_info or {}).get("admin_rule_candidate")
        rid = admin_hint.get("id") if admin_hint else None
        calls.append(rid)
        if admin_hint and admin_hint.get("id") == "ask_email_if_missing":
            return True, "allow_email", None, []
        return False, "deny", None, []

    monkeypatch.setattr("src.proactive_controller.evaluate_proactive_decision_v1", fake_dpe)

    # Composer to return email followup
    def fake_compose(llm, question, standalone_question, primary_answer, reason, candidate_entities, graph_entities, mode, admin_rule=None):
        if admin_rule and admin_rule.get("id") == "ask_email_if_missing":
            return "Could you share your email so we can send a summary?"
        return None

    monkeypatch.setattr("src.proactive_controller.compose_followup_message_v1", fake_compose)

    # Force turnCount to a value that passes cooldown
    monkeypatch.setattr("src.proactive_controller.get_session_state", lambda g, s: {"proactive_enabled": True, "turnCount": 3, "lastProactiveTurn": 0, "lastProactiveTimestamp": None})

    followup = maybe_trigger_proactive_followup(
        graph=graph,
        session_id="s1",
        mode="test",
        primary_answer="A",
        retrieval_info={},
        llm=None,
        question="Q",
        standalone_question="Q",
        tenant_id=None,
    )

    # Ensure DPE was called for ask_email_if_missing and composer produced the followup
    assert "ask_email_if_missing" in calls, f"DPE was not called for ask_email_if_missing, calls={calls}"
    assert followup == "Could you share your email so we can send a summary?"
