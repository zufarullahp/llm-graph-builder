from __future__ import annotations
from typing import Optional, Mapping, Any
from sqlalchemy import text
from sqlalchemy.orm import Session


def find_by_owner_user_id(db: Session, owner_user_id: str) -> Optional[Mapping[str, Any]]:
    """
    Find the first Tenant row for a given ownerUserId.
    """
    q = text(
        'SELECT * FROM "Tenant" WHERE "ownerUserId" = :uid LIMIT 1'
    )
    row = db.execute(q, {"uid": owner_user_id}).mappings().first()
    return row


def create(
    db: Session,
    *,
    name: str,
    owner_user_id: str,
    owner_email: str,
    plan: str = "STANDARD",
    is_active: bool = True,
) -> Mapping[str, Any]:
    """
    Create a new Tenant. Prisma uses gen_random_uuid() and now().
    """
    q = text(
        '''
        INSERT INTO "Tenant"
            ("id","name","ownerUserId","ownerEmail","plan","isActive","createdAt","updatedAt")
        VALUES
            (gen_random_uuid(), :name, :owner_user_id, :owner_email, :plan, :is_active, now(), now())
        RETURNING *
        '''
    )
    row = db.execute(q, {
        "name": name,
        "owner_user_id": owner_user_id,
        "owner_email": owner_email,
        "plan": plan,
        "is_active": is_active,
    }).mappings().first()
    return row
