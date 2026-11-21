import asyncio
from unittest.mock import AsyncMock

import pytest

from backend import check_ai
from backend.ai_writer import Draft, WritingError
from backend.config import Settings


@pytest.mark.parametrize("error", [None, WritingError(
    "Nhà cung cấp từ chối xác thực.", 503,
    code="AI_AUTHENTICATION_FAILED", upstream_status=401,
)])
def test_check_uses_current_backend_config_and_sanitized_errors(monkeypatch, error):
    writer = AsyncMock()
    writer.parse = AsyncMock(
        side_effect=error,
        return_value=(Draft(content="OK", warnings=[]), 12, 8),
    )
    settings = Settings(
        _env_file=None, openai_api_key="secret-not-for-output",
        openai_base_url="https://provider.example/private-path/v1",
        openai_api_mode="responses", openai_response_format="text",
        openai_model="gpt-6.1-sol",
    )
    captured = []

    def factory(actual_settings):
        captured.append(actual_settings)
        return writer

    monkeypatch.setattr(check_ai, "AIWriter", factory)
    result, exit_code = asyncio.run(check_ai.check_ai(settings))
    assert captured == [settings]
    assert result["api_mode"] == "responses"
    assert result["response_format"] == "text"
    assert result["model"] == "gpt-6.1-sol"
    assert exit_code == (1 if error else 0)
    assert result["ok"] is (error is None)
    if error:
        assert result["code"] == "AI_AUTHENTICATION_FAILED"
        assert result["upstream_status"] == 401
    assert "secret-not-for-output" not in str(result)
    assert "private-path" not in str(result)
    writer.close.assert_awaited_once()


def test_invalid_environment_does_not_print_secret_values(monkeypatch, capsys):
    def invalid_settings():
        Settings(_env_file=None, openai_api_mode="SECRET-INVALID-VALUE")

    monkeypatch.setattr(check_ai, "get_settings", invalid_settings)
    assert check_ai.main([]) == 2
    output = capsys.readouterr().out
    assert "CONFIG_INVALID" in output
    assert "SECRET-INVALID-VALUE" not in output


def test_check_still_validates_output(monkeypatch):
    writer = AsyncMock()
    writer.parse.return_value = (Draft(content="not OK", warnings=[]), 0, 0)
    monkeypatch.setattr(check_ai, "AIWriter", lambda _: writer)
    result, exit_code = asyncio.run(check_ai.check_ai(Settings(_env_file=None)))
    assert exit_code == 1
    assert result["code"] == "AI_CHECK_OUTPUT_INVALID"
    writer.close.assert_awaited_once()


def test_help_does_not_load_credentials_or_call_ai(monkeypatch, capsys):
    def unexpected():
        raise AssertionError("Help must not read credentials or call a provider")

    monkeypatch.setattr(check_ai, "get_settings", unexpected)
    with pytest.raises(SystemExit) as result:
        check_ai.main(["--help"])
    assert result.value.code == 0
    assert "billable" in capsys.readouterr().out
