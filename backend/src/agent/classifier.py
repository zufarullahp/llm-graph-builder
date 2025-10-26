# src/agent/classifier.py
import os
import time
import logging
from datetime import datetime
from typing import Optional

from openai import OpenAI
from src.agent.schema import IntentResult

class IntentDetectionError(Exception):
    """Custom error ketika klasifikasi intent gagal total."""
    pass


def classify_intent(question: str, model: Optional[str] = None) -> IntentResult:
    """
    Klasifikasi intent berbasis LLM few-shot prompt.
    Jika LLM gagal → fallback ke default intent 'factual' (vector retriever).
    """
    start_time = time.time()

    # --- Load credentials dan model ---
    model_name = model or os.getenv("ROUTER_MODEL", "gpt-4o")
    openai_api_key = os.getenv("OPENAI_API_KEY") or os.getenv("ROUTER_API_KEY")

    if not openai_api_key:
        raise IntentDetectionError("Missing OpenAI/Router API key")

    client = OpenAI(api_key=openai_api_key)

    # --- Few-shot examples ---
    system_prompt = (
        "You are an Intent Classifier for a retrieval-based AI system.\n"
        "Your task is to identify which retriever mode best fits the user's question.\n"
        "You must respond in JSON with keys: intent, confidence, reasoning.\n\n"
        "Available intents and their meanings:\n"
        "- factual → asks for factual or descriptive info (use vector retriever)\n"
        "- literal → keyword / phrase / text lookup (use fulltext retriever)\n"
        "- entity → refers to specific people, companies, or named entities (use entity_vector)\n"
        "- relational → asks about relationships, dependencies, or structures (use graph)\n"
        "- hybrid → combines text & graph reasoning (use graph_vector_fulltext)\n"
        "- conceptual → abstract, trend, or general idea (use global_vector_fulltext)\n"
    )

    few_shots = [
        {"role": "user", "content": "Apa itu Joget DX?"},
        {"role": "assistant", "content": '{"intent": "factual", "confidence": 0.9, "reasoning": "Question seeks a factual definition"}'},
        {"role": "user", "content": "Siapa CEO dari perusahaan ITAsoft?"},
        {"role": "assistant", "content": '{"intent": "entity", "confidence": 0.88, "reasoning": "Asks for a named entity related to a company"}'},
        {"role": "user", "content": "Bagaimana hubungan antara invoice dan pembayaran?"},
        {"role": "assistant", "content": '{"intent": "relational", "confidence": 0.91, "reasoning": "Relationship-type question"}'},
        {"role": "user", "content": "Bandingkan Joget DX dan PowerApps."},
        {"role": "assistant", "content": '{"intent": "hybrid", "confidence": 0.87, "reasoning": "Comparison requires text & structured reasoning"}'},
        {"role": "user", "content": "Jelaskan tren low-code platform di Indonesia."},
        {"role": "assistant", "content": '{"intent": "conceptual", "confidence": 0.86, "reasoning": "Abstract trend or conceptual query"}'},
    ]

    # --- Build chat ---
    messages = [{"role": "system", "content": system_prompt}] + few_shots + [
        {"role": "user", "content": question}
    ]

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.1,
            max_tokens=500,
        )

        raw_output = response.choices[0].message.content.strip()

        # pastikan output berbentuk JSON
        import json
        parsed = json.loads(raw_output)

        intent = parsed.get("intent", "factual")
        confidence = float(parsed.get("confidence", 0.75))
        reasoning = parsed.get("reasoning", "LLM classified intent")

        latency_ms = (time.time() - start_time) * 1000.0

        logging.info(
            f"[IntentClassifier] intent={intent} confidence={confidence:.2f} model={model_name} latency={latency_ms:.1f}ms"
        )

        return IntentResult(
            intent=intent,
            confidence=confidence,
            reasoning=reasoning,
            model_used=model_name,
            latency_ms=latency_ms,
            timestamp=datetime.utcnow(),
        )

    except Exception as e:
        # fallback aman
        latency_ms = (time.time() - start_time) * 1000.0
        logging.error(f"[IntentClassifier] LLM failed: {e}. Fallback to 'factual' intent.")

        return IntentResult(
            intent="factual",
            confidence=0.6,
            reasoning=f"Fallback to default due to error: {e}",
            model_used=model_name,
            latency_ms=latency_ms,
            timestamp=datetime.utcnow(),
        )
