from __future__ import annotations
from typing import Optional, Mapping, Any, List
from sqlalchemy import text
from sqlalchemy.orm import Session


def exists_by_tenant_and_name(db: Session, tenant_id: str, name: str) -> bool:
    q = text(
        'SELECT 1 FROM "Domain" WHERE "tenantId" = :tid AND "name" = :name LIMIT 1'
    )
    row = db.execute(q, {"tid": tenant_id, "name": name}).first()
    return row is not None

# Checks
def create(
    db: Session,
    *,
    tenant_id: str,
    name: str,
    icon: Optional[str] = None,
) -> Mapping[str, Any]:
    q = text(
        '''
        INSERT INTO "Domain"
            ("id","tenantId","name","icon")
        VALUES
            (gen_random_uuid(), :tenant_id, :name, :icon)
        RETURNING *
        '''
    )
    icon = icon if icon is not None else ""
    row = db.execute(q, {"tenant_id": tenant_id, "name": name, "icon": icon}).mappings().first()
    return row


def list_by_tenant(
    db: Session,
    tenant_id: str,
    *,
    status_filter: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    Return paginated list of domains with their provisionStatus (join DomainGraph).
    """
    offset = (page - 1) * page_size

    base = '''
        FROM "Domain" d
        LEFT JOIN "DomainGraph" g ON g."domainId" = d."id"
        WHERE d."tenantId" = :tid
    '''
    if status_filter:
        base += ' AND g."provisionStatus" = :status '

    # items
    q_items = text(
        'SELECT d."id" as "domainId", d."name", d."icon", '
        '       COALESCE(g."provisionStatus", \'provisioning\') AS "provisionStatus", '
        '       COALESCE(g."seedStatus", \'not_started\') AS "seedStatus" ' +
        base +
        ' LIMIT :limit OFFSET :offset'
    )
    params = {"tid": tenant_id, "limit": page_size, "offset": offset}
    if status_filter:
        params["status"] = status_filter

    items = db.execute(q_items, params).mappings().all()

    # total
    q_count = text('SELECT COUNT(*) ' + base)
    total = db.execute(q_count, {"tid": tenant_id, **({"status": status_filter} if status_filter else {})}).scalar_one()

    return {"items": items, "page": page, "pageSize": page_size, "total": total}


def get_by_id(db: Session, domain_id: str) -> Optional[Mapping[str, Any]]:
    q = text('SELECT * FROM "Domain" WHERE "id" = :id LIMIT 1')
    return db.execute(q, {"id": domain_id}).mappings().first()


def get_by_name(db: Session, name: str) -> Optional[Mapping[str, Any]]:
    q = text('SELECT * FROM "Domain" WHERE "name" = :name LIMIT 1')
    return db.execute(q, {"name": name}).mappings().first()


def delete_with_relations(db: Session, domain_id: str) -> None:
    """
    Delete Domain and its dependent rows.
    - Deletes DomainGraph first (FK 1–1).
    - Deletes other domain-scoped configs if exist (ChatBot, HelpDesk, FilterQuestions, Product, Customer, ChatRoom...)
      Uncomment according to your current Prisma schema & FK onDelete rules.
    """
    # DomainGraph 1–1
    db.execute(text('DELETE FROM "DomainGraph" WHERE "domainId" = :id'), {"id": domain_id})

    # Optional: other related tables (uncomment as needed, order matters if no ON DELETE CASCADE)
    # db.execute(text('DELETE FROM "ChatBot" WHERE "domainId" = :id'), {"id": domain_id})
    # db.execute(text('DELETE FROM "HelpDesk" WHERE "domainId" = :id'), {"id": domain_id})
    # db.execute(text('DELETE FROM "FilterQuestions" WHERE "domainId" = :id'), {"id": domain_id})
    # db.execute(text('DELETE FROM "Product" WHERE "domainId" = :id'), {"id": domain_id})
    # db.execute(text('DELETE FROM "Customer" WHERE "domainId" = :id'), {"id": domain_id})
    # db.execute(text('DELETE FROM "ChatRoom" WHERE "customerId" IN (SELECT "id" FROM "Customer" WHERE "domainId" = :id)'), {"id": domain_id})
    # db.execute(text('DELETE FROM "ChatMessage" WHERE "chatRoomId" IN (SELECT "id" FROM "ChatRoom" WHERE "customerId" IN (SELECT "id" FROM "Customer" WHERE "domainId" = :id))'), {"id": domain_id})

    # finally Domain
    db.execute(text('DELETE FROM "Domain" WHERE "id" = :id'), {"id": domain_id})
