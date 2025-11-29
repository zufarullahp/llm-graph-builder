import logging
import os
from typing import Dict, Any, Optional

# module-level logger
logger = logging.getLogger("privas.proactive.action_router")

from src.rule_instance import get_active_rule_instances
from src.proactive_actions import store_email_and_notify, confirm_save_pending_contact


def _is_enabled() -> bool:
    return os.getenv("ENABLE_PROACTIVE_ACTIONS", "false").lower() in ("1", "true", "yes")


def route_meta_turn(graph, session_id: str, nid_result: Dict[str, Any], session_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Route a meta-turn detected by NID to the appropriate action handler based on active RuleInstance.

    Returns {
      handled: bool,
      message_override: Optional[str],
      updated_rule_status: Optional[str],
      action_meta: Optional[dict],
      rule_instance_id: Optional[str]
    }
    """
    if not _is_enabled():
        return {"handled": False}

    try:
        # Get active rule instances for this session
        candidates = get_active_rule_instances(graph, session_id)
        if not candidates:
            return {"handled": False}

        intent = nid_result.get("intent")
        slots = nid_result.get("slots") or {}

        # Prioritize the most recent waiting instance
        for ri in candidates:
            rule_id = ri.get("rule_id")
            # Simple mapping rules for now
            if rule_id == "ask_email_if_missing":
                # If user provided an email directly
                if intent == "contact_sharing" and slots.get("email"):
                    result = store_email_and_notify(graph, session_id, slots, ri)
                    return {"handled": result.get("ok", False), "message_override": result.get("message_override"), "updated_rule_status": result.get("updated_rule_status"), "action_meta": result.get("action_meta"), "rule_instance_id": ri.get("id")}
                # If user answered 'yes' to a pending contact
                if intent == "affirmative":
                    result = confirm_save_pending_contact(graph, session_id, slots, ri)
                    return {"handled": result.get("ok", False), "message_override": result.get("message_override"), "updated_rule_status": result.get("updated_rule_status"), "action_meta": result.get("action_meta"), "rule_instance_id": ri.get("id")}

        # Nothing handled
        return {"handled": False}

    except Exception as e:
        logging.exception(f"Action Router failed for session={session_id} nid={nid_result}: {e}")
        return {"handled": False}
