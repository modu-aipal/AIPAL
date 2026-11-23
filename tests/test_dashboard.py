import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes import calc as calc_route
from app.core.config import get_settings
from app.main import app
from app.schemas.calc import CalcRequest
from app.schemas.plan import AnalysisPlan
from app.services import explain, planner
from app.services.calc import build_request
from app.services.calc.http_adapter import HttpCalculator
from app.services.calc.mock import MockCalculator
from app.services.dataset import area_ids

client = TestClient(app)
URL = "/api/dashboard/analyze"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("CALC_MODE", "mock")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("API_KEY", "")  # 인증은 test_security.py 에서 검증
    get_settings.cache_clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()


PLAN_OK = {
    "status": "ok", "intent": "region_comparison", "regions": ["성수", "홍대"],
    "metrics": [{"column": "est_sales", "op": "sum"}],
}
SINGLE = {
    "status": "ok", "intent": "sales_trend", "regions": ["홍대"],
    "metrics": [{"column": "est_sales", "op": "sum"}],
}


def fake_llms(monkeypatch, plan_payload, explain_fn):
    """planner 호출(format 있음)과 explain 호출(format 없음)을 구분해서 가짜 응답."""
    async def fake_chat(message, **kw):
        if kw.get("format") is not None:
            return "m", json.dumps(plan_payload)
        return "m", explain_fn(message)

    monkeypatch.setattr(planner.ollama, "chat", fake_chat)
    monkeypatch.setattr(explain.ollama, "chat", fake_chat)


def facts_of(message: str) -> str:
    return message.split("<facts>")[1].split("</facts>")[0]


# ---- area / sql ----
def test_area_ids():
    assert area_ids(["성수"]) == "seongsu"
    assert area_ids(["성수", "홍대"]) == "seongsu,hongdae"
    assert area_ids([]) == ""


def test_response_has_exactly_three_fields_and_mock_marked(monkeypatch):
    fake_llms(monkeypatch, SINGLE, lambda m: "홍대의 분기별 추정매출 합계를 정리했습니다.")
    r = client.post(URL, json={"question": "홍대의 음식점 분기별 매출을 보여줘."})
    assert r.status_code == 200
    b = r.json()
    assert set(b) == {"area", "sql", "text"}
    assert b["area"] == "hongdae" and b["sql"] == ""
    assert b["text"].startswith("[테스트용 Mock")
    assert r.headers["x-is-mock"] == "true"


def test_multi_region_area_is_comma_joined(monkeypatch):
    fake_llms(monkeypatch, PLAN_OK, lambda m: "비교 결과입니다.")
    r = client.post(URL, json={"question": "성수와 홍대의 카페 매출을 비교해줘."})
    assert r.json()["area"] == "seongsu,hongdae"


def test_sql_returned_only_when_engine_reports_executed_sql(monkeypatch):
    class SqlEngine(MockCalculator):
        async def calculate(self, req):
            res = await super().calculate(req)
            res.executed_sql = "SELECT region, SUM(est_sales) FROM t GROUP BY region"
            return res

    app.dependency_overrides[calc_route._calculator] = lambda: SqlEngine()
    fake_llms(monkeypatch, PLAN_OK, lambda m: "ok")
    r = client.post(URL, json={"question": "성수와 홍대의 카페 매출을 비교해줘."})
    assert r.json()["sql"].startswith("SELECT")


# ---- text grounding ----
def test_text_uses_only_calc_numbers_when_model_complies(monkeypatch):
    def good(m):
        line = [l for l in facts_of(m).splitlines() if l.startswith("[")][0]
        return "첫 번째 결과: " + line

    fake_llms(monkeypatch, SINGLE, good)
    r = client.post(URL, json={"question": "홍대의 음식점 분기별 매출을 보여줘."})
    assert r.status_code == 200 and "추정매출 합계" in r.json()["text"]


def test_invented_number_falls_back_to_template(monkeypatch):
    calls = []

    def bad(m):
        calls.append(1)
        return "홍대 매출은 987654321원으로 성수의 3.7배입니다."

    fake_llms(monkeypatch, SINGLE, bad)
    r = client.post(URL, json={"question": "홍대의 음식점 분기별 매출을 보여줘."})
    text = r.json()["text"]
    assert len(calls) == explain.MAX_ATTEMPTS  # 재시도 후 포기
    assert "987654321" not in text and "3.7" not in text
    assert "계산 결과:" in text  # 결정적 템플릿


def test_ungrounded_number_detector():
    facts = ["[성수] 추정매출 합계 1,714 (사용 행 152)", "분석 기간: 2024-01~2024-12"]
    assert explain.ungrounded_numbers("성수 매출은 1714이고 기간은 2024년입니다.", facts, 1) == []
    assert explain.ungrounded_numbers("성수 매출은 2,000입니다.", facts, 1) == ["2000"]


