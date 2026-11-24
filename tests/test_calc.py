import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes import calc as calc_route
from app.core.config import get_settings
from app.main import app
from app.schemas.calc import CalcResult
from app.schemas.plan import AnalysisPlan
from app.services import planner
from app.services.calc import build_request, get_calculator
from app.services.calc.builder import baseline_for
from app.services.calc.errors import CalcConfigError, CalcRequestError
from app.services.calc.http_adapter import HttpCalculator
from app.services.calc.mock import MockCalculator

client = TestClient(app)


def plan(**kw) -> AnalysisPlan:
    base = dict(
        intent="region_comparison", regions=["성수", "홍대"], industries=["카페"],
        metrics=[{"column": "est_sales", "op": "sum"}], group_by=["region"],
        comparison="region", filters=[{"column": "industry", "op": "eq", "value": "카페"}],
        period=None, time_column="quarter",
    )
    base.update(kw)
    return AnalysisPlan.model_validate(base)


GROWTH = dict(
    intent="industry_comparison", regions=["강남"], industries=[],
    metrics=[{"column": "est_sales", "op": "growth_rate"}], group_by=["industry"],
    comparison="industry", filters=[], period={"start": "2024-01", "end": "2024-12"},
)


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch):
    monkeypatch.setenv("CALC_MODE", "mock")
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------- builder ----------
def test_builder_includes_region_and_industry_filters():
    r = build_request(plan(), "ds1", "rid")
    cols = {(f.column, f.op) for f in r.filters}
    assert ("industry", "eq") in cols and ("region", "in") in cols
    assert r.dataset_id == "ds1" and r.growth is None


def test_baseline_period_same_length_preceding():
    p = plan(**GROWTH)
    g = build_request(p, "ds1").growth
    assert g.baseline_period.model_dump() == {"start": "2023-01", "end": "2023-12"}
    assert g.formula == "(current - baseline) / baseline" and g.zero_baseline_policy == "null"
    b = baseline_for(plan(period={"start": "2024-02", "end": "2024-04"}).period)
    assert (b.start, b.end) == ("2023-11", "2024-01")


def test_growth_without_period_rejected():
    with pytest.raises(CalcRequestError):
        build_request(plan(**{**GROWTH, "period": None}), "ds1")


# ---------- mock ----------
@pytest.mark.anyio
async def test_mock_is_marked_and_matches_request():
    req = build_request(plan(**GROWTH), "ds1", "rid")
    res = await MockCalculator().calculate(req)
    assert res.is_mock and res.data_source == "MOCK_TEST_DATA" and res.status == "ok"
    assert res.applied.baseline_period.start == "2023-01"
    assert all("MOCK_TEST_DATA" in r.notes[0] for r in res.results)
    # growth null 은 사유(baseline_zero) 노트가 있어야 함
    for r in res.results:
        for v in r.values.values():
            assert v is not None or "baseline_zero" in r.notes


@pytest.mark.anyio
async def test_mock_unknown_column_returns_error():
    bad = build_request(plan(metrics=[{"column": "est_sales", "op": "sum"}]), "ds1")
    bad.metrics[0].column = "profit"
    res = await MockCalculator().calculate(bad)
    assert res.status == "error" and res.error.code == "COLUMN_NOT_FOUND"


# ---------- factory ----------
def test_mock_blocked_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    with pytest.raises(CalcConfigError):
        get_calculator()
    r = client.post("/api/calc", json=plan().model_dump())
    assert r.status_code == 503


def test_factory_http_mode(monkeypatch):
    monkeypatch.setenv("CALC_MODE", "http")
    get_settings.cache_clear()
    assert isinstance(get_calculator(), HttpCalculator)


# ---------- API (mock) ----------
def test_api_calc_mock_flagged():
    r = client.post("/api/calc", json=plan().model_dump())
    assert r.status_code == 200
    b = r.json()
    assert b["is_mock"] is True and "Mock" in b["warning"]
    assert b["result"]["data_source"] == "MOCK_TEST_DATA"
    assert b["result"]["applied"]["filters"]


def test_api_analyze_flow(monkeypatch):
    async def fake_chat(message, **kw):
        return "m", json.dumps({
            "status": "ok", "intent": "region_comparison", "regions": ["성수", "홍대"],
            "metrics": [{"column": "est_sales", "op": "sum"}],
        })

    monkeypatch.setattr(planner.ollama, "chat", fake_chat)
    r = client.post("/api/analyze", json={"question": "성수와 홍대의 카페 매출을 비교해줘."})
    b = r.json()
    assert r.status_code == 200 and b["status"] == "ok"
    assert b["plan_response"]["plan"]["industries"] == ["카페"]
    assert b["calc"]["is_mock"] is True
    applied = b["calc"]["result"]["applied"]
    assert {"column": "industry", "op": "eq", "value": "카페"} in applied["filters"]


def test_api_analyze_clarification_skips_calc(monkeypatch):
    called = []

    async def fake_chat(message, **kw):
        return "m", json.dumps({"status": "ok", "intent": "other"})

    class Spy(MockCalculator):
        async def calculate(self, req):
            called.append(1)
            return await super().calculate(req)

    monkeypatch.setattr(planner.ollama, "chat", fake_chat)
    app.dependency_overrides[calc_route._calculator] = lambda: Spy()
    try:
        r = client.post("/api/analyze", json={"question": "분석 좀 해줘"})
    finally:
        app.dependency_overrides.clear()
    assert r.json()["status"] == "needs_clarification" and r.json()["calc"] is None
    assert not called


