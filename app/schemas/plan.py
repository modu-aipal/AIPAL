"""분석 계획(Plan) 스키마. C 담당 계산 엔진이 소비할 구조화 JSON."""
from typing import Literal

from pydantic import BaseModel, Field

from app.services.areas import load_areas

# 지원 지역 20곳 (data/area_map.csv 의 area_name). 모델 출력 형식(JSON Schema)에도 그대로 들어간다.
Region = Literal[tuple(load_areas())]  # type: ignore[valid-type]
AggOp = Literal["sum", "avg", "growth_rate", "per_store", "ratio"]  # avg=분기당 평균, per_store=점포당 월평균(매출 지표만), ratio=구성비·점포 비율(C v1.1)
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


# 사용자가 말한 '잘나간다/뜬다' 같은 관용 표현이 가리키는 개념. 코드가 이것을 데이터의 지표로 바꾼다.
#  overall=잘나가는·장사 잘되는·인기·돈 되는(규모+증가+점포당을 함께 본다), size=매출 규모, growth=뜨는·성장·증가,
#  efficiency=점포당·한 달에 얼마나 버는, count=점포 몇 개
Concept = Literal["overall", "size", "growth", "efficiency", "count", "closures", "openings", "none"]


class PlanDraft(BaseModel):
    status: Literal["ok", "needs_clarification"]
    intent: Intent = Field("other", description="분석 목적. 분류 불가/추천/순위 요청은 other")
    concept: Concept = Field("none", description="'잘나가는·뜨는·점포 몇 개' 같은 표현이 가리키는 개념")
    direction: Literal["high", "low"] = Field("high", description="높은/많은=high, 낮은/안 되는/하위=low")
    top_n: int | None = Field(None, ge=1, le=20, description="'TOP 3', '상위 5개'처럼 말한 개수")
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
    rank_order: Literal["desc", "asc"] | None = Field(None, description="여러 행을 정렬하는 방향")
    top_n: int | None = Field(None, description="순위·업종 비교에서 보여 줄 개수 (None이면 전부)")
    sort_by: str | None = Field(None, description="정렬 기준 지표 키 '<컬럼>.<연산>' (예: est_sales.growth_rate)")
    concept: str | None = Field(None, description="해석한 개념 (overall/size/growth/efficiency/count/composition/location/competition)")
    disclaimers: list[str] = Field([], description="답변에 반드시 붙일 한계 안내 (예: 추천이 아닌 데이터 순위)")
    kind: str | None = Field(None, description="판단·특수 질문의 종류 (startup/income/survival/outlook/compare/location/competition/composition)")
    growth_basis: Literal["previous", "year_over_year"] = Field(
        "previous", description="증감률 비교 기준: previous=직전 같은 길이 기간, year_over_year=전년 같은 기간")


class PlanResponse(BaseModel):
    # info = 계산 없이 데이터 자체를 설명하는 답 (출처·기준일·추정매출 뜻 등). info_text 에 들어 있다.
    status: Literal["ok", "needs_clarification", "info"]
    info_text: str | None = None
    info_topic: str | None = None
    plan: AnalysisPlan | None = None
    missing_fields: list[str] = []  # missing_conditions + missing_columns
    missing_conditions: list[str] = Field([], description="질문에서 부족한 분석 조건: region/industry/period/metric/analysis_type")
    missing_columns: list[str] = Field([], description="필요하지만 데이터셋에 없는 컬럼/지표")
    reason: str | None = None
    clarification_question: str | None = None
    suggested_questions: list[str] = Field([], description="바로 보낼 수 있는 고친 질문(서버 검증 통과)")
    model: str
    elapsed_ms: int