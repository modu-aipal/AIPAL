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
    "성수 카페 성공 확률은?", "가장 안전한 투자처는?", "홍대 음식점 월별 매출 보여줘",
    "카페 점포 비중이 높은 상권은?", "잠실 매출 알려줘", "노량진 매출 알려줘", "성수의 카페 매출 비교",
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
    r = ev("성수 카페 성공 확률은?")
    assert "지원하지 않습니다" in r.reason
    assert any("성수" in s and "카페" in s for s in r.suggested_questions)


def test_unsupported_ratio_suggests_plain_questions():
    r = ev("카페 점포 비중이 높은 상권은?")
    assert r.status == "needs_clarification" and r.suggested_questions


def okplan(q):
    r = ev(q)
    assert r.status == "ok", (q, r.clarification_question)
    return r.plan


def test_weekend_ratio_ranking():
    p = okplan("주말 매출 비중이 높은 상권은?")
    assert p.intent == "ranking" and p.metrics[0].column == "weekend_sales" and p.metrics[0].op == "ratio"
    assert p.sort_by == "weekend_sales.ratio"


def test_distribution_for_one_area():
    p = okplan("한강로는 언제 매출이 몰려?")
    assert p.intent == "lookup" and len(p.metrics) == 6 and all(m.op == "ratio" for m in p.metrics)


def test_closure_rate_uses_store_ratio():
    p = okplan("폐업률 높은 곳은?")
    assert p.metrics[0].column == "close_count" and p.metrics[0].op == "ratio"


def test_location_question_is_ranking_with_disclaimer():
    p = okplan("의류의 경우 어디서 장사하는게 좋아?")
    assert p.intent == "ranking" and p.industries == ["의류"] and p.sort_by == "est_sales.per_store"
    assert p.disclaimers and "추천이 아닙니다" in p.disclaimers[0]


def test_location_question_needs_industry():
    r = ev("어디서 장사하는게 좋아?")
    assert r.status == "needs_clarification" and r.suggested_questions


def test_competition_question():
    p = okplan("카페 경쟁이 심한 곳은?")
    assert p.sort_by == "store_count.avg" and p.disclaimers


def test_data_questions_get_info_answer():
    r = ev("추정매출이 뭐야?")
    assert r.status == "info" and "보정비율" in r.info_text
    assert ev("출처가 어디야?").status == "info"
    assert ev("성수 점포 수 알려줘").status == "ok"


def test_unavailable_terms_still_blocked():
    assert ev("성수 임대료 알려줘").status == "needs_clarification"


def test_suggestions_do_not_recurse():
    r = planner.evaluate("성수 카페 성공 확률은?", NULL, DS, LATEST, suggest=False)
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
    b = client.post("/api/plan", json={"question": "성수 카페 성공 확률은?"}).json()
    assert b["status"] == "needs_clarification" and len(b["suggested_questions"]) >= 1


def test_dashboard_422_carries_suggestions(monkeypatch):
    _fake_llm(monkeypatch, {"status": "ok", "intent": "other"})
    r = client.post("/api/dashboard/analyze", json={"question": "성수 카페 성공 확률은?"})
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


# ---------------------------------------------------------------- 정렬·상위 N (코드가 순위를 정한다)
def test_ranking_rows_sorted_by_value_and_cut_to_top_n():
    from app.services.ranking import rank

    rows = [(f"업종{i}", float(v) * 1e10) for i, v in enumerate([3, 9, 5, 1, 7, 8, 2], 1)]
    res = _result(rows)
    view = rank(_plan(intent="ranking", sort_by="est_sales.sum", rank_order="desc", top_n=3), res)
    assert [r.group["region"] for r in view.rows] == ["업종2", "업종6", "업종5"] and view.total == 7 and view.ranked
    low = rank(_plan(intent="ranking", sort_by="est_sales.sum", rank_order="asc", top_n=2), res)
    assert [r.group["region"] for r in low.rows] == ["업종4", "업종7"]


def test_growth_ranking_excludes_tiny_sales_and_missing_values():
    from app.schemas.calc import CalcApplied, CalcMetric, CalcResult, CalcRow
    from app.services.ranking import rank

    def row(name, sales, growth):
        return CalcRow(group={"industry": name}, values={"est_sales.sum": sales, "est_sales.growth_rate": growth},
                       rows_used=1)

    res = CalcResult(
        request_id="r", status="ok", dataset_id="d", data_version="v", data_source="s", rows_used=9,
        applied=CalcApplied(columns_used=["est_sales"], operations=[CalcMetric(column="est_sales", op="growth_rate"),
                                                                    CalcMetric(column="est_sales", op="sum")],
                            group_by=["industry"], filters=[]),
        results=[row("큰업종A", 5e10, 0.10), row("큰업종B", 3e10, 0.30), row("아주작음", 2e6, 8.0),
                 row("값없음", 4e10, None)],
    )
    plan = _plan(intent="industry_comparison", sort_by="est_sales.growth_rate", rank_order="desc", top_n=5,
                 metrics=[{"column": "est_sales", "op": "growth_rate"}, {"column": "est_sales", "op": "sum"}],
                 group_by=["industry"])
    view = rank(plan, res)
    assert [r.group["industry"] for r in view.rows] == ["큰업종B", "큰업종A"]  # 800%인 아주작음은 제외
    assert any("1억 원 이상" in n for n in view.notes) and any("계산할 수 없는" in n for n in view.notes)