def test_growth_percent_and_null_formatting():
    assert explain._fmt_value("growth_rate", 0.1279, []) == "+12.8%"
    assert explain._fmt_value("growth_rate", -0.0406, []) == "-4.1%"
    assert "기준 기간 값이 0" in explain._fmt_value("growth_rate", None, ["baseline_zero"])


# ---- clarification / errors ----
def test_clarification_returns_422_without_calc(monkeypatch):
    called = []

    class Spy(MockCalculator):
        async def calculate(self, req):
            called.append(1)
            return await super().calculate(req)

    app.dependency_overrides[calc_route._calculator] = lambda: Spy()
    fake_llms(monkeypatch, {"status": "ok", "intent": "other"}, lambda m: "x")
    r = client.post(URL, json={"question": "분석 좀 해줘"})
    d = r.json()["detail"]
    assert r.status_code == 422 and d["error"] == "needs_clarification" and not called


def test_calc_error_result_returns_502(monkeypatch):
    class ErrEngine(MockCalculator):
        async def calculate(self, req):
            return self._error(req, "NO_DATA", "조건에 맞는 데이터 없음")

    app.dependency_overrides[calc_route._calculator] = lambda: ErrEngine()
    fake_llms(monkeypatch, PLAN_OK, lambda m: "x")
    r = client.post(URL, json={"question": "성수와 홍대의 카페 매출을 비교해줘."})
    assert r.status_code == 502 and r.json()["detail"]["engine_error"]["code"] == "NO_DATA"


def test_ollama_down_during_explain_returns_503(monkeypatch):
    from app.services import ollama

    async def chat(message, **kw):
        if kw.get("format") is not None:
            return "m", json.dumps(PLAN_OK)
        raise ollama.OllamaUnavailableError("down")

    monkeypatch.setattr(planner.ollama, "chat", chat)
    monkeypatch.setattr(explain.ollama, "chat", chat)
    r = client.post(URL, json={"question": "성수와 홍대의 카페 매출을 비교해줘."})
    assert r.status_code == 503


def test_engine_timeout_and_bad_response_mapped(monkeypatch):
    def handler_timeout(request):
        raise httpx.ReadTimeout("slow")

    def make(handler):
        c = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://engine")
        return HttpCalculator("http://engine", 5, client=c)

    fake_llms(monkeypatch, PLAN_OK, lambda m: "x")
    app.dependency_overrides[calc_route._calculator] = lambda: make(handler_timeout)
    assert client.post(URL, json={"question": "성수와 홍대의 카페 매출을 비교해줘."}).status_code == 504
    app.dependency_overrides[calc_route._calculator] = lambda: make(lambda r: httpx.Response(200, json={"x": 1}))
    assert client.post(URL, json={"question": "성수와 홍대의 카페 매출을 비교해줘."}).status_code == 502


def test_real_engine_result_has_no_mock_prefix(monkeypatch):
    """실제(비 Mock) 엔진 결과면 Mock 표시가 붙지 않아야 한다."""
    class RealLike(MockCalculator):
        async def calculate(self, req):
            res = await super().calculate(req)
            res.is_mock = False
            res.data_source = "commercial_area_db"
            res.data_version = "2024-12-01"
            return res

    app.dependency_overrides[calc_route._calculator] = lambda: RealLike()
    fake_llms(monkeypatch, SINGLE, lambda m: "설명입니다.")
    r = client.post(URL, json={"question": "홍대의 음식점 분기별 매출을 보여줘."})
    assert r.status_code == 200 and "x-is-mock" not in r.headers
    assert not r.json()["text"].startswith("[테스트용")


def test_existing_calc_result_accepts_executed_sql_optional():
    req = build_request(
        AnalysisPlan.model_validate(dict(
            intent="region_comparison", regions=["성수"], industries=[],
            metrics=[{"column": "est_sales", "op": "sum"}], group_by=["region"],
            comparison="region", filters=[], period=None, time_column="quarter")),
        "ds", "rid")
    assert isinstance(req, CalcRequest)


def test_ranking_judgment_words_rejected(monkeypatch):
    calls = []

    def ranked(m):
        calls.append(1)
        return "홍대가 가장 높고 창업을 추천합니다."

    fake_llms(monkeypatch, SINGLE, ranked)
    r = client.post(URL, json={"question": "홍대의 음식점 분기별 매출을 보여줘."})
    assert len(calls) == explain.MAX_ATTEMPTS
    assert "추천" not in r.json()["text"] and "계산 결과:" in r.json()["text"]
    assert explain.judgment_words("가장 큰 증가율") == ["가장"]


