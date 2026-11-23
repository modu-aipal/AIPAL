"""AnalysisPlan -> CalcRequest 변환 (계산은 하지 않음)."""
import uuid

from app.schemas.calc import CalcMetric, CalcRequest, GrowthSpec
from app.schemas.plan import AnalysisPlan, FilterSpec, PeriodSpec
from app.services.calc.errors import CalcRequestError


def _ym_to_idx(ym: str) -> int:
    y, m = ym.split("-")
    return int(y) * 12 + int(m) - 1


def _idx_to_ym(i: int) -> str:
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def baseline_for(period: PeriodSpec) -> PeriodSpec:
    """현재 기간 직전의 같은 길이(개월) 기간. 예: 2024-01~2024-12 -> 2023-01~2023-12"""
    if not (period.start and period.end):
        raise CalcRequestError("growth_rate에는 기간(start, end)이 필요합니다")
    s, e = _ym_to_idx(period.start), _ym_to_idx(period.end)
    if e < s:
        raise CalcRequestError("기간의 start가 end보다 늦습니다")
    n = e - s + 1
    return PeriodSpec(start=_idx_to_ym(s - n), end=_idx_to_ym(s - 1))


def build_request(plan: AnalysisPlan, dataset_id: str, request_id: str | None = None) -> CalcRequest:
    filters = list(plan.filters)
    if plan.regions:  # 지역 범위도 필터로 전달
        filters.append(
            FilterSpec(column="region", op="eq", value=plan.regions[0])
            if len(plan.regions) == 1
            else FilterSpec(column="region", op="in", value=list(plan.regions))
        )
    growth = None
    if any(m.op == "growth_rate" for m in plan.metrics):
        if plan.period is None:
            raise CalcRequestError("growth_rate에는 기간이 필요합니다")
        growth = GrowthSpec(current_period=plan.period, baseline_period=baseline_for(plan.period))
    extended = any(m.op in ("per_store", "ratio") for m in plan.metrics)
    return CalcRequest(
        spec_version="1.1" if extended else "1.0",
        request_id=request_id or uuid.uuid4().hex,
        dataset_id=dataset_id,
        time_column=plan.time_column,
        metrics=[CalcMetric(column=m.column, op=m.op) for m in plan.metrics],
        group_by=list(plan.group_by),
        filters=filters,
        period=plan.period,
        growth=growth,
    )
