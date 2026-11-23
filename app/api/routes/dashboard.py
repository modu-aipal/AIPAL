from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.routes.calc import _calculator, plan_or_raise, run_calc
from app.core.security import require_api_key
from app.schemas.calc import CalcError
from app.schemas.dashboard import DashboardRequest, DashboardResponse
from app.services import explain, ollama
from app.services.calc import Calculator
from app.services.dataset import area_ids

router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_api_key)])


@router.post("/dashboard/analyze", response_model=DashboardResponse)
async def dashboard_analyze(
    req: DashboardRequest, response: Response, calc: Calculator = Depends(_calculator)
) -> DashboardResponse:
    """질문 -> 분석 계획 -> 계산 엔진 -> 설명. A 담당 대시보드용 {area, sql, text}."""
    pr = await plan_or_raise(req.question, None)
    if pr.status != "ok":
        raise HTTPException(
            status_code=422,
            detail={
                "error": "needs_clarification",
                "clarification_question": pr.clarification_question,
                "missing_fields": pr.missing_fields,
                "reason": pr.reason,
                "suggested_questions": pr.suggested_questions,  # 서버가 검증한 '이렇게 물어보세요'
            },
        )
    api = await run_calc(pr.plan, calc)
    result = api.result
    if result.status != "ok":  # Mock/엔진이 오류 결과를 200으로 돌려준 경우
        err: CalcError = result.error
        raise HTTPException(
            status_code=502, detail={"error": "calc_engine_error", "engine_error": err.model_dump()}
        )
    try:
        text, _ = await explain.generate_explanation(req.question, pr.plan, result)
    except ollama.OllamaError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    if result.is_mock:  # 실제 분석으로 오인되지 않도록 본문과 헤더에 표시
        text = explain.MOCK_PREFIX + text
        response.headers["X-Is-Mock"] = "true"
        response.headers["X-Data-Source"] = result.data_source or "MOCK"
    return DashboardResponse(
        area=area_ids(pr.plan.regions), sql=result.executed_sql or "", text=text
    )
