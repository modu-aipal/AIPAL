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






# ---- 답변 구조: 결론 한 줄 + 목록(코드) + 해석(모델, 검증) + 기준·주의(코드) ----
import re  # noqa: E402


def _ask(question="홍대의 음식점 분기별 매출을 보여줘."):
    r = client.post(URL, json={"question": question})
    assert r.status_code == 200, r.text
    return r.json()["text"].removeprefix(explain.MOCK_PREFIX)  # Mock 접두는 따로 검증한다


def test_answer_is_structured_headline_list_interpretation_caveats(monkeypatch):
    fake_llms(monkeypatch, SINGLE, lambda m: "분기마다 값이 달라지는 흐름입니다.")
    blocks = _ask().split("\n\n")
    head, *lines = blocks[0].split("\n")
    assert "분기별" in head and "추이" in head
    assert lines and all(l.startswith("• ") for l in lines)  # 분기마다 한 줄
    assert blocks[1].startswith("→ 가장 높은 분기는")  # 코드가 계산 결과에서 뽑은 관찰
    assert blocks[2] == "분기마다 값이 달라지는 흐름입니다."  # 모델의 해석(설정으로 켠 경우)
    assert blocks[-1].startswith("※ 기준:")  # 코드가 붙인 기준


def test_numbers_in_list_come_from_calc_not_model(monkeypatch):
    seen = {}

    def llm(m):
        seen["facts"] = facts_of(m)
        return "홍대 값은 987654321원입니다."  # 지어낸 숫자

    fake_llms(monkeypatch, SINGLE, llm)
    text = _ask()
    assert "987654321" not in text  # 해석은 거부되고
    assert "억 원" in text.split("\n\n")[0]  # 목록은 계산 결과 그대로
    assert "계산 결과:" not in text  # 예전처럼 줄줄이 나열하지 않는다
    assert "억 원" in seen["facts"] and not re.search(r"\d{1,3}(,\d{3}){3,}(?!\d)", seen["facts"])


def test_judgment_words_in_interpretation_are_rejected(monkeypatch):
    fake_llms(monkeypatch, SINGLE, lambda m: "홍대가 가장 높고 창업을 추천합니다.")
    text = _ask()
    assert "추천" not in text and "창업" not in text  # 모델의 문장은 거부된다 (코드가 만든 관찰은 별개)
    assert text.split("\n\n")[0].count("• ") >= 1  # 목록은 그대로


def test_false_negation_is_rejected(monkeypatch):
    fake_llms(monkeypatch, SINGLE, lambda m: "홍대에서 잘나가는 업종은 없습니다.")
    text = _ask()
    assert "없습니다" not in text and text.startswith("홍대")


def test_model_interpretation_with_copied_number_is_kept(monkeypatch):
    def llm(m):
        line = [l for l in facts_of(m).splitlines() if l.startswith("•")][0]
        value = re.search(r"([\d,\.]+억 원)", line).group(1)
        return f"첫 분기 값은 {value}입니다."

    fake_llms(monkeypatch, SINGLE, llm)
    text = _ask()
    assert "첫 분기 값은" in text  # 숫자를 그대로 복사하면 통과


def test_engine_notes_are_appended_to_text(monkeypatch):
    notes = {
        "성수": ["region_dong_count: 4", "industry_group: 카페=커피-음료",
                "pre_2024_basis_unconfirmed: 2021~2023년 자료의 재산출 여부는 확인 중입니다"],
        "홍대": ["region_dong_count: 1", "industry_group: 카페=커피-음료",
                "pre_2024_basis_unconfirmed: 2021~2023년 자료의 재산출 여부는 확인 중입니다"],
    }
    app.dependency_overrides[calc_route._calculator] = lambda: _engine_with_notes(notes)
    fake_llms(monkeypatch, PLAN_OK, lambda m: "비교 결과입니다.")
    text = _ask("성수와 홍대의 카페 매출을 비교해줘.")
    assert "비교 결과입니다." in text
    assert "※ 주의: 2021~2023년 자료의 재산출 여부는 확인 중입니다" in text
    assert text.count("※ 주의") == 1  # 행마다 중복되지 않음
    assert "※ 성수: 행정동 4개 묶음이라" in text  # C의 지역 주의 문구가 행정동 수를 대신 설명한다
    assert "지역별 포함 행정동 수" not in text  # 같은 말을 두 번 하지 않는다
    assert "※ 업종 묶음: 카페=커피-음료" in text


