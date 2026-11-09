from functools import lru_cache
from pathlib import Path
from pydantic import model_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), extra="ignore")
    app_name: str = "HealthFlow"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./healthflow.db"
    jwt_secret_key: str = "development-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "healthflow"
    jwt_audience: str = "healthflow-api"
    access_token_expire_minutes: int = 60
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    forecast_model_mode: str = "artifact"
    forecast_model_dir: Path = Path("model_artifacts/emergency_admissions_forecast")
    forecast_model_file: str = "healthflow_emergency_admissions_pipeline.joblib"
    forecast_data_dir: Path = Path("dataset/processed/nhs_england_ae")
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen3:8b"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_temperature: float = 0
    ollama_request_timeout_seconds: int = 120
    intelligence_provider: str = "groq"
    groq_api_key: str = Field(default="", repr=False)
    groq_model: str = "openai/gpt-oss-120b"
    rag_embedding_model: str = "BAAI/bge-small-en-v1.5"
    rag_cache_dir: Path = Path(".rag_cache")
    upload_dir: Path = Path("uploads")
    max_policy_file_bytes: int = 10 * 1024 * 1024
    demo_admin_email: str = "admin@healthflow.local"
    demo_admin_password: str = "ChangeMe123!"
    seed_demo_admin: bool = True
    log_level: str = "INFO"

    @model_validator(mode="after")
    def reject_unsafe_production_settings(self) -> "Settings":
        if self.app_env.lower() != "production":
            return self
        errors = []
        if len(self.jwt_secret_key.encode()) < 32 or "change" in self.jwt_secret_key.lower():
            errors.append("JWT_SECRET_KEY must be a random secret of at least 32 bytes")
        if self.seed_demo_admin:
            errors.append("SEED_DEMO_ADMIN must be false")
        if any("localhost" in origin or "127.0.0.1" in origin for origin in self.cors_origin_list):
            errors.append("CORS_ORIGINS must contain only approved HTTPS origins")
        if errors:
            raise ValueError("Unsafe production configuration: " + "; ".join(errors))
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
