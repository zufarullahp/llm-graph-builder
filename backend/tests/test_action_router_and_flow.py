import os
import json

from src.rule_instance import create_rule_instance, get_active_rule_instances
from src.proactive_action_router import route_meta_turn
from src.proactive_actions import store_email_and_notify
from src.history_graph import save_history_graph
from src.natural_intent import detect_natural_intent
from src.nid_handlers import persist_contact, store_pending_contact
from src.proactive_action_router import route_meta_turn
from src.natural_intent import classify_intent_with_llm

from test_utils.fake_graph import FakeGraph


def test_route_meta_turn_store_email_and_notify_unit(fake_graph):
    os.environ["ENABLE_PROACTIVE_ACTIONS"] = "true"
    graph = fake_graph
    session_id = "sess-1"

    # Create a rule instance manually
    ri_id = create_rule_instance(graph, session_id, "ask_email_if_missing", asked_at_turn=1, metadata={"proactive_reason": "test"})
    assert ri_id is not None

    # Ensure active rule instance is visible
    active = get_active_rule_instances(graph, session_id)
    assert any(r.get("rule_id") == "ask_email_if_missing" for r in active)

    # Simulate NID result: user shared an email
    nid = {"intent": "contact_sharing", "slots": {"email": "user+test@example.com"}}

    result = route_meta_turn(graph, session_id, nid)
    assert result.get("handled") is True
    assert result.get("message_override") is not None
    assert result.get("action_meta") is not None


def test_full_ask_email_if_missing_flow_integration(fake_graph):
    os.environ["ENABLE_PROACTIVE_ACTIONS"] = "true"
    graph = fake_graph
    session_id = "sess-2"

    # 1) Simulate follow-up persisted (as if Composer emitted it)
    followup_text = "Can I save your email to send summaries?"
    save_history_graph(graph, session_id, source="rag", input_text="q", rephrased=None, output_text=followup_text, ids=[], cypher=None, response_type="followup", proactive_reason="ask_email", trigger_meta={"admin_rule_id": "ask_email_if_missing"})

    # 2) Create RuleInstance (controller would do this)
    ri_id = create_rule_instance(graph, session_id, "ask_email_if_missing", asked_at_turn=2, metadata={"proactive_reason": "ask_email"})
    assert ri_id is not None

    # 3) User replies with email -> NID detects contact_sharing
    text = "My email is me+bot@example.com"
    nid = detect_natural_intent(text)
    assert nid.get("intent") == "contact_sharing"
    assert nid.get("slots", {}).get("email") is not None

    # 4) Route meta-turn -> should store email, create job stub, persist contact, complete RI
    router_res = route_meta_turn(graph, session_id, nid)
    assert router_res.get("handled") is True
    # message override should be provided by action handler
    assert isinstance(router_res.get("message_override"), str)

    # 5) Session/profile should have email
    assert graph.sessions.get(session_id, {}).get("email") == nid["slots"]["email"]

    # 6) Persisted contact exists in saved_responses (persist_contact via save_history_graph)
    assert any(r.get("source") == "nid" for r in graph.saved_responses)

    # 7) RuleInstance should no longer be active (status COMPLETED)
    active_after = [r for r in graph.rule_instances if r.get("status") in ("WAITING", "PENDING")]
    assert len(active_after) == 0

    # 8) router action_meta should include resp_id and job_id keys (job may be None)
    am = router_res.get("action_meta") or {}
    assert "resp_id" in am


def test_confirm_save_pending_contact_flow(fake_graph):
    os.environ["ENABLE_PROACTIVE_ACTIONS"] = "true"
    graph = fake_graph
    session_id = "sess-3"

    # Simulate follow-up and RuleInstance
    followup_text = "Can I save your email to send summaries?"
    save_history_graph(graph, session_id, source="rag", input_text="q", rephrased=None, output_text=followup_text, ids=[], cypher=None, response_type="followup", proactive_reason="ask_email", trigger_meta={"admin_rule_id": "ask_email_if_missing"})
    ri_id = create_rule_instance(graph, session_id, "ask_email_if_missing", asked_at_turn=1, metadata={"proactive_reason": "ask_email"})
    assert ri_id is not None

    # Store pending contact (user previously provided contact but hadn't consented)
    email = "p+yes@example.com"
    store_pending_contact(graph, session_id, {"email": email})
    assert graph.sessions.get(session_id, {}).get("pending_contact") is not None

    # User replies 'Yes' -> affirmative NID
    nid_yes = detect_natural_intent("Yes")
    assert nid_yes.get("intent") == "affirmative"

    # Route meta-turn -> should confirm save and persist contact
    router_res = route_meta_turn(graph, session_id, nid_yes)
    assert router_res.get("handled") is True
    assert router_res.get("message_override")

    # Pending should be cleared
    assert graph.sessions.get(session_id, {}).get("pending_contact") is None

    # A response with source 'nid' should have been saved
    assert any(r.get("source") == "nid" for r in graph.saved_responses)

    # RuleInstance completed
    assert not any(r.get("status") in ("WAITING", "PENDING") for r in graph.rule_instances)


def test_yes_without_pending_contact_should_not_handle(fake_graph):
    """User says 'Yes' but no pending contact exists -> router.handled == False and RI unchanged."""
    os.environ["ENABLE_PROACTIVE_ACTIONS"] = "true"
    graph = fake_graph
    session_id = "sess-no-pending"

    # Create a waiting RuleInstance
    ri_id = create_rule_instance(graph, session_id, "ask_email_if_missing", asked_at_turn=1, metadata={})
    assert ri_id is not None

    nid_yes = detect_natural_intent("Yes")
    assert nid_yes.get("intent") == "affirmative"

    res = route_meta_turn(graph, session_id, nid_yes)
    # Handler should have attempted but returned ok False -> router.handled False
    assert res.get("handled") is False
    # RuleInstance should remain WAITING
    assert any(r.get("status") == "WAITING" for r in graph.rule_instances)


def test_malformed_email_slots_result_in_no_handle(fake_graph):
    """NID detects contact_sharing but slots invalid (no email) -> action returns ok=False -> router.handled False."""
    os.environ["ENABLE_PROACTIVE_ACTIONS"] = "true"
    graph = fake_graph
    session_id = "sess-malformed"

    ri_id = create_rule_instance(graph, session_id, "ask_email_if_missing", asked_at_turn=1, metadata={})
    assert ri_id is not None

    # Simulate NID that found intent but no usable slots
    nid = {"intent": "contact_sharing", "slots": {}}
    res = route_meta_turn(graph, session_id, nid)
    assert res.get("handled") is False
    # RuleInstance remains waiting
    assert any(r.get("status") == "WAITING" for r in graph.rule_instances)


def test_no_active_rule_instance_returns_not_handled(fake_graph):
    os.environ["ENABLE_PROACTIVE_ACTIONS"] = "true"
    graph = fake_graph
    session_id = "sess-no-ri"

    nid = {"intent": "contact_sharing", "slots": {"email": "a@b.com"}}
    res = route_meta_turn(graph, session_id, nid)
    assert res.get("handled") is False


def test_llm_nid_low_confidence_defaults_to_requires_retrieval():
    # When LLM classifier is unavailable or unsure, it should return requires_retrieval=True
    # classify_intent_with_llm returns requires_retrieval True if SystemMessage/HumanMessage are not importable
    res = classify_intent_with_llm(None, "This is ambiguous")
    assert res.get("requires_retrieval") is True
