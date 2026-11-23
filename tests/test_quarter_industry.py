"""C 엔진 실제 데이터 기준(분기 단위, 업종 63종, 점포 수 없음) 회귀 테스트."""
import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services import planner
from app.services.calc import build_request
from app.services.calc.mock import MockCalculator
from app.services.dataset import INDUSTRIES, INDUSTRY_GROUPS, REAL_INDUSTRIES, default_dataset
from app.services.planner import _period_from_question, _quarter_aligned, find_industries

client = TestClient(app)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("CALC_MODE", "mock")
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def plan_with(monkeypatch, q, payload):
    async def fake(message, **kw):
        return "m", json.dumps(payload)

    monkeypatch.setattr(planner.ollama, "chat", fake)
    r = client.post("/api/plan", json={"question": q})
    return r.json()


REGION_CMP = {"status": "ok", "intent": "region_comparison", "metrics": [{"column": "est_sales", "op": "sum"}]}
TREND = {"status": "ok", "intent": "sales_trend", "metrics": [{"column": "est_sales", "op": "sum"}]}


# ---------- 데이터셋 메타 ----------
def test_dataset_meta_matches_engine():
    cols = {c.name: c for c in default_dataset().columns}
    assert {"store_count", "general_store_count", "franchise_count", "open_count", "close_count"} <= set(cols)
    assert len(cols["region"].allowed_values) == 20  # 대시보드와 같은 20곳
    assert cols["quarter"].dtype == "date" and "year_month" not in cols
    assert {"est_sales", "est_count", "weekend_sales"} <= set(cols)
    assert len(REAL_INDUSTRIES) == 63 and len(set(REAL_INDUSTRIES)) == 63
    assert set(INDUSTRY_GROUPS) <= set(INDUSTRIES)
    assert len(INDUSTRIES) == len(set(INDUSTRIES))


# ---------- 업종 ----------
ALLOWED = INDUSTRIES


def test_real_industry_name_matched():
    assert find_industries("성수와 홍대의 한식음식점 매출", ALLOWED) == ["한식음식점"]


def test_group_name_matched_without_double_count():
    assert find_industries("강남의 음식점 매출", ALLOWED) == ["음식점"]
    assert find_industries("강남의 커피-음료 매출", ALLOWED) == ["커피-음료"]


def test_group_and_real_both_mentioned_in_order():
    assert find_industries("카페와 한식음식점 비교", ALLOWED) == ["카페", "한식음식점"]


def test_real_industry_reaches_calc_filter(monkeypatch):
    b = plan_with(monkeypatch, "성수와 홍대의 치킨전문점 매출 비교", {**REGION_CMP, "regions": ["성수", "홍대"]})
    assert b["status"] == "ok"
    assert {"column": "industry", "op": "eq", "value": "치킨전문점"} in b["plan"]["filters"]


# ---------- 기간(분기) ----------
@pytest.mark.parametrize("q,start,end", [
    ("2024년 1분기", "2024-01", "2024-03"),
    ("2024년 2분기 매출", "2024-04", "2024-06"),
    ("2024년 1~2분기", "2024-01", "2024-06"),
    ("2024Q4", "2024-10", "2024-12"),
    ("2024년 매출", "2024-01", "2024-12"),
])
def test_quarter_periods_parsed(q, start, end):
    p = _period_from_question(q)
    assert (p.start, p.end) == (start, end) and _quarter_aligned(p)


def test_month_period_not_quarter_aligned():
    p = _period_from_question("2024년 2월 매출")
    assert not _quarter_aligned(p)


def test_non_quarter_period_asks_clarification(monkeypatch):
    b = plan_with(monkeypatch, "2024년 2월 성수와 홍대의 카페 매출 비교", {**REGION_CMP, "regions": ["성수", "홍대"]})
    assert b["status"] == "needs_clarification" and b["missing_conditions"] == ["period"]
    assert "분기" in b["reason"]


def test_monthly_request_unsupported(monkeypatch):
    b = plan_with(monkeypatch, "홍대 음식점 월별 매출 보여줘", {**TREND, "regions": ["홍대"]})
    assert b["status"] == "needs_clarification"
    assert "월별 분석은 지원하지 않습니다" in b["reason"] and "분기별" in b["clarification_question"]


def test_quarterly_trend_groups_by_quarter(monkeypatch):
    b = plan_with(monkeypatch, "홍대 음식점 분기별 매출 보여줘", {**TREND, "regions": ["홍대"]})
    assert b["status"] == "ok"
    assert b["plan"]["group_by"] == ["quarter"] and b["plan"]["time_column"] == "quarter"


def test_model_made_up_period_is_ignored(monkeypatch):
    b = plan_with(monkeypatch, "홍대 음식점 분기별 매출", {**TREND, "regions": ["홍대"],
                  "period": {"start": "2024-02", "end": "2024-05"}})
    assert b["status"] == "ok" and b["plan"]["period"] is None


# ---------- 점포 수 ----------
def test_store_count_is_supported_as_quarterly_average(monkeypatch):
    b = plan_with(monkeypatch, "성수와 홍대의 카페 점포 수를 비교해줘", {**REGION_CMP, "regions": ["성수", "홍대"]})
    assert b["status"] == "ok"
    # 점포 수는 분기마다 쌓이는 값이라 합계가 아니라 분기당 평균으로 보낸다 (C 엔진 정의)
    assert b["plan"]["metrics"] == [{"column": "store_count", "op": "avg"}]
    assert "점포 수: 기간 내 분기 평균" in b["plan"]["assumptions"]


# ---------- Mock / avg ----------
@pytest.mark.anyio
async def test_mock_quarter_group_values_and_avg_formula():
    from app.schemas.plan import AnalysisPlan

    plan = AnalysisPlan.model_validate(dict(
        intent="sales_trend", regions=["홍대"], industries=[],
        metrics=[{"column": "est_sales", "op": "avg"}], group_by=["quarter"],
        comparison="none", filters=[], period={"start": "2024-01", "end": "2024-06"},
        time_column="quarter"))
    res = await MockCalculator().calculate(build_request(plan, "ds", "rid"))
    assert [r.group["quarter"] for r in res.results] == ["2024Q1", "2024Q2"]
    assert "분기당 평균" in res.methods[0].formula


def test_calc_result_accepts_engine_spec_1_1():
    from app.schemas.calc import CalcResult

    r = CalcResult(request_id="r", status="error", dataset_id="d", spec_version="1.1",
                   error={"code": "COLUMN_NOT_FOUND", "message": "점포수 없음"})
    assert r.spec_version == "1.1"
