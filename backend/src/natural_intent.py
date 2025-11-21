import re
from typing import Dict, Any, List, Optional
import json
import logging

try:
    from langchain_core.messages import SystemMessage, HumanMessage
except Exception:
    # langchain may not be available in some test environments; keep functions
    # import-safe and fail gracefully at runtime if LLM usage is required.
    SystemMessage = None
    HumanMessage = None

# Natural Intent Detector (rule-based v1)
# Returns dict: {intent, confidence, slots, requires_retrieval, handler_name}

# Regex patterns
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_REGEX = re.compile(r"\b(\+?\d[\d\s\-]{6,})\b")


def _normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    t = text.strip()
    # collapse spaces
    t = re.sub(r"\s+", " ", t)
    return t


def _is_short_utterance(text: str) -> bool:
    tokens = text.split()
    return len(tokens) <= 4 and len(text) <= 40


def compute_nid_features(text_raw: Optional[str]) -> Dict[str, Any]:
    """Compute a set of simple, reusable features for an utterance.

    Returned keys include:
      - is_short: bool (existing short heuristic)
      - is_question: bool
      - has_email: bool
      - has_phone: bool
      - has_contact_word: bool (email/phone/kontak/hp/mail)
      - token_count: int
      - char_length: int
    """
    text_raw = text_raw or ""
    text = _normalize(text_raw)
    tl = text.lower()

    # token/char counts
    tokens = text.split()
    token_count = len(tokens)
    char_length = len(text)

    # question heuristic
    def _looks_like_question_local(t: str) -> bool:
        if "?" in t:
            return True
        interrogatives = [
            "what",
            "when",
            "where",
            "why",
            "how",
            "who",
            "which",
            "do",
            "does",
            "did",
            "is",
            "are",
            "can",
            "could",
            "should",
            "would",
        ]
        for w in interrogatives:
            if t.startswith(w + " "):
                return True
        return False

    has_email = bool(EMAIL_REGEX.search(text_raw))
    has_phone = bool(PHONE_REGEX.search(text_raw))

    contact_words = ["email", "mail", "phone", "hp", "kontak", "contact", "no hp", "nomor"]
    has_contact_word = _contains_any(tl, contact_words)

    features = {
        "is_short": _is_short_utterance(tl),
        "is_question": _looks_like_question_local(tl),
        "has_email": has_email,
        "has_phone": has_phone,
        "has_contact_word": has_contact_word,
        "token_count": token_count,
        "char_length": char_length,
    }
    return features


def _contains_any(text: str, phrases: List[str]) -> bool:
    tl = text.lower()
    return any(p.lower() in tl for p in phrases)


def _contains_word(text: str, words: List[str]) -> bool:
    """Return True if any word appears as a separate token in text (word-boundary match)."""
    import re
    tl = text.lower()
    for w in words:
        if re.search(r"\b" + re.escape(w.lower()) + r"\b", tl):
            return True
    return False


