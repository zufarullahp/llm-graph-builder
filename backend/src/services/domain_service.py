from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Mapping, Any

from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.repositories import domain_repo, domain_graph_repo
from src.services.tenant_service import find_or_create_tenant_for
from src.services.graph_provisioner import provision_domain_graph, drop_domain_graph
from src.shared.errors import (
    ValidationError,
    ConflictError,
    TenantQuotaExceeded,
    NotFoundError,
    GraphNotReady,
)

logger = logging.getLogger(__name__)
cfg = get_settings()

# Simple background executor for dev / no-redis setup
_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def _plan_domain_quota(plan: str) -> int:
    plan = (plan or "STANDARD").upper()
    return {
        "STANDARD": 1,
        "PRO": 5,
        "ULTIMATE": 20,
    }.get(plan, 1)


def _validate_domain_name(name: str):
    if not name or len(name) < 3 or len(name) > 253:
        raise ValidationError("Invalid domain name length.", {"field": "name"})
    # simple fqdn-ish check: letters, digits, hyphen, dots; no spaces
    import re
    if not re.fullmatch(
        r"[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)*",
        name,
    ):
        raise ValidationError("Invalid domain name format (FQDN required).", {"field": "name"})


def _gen_idempotency_key() -> str:
    import uuid
    return f"idem_{uuid.uuid4().hex}"


# -----------------------------------------------------------------------------
# Create domain (async provisioning)
# -----------------------------------------------------------------------------

def create_domain_async(
    db: Session,
    *,
    user: Mapping[str, Any],
    name: str,
    icon: Optional[str] = None,
) -> Mapping[str, Any]:
    """
    - find-or-create tenant for user
    - enforce plan quota
    - ensure unique (tenantId, name)
    - insert Domain + DomainGraph(provisioning, idempotencyKey)
    - **COMMIT** registry rows
    - enqueue background job: provision_domain_graph(domainId) (atau run inline)
    - return DTO (202)
    """
    _validate_domain_name(name)

    tenant = find_or_create_tenant_for(db, user)

    # quota
    listing = domain_repo.list_by_tenant(db, tenant["id"], page=1, page_size=1_000_000)
    if listing["total"] >= _plan_domain_quota(tenant["plan"]):
        raise TenantQuotaExceeded("Domain quota reached for your plan.")

    # unique
    if domain_repo.exists_by_tenant_and_name(db, tenant["id"], name):
        raise ConflictError(
            "Domain name is already used within this tenant.",
            {"name": name, "constraint": "tenantId_name_unique"},
        )

    # create records dalam 1 transaksi; commit sebelum enqueue
    idemp = _gen_idempotency_key()
    try:
        default_icon = icon if icon is not None else ""
        domain = domain_repo.create(db, tenant_id=tenant["id"], name=name, icon=default_icon)
        domain_graph_repo.create_initial(db, domain_id=domain["id"], idempotency_key=idemp)
        db.commit()  # <<< PENTING: commit dulu agar terlihat oleh worker/driver lain
    except Exception:
        db.rollback()
        raise

    # enqueue provisioning (atau run inline)
    if cfg.PROVISION_ASYNC:
        _EXECUTOR.submit(_provision_job_wrapper, domain["id"])
    else:
        # run inline (synchronous / dev)
        _provision_job_wrapper(domain["id"])

    logger.info("Enqueue provision job for domainId=%s", domain["id"])

    # assemble DTO
    return {
        "domainId": domain["id"],
        "tenantId": tenant["id"],
        "name": domain["name"],
        "icon": domain.get("icon"),
        "provisionStatus": "provisioning",
        "seedStatus": "not_started",
        "idempotencyKey": idemp,
        "createdAt": domain.get("createdAt"),
        "updatedAt": domain.get("updatedAt"),
    }


def _provision_job_wrapper(domain_id: str):
    """
    Runs inside background thread. Handles marking failed on exceptions.
    Membuka session baru agar tidak share koneksi/txn.
    """
    # gunakan factory yang sudah kamu buat untuk Postgres
    from src.db_psql.postgres import SessionLocal

    db = SessionLocal()
    try:
        # opsional: heart-beat status
        domain_graph_repo.mark_provisioning(db, domain_id)
        db.commit()

        provision_domain_graph(db, domain_id=domain_id)
        db.commit()
    except Exception as e:
        db.rollback()
        # mark failed dan commit
        try:
            domain_graph_repo.mark_failed(db, domain_id, str(e)[:500])
            db.commit()
        except Exception:
            db.rollback()
        # re-raise agar terlihat di log executor
        raise
    finally:
        db.close()


