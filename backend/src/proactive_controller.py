# src/proactive_controller.py
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from src.proactive_dpe import evaluate_proactive_decision_v1
from src.proactive_composer import compose_followup_message_v1
from src.proactive_entity_inspector import inspect_entities_in_graph
from src.history_graph import save_history_graph, _run_query
from src.proactive_admin_rules import load_proactive_rules_for_tenant, evaluate_admin_rules
from src.rule_instance import create_rule_instance

TURN_COOLDOWN_TURNS = 3       # spec: min 3 turns
TIME_COOLDOWN_SECONDS = 30    # spec: 30–60s, we start with 30s


def _ensure_session_node(graph, session_id: str) -> Dict[str, Any]:
    """
    Ensure Session exists and has proactive fields.
    Mirrors the defaults in save_history_graph.
    """
    cypher = """
    MERGE (s:Session {id:$sessionId})
    SET s.proactive_enabled      = coalesce(s.proactive_enabled, true),
        s.turnCount              = coalesce(s.turnCount, 0),
        s.lastProactiveTurn      = coalesce(s.lastProactiveTurn, 0),
        s.lastProactiveTimestamp = coalesce(
            s.lastProactiveTimestamp,
            datetime({epochSeconds: 0})
        )
    RETURN s.proactive_enabled AS proactive_enabled,
           s.turnCount AS turnCount,
           s.lastProactiveTurn AS lastProactiveTurn,
           s.lastProactiveTimestamp AS lastProactiveTimestamp
    """
    rows = _run_query(graph, cypher, {"sessionId": session_id}, access="WRITE")
    return rows[0] if rows else {
        "proactive_enabled": True,
        "turnCount": 0,
        "lastProactiveTurn": 0,
        "lastProactiveTimestamp": None,
    }


def get_session_state(graph, session_id: str) -> Dict[str, Any]:
    """
    Public helper to read current proactive state.
    """
    try:
        state = _ensure_session_node(graph, session_id)
        return state
    except Exception as e:
        logging.error(f"[Proactive][Controller] Failed to get session state for {session_id}: {e}")
        return {
            "proactive_enabled": True,
            "turnCount": 0,
            "lastProactiveTurn": 0,
            "lastProactiveTimestamp": None,
        }


def register_user_turn(graph, session_id: str) -> Dict[str, Any]:
    """
    Increment turnCount for each user message. This is called at the
    beginning of process_chat_response / process_graph_response.
    """
    cypher = """
    MERGE (s:Session {id:$sessionId})
    SET s.proactive_enabled      = coalesce(s.proactive_enabled, true),
        s.turnCount              = coalesce(s.turnCount, 0) + 1,
        s.lastProactiveTurn      = coalesce(s.lastProactiveTurn, 0),
        s.lastProactiveTimestamp = coalesce(
            s.lastProactiveTimestamp,
            datetime({epochSeconds: 0})
        )
    RETURN s.proactive_enabled AS proactive_enabled,
           s.turnCount AS turnCount,
           s.lastProactiveTurn AS lastProactiveTurn,
           s.lastProactiveTimestamp AS lastProactiveTimestamp
    """
    try:
        rows = _run_query(graph, cypher, {"sessionId": session_id}, access="WRITE")
        state = rows[0] if rows else {}
        
        return state
    except Exception as e:
        logging.error(f"Failed to register user turn for {session_id}: {e}")
        return get_session_state(graph, session_id)


