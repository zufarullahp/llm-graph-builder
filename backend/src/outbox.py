import json
import uuid
import logging
from datetime import datetime
from typing import Optional, Any, Dict

from sqlalchemy import text

from src.db_psql.postgres import engine
logger = logging.getLogger("privas.outbox")


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def enqueue_email_job(
    session_id: str,
    recipient_email: str,
    subject: str,
    body: str,
    payload: Optional[Dict[str, Any]] = None,
    rule_instance_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    max_attempts: int = 5,
) -> Optional[str]:
    """Insert an email job into Postgres outbox.

    Returns the job id (string) if inserted, or None if conflict/failed.
    Uses plain SQL with engine.begin() and ON CONFLICT DO NOTHING for idempotency.
    """
    # deterministic idempotency key if not provided and rule_instance_id available
    if not idempotency_key and rule_instance_id:
        idempotency_key = f"email:{session_id}:{rule_instance_id}"

    job_id = str(uuid.uuid4())
    payload_json = json.dumps(payload or {})

    sql = text(
        """
        INSERT INTO email_jobs (
            id, session_id, rule_instance_id, recipient_email, subject, body, payload,
            status, attempts, max_attempts, next_retry_at, last_error, idempotency_key, created_at, updated_at
        ) VALUES (
            :id, :session_id, :rule_instance_id, :recipient_email, :subject, :body, :payload,
            'pending', 0, :max_attempts, NULL, NULL, :idempotency_key, now(), now()
        )
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id
        """
    )

    params = {
        "id": job_id,
        "session_id": session_id,
        "rule_instance_id": rule_instance_id,
        "recipient_email": recipient_email,
        "subject": subject,
        "body": body,
        "payload": payload_json,
        "max_attempts": max_attempts,
        "idempotency_key": idempotency_key,
    }

    try:
        with engine.begin() as conn:
            res = conn.execute(sql, params)
            row = res.fetchone()
            if row and row[0]:
                return row[0]
            # conflict or nothing inserted
            logging.info(f"Outbox: job not inserted due to idempotency (key={idempotency_key})")
            return None
    except Exception as e:
        logging.exception(f"Failed to enqueue email job: {e}")
        return None
