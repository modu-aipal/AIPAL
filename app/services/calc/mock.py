"""테스트용 MockCalculator.

!! 모든 값은 해시로 만든 가짜 숫자이며 실제 상권 데이터가 아니다 !!
결과에는 is_mock=true, data_source="MOCK_TEST_DATA" 가 항상 표시된다.
APP_ENV=production 에서는 factory 가 사용을 막는다.
"""
import hashlib
import itertools

from app.schemas.calc import (
    GROWTH_FORMULA,
    CalcApplied,
    CalcError,
    CalcMethod,
    CalcRequest,
    CalcResult,
    CalcRow,
)
from app.services.calc.builder import _idx_to_ym, _ym_to_idx
from app.services.dataset import INDUSTRY_GROUPS, REGIONS, default_dataset

MOCK_SOURCE = "MOCK_TEST_DATA"
MOCK_VERSION = "mock-0"
MAX_GROUPS = 60


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _periods(req: CalcRequest) -> list[str]:
    """시간 그룹 값. 시간 컬럼이 quarter 이면 분기 코드(2025Q4), 아니면 월."""
    p = req.period
    quarterly = req.time_column == "quarter"
    if p and p.start and p.end:
        s, e = _ym_to_idx(p.start), _ym_to_idx(p.end)
        if quarterly:
            return [f"{i // 12}Q{i % 12 // 3 + 1}" for i in range(s, min(e, s + 23) + 1, 3)]
        return [_idx_to_ym(i) for i in range(s, min(e, s + 23) + 1)]
    return ["2024Q1", "2024Q2", "2024Q3"] if quarterly else ["2024-01", "2024-02", "2024-03"]


def _filter_values(req: CalcRequest, col: str, default: list[str]) -> list[str]:
    for f in req.filters:
        if f.column == col:
            return f.value if isinstance(f.value, list) else [f.value]
    return default


def _formula(m) -> str:
    if m.op == "sum":
        return f"sum({m.column})"
    if m.op == "avg":
        return f"sum({m.column}) / (기간 내 분기 수)  # 분기당 평균"
    if m.op == "per_store":
        return f"sum({m.column}) / (sum(store_count) × 3)  # 점포당 월평균"
    if m.op == "ratio":
        return f"sum({m.column}) / sum(분모)  # 구성비"
    return (
        f"{GROWTH_FORMULA}; current=sum({m.column}) over current_period, "
        f"baseline=sum({m.column}) over baseline_period; baseline==0 -> null"
    )


class MockCalculator:
    def __init__(self, dataset=None):
        self.ds = {c.name: c for c in (dataset or default_dataset()).columns}

    def _error(self, req, code, msg) -> CalcResult:
        return CalcResult(
            request_id=req.request_id, status="error", is_mock=True, dataset_id=req.dataset_id,
            data_version=MOCK_VERSION, data_source=MOCK_SOURCE,
            error=CalcError(code=code, message=msg),
        )

    async def calculate(self, req: CalcRequest) -> CalcResult:
        for m in req.metrics:
            c = self.ds.get(m.column)
            if c is None:
                return self._error(req, "COLUMN_NOT_FOUND", f"컬럼 없음: {m.column}")
            if c.dtype != "number":
                return self._error(req, "UNSUPPORTED_OPERATION", f"숫자 컬럼이 아님: {m.column}")
        for g in req.group_by:
            if g not in self.ds:
                return self._error(req, "COLUMN_NOT_FOUND", f"컬럼 없음: {g}")

        dims = []
        for g in req.group_by:
            if g == "region":
                vals = _filter_values(req, "region", REGIONS)
            elif g == "industry":
                vals = _filter_values(req, "industry", INDUSTRY_GROUPS)
            elif g == req.time_column:
                vals = _periods(req)
            else:
                vals = ["mock"]
            dims.append([(g, v) for v in vals])
        combos = list(itertools.islice(itertools.product(*dims), MAX_GROUPS)) if dims else [()]

        rows, total = [], 0
        for combo in combos:
            group = dict(combo)
            values, notes = {}, ["MOCK_TEST_DATA: 가짜 값, 실제 분석 결과 아님"]
            n = 50 + _h("rows", sorted(group.items())) % 200
            for m in req.metrics:
                key = f"{m.column}.{m.op}"
                seed = _h(m.column, m.op, sorted(group.items()))
                if m.op == "growth_rate":
                    if seed % 7 == 0:  # 기준값 0 규칙 시연
                        values[key] = None
                        notes.append("baseline_zero")
                    else:
                        values[key] = round(((seed % 4000) - 1000) / 10000, 4)
                elif m.op == "ratio":
                    values[key] = round(0.05 + (seed % 400) / 1000, 4)  # 가짜 값 (5~45%)
                elif m.op == "per_store":
                    values[key] = float((300 + seed % 2000) * 10_000)  # 가짜 값 (300~2,300만 원 규모)
                elif m.op == "sum":
                    values[key] = float((1000 + seed % 9000) * 1_000_000)  # 가짜 값 (10~100억 원 규모)
                else:
                    values[key] = round(10 + (seed % 900) / 10, 2)
            rows.append(CalcRow(group=group, values=values, rows_used=n, notes=notes))
            total += n

        used = sorted(
            {m.column for m in req.metrics} | set(req.group_by) | {f.column for f in req.filters}
        )
        return CalcResult(
            request_id=req.request_id, status="ok", is_mock=True, dataset_id=req.dataset_id,
            data_version=MOCK_VERSION, data_source=MOCK_SOURCE, rows_used=total,
            methods=[CalcMethod(column=m.column, op=m.op, formula=_formula(m)) for m in req.metrics],
            applied=CalcApplied(
                columns_used=used, operations=req.metrics, group_by=req.group_by,
                filters=req.filters, period=req.period,
                baseline_period=req.growth.baseline_period if req.growth else None,
            ),
            results=rows,
        )
