"""B의 코드(app/)를 고치지 않고, B의 HttpCalculator가 C 엔진을 호출해 검증까지 통과하는지 확인한다.

B의 계획 → 계산 요청 변환(build_request), 응답 검증(verify_result), 스키마(CalcResult)를 그대로 쓴다.
"""
import asyncio

import pytest

pytest.importorskip("pandas")
httpx = pytest.importorskip("httpx")

from app.schemas.plan import AnalysisPlan, FilterSpec, MetricSpec, PeriodSpec  # noqa: E402
from app.services.calc.builder import build_request  # noqa: E402
from app.services.calc.errors import CalcEngineError  # noqa: E402
from app.services.calc.http_adapter import HttpCalculator  # noqa: E402

from calc_engine.main import app as engine_app  # noqa: E402


def call_engine(plan: AnalysisPlan):
    async def run():
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=engine_app), base_url="http://calc-engine")
        try:
            calc = HttpCalculator("http://calc-engine", timeout=30, client=client)
            return await calc.calculate(build_request(plan, "commercial_area_v1"))
        finally:
            await client.aclose()
    return asyncio.run(run())


def plan(**kw) -> AnalysisPlan:
    base = dict(intent="region_comparison", regions=[], industries=[], metrics=[], group_by=[],
                comparison="none", filters=[], period=None, time_column="year_month")
    return AnalysisPlan(**{**base, **kw})


def test_b_region_comparison_passes_b_verification():
    result = call_engine(plan(
        regions=["성수", "홍대"], industries=["카페"],
        metrics=[MetricSpec(column="est_sales", op="sum")], group_by=["region"], comparison="region",
        filters=[FilterSpec(column="industry", op="eq", value="카페")],
        period=PeriodSpec(start="2025-10", end="2025-12"),
    ))
    assert result.status == "ok" and result.is_mock is False
    got = {r.group["region"]: r.values["est_sales.sum"] for r in result.results}
    assert got == {"성수": 15_496_172_851, "홍대": 27_768_312_903}


def test_b_growth_rate_passes_b_verification():
    # B는 기준 기간을 '직전 같은 길이'로 만든다: 2025년 전체 → 2024년 전체
    result = call_engine(plan(
        intent="sales_trend", regions=["강남"],
        metrics=[MetricSpec(column="est_sales", op="growth_rate")], group_by=["industry"],
        period=PeriodSpec(start="2025-01", end="2025-12"),
    ))
    assert result.status == "ok"
    assert result.applied.baseline_period == PeriodSpec(start="2024-01", end="2024-12")
    assert len(result.results) > 10


def test_b_trend_by_year_month_passes_b_verification():
    result = call_engine(plan(
        intent="sales_trend", regions=["홍대"], metrics=[MetricSpec(column="est_sales", op="sum")],
        group_by=["year_month"], period=PeriodSpec(start="2025-01", end="2025-12"),
    ))
    assert [r.group["year_month"] for r in result.results] == ["2025Q1", "2025Q2", "2025Q3", "2025Q4"]


def test_b_store_count_from_store_data():
    # 점포 데이터(OA-22172) 연결 후: B 규격의 store_count가 그대로 동작. 사이트 서교동 2025Q4 점포수 8,820
    result = call_engine(plan(
        regions=["홍대"], metrics=[MetricSpec(column="store_count", op="sum")], group_by=["region"],
        period=PeriodSpec(start="2025-10", end="2025-12"),
    ))
    assert result.status == "ok"
    assert result.results[0].values["store_count.sum"] == 8820


def test_b_receives_engine_error_for_unknown_column():
    with pytest.raises(CalcEngineError) as e:
        call_engine(plan(metrics=[MetricSpec(column="profit", op="sum")]))
    assert e.value.error.code == "COLUMN_NOT_FOUND"