# -----------------------------------------------------------------------------
# Queries & helpers
# -----------------------------------------------------------------------------

def list_domains(
    db: Session,
    *,
    user: Mapping[str, Any],
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Mapping[str, Any]:
    tenant = find_or_create_tenant_for(db, user)
    return domain_repo.list_by_tenant(db, tenant["id"], status_filter=status, page=page, page_size=page_size)


def get_domain_detail(db: Session, *, user: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    _validate_domain_name(name)
    domain = domain_repo.get_by_name(db, name)
    if not domain:
        raise NotFoundError("Domain not found.", {"name": name})

    # (opsional) validasi kepemilikan jika nanti user bisa multi-tenant
    # tenant = find_or_create_tenant_for(db, user)
    # if domain["tenantId"] != tenant["id"]:
    #     raise ForbiddenError()

    dg = domain_graph_repo.get_by_domain_id(db, domain["id"])
    provision_status = dg["provisionStatus"] if dg else "provisioning"
    seed_status = dg["seedStatus"] if dg else "not_started"

    return {
        "domainId": domain["id"],
        "tenantId": domain["tenantId"],
        "name": domain["name"],
        "icon": domain.get("icon"),
        "provisionStatus": provision_status,
        "seedStatus": seed_status,
        "createdAt": domain.get("createdAt"),
        "updatedAt": domain.get("updatedAt"),
    }


def get_status(db: Session, *, user: Mapping[str, Any], domain_id: str) -> Mapping[str, Any]:
    domain = domain_repo.get_by_id(db, domain_id)
    if not domain:
        raise NotFoundError("Domain not found.", {"domainId": domain_id})

    dg = domain_graph_repo.get_by_domain_id(db, domain_id)
    if not dg:
        # fallback defensif: anggap provisioning
        return {
            "domainId": domain_id,
            "provisionStatus": "provisioning",
            "failReason": None,
            "updatedAt": domain.get("updatedAt"),
        }

    return {
        "domainId": domain_id,
        "provisionStatus": dg["provisionStatus"],
        "failReason": dg.get("failReason"),
        "updatedAt": dg.get("updatedAt"),
    }


def retry_provision(db: Session, *, user: Mapping[str, Any], domain_id: str) -> Mapping[str, Any]:
    domain = domain_repo.get_by_id(db, domain_id)
    if not domain:
        raise NotFoundError("Domain not found.", {"domainId": domain_id})

    dg = domain_graph_repo.get_by_domain_id(db, domain_id)
    if dg and dg.get("provisionStatus") == "online":
        raise GraphNotReady("Graph is already online; retry not required.", {"domainId": domain_id})

    # set status provisioning lalu commit sebelum enqueue
    try:
        domain_graph_repo.mark_provisioning(db, domain_id)
        db.commit()
    except Exception:
        db.rollback()
        raise

    if cfg.PROVISION_ASYNC:
        _EXECUTOR.submit(_provision_job_wrapper, domain_id)
    else:
        _provision_job_wrapper(domain_id)

    return {"domainId": domain_id, "provisionStatus": "provisioning"}


def delete_domain(db: Session, *, user: Mapping[str, Any], domain_id: str) -> None:
    domain = domain_repo.get_by_id(db, domain_id)
    if not domain:
        # kalau ingin idempotent delete, bisa return saja; di sini 404 agar eksplisit
        raise NotFoundError("Domain not found.", {"domainId": domain_id})

    # 1) Drop graph (idempotent; provisioning-side effect di Neo4j)
    try:
        drop_domain_graph(db, domain_id=domain_id)
    except Exception:
        # kalau drop di Neo4j gagal, tetap lanjut hapus registry?
        # pilihannya tergantung kebijakan—di sini kita teruskan exception agar caller tahu.
        raise

    # 2) Delete registry rows (DomainGraph dulu, lalu Domain)
    try:
        domain_repo.delete_with_relations(db, domain_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
