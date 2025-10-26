# src/agent/evaluator.py
import os
from typing import Iterable

from src.agent.schema import ChatBotResult, EvaluationResult


# ====== Konfigurasi threshold via ENV (punya default aman) ======
MIN_SOURCES = int(os.getenv("EVAL_MIN_SOURCES", "1"))                 # perlu >= 1 sumber
MAX_LATENCY_MS = float(os.getenv("EVAL_MAX_LATENCY_MS", "15000"))     # 15 detik
MIN_MESSAGE_LEN = int(os.getenv("EVAL_MIN_MESSAGE_LEN", "20"))        # minimal panjang jawaban
GENERIC_SCORE_CUTOFF = float(os.getenv("EVAL_GENERIC_SCORE_CUTOFF", "0.75"))  # skor minimum agar dianggap valid


# Frasa yang menandakan jawaban generik/tidak konklusif
GENERIC_PATTERNS: tuple[str, ...] = (
    "something went wrong",
    "i couldn't find",
    "no relevant documents",
    "no context",
    "maaf, saya tidak menemukan",
    "tidak menemukan data relevan",
    "unable to answer",
    "i do not have enough information",
    "i don't have enough information",
)


def _contains_any(text: str, patterns: Iterable[str]) -> bool:
    tl = (text or "").strip().lower()
    return any(p in tl for p in patterns)


def _is_generic_message(message: str) -> bool:
    if not message or len(message.strip()) < MIN_MESSAGE_LEN:
        return True
    return _contains_any(message, GENERIC_PATTERNS)


def evaluate_chatbot_result(res: ChatBotResult) -> EvaluationResult:
    """
    Menilai kualitas hasil dari /chat_bot (yang sudah dinormalisasi).
    Mengembalikan:
      - is_valid: apakah cukup layak dipakai tanpa fallback
      - score: skor 0..1 (semakin tinggi semakin bagus)
      - sources_count: jumlah sumber yang dikembalikan RAG
      - latency_ms: latency dari sisi retriever (jika tersedia di info.response_time)
      - fallback_needed: true jika perlu jalankan fallback chain
    """
    info = res.info or {}
    sources = info.get("sources") or []
    latency_ms = float(info.get("response_time") or 0.0) * 1000.0
    message = (res.message or "").strip()

    # ---- Komponen skor sederhana (0..1) ----
    score = 0.0

    # (1) Sumber: kontribusi utama (0.0 ~ 0.6)
    if isinstance(sources, list) and len(sources) >= MIN_SOURCES:
        # skala: 1 sumber = 0.4, 2+ sumber = 0.6
        score += 0.4 if len(sources) == 1 else 0.6

    # (2) Kualitas pesan: panjang & tidak generik (0.0 ~ 0.3)
    if not _is_generic_message(message):
        # makin panjang makin kredibel (sederhana)
        score += 0.2
        if len(message) >= (MIN_MESSAGE_LEN * 2):
            score += 0.1  # bonus jika jawaban tidak terlalu pendek

    # (3) Latency: cepat lebih baik (0.0 ~ 0.1)
    if latency_ms > 0:
        if latency_ms <= MAX_LATENCY_MS:
            score += 0.1  # masih dalam ambang yang bisa diterima

    # ---- Keputusan fallback ----
    # fallback jika: tidak ada sumber, pesan generik/terlalu pendek, atau latency berlebihan, atau skor di bawah cutoff
    no_sources = len(sources) < MIN_SOURCES
    generic = _is_generic_message(message)
    too_slow = latency_ms > MAX_LATENCY_MS if latency_ms > 0 else False
    fallback_needed = no_sources or generic or too_slow or (score < GENERIC_SCORE_CUTOFF)

    is_valid = not fallback_needed

    return EvaluationResult(
        is_valid=is_valid,
        score=round(min(max(score, 0.0), 1.0), 2),
        sources_count=len(sources),
        latency_ms=latency_ms,
        reasoning="rule-based evaluator (sources/message/latency)",
        fallback_needed=fallback_needed,
    )
