import json
import logging
from typing import Dict, Any, List, Optional

from src.history_graph import _run_query


def create_rule_instance(graph, session_id: str, rule_id: str, asked_at_turn: int, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Create a RuleInstance node and link it to the Session.

    Returns the created rule_instance id or None on failure.
    """
    try:
        # First, check for an existing active WAITING RuleInstance for this (session, rule)
        check_cypher = (
            "MATCH (s:Session {id:$sessionId})-[:HAS_RULE_INSTANCE]->(ri:RuleInstance)\n"
            "WHERE ri.rule_id = $ruleId AND ri.status IN ['WAITING']\n"
            "RETURN ri.id AS id, ri.asked_at_turn AS asked_at_turn, ri.metadata AS metadata LIMIT 1"
        )
        rows = _run_query(graph, check_cypher, {"sessionId": session_id, "ruleId": rule_id}, access="READ")
        if rows and rows[0].get("id"):
            # Reuse existing active RuleInstance instead of creating a duplicate
            existing_id = rows[0]["id"]
            logging.info(f"[RuleInstance] reuse existing WAITING rule_instance={existing_id} rule_id={rule_id} session={session_id}")
            return existing_id

        # No active WAITING instance found -> create a new one
        meta_str = json.dumps(metadata or {})
        cypher = (
            "MERGE (s:Session {id:$sessionId})\n"
            "CREATE (ri:RuleInstance { id: randomUuid(), rule_id:$ruleId, status:$status, asked_at_turn:$askedAtTurn, asked_at_ts: datetime(), metadata:$meta })\n"
            "MERGE (s)-[:HAS_RULE_INSTANCE]->(ri)\n"
            "RETURN ri.id AS id"
        )
        rows = _run_query(graph, cypher, {"sessionId": session_id, "ruleId": rule_id, "status": "WAITING", "askedAtTurn": asked_at_turn, "meta": meta_str}, access="WRITE")
        if rows and rows[0].get("id"):
            created_id = rows[0]["id"]
            logging.info(f"[RuleInstance] created rule_instance={created_id} rule_id={rule_id} session={session_id}")

            # Post-create safety: ensure there's at most one WAITING instance for this (session, rule).
            # If duplicates exist (some test harnesses or older data), expire the extras and
            # return the canonical (oldest) WAITING instance's id.
            try:
                active = get_active_rule_instances(graph, session_id)
                matching = [r for r in active if r.get("rule_id") == rule_id and r.get("status") == "WAITING"]
                if len(matching) > 1:
                    # pick the newest by asked_at_turn as canonical (prefer most recent prompt)
                    canonical = max(matching, key=lambda x: (x.get("asked_at_turn") or 0))
                    canonical_id = canonical.get("id")
                    # expire others
                    for r in matching:
                        if r.get("id") != canonical_id:
                            try:
                                # mark sibling as EXPIRED with small metadata
                                meta_patch = {"expired_by": "create_rule_instance", "expired_reason": "dedup_on_create"}
                                update_rule_instance_status(graph, r.get("id"), "EXPIRED", meta_patch, completed_at_turn=r.get("asked_at_turn"))
                            except Exception:
                                logging.exception("Failed to expire duplicate RuleInstance during dedup")
                    logging.info(f"[RuleInstance] deduped rule={rule_id} session={session_id}, canonical={canonical_id}")
                    return canonical_id
            except Exception:
                logging.exception("Post-create dedup safety check failed")

            return created_id
        return None
    except Exception as e:
        logging.error(f"Failed to create RuleInstance for session={session_id} rule={rule_id}: {e}")
        return None


def get_active_rule_instances(graph, session_id: str) -> List[Dict[str, Any]]:
    """Return active/waiting rule instances for a session, ordered by asked_at_ts desc."""
    try:
        cypher = (
            "MATCH (s:Session {id:$sessionId})-[:HAS_RULE_INSTANCE]->(ri) "
            "WHERE ri.status IN ['WAITING','PENDING'] "
            "RETURN ri.id AS id, ri.rule_id AS rule_id, ri.status AS status, ri.asked_at_turn AS asked_at_turn, ri.metadata AS metadata, ri.asked_at_ts AS asked_at_ts ORDER BY ri.asked_at_ts DESC"
        )
        rows = _run_query(graph, cypher, {"sessionId": session_id}, access="READ")
        results = []
        for r in rows or []:
            meta = r.get("metadata")
            try:
                meta_parsed = json.loads(meta) if isinstance(meta, str) and meta else (meta or {})
            except Exception:
                meta_parsed = {"raw": meta}
            results.append({
                "id": r.get("id"),
                "rule_id": r.get("rule_id"),
                "status": r.get("status"),
                "asked_at_turn": r.get("asked_at_turn"),
                "metadata": meta_parsed,
            })
        return results
    except Exception as e:
        logging.error(f"Failed to read RuleInstance for session={session_id}: {e}")
        return []


def update_rule_instance_status(graph, rule_instance_id: str, status: str, metadata_patch: Optional[Dict[str, Any]] = None, completed_at_turn: Optional[int] = None) -> bool:
    try:
        if metadata_patch is None:
            metadata_patch = {}
        meta_str = json.dumps(metadata_patch)
        if completed_at_turn is not None:
            cypher = (
                "MATCH (ri:RuleInstance {id:$id}) SET ri.status=$status, ri.completed_at_turn=$completedAtTurn, ri.completed_at_ts=datetime(), ri.metadata = $meta RETURN ri.id AS id"
            )
            params = {"id": rule_instance_id, "status": status, "completedAtTurn": completed_at_turn, "meta": meta_str}
        else:
            cypher = "MATCH (ri:RuleInstance {id:$id}) SET ri.status=$status, ri.metadata = $meta RETURN ri.id AS id"
            params = {"id": rule_instance_id, "status": status, "meta": meta_str}

        rows = _run_query(graph, cypher, params, access="WRITE")
        return bool(rows)
    except Exception as e:
        logging.error(f"Failed to update RuleInstance {rule_instance_id} status to {status}: {e}")
        return False
