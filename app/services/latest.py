"""데이터의 최신 분기. C 엔진 /health 에서 읽고(5분 캐시), 못 읽으면 설정값(LATEST_QUARTER)을 쓴다."""
import time

import httpx

from app.core.config import get_settings
from app.services.periods import Quarter, parse_quarter

_cache: dict = {"t": 0.0, "v": None}


def reset_cache() -> None:
    _cache.update(t=0.0, v=None)


async def latest_quarter() -> Quarter:
    s = get_settings()
    now = time.monotonic()
    if _cache["v"] is not None and now - _cache["t"] < s.latest_cache_seconds:
        return _cache["v"]
    value: Quarter | None = None
    if s.calc_mode == "http":
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(s.calc_engine_url.rstrip("/") + "/health")
            value = parse_quarter(str(r.json()["quarters"][-1]))
        except Exception:  # 엔진이 꺼져 있거나 응답이 이상하면 설정값 사용
            value = None
    if value is None:
        return parse_quarter(s.latest_quarter)  # 실패한 값은 캐시하지 않는다
    _cache.update(t=now, v=value)
    return value
