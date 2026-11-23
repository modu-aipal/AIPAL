from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings
from app.schemas.calc import CalcApiResponse
from app.schemas.plan import AnalysisPlan, PlanRequest, PlanResponse
from app.services import ollama, planner
from app.services.calc import (
    MOCK_WARNING,
    CalcIntegrationError,
    Calculator,
    build_request,
    get_calculator,
)
from app.services.calc.errors import CalcEngineError

router = APIRouter(tags=["calc"])


class AnalyzeResponse(BaseModel):
    status: str  # ok | needs_clarification | info
    plan_response: PlanResponse
    calc: CalcApiResponse | None = None


def _http_error(e: CalcIntegrationError) -> HTTPException:
    detail: object = str(e)
    if isinstance(e, CalcEngineError):
        detail = {"error": "calc_engine_error", "engine_error": e.error.model_dump()}
    return HTTPException(status_code=e.status_code, detail=detail)


async def run_calc(plan: AnalysisPlan, calc: Calculator) -> CalcApiResponse:
    try:
        req = build_request(plan, get_settings().calc_dataset_id)
        result = await calc.calculate(req)
    except CalcIntegrationError as e:
        raise _http_error(e) from e
    return CalcApiResponse(
        is_mock=result.is_mock, warning=MOCK_WARNING if result.is_mock else None, result=result
    )


def _calculator() -> Calculator:
    try:
        return get_calculator()
    except CalcIntegrationError as e:
        raise _http_error(e) from e


@router.post("/calc", response_model=CalcApiResponse)
async def calc_from_plan(plan: AnalysisPlan, calc: Calculator = Depends(_calculator)) -> CalcApiResponse:
    """검증된 분석 계획 -> 계산 엔진 호출 (계산은 엔진에서만 수행)."""
    return await run_calc(plan, calc)


async def plan_or_raise(question: str, dataset) -> PlanResponse:
    """질문 -> 계획. 실패는 HTTPException으로 변환 (analyze/dashboard 공용)."""
    try:
        _, pr = await planner.make_plan(question, dataset)
    except ollama.OllamaError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except planner.PlanOutputError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except planner.PlanValidationError as e:
        raise HTTPException(
            status_code=422, detail={"error": "plan_validation_failed", "violations": e.violations}
        ) from e
    return pr


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: PlanRequest, calc: Calculator = Depends(_calculator)) -> AnalyzeResponse:
    """자연어 질문 -> 분석 계획 -> 계산 엔진. 재질문이 필요하면 계산하지 않는다."""
    pr = await plan_or_raise(req.question, req.dataset)
    if pr.status == "info":
        return AnalyzeResponse(status="info", plan_response=pr)
    if pr.status != "ok":
        return AnalyzeResponse(status="needs_clarification", plan_response=pr)
    return AnalyzeResponse(status="ok", plan_response=pr, calc=await run_calc(pr.plan, calc))
