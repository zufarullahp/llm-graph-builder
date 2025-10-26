# src/agent/orchestrator.py
import os
import json
import time
from typing import Any, Dict, List, Optional

import httpx

from src.agent.schema import (
    AgentChatRequest,
    AgentChatResponse,
    ChatBotResult,
)
from src.agent.classifier import classify_intent
from src.agent.mapper import map_intent_to_mode
from src.agent.evaluator import evaluate_chatbot_result


# ===== Konfigurasi dasar =====
FASTAPI_BASE_URL = os.environ.get("FASTAPI_URL", "http://127.0.0.1:8000")

# Kredensial /chat_bot (ikuti env existing di backend kamu)
NEO4J_URI = os.environ.get("FASTAPI_NEO4J_URI", os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
NEO4J_USER = os.environ.get("FASTAPI_NEO4J_USER", os.environ.get("NEO4J_USER", "neo4j"))
NEO4J_PASSWORD = os.environ.get("FASTAPI_NEO4J_PASSWORD", os.environ.get("NEO4J_PASSWORD", "password"))
NEO4J_DB = os.environ.get("FASTAPI_NEO4J_DB", os.environ.get("NEO4J_DB", "neo4j"))
CHAT_MODEL = os.environ.get("FASTAPI_MODEL", os.environ.get("OPENAI_MODEL", "openai_gpt_4o"))

# Batas fallback (boleh diatur via ENV)
MAX_FALLBACKS = int(os.environ.get("AGENT_MAX_FALLBACKS", "3"))


async def _call_chat_bot(
    *,
    question: str,
    session_id: str,
    mode: str,
    document_names: Optional[List[str]],
    email: Optional[str],
    uri: str, 
    userName: str, 
    password: str, 
    database: str,
) -> Dict[str, Any]:
    """
    Memanggil endpoint /chat_bot dengan form-urlencoded (sesuai kontrak existing).
    Mengembalikan raw JSON dari /chat_bot (berbentuk {status, data}).
    """
    if not uri or not userName or not password or not database:
        raise ValueError("Missing DB connection params for /chat_bot")
    
    url = f"{FASTAPI_BASE_URL}/chat_bot"

    form = {
        # "uri": NEO4J_URI,
        # "userName": NEO4J_USER,
        # "password": NEO4J_PASSWORD,
        # "database": NEO4J_DB,
        "uri": uri,
        "userName": userName,
        "password": password,
        "database": database,
        "model": CHAT_MODEL,
        "mode": mode,
        "question": question,
        "session_id": session_id,
        # /chat_bot mengharapkan string JSON untuk document_names
        "document_names": json.dumps(document_names or []),
    }
    print(f"[agent→/chat_bot] mode={mode} uri={uri} user={userName} db={database} sess={session_id}")

    if email:
        form["email"] = email

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, data=form)
        resp.raise_for_status()
        return resp.json()


def _normalize_chatbot_response(raw: Dict[str, Any]) -> ChatBotResult:
    """
    Normalisasi wrapper {status, data} dari /chat_bot ke bentuk yang dipakai evaluator/orchestrator.
    """
    data = raw.get("data")

    # 🔍 Tambahkan debug untuk mendeteksi double-encoded JSON
    if isinstance(data, str):
        import json
        try:
            data = json.loads(data)
        except Exception:
            print("⚠️  /chat_bot returned 'data' as string, not JSON:", data[:300])
            data = {}

    info = data.get("info") or {}

    return ChatBotResult(
        message=data.get("message", "") or "",
        info=info,
        session_id=data.get("session_id", "") or "",
        raw_response=raw,
    )



async def run_agent_chat(req: AgentChatRequest) -> AgentChatResponse:
    """
    Orkestrasi utama:
    1) Klasifikasi intent (LLM/heuristik) → intent, confidence, reasoning
    2) Mapping intent → primary_mode & fallback_modes
    3) Panggil /chat_bot dengan mode terpilih; jika hasil kurang valid → coba fallback
    4) Build AgentChatResponse (message, mode_used, router info, sources, metrics)
    """
    t0 = time.time()

    # ---- 1) Intent Classifier ----
    intent_res = classify_intent(req.question, model=req.llm_router_model)

    # ---- 2) Mapping ke Mode ----
    plan = map_intent_to_mode(intent_res, policy=req.mode_policy)
    all_modes = [plan.primary_mode] + plan.fallback_modes
    # batasi jumlah total percobaan
    all_modes = all_modes[: max(1, min(len(all_modes), 1 + MAX_FALLBACKS))]

    attempts = 0
    used_mode = plan.primary_mode
    fallback_used = False

    last_norm: Optional[ChatBotResult] = None
    last_eval = None

    # ---- 3) Eksekusi /chat_bot (primary → fallbacks) ----
    for mode in all_modes:
        attempts += 1
        used_mode = mode

        try:
            raw = await _call_chat_bot(
                question=req.question,
                session_id=req.session_id,
                mode=mode,
                document_names=req.document_names or [],
                email=req.email,
                uri=req.uri,
                userName=req.userName,
                password=req.password,
                database=req.database,
            )
            print("[agent] /chat_bot RAW:", json.dumps(raw)[:600])
        except Exception:
            # jika HTTP error, coba fallback berikutnya
            fallback_used = True
            continue

        norm = _normalize_chatbot_response(raw)
        last_norm = norm

        # Jika /chat_bot tidak success, tandai untuk fallback
        if raw.get("status") != "Success":
            fallback_used = True
            continue

        # ---- 4) Evaluasi hasil ----
        eval_res = evaluate_chatbot_result(norm)
        last_eval = eval_res

        if eval_res.is_valid:
            # cukup baik → berhenti
            break
        else:
            fallback_used = True
            # lanjut ke mode fallback berikutnya

    # ---- 5) Build Response ----
    # Jika semua percobaan gagal/invalid, kembalikan pesan ramah
    if not last_norm or (last_eval and not last_eval.is_valid):
        total_ms = (time.time() - t0) * 1000.0
        return AgentChatResponse(
            status="Success",
            message="Maaf, saya tidak menemukan data relevan untuk pertanyaan ini.",
            mode_used=used_mode,
            router={
                "intent": intent_res.intent,
                "confidence": intent_res.confidence,
                "reasoning": intent_res.reasoning,
                "fallback_used": True,
                "attempts": attempts,
                "trace_id": plan.trace_id,
            },
            info={
                "sources": [],
                "response_time": 0.0,
                "model": CHAT_MODEL,
                "metrics": {
                    "classifier_ms": intent_res.latency_ms,
                    "retriever_ms": 0.0,
                    "total_ms": total_ms,
                },
            },
            session_id=req.session_id,
        )

    # respons valid → pakai info dari percobaan terakhir yang lolos
    info = last_norm.info or {}
    total_ms = (time.time() - t0) * 1000.0
    retriever_ms = float(info.get("response_time") or 0.0) * 1000.0

    return AgentChatResponse(
        status="Success",
        message=last_norm.message,
        mode_used=used_mode,
        router={
            "intent": intent_res.intent,
            "confidence": intent_res.confidence,
            "reasoning": intent_res.reasoning,
            "fallback_used": fallback_used,
            "attempts": attempts,
            "trace_id": plan.trace_id,
        },
        info={
            "sources": info.get("sources") or [],
            "response_time": info.get("response_time", 0.0),
            "model": info.get("model", CHAT_MODEL),
            "metrics": {
                "classifier_ms": intent_res.latency_ms,
                "retriever_ms": retriever_ms,
                "total_ms": total_ms,
            },
        },
        session_id=req.session_id,
    )
