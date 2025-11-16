import json
import logging
from typing import Dict, Any, Optional

from src.history_graph import _run_query, save_history_graph


def store_pending_contact(graph, session_id: str, slots: Dict[str, Any]) -> None:
    """Store pending contact in Session.pending_contact as JSON string."""
    try:
        pending_str = json.dumps(slots or {})
        cypher = """
        MERGE (s:Session {id:$sessionId})
        SET s.pending_contact = $pending
        RETURN s.pending_contact AS pending
        """
        _run_query(graph, cypher, {"sessionId": session_id, "pending": pending_str}, access="WRITE")
        logging.info(f"[NID][Handler] stored pending_contact for session={session_id}")
    except Exception as e:
        logging.error(f"[NID][Handler] Failed to store pending contact for {session_id}: {e}")


def get_and_clear_pending_contact(graph, session_id: str) -> Optional[Dict[str, Any]]:
    """Return pending_contact (dict) if present and clear it from Session."""
    try:
        cypher_read = "MATCH (s:Session {id:$sessionId}) RETURN s.pending_contact AS pending"
        rows = _run_query(graph, cypher_read, {"sessionId": session_id}, access="READ")
        if rows and rows[0].get("pending"):
            pending_str = rows[0]["pending"]
            try:
                pending = json.loads(pending_str)
            except Exception:
                pending = {"raw": pending_str}

            # clear
            cypher_clear = "MERGE (s:Session {id:$sessionId}) REMOVE s.pending_contact RETURN true"
            _run_query(graph, cypher_clear, {"sessionId": session_id}, access="WRITE")
            logging.info(f"[NID][Handler] retrieved and cleared pending_contact for session={session_id}")
            return pending
        return None
    except Exception as e:
        logging.error(f"[NID][Handler] Error getting pending contact for {session_id}: {e}")
        return None


def persist_contact(graph, session_id: str, slots: Dict[str, Any]) -> Optional[str]:
    """Persist final contact info into history_graph as a Response node.

    Returns the saved Response id or None on error.
    """
    try:
        # Save as a Response of type 'contact'
        trigger_meta = {"source": "nid", "slots": slots}
        resp_id = save_history_graph(
            graph=graph,
            session_id=session_id,
            source="nid",
            input_text="consent:save_contact",
            rephrased=None,
            output_text="Contact saved",
            ids=[],
            cypher=None,
            response_type="contact",
            proactive_reason="contact_saved",
            trigger_meta=trigger_meta,
        )
        # Some graph wrappers / drivers may not return the created id from
        # save_history_graph (it may return an empty string). If that
        # happens, try to look up the Response node we just created and
        # return its id so callers can reliably detect success.
        if not resp_id:
            try:
                cypher = (
                    "MATCH (s:Session {id:$sessionId})-[:HAS_RESPONSE]->(r)"
                    " WHERE r.input=$input AND r.output=$output AND r.source=$source"
                    " RETURN r.id AS id ORDER BY r.createdAt DESC LIMIT 1"
                )
                rows = _run_query(graph, cypher, {
                    "sessionId": session_id,
                    "input": "consent:save_contact",
                    "output": "Contact saved",
                    "source": "nid",
                }, access="READ")
                if rows and rows[0].get("id"):
                    resp_id = rows[0]["id"]
            except Exception:
                # ignore lookup failures and keep resp_id as falsy
                pass

        logging.info(f"[NID][Handler] persisted contact for session={session_id} resp_id={resp_id}")
        return resp_id
    except Exception as e:
        logging.error(f"[NID][Handler] Failed to persist contact for {session_id}: {e}")
        return None