def test_trio_for_overall_idiom_and_headline_lines():
    import asyncio

    from app.services.calc.mock import MockCalculator
    from app.services.compose import compose_block
    from app.services.ranking import rank

    p = plan_of("가산동에서 잘나가는 업종")
    assert [f"{m.column}.{m.op}" for m in p.metrics] == ["est_sales.sum", "est_sales.growth_rate", "est_sales.per_store"]
    assert p.sort_by == "est_sales.sum" and p.top_n == 5 and p.rank_order == "desc" and p.concept == "overall"
    res = asyncio.run(MockCalculator().calculate(build_request(p, "ds", "rid")))
    view = rank(p, res)
    head, lines = compose_block(p, res, view)
    assert "가산동의 업종 중 매출 규모 상위 5개 업종입니다" in head and "전체 7개 중" in head
    assert len(lines) == 5 and [l.split(".")[0] for l in lines] == ["1", "2", "3", "4", "5"]
    assert all("매출 " in l and "점포당 월 " in l for l in lines)


# ---------------------------------------------------------------- 의미 해석: 개념 · 방향 · 개수
def test_growth_idiom_sorts_by_growth():
    p = plan_of("강남 요즘 뜨는 업종")
    assert p.sort_by == "est_sales.growth_rate" and p.metrics[0].op == "growth_rate" and p.top_n == 5


def test_low_direction_idiom_sorts_ascending():
    assert plan_of("독산 요즘 장사 안 되는 업종").rank_order == "asc"
    assert plan_of("매출 하위 3곳").rank_order == "asc"


def test_top_n_is_parsed():
    assert plan_of("장사 잘되는 곳 TOP 3").top_n == 3
    assert plan_of("홍대에서 매출 제일 큰 업종 3개").top_n == 3
    assert plan_of("압구정 업종 순위 알려줘").top_n == 5  # 말하지 않으면 5개


def test_model_understands_idiom_the_code_does_not_know():
    d = PlanDraft(status="ok", intent="industry_comparison", concept="growth")
    p = plan_of("떡상한 업종 알려줘", d)
    assert p.sort_by == "est_sales.growth_rate" and p.concept == "growth"
    assert plan_of("떡상한 업종 알려줘").concept is None  # 모델이 없으면 규모 순(기본)


def test_model_can_say_closures_and_openings():
    p = plan_of("문 닫는 가게가 많은 동네", PlanDraft(status="ok", intent="other", concept="closures"))
    assert p.intent == "ranking" and p.sort_by == "close_count.ratio" and p.rank_order == "desc"
    p = plan_of("새로 문 연 가게가 많은 곳", PlanDraft(status="ok", intent="other", concept="openings"))
    assert p.sort_by == "open_count.sum"


def test_clear_words_beat_a_wrong_model_direction():
    d = PlanDraft(status="ok", intent="ranking", direction="low")
    assert plan_of("폐업이 많은 동네는?", d).rank_order == "desc"


def test_concept_priority_setting(monkeypatch):
    from app.core.config import get_settings

    d = PlanDraft(status="ok", intent="ranking", concept="size")
    assert plan_of("요즘 뜨는 상권은?", d).sort_by == "est_sales.sum"  # model_first: 모델 의견
    monkeypatch.setenv("CONCEPT_PRIORITY", "rules_first")
    get_settings.cache_clear()
    assert plan_of("요즘 뜨는 상권은?", d).sort_by == "est_sales.growth_rate"  # 알려진 표현 우선


def test_explicit_growth_word_beats_model_concept():
    d = PlanDraft(status="ok", intent="ranking", concept="size")
    assert plan_of("최근 1년 가장 많이 성장한 상권", d).sort_by == "est_sales.growth_rate"


def test_unavailable_terms_are_reported_without_the_model():
    r = ev("성수 월세 알려줘")
    assert r.status == "needs_clarification" and r.missing_columns == ["월세"] and r.suggested_questions


def test_false_negation_words():
    assert explain.false_negations("잘나가는 업종은 없습니다", True) == ["없습니다"]
    assert explain.false_negations("잘나가는 업종은 없습니다", False) == []


def test_idiom_question_answer_blocks_and_wrong_negation_rejected(monkeypatch):
    async def fake(message, **kw):
        if kw.get("format") is not None:
            return "m", json.dumps({"status": "ok", "intent": "other"})
        return "m", "가산동에서 잘나가는 업종은 없습니다."  # 틀린 부정: 거부되어야 함

    monkeypatch.setattr(planner.ollama, "chat", fake)
    monkeypatch.setattr(explain.ollama, "chat", fake)
    r = client.post("/api/dashboard/analyze", json={"question": "가산동에서 잘나가는 업종"})
    text = r.json()["text"]
    assert r.status_code == 200 and "없습니다" not in text
    head, *rest = text.split("\n\n")[0].split("\n")
    assert "상위 5개 업종" in head and len(rest) == 5
    assert "※ 기준:" in text


def test_explanation_timeout_keeps_structure(monkeypatch):
    async def fake(message, **kw):
        if kw.get("format") is not None:
            return "m", json.dumps({"status": "ok", "intent": "other"})
        raise ollama_mod.OllamaTimeoutError("느림")

    monkeypatch.setattr(planner.ollama, "chat", fake)
    monkeypatch.setattr(explain.ollama, "chat", fake)
    r = client.post("/api/dashboard/analyze", json={"question": "성수와 홍대의 카페 매출을 비교해줘"})
    text = r.json()["text"]
    assert r.status_code == 200 and text.split("\n\n")[0].count("• ") == 2  # 해석만 빠지고 결론·목록은 나간다
    assert "※ 기준:" in text


