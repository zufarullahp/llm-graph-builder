from __future__ import annotations

import json
import time
import base64
from dataclasses import dataclass
from typing import Optional

import jwt  # PyJWT
import requests
from fastapi import Header, Request, Depends

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.db_psql.postgres import get_db
from src.shared.crypto import decrypt
from src.shared.errors import (
    UnauthenticatedError,
    ForbiddenError,
    NotFoundError,
    GraphNotReady,
    InternalServerError,
)


cfg = get_settings()


# ============================================================
# JWT / Clerk helpers
# ============================================================

_JWKS_CACHE: dict[str, dict] = {}
_JWKS_CACHE_TTL = 60 * 10  # 10 minutes
_JWKS_CACHE_AT: float | None = None


def _load_jwks(url: str) -> dict:
    global _JWKS_CACHE, _JWKS_CACHE_AT
    now = time.time()
    if _JWKS_CACHE and _JWKS_CACHE_AT and (now - _JWKS_CACHE_AT) < _JWKS_CACHE_TTL:
        return _JWKS_CACHE
    resp = requests.get(url, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    _JWKS_CACHE = {k["kid"]: k for k in data.get("keys", [])}
    _JWKS_CACHE_AT = now
    return _JWKS_CACHE


def _get_signing_key_from_jwks(token: str, jwks_url: str):
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    if not kid:
        raise UnauthenticatedError("JWT header missing 'kid' for JWKS lookup.")
    jwks = _load_jwks(jwks_url)
    key = jwks.get(kid)
    if not key:
        # refresh once
        jwks = _load_jwks(jwks_url)
        key = jwks.get(kid)
        if not key:
            raise UnauthenticatedError("Signing key not found in JWKS.")
    return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))


def _decode_jwt(token: str) -> dict:
    """
    Decode & validate a JWT from Clerk (or other IdP).
    - If CLERK_JWKS_URL is provided, validate signature (RS256).
    - Else if ENVIRONMENT=development, decode without verify (local only).
    - Otherwise, raise error.
    """
    jwks_url = getattr(cfg, "CLERK_JWKS_URL", None) or _getenv("CLERK_JWKS_URL")
    issuer = getattr(cfg, "CLERK_ISSUER", None) or _getenv("CLERK_ISSUER")
    audience = getattr(cfg, "CLERK_AUDIENCE", None) or _getenv("CLERK_AUDIENCE")

    if jwks_url:
        key = _get_signing_key_from_jwks(token, jwks_url)
        options = {"verify_aud": bool(audience)}
        decoded = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            audience=audience if audience else None,
            issuer=issuer if issuer else None,
            options=options,
        )
        return decoded

    # Dev fallback: allow decode without verify ONLY in development
    if cfg.ENVIRONMENT.lower() == "development":
        # return jwt.decode(token, options={"verify_signature": False})
        return {"userId": "dev-user-001", "email": "dev@local.test"}

    raise UnauthenticatedError("JWT verification configuration missing.")


def _getenv(name: str) -> Optional[str]:
    import os
    return os.getenv(name)


# ============================================================
# Public dependency: current user (Clerk/JWT)
# ============================================================

def get_current_user(authorization: str = Header(None)) -> dict:
    """
    TEMP: Development mode bypass — skip JWT verification entirely.
    """
    from src.core.config import get_settings
    cfg = get_settings()

    # 🔹 kalau ENVIRONMENT=development, langsung return user dummy
    if cfg.ENVIRONMENT.lower() == "development":
        return {"userId": "dev-user-001", "email": "dev@local.test"}

    # 🔸 sisanya produksi normal
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthenticatedError("Missing Bearer token in Authorization header.")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise UnauthenticatedError("Empty Bearer token.")

    try:
        claims = _decode_jwt(token)
    except Exception as e:
        raise UnauthenticatedError(f"Invalid token: {str(e)}")

    user_id = claims.get("sub") or claims.get("user_id")
    if not user_id:
        raise UnauthenticatedError("Token payload missing 'sub' (user id).")

    return {"userId": user_id, "email": claims.get("email")}


# ============================================================
# Graph resolve dependency (by Host header)
# ============================================================

@dataclass
class GraphCredentials:
    uri: str
    database: str
    username: str
    password: str
    domain_id: str
    domain_name: str


def _extract_host(request: Request) -> str:
    # honor proxies if any
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if not host:
        raise NotFoundError("Host header not found.")
    # strip port if exists
    if ":" in host:
        host = host.split(":", 1)[0]
    return host.strip().lower()


def resolve_graph_by_host(
    request: Request,
    db: Session = Depends(get_db),
) -> GraphCredentials:
    """
    Resolve incoming Host to Domain → DomainGraph credentials.
    Used by pipeline endpoints to create a Neo4j connection context.
    """
    host = _extract_host(request)

    # 1) Find Domain by name (unique per tenant)
    q_domain = text(
        'SELECT "id", "name" FROM "Domain" WHERE "name" = :host LIMIT 1'
    )
    row = db.execute(q_domain, {"host": host}).mappings().first()
    if not row:
        raise NotFoundError("Domain not found.", {"name": host})

    domain_id = row["id"]
    domain_name = row["name"]

    # 2) Load DomainGraph record
    q_graph = text(
        'SELECT "neo4jUri", "neo4jDatabase", "neo4jUsername", "neo4jSecretEnc", "provisionStatus" '
        'FROM "DomainGraph" WHERE "domainId" = :did'
    )
    gr = db.execute(q_graph, {"did": domain_id}).mappings().first()
    if not gr:
        # should not happen if create flow is correct
        raise NotFoundError("Domain graph registry not found.", {"domainId": domain_id})

    status = gr["provisionStatus"]
    if status != "online":
        # 503 so FE can retry/poll
        raise GraphNotReady(f"Graph status is '{status}'.", {"domainId": domain_id, "status": status})

    uri = gr["neo4jUri"]
    database = gr["neo4jDatabase"]
    username = gr["neo4jUsername"]
    secret_enc = gr["neo4jSecretEnc"]

    if not all([uri, database, username, secret_enc]):
        raise InternalServerError(
            "Incomplete graph credentials in registry.",
            {"domainId": domain_id}
        )

    try:
        password = decrypt(secret_enc)
    except Exception as e:
        raise InternalServerError("Failed to decrypt graph secret.", {"error": str(e)})

    return GraphCredentials(
        uri=uri,
        database=database,
        username=username,
        password=password,
        domain_id=domain_id,
        domain_name=domain_name,
    )