# ---------- HTTP adapter ----------
def _adapter(handler):
    c = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://engine")
    return HttpCalculator("http://engine", 5, client=c)


async def _ok_body(req_json, **over):
    from app.schemas.calc import CalcRequest

    req = CalcRequest.model_validate(req_json)
    res = await MockCalculator().calculate(req)
    body = res.model_dump(mode="json")
    body["is_mock"] = False
    body["data_source"] = "commercial_area_db"
    body["data_version"] = "2024-12-01"
    body.update(over)
    return body


@pytest.mark.anyio
async def test_http_adapter_ok():
    req = build_request(plan(**GROWTH), "ds1", "rid")
    body = await _ok_body(req.model_dump(mode="json"))
    seen = {}

    def handler(r):
        seen["path"] = r.url.path
        seen["body"] = json.loads(r.content)
        return httpx.Response(200, json=body)

    res = await _adapter(handler).calculate(req)
    assert seen["path"] == "/calculate" and seen["body"]["growth"]["baseline_period"]["start"] == "2023-01"
    assert res.data_version == "2024-12-01" and not res.is_mock


@pytest.mark.anyio
@pytest.mark.parametrize("exc,status", [
    (httpx.ConnectError("x"), 503), (httpx.ReadTimeout("x"), 504),
])
async def test_http_adapter_transport_errors(exc, status):
    from app.services.calc.errors import CalcTimeoutError, CalcUnavailableError

    def handler(r):
        raise exc

    with pytest.raises((CalcTimeoutError, CalcUnavailableError)) as ei:
        await _adapter(handler).calculate(build_request(plan(), "ds1", "rid"))
    assert ei.value.status_code == status


@pytest.mark.anyio
async def test_http_adapter_bad_responses():
    from app.services.calc.errors import CalcResponseError

    req = build_request(plan(), "ds1", "rid")
    for resp in (
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"foo": 1}),
        httpx.Response(500, text="boom"),
    ):
        with pytest.raises(CalcResponseError):
            await _adapter(lambda r, resp=resp: resp).calculate(req)


@pytest.mark.anyio
async def test_http_adapter_rejects_mismatch_and_mock_flag():
    from app.services.calc.errors import CalcResponseError

    req = build_request(plan(), "ds1", "rid")
    good = await _ok_body(req.model_dump(mode="json"))
    # 필터 누락(업종 조건 무시) -> 거부
    nofilter = json.loads(json.dumps(good))
    nofilter["applied"]["filters"] = []
    with pytest.raises(CalcResponseError):
        await _adapter(lambda r: httpx.Response(200, json=nofilter)).calculate(req)
    # 다른 request_id
    with pytest.raises(CalcResponseError):
        await _adapter(lambda r: httpx.Response(200, json={**good, "request_id": "other"})).calculate(req)
    # 실제 엔진이 is_mock=true
    with pytest.raises(CalcResponseError):
        await _adapter(lambda r: httpx.Response(200, json={**good, "is_mock": True})).calculate(req)
    # null 값인데 사유 없음
    bad = json.loads(json.dumps(good))
    bad["results"][0]["values"]["est_sales.sum"] = None
    with pytest.raises(CalcResponseError):
        await _adapter(lambda r: httpx.Response(200, json=bad)).calculate(req)


@pytest.mark.anyio
async def test_http_adapter_engine_error():
    from app.services.calc.errors import CalcEngineError

    req = build_request(plan(), "ds1", "rid")
    body = {"request_id": "rid", "status": "error", "dataset_id": "ds1",
            "error": {"code": "DATASET_NOT_FOUND", "message": "no such dataset"}}
    with pytest.raises(CalcEngineError) as ei:
        await _adapter(lambda r: httpx.Response(404, json=body)).calculate(req)
    assert ei.value.error.code == "DATASET_NOT_FOUND"


def test_api_maps_engine_failures(monkeypatch):
    monkeypatch.setenv("CALC_MODE", "http")
    monkeypatch.setenv("CALC_ENGINE_URL", "http://127.0.0.1:1")  # 연결 불가
    get_settings.cache_clear()
    r = client.post("/api/calc", json=plan().model_dump())
    assert r.status_code == 503


def test_calc_result_schema_consistency():
    with pytest.raises(ValueError):
        CalcResult(request_id="r", status="ok", dataset_id="d")  # data_version 등 누락
    with pytest.raises(ValueError):
        CalcResult(request_id="r", status="error", dataset_id="d")  # error 누락


def test_baseline_for_year_over_year_shifts_twelve_months():
    from app.schemas.plan import PeriodSpec

    b = baseline_for(PeriodSpec(start="2025-10", end="2025-12"), "year_over_year")
    assert (b.start, b.end) == ("2024-10", "2024-12")
    c = baseline_for(PeriodSpec(start="2025-07", end="2026-06"), "year_over_year")
    assert (c.start, c.end) == ("2024-07", "2025-06")
    d = baseline_for(PeriodSpec(start="2025-10", end="2025-12"))
    assert (d.start, d.end) == ("2025-07", "2025-09")  # 기본은 직전 기간
