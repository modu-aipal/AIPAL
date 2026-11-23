"""엔진 응답 검증: 규격 일치 + 요청과의 일치 (불일치면 CalcResponseError)."""
from app.schemas.calc import CalcRequest, CalcResult
from app.services.calc.errors import CalcResponseError


def verify_result(req: CalcRequest, res: CalcResult) -> None:
    def bad(msg: str):
        raise CalcResponseError(f"계산 엔진 응답 검증 실패: {msg}")

    if res.request_id != req.request_id:
        bad("request_id 불일치")
    if res.dataset_id != req.dataset_id:
        bad("dataset_id 불일치")
    if res.status != "ok":
        return
    a = res.applied
    if a.operations != req.metrics:
        bad("적용된 연산이 요청과 다름")
    if a.group_by != req.group_by:
        bad("적용된 group_by가 요청과 다름")
    if a.filters != req.filters:
        bad("적용된 필터가 요청과 다름")
    if a.period != req.period:
        bad("적용된 기간이 요청과 다름")
    if a.baseline_period != (req.growth.baseline_period if req.growth else None):
        bad("비교 기준 기간이 요청과 다름")
    need_cols = {m.column for m in req.metrics} | set(req.group_by) | {f.column for f in req.filters}
    if not need_cols <= set(a.columns_used):
        bad("columns_used에 요청 컬럼이 빠져 있음")
    keys = {f"{m.column}.{m.op}" for m in req.metrics}
    growth_keys = {f"{m.column}.{m.op}" for m in req.metrics if m.op in ("growth_rate", "ratio", "per_store")}
    for row in res.results:
        if set(row.group) != set(req.group_by):
            bad(f"결과 그룹 키가 group_by와 다름: {sorted(row.group)}")
        if set(row.values) != keys:
            bad(f"결과 값 키가 요청 지표와 다름: {sorted(row.values)}")
        for k, v in row.values.items():
            if v is None and (k not in growth_keys or not row.notes):
                bad(f"{k}: null 값은 growth_rate·ratio·per_store 이며 notes 사유가 있을 때만 허용")
    if res.results and sum(r.rows_used for r in res.results) > res.rows_used:
        bad("그룹별 rows_used 합이 전체 rows_used보다 큼")
