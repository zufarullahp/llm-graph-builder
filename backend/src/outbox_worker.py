import os
import time
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
from typing import List

from sqlalchemy import text

from src.db_psql.postgres import engine
from src.core.config import get_settings
from dotenv import load_dotenv

load_dotenv()


SETTINGS = get_settings()


def _send_email_smtp(recipient: str, subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", 587))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    from_addr = os.getenv("SMTP_FROM", username)

    if not host:
        raise RuntimeError("SMTP_HOST not configured")

    # Tentukan mode protokol berdasarkan port
    if port == 465:
        mode = "SSL"
    elif port == 587:
        mode = "STARTTLS"
    else:
        mode = "PLAIN"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = recipient
    msg.set_content(body)

    start_time = time.time()
    logging.info(
        "[OUTBOX] Preparing SMTP send → host=%s port=%s mode=%s to=%s subject=%s",
        host, port, mode, recipient, subject,
    )

    try:
        # Port 465 → implicit SSL
        if mode == "SSL":
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                if username and password:
                    smtp.login(username, password)
                smtp.send_message(msg)

        # Port 587 → STARTTLS
        elif mode == "STARTTLS":
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                if username and password:
                    smtp.login(username, password)
                smtp.send_message(msg)

        # Lainnya → plain
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                if username and password:
                    smtp.login(username, password)
                smtp.send_message(msg)

        duration = (time.time() - start_time) * 1000
        logging.info(
            "[OUTBOX] Email sent successfully → %s (%d ms) mode=%s",
            recipient,
            duration,
            mode,
        )

    except Exception as e:
        duration = (time.time() - start_time) * 1000
        logging.error(
            "[OUTBOX] SMTP send FAILED → %s (%d ms) mode=%s error=%s",
            recipient,
            duration,
            mode,
            str(e),
        )
        raise


def claim_jobs(batch: int = 10) -> List[dict]:
    """Atomically claim up to `batch` pending jobs and mark them processing.
    Returns a list of dict rows.
    """
    sql = text(
        """
        WITH cte AS (
          SELECT id FROM email_jobs
          WHERE status = 'pending' AND (next_retry_at IS NULL OR next_retry_at <= now())
          ORDER BY created_at
          LIMIT :batch
          FOR UPDATE SKIP LOCKED
        )
        UPDATE email_jobs SET status = 'processing', updated_at = now()
        WHERE id IN (SELECT id FROM cte)
        RETURNING *;
        """
    )
    with engine.begin() as conn:
        res = conn.execute(sql, {"batch": batch})
        rows = [dict(row._mapping) for row in res.fetchall()]
    return rows


def mark_job_sent(job_id: str) -> None:
    sql = text("UPDATE email_jobs SET status='sent', sent_at=now(), updated_at=now() WHERE id = :id")
    with engine.begin() as conn:
        conn.execute(sql, {"id": job_id})


def mark_job_failed(job_id: str, attempts: int, max_attempts: int, backoff_seconds: int, last_error: str) -> None:
    next_retry = None
    status = 'pending'
    if attempts >= max_attempts:
        status = 'failed'
    else:
        next_retry = datetime.utcnow() + timedelta(seconds=backoff_seconds)

    sql = text(
        "UPDATE email_jobs SET attempts = :attempts, last_error = :last_error, next_retry_at = :next_retry, status = :status, updated_at = now() WHERE id = :id"
    )
    with engine.begin() as conn:
        conn.execute(sql, {"attempts": attempts, "last_error": last_error, "next_retry": next_retry, "status": status, "id": job_id})


def worker_loop(batch: int = 5, poll_interval: int = 5, base_backoff: int = 30):
    logging.info("Outbox worker starting: batch=%s poll_interval=%s", batch, poll_interval)
    while True:
        try:
            jobs = claim_jobs(batch)
            if not jobs:
                time.sleep(poll_interval)
                continue

            for j in jobs:
                job_id = j.get("id")
                recipient = j.get("recipient_email")
                subject = j.get("subject") or ""
                body = j.get("body") or ""
                attempts = (j.get("attempts") or 0) + 1
                max_attempts = j.get("max_attempts") or 5

                try:
                    _send_email_smtp(recipient, subject, body)
                    mark_job_sent(job_id)
                    logging.info("Outbox: sent job=%s to=%s", job_id, recipient)
                except Exception as e:
                    # exponential backoff
                    backoff = base_backoff * (2 ** (attempts - 1))
                    logging.exception("Outbox: send failed job=%s attempt=%s error=%s", job_id, attempts, str(e))
                    mark_job_failed(job_id, attempts, max_attempts, backoff, str(e))

        except Exception:
            logging.exception("Outbox worker encountered unexpected error")
            time.sleep(poll_interval)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=int(os.getenv("OUTBOX_BATCH", "5")))
    parser.add_argument("--poll", type=int, default=int(os.getenv("OUTBOX_POLL", "5")))
    parser.add_argument("--base-backoff", type=int, default=int(os.getenv("OUTBOX_BASE_BACKOFF", "30")))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if args.once:
        jobs = claim_jobs(args.batch)
        for j in jobs:
            job_id = j.get("id")
            recipient = j.get("recipient_email")
            subject = j.get("subject") or ""
            body = j.get("body") or ""
            try:
                _send_email_smtp(recipient, subject, body)
                mark_job_sent(job_id)
                print(f"Sent job={job_id}")
            except Exception as e:
                logging.exception("Failed to send job once: %s", e)
        exit(0)

    worker_loop(batch=args.batch, poll_interval=args.poll, base_backoff=args.base_backoff)