def detect_natural_intent(
    text_raw: Optional[str],
    session_id: Optional[str] = None,
    history_preview: Optional[str] = None,
) -> Dict[str, Any]:
    """Detect one of the 11 intents (rule-based v1).

    Returns:
      {
        "intent": str,
        "confidence": float,
        "slots": dict,
        "requires_retrieval": bool,
        "handler_name": Optional[str],
      }
    """
    # Normalize text and compute shared precomputed features
    text = _normalize(text_raw)
    tl = text.lower()
    features = compute_nid_features(text_raw)

    slots: Dict[str, Any] = {}

    # 11. No-Content / Empty
    if not tl or tl.strip() == "":
        return {
            "intent": "no_content",
            "confidence": 1.0,
            "slots": {},
            "requires_retrieval": False,
            "handler_name": "handle_no_content",
            "features": features,
        }

    # Affirmative / Consent (tuned): require short utterance, not a question,
    # not an explicit email, and not an immediate 'please' after the affirmative
    affirmative_words = ["yes", "ya", "sure", "ok", "boleh", "iya"]
    tokens = tl.split()
    second_token = tokens[1] if len(tokens) > 1 else None
    if (
        features.get("is_short")
        and not features.get("is_question")
        and not features.get("has_email")
        and _contains_word(tl, affirmative_words)
        and (second_token is None or second_token != "please")
    ):
        return {
            "intent": "affirmative",
            "confidence": 0.9,
            "slots": {},
            "requires_retrieval": False,
            "handler_name": "handle_affirmative",
            "features": features,
        }

    # Attachment intent - look for explicit words (metadata not available here)
    if _contains_any(tl, ["here is the file", "here's the file", "i uploaded", "tolong analisa file", "ini file", "ini pdf"]):
        return {
            "intent": "upload_attachment",
            "confidence": 0.95,
            "slots": {"has_attachment": False},
            "requires_retrieval": False,
            "handler_name": "handle_upload",
            "features": features,
        }

    # Contact Sharing: email — require both an email token and contact/email keywords
    if features.get("has_email") and features.get("has_contact_word"):
        email_m = EMAIL_REGEX.search(text_raw)
        if email_m:
            slots["email"] = email_m.group(0)
            return {
                "intent": "contact_sharing",
                "confidence": 0.95,
                "slots": slots,
                "requires_retrieval": False,
                "handler_name": "handle_contact_sharing",
                "features": features,
            }

    # Contact: phone — require phone token and contact keywords
    if features.get("has_phone") and features.get("has_contact_word"):
        phone_m = PHONE_REGEX.search(text_raw)
        if phone_m:
            slots["phone"] = phone_m.group(0)
            return {
                "intent": "contact_sharing",
                "confidence": 0.9,
                "slots": slots,
                "requires_retrieval": False,
                "handler_name": "handle_contact_sharing",
                "features": features,
            }

    # Contact: name intro (softer rule) — ensure it's not a question
    if not features.get("is_question") and _contains_any(tl, ["my name is ", "nama saya ", "saya bernama "]):
        for p in ["my name is ", "nama saya ", "saya bernama "]:
            idx = tl.find(p)
            if idx != -1:
                name = text[idx + len(p) :].split(".")[0].split(",")[0].strip()
                if name:
                    slots["name"] = name
                    return {
                        "intent": "contact_sharing",
                        "confidence": 0.7,
                        "slots": slots,
                        "requires_retrieval": False,
                        "handler_name": "handle_contact_sharing",
                        "features": features,
                    }

    # Task Meta
    if _contains_any(tl, ["save this", "save conversation", "clear history", "delete session", "reset chat", "change mode", "toggle proactive", "matikan proaktif", "hapus sesi", "ganti mode"]):
        # map to a simple command slot
        slots["command"] = tl
        return {
            "intent": "task_meta",
            "confidence": 0.95,
            "slots": slots,
            "requires_retrieval": False,
            "handler_name": "handle_task_meta",
            "features": features,
        }

    # Explicit proactive intent
    if _contains_any(tl, [
        "help me navigate",
        "what's next",
        "what is the next step",
        "what should i do",
        "what should i do next",
        "lanjut",
        "lanjut dong",
        "step selanjutnya",
        "kasih ide lagi",
        "give me more ideas",
        "next step",
        "next steps",
        "next step please",
        "bantu saya",
        "what else",
    ]):
        return {
            "intent": "explicit_proactive_intent",
            "confidence": 0.9,
            "slots": {},
            "requires_retrieval": False,
            "handler_name": "handle_explicit_proactive",
            "features": features,
        }

    # Greeting / Closing
    greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "halo", "hallo", "selamat pagi", "assalamualaikum", "yo", "bro"]
    closings = ["bye", "goodbye", "see you", "sampai jumpa", "terima kasih banyak", "makasih ya", "thank you", "good night", "talk to you"]
    # Treat short salutations as greeting/closing, or detect explicit sign-offs
    if (not features.get("is_question")) and (_contains_word(tl, greetings) or _contains_word(tl, closings) or _contains_any(tl, ["good night", "talk to you", "see you later"])):
        # If the message contains other substantial content beyond a salutation, don't mark it as only greeting.
        # Keep simple: prefer greeting when it's short or contains explicit sign-off phrases.
        if features.get("is_short") or _contains_any(tl, ["good night", "talk to you", "see you later"]):
            return {
                "intent": "greeting_closing",
                "confidence": 0.95,
                "slots": {},
                "requires_retrieval": False,
                "handler_name": "handle_greeting",
                "features": features,
            }

    # Clarification
    clarification_phrases = [
        "what do you mean",
        "what does that mean",
        "explain more",
        "explain again",
        "can you explain it in simpler words",
        "can you repeat the last answer",
        "what is an example",
        "give me an example",
        "can you elaborate",
        "maksudnya apa",
        "jelaskan lagi",
        "contoh dong",
    ]
    if _contains_any(tl, clarification_phrases):
        return {
            "intent": "clarification",
            "confidence": 0.85,
            "slots": {},
            "requires_retrieval": False,
            "handler_name": "handle_clarification",
            "features": features,
        }
    # Feedback
    feedback_phrases = [
        "that's wrong",
        "not correct",
        "incorrect",
        "i disagree",
        "the answer isn't clear",
        "ulang lagi",
        "itu salah",
        "jawabannya salah",
        "not helpful",
        "not useful",
        "very clear",
        "you are stupid",
    ]
    if _contains_any(tl, feedback_phrases):
        return {
            "intent": "feedback",
            "confidence": 0.9,
            "slots": {},
            "requires_retrieval": False,
            "handler_name": "handle_feedback",
            "features": features,
        }

    # Small talk / Social — only when it's a short utterance. Allow a few short question forms.
    small_talk_phrases_en = [
        "ok",
        "okay",
        "great",
        "nice",
        "that's it",
        "all good",
        "good afternoon",
        "thanks",
        "you are very helpful",
        "this is interesting",
        "that's cool",
    ]
    small_talk_phrases_id = ["makasih", "terima kasih", "sip", "siap", "mantap", "oke", "udah cukup", "gitu aja"]
    # Permit short question variants that are small-talk
    small_talk_question_allow = ["how are you", "are you human", "lagi ngapain", "ngapain"]
    if features.get("is_short") and (((not features.get("is_question")) and (_contains_any(tl, small_talk_phrases_en) or _contains_any(tl, small_talk_phrases_id))) or _contains_any(tl, small_talk_question_allow)):
        return {
            "intent": "small_talk",
            "confidence": 0.95,
            "slots": {},
            "requires_retrieval": False,
            "handler_name": "handle_small_talk",
            "features": features,
        }

    # Personal context — conservative: only non-question longer first-person
    if not features.get("is_question"):
        if (" i " in f" {tl} " or tl.startswith("i ") or tl.startswith("i'm ") or tl.startswith("im ")) and len(tl.split()) >= 8:
            return {
                "intent": "personal_context",
                "confidence": 0.7,
                "slots": {"raw_context": text_raw},
                "requires_retrieval": False,
                "handler_name": "handle_personal_context",
                "features": features,
            }
        if _contains_any(tl, ["saya ", "aku ", "gue ", "klien saya"]) and len(tl.split()) >= 8:
            return {
                "intent": "personal_context",
                "confidence": 0.7,
                "slots": {"raw_context": text_raw},
                "requires_retrieval": False,
                "handler_name": "handle_personal_context",
                "features": features,
            }

    

    # Non-retrieval information inquiry: bot/capabilities/pricing
    if _contains_any(tl, ["how do i use this bot", "how does this bot work", "what can you do", "how much do you charge", "berapa biaya", "bagaimana cara pakai bot ini"]):
        return {
            "intent": "non_retrieval_inquiry",
            "confidence": 0.85,
            "slots": {},
            "requires_retrieval": False,
            "handler_name": "handle_non_retrieval_inquiry",
            "features": features,
        }

    # Fallback: unknown -> requires retrieval
    return {
        "intent": "unknown",
        "confidence": 0.3,
        "slots": {},
        "requires_retrieval": True,
        "handler_name": None,
        "features": features,
    }


