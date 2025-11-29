import logging
import os
from typing import Tuple, Optional

from dotenv import load_dotenv

load_dotenv()


from src.history_graph import _run_query

# module-level logger
logger = logging.getLogger("privas.email_composer")

# Optional OpenAI integration (best-effort)
try:
    import openai  # type: ignore
except Exception:
    openai = None  # type: ignore


def _fetch_recent_session_text(graph, session_id: str, limit: int = 1) -> str:
    """Return concatenated recent response texts for the session (best-effort)."""
    try:
        # Use a simple, reliable query to fetch recent Response nodes for the session.
        # Avoid variable-length relationship parameters (e.g. "*0..$limit") since many
        # Cypher engines do not accept a parameter for the range bound. Instead, fetch
        # responses directly and apply LIMIT.
        cypher = (
            "MATCH (s:Session {id:$sessionId})-[:LAST_RESPONSE]->(r:Response)<-[*0..2]-(r2:Response)\n"
            "RETURN r2.output as text, r.createdAt AS createdAt\n"
            "ORDER BY r.createdAt DESC LIMIT $limit"
        )
        rows = _run_query(graph, cypher, {"sessionId": session_id, "limit": limit}, access="READ")
        texts = []
        for r in rows:
            t = r.get("text") or ""
            if t:
                texts.append(t)
        return "\n\n".join(reversed(texts))
    except Exception:
        logging.exception("Failed to fetch recent session text")
        return ""


def compose_email_content(
    graph,
    session_id: str,
    resp_id: Optional[str],
    recipient_email: str,
    model: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Compose (subject, body) using recent session/context and an LLM (best-effort).
    Falls back to a short deterministic template on any failure.
    """
    try:
        logging.debug("Composing email content for session=%s recipient=%s", session_id, recipient_email)
        recent_text = _fetch_recent_session_text(graph, session_id, limit=6)

        resp_snippet = ""
        try:
            if resp_id:
                cypher = "MATCH (s:Session {id:$sessionId})-[q:LAST_RESPONSE]->(r:Response) RETURN r.input AS text LIMIT 1"
                try:
                    rows = _run_query(graph, cypher, {"sessionId": session_id}, access="READ")
                except Exception:
                    rows = _run_query(graph, cypher, {"sessionId": session_id}, access="READ")
                if rows and rows[0].get("text"):
                    resp_snippet = rows[0]["text"]
        except Exception:
            logging.debug("Could not fetch Response node snippet; continuing without it")

        system_prompt = (
            "You are an assistant that writes short, friendly email summaries for users "
            "based on the recent conversation. Keep the subject short (under 60 chars) "
            "and body to one concise paragraph and a closing line. Avoid including PII beyond confirming the recipient email."
        )

        user_prompt = (
            f"Recipient: {recipient_email}\n\n"
            "Recent conversation (most recent last):\n"
            f"{recent_text}\n\n"
            "Response snippet (the saved response that triggered this email):\n"
            f"{resp_snippet}\n\n"
            "Produce:\n1) Subject on a single line.\n2) Body paragraph (one or two short paragraphs)."
        )

        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
        model = model or os.getenv("EMAIL_COMPOSER_MODEL") or "gpt-4o-mini"
        if openai and api_key:
            try:
                # New SDK pattern: instantiate client and call chat completions
                # e.g. client = openai.OpenAI(api_key=...)
                try:
                    client = openai.OpenAI(api_key=api_key)
                except Exception:
                    # fallback in case the module exposes a different name/constructor
                    client = openai.OpenAI()

                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=400,
                    temperature=0.2,
                )

                # Try structured access then mapping-like access for compatibility
                text = ""
                try:
                    # object-style
                    text = resp.choices[0].message.content.strip()
                except Exception:
                    try:
                        # dict-style
                        text = resp["choices"][0]["message"]["content"].strip()
                    except Exception:
                        # last-resort string conversion
                        text = str(resp).strip()

                parts = text.split("\n\n", 1)
                subject = parts[0].strip().replace("\n", " ") if parts else ""
                body = parts[1].strip() if len(parts) > 1 else ""
                if not subject:
                    subject = "Your Privas AI summary"
                if not body:
                    body = f"Thanks — we'll send summaries to {recipient_email}."
                return subject, body
            except Exception:
                logging.exception("LLM composition failed, falling back to template")

        short = (resp_snippet or recent_text or "").strip().split("\n")[0][:80]
        subject = f"Your Privas AI summary — {short}" if short else "Your Privas AI summary"
        body = (
            f"Thanks — we'll send summaries to {recipient_email}.\n\nSummary note: {short}"
            if short
            else f"Thanks — we'll send summaries to {recipient_email}."
        )
        logging.debug("Composed fallback email subject=%s body=%s", subject, body)
        return subject, body

    except Exception:
        logging.exception("compose_email_content unexpected failure, using fallback")
        return "Your Privas AI summary", f"Thanks — we'll send summaries to {recipient_email}."
