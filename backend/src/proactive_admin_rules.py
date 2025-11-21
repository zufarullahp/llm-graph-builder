# src/proactive_admin_rules.py
import logging
from typing import Dict, Any, List, Optional


# 👉 Untuk sementara: config in-memory per-tenant.
# Nanti bisa diganti baca dari Neo4j / Postgres / config service.
DEFAULT_RULES_BY_TENANT: Dict[str, List[Dict[str, Any]]] = {
    "*": [
        {
            "id": "ask_email_if_missing",
            "name": "Ask for user email",
            "active": True,
            "event": "AFTER_ANSWER",    # dieksekusi setelah bubble #1
            "min_turn": 1,              # boleh dari turn 1
            "max_per_session": 1,       # opsional: 1x per session
            "priority": 100,            # makin besar = makin prioritas
            # Template / hint untuk Composer (LLM)
            "llm_instruction": (
                "Create a short, polite follow-up asking the user for their email address. "
                "Explain briefly why it is useful (e.g., to send summary, follow-ups, or documents). "
                "Respect the user's choice if they don't want to share it. "
                "Do NOT answer the original question again. "
                "Keep it within 2–3 short sentences."
            ),
            # Bisa dipakai untuk filter konteks admin:
            "metadata": {
                "category": "contact_collection",
            },
        }
        ,
        {
            "id": "generic_every_3_turns",
            "name": "Every 3 turns helpful tip",
            "active": True,
            "event": "AFTER_ANSWER",
            # top-level priority lower than contact collection rules
            "priority": 10,
            # high-level category for UX/tests
            "category": "soft_followup",
            # conditions expressed as a declarative dict for DPE mapping
            "conditions": {
                "every_n_turns": 3,
                "requires_context": False,
            },
            # key used by Composer for template selection
            "template_key": "tip_every_3_turns_v1",
            # hint for cooldown enforcement (interpreted elsewhere)
            "cooldown_hint": "3_turns",
            "flags": {"soft_skip": True},
        }
    ]
}


def load_proactive_rules_for_tenant(tenant_id: Optional[str]) -> List[Dict[str, Any]]:
    """
    Untuk sekarang:
      - kalau tenant_id ada di map, pakai itu
      - kalau tidak, fallback ke '*' (global default)
    Hanya mengembalikan rules yang active=True.
    """
    key = tenant_id or "*"
    rules = DEFAULT_RULES_BY_TENANT.get(key) or DEFAULT_RULES_BY_TENANT.get("*", [])
    active_rules = [r for r in rules if r.get("active", False)]

    logging.debug(
        f"[Proactive][AdminRules] Loaded {len(active_rules)} rules for tenant={key}"
    )
    return active_rules


def evaluate_admin_rules(
    session_state: Dict[str, Any],
    runtime_context: Dict[str, Any],
    rules: List[Dict[str, Any]],
    return_all: bool = False,
) -> Optional[List[Dict[str, Any]]]:
    """
    Pure function: return an ordered list of eligible admin rules (candidates).
    This function remains pure (no I/O) and only uses session_state + runtime_context
    to filter and rank rules. The controller/DPE may then iterate candidates and
    apply more expensive or stateful checks (e.g., graph-based pre-filters).

    return: list of rule dicts ordered by priority (highest first). Empty list if none.
    """
    if not rules:
        return [] if return_all else None

    event = runtime_context.get("event", "AFTER_ANSWER")
    turn_index = session_state.get("turnCount", 0) or 0

    candidates: List[Dict[str, Any]] = []

    for rule in rules:
        if not rule.get("active", False):
            continue

        rule_event = rule.get("event") or "AFTER_ANSWER"
        if rule_event != event:
            continue

        min_turn = int(rule.get("min_turn", 1) or 1)
        if turn_index < min_turn:
            continue

        # Support declarative every_n_turns condition (e.g., every 3 turns)
        conditions = rule.get("conditions") or {}
        every_n = conditions.get("every_n_turns")
        if every_n is not None:
            try:
                every_n_val = int(every_n)
            except Exception:
                every_n_val = None

            # ignore invalid or non-positive values
            if every_n_val is None or every_n_val <= 0:
                pass
            else:
                # Skip for turn 0 and when current turn is not a multiple of every_n
                if turn_index == 0 or (turn_index % every_n_val) != 0:
                    continue

        # Optional: max_per_session (kalau mau batasi 1x/ session)
        max_per_session = rule.get("max_per_session")
        if max_per_session is not None:
            # Untuk sekarang, kita belum logging counter khusus per rule,
            # jadi aturan ini belum enforced. Bisa ditambah nanti di Sprint berikutnya.
            pass

        candidates.append(rule)

    if not candidates:
        logging.debug("[Proactive][AdminRules] No eligible admin rules for this turn")
        return [] if return_all else None

    # Return candidates ordered by priority (highest first)
    ordered = sorted(
        candidates,
        key=lambda r: int(r.get("priority", 0)),
        reverse=True,
    )

    logging.info(
        f"[Proactive][AdminRules] {len(ordered)} eligible rules found for turn={turn_index}"
    )
    if return_all:
        return ordered
    # Backwards-compatible single-selection behavior: return the highest-priority rule
    best = ordered[0] if ordered else None
    logging.info(
        f"[Proactive][AdminRules] Selected rule id={best.get('id')} "
        f"name={best.get('name')} for turn={turn_index}"
    )
    return best
