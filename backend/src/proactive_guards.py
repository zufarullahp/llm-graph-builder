import logging
from src.history_graph import _run_query
logger = logging.getLogger("privas.proactive.guards")


def has_collected_email(graph, session_id: str) -> bool:
    """Return True if an email is already present for this session.

    Checks, in order:
      1) `s.email` fixed property (compat)
      2) `Profile.email` primitive property attached via `HAS_PROFILE`

    Uses a FakeGraph fast-path when available (checks `graph.sessions` and `graph.profiles`).
    """
    try:
        # Fast-path for test double FakeGraph which exposes .sessions and .profiles dicts
        if hasattr(graph, "sessions") and isinstance(getattr(graph, "sessions"), dict):
            s = graph.sessions.get(session_id, {})
            if s.get("email"):
                return True
            profiles = getattr(graph, "profiles", {})
            p = profiles.get(session_id) if isinstance(profiles, dict) else None
            if p and p.get("email"):
                return True
            return False

        # Read session email and linked Profile.email (if any)
        cypher = (
            "MATCH (s:Session {id:$sessionId}) OPTIONAL MATCH (s)-[:HAS_PROFILE]->(p:Profile) "
            "RETURN s.email AS email, p.email AS profile_email LIMIT 1"
        )
        rows = _run_query(graph, cypher, {"sessionId": session_id}, access="READ")
        if not rows:
            return False
        row = rows[0]

        if row.get("email"):
            return True
        if row.get("profile_email"):
            return True
        return False
    except Exception:
        logging.exception("has_collected_email failed")
        return False
