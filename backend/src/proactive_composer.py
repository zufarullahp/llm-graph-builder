# src/proactive_composer.py
import json
import logging
from typing import Dict, Any, List, Optional

from langchain.schema import HumanMessage, SystemMessage


def detect_language_simple(question: str, primary_answer: str) -> str:
    """
    Heuristik sederhana untuk mendeteksi bahasa utama (id / en / other)
    tanpa menambah dependency eksternal.

    - Hitung beberapa kata kunci umum Indonesia vs Inggris.
    - Kalau skor Indonesia > Inggris → "id"
    - Kalau skor Inggris > Indonesia → "en"
    - Kalau imbang / sangat sedikit → "other" (biarkan LLM memutuskan,
      tapi tetap diarahkan ke bahasa pertanyaan).
    """
    text = f"{question} {primary_answer}".lower()

    id_keywords = [
        "apa", "yang", "kenapa", "bagaimana", "dimana", "kapan",
        "saya", "kamu", "anda", "tidak", "bisa", "dengan", "untuk",
        "dalam", "kalau", "jadi", "karena", "dan", "atau", "jika",
    ]
    en_keywords = [
        "what", "why", "how", "where", "when", "which",
        "i ", "you ", "can ", "cannot", "can't", "should",
        "would", "could", "please", "help", "about", "the ",
    ]

    id_score = sum(text.count(k) for k in id_keywords)
    en_score = sum(text.count(k) for k in en_keywords)

    if id_score > en_score:
        return "id"
    if en_score > id_score:
        return "en"
    return "other"


def compose_followup_message_v1(
    llm,
    question: str,
    standalone_question: str,
    primary_answer: str,
    reason: str,
    candidate_entities: List[Dict[str, Any]],
    mode: str,
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

    # Jelaskan bahasa dengan jelas ke LLM
    language_instruction = {
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
        "other": (
            "You MUST infer the user's language from the question, "
            "then reply strictly in that same language. "
            "Do NOT use any other language."
        ),
    }[user_language]

    system_msg = SystemMessage(
        content=(
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
    )

    payload = {
        "reason": reason,
        "mode": mode,
        "user_language": user_language,
        "user_question": question,
        "standalone_question": standalone_question,
        "primary_answer_preview": primary_answer[:400],
        "entities": candidate_entities,
    }

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
