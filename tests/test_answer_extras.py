"""창업·수입 질문의 답변 형식: 결론 한 문장 + 같은 조건에서의 순위 + 이어서 물어볼 질문."""
from dataclasses import replace

import pytest

from app.schemas.calc import CalcApplied, CalcMetric, CalcResult, CalcRow
from app.schemas.plan import AnalysisPlan, PlanDraft
from app.services import explain, planner
from app.services.answer_extras import (
    build_rank_plan,
    compute_ranks,
    followup_candidates,
    wants_rank_context,
)
from app.services.dataset import default_dataset
from app.services.ranking import rank

DS = default_dataset()
LATEST = (2026, 2)
NULL = PlanDraft(status="ok", intent="other")


def plan_for(q):
    r = planner.evaluate(q, NULL, DS, LATEST)
    assert r.status == "ok", q
    return r.plan


def _regions_result(rows):
    """rows: (지역, 점포당, 점포 수, 매출합)"""
    ops = [CalcMetric(column="est_sales", op="per_store"), CalcMetric(column="store_count", op="avg"),
           CalcMetric(column="est_sales", op="sum")]
    return CalcResult(
        request_id="r", status="ok", dataset_id="d", data_version="v", data_source="s", rows_used=9,
        applied=CalcApplied(columns_used=["est_sales", "store_count"], operations=ops, group_by=["region"], filters=[]),
        results=[CalcRow(group={"region": n}, values={"est_sales.per_store": ps, "store_count.avg": sc, "est_sales.sum": sm},
                         rows_used=1) for n, ps, sc, sm in rows])


REGIONS = [("강남", 22e6, 541, 5e11), ("명동", 21e6, 200, 3e11), ("성수", 8.8e6, 598, 6e11),
           ("홍대", 13e6, 712, 9e11), ("작은곳", 99e6, 3, 5e7)]  # 작은곳: 매출 1억 원 미만 -> 순위에서 제외


def test_context_only_for_single_area_startup_and_income_lookups():
    assert wants_rank_context(plan_for("성수에서 카페 차리면 괜찮을까?"))
    assert wants_rank_context(plan_for("성수 카페 사장 수입은?"))
    assert not wants_rank_context(plan_for("성수 카페 매출 알려줘"))
    assert not wants_rank_context(plan_for("카페 창업하기 좋은 곳은?"))  # 이미 지역 순위
    assert not wants_rank_context(plan_for("성수 홍대 중 어디가 나아?"))  # 두 지역 비교


def test_rank_plan_asks_for_every_region_with_same_industry_and_period():
    p = plan_for("성수에서 카페 차리면 괜찮을까?")
    rp = build_rank_plan(p)
    assert rp.intent == "ranking" and rp.regions == [] and rp.group_by == ["region"]
    assert rp.filters == p.filters and rp.period == p.period and rp.top_n is None
    assert [f"{m.column}.{m.op}" for m in rp.metrics] == ["est_sales.per_store", "store_count.avg", "est_sales.sum"]
    assert build_rank_plan(plan_for("성수 카페 매출 알려줘")) is None


def test_ranks_are_read_from_engine_values_and_tiny_regions_are_excluded():
    p = plan_for("성수에서 카페 차리면 괜찮을까?")
    rc = compute_ranks(p, _regions_result(REGIONS))
    assert rc.total == 4 and rc.excluded == 1  # 작은곳(매출 5천만 원)은 순위에서 뺐다
    assert rc.per_store_rank == 4  # 강남 > 명동 > 홍대 > 성수
    assert rc.store_rank == 2  # 홍대 712 > 성수 598
    assert rc.top_region == "강남"


def test_ranks_unavailable_when_target_missing_or_error():
    p = plan_for("성수에서 카페 차리면 괜찮을까?")
    assert compute_ranks(p, _regions_result([r for r in REGIONS if r[0] != "성수"])) is None
    bad = _regions_result(REGIONS).model_copy(update={"status": "error"})
    assert compute_ranks(p, bad) is None


def test_followup_candidates_use_correct_josa_and_context():
    p = plan_for("성수에서 카페 차리면 괜찮을까?")
    rc = compute_ranks(p, _regions_result(REGIONS))
    c = followup_candidates(p, rc)
    assert "성수와 강남의 카페 점포당 월평균 매출을 비교해줘" in c  # 받침 없음 -> '와'
    assert any("카페 점포당 월평균 매출이 높은 지역은?" == x for x in c)
    q = followup_candidates(plan_for("강남에서 카페 차리면 괜찮을까?"), replace(rc, top_region="홍대"))
    assert "강남과 홍대의 카페 점포당 월평균 매출을 비교해줘" in q  # 받침 있음 -> '과'


def test_verified_followups_all_pass_without_a_model():
    p = plan_for("성수에서 카페 차리면 괜찮을까?")
    rc = compute_ranks(p, _regions_result(REGIONS))
    qs = planner.verify_questions(followup_candidates(p, rc), DS, LATEST)
    assert 1 <= len(qs) <= 3
    for q in qs:
        assert planner.evaluate(q, NULL, DS, LATEST, suggest=False).status == "ok", q


def _main_result():
    ops = [CalcMetric(column="store_count", op="avg"), CalcMetric(column="est_sales", op="per_store"),
           CalcMetric(column="est_sales", op="sum"), CalcMetric(column="est_sales", op="growth_rate")]
    return CalcResult(
        request_id="r", status="ok", dataset_id="d", data_version="v", data_source="s", rows_used=9,
        applied=CalcApplied(columns_used=["est_sales", "store_count"], operations=ops, group_by=[], filters=[]),
        results=[CalcRow(group={}, values={"store_count.avg": 598.0, "est_sales.per_store": 8.88e6,
                                           "est_sales.sum": 6.379e10, "est_sales.growth_rate": 0.059}, rows_used=4)])


@pytest.mark.anyio
async def test_answer_has_conclusion_sentence_ranks_followups_and_notice():
    p = plan_for("성수에서 카페 차리면 괜찮을까?")
    rc = compute_ranks(p, _regions_result(REGIONS))
    text, _ = await explain.generate_explanation("q", p, _main_result(), rank_ctx=rc, followups=["다음 질문 하나"])
    lines = text.split("\n")
    assert lines[0] == "성수 카페는 점포 598개, 한 곳당 월평균 매출 888만 원입니다 (2025Q3~2026Q2)."
    assert "• 점포당 월평균: 카페 기준 4곳 중 4위 (높은 순)" in text
    assert "• 점포 수: 카페 기준 4곳 중 2위 (많은 순)" in text
    assert "• 매출 증감: +5.9% (직전 4분기 대비)" in text and "• 매출 합계: 637.9억 원" in text
    assert "→ 이어서 물어보기: 다음 질문 하나" in text
    assert "추천이 아닙니다" in text  # 고정 안내는 그대로
    assert "→ 직전 같은 기간" not in text  # 증감은 목록에 이미 있으므로 중복 관찰문 없음


@pytest.mark.anyio
async def test_answer_without_rank_still_has_sentence_and_notice():
    p = plan_for("성수에서 카페 차리면 괜찮을까?")
    text, _ = await explain.generate_explanation("q", p, _main_result())
    assert text.startswith("성수 카페는 점포 598개") and "점포당 월평균:" not in text and "추천이 아닙니다" in text
    assert "이어서 물어보기" not in text


def test_other_answers_keep_their_format():
    view = rank(plan_for("성수 카페 매출 알려줘"), _main_result())
    assert view.rows  # 일반 조회는 startup 형식을 쓰지 않는다 (plan.kind 가 없다)
    assert plan_for("성수 카페 매출 알려줘").kind is None
