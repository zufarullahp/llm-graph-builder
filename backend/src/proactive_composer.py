from typing import Dict, Any, List, Optional
import json
import logging

from langchain.schema import SystemMessage, HumanMessage


logger = logging.getLogger("privas.proactive.composer")

# NOTE (refactor): static templates are deprecated.
# All runtime follow-ups should be generated via the LLM in
# `compose_followup_message_v1()`; templates remain only as examples
# and for possible future cleanup.
TEMPLATES = {
    "tip_every_3_turns_v1": (
        "Quick tip: you can ask me for examples, clarifications, or next steps anytime."
    ),
}


def resolve_template(template_key: str) -> Optional[str]:
    """(Deprecated) Resolve a static template by key. Returns None if not found.

    Templates are deprecated for runtime use — prefer the LLM composer.
    """
    return TEMPLATES.get(template_key)


def compose_followup_template(rule: Dict[str, Any], session_state: Dict[str, Any], retrieval_info: Dict[str, Any]) -> Optional[str]:
    """Deprecated: previously returned a static template string for a rule.

    This function is intentionally deprecated and now returns `None` to
    ensure the runtime uses the LLM-based composer (`compose_followup_message_v1`).
    The signature is preserved for compatibility.
    """
    try:
        logging.warning("compose_followup_template is deprecated and disabled; using LLM composer instead")
    except Exception:
        pass
    return None


def detect_language_simple(question: str, primary_answer: str) -> str:
    """
    Heuristic sangat sederhana untuk deteksi bahasa user.
    Kalau kamu sudah punya versi lain, boleh pakai yang itu, fungsi ini hanya fallback.
    """
    text = (question or "") + " " + (primary_answer or "")
    text_lower = text.lower()

    # Heuristik kasar: cari kata-kata Indonesia
    id_markers = ["apa", "bagaimana", "mengapa", "tolong", "saya", "kamu", "tidak", "bisa", "yang"]
    if any(m in text_lower for m in id_markers):
        return "id"

    # Default English
    return "en"


def compose_followup_message_v1(
    llm,
    question: str,
    standalone_question: str,
    primary_answer: str,
    reason: str,
    candidate_entities: List[Dict[str, Any]],
    graph_entities: Optional[Dict[str, Any]],
    mode: str,
    admin_rule: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Use an LLM (preferably a BIG model, e.g. gpt-4o) to generate bubble #2 text.

    Requirements (from spec):
      - Do NOT answer the original question again.
      - Do NOT apologize.
      - Do NOT repeat the main response.
      - MUST respond in the same language as the user.
      - Focus on clarification, graph insights, entity alignment, or navigation.
      - Acts as a premium, warm, first impression when appropriate.

    Output format:
      - 1 short intro line (1–2 sentences).
      - Then 2–3 bullet points starting with "- ".
    """

    user_language = detect_language_simple(question, primary_answer)

    logging.info(
        "[Proactive][Composer] start reason=%s mode=%s candidates=%s lang=%s",
        reason,
        mode,
        len(candidate_entities or []),
        user_language,
    )

    # Instruksi bahasa yang jelas ke LLM
    language_instruction_map = {
        "id": (
            "The user is interacting in Indonesian. "
            "You MUST reply strictly in natural, conversational Indonesian. "
            "Do NOT use any other language."
        ),
        "en": (
            "The user is interacting in English. "
            "You MUST reply strictly in natural, conversational English. "
            "Do NOT use any other language."
        ),
    }
    language_instruction = language_instruction_map.get(
        user_language,
        (
            "You MUST infer the user's language from the question, "
            "then reply strictly in that same language. "
            "Do NOT use any other language."
        ),
    )

    admin_hint = ""
    if admin_rule and admin_rule.get("id") == "ask_email_if_missing":
        admin_hint = admin_rule.get("llm_instruction", "")

    if admin_rule:
        logging.info(
            "[Proactive][Composer] admin_rule_applied id=%s name=%s",
            admin_rule.get("id"),
            admin_rule.get("name"),
        )
    else:
        logging.debug("[Proactive][Composer] no_admin_rule -> default proactive behavior")

    # 🔧 Build system prompt as pure string, then bungkus SystemMessage
    system_content = (
        "You are composing a SECOND chat bubble for a knowledge-graph powered assistant called Privas AI.\n"
        "This bubble is a proactive follow-up, not the main answer.\n"
        "You MUST NOT re-answer the main question.\n"
        "You MUST NOT apologize.\n"
        "You MUST NOT repeat the main answer.\n"
        f"{language_instruction}\n\n"
        "Focus only on:\n"
        "- Clarifying ambiguous entities.\n"
        "- Offering helpful graph-based navigation or insights.\n"
        "- Gently proposing next steps.\n\n"
        "Tone:\n"
        "- Warm, professional, and concise.\n"
        "- Feels premium, like a smart assistant that understands the user's context.\n\n"
        "Output requirements:\n"
        "- First, 1 short intro line (1–2 sentences max).\n"
        "- Then 2–3 bullet points, each starting with '- '.\n"
        "- No extra JSON, no metadata, only user-facing text.\n"
    )

    if admin_hint:
        system_content += (
            "\n\nAdditional instruction based on admin rule:\n"
            f"{admin_hint}\n"
            "You MUST respect the intent of this admin rule while staying natural.\n"
        )

    system_msg = SystemMessage(content=system_content)

    payload: Dict[str, Any] = {
        "reason": reason,
        "mode": mode,
        "user_language": user_language,
        "user_question": question,
        "standalone_question": standalone_question,
        "primary_answer_preview": primary_answer[:400],
        "entities": candidate_entities or [],
    }

    # Optional: kirim admin_rule id ke LLM sebagai hint
    if admin_rule:
        payload["admin_rule_id"] = admin_rule.get("id")
        payload["admin_rule_name"] = admin_rule.get("name")

    user_msg = HumanMessage(content=json.dumps(payload, ensure_ascii=False))

    try:
        llm_resp = llm.invoke([system_msg, user_msg])
        text = llm_resp.content if hasattr(llm_resp, "content") else str(llm_resp)
        text = (text or "").strip()

        logging.debug(
            "[Proactive][Composer] raw_llm_output=%s",
            text.replace("\n", " ")[:300],
        )
    except Exception as e:
        logging.error(f"[Proactive][Composer] LLM error: {e}")
        return None

    # Minimal sanity check: must contain at least 2 bullets to be useful
    bullet_count = text.count("- ")
    if bullet_count < 2:
        logging.info(
            "[Proactive][Composer] insufficient_bullets bullet_count=%s -> SKIP",
            bullet_count,
        )
        return None

    logging.info(
        "[Proactive][Composer] success length=%s bullets=%s",
        len(text),
        bullet_count,
    )
    return text