@pytest.mark.parametrize("q", ["성수 카페 점포당 매출 알려줘", "성수 카페 한 곳당 매출은?", "성수 카페 가게당 매출 알려줘"])
def test_per_store_wording_with_industry(q):
    p = okplan(q)
    assert [(m.column, m.op) for m in p.metrics] == [("est_sales", "per_store"), ("store_count", "avg")]
    assert p.industries == ["카페"] and p.regions == ["성수"]


# ---------------------------------------------------------------- 창업 가부 질문은 현황 데이터로 답한다
def test_startup_question_answers_with_store_count_and_per_store():
    p = okplan("성수에서 카페 차리면 괜찮을까?")
    assert p.intent == "lookup" and p.regions == ["성수"] and p.industries == ["카페"]
    assert [(m.column, m.op) for m in p.metrics] == [
        ("store_count", "avg"), ("est_sales", "per_store"), ("est_sales", "sum"), ("est_sales", "growth_rate")]
    assert p.disclaimers and "추천이 아닙니다" in p.disclaimers[0]


def test_startup_question_with_two_areas_compares():
    p = okplan("성수와 홍대 중 카페 창업하기 좋은 곳은?")
    assert p.intent == "region_comparison" and p.sort_by == "est_sales.per_store"


@pytest.mark.parametrize("q", ["성수 카페 성공 확률은?", "성수 카페 성공확률 알려줘", "가장 안전한 투자처는?", "카페 투자 수익률은?"])
def test_probability_and_investment_stay_blocked(q):
    r = ev(q)
    assert r.status == "needs_clarification" and r.plan is None and r.suggested_questions
    assert "지원하지 않습니다" in r.reason or "제공하지 않아요" in r.reason


# ---------------------------------------------------------------- 설명 문구가 계산 질문을 가로채지 않는다
HIJACK_QUESTIONS = [
    "성수 행정동별 매출 보여줘", "강남 최신 분기 매출", "이태원 갱신된 매출 알려줘", "시장 도매형 상권 매출 순위",
    "신한카드 매출 알려줘", "한강로 출처 매출", "성수 최신 분기 점포 수",
]


@pytest.mark.parametrize("q", HIJACK_QUESTIONS)
def test_data_facts_do_not_hijack_analysis_questions(q):
    r = ev(q)
    assert r.status != "info", q


@pytest.mark.parametrize("q", ["최신 분기가 언제야?", "데이터 언제까지 있어?", "데이터 출처가 어디야?", "행정동이 뭐야?",
                               "추정매출이 뭐야?", "도움말", "성수는 왜 4개 동이야?", "시장 도매형 상권이 뭐야?"])
def test_data_facts_still_answer_real_questions(q):
    assert ev(q).status == "info", q


def test_clinic_limit_notice_still_shown_with_area():
    assert ev("강남 피부과 매출 알려줘").status == "info"


def test_freshness_text_matches_what_was_verified():
    r = ev("데이터 기준일이 언제야?")
    assert "2025년 자료가 공식 2025년 파일과 숫자가 모두 같은" in r.info_text
    assert "같은 기간의 공식 파일" not in r.info_text


def test_rates_text_describes_period_total():
    r = ev("폐업률이 뭐야?")
    assert "기간 전체" in r.info_text and "분기 평균" not in r.info_text


def test_real_estate_agency_industry_supported():
    p = okplan("명동 부동산중개업 2026년 2분기 매출")
    assert p.industries == ["부동산중개업"] and p.regions == ["명동"]
    assert okplan("명동 부동산 매출 알려줘").industries == ["부동산중개업"]
    # 업종 이름 속 '개업'이 개업 점포 수 지표로 잡히면 안 된다
    assert [(m.column, m.op) for m in okplan("명동 부동산중개업 매출").metrics] == [("est_sales", "sum")]
    assert any(m.column == "open_count" for m in okplan("명동 개업 점포 수").metrics)


# ---------------------------------------------------------------- 점포당 표현 사전
PER_STORE_PHRASES = [
    "점포당 매출", "점포별 매출", "가게당 매출", "가게별 매출", "매장당 매출", "매장별 매출", "업소당 매출",
    "가게 하나당 매출", "한 집당 얼마", "한 곳당 매출", "1개 점포 매출", "점포 1곳당 월매출", "점포 한 곳 매출",
    "점포 수 대비 매출", "매출 점포 수로 나눠줘", "가게 평균 매출", "점포마다 매출", "점포당 연매출",
]


@pytest.mark.parametrize("phrase", PER_STORE_PHRASES)
def test_per_store_phrases_all_recognized(phrase):
    p = okplan(f"성수 카페 {phrase}")
    assert p.metrics[0].column == "est_sales" and p.metrics[0].op == "per_store", phrase


@pytest.mark.parametrize("q", ["점포당 매출 높은 곳", "점포별 매출 TOP 5", "가게별 매출이 가장 높은 곳"])
def test_per_store_ranking_phrases_sort_by_per_store(q):
    p = okplan(q)
    assert p.intent == "ranking" and p.sort_by == "est_sales.per_store"


@pytest.mark.parametrize("q", ["점포 수 많은 곳", "성수 점포 수 알려줘", "성수 카페 매출", "별로 안 되는 가게는?", "성수 가게 수"])
def test_per_store_not_triggered_by_lookalikes(q):
    r = ev(q)
    if r.status == "ok":
        assert not any(m.op == "per_store" for m in r.plan.metrics), q


def test_per_store_lookup_adds_store_count_as_evidence():
    p = okplan("성수 카페 점포별 매출")
    assert [(m.column, m.op) for m in p.metrics] == [("est_sales", "per_store"), ("store_count", "avg")]


