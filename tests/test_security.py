import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

client = TestClient(app)
URL = "/api/dashboard/analyze"
BODY = {"question": "x"}


def setenv(monkeypatch, key, env="development"):
    monkeypatch.setenv("API_KEY", key)
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("CALC_MODE", "mock")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear():
    yield
    get_settings.cache_clear()


def test_missing_key_401(monkeypatch):
    setenv(monkeypatch, "secret-key")
    assert client.post(URL, json=BODY).status_code == 401


def test_wrong_key_401(monkeypatch):
    setenv(monkeypatch, "secret-key")
    assert client.post(URL, json=BODY, headers={"X-API-Key": "nope"}).status_code == 401


def test_correct_key_passes_auth(monkeypatch):
    setenv(monkeypatch, "secret-key")
    r = client.post(URL, json=BODY, headers={"X-API-Key": "secret-key"})
    assert r.status_code != 401  # 인증 통과 (이후 단계 결과는 별도 테스트)


def test_production_without_configured_key_503(monkeypatch):
    setenv(monkeypatch, "", env="production")
    assert client.post(URL, json=BODY, headers={"X-API-Key": "any"}).status_code == 503


def test_dev_without_key_skips_auth(monkeypatch):
    setenv(monkeypatch, "")
    assert client.post(URL, json=BODY).status_code != 401


PROTECTED = ["/api/dashboard/analyze", "/api/chat", "/api/plan", "/api/calc", "/api/analyze"]


@pytest.mark.parametrize("url", PROTECTED)
def test_every_api_requires_key(monkeypatch, url):
    setenv(monkeypatch, "secret-key")
    assert client.post(url, json=BODY).status_code == 401
    assert client.post(url, json=BODY, headers={"X-API-Key": "nope"}).status_code == 401


@pytest.mark.parametrize("url", PROTECTED)
def test_every_api_with_key_passes_auth(monkeypatch, url):
    setenv(monkeypatch, "secret-key")
    r = client.post(url, json={"message": "x", "question": "x"}, headers={"X-API-Key": "secret-key"})
    assert r.status_code != 401


@pytest.mark.parametrize("url", PROTECTED)
def test_every_api_production_without_key_503(monkeypatch, url):
    setenv(monkeypatch, "", env="production")
    assert client.post(url, json=BODY).status_code == 503


def test_other_endpoints_unaffected(monkeypatch):
    setenv(monkeypatch, "secret-key")
    assert client.get("/health").status_code == 200