def register_proactive_emission(graph, session_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    When a proactive follow-up is actually emitted,
    we record lastProactiveTurn and lastProactiveTimestamp.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    cypher = """
    MATCH (s:Session {id:$sessionId})
    SET s.lastProactiveTurn      = coalesce(s.turnCount, 0),
        s.lastProactiveTimestamp = datetime($nowIso)
    RETURN s.proactive_enabled AS proactive_enabled,
           s.turnCount AS turnCount,
           s.lastProactiveTurn AS lastProactiveTurn,
           s.lastProactiveTimestamp AS lastProactiveTimestamp
    """
    params = {
        "sessionId": session_id,
        "nowIso": now.isoformat(),
    }
    try:
        rows = _run_query(graph, cypher, params, access="WRITE")
        state = rows[0] if rows else {}
        logging.info(
            "[Proactive][Controller] register_proactive_emission session=%s turn=%s",
            session_id,
            state.get("lastProactiveTurn"),
        )
        return state
    except Exception as e:
        logging.error(f"Failed to register proactive emission for {session_id}: {e}")
        return get_session_state(graph, session_id)


def evaluate_cooldown(state: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """
    Pure function: given session state, decide if cooldown is satisfied.
    Does NOT know about DPE – it's only cooldown/toggle logic.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    proactive_enabled = state.get("proactive_enabled", True)
    if not proactive_enabled:
        return False

    turn_count = state.get("turnCount", 0) or 0
    last_turn = state.get("lastProactiveTurn", 0) or 0
    last_ts = state.get("lastProactiveTimestamp")

    # 🔐 FIRST MESSAGE RULE:
    # Untuk turn pertama, jangan blokir dengan cooldown.
    if turn_count <= 1:
        return True

    # Turn-based cooldown
    if (turn_count - last_turn) < TURN_COOLDOWN_TURNS:
        return False

    # Time-based cooldown
    if last_ts:
        try:
            last_dt = None
            # native datetime (from Python)
            if isinstance(last_ts, datetime):
                last_dt = last_ts
            else:
                # neo4j-like temporal object with to_native()
                to_native = getattr(last_ts, "to_native", None)
                if callable(to_native):
                    try:
                        last_dt = to_native()
                    except Exception:
                        last_dt = None
                # try ISO string parse if still None
                if not last_dt and isinstance(last_ts, str):
                    try:
                        last_dt = datetime.fromisoformat(last_ts)
                    except Exception:
                        last_dt = None

            if last_dt:
                delta = (now - last_dt).total_seconds()
                if delta < TIME_COOLDOWN_SECONDS:
                    return False
        except Exception:
            # Kalau parsing gagal, rely only on turn-based
            pass

    return True


# version one only with real graph entities
# def maybe_trigger_proactive_followup(
#     graph,
#     session_id: str,
#     mode: str,
#     primary_answer: str,
#     retrieval_info: Dict[str, Any],
#     llm,
#     question: str,
#     standalone_question: str,
# ) -> Optional[str]:
#     """
#     Sprint 2 with real graph entities:
#       - Uses entities.entityids & relationshipids from retrieval_info["entities"]
#       - Resolves them via inspector
#       - Feeds rich graph-aware data to DPE & Composer (LLM-based)
#     """
#     logging.info(
#         "[Proactive][Controller] maybe_trigger start session=%s mode=%s",
#         session_id,
#         mode,
#     )

#     # 1. session state + cooldown
#     state = get_session_state(graph, session_id)
#     logging.debug("[Proactive][Controller] state=%s", state)

#     if not evaluate_cooldown(state):
#         logging.debug(
#             "[Proactive][Controller] cooldown_not_satisfied session=%s state=%s",
#             session_id,
#             state,
#         )
#         return None

#     entities_dict = retrieval_info.get("entities") or {}
#     nodedetails = retrieval_info.get("nodedetails") or {}

#     # 2. Graph Entity Inspector: resolve elementIds -> nodes + relationships
#     graph_entities = inspect_entities_in_graph(
#         graph=graph,
#         entities_dict=entities_dict,
#         nodedetails=nodedetails,
#     )

#     candidate_entities = graph_entities.get("candidates", [])
#     logging.debug(
#         "[Proactive][Controller] inspector candidates=%s nodes=%s rels=%s",
#         len(candidate_entities),
#         len(graph_entities.get("nodes") or []),
#         len(graph_entities.get("relationships") or []),
#     )

#     # 3. DPE v1 (LLM-based policy)
#     #    DPE v1 mengembalikan: (allow, reason, trigger_meta, dpe_entities)
#     allow, reason, trigger_meta, dpe_entities = evaluate_proactive_decision_v1(
#         llm=llm,
#         session_state=state,
#         question=question,
#         standalone_question=standalone_question,
#         primary_answer=primary_answer,
#         retrieval_info={
#             **(retrieval_info or {}),
#             "graph_entities": graph_entities,
#             "candidate_entities": candidate_entities,
#         },
#         mode=mode,
#     )

#     logging.info(
#         "[Proactive][Controller] DPE_decision allow=%s reason=%s session=%s",
#         allow,
#         reason,
#         session_id,
#     )

#     if not allow:
#         logging.debug(
#             "[Proactive][Controller] DPE_skip session=%s reason=%s",
#             session_id,
#             reason,
#         )
#         return None

#     # 4. Composer v1 (LLM) – build bubble #2 text
#     followup_text = compose_followup_message_v1(
#         llm=llm,
#         question=question,
#         standalone_question=standalone_question,
#         primary_answer=primary_answer,
#         reason=reason,
#         candidate_entities=candidate_entities,
#         mode=mode,
#     )

#     if not followup_text:
#         logging.debug(
#             "[Proactive][Controller] composer_empty session=%s reason=%s",
#             session_id,
#             reason,
#         )
#         return None

#     # 5. Persist followup as Response{type:'followup'}
#     try:
#         # reuse context ids from nodedetails.chunkdetails if present
#         ctx_ids = []
#         chunkdetails = nodedetails.get("chunkdetails") or []
#         for c in chunkdetails:
#             cid = c.get("id")
#             if cid:
#                 ctx_ids.append(cid)

#         save_history_graph(
#             graph=graph,
#             session_id=session_id,
#             source=mode,
#             input_text=question,
#             rephrased=standalone_question,
#             output_text=followup_text,
#             ids=ctx_ids,
#             cypher=None,
#             response_type="followup",
#             proactive_reason=reason,
#             trigger_meta={
#                 **(trigger_meta or {}),
#                 "graph_entities": graph_entities,
#             },
#         )

#         register_proactive_emission(graph, session_id)
#         logging.info(
#             "[Proactive][Controller] followup_emitted session=%s ctx_ids=%s",
#             session_id,
#             len(ctx_ids),
#         )

#     except Exception as e:
#         logging.error(
#             f"[Proactive][Controller] Failed to persist follow-up for session={session_id}: {e}"
#         )

#     return followup_text


def maybe_trigger_proactive_followup(
    graph,
    session_id: str,
    mode: str,
    primary_answer: str,
    retrieval_info: Dict[str, Any],
    llm,
    question: str,
    standalone_question: str,
    tenant_id: Optional[str] = None,   # 🆕 optional, biar future-proof per tenant
) -> Optional[str]:
    """
    Sprint 2+AdminRules:
      - Inspect graph entities (entityids & relationshipids).
      - Load admin-configurable rules for this tenant.
      - Evaluate which admin rule (if any) is eligible.
      - Pass both graph + admin signals into DPE.
      - If ALLOW, Composer build bubble #2.
    """
    # 1. Baca state dan cek cooldown
    state = get_session_state(graph, session_id)
    if not evaluate_cooldown(state):
        logging.debug(
            f"[Proactive][Controller] Cooldown not satisfied for session={session_id}"
        )
        return None

    # 2. Resolve graph entities dari retrieval_info
    entities_dict = retrieval_info.get("entities") or {}
    nodedetails = retrieval_info.get("nodedetails") or {}

    try:
        graph_entities = inspect_entities_in_graph(
            graph=graph,
            entities_dict=entities_dict,
            nodedetails=nodedetails,
        )
    except Exception as e:
        logging.error(
            f"[Proactive][Controller] inspect_entities_in_graph error "
            f"session={session_id}: {e}"
        )
        graph_entities = {"nodes": [], "relationships": []}

    # 👉 Untuk DPE v1 kita masih pakai top-entities dari retrieval_info,
    # tapi inspector memberi data kaya untuk Composer & logging.
    candidate_entities = graph_entities.get("nodes", [])

    # 3. Admin-configurable rules (lapisan baru)
    try:
        rules = load_proactive_rules_for_tenant(tenant_id)
        admin_rule = evaluate_admin_rules(
            session_state=state,
            runtime_context={
                "event": "AFTER_ANSWER",
                "mode": mode,
                "question": question,
                "standalone_question": standalone_question,
            },
            rules=rules,
        )
    except Exception as e:
        logging.error(
            f"[Proactive][AdminRules] Error while evaluating rules "
            f"session={session_id}: {e}"
        )
        admin_rule = None

    # Masukkan admin_rule candidate ke retrieval_info agar DPE bisa lihat
    # (tanpa mengubah signature DPE).
    if admin_rule:
        retrieval_info = dict(retrieval_info or {})
        retrieval_info["admin_rule_candidate"] = {
            "id": admin_rule.get("id"),
            "name": admin_rule.get("name"),
            "event": admin_rule.get("event"),
            "priority": admin_rule.get("priority"),
            "metadata": admin_rule.get("metadata") or {},
        }

    # 4. DPE v1 (LLM-based policy) – sekarang tahu tentang admin_rule_candidate
    allow, reason, trigger_meta, _top_entities = evaluate_proactive_decision_v1(
        llm=llm,
        session_state=state,
        question=question,
        standalone_question=standalone_question,
        primary_answer=primary_answer,
        retrieval_info=retrieval_info,
        mode=mode,
    )

    if not allow:
        logging.debug(
            f"[Proactive][Controller] DPE decided SKIP for session={session_id}, "
            f"reason={reason}"
        )
        return None

    # 5. Composer v1 (LLM) – build bubble #2 text
    #    Kalau ada admin_rule, Composer bisa gunakan llm_instruction-nya.
    followup_text = compose_followup_message_v1(
        llm=llm,
        question=question,
        standalone_question=standalone_question,
        primary_answer=primary_answer,
        reason=reason,
        candidate_entities=candidate_entities,
        graph_entities=graph_entities,
        mode=mode,
        admin_rule=admin_rule,   # 🆕
    )

    if not followup_text:
        logging.debug(
            f"[Proactive][Controller] Composer returned empty text for "
            f"session={session_id}, reason={reason}"
        )
        return None

    # 6. Persist followup sebagai Response{type:'followup'}
    try:
        nodedetails = retrieval_info.get("nodedetails") or {}
        ctx_ids = []
        chunkdetails = nodedetails.get("chunkdetails") or []
        for c in chunkdetails:
            cid = c.get("id")
            if cid:
                ctx_ids.append(cid)

        save_history_graph(
            graph=graph,
            session_id=session_id,
            source=mode,
            input_text=question,
            rephrased=standalone_question,
            output_text=followup_text,
            ids=ctx_ids,
            cypher=None,
            response_type="followup",
            proactive_reason=reason,
            trigger_meta={
                **(trigger_meta or {}),
                "graph_entities": graph_entities,
                "admin_rule_id": admin_rule.get("id") if admin_rule else None,
            },
        )

        # If an admin_rule triggered this follow-up, create a per-session RuleInstance
        try:
            if admin_rule and admin_rule.get("id"):
                # use current turn count as asked_at_turn
                asked_turn = state.get("turnCount") if isinstance(state, dict) else None
                create_rule_instance(graph, session_id, admin_rule.get("id"), asked_at_turn=asked_turn or 0, metadata={"proactive_reason": reason})
        except Exception:
            pass

        register_proactive_emission(graph, session_id)

    except Exception as e:
        logging.error(
            f"[Proactive][Controller] Failed to persist follow-up for "
            f"session={session_id}: {e}"
        )

    return followup_text
