# src/proactive_dpe.py
import json
import logging
from typing import Dict, Any, List, Tuple

from langchain.schema import HumanMessage, SystemMessage


def extract_top_entities(retrieval_info: Dict[str, Any], top_k: int = 3) -> List[Dict[str, Any]]:
    """
    Extract top entities from retrieval_info["entities"].

    NOTE:
    - Saat ini retrieval_info["entities"] di pipeline kamu berisi struktur:
        { "entityids": [...], "relationshipids": [...] }
      jadi extract ini hanya bikin ringkasan ringan, bukan scoring beneran.
    - Nanti kalau kamu punya struktur salience yang lebih kaya, mapping cukup di sini.

    Output selalu:
      [ {id, label, type, salience}, ... ]
    """
    raw = retrieval_info.get("entities") or {}
    entities: List[Dict[str, Any]] = []

    # Kalau bentuknya sudah dictionary yg lebih kaya di masa depan, mapping di sini saja.
    for key, val in raw.items():
        if isinstance(val, dict):
            label = val.get("label") or key
            ent_type = val.get("type") or val.get("category") or "Unknown"
            salience = val.get("salience") or val.get("score") or 0.0
        else:
            # fallback untuk list/primitive (contoh: entityids, relationshipids)
            label = str(key)
            ent_type = "Unknown"
            salience = 0.0

        entities.append(
            {
                "id": key,
                "label": label,
                "type": ent_type,
                "salience": float(salience),
            }
        )

    entities.sort(key=lambda e: e["salience"], reverse=True)
    return entities[:top_k]


def evaluate_proactive_decision_v1(
    llm,
    session_state: Dict[str, Any],
    question: str,
    standalone_question: str,
    primary_answer: str,
    retrieval_info: Dict[str, Any],
    mode: str,
) -> Tuple[bool, str, Dict[str, Any], List[Dict[str, Any]]]:
    """
    DPE v1:
      - Menggunakan LLM sebagai policy engine (classifier).
      - Untuk turn 1: WAJIB default ke ALLOW (welcome follow-up) jika ada konteks.
      - Menggunakan sinyal entities + sources sebagai konteks.
    Returns:
      (allow, reason, trigger_meta, candidate_entities)
    """
    turn_count = session_state.get("turnCount", 0) or 0
    proactive_enabled = session_state.get("proactive_enabled", True)
    top_entities = extract_top_entities(retrieval_info, top_k=3)
    sources = retrieval_info.get("sources") or []

    logging.debug(
        f"[Proactive][DPE] start turn={turn_count} enabled={proactive_enabled} "
        f"entities={len(top_entities)} sources={len(sources)} mode={mode}"
    )

    # Kalau proactive OFF → langsung SKIP, tapi tetap balikin meta
    if not proactive_enabled:
        logging.info("[Proactive][DPE] proactive_disabled -> SKIP")
        return False, "proactive_disabled", {
            "turnCount": turn_count,
            "entities": top_entities,
            "sources_count": len(sources),
        }, top_entities

    has_any_context = bool(top_entities) or bool(sources)

    policy_system = SystemMessage(
        content=(
            "You are a deterministic policy engine for a chatbot proactive follow-up system.\n"
            "You MUST respond ONLY with strict JSON, no extra text.\n"
            'Valid JSON shape (single object):\n'
            '{ "decision": "ALLOW" or "SKIP", "reason": "<short_reason>" }\n\n'
            "Hard rules:\n"
            "- If this is the FIRST user message in the session (turn_count == 1), "
            "  and there is any meaningful context (entities or sources), you MUST choose decision = \"ALLOW\".\n"
            "- If proactive mode is disabled, you MUST choose decision = \"SKIP\".\n"
            "- Do NOT attempt to answer the user question. Only decide whether to send a second proactive bubble.\n"
            "- Do NOT wrap the JSON in markdown code fences.\n"
            "- Do NOT add explanation outside the JSON object.\n"
        )
    )

    user_payload = {
        "turn_count": turn_count,
        "mode": mode,
        "has_any_context": has_any_context,
        "entities": top_entities,
        "sources_count": len(sources),
        "question": question,
        "standalone_question": standalone_question,
        "primary_answer_preview": primary_answer[:400],
    }

    user_msg = HumanMessage(content=json.dumps(user_payload, ensure_ascii=False))

    try:
        llm_resp = llm.invoke([policy_system, user_msg])
        raw = llm_resp.content if hasattr(llm_resp, "content") else str(llm_resp)
        raw = (raw or "").strip()

        # 🔧 Sanitasi umum: buang markdown code fences ```json ... ```
        if raw.startswith("```"):
            # buang leading & trailing backticks
            raw = raw.strip("`").strip()
            # jika diawali kata 'json' atau 'JSON', buang
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()

        # 🔧 Ekstrak objek JSON pertama kalau ada noise di luar
        candidate = raw
        if not (candidate.lstrip().startswith("{") and candidate.rstrip().endswith("}")):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = candidate[start:end + 1]

        logging.debug(
            "[Proactive][DPE] raw_policy_output sanitized=%s",
            candidate.replace("\n", " ")[:300],
        )

        data = json.loads(candidate)
        decision = (data.get("decision") or "").upper()
        reason = data.get("reason") or "unspecified"

        # 🔒 Safety net: enforce arch rule on first message
        if turn_count == 1 and has_any_context:
            if decision != "ALLOW":
                logging.info(
                    "[Proactive][DPE] override_first_message old_decision=%s new_decision=ALLOW",
                    decision,
                )
            decision = "ALLOW"
            if not reason:
                reason = "first_message_welcome"

        allow = decision == "ALLOW"
        logging.info(
            "[Proactive][DPE] decision=%s reason=%s turn=%s has_context=%s",
            decision,
            reason,
            turn_count,
            has_any_context,
        )

        trigger_meta = {
            "turnCount": turn_count,
            "entities": top_entities,
            "sources_count": len(sources),
            "raw_policy_output": data,
        }
        return allow, reason, trigger_meta, top_entities

    except Exception as e:
        logging.error(f"[Proactive][DPE] Failed to parse policy output: {e}")
        logging.debug("[Proactive][DPE] raw_policy_output_unparsed=%s", raw[:300] if 'raw' in locals() else "")

        # fallback: hanya welcome di first-message kalau ada konteks
        if turn_count == 1 and has_any_context:
            logging.info(
                "[Proactive][DPE] fallback_first_message_welcome error=%s", str(e)
            )
            return True, "first_message_welcome_fallback", {
                "turnCount": turn_count,
                "entities": top_entities,
                "sources_count": len(sources),
                "error": str(e),
            }, top_entities

        return False, "policy_error_skip", {
            "turnCount": turn_count,
            "entities": top_entities,
            "sources_count": len(sources),
            "error": str(e),
        }, top_entities
