"""A 담당 대시보드용 응답 모델. 필드는 합의된 3개만 사용한다."""
from pydantic import BaseModel, Field, field_validator


class DashboardRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    # 이번 대화에서 직전에 한 질문들(오래된 순). "그럼 홍대는?"처럼 이어 묻는 질문을 이해하는 데만 쓰고 저장하지 않는다.
    # 잘못된 값은 오류 대신 무시한다 (없어도 지금처럼 동작한다).
    history: list[str] = Field(default_factory=list)

    @field_validator("history", mode="before")
    @classmethod
    def _clean(cls, v):
        from app.services.follow_up import clean_history

        return clean_history(v if isinstance(v, list) else None)


class DashboardResponse(BaseModel):
    area: str = Field(..., description="지역 식별값 (예: seongsu). 복수 지역/미지정은 docs/DASHBOARD_API.md 참고")
    sql: str = Field("", description="실제 실행된 SQL이 있을 때만. Pandas 계산이면 빈 문자열")
    text: str = Field(..., description="계산 결과에 존재하는 수치만 사용한 설명")
