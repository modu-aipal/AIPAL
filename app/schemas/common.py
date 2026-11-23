from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    app: str
    env: str
    version: str
    ollama_model: str
    # 분석 서버가 계산할 수 있는 지역(area_name). 대시보드가 어느 질문을 서버로 보낼지 정할 때 읽는다.
    regions: list[str] = []