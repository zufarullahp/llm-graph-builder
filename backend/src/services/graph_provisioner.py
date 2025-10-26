# src/services/graph_provisioner.py
from __future__ import annotations

import base64
import logging
import re
import secrets
import time
from typing import Mapping, Any

from neo4j import GraphDatabase, basic_auth
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.shared.crypto import encrypt
from src.shared.errors import Neo4jUnavailable, GraphTimeout
from src.repositories import domain_repo, domain_graph_repo

logger = logging.getLogger(__name__)
cfg = get_settings()


def _admin_driver():
    """Connect to Neo4j as admin to execute system-level operations."""
    try:
        driver = GraphDatabase.driver(
            cfg.NEO4J_ADMIN_URI,
            auth=basic_auth(cfg.NEO4J_ADMIN_USER, cfg.NEO4J_ADMIN_PASS),
        )
        return driver
    except Exception as e:
        raise Neo4jUnavailable(str(e))


# ---------- helpers: naming & capability ----------

_DB_RE_ALLOWED = re.compile(r"[^a-z0-9.-]")


def _id_str(x: Any) -> str:
    return str(x) if x is not None else ""


def _sanitize_db_name(s: str) -> str:
    """
    Make a valid Neo4j database name:
      - lowercase
      - only [a-z0-9.-]
      - must start with a letter
      - max length 63
    """
    s = s.lower()
    s = _DB_RE_ALLOWED.sub("-", s)
    if not s or not s[0].isalpha():
        s = f"db-{s}"
    return s[:63]


def _make_db_name(domain: Mapping[str, Any]) -> str:
    """
    Predictable & unique enough, yet valid for Neo4j.
    Example: "db-2825f09f-chat.acme.ai"
    """
    dom_id_part = _id_str(domain["id"]).replace("-", "")[:8]
    raw = f"{dom_id_part}-{domain['name']}"
    return _sanitize_db_name(raw)


def _make_user_name(domain: Mapping[str, Any]) -> str:
    # Tidak dipakai lagi (kita pakai user shared), tetap dipertahankan untuk kompatibilitas.
    dom_id = _id_str(domain["id"]).replace("-", "")
    base = f"u{dom_id[:15]}"
    return base.lower()


def _generate_secret() -> str:
    # Tidak dipakai lagi, tetap disimpan untuk kompatibilitas.
    return base64.b64encode(secrets.token_bytes(24)).decode()


def _supports_multi_db(driver) -> bool:
    """Detect if server supports multi-database (Enterprise)."""
    try:
        with driver.session(database="system") as session:
            _ = list(session.run("SHOW DATABASES"))
            return True
    except Exception:
        return False


def _wait_until_online(driver, db_name: str, timeout_sec: int = 120) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        with driver.session(database="system") as session:
            rec = session.run("SHOW DATABASE $db", db=db_name).single()
            if rec:
                status = rec.get("currentStatus") or rec.get("status")
                if status and "online" in str(status).lower():
                    return
        time.sleep(1.0)
    raise GraphTimeout(f"Database {db_name} did not become online within {timeout_sec}s.")


# ---------- main ops ----------

def provision_domain_graph(db: Session, *, domain_id: str) -> None:
    """
    Idempotent provisioning:
      - If already online → return.
      - Else create DB (if supported), simpan kredensial shared, mark online.
      - Any failure → mark_failed with reason.

    Tambahan “sabuk pengaman”:
      - Retry singkat (5x) kalau baris Domain belum terlihat (gap commit vs job start).
    """
    logger.info("[PROVISION] start domainId=%s", domain_id)

    try:
        dg = domain_graph_repo.get_by_domain_id(db, domain_id)
        if dg and dg.get("provisionStatus") == "online":
            logger.info("[PROVISION] already online, skip domainId=%s", domain_id)
            return

        # --- retry kecil agar tidak balapan dengan commit transaksi pembuatan domain ---
        domain = domain_repo.get_by_id(db, domain_id)
        if not domain:
            for _ in range(5):
                time.sleep(0.3)
                domain = domain_repo.get_by_id(db, domain_id)
                if domain:
                    break
        if not domain:
            logger.warning("[PROVISION] domain not found id=%s after retries", domain_id)
            domain_graph_repo.mark_failed(db, domain_id, fail_reason="DOMAIN_ROW_NOT_VISIBLE")
            return
        # -------------------------------------------------------------------------------

        driver = _admin_driver()
        try:
            use_multi_db = _supports_multi_db(driver)
            logger.info("[PROVISION] multi-db supported=%s", use_multi_db)

            if use_multi_db:
                database = _make_db_name(domain)
            else:
                # Community fallback: use default database name
                database = "neo4j"

            # 🔑 Pakai user shared dari .env (tanpa CREATE USER/GRANT)
            username = cfg.NEO4J_ADMIN_USER
            password = cfg.NEO4J_ADMIN_PASS
            logger.info("[PROVISION] target db=%s using shared user=%s", database, username)

            # 1) CREATE DATABASE (Enterprise only)
            if use_multi_db:
                try:
                    with driver.session(database="system") as session:
                        session.run("CREATE DATABASE $db IF NOT EXISTS", db=database)
                    _wait_until_online(driver, database, timeout_sec=120)
                except GraphTimeout:
                    raise
                except Exception as e:
                    raise Neo4jUnavailable(f"CREATE/SHOW DATABASE failed: {e}")

            # 2) (DIHILANGKAN) CREATE USER + GRANTS
            # Kita tidak membuat user/role baru. Semua akses memakai user shared.

            # 3) Save credentials encrypted; mark online
            enc = encrypt(password)
            domain_graph_repo.save_credentials(
                db,
                domain_id=domain_id,
                uri=cfg.NEO4J_PUBLIC_URI,
                database=database,
                username=username,
                secret_enc=enc,
                cred_version=1,
            )
            domain_graph_repo.mark_online(db, domain_id)
            logger.info("[PROVISION] success domainId=%s db=%s user=%s", domain_id, database, username)

        finally:
            try:
                driver.close()
            except Exception:
                pass

    except GraphTimeout as e:
        logger.exception("[PROVISION] timeout domainId=%s: %s", domain_id, e)
        domain_graph_repo.mark_failed(db, domain_id, fail_reason=str(e)[:500])
    except Neo4jUnavailable as e:
        logger.exception("[PROVISION] neo4j admin error domainId=%s: %s", domain_id, e)
        domain_graph_repo.mark_failed(db, domain_id, fail_reason=str(e)[:500])
    except Exception as e:
        logger.exception("[PROVISION] unexpected error domainId=%s: %s", domain_id, e)
        domain_graph_repo.mark_failed(db, domain_id, fail_reason=str(e)[:500])


def drop_domain_graph(db: Session, *, domain_id: str) -> None:
    """
    Idempotent DROP DATABASE for a domain graph.
    """
    logger.info("[DROP] start domainId=%s", domain_id)
    dg = domain_graph_repo.get_by_domain_id(db, domain_id)
    if not dg or not dg.get("neo4jDatabase"):
        logger.info("[DROP] nothing to drop for domainId=%s", domain_id)
        return

    database = dg["neo4jDatabase"]

    driver = _admin_driver()
    try:
        with driver.session(database="system") as session:
            # Works on Enterprise; pada Community akan error/diabaikan → tangkap & laporkan
            session.run("DROP DATABASE $db IF EXISTS", db=database)
        logger.info("[DROP] dropped db=%s domainId=%s", database, domain_id)
    except Exception as e:
        raise Neo4jUnavailable(f"DROP DATABASE failed: {e}")
    finally:
        try:
            driver.close()
        except Exception:
            pass
