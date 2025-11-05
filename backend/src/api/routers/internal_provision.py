from __future__ import annotations

from typing import Optional, Mapping, Any

from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.db_psql.postgres import get_db
from src.repositories import domain_repo, domain_graph_repo, tenant_repo
from src.repositories import provision_audit_repo
from src.services import domain_service

cfg = get_settings()
router = APIRouter()


class ProvisionRequest(BaseModel):
    domainId: str


@router.post("/api/internal/provision", status_code=status.HTTP_202_ACCEPTED)
def provision_domain(
    payload: ProvisionRequest,
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
    db: Session = Depends(get_db),
):
    # validate token
    if not cfg.INTERNAL_PROVISION_TOKEN or x_internal_token != cfg.INTERNAL_PROVISION_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    domain_id = payload.domainId

    # check domain exists
    domain = domain_repo.get_by_id(db, domain_id)
    if not domain:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found")

    # ensure tenant exists for domain owner (best-effort)
    owner_user_id = domain.get("userId")
    if owner_user_id:
        tenant = tenant_repo.find_by_owner_user_id(db, owner_user_id)
        if not tenant:
            # create a default tenant record; best-effort values
            tenant = tenant_repo.create(db, name="Workspace", owner_user_id=owner_user_id, owner_email="", plan="STANDARD", is_active=True)
            db.commit()

    # check/create DomainGraph idempotently
    dg = domain_graph_repo.get_by_domain_id(db, domain_id)
    idemp = None
    if not dg:
        try:
            idemp = domain_service._gen_idempotency_key()
            domain_graph_repo.create_initial(db, domain_id=domain_id, idempotency_key=idemp)
            db.commit()
            provision_audit_repo.log_event(db, domain_id=domain_id, event="provision_requested", actor="service_token", result="accepted", payload={"idempotencyKey": idemp})
        except Exception:
            db.rollback()
            # possible race: someone else created the row concurrently
            dg = domain_graph_repo.get_by_domain_id(db, domain_id)
            if not dg:
                provision_audit_repo.log_event(db, domain_id=domain_id, event="provision_requested", actor="service_token", result="failed", payload={})
                raise
    else:
        # already exists
        provision_audit_repo.log_event(db, domain_id=domain_id, event="provision_requested", actor="service_token", result="already_exists", payload={"provisionStatus": dg.get("provisionStatus")})

    # enqueue background job using existing executor/wrapper
    try:
        # submit to executor; wrapper will open its own DB session and handle commits
        domain_service._EXECUTOR.submit(domain_service._provision_job_wrapper, domain_id)
    except Exception:
        provision_audit_repo.log_event(db, domain_id=domain_id, event="enqueue_failed", actor="service_token", result="failed", payload={})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to enqueue provision job")

    return {"domainId": domain_id, "provisionStatus": "provisioning", "idempotencyKey": idemp}


@router.get("/api/domains/{domainId}/provision-status", status_code=status.HTTP_200_OK)
def get_provision_status(
    domainId: str,
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
    db: Session = Depends(get_db),
):
    if not cfg.INTERNAL_PROVISION_TOKEN or x_internal_token != cfg.INTERNAL_PROVISION_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    dg = domain_graph_repo.get_by_domain_id(db, domainId)
    if not dg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DomainGraph not found")

    return {"domainId": domainId, "provisionStatus": dg.get("provisionStatus"), "failReason": dg.get("failReason"), "updatedAt": dg.get("updatedAt")}
