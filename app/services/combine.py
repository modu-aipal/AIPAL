"""여러 칸을 더해 보여 주는 값 (예: 야간 = 밤 21~24시 + 새벽 0~6시).

계산은 모두 C 엔진이 했고, 여기서는 엔진이 준 같은 종류의 두 값을 더하기만 한다 (분모가 같은 비중이거나 매출 합계라서 더해도 된다).
하나라도 계산할 수 없으면 합친 값도 None 이다. 합친 항목은 결과의 지표 목록 맨 앞에 붙는다.
"""
from app.schemas.calc import CalcMetric, CalcResult
from app.schemas.plan import AnalysisPlan


def apply_combine(plan: AnalysisPlan, result: CalcResult) -> CalcResult:
    if not plan.combine or result.status != "ok" or result.applied is None:
        return result
    ops = list(result.applied.operations)
    added: list[CalcMetric] = []
    for key, parts in plan.combine.items():
        op = next((m.op for m in ops if m.column in parts), None)
        if op is None or any(not any(m.column == p and m.op == op for m in ops) for p in parts):
            continue
        for row in result.results:
            vals = [row.values.get(f"{p}.{op}") for p in parts]
            row.values[f"{key}.{op}"] = None if any(v is None for v in vals) else sum(vals)
        added.append(CalcMetric(column=key, op=op))
    result.applied.operations = added + ops
    return result