def test_per_store_with_store_count_question():
    p = okplan("성수 카페 점포당 매출과 점포 수")
    assert {(m.column, m.op) for m in p.metrics} == {("est_sales", "per_store"), ("store_count", "avg")}


def test_per_store_growth_adds_growth_with_note():
    p = okplan("성수 점포당 매출 증가율")
    assert {m.op for m in p.metrics} >= {"per_store", "growth_rate"}
    assert any("점포당 값의 증감이 아닙니다" in a for a in p.assumptions)


def test_per_store_annual_wording_notes_monthly_basis():
    p = okplan("성수 카페 점포당 연매출")
    assert any("월평균" in a for a in p.assumptions)


@pytest.mark.parametrize("q", ["성수 카페 평균 매출", "성수 카페 월평균 매출"])
def test_ambiguous_average_shows_per_store_and_total(q):
    p = okplan(q)
    assert [(m.column, m.op) for m in p.metrics][:2] == [("est_sales", "per_store"), ("est_sales", "sum")]
    assert any("평균 매출" in a for a in p.assumptions)


def test_avg_ticket_is_not_silently_turned_into_total():
    r = ev("성수 카페 객단가")
    assert r.status == "needs_clarification" and "객단가" in r.reason and r.suggested_questions


@pytest.mark.parametrize("concept", ["size", "overall", "none"])
def test_per_store_wording_beats_model_concept(concept):
    d = PlanDraft(status="ok", intent="ranking", concept=concept)
    r = planner.evaluate("점포별 매출 TOP 3", d, DS, LATEST)
    assert r.status == "ok" and r.plan.sort_by == "est_sales.per_store"


def test_ambiguous_average_with_quarter_in_question():
    p = okplan("2026년 2분기 성수 카페 평균 매출")
    assert [(m.column, m.op) for m in p.metrics][:2] == [("est_sales", "per_store"), ("est_sales", "sum")]
    q = okplan("성수 카페 분기 평균 매출")
    assert not any(m.op == "per_store" for m in q.metrics)


# ---------------------------------------------------------------- 판단 표현 -> 지표 연결
def keys(p):
    return [f"{m.column}.{m.op}" for m in p.metrics]


STARTUP_CASES = [
    # (질문, intent, 정렬 기준)
    ("강남에서 창업하기 좋은 업종은?", "industry_comparison", "est_sales.per_store"),
    ("성수에서 어떤 가게를 열면 좋을까?", "industry_comparison", "est_sales.per_store"),
    ("홍대에서 할 만한 업종은?", "industry_comparison", "est_sales.per_store"),
    ("카페 창업하기 좋은 곳은?", "ranking", "est_sales.per_store"),
    ("카페 차리기 좋은 동네 추천해줘", "ranking", "est_sales.per_store"),
    ("카페 하나 열면 매출 얼마 나와?", "ranking", "est_sales.per_store"),
    ("카페 하면 한 달에 얼마 벌어?", "ranking", "est_sales.per_store"),
]


@pytest.mark.parametrize("q,intent,sort", STARTUP_CASES)
def test_startup_wording_is_answered_as_data_ranking(q, intent, sort):
    p = okplan(q)
    assert p.intent == intent and p.sort_by == sort and p.disclaimers, q


@pytest.mark.parametrize("q", ["창업하기 좋은 곳은?", "가게 열기 좋은 곳 알려줘"])
def test_startup_without_any_subject_asks_for_industry(q):
    r = ev(q)
    assert r.status == "needs_clarification" and "업종" in r.reason and r.suggested_questions


SURVIVAL_CASES = [
    ("폐업 적은 업종은?", "asc"), ("살아남기 쉬운 업종은?", "asc"), ("어느 업종이 제일 안정적이야?", "asc"),
    ("폐업률 낮은 업종은?", "asc"), ("망하는 업종은?", "desc"), ("폐업이 많은 업종은?", "desc"),
]


@pytest.mark.parametrize("q,order", SURVIVAL_CASES)
def test_survival_and_danger_use_closure_rate_not_count_or_sales(q, order):
    p = okplan(q)
    assert p.intent == "industry_comparison" and p.sort_by == "close_count.ratio" and p.rank_order == order, q
    assert keys(p)[:2] == ["close_count.ratio", "store_count.avg"]  # 점포 수 하한 적용을 위해 함께 계산
    assert "est_sales.sum" in keys(p)  # 매출 없는 업종(점포 데이터에만 있음)을 순위에서 빼는 기준
    assert p.disclaimers


def test_competition_wording_ranks_by_store_count():
    p = okplan("카페 너무 많은 동네는?")
    assert p.sort_by == "store_count.avg" and p.rank_order == "desc"
    q = okplan("경쟁 적은 곳은?")
    assert q.sort_by == "store_count.avg" and q.rank_order == "asc"
    r = okplan("블루오션 업종은?")
    assert r.intent == "industry_comparison" and r.sort_by == "store_count.avg" and r.rank_order == "asc"


def test_income_wording_is_per_store_sales_with_not_profit_notice():
    p = okplan("성수 카페 사장 수입은?")
    assert keys(p) == ["est_sales.per_store", "store_count.avg"]
    assert any("순이익" in d for d in p.disclaimers)


def test_outlook_wording_is_past_trend_not_forecast():
    p = okplan("성수 카페 앞으로 전망 어때?")
    assert p.intent == "sales_trend" and any("예측이 아닙니다" in d for d in p.disclaimers)
    assert keys(p) == ["est_sales.sum"]  # 추이만 보여 준다
    q = okplan("요즘 유망한 업종은?")
    assert q.intent == "industry_comparison" and q.sort_by == "est_sales.growth_rate"  # '유망한'이 '망한'으로 읽히지 않는다


