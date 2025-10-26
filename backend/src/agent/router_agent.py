from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime
import traceback

# Import schema dan orchestrator
from src.agent.schema import AgentChatRequest, AgentChatResponse
from src.agent.orchestrator import run_agent_chat

router = APIRouter(prefix="/agent_chat", tags=["Agent Chat"])


@router.post("", response_model=AgentChatResponse)
async def agent_chat_endpoint(
    question: str = Form(...),
    session_id: str = Form(...),
    document_names: str = Form("[]"),
    llm_router_model: str = Form("gpt-4o-mini"),
    mode_policy: str = Form("llm_first"),
    email: str = Form(None),
    uri: str = Form(...),
    userName: str = Form(...),
    password: str = Form(...),
    database: str = Form(...),
):
    """
    Entry point baru untuk Agent Chat.
    Agent akan:
      1. Menganalisa intent pertanyaan (LLM Classifier)
      2. Memilih retriever plan (mapper)
      3. Memanggil /chat_bot (FastAPI retriever backend)
      4. Mengevaluasi hasil & menyusun respon final
    """

    try:
        # 🧩 Buat request object
        request_data = AgentChatRequest(
            question=question,
            session_id=session_id,
            document_names=[] if document_names == "[]" else document_names.split(","),
            llm_router_model=llm_router_model,
            mode_policy=mode_policy,
            email=email,
            uri=uri, 
            userName=userName, 
            password=password, 
            database=database,
        )

        # 🚀 Jalankan agent orchestration pipeline
        response: AgentChatResponse = await run_agent_chat(request_data)

        # ✅ Kembalikan hasil final
        return JSONResponse(
            status_code=200,
            content=response.model_dump(mode="json"),
        )

    except HTTPException as http_exc:
        raise http_exc

    except Exception as e:
        traceback.print_exc()
        error_msg = str(e)
        fail_response = {
            "status": "Failed",
            "message": f"Agent pipeline error: {error_msg}",
            "mode_used": None,
            "router": {},
            "info": {},
            "session_id": session_id,
            "created_at": datetime.utcnow().isoformat(),
        }
        return JSONResponse(status_code=500, content=fail_response)
