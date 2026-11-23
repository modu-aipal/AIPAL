"""계산 엔진(C 담당) API 규격 v1.0 — 요청/응답 스키마.

상세 설명과 예시는 docs/CALC_API.md 참고.
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.plan import AggOp, FilterSpec, PeriodSpec

SPEC_VERSION = "1.0"
GROWTH_FORMULA = "(current - baseline) / baseline"

ErrorCode = Literal[
    "INVALID_REQUEST",
    "DATASET_NOT_FOUND",
    "COLUMN_NOT_FOUND",
    "UNSUPPORTED_OPERATION",
    "NO_DATA",
    "INTERNAL_ERROR",
]


# ---------------- 요청 ----------------
class CalcMetric(BaseModel):
    column: str
    op: AggOp


class GrowthSpec(BaseModel):
    """growth_rate 계산 규칙. growth_rate 지표가 있을 때만 포함."""

    aggregation: Literal["sum"] = "sum"  # 기간별 값은 sum 으로 집계
    current_period: PeriodSpec  # 비교 대상(현재) 기간, YYYY-MM 양끝 포함
    baseline_period: PeriodSpec  # 비교 기준 기간 (현재 기간 직전의 같은 길이 기간)
    formula: Literal["(current - baseline) / baseline"] = GROWTH_FORMULA
    zero_baseline_policy: Literal["null"] = "null"  # baseline == 0 이면 값 null + 노트


class CalcRequest(BaseModel):
    spec_version: Literal["1.0", "1.1"] = SPEC_VERSION  # 1.1 = per_store/ratio 같은 확장 op를 쓸 때
    request_id: str
    dataset_id: str
    time_column: str | None = None
    metrics: list[CalcMetric] = Field(..., min_length=1)
    group_by: list[str] = []
    filters: list[FilterSpec] = []
    period: PeriodSpec | None = None  # sum/avg 에 적용. None 이면 전체 기간
    growth: GrowthSpec | None = None


# ---------------- 응답 ----------------
class CalcMethod(BaseModel):
    column: str
    op: AggOp
    formula: str  # 사람이 읽을 수 있는 계산식


class CalcApplied(BaseModel):
    """엔진이 실제로 적용한 조건 (요청과 일치해야 함)."""

    columns_used: list[str]
    operations: list[CalcMetric]
    group_by: list[str]
    filters: list[FilterSpec]
    period: PeriodSpec | None = None
    baseline_period: PeriodSpec | None = None


class CalcRow(BaseModel):
    group: dict[str, str] = {}
    values: dict[str, float | None]  # 키: "<column>.<op>"
    rows_used: int = Field(..., ge=0)
    notes: list[str] = []  # 예: baseline_zero, baseline_missing


class CalcError(BaseModel):
    code: ErrorCode
    message: str
    details: dict | None = None


class CalcResult(BaseModel):
    spec_version: Literal["1.0", "1.1"] = SPEC_VERSION  # 1.1 = 엔진의 ratio/share 확장 응답
    request_id: str
    status: Literal["ok", "error"]
    is_mock: bool = False  # 테스트용 Mock 결과면 반드시 true
    dataset_id: str
    data_version: str | None = None
    data_source: str | None = None
    rows_used: int = Field(0, ge=0)  # 전체 사용 행 수
    methods: list[CalcMethod] = []
    applied: CalcApplied | None = None
    results: list[CalcRow] = []
    # 엔진이 실제로 실행한 SQL이 있을 때만 채운다. Pandas 계산이면 null (v1.0 하위 호환 선택 필드)
    executed_sql: str | None = None
    error: CalcError | None = None

    @model_validator(mode="after")
    def _consistent(self):
        if self.status == "ok":
            if self.error is not None:
                raise ValueError("status=ok 인데 error가 있습니다")
            if not self.data_version or not self.data_source or self.applied is None:
                raise ValueError("status=ok 에는 data_version, data_source, applied 가 필요합니다")
        elif self.error is None:
            raise ValueError("status=error 에는 error가 필요합니다")
        return self


# ---------------- 우리 API ----------------
class CalcApiResponse(BaseModel):
    """/api/calc, /api/analyze 가 돌려주는 계산 결과 (Mock 여부 표시)."""

    is_mock: bool
    warning: str | None = None
    result: CalcResult