@pytest.mark.parametrize("q,intent", [("카페랑 편의점 중에 뭐가 나아?", "industry_comparison"),
                                      ("성수 홍대 중 어디가 나아?", "region_comparison"),
                                      ("성수 카페 vs 홍대 카페 어디가 좋아?", "region_comparison")])
def test_choice_questions_compare_per_store_not_just_total(q, intent):
    p = okplan(q)
    assert p.intent == intent and p.sort_by == "est_sales.per_store" and p.disclaimers, q


def test_investment_and_capital_questions_are_declined_with_reason():
    r0 = ev("가장 안전한 투자처는?")
    assert "투자" in r0.reason and "폐업률 낮은 업종은?" in r0.suggested_questions
    r = ev("소자본 창업 뭐가 좋아?")
    assert r.status == "needs_clarification" and r.missing_columns


@pytest.mark.parametrize("q", ["성수 매출 좋아졌어?", "성수 카페 매출 알려줘", "희망하는 업종 알려줘", "성수와 홍대의 카페 매출을 비교해줘"])
def test_ordinary_questions_do_not_trigger_judgment_notices(q):
    from app.services.judgment import detect_judgment

    assert detect_judgment(q, 0, 0) is None, q


def test_industry_word_turns_composition_into_industry_ranking():
    p = okplan("주말 장사 잘 되는 업종은?")
    assert p.intent == "industry_comparison" and p.sort_by == "weekend_sales.ratio"


# ---------------------------------------------------------------- C 검증의 미해결 오류 (PEARL_TEST)
def test_year_over_year_wording_uses_same_quarter_last_year():
    from app.services.calc.builder import build_request

    p = okplan("이태원 2025년 4분기 전년 같은 분기 대비 증감률")
    assert p.growth_basis == "year_over_year" and p.period.start == "2025-10" and p.period.end == "2025-12"
    g = build_request(p, "d").growth
    assert (g.baseline_period.start, g.baseline_period.end) == ("2024-10", "2024-12")  # 전 분기(2025-07~09)가 아니다
    assert any("전년 같은 기간 대비" in a for a in p.assumptions)


@pytest.mark.parametrize("q", ["이태원 2025년 4분기 작년 대비 매출", "이태원 2025년 4분기 전년 동기 대비 증감률"])
def test_year_over_year_wording_variants(q):
    p = okplan(q)
    assert p.growth_basis == "year_over_year" and any(m.op == "growth_rate" for m in p.metrics)


def test_year_over_year_without_period_uses_latest_quarter_not_last_year_range():
    p = okplan("강남 작년 같은 분기 대비 매출 증감")
    assert p.growth_basis == "year_over_year" and (p.period.start, p.period.end) == ("2026-04", "2026-06")


def test_default_growth_states_what_it_was_compared_with():
    p = okplan("이태원 2025년 4분기 증감률")
    assert p.growth_basis == "previous" and any("직전 분기 대비" in a for a in p.assumptions)
    q = okplan("강남 매출 증가율")
    assert any("직전 4분기 대비" in a for a in q.assumptions)


def test_total_question_returns_one_combined_value():
    p = okplan("성수와 홍대 매출 합계는?")
    assert p.intent == "lookup" and p.regions == ["성수", "홍대"] and [m.op for m in p.metrics] == ["sum"]
    assert p.group_by == [] and any("합산" in a for a in p.assumptions)
    assert okplan("전체 지역 매출 합계").regions == []


def test_weekday_and_weekend_both_answered():
    p = okplan("이태원 2025년 4분기 주중 매출과 주말 매출")
    assert {m.column for m in p.metrics} == {"weekday_sales", "weekend_sales"}


def test_gender_sum_vs_total_explains_missing_corporate_sales():
    p = okplan("남성 매출과 여성 매출이 총매출과 같아?")
    assert p.intent == "lookup" and {m.column for m in p.metrics} == {"male_sales", "female_sales", "est_sales"}
    assert any("법인" in a for a in p.assumptions)


def test_gender_words_are_never_treated_as_unknown_industries():
    d = PlanDraft(status="ok", intent="other", industries=["남성", "여성"])
    r = planner.evaluate("남성 매출과 여성 매출이 총매출과 같아?", d, DS, LATEST)
    assert r.status == "ok"


@pytest.mark.parametrize("q", ["2030년 1분기 강남 매출", "2020년 강남 매출", "강남 2026년 3분기 매출"])
def test_period_outside_data_range_explains_available_range(q):
    r = ev(q)
    assert r.status == "needs_clarification" and "2021년 1분기" in r.reason and "2026년 2분기" in r.reason
    assert r.suggested_questions


def test_latest_quarter_itself_is_inside_range():
    assert okplan("강남 2026년 2분기 매출").period.end == "2026-06"


# ---------------------------------------------------------------- 이어 묻기 (history)
from app.services.follow_up import clean_history, is_follow_up  # noqa: E402


def follow(history, q):
    """history(오래된 순)를 읽은 뒤 q를 평가한다. 서버의 make_plan 과 같은 순서."""
    ctx = planner.build_context(history, DS, LATEST)
    return planner.evaluate(q, NULL, DS, LATEST, context=ctx)


def fplan(history, q):
    r = follow(history, q)
    assert r.status == "ok", (history, q, r.reason)
    return r.plan


def test_follow_up_inherits_missing_industry_and_metric():
    p = fplan(["성수 카페 점포당 매출"], "그럼 홍대는?")
    assert p.regions == ["홍대"] and p.industries == ["카페"]
    assert keys(p)[0] == "est_sales.per_store"
    assert p.assumptions[0].startswith("이전 질문의") and "이어서 적용" in p.assumptions[0]


