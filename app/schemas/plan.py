"""분석 계획(Plan) 스키마. C 담당 계산 엔진이 소비할 구조화 JSON."""
from typing import Literal

from pydantic import BaseModel, Field

from app.services.areas import load_areas

# 지원 지역 20곳 (data/area_map.csv 의 area_name). 모델 출력 형식(JSON Schema)에도 그대로 들어간다.
Region = Literal[tuple(load_areas())]  # type: ignore[valid-type]
AggOp = Literal["sum", "avg", "growth_rate", "per_store"]  # avg=분기당 평균, per_store=점포당 월평균(매출 지표만)
FilterOp = Literal["eq", "in", "gte", "lte"]
Comparison = Literal["none", "region", "industry"]
# 분석 목적: other = 분류 불가/미지원 (재질문 처리)
Intent = Literal[
    "lookup", "region_comparison", "industry_comparison", "sales_trend", "ranking", "other"
]


# ---- 데이터셋 메타데이터 (요청으로 전달 가능, 미전달 시 기본값 사용) ----
class ColumnMeta(BaseModel):
    name: str
    dtype: Literal["string", "number", "date"]
    role: Literal["dimension", "measure"]
    allowed_values: list[str] | None = None


class DatasetMeta(BaseModel):
    columns: list[ColumnMeta] = Field(..., min_length=1)


# ---- LLM 출력 스키마 (Ollama format 으로 전달) ----
class MetricSpec(BaseModel):
    column: str
    op: AggOp


class FilterSpec(BaseModel):
    column: str
    op: FilterOp
    value: str | list[str]


class PeriodSpec(BaseModel):
    start: str | None = Field(None, description="YYYY-MM")
    end: str | None = Field(None, description="YYYY-MM")


class PlanDraft(BaseModel):
    status: Literal["ok", "needs_clarification"]
    intent: Intent = Field("other", description="분석 목적. 분류 불가/추천/순위 요청은 other")
    regions: list[Region] = []
    industries: list[str] = []
    metrics: list[MetricSpec] = []
    group_by: list[str] = []
    comparison: Comparison = "none"
    filters: list[FilterSpec] = []
    period: PeriodSpec | None = None
    missing_fields: list[str] = []
    clarification_question: str | None = None


# ---- API ----
class PlanRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    dataset: DatasetMeta | None = None


class AnalysisPlan(BaseModel):
    intent: Intent
    regions: list[Region]
    industries: list[str]
    metrics: list[MetricSpec]
    group_by: list[str]
    comparison: Comparison
    filters: list[FilterSpec]
    period: PeriodSpec | None
    time_column: str | None = None
    assumptions: list[str] = Field([], description="질문에 없어서 기본값으로 가정한 것 (답변에 밝힌다)")
    rank_order: Literal["desc", "asc"] | None = Field(None, description="ranking 정렬 방향")


class PlanResponse(BaseModel):
    status: Literal["ok", "needs_clarification"]
    plan: AnalysisPlan | None = None
    missing_fields: list[str] = []  # missing_conditions + missing_columns
    missing_conditions: list[str] = Field([], description="질문에서 부족한 분석 조건: region/industry/period/metric/analysis_type")
    missing_columns: list[str] = Field([], description="필요하지만 데이터셋에 없는 컬럼/지표")
    reason: str | None = None
    clarification_question: str | None = None
    suggested_questions: list[str] = Field([], description="바로 보낼 수 있는 고친 질문(서버 검증 통과)")
    model: str
    elapsed_ms: int