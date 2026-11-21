from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "Content Studio"
    app_password: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")
    database_url: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-5-mini"
    openai_timeout_seconds: int = Field(default=120, ge=10, le=300)
    app_origin: str = ""
    generate_requests_per_hour: int = Field(default=30, ge=1, le=1000)
    max_concurrent_generations: int = Field(default=2, ge=1, le=10)

    @property
    def production(self) -> bool:
        return self.app_env == "production"

    @property
    def auth_ready(self) -> bool:
        if not self.production:
            return True
        return (
            len(self.app_password.get_secret_value()) >= 12
            and len(self.session_secret.get_secret_value()) >= 32
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