def test_follow_up_inherits_stated_period_but_not_default_period():
    p = fplan(["성수 카페 2025년 4분기 매출"], "그럼 홍대는?")
    assert (p.period.start, p.period.end) == ("2025-10", "2025-12") and "기간" in p.assumptions[0]
    q = fplan(["성수 카페 매출"], "그럼 홍대는?")  # 앞 질문에 기간이 없었다 -> 기본값(최근 4분기) 그대로
    assert (q.period.start, q.period.end) == ("2025-07", "2026-06") and "기간" not in q.assumptions[0]


def test_follow_up_chain_keeps_conditions():
    p = fplan(["성수 카페 매출", "그럼 홍대는?"], "강남은?")
    assert p.regions == ["강남"] and p.industries == ["카페"]


def test_follow_up_relative_period_word_replaces_old_period():
    p = fplan(["성수 카페 2025년 4분기 매출"], "작년은?")
    assert p.regions == ["성수"] and (p.period.start, p.period.end) == ("2025-01", "2025-12")


@pytest.mark.parametrize("history,q", [
    (["성수 카페 매출 알려줘"], "강남 한식 매출 알려줘"),   # 이미 완성된 질문
    (["성수 카페 매출 알려줘"], "요즘 뜨는 상권은?"),       # 순위형은 지역을 붙이지 않는다
    (["성수 카페 매출 알려줘"], "창업하기 좋은 곳은?"),     # 이어 묻는 표현이 없다
    (["성수 카페 매출 알려줘"], "가장 높은 곳은?"),
])
def test_unrelated_questions_inherit_nothing(history, q):
    r = follow(history, q)
    if r.status == "ok":
        assert not r.plan.assumptions or not r.plan.assumptions[0].startswith("이전 질문의"), (q, r.plan.assumptions)
        assert r.plan.regions != ["성수"] or "성수" in q
    else:
        assert r.status == "needs_clarification"


def test_info_question_never_inherits():
    assert follow(["성수 카페 매출 알려줘"], "추정매출이 뭐야?").status == "info"


def test_follow_up_without_history_behaves_like_before():
    a = planner.evaluate("그럼 홍대는?", NULL, DS, LATEST)
    b = follow([], "그럼 홍대는?")
    assert a.status == b.status and a.plan.regions == b.plan.regions == ["홍대"] and a.plan.industries == []


# ---------------------------------------------------------------- 되물음에 대한 짧은 답 ("카페 매출" -> "성수동")
def answer(history, q):
    """서버의 make_plan 과 같은 순서: 되물음에 이은 답이면 앞 질문과 합쳐 읽는다."""
    merged = planner.clarification_answer(q, history, DS, LATEST)
    ctx = planner.build_context(clean_history(history)[:-1] if merged else history, DS, LATEST)
    return merged, planner.evaluate(merged or q, NULL, DS, LATEST, context=ctx)


@pytest.mark.parametrize("history,q,region,industry", [
    (["카페 매출"], "성수동", "성수", "카페"),
    (["카페 매출"], "성수는?", "성수", "카페"),
    (["카페 매출"], "성수 알려줘", "성수", "카페"),
    (["카페 점포당 매출"], "홍대", "홍대", "카페"),
])
def test_short_answer_after_clarification_is_merged(history, q, region, industry):
    merged, r = answer(history, q)
    assert merged and r.status == "ok", (history, q, r.reason)
    assert r.plan.regions == [region] and r.plan.industries == [industry]


def test_merged_answer_keeps_metric_of_first_question():
    _, r = answer(["카페 점포당 매출"], "홍대")
    assert keys(r.plan)[0] == "est_sales.per_store"


@pytest.mark.parametrize("history,q", [
    (["카페 매출"], "강남 한식 매출 알려줘"),   # 이미 완성된 질문
    (["카페 매출"], "매출 순위 알려줘"),         # 순위를 말했다
    (["카페 매출"], "추정매출이 뭐야?"),         # 값을 말한 답이 아니다
    (["성수 카페 매출"], "홍대"),                # 앞 질문이 막히지 않았다
    ([], "성수동"),                              # 앞 질문이 없다
    (["성수 매출"], "카페"),                     # 앞 질문이 막히지 않았다
])
def test_not_merged_when_not_an_answer_to_clarification(history, q):
    assert planner.clarification_answer(q, history, DS, LATEST) is None


def test_follow_up_after_merged_answer_keeps_industry():
    # "카페 매출" -> "성수동"(합쳐 읽음) -> "그럼 홍대는?" : 카페가 계속 이어진다
    p = fplan(["카페 매출", "성수동"], "그럼 홍대는?")
    assert p.regions == ["홍대"] and p.industries == ["카페"]


def test_blocked_history_is_skipped():
    p = fplan(["창업하기 좋은 곳은?", "성수 카페 매출"], "그럼 홍대는?")  # 앞의 막힌 질문은 건너뛴다
    assert p.industries == ["카페"]


def test_industry_word_keeps_region_but_drops_industry():
    p = fplan(["성수 카페 매출"], "그럼 업종별로는?")
    assert p.intent == "industry_comparison" and p.regions == ["성수"] and p.industries == []


@pytest.mark.parametrize("q,expected", [("그럼 홍대는?", True), ("홍대는?", True), ("작년은?", True), ("점포당은?", True),
                                        ("강남도?", True), ("요즘 뜨는 상권은?", False), ("창업하기 좋은 곳은?", False),
                                        ("성수 카페 매출 알려줘", False), ("추정매출이 뭐야?", False)])
