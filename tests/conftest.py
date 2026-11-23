"""모든 테스트 공통: 개발 PC의 .env 값(CALC_MODE=http, API_KEY 등)에 테스트가 좌우되지 않게 한다."""
import pytest

from app.core.config import get_settings
from app.services import latest


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch):
    monkeypatch.setenv("CALC_MODE", "mock")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("API_KEY", "")
    monkeypatch.setenv("LATEST_QUARTER", "2026Q2")
    monkeypatch.setenv("EXPLAIN_INTERPRETATION", "true")  # 모델 해석 경로도 테스트한다 (운영 기본은 꺼짐)
    get_settings.cache_clear()
    latest.reset_cache()
    yield
    get_settings.cache_clear()
    latest.reset_cache()
