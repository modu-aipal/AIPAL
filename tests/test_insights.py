"""코드가 계산 결과에서 직접 뽑는 관찰(insights)과 모델 해석 기본값."""
import os

from app.core.config import Settings
from app.schemas.calc import CalcApplied, CalcMetric, CalcResult, CalcRow
from app.schemas.plan import AnalysisPlan
from app.services.compose import insights
from app.services.ranking import rank

TRIO = [CalcMetric(column="est_sales", op="sum"), CalcMetric(column="est_sales", op="growth_rate"),
        CalcMetric(column="est_sales", op="per_store")]


def _result(rows, ops=TRIO, group="industry"):
    return CalcResult(
        request_id="r", status="ok", dataset_id="d", data_version="v", data_source="s", rows_used=9,
        applied=CalcApplied(columns_used=["est_sales"], operations=ops, group_by=[group] if group else [], filters=[]),
        results=[CalcRow(group={group: n} if group else {},
                         values={"est_sales.sum": s, "est_sales.growth_rate": g, "est_sales.per_store": 1e7},
                         rows_used=1) for n, s, g in rows],
    )


def _plan(**kw):
    base = dict(intent="industry_comparison", regions=["가산동"], industries=[],
                metrics=[{"column": "est_sales", "op": "sum"}, {"column": "est_sales", "op": "growth_rate"},
                         {"column": "est_sales", "op": "per_store"}],
                group_by=["industry"], comparison="industry", filters=[], period=None,
                sort_by="est_sales.sum", rank_order="desc", top_n=5)
    base.update(kw)
    return AnalysisPlan.model_validate(base)


def test_ranking_insights_count_up_and_down_and_flag_big_but_shrinking_first():
    res = _result([("일반의류", 9e10, -0.004), ("한식", 7e10, 0.055), ("가전", 5e10, -0.024),
                   ("화장품", 3e10, -0.084), ("편의점", 2e10, -0.052)])
    plan = _plan()
    out = insights(plan, res, rank(plan, res))
    assert out[0] == "증감은 목록 5개 중 1개가 늘고 4개가 줄었습니다."
    assert out[1] == "매출 1위 일반의류는 증감이 -0.4%로, 규모는 크지만 줄고 있습니다."


def test_no_first_place_warning_when_the_leader_is_growing():
    res = _result([("A", 9e10, 0.2), ("B", 7e10, -0.1)])
    plan = _plan()
    assert insights(plan, res, rank(plan, res)) == ["증감은 목록 2개 중 1개가 늘고 1개가 줄었습니다."]


def test_trend_insight_names_highest_and_lowest_quarter():
    ops = [CalcMetric(column="est_sales", op="sum")]
    res = CalcResult(
        request_id="r", status="ok", dataset_id="d", data_version="v", data_source="s", rows_used=9,
        applied=CalcApplied(columns_used=["est_sales"], operations=ops, group_by=["quarter"], filters=[]),
        results=[CalcRow(group={"quarter": q}, values={"est_sales.sum": v}, rows_used=1)
                 for q, v in [("2025Q3", 2.9e11), ("2025Q4", 3.1e11), ("2026Q1", 3.0e11), ("2026Q2", 3.5e11)]],
    )
    plan = _plan(intent="sales_trend", regions=["성수"], group_by=["quarter"], comparison="none",
                 metrics=[{"column": "est_sales", "op": "sum"}], sort_by=None, rank_order=None, top_n=None)
    assert insights(plan, res, rank(plan, res)) == ["가장 높은 분기는 2026Q2, 가장 낮은 분기는 2025Q3입니다."]


def test_lookup_with_growth_says_whether_it_rose():
    res = _result([("", 5e10, -0.03)], group=None)
    res.results[0].group = {}
    plan = _plan(intent="lookup", group_by=[], comparison="none", sort_by=None, rank_order=None, top_n=None)
    assert insights(plan, res, rank(plan, res)) == ["직전 같은 기간보다 매출이 줄었습니다."]


def test_single_metric_lookup_has_no_insight():
    ops = [CalcMetric(column="est_sales", op="sum")]
    res = _result([("", 5e10, None)], ops=ops, group=None)
    plan = _plan(intent="lookup", group_by=[], comparison="none", sort_by=None, rank_order=None, top_n=None,
                 metrics=[{"column": "est_sales", "op": "sum"}])
    assert insights(plan, res, rank(plan, res)) == []


def test_model_interpretation_is_off_by_default():
    env = {k: v for k, v in os.environ.items() if k != "EXPLAIN_INTERPRETATION"}
    old = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        assert Settings(_env_file=None).explain_interpretation is False  # 기본값: 코드가 만든 관찰만
    finally:
        os.environ.clear()
        os.environ.update(old)