def test_follow_up_detection(q, expected):
    assert is_follow_up(q) is expected


def test_clean_history_is_defensive():
    assert clean_history(["a", " ", "b", 3, None, "c", "d"]) == ["b", "c", "d"][-3:]
    assert clean_history(None) == [] and clean_history(["x" * 500])[0] == "x" * 200


@pytest.mark.parametrize("word,industry", [("한식", "한식음식점"), ("중식", "중식음식점"), ("분식", "분식전문점"),
                                           ("치킨", "치킨전문점"), ("빵집", "제과점"), ("피시방", "PC방")])
def test_short_industry_names_are_not_silently_dropped(word, industry):
    p = okplan(f"강남 {word} 매출 알려줘")
    assert p.industries == [industry], word  # 인식되지 않으면 '전체 업종 합계'로 조용히 계산되던 문제

# ---------------------------------------------------------------- 예상 질문 점검에서 찾은 문제 수정
@pytest.mark.parametrize("q,start,end", [
    ("강남 올해 1분기 매출", "2026-01", "2026-03"),      # 올해 전체가 아니라 말한 분기만
    ("강남 작년 3분기 매출", "2025-07", "2025-09"),
    ("강남 작년 3~4분기 매출", "2025-07", "2025-12"),
    ("강남 올해 상반기 매출", "2026-01", "2026-06"),
    ("강남 작년 하반기 매출", "2025-07", "2025-12"),
])
def test_relative_year_with_quarter(q, start, end):
    r = planner.evaluate(q, NULL, DS, LATEST)
    assert r.status == "ok" and (r.plan.period.start, r.plan.period.end) == (start, end)


def test_relative_year_quarter_beyond_data_is_clarified():
    r = planner.evaluate("강남 올해 3분기 매출", NULL, DS, LATEST)
    assert r.status == "needs_clarification" and "2026년 2분기" in r.reason


@pytest.mark.parametrize("q", ["이태원 매출 늘고 있어?", "강남 매출 줄었어?", "홍대 매출 올랐어?", "건대 매출 떨어졌어?"])
def test_growing_or_shrinking_questions_use_growth(q):
    r = planner.evaluate(q, NULL, DS, LATEST)
    assert r.status == "ok" and keys(r.plan)[0] == "est_sales.growth_rate", q


def test_many_places_with_industry_ranks_by_store_count():
    r = planner.evaluate("카페 많은 곳 top 5", NULL, DS, LATEST)
    p = r.plan
    assert r.status == "ok" and p.intent == "ranking" and p.sort_by == "store_count.avg" and p.rank_order == "desc" and p.top_n == 5
    assert any("점포 수 기준" in a for a in p.assumptions)
    low = planner.evaluate("카페 적은 곳", NULL, DS, LATEST).plan
    assert low.sort_by == "store_count.avg" and low.rank_order == "asc"


def test_many_places_without_industry_is_not_store_count():
    p = planner.evaluate("사람 많은 곳", NULL, DS, LATEST).plan  # 유동인구 같은 말은 점포 수로 바꾸지 않는다
    assert p is None or p.sort_by != "store_count.avg"


@pytest.mark.parametrize("q", ["건대 술집 위험해?", "홍대 카페 위험하지 않아?", "성수 미용실 위험할까?"])
def test_risky_expressions_are_danger(q):
    r = planner.evaluate(q, NULL, DS, LATEST)
    assert r.status == "ok" and r.plan.kind == "danger", q


@pytest.mark.parametrize("q,topic", [
    ("이 데이터 언제 거야?", "freshness"),
    ("데이터 언제까지 있어?", "freshness"),
    ("점포 수에 프랜차이즈도 들어가?", "store_def"),
    ("프랜차이즈는 점포 수에서 빠져?", "store_def"),
])
def test_more_data_fact_phrasings(q, topic):
    r = planner.evaluate(q, NULL, DS, LATEST)
    assert r.status == "info" and r.info_topic == topic, q


@pytest.mark.parametrize("q", ["성수 점포 수 알려줘", "성수 프랜차이즈 점포 수", "강남 점포 수 순위", "성수 프랜차이즈 비율"])
def test_store_questions_stay_analysis(q):
    assert planner.evaluate(q, NULL, DS, LATEST).status == "ok", q


@pytest.mark.parametrize("history,q,region,industry,primary", [
    (["성수 카페 매출"], "점포당으로 보면?", "성수", "카페", "est_sales.per_store"),
    (["성수 카페 매출"], "그거 말고 점포 수는?", "성수", "카페", "store_count.avg"),
])
def test_more_follow_up_phrasings(history, q, region, industry, primary):
    p = fplan(history, q)
    assert p.regions == [region] and p.industries == [industry] and keys(p)[0] == primary


def test_period_only_answer_follows_up():
    p = fplan(["성수 카페 매출"], "2025년 4분기")
    assert p.regions == ["성수"] and p.industries == ["카페"] and (p.period.start, p.period.end) == ("2025-10", "2025-12")


def test_ranking_follow_up_keeps_industry_not_region():
    p = fplan(["성수 카페 매출"], "순위로 보여줘")
    assert p.intent == "ranking" and p.regions == [] and p.industries == ["카페"]


@pytest.mark.parametrize("q", ["2025년 4분기 매출 순위", "강남 매출", "요즘 뜨는 상권은?"])
def test_new_questions_are_not_follow_ups(q):
    assert not is_follow_up(q)


def test_typo_gets_suggestion_not_guess():
    r = planner.evaluate("홍데 매출", NULL, DS, LATEST)
    assert r.status == "needs_clarification" and "'홍대' 말씀이신가요?" in r.reason


