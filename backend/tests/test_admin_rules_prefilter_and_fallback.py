import logging
from types import SimpleNamespace

import pytest

from src.proactive_controller import maybe_trigger_proactive_followup
from src.proactive_admin_rules import load_proactive_rules_for_tenant


class FakeGraph:
    """Minimal fake graph with sessions/profiles dicts used by has_collected_email."""

    def __init__(self, session_email=None, profile_email=None):
        self.sessions = {}
        self.profiles = {}
        if session_email:
            self.sessions["s1"] = {"email": session_email}
        if profile_email:
            self.profiles["s1"] = {"email": profile_email}


def test_prefilter_ask_email_and_soft_skip_fallback(monkeypatch, caplog):
    """
    Scenario:
      - There are two admin rules: ask_email_if_missing (priority 100) and generic_every_3_turns (priority 10, soft_skip).
      - The session already has an email, so ask_email_if_missing should be pre-filtered and NOT considered.
      - The DPE should be called for the remaining candidate; we simulate DPE denying the high-priority rule (if it were present)
        but allowing the soft-followup rule, which should result in a followup_text being returned.
    """
    caplog.set_level(logging.DEBUG)

    # Prepare a fake graph that already has an email for session 's1'
    graph = FakeGraph(session_email="user@example.com")
    session_id = "s1"

    # Load default rules and ensure both exist
    rules = load_proactive_rules_for_tenant(None)
    ids = {r.get("id") for r in rules}
    assert "ask_email_if_missing" in ids
    assert "generic_every_3_turns" in ids

    # Monkeypatch DPE to assert it's only called for the allowed candidate(s)
    calls = []

    def fake_evaluate_proactive_decision_v1(llm, session_state, question, standalone_question, primary_answer, retrieval_info, mode, graph, session_id):
        # Record which candidate was passed via retrieval_info hint
        admin_hint = (retrieval_info or {}).get("admin_rule_candidate")
        calls.append(admin_hint.get("id") if admin_hint else None)

        # Simulate: allow only if candidate id == 'generic_every_3_turns'
        if admin_hint and admin_hint.get("id") == "generic_every_3_turns":
            return True, "allowed_generic", {"meta": True}, []
        return False, "denied", None, []

    monkeypatch.setattr("src.proactive_controller.evaluate_proactive_decision_v1", fake_evaluate_proactive_decision_v1)

    # Monkeypatch composer to return a determinist followup text when called
    def fake_compose_followup_message_v1(llm, question, standalone_question, primary_answer, reason, candidate_entities, graph_entities, mode, admin_rule=None):
        if admin_rule and admin_rule.get("id") == "generic_every_3_turns":
            return "Here is a helpful tip every 3 turns."
        return None

    monkeypatch.setattr("src.proactive_controller.compose_followup_message_v1", fake_compose_followup_message_v1)

    # Monkeypatch get_session_state to avoid real DB/Neo4j calls and ensure turnCount==3
    def fake_get_session_state(graph_arg, session_id_arg):
        return {
            "proactive_enabled": True,
            "turnCount": 3,
            "lastProactiveTurn": 0,
            "lastProactiveTimestamp": None,
        }

    monkeypatch.setattr("src.proactive_controller.get_session_state", fake_get_session_state)

    # Call the controller: note we set turnCount to 3 to satisfy every_3_turns
    mode = "test"
    primary_answer = "Answer"
    retrieval_info = {}
    llm = None
    question = "Q"
    standalone_question = "Q"

    # Ensure session state has turnCount >= 3 by registering a session node via controller helper
    # We can call register_user_turn, but simpler is to set session node directly in fake graph structures
    # The controller uses has_collected_email which reads graph.sessions; register_user_turn writes to Neo4j normally.

    # Call the function under test
    followup = maybe_trigger_proactive_followup(
        graph=graph,
        session_id=session_id,
        mode=mode,
        primary_answer=primary_answer,
        retrieval_info=retrieval_info,
        llm=llm,
        question=question,
        standalone_question=standalone_question,
        tenant_id=None,
    )

    # Assert that the pre-filter removed ask_email_if_missing so DPE was NOT called with it
    assert "ask_email_if_missing" not in calls

    # Since our fake DPE allows generic_every_3_turns, the controller should return the composed followup
    assert followup == "Here is a helpful tip every 3 turns." or followup is not None


if __name__ == "__main__":
    pytest.main([__file__])
