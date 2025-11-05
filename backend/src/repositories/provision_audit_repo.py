from __future__ import annotations
from typing import Mapping, Any
from sqlalchemy import text
from sqlalchemy.orm import Session
import json
import logging

logger = logging.getLogger(__name__)


def log_event(db: Session, *, domain_id: str, event: str, actor: str | None = None, result: str | None = None, payload: Mapping[str, Any] | None = None):
    q = text(
        '''
        INSERT INTO "DomainProvisionAudit" ("id","domainId","event","actor","result","payload","createdAt")
        VALUES (gen_random_uuid(), :domain_id, :event, :actor, :result, CAST(:payload AS jsonb), now())
        RETURNING *
        '''
    )
    params = {
        "domain_id": domain_id,
        "event": event,
        "actor": actor,
        "result": result,
        "payload": json.dumps(payload) if payload is not None else None,
    }
    try:
        row = db.execute(q, params).mappings().first()
        return row
    except Exception as e:
        # Audit write must not break main flow; log and return None
        logger.warning("Failed to write DomainProvisionAudit: %s", e)
        try:
            # attempt rollback of the audit insert transaction fragment if needed
            db.rollback()
        except Exception:
            pass
        return None
