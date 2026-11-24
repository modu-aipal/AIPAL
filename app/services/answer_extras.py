"""창업·수입 질문 답변에 덧붙이는 '비교 맥락': 같은 조건에서 이 지역이 20곳 중 몇 위인지, 이어서 물어볼 질문.

숫자는 전부 계산 엔진에서 온다. 순위를 매기려고 계산 엔진에 한 번 더 요청하고(지역별 점포당 매출·점포 수),
코드는 그 결과를 정렬해 위치만 읽는다. 순위 계산이 실패하면 순위 줄만 빼고 답한다.
"""
from dataclasses import dataclass

from app.schemas.calc import CalcResult
from app.schemas.plan import AnalysisPlan, MetricSpec
from app.services.ranking import MIN_SALES_FOR_GROWTH

CONTEXT_KINDS = ("startup", "income")  # 순위 맥락을 덧붙이는 답변 종류 (한 지역 조회일 때만)


@dataclass
class RankContext:
    total: int  # 순위를 매긴 지역 수 (매출이 너무 작은 지역은 뺐다)
    per_store_rank: int
    store_rank: int
    excluded: int  # 매출이 1억 원 미만이라 뺀 지역 수
    top_region: str | None  # 점포당 매출이 가장 높은 지역(대상 지역 제외) — 이어서 물어볼 비교 대상


def wants_rank_context(plan: AnalysisPlan) -> bool:
    return plan.kind in CONTEXT_KINDS and plan.intent == "lookup" and len(plan.regions) == 1


def build_rank_plan(plan: AnalysisPlan) -> AnalysisPlan | None:
    """같은 업종·기간으로 '모든 지역'의 점포당 매출·점포 수를 구하는 계획 (대상 지역의 순위를 읽기 위한 것)."""
    if not wants_rank_context(plan):
        return None
    return plan.model_copy(update={
        "intent": "ranking", "regions": [], "group_by": ["region"], "comparison": "region",
        "metrics": [MetricSpec(column="est_sales", op="per_store"), MetricSpec(column="store_count", op="avg"),
                    MetricSpec(column="est_sales", op="sum")],
        "sort_by": "est_sales.per_store", "rank_order": "desc", "top_n": None,
        "assumptions": [], "disclaimers": [], "kind": None, "growth_basis": "previous",
    })


def compute_ranks(plan: AnalysisPlan, result: CalcResult) -> RankContext | None:
    """지역별 결과를 정렬해 대상 지역의 위치를 읽는다. 읽을 수 없으면 None."""
    if result.status != "ok" or not plan.regions:
        return None
    target = plan.regions[0]
    rows, excluded = [], 0
    for r in result.results:
        name = r.group.get("region")
        ps, sc, sm = (r.values.get(k) for k in ("est_sales.per_store", "store_count.avg", "est_sales.sum"))
        if name is None or ps is None or sc is None:
            continue
        if (sm or 0) < MIN_SALES_FOR_GROWTH:  # 매출이 너무 작은 지역은 점포당 값이 크게 흔들려 순위에서 뺀다
            excluded += 1
            continue
        rows.append((name, ps, sc))
    names = [n for n, _, _ in rows]
    if target not in names:
        return None
    by_ps = sorted(rows, key=lambda x: x[1], reverse=True)
    by_sc = sorted(rows, key=lambda x: x[2], reverse=True)
    top = next((n for n, _, _ in by_ps if n != target), None)
    return RankContext(total=len(rows), per_store_rank=[n for n, _, _ in by_ps].index(target) + 1,
                       store_rank=[n for n, _, _ in by_sc].index(target) + 1, excluded=excluded, top_region=top)


def _wa(word: str) -> str:
    """받침 유무로 와/과."""
    ch = word.strip()[-1:] if word.strip() else ""
    if "가" <= ch <= "힣":
        return word + ("과" if (ord(ch) - 0xAC00) % 28 else "와")
    return word + "와"


def followup_candidates(plan: AnalysisPlan, rank: RankContext | None) -> list[str]:
    """이어서 물어볼 만한 질문 후보 (서버가 모델 없이 통과하는지 확인한 것만 실제로 보여 준다)."""
    region = plan.regions[0] if plan.regions else ""
    ind = plan.industries[0] if plan.industries else ""
    pre = f"{ind} " if ind else ""
    out: list[str] = []
    if rank and rank.top_region and region:
        out.append(f"{_wa(region)} {rank.top_region}의 {pre}점포당 월평균 매출을 비교해줘")
    out.append(f"{pre}점포당 월평균 매출이 높은 지역은?")
    if region:
        out.append(f"{region} 업종별 점포당 월평균 매출 순위 알려줘")
        out.append(f"{region} {pre}분기별 매출 추이 보여줘")
    return out
