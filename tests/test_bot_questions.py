"""질문 유형 확장 · 20곳 · 최근/올해 처리 · 제안형 재질문 · 점포 지표 (모델 없이 서버 규칙만 검증)."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.calc import CalcApplied, CalcMetric, CalcResult, CalcRow
from app.schemas.plan import AnalysisPlan, PlanDraft
from app.services import explain, latest, planner
from app.services.areas import find_areas, load_areas
from app.services.calc import build_request
from app.services.dataset import AREA_IDS, REGIONS, area_ids, default_dataset
from app.services.periods import parse_quarter, relative_period

client = TestClient(app)
DS = default_dataset()
LATEST = (2026, 2)
NULL = PlanDraft(status="ok", intent="other")  # 모델이 아무것도 못 알아들은 경우


def ev(q, draft=None):
    return planner.evaluate(q, draft or NULL, DS, LATEST)


def plan_of(q, draft=None):
    r = ev(q, draft)
    assert r.status == "ok", (q, r.reason, r.clarification_question)
    return r.plan


# ---------------------------------------------------------------- 20곳
WANTED = ["제기동", "노량진2동", "가산동", "한강로동", "종로1~4가", "가락1동", "노량진1동", "여의동", "압구정동",
          "청담동", "신사동", "영등포동", "독산1동", "논현1동", "명동", "성수", "홍대", "건대", "강남", "이태원"]


def test_twenty_areas_match_area_map():
    assert sorted(REGIONS) == sorted(WANTED) and len(REGIONS) == 20
    assert AREA_IDS["건대"] == "kondae" and AREA_IDS["성수"] == "seongsu" and AREA_IDS["명동"] == "myeong"
    assert area_ids(["성수", "홍대"]) == "seongsu,hongdae"
    assert set(load_areas()) == set(WANTED)


@pytest.mark.parametrize("name", WANTED)
def test_every_area_is_answerable_by_name(name):
    p = plan_of(f"{name} 매출 알려줘")
    assert p.intent == "lookup" and p.regions == [name]


@pytest.mark.parametrize("alias,name", [
    ("여의도", "여의동"), ("압구정", "압구정동"), ("청담", "청담동"), ("종로", "종로1~4가"), ("영등포", "영등포동"),
    ("논현", "논현1동"), ("독산", "독산1동"), ("가락동", "가락1동"), ("한강로", "한강로동"), ("홍대입구", "홍대"),
    ("건대입구", "건대"), ("역삼", "강남"),
])
def test_aliases(alias, name):
    assert find_areas(f"{alias} 매출").found == [name]


def test_ambiguous_dong_asks_which_one():
    assert find_areas("노량진 매출").ambiguous == [["노량진1동", "노량진2동"]]
    r = ev("노량진 매출 알려줘")
    assert r.status == "needs_clarification" and r.missing_conditions == ["region"]
    assert r.suggested_questions == ["노량진1동 매출 알려줘", "노량진2동 매출 알려줘"]
    assert plan_of("노량진2동 매출 알려줘").regions == ["노량진2동"]


def test_gu_name_does_not_double_match():
    assert find_areas("강남구 청담동 매출").found == ["청담동"]
    assert find_areas("강남구 매출").found == ["강남"]


# ---------------------------------------------------------------- 질문 유형
def test_lookup_defaults_and_assumptions():
    p = plan_of("강남 매출 알려줘")
    assert p.intent == "lookup" and p.group_by == [] and p.metrics[0].column == "est_sales"
    assert p.period.model_dump() == {"start": "2025-07", "end": "2026-06"}
    assert "업종: 전체 업종 합계" in p.assumptions
    assert any("최근 4분기(2025Q3~2026Q2)" in a for a in p.assumptions)


def test_lookup_with_industry_and_explicit_quarter():
    p = plan_of("2025년 4분기 이태원 음식점 매출은 얼마야?")
    assert p.industries == ["음식점"] and p.period.model_dump() == {"start": "2025-10", "end": "2025-12"}
    assert not any(a.startswith("업종") for a in p.assumptions)


def test_trend_defaults_to_all_quarters_and_single_area_group():
    p = plan_of("홍대 음식점 분기별 매출 추이")
    assert p.intent == "sales_trend" and p.group_by == ["quarter"] and p.period is None
    assert plan_of("성수와 홍대의 분기별 매출 추이").group_by == ["quarter", "region"]


def test_ranking_covers_all_areas_and_growth():
    p = plan_of("최근 1년 가장 많이 성장한 상권은?")
    assert p.intent == "ranking" and p.regions == [] and p.group_by == ["region"]
    assert p.metrics[0].op == "growth_rate" and p.rank_order == "desc"
    assert p.assumptions[0] == "지역: 20곳 전체"
    assert plan_of("매출이 가장 낮은 상권은?").rank_order == "asc"


def test_ranking_with_industry_filter():
    p = plan_of("카페 매출이 가장 높은 상권은?")
    assert p.intent == "ranking" and p.industries == ["카페"]


def test_region_comparison_and_need_more():
    assert plan_of("성수와 홍대의 카페 매출을 비교해줘").intent == "region_comparison"
    r = ev("성수의 카페 매출 비교")
    assert r.status == "needs_clarification" and r.missing_conditions == ["region"]
    assert r.suggested_questions and all("성수" in s for s in r.suggested_questions[:1])


def test_no_area_lists_supported_areas():
    r = ev("잠실 매출 알려줘")
    assert r.status == "needs_clarification" and "지원하는 지역" in r.reason and "명동" in r.reason
    assert r.suggested_questions


# ---------------------------------------------------------------- 기간
@pytest.mark.parametrize("q,start,end", [
    ("최근 1년", "2025-07", "2026-06"),
    ("최근 2년", "2024-07", "2026-06"),
    ("최근 3분기", "2025-10", "2026-06"),
    ("최근 분기", "2026-04", "2026-06"),
    ("올해", "2026-01", "2026-06"),
    ("작년", "2025-01", "2025-12"),
    ("지난해", "2025-01", "2025-12"),
    ("최근", "2025-07", "2026-06"),
])
def test_relative_periods(q, start, end):
    p, desc = relative_period(f"성수 매출 {q}", LATEST)
    assert (p.start, p.end) == (start, end) and desc


def test_relative_period_reaches_plan_with_assumption():
    p = plan_of("성수 올해 매출 알려줘")
    assert p.period.model_dump() == {"start": "2026-01", "end": "2026-06"}
    assert any(a.startswith("기간: 올해") for a in p.assumptions)


def test_non_quarter_month_period_suggests_quarter():
    r = ev("2025년 2월 성수 매출 알려줘")
    assert r.status == "needs_clarification" and r.missing_conditions == ["period"]
    assert r.suggested_questions[0] == "2025년 1분기 성수 매출 알려줘"


def test_growth_trend_gets_period():
    p = plan_of("성수 분기별 매출 증가 추이")
    assert p.metrics[0].op == "growth_rate" and p.period is not None


# ---------------------------------------------------------------- 점포 지표
def test_store_metrics_ops():
    assert plan_of("성수 점포 수 알려줘").metrics[0].model_dump() == {"column": "store_count", "op": "avg"}
    assert plan_of("강남 개업 점포 수").metrics[0].model_dump() == {"column": "open_count", "op": "sum"}
    assert plan_of("강남 폐업 점포 수").metrics[0].column == "close_count"
    assert plan_of("강남 프랜차이즈 점포 수").metrics[0].column == "franchise_count"
    assert "점포 수: 기간 내 분기 평균" in plan_of("성수 점포 수 알려줘").assumptions


def test_per_store_metric():
    m = plan_of("이태원 점포당 월평균 매출은?").metrics[0]
    assert m.model_dump() == {"column": "est_sales", "op": "per_store"}
    assert plan_of("점포당 매출이 가장 높은 곳은?").metrics[0].op == "per_store"


def test_model_sum_on_store_count_becomes_avg():
    d = PlanDraft(status="ok", intent="lookup", regions=["성수"], metrics=[{"column": "store_count", "op": "sum"}])
    assert plan_of("성수 알려줘", d).metrics[0].op == "avg"


def test_per_store_only_on_sales_columns():
    d = PlanDraft(status="ok", intent="lookup", regions=["성수"], metrics=[{"column": "store_count", "op": "per_store"}])
    with pytest.raises(planner.PlanValidationError):
        ev("성수 알려줘", d)


# ---------------------------------------------------------------- 막힐 때: 이유 + 서버가 검증한 제안
BLOCKED = [
    "성수에서 카페 차리면 괜찮을까?", "건대와 이태원 중 창업하기 좋은 곳은?", "홍대 음식점 월별 매출 보여줘",
    "주말 매출 비중이 높은 상권은?", "잠실 매출 알려줘", "노량진 매출 알려줘", "성수의 카페 매출 비교",
    "2025년 2월 성수 매출", "분석 좀 해줘", "서점 매출 알려줘",
]


@pytest.mark.parametrize("q", BLOCKED)
def test_blocked_questions_get_reason_and_runnable_suggestions(q):
    r = ev(q)
    assert r.status == "needs_clarification" and r.plan is None
    assert r.suggested_questions, q
    assert "이렇게 물어보세요" in r.clarification_question
    for s in r.suggested_questions:  # 제안한 질문은 모델 없이도 반드시 통과
        assert ev(s).status == "ok", (q, s)


def test_judgment_suggestions_keep_user_context():
    r = ev("성수에서 카페 차리면 괜찮을까?")
    assert "지원하지 않습니다" in r.reason
    assert any("성수" in s and "카페" in s for s in r.suggested_questions)


def test_ratio_suggests_closest_measure():
    r = ev("주말 매출 비중이 높은 상권은?")
    assert "주말 매출이 가장 높은 상권은?" in r.suggested_questions


def test_suggestions_do_not_recurse():
    r = planner.evaluate("성수에서 카페 차리면 괜찮을까?", NULL, DS, LATEST, suggest=False)
    assert r.suggested_questions == []


# ---------------------------------------------------------------- 최신 분기
def _patch_health(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(latest.httpx, "AsyncClient", factory)


@pytest.mark.anyio
async def test_latest_quarter_reads_engine_health(monkeypatch):
    monkeypatch.setenv("CALC_MODE", "http")
    from app.core.config import get_settings
    get_settings.cache_clear()
    _patch_health(monkeypatch, lambda r: httpx.Response(200, json={"quarters": ["20211", "20263"]}))
    assert await latest.latest_quarter() == (2026, 3)


@pytest.mark.anyio
async def test_latest_quarter_falls_back_to_setting(monkeypatch):
    monkeypatch.setenv("CALC_MODE", "http")
    from app.core.config import get_settings
    get_settings.cache_clear()

    def boom(r):
        raise httpx.ConnectError("down")

    _patch_health(monkeypatch, boom)
    assert await latest.latest_quarter() == (2026, 2)
    assert parse_quarter("2026-Q4") == (2026, 4) and parse_quarter("20262") == (2026, 2)


# ---------------------------------------------------------------- 설명: 정렬 · 가정 · 지역 주의 · 표시
def _result(rows, op="sum", column="est_sales", notes=None):
    return CalcResult(
        request_id="r", status="ok", dataset_id="d", data_version="v", data_source="s", rows_used=99,
        applied=CalcApplied(columns_used=[column, "region"], operations=[CalcMetric(column=column, op=op)],
                            group_by=["region"], filters=[]),
        results=[CalcRow(group={"region": n}, values={f"{column}.{op}": v}, rows_used=1, notes=list(notes or []))
                 for n, v in rows],
    )


def _plan(**kw):
    base = dict(intent="ranking", regions=[], industries=[], metrics=[{"column": "est_sales", "op": "sum"}],
                group_by=["region"], comparison="region", filters=[], period=None, time_column="quarter")
    base.update(kw)
    return AnalysisPlan.model_validate(base)


def test_ranking_rows_sorted_by_value():
    res = _result([("성수", 3e10), ("홍대", 9e10), ("강남", 5e10)])
    rows = explain._ordered(_plan(rank_order="desc"), res)
    assert [r.group["region"] for r in rows] == ["홍대", "강남", "성수"]
    rows = explain._ordered(_plan(rank_order="asc"), res)
    assert [r.group["region"] for r in rows] == ["성수", "강남", "홍대"]
    facts = explain.build_facts(_plan(rank_order="desc"), res)
    assert facts[-3].startswith("[홍대]") and "값이 큰 순서" in "\n".join(facts)


def test_ranking_allows_sort_words_but_not_recommendation():
    assert explain.judgment_words("홍대가 가장 높습니다", allow_ranking=True) == []
    assert explain.judgment_words("홍대가 가장 높습니다") == ["가장"]
    assert explain.judgment_words("홍대를 추천합니다", allow_ranking=True) == ["추천"]


def test_caveats_include_assumptions_and_wholesale_warning():
    res = _result([("제기동", 1e10), ("노량진2동", 2e10), ("성수", 3e10)])
    plan = _plan(assumptions=["업종: 전체 업종 합계", "기간: 최근 4분기(2025Q3~2026Q2)"])
    lines = explain.build_caveats(res, plan)
    assert lines[0] == "※ 기준: 업종: 전체 업종 합계 · 기간: 최근 4분기(2025Q3~2026Q2)"
    joined = "\n".join(lines)
    assert "시장·도매형 상권(제기동, 노량진2동)" in joined
    assert "※ 성수:" in joined  # 성수는 행정동 4개 묶음 안내


def test_display_formats_for_store_metrics():
    f = explain._fmt_value
    assert f("per_store", 13_941_345.0, [], "est_sales") == "1,394만 원"
    assert f("avg", 8820.4, [], "store_count") == "8,820개"
    assert f("sum", 223.0, [], "open_count") == "223개"
    assert explain.OP_LABEL["avg"] == "분기당 평균"


# ---------------------------------------------------------------- 요청/응답 연결
def test_per_store_request_goes_to_engine():
    req = build_request(plan_of("이태원 점포당 월평균 매출은?"), "ds", "rid")
    assert req.metrics[0].op == "per_store" and req.growth is None
    assert any(f.column == "region" and f.value == "이태원" for f in req.filters)


def test_ranking_request_has_no_region_filter():
    req = build_request(plan_of("가장 많이 성장한 상권은?"), "ds", "rid")
    assert req.group_by == ["region"] and not any(f.column == "region" for f in req.filters)
    assert req.growth is not None and req.growth.baseline_period.start == "2024-07"


def _fake_llm(monkeypatch, payload):
    async def fake(message, **kw):
        return "m", json.dumps(payload)

    monkeypatch.setattr(planner.ollama, "chat", fake)


def test_api_plan_returns_suggested_questions(monkeypatch):
    _fake_llm(monkeypatch, {"status": "ok", "intent": "other"})
    b = client.post("/api/plan", json={"question": "성수에서 카페 차리면 괜찮을까?"}).json()
    assert b["status"] == "needs_clarification" and len(b["suggested_questions"]) >= 1


def test_dashboard_422_carries_suggestions(monkeypatch):
    _fake_llm(monkeypatch, {"status": "ok", "intent": "other"})
    r = client.post("/api/dashboard/analyze", json={"question": "성수에서 카페 차리면 괜찮을까?"})
    d = r.json()["detail"]
    assert r.status_code == 422 and d["error"] == "needs_clarification" and d["suggested_questions"]


def test_dashboard_answers_lookup_end_to_end(monkeypatch):
    async def fake(message, **kw):
        if kw.get("format") is not None:
            return "m", json.dumps({"status": "ok", "intent": "other"})
        return "m", "명동 설명입니다."

    monkeypatch.setattr(planner.ollama, "chat", fake)
    monkeypatch.setattr(explain.ollama, "chat", fake)
    r = client.post("/api/dashboard/analyze", json={"question": "명동 매출 알려줘"})
    b = r.json()
    assert r.status_code == 200 and b["area"] == "myeong" and b["sql"] == ""
    assert "※ 기준:" in b["text"] and "업종: 전체 업종 합계" in b["text"]


def test_dashboard_ranking_has_empty_area(monkeypatch):
    async def fake(message, **kw):
        if kw.get("format") is not None:
            return "m", json.dumps({"status": "ok", "intent": "other"})
        return "m", "설명입니다."

    monkeypatch.setattr(planner.ollama, "chat", fake)
    monkeypatch.setattr(explain.ollama, "chat", fake)
    b = client.post("/api/dashboard/analyze", json={"question": "가장 많이 성장한 상권은?"}).json()
    assert b["area"] == ""
    assert "지역: 20곳 전체" in b["text"] and "시장·도매형 상권" in b["text"]


# ---------------------------------------------------------------- 모델이 지어낸 '없는 항목'은 무시
def test_made_up_missing_column_is_ignored():
    d = PlanDraft(status="needs_clarification", intent="ranking", missing_fields=["유동인구", "임대료"])
    p = plan_of("최근 1년 가장 많이 성장한 상권은?", d)  # 질문에 없는 말이므로 막지 않는다
    assert p.intent == "ranking" and p.metrics[0].op == "growth_rate"


def test_missing_column_named_in_question_is_kept():
    d = PlanDraft(status="needs_clarification", intent="region_comparison", missing_fields=["유동인구"])
    r = ev("성수와 홍대의 유동인구 비교해줘", d)
    assert r.status == "needs_clarification" and r.missing_columns == ["유동인구"]


# ---------------------------------------------------------------- 모델이 멈추거나 늦을 때
from app.services import ollama as ollama_mod  # noqa: E402


def test_planner_falls_back_to_rules_when_model_times_out(monkeypatch):
    seen = []

    async def slow(message, **kw):
        seen.append(kw)
        raise ollama_mod.OllamaRunawayError("출력이 끝나지 않음")

    monkeypatch.setattr(planner.ollama, "chat", slow)
    b = client.post("/api/plan", json={"question": "카페 매출이 가장 낮은 상권은?"}).json()
    assert b["status"] == "ok" and b["plan"]["intent"] == "ranking" and b["plan"]["rank_order"] == "asc"
    assert b["plan"]["industries"] == ["카페"]
    assert len(seen) == 1  # 시간 초과는 재시도하지 않는다
    assert seen[0]["timeout"] == 30 and seen[0]["max_tokens"] == 400  # 계획 호출에는 상한이 걸린다


def test_planner_timeout_without_rules_match_still_asks(monkeypatch):
    async def slow(message, **kw):
        raise ollama_mod.OllamaTimeoutError("시간 초과")

    monkeypatch.setattr(planner.ollama, "chat", slow)
    b = client.post("/api/plan", json={"question": "분석 좀 해줘"}).json()
    assert b["status"] == "needs_clarification" and b["suggested_questions"]


def test_malformed_model_output_is_still_a_clear_error(monkeypatch):
    async def bad(message, **kw):
        return "m", "not json"

    monkeypatch.setattr(planner.ollama, "chat", bad)
    assert client.post("/api/plan", json={"question": "성수 매출"}).status_code == 502


def test_explanation_timeout_falls_back_to_template(monkeypatch):
    async def fake(message, **kw):
        if kw.get("format") is not None:
            return "m", json.dumps({"status": "ok", "intent": "other"})
        raise ollama_mod.OllamaTimeoutError("느림")

    monkeypatch.setattr(planner.ollama, "chat", fake)
    monkeypatch.setattr(explain.ollama, "chat", fake)
    r = client.post("/api/dashboard/analyze", json={"question": "강남 매출 알려줘"})
    assert r.status_code == 200 and "계산 결과:" in r.json()["text"]  # 오류 대신 결정적 문장


def test_ollama_chat_sends_limits_and_detects_runaway():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": "{"}, "done_reason": "length"})

    import asyncio
    c = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://t")
    with pytest.raises(ollama_mod.OllamaRunawayError):
        asyncio.run(ollama_mod.chat("q", max_tokens=123, client=c))
    assert seen["body"]["options"]["num_predict"] == 123


def test_dong_count_line_is_compact_for_many_regions():
    rows = [(f"지역{i}", 1e10) for i in range(6)]
    res = _result(rows)
    for i, r in enumerate(res.results):
        r.notes = ["region_dong_count: 4" if i == 0 else "region_dong_count: 1"]
    line = [x for x in explain.build_caveats(res) if "행정동 수" in x][0]
    assert "지역0 4개 (나머지는 1개)" in line and "지역3" not in line
