import time

from fastapi import APIRouter, Depends, HTTPException


from app.core.security import require_api_key
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import ollama

router = APIRouter(tags=["chat (dev)"], dependencies=[Depends(require_api_key)])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """로컬 개발용 Ollama 테스트 API."""
    start = time.perf_counter()
    try:
        model, reply = await ollama.chat(
            req.message, system=req.system, model=req.model, temperature=req.temperature
        )
    except ollama.OllamaError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return ChatResponse(
        model=model, reply=reply, elapsed_ms=int((time.perf_counter() - start) * 1000)
    )