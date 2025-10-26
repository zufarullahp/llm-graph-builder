from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


# === Request dari Frontend ===
class AgentChatRequest(BaseModel):
    question: str
    session_id: str
    document_names: Optional[List[str]] = []
    llm_router_model: Optional[str] = None
    mode_policy: Optional[str] = "llm_first"
    router_flags: Optional[Dict[str, Any]] = {}
    email: Optional[str] = None
    uri: str
    userName: str
    password: str
    database: str


# === Hasil Classifier ===
class IntentResult(BaseModel):
    intent: str
    confidence: float
    reasoning: str
    model_used: str
    latency_ms: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# === Mapping hasil Router ===
class RetrieverPlan(BaseModel):
    primary_mode: str
    fallback_modes: List[str]
    policy_used: str
    intent: str
    confidence: float
    reasoning: str
    trace_id: str


# === Output dari /chat_bot ===
class ChatBotResult(BaseModel):
    message: str
    info: Dict[str, Any]
    session_id: str
    raw_response: Dict[str, Any]


# === Evaluasi hasil retriever ===
class EvaluationResult(BaseModel):
    is_valid: bool
    score: float
    sources_count: int
    latency_ms: float
    reasoning: Optional[str] = None
    fallback_needed: bool = False


# === Final Response ===
class AgentChatResponse(BaseModel):
    status: str = Field(default="Success")
    message: str
    mode_used: str
    router: Dict[str, Any]
    info: Dict[str, Any]
    session_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
