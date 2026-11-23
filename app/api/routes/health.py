from fastapi import APIRouter

from app import __version__
from app.core.config import get_settings
from app.schemas.common import HealthResponse
from app.services.dataset import REGIONS

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    s = get_settings()
    return HealthResponse(
        app=s.app_name, env=s.app_env, version=__version__, ollama_model=s.ollama_model,
        regions=list(REGIONS),
    )