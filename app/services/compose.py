"""계산 결과 -> 읽기 쉬운 구조 (결론 한 줄 + 정돈된 목록). 숫자는 계산 결과에서 그대로 옮기므로 틀릴 수 없다.

표시 규칙 (docs/DATA.md 6절, C 합의): 금액=억 원 소수 첫째 자리, 증감률=부호 붙인 % 소수 첫째 자리,
건수=쉼표 정수, 점포당 월평균=만 원. API 값은 반올림하지 않은 원본이며 표시할 때만 반올림한다.
"""
from app.schemas.calc import CalcResult, CalcRow
from app.schemas.plan import AnalysisPlan
from app.services.composition import RATIO_COLUMNS, item_label, ratio_full, ratio_short
from app.services.periods import label as quarter_label
from app.services.ranking import RankedView, group_label

COLUMN_LABEL = {
    "est_sales": "추정매출", "est_count": "매출 건수",
    "weekday_sales": "주중 매출", "weekend_sales": "주말 매출",
    "male_sales": "남성 매출", "female_sales": "여성 매출",
    "store_count": "점포 수", "general_store_count": "일반 점포 수", "franchise_count": "프랜차이즈 점포 수",
    "open_count": "개업 점포 수", "close_count": "폐업 점포 수",
}
OP_LABEL = {"sum": "합계", "avg": "분기당 평균", "growth_rate": "증감률", "per_store": "점포당 월평균", "ratio": "비중"}
STORE_COLUMNS = {"store_count", "general_store_count", "franchise_count", "open_count", "close_count"}
# 목록 한 줄에 쓰는 짧은 이름
_SHORT = {"est_sales": "매출", "est_count": "결제 건수", "weekday_sales": "주중 매출", "weekend_sales": "주말 매출",
          "male_sales": "남성 매출", "female_sales": "여성 매출", "store_count": "점포",
          "general_store_count": "일반 점포", "franchise_count": "프랜차이즈 점포", "open_count": "개업",
          "close_count": "폐업"}
# '무엇 기준으로 정렬했나'를 설명하는 말
_BASIS = {"sum": "매출 규모", "growth_rate": "매출 증가율", "per_store": "점포당 월평균 매출", "avg": "분기당 평균"}
_ORDER = {"sum": 0, "avg": 0, "ratio": 0, "growth_rate": 1, "per_store": 2}  # 규모 → 증감 → 점포당 순으로 보여 준다


def fmt_value(op: str, v: float | None, notes: list[str], column: str | None = None) -> str:
    if v is None:
        if "baseline_zero" in notes:
            return "산출 불가(기준 기간 값이 0)"
        if "baseline_missing" in notes:
            return "산출 불가(기준 기간 데이터 없음)"
        return "산출 불가"
    if op == "growth_rate":
        return f"{v * 100:+.1f}%"
    if op == "ratio":
        return f"{v * 100:.1f}%"
    if op == "per_store":
        return f"{v / 1e4:,.0f}만 원"
    if column in STORE_COLUMNS:
        return f"{v:,.0f}개"
    if column is not None and column.endswith("_sales"):
        return f"{v / 1e8:,.1f}억 원"
    if column == "est_count":
        return f"{v:,.0f}건"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def eun_neun(word: str) -> str:
    """받침 유무로 은/는."""
    ch = word.strip()[-1:] if word.strip() else ""
    if "가" <= ch <= "힣":
        return word + ("은" if (ord(ch) - 0xAC00) % 28 else "는")
    return word + "은(는)"


def col_label(column: str) -> str:
    if column in COLUMN_LABEL:
        return COLUMN_LABEL[column]
    return f"{item_label(column)} 매출" if column in RATIO_COLUMNS else column


def short_label(column: str, op: str) -> str:
    if op == "ratio":
        return ratio_short(column)
    base = _SHORT.get(column) or (f"{item_label(column)} 매출" if column in RATIO_COLUMNS else column)
    if op == "growth_rate":
        return "증감" if column == "est_sales" else f"{base} 증감"
    if op == "per_store":
        return "점포당 월" if column == "est_sales" else f"{base} 점포당 월"
    return base


def full_label(column: str, op: str) -> str:
    if op == "ratio":
        return ratio_full(column)
    return f"{col_label(column)} {OP_LABEL.get(op, op)}"


def basis_text(plan: AnalysisPlan) -> str:
    key = plan.sort_by or ""
    col, _, op = key.partition(".")
    if op == "ratio":
        return ratio_full(col)
    if col in STORE_COLUMNS:
        return COLUMN_LABEL.get(col, col)
    if op == "sum" and col != "est_sales" and col in RATIO_COLUMNS:
        return f"{col_label(col)} 규모"
    return _BASIS.get(op, "값")


