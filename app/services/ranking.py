"""순위·업종 비교 결과를 정렬하고 상위 N개로 줄인다. 순위는 코드가 정한다 (모델이 아님).

- 증가율 기준은 매출 규모가 아주 작은 곳(최근 매출 1억 원 미만)을 뺀다: 기준이 작으면 증가율이 과장된다.
- 계산할 수 없는 값(None)은 순위에서 뺀다.
"""
from dataclasses import dataclass, field

from app.schemas.calc import CalcResult, CalcRow
from app.schemas.plan import AnalysisPlan

MIN_SALES_FOR_GROWTH = 1e8  # 원. 증가율 순위에서 제외할 최근 매출 하한


@dataclass
class RankedView:
    rows: list[CalcRow]
    total: int  # 계산된 전체 행(그룹) 수
    key: str | None = None  # 정렬 기준 지표 키
    ranked: bool = False  # 상위 N개로 줄였는가
    notes: list[str] = field(default_factory=list)  # 제외 안내 (답변 끝에 붙는다)


def group_label(row: CalcRow) -> str:
    """행의 그룹 값을 사람이 읽는 이름으로 (예: '성수', '2025Q3', '성수 · 2025Q3')."""
    return " · ".join(str(v) for v in row.group.values()) or "전체"


def _unit(plan: AnalysisPlan) -> str:
    return "상권" if plan.intent == "ranking" else "업종"


def rank(plan: AnalysisPlan, result: CalcResult) -> RankedView:
    rows = list(result.results)
    key = plan.sort_by
    view = RankedView(rows=rows, total=len(rows), key=key)
    if plan.intent == "sales_trend":  # 시간 순서
        view.rows = sorted(rows, key=lambda r: tuple(str(v) for v in r.group.values()))
        return view
    if not key or plan.intent not in ("ranking", "industry_comparison", "region_comparison"):
        return view
    desc = plan.rank_order != "asc"
    if plan.intent in ("ranking", "industry_comparison"):
        # 점포 데이터에만 있고 매출이 없는 그룹(매출 0)은 순위 대상이 아니다. 하위 순위가 0으로 채워지는 것도 막는다.
        sales = next((f"{m.column}.sum" for m in result.applied.operations
                      if m.column.endswith("_sales") and m.op == "sum"), None)
        if sales and any(sales in r.values for r in rows):
            rows = [r for r in rows if (r.values.get(sales) or 0) > 0]
            view.total = len(rows)
    have = [r for r in rows if r.values.get(key) is not None]
    nodata = len(rows) - len(have)  # 이미 매출이 있는 그룹 중 값을 계산할 수 없는 것
    excluded_small = 0
    if key.endswith((".growth_rate", ".per_store")):
        sales_key = key.rsplit(".", 1)[0] + ".sum"
        kept = [r for r in have if (r.values.get(sales_key) is None or r.values[sales_key] >= MIN_SALES_FOR_GROWTH)]
        excluded_small = len(have) - len(kept)
        have = kept
    have.sort(key=lambda r: r.values[key], reverse=desc)
    if plan.top_n and plan.intent in ("ranking", "industry_comparison"):
        view.rows, view.ranked = have[: plan.top_n], True
    else:
        view.rows = have
    if excluded_small:
        view.notes.append(f"증가율은 최근 매출이 1억 원 이상인 {_unit(plan)}만 비교했습니다 (작은 {excluded_small}개 제외).")
    if nodata:
        view.notes.append(f"값을 계산할 수 없는 {_unit(plan)} {nodata}개는 순위에서 뺐습니다.")
    return view