def test_caveats_added_even_when_interpretation_is_rejected(monkeypatch):
    notes = {"성수": ["region_dong_count: 4"], "홍대": ["region_dong_count: 1"]}
    app.dependency_overrides[calc_route._calculator] = lambda: _engine_with_notes(notes)
    fake_llms(monkeypatch, PLAN_OK, lambda m: "홍대가 가장 높습니다 99999")
    text = _ask("성수와 홍대의 카페 매출을 비교해줘.")
    assert "99999" not in text and "※ 성수: 행정동 4개 묶음이라" in text
    assert text.split("\n\n")[0].count("• ") == 2  # 두 지역이 목록으로


def test_single_value_lookup_does_not_call_the_model_for_interpretation(monkeypatch):
    calls = []

    async def fake(message, **kw):
        if kw.get("format") is not None:
            return "m", json.dumps({"status": "ok", "intent": "other"})
        calls.append(1)
        return "m", "쓰이지 않음"

    monkeypatch.setattr(planner.ollama, "chat", fake)
    monkeypatch.setattr(explain.ollama, "chat", fake)
    text = _ask("강남 매출 알려줘")
    assert not calls and text.startswith("강남의 ") and "추정매출 합계는" in text.split("\n")[0]


# ---------------------------------------------------------------- 이어 묻기: 대시보드가 history 를 보낸다
def test_dashboard_follow_up_uses_history(monkeypatch):
    fake_llms(monkeypatch, {"status": "ok", "intent": "other"}, lambda m: "")
    r = client.post(URL, json={"question": "그럼 홍대는?", "history": ["성수 카페 매출 알려줘"]})
    assert r.status_code == 200
    text = r.json()["text"]
    assert "이전 질문의" in text and "이어서 적용" in text and "홍대" in text


def test_dashboard_without_history_is_unchanged(monkeypatch):
    fake_llms(monkeypatch, {"status": "ok", "intent": "other"}, lambda m: "")
    r = client.post(URL, json={"question": "그럼 홍대는?"})
    assert r.status_code == 200 and "이전 질문의" not in r.json()["text"]


@pytest.mark.parametrize("bad", ["문자열", 5, {"a": 1}, [1, None, "  "], ["a"] * 10])
def test_dashboard_ignores_malformed_history(monkeypatch, bad):
    fake_llms(monkeypatch, {"status": "ok", "intent": "other"}, lambda m: "")
    r = client.post(URL, json={"question": "성수 카페 매출 알려줘", "history": bad})
    assert r.status_code == 200


# ---------------------------------------------------------------- 창업 질문: 순위 맥락 + 이어서 물어보기
def test_dashboard_startup_answer_adds_followups_and_survives_rank_failure(monkeypatch):
    fake_llms(monkeypatch, {"status": "ok", "intent": "other"}, lambda m: "")
    r = client.post(URL, json={"question": "성수에서 카페 차리면 괜찮을까?"})
    assert r.status_code == 200
    text = r.json()["text"]
    assert text.startswith("[테스트용 Mock") and "성수 카페는 점포" in text
    assert "→ 이어서 물어보기:" in text and "추천이 아닙니다" in text


def test_dashboard_answer_unchanged_when_rank_call_fails(monkeypatch):
    fake_llms(monkeypatch, {"status": "ok", "intent": "other"}, lambda m: "")
    from app.api.routes import dashboard as dash

    real = dash.run_calc
    calls = {"n": 0}

    async def flaky(plan, calc):
        calls["n"] += 1
        if calls["n"] == 2:  # 두 번째(순위 계산)만 실패
            raise RuntimeError("engine down")
        return await real(plan, calc)

    monkeypatch.setattr(dash, "run_calc", flaky)
    r = client.post(URL, json={"question": "성수에서 카페 차리면 괜찮을까?"})
    assert r.status_code == 200 and "성수 카페는 점포" in r.json()["text"] and "점포당 월평균:" not in r.json()["text"]
