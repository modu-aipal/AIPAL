"""순위 품질: 매출 없는 그룹 제외 · 증감 방향 사실 · 목록 재나열 해석 거부."""
from app.schemas.calc import CalcApplied, CalcMetric, CalcResult, CalcRow
from app.schemas.plan import AnalysisPlan
from app.services import explain
from app.services.ranking import rank


def _result(rows):
    """rows: (업종, 매출, 증감) — 점포 데이터에만 있는 업종은 매출 0.0 으로 온다."""
    ops = [CalcMetric(column="est_sales", op="sum"), CalcMetric(column="est_sales", op="growth_rate"),
           CalcMetric(column="est_sales", op="per_store")]
    return CalcResult(
        request_id="r", status="ok", dataset_id="d", data_version="v", data_source="s", rows_used=99,
        applied=CalcApplied(columns_used=["est_sales"], operations=ops, group_by=["industry"], filters=[]),
        results=[CalcRow(group={"industry": n}, values={"est_sales.sum": s, "est_sales.growth_rate": g,
                                                         "est_sales.per_store": 1e7}, rows_used=1)
                 for n, s, g in rows],
    )


def _plan(**kw):
    base = dict(intent="industry_comparison", regions=["가산동"], industries=[],
                metrics=[{"column": "est_sales", "op": "sum"}, {"column": "est_sales", "op": "growth_rate"},
                         {"column": "est_sales", "op": "per_store"}],
                group_by=["industry"], comparison="industry", filters=[], period=None,
                sort_by="est_sales.sum", rank_order="desc", top_n=5)
    base.update(kw)
    return AnalysisPlan.model_validate(base)


ROWS = [("A", 9e10, 0.1), ("B", 7e10, -0.2), ("C", 5e10, 0.3), ("D", 3e10, 0.0), ("E", 2e10, -0.1),
        ("F", 1e10, 0.2), ("점포만있음1", 0.0, None), ("점포만있음2", 0.0, None)]


def test_groups_without_sales_are_not_counted_or_ranked():
    view = rank(_plan(), _result(ROWS))
    assert view.total == 6  # 매출이 있는 업종만 '전체'로 센다
    assert [r.group["industry"] for r in view.rows] == ["A", "B", "C", "D", "E"]


def test_bottom_ranking_is_not_filled_with_zero_sales():
    view = rank(_plan(rank_order="asc", top_n=3), _result(ROWS))
    assert [r.group["industry"] for r in view.rows] == ["F", "E", "D"]  # 매출 0인 업종이 하위를 채우지 않는다


def test_no_misleading_nodata_note_for_sales_less_groups():
    view = rank(_plan(sort_by="est_sales.growth_rate"), _result(ROWS))
    assert not any("계산할 수 없는" in n for n in view.notes)


def test_facts_tell_the_model_how_many_went_up_or_down():
    res = _result(ROWS)
    facts = explain.build_facts(_plan(), res)
    assert facts[-1] == "목록 5개 중 증감이 늘어난 곳 2개, 줄어든 곳 2개."  # A +, C + / B -, E - (D는 0)


def test_interpretation_repeating_the_list_is_rejected():
    view = rank(_plan(), _result(ROWS))
    assert explain.repeats_list("A, B, C가 상위입니다.", view)
    assert not explain.repeats_list("매출은 큰데 증감이 마이너스인 곳이 절반입니다.", view)
