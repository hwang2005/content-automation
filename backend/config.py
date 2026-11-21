from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "Content Studio"
    app_password: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")
    database_url: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str = ""
    openai_api_mode: Literal["auto", "responses", "chat_completions"] = "auto"
    openai_response_format: Literal["json_schema", "json_object", "text"] = "json_schema"
    openai_chat_token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    openai_model: str = "gpt-5-mini"
    openai_timeout_seconds: int = Field(default=120, ge=10, le=300)
    app_origin: str = ""
    generate_requests_per_hour: int = Field(default=30, ge=1, le=1000)
    max_concurrent_generations: int = Field(default=2, ge=1, le=10)

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value):
        # Render values and pasted credentials can include trailing spaces/newlines.
        key = value.get_secret_value() if isinstance(value, SecretStr) else value
        return key.strip() if isinstance(key, str) else key

    @field_validator("openai_base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return ""
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or any(character.isspace() or ord(character) < 32 for character in value)
                or "\\" in value
            ):
                raise ValueError
            # Accessing port also validates malformed/out-of-range port numbers.
            _ = parsed.port
        except ValueError:
            raise ValueError(
                "OPENAI_BASE_URL phải là URL HTTP/HTTPS, không chứa thông tin đăng nhập, query hoặc fragment."
            ) from None
        if parsed.path.endswith(("/chat/completions", "/responses")):
            raise ValueError("OPENAI_BASE_URL phải là URL gốc API (ví dụ https://provider.example/v1), không phải URL endpoint.")
        return value

    @property
    def ai_base_url(self) -> str:
        return self.openai_base_url or "https://api.openai.com/v1"

    @property
    def ai_api_mode(self) -> str:
        if self.openai_api_mode != "auto":
            return self.openai_api_mode
        # Most third-party compatible APIs implement Chat Completions, not Responses.
        return "responses" if urlsplit(self.ai_base_url).hostname == "api.openai.com" else "chat_completions"

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
