from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from sqlalchemy.orm import Session

from src.api.deps import get_current_user
from src.db_psql.postgres import get_db
from src.services.domain_service import (
    create_domain_async,
    list_domains,
    get_domain_detail,
    get_status,
    retry_provision,
    delete_domain,
)

router = APIRouter(prefix="/domains", tags=["Domains"])


# ============================
# Request / Response Models
# ============================

class CreateDomainRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=253, description="FQDN domain, unik per-tenant")
    icon: Optional[str] = Field(default=None, description="URL icon (opsional)")


# ============================
# Routes
# ============================

@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_domain(
    payload: CreateDomainRequest,
    response: Response,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create domain & enqueue async provisioning (thread pool).
    Returns 202 Accepted and Location header to poll status.
    """
    dto = create_domain_async(
        db,
        user=user,
        name=payload.name.strip().lower(),
        icon=payload.icon,
    )

    # Set Location header for polling
    response.headers["Location"] = f"/domains/{dto['domainId']}/status"
    # (opsional) idempotency key bisa dipasang di service jika ingin diekspos
    return dto


@router.get("", status_code=status.HTTP_200_OK)
def list_user_domains(
    page: int = 1,
    pageSize: int = 20,
    statusFilter: Optional[str] = None,  # provisioning|online|failed|...
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List domain milik user login (scoped by tenant).
    """
    return list_domains(
        db,
        user=user,
        status=statusFilter,
        page=page,
        page_size=pageSize,
    )


@router.get("/{domainId}/status", status_code=status.HTTP_200_OK)
def get_domain_status(
    domainId: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Polling status provisioning untuk satu domain.
    """
    return get_status(db, user=user, domain_id=domainId)


@router.get("/{name}", status_code=status.HTTP_200_OK)
def get_domain_by_name(
    name: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Detail domain untuk halaman settings.
    """
    return get_domain_detail(db, user=user, name=name.strip().lower())


@router.post("/{domainId}/provision/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_domain_provision(
    domainId: str,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Enqueue ulang provisioning jika sebelumnya failed.
    """
    return retry_provision(db, user=user, domain_id=domainId)


@router.delete("/{domainId}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_domain(
    domainId: str,
    dropGraph: bool = True,  # dikunci default True sesuai kebijakan
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Hapus domain dan DROP database Neo4j per-domain (idempotent).
    Query param `dropGraph` ada untuk kompatibilitas kontrak; saat ini diabaikan (selalu drop).
    """
    # Kebijakan: selalu drop DB
    _ = dropGraph
    delete_domain(db, user=user, domain_id=domainId)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
