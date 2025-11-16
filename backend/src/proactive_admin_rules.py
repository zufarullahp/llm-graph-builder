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
) -> Optional[Dict[str, Any]]:
    """
    Pure function: pilih SATU rule admin yang paling cocok.
    Tidak melakukan I/O, hanya pakai state + context.

    return:
      - dict rule terpilih (sudah siap dikirim ke DPE/Composer), atau
      - None kalau tidak ada yang eligible.
    """
    if not rules:
        return None

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

        # Optional: max_per_session (kalau mau batasi 1x/ session)
        max_per_session = rule.get("max_per_session")
        if max_per_session is not None:
            # Untuk sekarang, kita belum logging counter khusus per rule,
            # jadi aturan ini belum enforced. Bisa ditambah nanti di Sprint berikutnya.
            pass

        candidates.append(rule)

    if not candidates:
        logging.debug("[Proactive][AdminRules] No eligible admin rules for this turn")
        return None

    # Pilih berdasarkan priority tertinggi
    best = sorted(
        candidates,
        key=lambda r: int(r.get("priority", 0)),
        reverse=True,
    )[0]

    logging.info(
        f"[Proactive][AdminRules] Selected rule id={best.get('id')} "
        f"name={best.get('name')} for turn={turn_index}"
    )
    return best