# ---- 엔진 notes 전달 ----
def _engine_with_notes(notes_by_region):
    class NotedEngine(MockCalculator):
        async def calculate(self, req):
            res = await super().calculate(req)
            res.is_mock = False
            res.data_source = "commercial_area_db"
            res.data_version = "2024-12-01"
            for row in res.results:
                row.notes = list(notes_by_region.get(row.group.get("region"), []))
            return res

    return NotedEngine()


def test_engine_notes_are_appended_to_text(monkeypatch):
    notes = {
        "성수": ["region_dong_count: 4", "industry_group: 카페=커피-음료",
                "pre_2024_basis_unconfirmed: 2021~2023년 자료의 재산출 여부는 확인 중입니다"],
        "홍대": ["region_dong_count: 1", "industry_group: 카페=커피-음료",
                "pre_2024_basis_unconfirmed: 2021~2023년 자료의 재산출 여부는 확인 중입니다"],
    }
    app.dependency_overrides[calc_route._calculator] = lambda: _engine_with_notes(notes)
    fake_llms(monkeypatch, PLAN_OK, lambda m: "비교 결과입니다.")
    text = client.post(URL, json={"question": "성수와 홍대의 카페 매출을 비교해줘."}).json()["text"]
    assert text.startswith("비교 결과입니다.")
    assert "※ 주의: 2021~2023년 자료의 재산출 여부는 확인 중입니다" in text
    assert text.count("※ 주의") == 1  # 행마다 중복되지 않음
    assert "성수 4개, 홍대 1개" in text
    assert "※ 업종 묶음: 카페=커피-음료" in text


def test_caveats_added_even_on_template_fallback(monkeypatch):
    notes = {"성수": ["region_dong_count: 4"], "홍대": ["region_dong_count: 1"]}
    app.dependency_overrides[calc_route._calculator] = lambda: _engine_with_notes(notes)
    fake_llms(monkeypatch, PLAN_OK, lambda m: "홍대가 가장 높습니다 99999")
    text = client.post(URL, json={"question": "성수와 홍대의 카페 매출을 비교해줘."}).json()["text"]
    assert "계산 결과:" in text and "성수 4개, 홍대 1개" in text


def test_baseline_notes_and_mock_note_not_duplicated_as_caveats():
    from app.schemas.calc import CalcResult  # noqa: F401
    from app.services.explain import build_caveats

    class R:  # 최소 결과 흉내
        class Row:
            def __init__(self, notes, group):
                self.notes, self.group = notes, group
        results = [Row(["MOCK_TEST_DATA: 가짜 값", "baseline_zero"], {"industry": "카페"})]

    assert build_caveats(R) == []


# ---- 표시 규칙 (docs/DATA.md 6절): 억 원 / % 소수 첫째 자리 / 건수 쉼표 ----
def test_display_rules_amount_ratio_count():
    f = explain._fmt_value
    assert f("sum", 519_250_000_000.0, [], "est_sales") == "5,192.5억 원"
    assert f("sum", 281_215_234_886.0, [], "est_sales") == "2,812.2억 원"
    assert f("sum", 40_000_000.0, [], "weekend_sales") == "0.4억 원"
    assert f("sum", 224_959.0, [], "est_count") == "224,959건"
    assert f("growth_rate", 0.048, [], "est_sales") == "+4.8%"


def test_facts_use_display_format_and_text_grounding_follows(monkeypatch):
    seen = {}

    def llm(m):
        seen["facts"] = facts_of(m)
        return "비교 결과입니다."

    fake_llms(monkeypatch, PLAN_OK, llm)
    client.post(URL, json={"question": "성수와 홍대의 카페 매출을 비교해줘."})
    assert "억 원" in seen["facts"] and "," in seen["facts"]
    # 원 단위 긴 숫자(소수점 없는 10자리 이상)가 설명 근거에 남아 있지 않아야 함
    import re
    assert not re.search(r"\d{1,3}(,\d{3}){3,}(?!\d)", seen["facts"].split("사용 행 수")[0] + "")


def test_model_must_copy_display_numbers(monkeypatch):
    def llm(m):
        line = [l for l in facts_of(m).splitlines() if l.startswith("[")][0]
        return "성수의 값은 " + line.split("합계 ")[1].split(" (")[0] + "입니다."

    fake_llms(monkeypatch, PLAN_OK, llm)
    t = client.post(URL, json={"question": "성수와 홍대의 카페 매출을 비교해줘."}).json()["text"]
    assert "억 원" in t and "계산 결과:" not in t  # 표시 숫자를 그대로 복사하면 통과
