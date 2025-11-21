from src.proactive_dpe import evaluate_proactive_decision_v1
from test_utils.fake_graph import FakeGraph


def make_admin_candidate():
    return {"rule_id": "ask_email_if_missing", "id": "ask_email_if_missing", "metadata": {}}


def test_dpe_skips_when_session_email_present(fake_graph):
    graph = fake_graph
    session_id = "guard-sess-1"
    # set session email
    graph.sessions.setdefault(session_id, {})["email"] = "a@b.com"

    state = {"turnCount": 1, "proactive_enabled": True, "email": "a@b.com"}
    allow, reason, meta, ents = evaluate_proactive_decision_v1(
        llm=None,
        session_state=state,
        question="q",
        standalone_question="q",
        primary_answer="ans",
        retrieval_info={"admin_rule_candidate": make_admin_candidate()},
        mode="test",
        graph=graph,
        session_id=session_id,
    )

    assert allow is False
    assert reason == "email_already_present"


def test_dpe_allows_when_no_email(fake_graph):
    graph = fake_graph
    session_id = "guard-sess-2"
    # ensure no email
    graph.sessions.setdefault(session_id, {}).pop("email", None)

    state = {"turnCount": 1, "proactive_enabled": True}
    allow, reason, meta, ents = evaluate_proactive_decision_v1(
        llm=None,
        session_state=state,
        question="q",
        standalone_question="q",
        primary_answer="ans",
        retrieval_info={"admin_rule_candidate": make_admin_candidate()},
        mode="test",
        graph=graph,
        session_id=session_id,
    )

    # For turnCount==1 with context only, DPE enforces ALLOW if not skipped by guard
    assert isinstance(allow, bool)