def period_text(plan: AnalysisPlan) -> str:
    p = plan.period
    if not (p and p.start and p.end):
        return "전체 기간"

    def q(ym: str) -> str:
        y, m = ym.split("-")
        return quarter_label((int(y), (int(m) - 1) // 3 + 1))

    a, b = q(p.start), q(p.end)
    return a if a == b else f"{a}~{b}"


def subject(plan: AnalysisPlan) -> str:
    parts = ["·".join(plan.regions)] if plan.regions else []
    if plan.industries:
        parts.append("·".join(plan.industries))
    return " ".join(parts) or "전체"


def _row_values(plan_ops, row: CalcRow) -> list[tuple[str, str, str]]:
    """[(짧은이름, 값문자열, 키)] — 계산한 지표 순서가 아니라 규모→증감→점포당 순으로 보여 준다."""
    out = []
    for m in sorted(plan_ops, key=lambda m: _ORDER.get(m.op, 3)):
        key = f"{m.column}.{m.op}"
        out.append((short_label(m.column, m.op), fmt_value(m.op, row.values.get(key), row.notes, m.column), key))
    return out


def list_lines(plan: AnalysisPlan, result: CalcResult, view: RankedView) -> list[str]:
    ops = result.applied.operations
    rows = view.rows
    if not rows:
        return []
    if len(rows) == 1 and not rows[0].group:  # 한 곳의 값: 지표를 한 줄씩
        if len(ops) == 1:
            return []  # 결론 문장이 값을 말한다
        if all(m.op == "ratio" for m in ops):  # 구성비 분포: 항목 이름과 비중만
            return [f"• {item_label(m.column)}: {fmt_value('ratio', rows[0].values.get(f'{m.column}.ratio'), rows[0].notes)}"
                    for m in ops if m.column not in plan.combine]  # 합친 값은 결론 문장이 말한다
        ordered = sorted(ops, key=lambda m: _ORDER.get(m.op, 3))
        return [f"• {full_label(m.column, m.op)}: "
                f"{fmt_value(m.op, rows[0].values.get(f'{m.column}.{m.op}'), rows[0].notes, m.column)}" for m in ordered]
    lines = []
    for i, r in enumerate(rows, 1):
        vals = " · ".join(f"{name} {val}" for name, val, _ in _row_values(ops, r))
        marker = f"{i}." if view.ranked else "•"
        lines.append(f"{marker} {group_label(r)} — {vals}")
    return lines


def headline(plan: AnalysisPlan, result: CalcResult, view: RankedView) -> str:
    ops = result.applied.operations
    when = period_text(plan)
    subj = subject(plan)
    n = len(view.rows)
    direction = "하위" if plan.rank_order == "asc" else "상위"
    if plan.intent in ("ranking", "industry_comparison") and plan.top_n:
        if not view.rows:
            return "비교할 수 있는 결과가 없습니다."
        scope = f"{subj}의 업종 중" if plan.intent == "industry_comparison" else (
            f"{'·'.join(plan.industries)} 기준 " if plan.industries else "")
        unit = "업종" if plan.intent == "industry_comparison" else "상권"
        total = f"전체 {view.total}{'개' if unit == '업종' else '곳'} 중"
        if plan.intent == "industry_comparison" and not plan.regions:
            scope = "전체 지역의 업종 중"
        return f"{scope.strip()}{' ' if scope.strip() else ''}{basis_text(plan)} {direction} {n}개 {unit}입니다 ({total}, {when})."
    if plan.intent == "region_comparison":
        return f"{'·'.join(plan.regions)} 비교입니다 ({when})." + (
            f" 정렬 기준은 {basis_text(plan)}입니다." if plan.sort_by and n > 1 else "")
    if plan.intent == "industry_comparison":
        return f"{subj}의 업종별 {basis_text(plan)}입니다 ({when})."
    if plan.intent == "sales_trend":
        m = ops[0]
        return f"{subj} 분기별 {full_label(m.column, m.op)} 추이입니다 ({when})."
    # lookup
    row = view.rows[0] if view.rows else None
    if row is not None and plan.combine and not row.group:  # 야간처럼 두 칸을 더한 값을 결론으로
        m = next((m for m in ops if m.column in plan.combine), None)
        if m is not None:
            val = fmt_value(m.op, row.values.get(f"{m.column}.{m.op}"), row.notes, m.column)
            return f"{subj}의 {when} {eun_neun(full_label(m.column, m.op))} {val}입니다."
    if row is not None and len(ops) == 1:
        m = ops[0]
        val = fmt_value(m.op, row.values.get(f"{m.column}.{m.op}"), row.notes, m.column)
        return f"{subj}의 {when} {eun_neun(full_label(m.column, m.op))} {val}입니다."
    if ops and all(m.op == "ratio" for m in ops):
        return f"{subj}의 {when} 매출 구성비입니다."
    return f"{subj}의 {when} 성적표입니다."


def startup_block(plan: AnalysisPlan, result: CalcResult, view: RankedView, rank=None) -> tuple[str, list[str]] | None:
    """창업·수입 질문(한 지역·업종 조회)의 답: 결론 한 문장 + 같은 조건에서의 순위 + 증감·합계. 못 만들면 None(기본 형식)."""
    if len(view.rows) != 1:
        return None
    row = view.rows[0]
    ps, sc = row.values.get("est_sales.per_store"), row.values.get("store_count.avg")
    if ps is None or sc is None:
        return None
    head = (f"{eun_neun(subject(plan))} 점포 {fmt_value('avg', sc, [], 'store_count')}, "
            f"한 곳당 월평균 매출 {fmt_value('per_store', ps, [])}입니다 ({period_text(plan)}).")
    lines: list[str] = []
    if rank is not None:
        basis = f"{'·'.join(plan.industries)} 기준" if plan.industries else "전체 업종 기준"
        lines.append(f"• 점포당 월평균: {basis} {rank.total}곳 중 {rank.per_store_rank}위 (높은 순)")
        lines.append(f"• 점포 수: {basis} {rank.total}곳 중 {rank.store_rank}위 (많은 순)")
    gr = row.values.get("est_sales.growth_rate")
    if gr is not None:
        from app.services.planner import _growth_basis_text  # 지연 import: 증감을 무엇과 비교했는지

        lines.append(f"• 매출 증감: {fmt_value('growth_rate', gr, [])} ({_growth_basis_text(plan.period, plan.growth_basis == 'year_over_year')})"
                     if plan.period and plan.period.start and plan.period.end else f"• 매출 증감: {fmt_value('growth_rate', gr, [])}")
    sm = row.values.get("est_sales.sum")
    if sm is not None:
        lines.append(f"• 매출 합계: {fmt_value('sum', sm, [], 'est_sales')}")
    return head, lines


def compose_block(plan: AnalysisPlan, result: CalcResult, view: RankedView) -> tuple[str, list[str]]:
    return headline(plan, result, view), list_lines(plan, result, view)


def insights(plan: AnalysisPlan, result: CalcResult, view: RankedView) -> list[str]:
    """계산 결과에서 코드가 직접 뽑은 관찰 (모델이 말하는 해석이 아니라 항상 맞는 문장).

    예: 상위 5개 중 증감이 늘어난 곳·줄어든 곳의 수, 규모 1위의 증감 방향, 추이의 가장 높은·낮은 분기.
    """
    ops = {f"{m.column}.{m.op}": m for m in result.applied.operations}
    gkey = next((k for k in ops if k.endswith(".growth_rate")), None)
    skey = next((k for k in ops if k.split(".")[0].endswith("_sales") and k.endswith(".sum")), None)
    rows = view.rows
    out: list[str] = []
    multi = plan.intent in ("ranking", "industry_comparison", "region_comparison")
    if multi and len(rows) >= 2 and gkey:
        have = [r for r in rows if r.values.get(gkey) is not None]
        up = sum(1 for r in have if r.values[gkey] > 0)
        down = sum(1 for r in have if r.values[gkey] < 0)
        if have:
            out.append(f"증감은 목록 {len(have)}개 중 {up}개가 늘고 {down}개가 줄었습니다.")
        top = rows[0]
        g = top.values.get(gkey)
        if skey and plan.sort_by == skey and plan.rank_order != "asc" and g is not None and g < 0:
            out.append(f"매출 1위 {eun_neun(group_label(top))} 증감이 {fmt_value('growth_rate', g, [])}로, 규모는 크지만 줄고 있습니다.")
    if plan.intent == "sales_trend" and len(rows) >= 2 and result.applied.operations:
        m = result.applied.operations[0]
        key = f"{m.column}.{m.op}"
        have = [r for r in rows if r.values.get(key) is not None]
        if len(have) >= 2:
            hi = max(have, key=lambda r: r.values[key])
            lo = min(have, key=lambda r: r.values[key])
            out.append(f"가장 높은 분기는 {group_label(hi)}, 가장 낮은 분기는 {group_label(lo)}입니다.")
    rkeys = [k for k in ops if k.endswith(".ratio")]
    if plan.intent == "lookup" and len(rows) == 1 and len(rkeys) > 1 and len(rkeys) == len(ops) and not plan.combine:
        vals = {k: rows[0].values.get(k) for k in rkeys if rows[0].values.get(k) is not None}
        if vals:
            top = max(vals, key=vals.get)
            out.append(f"가장 큰 비중은 {item_label(top.split('.')[0])} {fmt_value('ratio', vals[top], [])}입니다.")
    if plan.intent == "lookup" and len(rows) == 1 and gkey and len(ops) > 1:
        g = rows[0].values.get(gkey)
        if g is not None:
            word = "늘었습니다" if g > 0 else "줄었습니다" if g < 0 else "비슷합니다"
            out.append(f"직전 같은 기간보다 매출이 {word}.")
    return out
