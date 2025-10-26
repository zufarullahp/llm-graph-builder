from __future__ import annotations
from typing import Mapping, Any
from sqlalchemy.orm import Session

from src.repositories import tenant_repo


def _derive_workspace_name(email: str | None) -> str:
    if not email:
        return "Workspace"
    prefix = email.split("@", 1)[0]
    return f"{prefix}'s Workspace"


def find_or_create_tenant_for(db: Session, user: dict) -> Mapping[str, Any]:
    """
    Return an existing tenant for the logged-in user or create one (STANDARD).
    user: {"userId": "...", "email": "..."}
    """
    owner_user_id = user["userId"]
    existing = tenant_repo.find_by_owner_user_id(db, owner_user_id)
    if existing:
        return existing

    # create default tenant
    name = _derive_workspace_name(user.get("email"))
    return tenant_repo.create(
        db,
        name=name,
        owner_user_id=owner_user_id,
        owner_email=user.get("email") or "",
        plan="STANDARD",
        is_active=True,
    )
