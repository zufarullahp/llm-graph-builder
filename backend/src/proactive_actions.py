import logging
import os
from typing import Dict, Any, Optional

from src.history_graph import save_history_graph
from src.nid_handlers import persist_contact, get_and_clear_pending_contact
from src.rule_instance import update_rule_instance_status


def _is_enabled() -> bool:
    return os.getenv("ENABLE_PROACTIVE_ACTIONS", "false").lower() in ("1", "true", "yes")


def store_email_and_notify(graph, session_id: str, slots: Dict[str, Any], rule_instance: Dict[str, Any]) -> Dict[str, Any]:
    """Action: store the email in the session/profile and create a Job stub to notify/send summary.

    Returns dict: {ok, message_override, updated_rule_status, action_meta}
    """
    if not _is_enabled():
        return {"ok": False, "message_override": None, "updated_rule_status": None, "action_meta": {}}

    email = slots.get("email")
    if not email:
        return {"ok": False, "message_override": "I couldn't find an email in your message.", "updated_rule_status": None, "action_meta": {}}

    # Persist as a Response node (via persist_contact) and also attach email to Session node
    try:
        # 1) attach email to session/profile
        cypher = "MERGE (s:Session {id:$sessionId}) SET s.email = $email RETURN elementId(s) AS sid"
        graph.query(cypher, {"sessionId": session_id, "email": email}) if hasattr(graph, "query") else None

        # 2) persist contact in history graph (Response node)
        resp_id = persist_contact(graph, session_id, {"email": email})

        # 3) create a Job stub (traceable side-effect)
        job_cypher = "CREATE (j:Job {id:randomUuid(), type:$type, status:'ENQUEUED', createdAt: datetime(), payload:$payload}) RETURN j.id AS id"
        payload = {"type": "send_email_summary", "email": email, "session_id": session_id}
        try:
            rows = graph.query(job_cypher, {"type": "send_email_summary", "payload": payload}) if hasattr(graph, "query") else []
            job_id = rows[0].get("id") if rows else None
        except Exception:
            job_id = None

        # 4) update rule instance status to COMPLETED
        try:
            if rule_instance and rule_instance.get("id"):
                update_rule_instance_status(graph, rule_instance["id"], "COMPLETED", {"saved_email": email}, completed_at_turn=rule_instance.get("asked_at_turn"))
        except Exception:
            logging.exception("Failed to update rule instance status after storing email")

        # 5) expire any other older WAITING RuleInstances for the same (session, rule)
        try:
            if rule_instance and rule_instance.get("id") and rule_instance.get("rule_id"):
                try:
                    # prepare metadata for expired siblings to help analytics/debugging
                    import json
                    from datetime import datetime as _dt

                    meta_payload = {
                        "expired_by": "store_email_and_notify",
                        "expired_reason": "superseded_by_primary_rule",
                        "timestamp": _dt.utcnow().isoformat() + "Z",
                    }
                    meta_str = json.dumps(meta_payload)

                    cleanup_cypher = (
                        "MATCH (s:Session {id:$sessionId})-[:HAS_RULE_INSTANCE]->(ri:RuleInstance)\n"
                        "WHERE ri.rule_id = $ruleId AND ri.status = 'WAITING' AND ri.id <> $currentId\n"
                        "SET ri.status = 'EXPIRED', ri.completed_at_ts = datetime(), ri.completed_at_turn = $currentTurn, ri.metadata = $meta\n"
                        "RETURN count(ri) AS expired_count"
                    )
                    params = {
                        "sessionId": session_id,
                        "ruleId": rule_instance.get("rule_id"),
                        "currentId": rule_instance.get("id"),
                        "currentTurn": rule_instance.get("asked_at_turn") or rule_instance.get("completed_at_turn") or 0,
                        "meta": meta_str,
                    }
                    # debug-visible call
                    print(f"DEBUG: calling cleanup_cypher with params={params}")
                    rows2 = graph.query(cleanup_cypher, params) if hasattr(graph, "query") else []
                    expired_count = rows2[0].get("expired_count") if rows2 else 0
                    logging.info(f"[RuleInstance] expired {expired_count} sibling WAITING instances for rule={params['ruleId']} session={session_id}")
                except Exception:
                    logging.exception("Failed to expire sibling RuleInstances after storing email")
        except Exception:
            # defensive - never block the success path if cleanup fails
            logging.exception("Unexpected error during sibling RuleInstance cleanup")

        msg = "Thanks — your email has been saved. I'll use it to send summaries if needed."
        return {"ok": True, "message_override": msg, "updated_rule_status": "COMPLETED", "action_meta": {"resp_id": resp_id, "job_id": job_id}}

    except Exception as e:
        logging.exception(f"store_email_and_notify failed: {e}")
        return {"ok": False, "message_override": "Failed to save email — please try again.", "updated_rule_status": None, "action_meta": {}}


def confirm_save_pending_contact(graph, session_id: str, slots: Dict[str, Any], rule_instance: Dict[str, Any]) -> Dict[str, Any]:
    """If pending contact exists in Session.pending_contact, persist it and complete the RuleInstance."""
    if not _is_enabled():
        return {"ok": False}

    try:
        pending = get_and_clear_pending_contact(graph, session_id)
        if not pending:
            return {"ok": False, "message_override": "I don't see any pending contact to save.", "updated_rule_status": None, "action_meta": {}}

        resp_id = persist_contact(graph, session_id, pending)
        if rule_instance and rule_instance.get("id"):
            update_rule_instance_status(graph, rule_instance["id"], "COMPLETED", {"saved_pending": True}, completed_at_turn=rule_instance.get("asked_at_turn"))

        msg = "Your contact has been saved. Thank you."
        return {"ok": True, "message_override": msg, "updated_rule_status": "COMPLETED", "action_meta": {"resp_id": resp_id}}

    except Exception as e:
        logging.exception(f"confirm_save_pending_contact failed: {e}")
        return {"ok": False, "message_override": "Failed to save pending contact.", "updated_rule_status": None, "action_meta": {}}
