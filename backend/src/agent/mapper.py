# src/agent/mapper.py
import uuid
import logging
from datetime import datetime
from typing import List
from src.agent.schema import IntentResult, RetrieverPlan

# =====================================
# Mapping utama antara intent dan retriever mode
# =====================================
INTENT_TO_MODE = {
    "factual": "vector",
    "literal": "fulltext",
    "entity": "entity_vector",
    "relational": "graph",
    "hybrid": "graph_vector_fulltext",
    "conceptual": "global_vector_fulltext",
}

# =====================================
# Fallback chain untuk setiap intent
# urutan dari yang paling spesifik ke general
# =====================================
FALLBACK_CHAIN = {
    "factual": ["graph_vector_fulltext", "global_vector_fulltext"],
    "literal": ["vector", "graph_vector_fulltext"],
    "entity": ["entity_vector", "graph_vector_fulltext", "global_vector_fulltext"],
    "relational": ["graph_vector_fulltext", "graph"],
    "hybrid": ["graph_vector_fulltext", "vector"],
    "conceptual": ["global_vector_fulltext", "vector"],
    "default": ["vector", "graph_vector_fulltext"],
}


def map_intent_to_mode(intent_result: IntentResult, policy: str = "default") -> RetrieverPlan:
    """
    Menerjemahkan hasil intent classifier menjadi rencana retriever.

    Args:
        intent_result: hasil klasifikasi LLM (intent, confidence, reasoning, dsb)
        policy: opsional; bisa diubah jika nanti ada strategi pemetaan lain.

    Returns:
        RetrieverPlan: berisi primary_mode, fallback_modes, timestamp, trace_id
    """
    intent = intent_result.intent.lower().strip() if intent_result.intent else "factual"

    primary_mode = INTENT_TO_MODE.get(intent, "vector")
    fallback_modes = FALLBACK_CHAIN.get(intent, FALLBACK_CHAIN["default"])

    # Pastikan fallback tidak duplikat dengan primary
    fallback_modes = [m for m in fallback_modes if m != primary_mode]

    plan = RetrieverPlan(
        primary_mode=primary_mode,
        fallback_modes=fallback_modes,
        timestamp=datetime.utcnow(),
        policy_used=policy,
        intent=intent_result.intent,
        confidence=float(intent_result.confidence),
        reasoning=intent_result.reasoning,
        trace_id=str(uuid.uuid4()),
    )

    logging.info(
        f"[Mapper] intent='{intent}' → primary='{primary_mode}', fallbacks={fallback_modes}, trace_id={plan.trace_id}"
    )

    return plan