def test_english_question_gets_korean_guidance():
    r = planner.evaluate("Hongdae cafe sales", NULL, DS, LATEST)
    assert r.status == "needs_clarification" and "한국어" in r.clarification_question

# ---------------------------------------------------------------- 야간 = 21시~06시 (두 칸 합), 합계의 N곳, 모델이 되읽은 말
from app.schemas.calc import CalcApplied, CalcMetric, CalcResult, CalcRow  # noqa: E402
from app.services.combine import apply_combine  # noqa: E402
from app.services.compose import compose_block  # noqa: E402
from app.services.ranking import rank as rank_view  # noqa: E402

NIGHT_PARTS = ["time_21_24_sales", "time_00_06_sales"]


def _night_result(plan, a, b):
    ops = [CalcMetric(column=c, op=plan.metrics[0].op) for c in NIGHT_PARTS]
    row = CalcRow(group={}, values={f"{c}.{plan.metrics[0].op}": v for c, v in zip(NIGHT_PARTS, (a, b))}, rows_used=4)
    return CalcResult(request_id="r", status="ok", dataset_id="d", data_version="v", data_source="s", rows_used=4,
                      applied=CalcApplied(columns_used=NIGHT_PARTS, operations=ops, group_by=[], filters=[]), results=[row])


@pytest.mark.parametrize("q", ["이태원 야간(21시~06시) 매출 비중은?", "이태원 야간 매출 비중", "이태원 21시~06시 매출 비중은?"])
def test_night_means_two_time_bands(q):
    p = planner.evaluate(q, NULL, DS, LATEST).plan
    assert [m.column for m in p.metrics] == NIGHT_PARTS and p.combine == {"time_night_sales": NIGHT_PARTS}
    assert any("밤(21~24시)과 새벽(0~6시)" in a for a in p.assumptions)


def test_night_ranking_sorts_by_the_combined_value():
    p = planner.evaluate("야간 매출 비중 높은 상권", NULL, DS, LATEST).plan
    assert p.intent == "ranking" and p.sort_by == "time_night_sales.ratio" and p.combine


@pytest.mark.parametrize("q,col", [("이태원 밤 매출 비중", "time_21_24_sales"), ("이태원 새벽 매출 비중", "time_00_06_sales")])
def test_other_time_words_keep_their_single_band(q, col):
    p = planner.evaluate(q, NULL, DS, LATEST).plan
    assert [m.column for m in p.metrics] == [col] and not p.combine


def test_combined_night_value_is_the_sum_of_engine_values_and_shown_with_parts():
    p = planner.evaluate("이태원 야간(21시~06시) 매출 비중은?", NULL, DS, LATEST).plan
    res = apply_combine(p, _night_result(p, 0.179, 0.227))
    assert res.results[0].values["time_night_sales.ratio"] == pytest.approx(0.406)
    head, lines = compose_block(p, res, rank_view(p, res))
    assert "야간(21~06시) 매출 비중은 40.6%입니다" in head
    assert lines == ["• 밤(21~24시): 17.9%", "• 새벽(0~6시): 22.7%"]


def test_combined_value_is_none_when_a_part_is_missing():
    p = planner.evaluate("이태원 야간 매출 비중", NULL, DS, LATEST).plan
    res = apply_combine(p, _night_result(p, 0.179, None))
    assert res.results[0].values["time_night_sales.ratio"] is None


def test_combine_is_a_noop_for_other_plans():
    p = planner.evaluate("이태원 밤 매출 비중", NULL, DS, LATEST).plan
    res = _night_result(p, 0.179, 0.227)
    n = len(res.applied.operations)
    assert len(apply_combine(p, res).applied.operations) == n


def test_total_with_named_regions_and_count_is_one_combined_value():
    p = planner.evaluate("2025년 4분기 성수 홍대 강남 이태원 건대 5곳 전체 매출 합계는?", NULL, DS, LATEST).plan
    assert p.intent == "lookup" and len(p.regions) == 5 and any("합산 값" in a for a in p.assumptions)


@pytest.mark.parametrize("q,intent", [
    ("성수 홍대 강남 이태원 건대 5곳 매출 순위", "region_comparison"),   # 순위 말이 있으면 합계가 아니다
    ("2025년 4분기 5곳 전체 매출 합계는?", "ranking"),                  # 어느 5곳인지 모르면 상위 5곳
])
def test_count_word_is_still_top_n_when_it_cannot_be_a_region_count(q, intent):
    assert planner.evaluate(q, NULL, DS, LATEST).plan.intent == intent


@pytest.mark.parametrize("q,missing", [
    ("이태원 2025년 4분기 매출은?", ["2025년 4분기 매출"]),
    ("이태원 2025년 4분기 밤 매출 비중은?", ["2025년 4분기", "밤 매출 비중"]),
    ("홍대 2025년 4분기 저녁 매출 비중은?", ["2025년", "4분기", "저녁 매출 비중"]),
])
def test_model_echoing_understood_terms_as_missing_does_not_block(q, missing):
    d = PlanDraft(status="needs_clarification", missing_fields=missing)
    assert planner.evaluate(q, d, DS, LATEST).status == "ok", q


@pytest.mark.parametrize("q,missing", [("성수 유동인구 알려줘", ["유동인구"]), ("성수 임대료 얼마야?", ["임대료"])])
def test_model_flagging_a_really_missing_item_still_blocks(q, missing):
    d = PlanDraft(status="needs_clarification", missing_fields=missing)
    r = planner.evaluate(q, d, DS, LATEST)
    assert r.status == "needs_clarification" and set(missing) <= set(r.missing_fields)
