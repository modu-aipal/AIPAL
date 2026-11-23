from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AIPAL LAB Analysis API"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "info"
    cors_origins: str = "http://localhost:3000"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_timeout_seconds: float = 120
    # 질문 해석(구조화 출력)은 짧아야 정상이다. 넘으면 모델 없이 서버 규칙으로 처리한다.
    plan_timeout_seconds: float = 30
    plan_max_tokens: int = 400
    explain_timeout_seconds: float = 60  # 넘으면 계산 결과를 그대로 나열한 문장으로 대체
    explain_max_tokens: int = 700
    # 모델이 쓰는 해석 문장은 숫자·추천·"없다"만 검사해서 "A가 다른 업종보다 크다" 같은 틀린 비교가 통과할 수 있다.
    # 그래서 기본은 끄고, 코드가 계산 결과에서 뽑은 관찰(insights)만 보여 준다.
    explain_interpretation: bool = False
    api_key: str = ""  # A(대시보드) 인증용. 비어 있으면 개발 환경에서만 인증 생략
    calc_engine_url: str = "http://localhost:8100"
    calc_mode: str = "http"  # http(실제 엔진) | mock(개발/테스트 전용)
    calc_timeout_seconds: float = 30
    calc_dataset_id: str = "commercial_area_v1"
    latest_quarter: str = "2026Q2"  # C 엔진 /health 를 읽지 못할 때 쓰는 최신 분기
    latest_cache_seconds: int = 300
    # 관용 표현의 의미 해석 순서: model_first(모델 > 알려진 표현) | rules_first(알려진 표현 > 모델). eval 점수로 정한다.
    concept_priority: str = "model_first"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()