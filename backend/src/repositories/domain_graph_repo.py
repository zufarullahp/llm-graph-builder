from __future__ import annotations
from typing import Optional, Mapping, Any
from sqlalchemy import text
from sqlalchemy.orm import Session


def create_initial(db: Session, *, domain_id: str, idempotency_key: str) -> Mapping[str, Any]:
    """
    Insert DomainGraph initial row for a domain with 'provisioning' status.
    """
    q = text(
        '''
        INSERT INTO "DomainGraph"
            ("domainId","provisionStatus","seedStatus","idempotencyKey","credVersion","createdAt","updatedAt")
        VALUES
            (:domain_id, 'provisioning', 'not_started', :idempotency_key, 1, now(), now())
        RETURNING *
        '''
    )
    row = db.execute(q, {"domain_id": domain_id, "idempotency_key": idempotency_key}).mappings().first()
    return row


def mark_provisioning(db: Session, domain_id: str) -> Mapping[str, Any]:
    q = text(
        '''
        UPDATE "DomainGraph"
        SET "provisionStatus"='provisioning', "updatedAt"=now()
        WHERE "domainId"=:id
        RETURNING *
        '''
    )
    return db.execute(q, {"id": domain_id}).mappings().first()


def mark_online(db: Session, domain_id: str) -> Mapping[str, Any]:
    q = text(
        '''
        UPDATE "DomainGraph"
        SET "provisionStatus"='online', "provisionedAt"=COALESCE("provisionedAt", now()), "updatedAt"=now()
        WHERE "domainId"=:id
        RETURNING *
        '''
    )
    return db.execute(q, {"id": domain_id}).mappings().first()


def mark_failed(db: Session, domain_id: str, fail_reason: str) -> Mapping[str, Any]:
    q = text(
        '''
        UPDATE "DomainGraph"
        SET "provisionStatus"='failed', "failReason"=:reason, "updatedAt"=now()
        WHERE "domainId"=:id
        RETURNING *
        '''
    )
    return db.execute(q, {"id": domain_id, "reason": fail_reason}).mappings().first()


def save_credentials(
    db: Session,
    *,
    domain_id: str,
    uri: str,
    database: str,
    username: str,
    secret_enc: str,
    cred_version: int = 1,
) -> Mapping[str, Any]:
    """
    Persist connection credentials for a domain graph.
    """
    q = text(
        '''
        UPDATE "DomainGraph"
        SET "neo4jUri"=:uri,
            "neo4jDatabase"=:database,
            "neo4jUsername"=:username,
            "neo4jSecretEnc"=:secret_enc,
            "credVersion"=:cred_version,
            "updatedAt"=now()
        WHERE "domainId"=:id
        RETURNING *
        '''
    )
    row = db.execute(q, {
        "uri": uri,
        "database": database,
        "username": username,
        "secret_enc": secret_enc,
        "cred_version": cred_version,
        "id": domain_id,
    }).mappings().first()
    return row


def get_by_domain_id(db: Session, domain_id: str) -> Optional[Mapping[str, Any]]:
    q = text('SELECT * FROM "DomainGraph" WHERE "domainId"=:id LIMIT 1')
    return db.execute(q, {"id": domain_id}).mappings().first()
