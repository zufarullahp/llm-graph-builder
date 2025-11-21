import pytest


def test_controller_uses_static_template_fast_path(monkeypatch):
    """Ensure Controller returns static template when admin_rule.template_key exists
    and does not call the LLM composer path.
    """
    from src import proactive_controller as controller

    # Minimal fake rule – will be injected by evaluate_admin_rules via load
    admin_rule = {
        "id": "generic_every_3_turns",
        "template_key": "tip_every_3_turns_v1",
        "name": "Every 3 turns helpful tip",
        "active": True,
        "event": "AFTER_ANSWER",
    }

    # Patch load_proactive_rules_for_tenant to return our rule list
    # Patch both module-level binding and controller-local binding
    import src.proactive_admin_rules as admin_rules_mod
    monkeypatch.setattr(admin_rules_mod, "load_proactive_rules_for_tenant", lambda tenant_id: [admin_rule])
    monkeypatch.setattr(controller, "load_proactive_rules_for_tenant", lambda tenant_id: [admin_rule])

    # Patch evaluate_proactive_decision_v1 to always allow (both module and controller binding)
    import src.proactive_dpe as dpe_mod
    monkeypatch.setattr(dpe_mod, "evaluate_proactive_decision_v1", lambda **kwargs: (True, "test", {}, []))
    monkeypatch.setattr(controller, "evaluate_proactive_decision_v1", lambda **kwargs: (True, "test", {}, []))

    # Patch get_session_state to a simple state where cooldown passes
    monkeypatch.setattr(
        controller, "get_session_state", lambda graph, session_id: {"turnCount": 3, "proactive_enabled": True, "lastProactiveTurn": 0}
    )

    # Patch composer functions (both module and controller bindings)
    import src.proactive_composer as composer_mod
    monkeypatch.setattr(composer_mod, "compose_followup_template", lambda rule, session_state, retrieval_info: "STATIC TEMPLATE OK")
    monkeypatch.setattr(controller, "compose_followup_template", lambda rule, session_state, retrieval_info: "STATIC TEMPLATE OK")

    # Patch compose_followup_message_v1 to raise if called (should not be called)
    def _llm_called(*args, **kwargs):
        raise AssertionError("LLM composer should not be called when static template exists")

    monkeypatch.setattr(composer_mod, "compose_followup_message_v1", _llm_called)
    monkeypatch.setattr(controller, "compose_followup_message_v1", _llm_called)

    # Spy/patched persistence functions on controller
    saved = {}
    def _save_history_graph(graph, session_id, source, input_text, rephrased, output_text, ids, cypher, response_type, proactive_reason, trigger_meta):
        saved['history_called'] = True
        # assert response_type is followup
        assert response_type == 'followup'
        # ensure admin_rule_id present in trigger_meta
        assert (trigger_meta or {}).get('admin_rule_id') == admin_rule.get('id')
        return 'resp-1'

    def _create_rule_instance(graph, session_id, rule_id, asked_at_turn=0, metadata=None):
        saved['create_called'] = True
        saved['ri_rule_id'] = rule_id

    def _register_proactive_emission(graph, session_id, now=None):
        saved['register_called'] = True

    monkeypatch.setattr(controller, 'save_history_graph', _save_history_graph)
    monkeypatch.setattr(controller, 'create_rule_instance', _create_rule_instance)
    monkeypatch.setattr(controller, 'register_proactive_emission', _register_proactive_emission)

    # use the FakeGraph from test_utils for minimal graph behavior
    from test_utils.fake_graph import FakeGraph

    g = FakeGraph()

    # Call controller; parameters can be minimal
    res = controller.maybe_trigger_proactive_followup(
        graph=g,
        session_id="sess-1",
        mode="graph_vector_fulltext",
        primary_answer="primary",
        retrieval_info={},
        llm=None,
        question="What is X?",
        standalone_question="What is X?",
        tenant_id=None,
    )

    assert res == "STATIC TEMPLATE OK"
    assert saved.get('history_called') is True
    assert saved.get('create_called') is True
    assert saved.get('register_called') is True
