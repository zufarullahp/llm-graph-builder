import pytest

from types import SimpleNamespace


def test_nid_rule_based_persists_reply(monkeypatch):
    """Verify rule-based NID replies are persisted via save_history_graph with kind 'nid_ack'."""
    # Capture kwargs passed to save_history_graph
    captured = {}

    def fake_save_history_graph(**kwargs):
        captured.update(kwargs)
        return None

    # Patch save_history_graph in the QA_integration module
    monkeypatch.setattr("src.QA_integration.save_history_graph", fake_save_history_graph)

    # Patch detect_natural_intent to trigger rule-based early return
    def fake_detect_natural_intent(question, session_id=None):
        return {"intent": "greeting_closing", "requires_retrieval": False}

    monkeypatch.setattr("src.QA_integration.detect_natural_intent", fake_detect_natural_intent)

    # Patch route_meta_turn to be a no-op (router_result available to trigger_meta)
    monkeypatch.setattr("src.QA_integration.route_meta_turn", lambda graph, session_id, nid, session_state: {})

    # Patch register_user_turn to avoid DB interactions
    monkeypatch.setattr("src.QA_integration.register_user_turn", lambda graph, session_id: {"turnCount": 1, "proactive_enabled": True})

    # Call process_chat_response with minimal arguments; it should take the early NID path
    from src.QA_integration import process_chat_response

    messages = []
    history = None
    graph = SimpleNamespace()  # dummy object

    result = process_chat_response(
        messages=messages,
        history=history,
        question="Hi there",
        model="dummy",
        graph=graph,
        document_names=[],
        chat_mode_settings={"mode": "graph_vector_fulltext"},
        session_id="test-session-1",
    )

    # Ensure we got a reply
    assert isinstance(result, dict)
    assert "message" in result

    # Ensure save_history_graph was called and persisted the same output_text
    assert captured, "save_history_graph was not called"
    assert captured.get("output_text") == result["message"]

    # trigger_meta should be present and include the nid_ack kind
    trigger_meta = captured.get("trigger_meta")
    assert isinstance(trigger_meta, dict)
    assert trigger_meta.get("kind") == "nid_ack"