def classify_intent_with_llm(llm, text: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Use an LLM to classify intent when rule-based falls through.

    Returns the same dict shape as detect_natural_intent but can include
    a richer 'confidence' and 'requires_retrieval' decision.
    """
    # If langchain messages are not importable, return unknown -> retrieval
    if SystemMessage is None or HumanMessage is None:
        logging.debug("LLM intent classifier unavailable (langchain not installed)")
        return {"intent": "unknown", "confidence": 0.0, "slots": {}, "requires_retrieval": True, "handler_name": None}

    try:
        system = SystemMessage(
            content=(
                "You are an intent classifier. Given a single user utterance, "
                "return a JSON object with keys: intent, confidence (0-1), "
                "requires_retrieval (true/false), handler_name (or null), and optional slots. "
                "Allowed intents: unknown, contact_sharing, affirmative, negative, upload_attachment, "
                "task_meta, explicit_proactive_intent, small_talk, clarification, feedback, personal_context, "
                "greeting_closing, non_retrieval_inquiry. Be conservative: if unsure, set requires_retrieval=true. "
                "Respond ONLY with the JSON object and no extra text."
            )
        )

        human = HumanMessage(content=f"Utterance: {text}")
        resp = llm.invoke([system, human])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        raw = (raw or "").strip()

        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = raw[start:end+1]
            try:
                data = json.loads(candidate)
                intent = data.get("intent") or "unknown"
                confidence = float(data.get("confidence") or 0.0)
                requires_retrieval = bool(data.get("requires_retrieval") or False)
                handler_name = data.get("handler_name")
                slots = data.get("slots") or {}
                return {
                    "intent": intent,
                    "confidence": confidence,
                    "slots": slots,
                    "requires_retrieval": requires_retrieval,
                    "handler_name": handler_name,
                }
            except Exception as e:
                logging.debug(f"LLM intent classifier JSON parse error: {e} raw={raw[:200]}")

        return {"intent": "unknown", "confidence": 0.2, "slots": {}, "requires_retrieval": True, "handler_name": None}
    except Exception as e:
        logging.error(f"LLM intent classification failed: {e}")
        return {"intent": "unknown", "confidence": 0.0, "slots": {}, "requires_retrieval": True, "handler_name": None}


def prepare_nid_llm_payload(text_raw: str, features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Prepare a structured payload for future LLM-based NID disambiguation.

        This function returns a JSON-serializable dict containing the original
        utterance, the computed features (see `compute_nid_features`) and optional
        minimal context (e.g. last bot message, pending actions). The contract is
        intentionally simple so an LLM prompt can consume it directly.

        Example output:
            {
                "text": "yes please simpler explanation",
                "features": { ... },
                "context": {"last_bot_message": "Would you like me to save your email?"}
            }

        Note: this function does not call any LLM. It's a helper to standardize the
        payload shape for future classifier integrations.
        """
        return {
                "text": text_raw,
                "features": features,
                "context": context or {},
        }
