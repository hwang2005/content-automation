import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError

from backend import ai_writer
from backend.ai_writer import AIWriter, Analysis, Draft, WritingError
from backend.config import Settings
from backend.extractor import SourcePage


def settings_for(**overrides):
    values = {
        "openai_api_key": "sk-provider-test", "openai_model": "compatible-test-model",
        "openai_base_url": "https://provider.example/api/v1", "openai_api_mode": "auto",
        "openai_response_format": "json_schema", "openai_chat_token_parameter": "max_tokens",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def mock_writer(monkeypatch, handler, **settings):
    def client_factory(**options):
        # Preserve all real initialization arguments so requests test base_url,
        # authentication and serialization through the actual OpenAI SDK.
        options["max_retries"] = 0
        return AsyncOpenAI(
            **options, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )

    monkeypatch.setattr(ai_writer, "AsyncOpenAI", client_factory)
    return AIWriter(settings_for(**settings))


def chat_response(content='{"content":"Bài thử 🎯","warnings":[]}', **overrides):
    result = {
        "id": "chatcmpl_test", "object": "chat.completion", "created": 1780000000,
        "model": "compatible-test-model",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {
            "role": "assistant", "content": content,
        }}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160},
    }
    result.update(overrides)
    return result


def responses_result(content='{"content":"Bài thử 🎯","warnings":[]}'):
    return {
        "id": "resp_test", "object": "response", "created_at": 1780000000,
        "model": "compatible-test-model", "status": "completed",
        "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                    "status": "completed", "content": [
                        {"type": "output_text", "text": content, "annotations": []},
                    ]}],
        "usage": {"input_tokens": 120, "output_tokens": 40, "total_tokens": 160},
        "tools": [], "parallel_tool_calls": False, "tool_choice": "auto",
    }


@pytest.mark.parametrize(("url", "mode", "expected"), [
    ("", "auto", "responses"),
    ("https://api.openai.com/v1/", "auto", "responses"),
    ("https://provider.example/api/v1/", "auto", "chat_completions"),
    ("http://127.0.0.1:1234/v1", "auto", "chat_completions"),
    ("https://provider.example/api/v1", "responses", "responses"),
    ("", "chat_completions", "chat_completions"),
])
def test_api_mode_and_base_url_defaults(url, mode, expected):
    settings = settings_for(openai_base_url=url, openai_api_mode=mode)
    assert settings.ai_api_mode == expected
    assert settings.ai_base_url == (url.rstrip("/") or "https://api.openai.com/v1")


@pytest.mark.parametrize("url", [
    "ftp://provider.example/v1", "provider.example/v1", "https://",
    "https://user:password@provider.example/v1", "https://provider.example/v1?key=secret",
    "https://provider.example/v1#token", "https://provider.example:bad/v1",
    "https://provider.example:70000/v1", "https://provider.example/white space",
    "https://provider.example\\evil", "https://provider.example/v1/chat/completions",
    "https://provider.example/v1/responses/",
])
def test_invalid_base_url_is_rejected_before_requests(url):
    with pytest.raises(ValidationError):
        settings_for(openai_base_url=url)


def test_provider_configuration_reads_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://configured.example/gateway/v1/")
    monkeypatch.setenv("OPENAI_API_KEY", "provider-env-key")
    monkeypatch.setenv("OPENAI_MODEL", "vendor/model-id")
    monkeypatch.setenv("OPENAI_API_MODE", "chat_completions")
    monkeypatch.setenv("OPENAI_RESPONSE_FORMAT", "json_object")
    monkeypatch.setenv("OPENAI_CHAT_TOKEN_PARAMETER", "max_completion_tokens")
    settings = Settings(_env_file=None)
    assert settings.ai_base_url == "https://configured.example/gateway/v1"
    assert settings.openai_api_key.get_secret_value() == "provider-env-key"
    assert settings.openai_model == "vendor/model-id"
    assert settings.ai_api_mode == "chat_completions"
    assert settings.openai_response_format == "json_object"
    assert settings.openai_chat_token_parameter == "max_completion_tokens"


def test_key_whitespace_is_normalized():
    settings = settings_for(openai_api_key="  sk-provider-test\r\n")
    assert settings.openai_api_key.get_secret_value() == "sk-provider-test"


@pytest.mark.parametrize("key", ['Bearer sk-secret', '"sk-secret"', "sk-secret\nother"])
def test_invalid_key_format_does_not_send_credentials(monkeypatch, key):
    async def run():
        calls = []
        writer = mock_writer(monkeypatch, lambda request: calls.append(request), openai_api_key=key)
        try:
            with pytest.raises(WritingError) as error:
                await writer.parse(Draft, "Test", {}, 700)
            assert error.value.code == "AI_KEY_FORMAT_INVALID"
            assert not calls
        finally:
            await writer.close()
    asyncio.run(run())


@pytest.mark.parametrize(("status", "body", "code"), [
    (401, {"code": "INVALID_API_KEY", "message": "PRIVATE"}, "AI_AUTHENTICATION_FAILED"),
    (403, {"error": {"message": "PRIVATE"}}, "AI_ACCESS_DENIED"),
    (404, {"error": {"code": "model_not_found"}}, "AI_MODEL_UNAVAILABLE"),
    (404, {"message": "PRIVATE"}, "AI_ENDPOINT_UNAVAILABLE"),
    (400, {"error": {"param": "response_format"}}, "AI_REQUEST_REJECTED"),
    (400, {"error": {"param": {"secret": "PRIVATE"}, "code": ["PRIVATE"]}}, "AI_REQUEST_REJECTED"),
])
def test_structured_provider_error_diagnosis(monkeypatch, status, body, code):
    async def run():
        writer = mock_writer(monkeypatch, lambda _: httpx.Response(status, json=body))
        try:
            with pytest.raises(WritingError) as error:
                await writer.parse(Draft, "Test", {}, 700)
            assert error.value.code == code
            assert error.value.upstream_status == status
            assert "PRIVATE" not in str(error.value)
        finally:
            await writer.close()
    asyncio.run(run())


@pytest.mark.parametrize("response_format", ["json_schema", "json_object", "text"])
@pytest.mark.parametrize("token_parameter", ["max_tokens", "max_completion_tokens"])
def test_chat_endpoint_request_and_validated_result(monkeypatch, response_format, token_parameter):
    async def run():
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=chat_response())

        writer = mock_writer(
            monkeypatch, handler, openai_response_format=response_format,
            openai_chat_token_parameter=token_parameter,
        )
        try:
            result, input_tokens, output_tokens = await writer.parse(
                Draft, "Viết bài tiếng Việt", {"text": "Thông tin nguồn"}, 700
            )
            assert result.content == "Bài thử 🎯" and result.warnings == []
            assert (input_tokens, output_tokens) == (120, 40)
            assert len(calls) == 1
            request = calls[0]
            assert str(request.url) == "https://provider.example/api/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer sk-provider-test"
            body = json.loads(request.content)
            assert body["model"] == "compatible-test-model"
            assert body[token_parameter] == 700
            assert ("max_tokens" in body) != ("max_completion_tokens" in body)
            assert not {"store", "input", "text", "max_output_tokens", "tools"} & body.keys()
            assert body["messages"][0]["role"] == "system"
            assert "Thông tin nguồn" in body["messages"][1]["content"]
            if response_format == "json_schema":
                response_schema = body["response_format"]["json_schema"]
                assert response_schema["strict"] is True
                assert response_schema["schema"]["additionalProperties"] is False
                assert response_schema["schema"]["required"] == ["content", "warnings"]
            else:
                assert "JSON Schema" in body["messages"][0]["content"]
                if response_format == "json_object":
                    assert body["response_format"] == {"type": "json_object"}
                else:
                    assert "response_format" not in body
        finally:
            await writer.close()
    asyncio.run(run())


@pytest.mark.parametrize("response_format", ["json_schema", "json_object", "text"])
def test_custom_responses_endpoint_preserves_prefix(monkeypatch, response_format):
    async def run():
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=responses_result())

        writer = mock_writer(monkeypatch, handler, openai_api_mode="responses", openai_response_format=response_format)
        try:
            result, input_tokens, output_tokens = await writer.parse(Draft, "Test", {}, 700)
            assert result.content == "Bài thử 🎯"
            assert (input_tokens, output_tokens) == (120, 40)
            assert str(calls[0].url) == "https://provider.example/api/v1/responses"
            body = json.loads(calls[0].content)
            assert body["store"] is False
            assert body["max_output_tokens"] == 700
            assert not {"messages", "max_tokens", "max_completion_tokens", "response_format"} & body.keys()
            if response_format == "json_schema":
                assert body["text"]["format"]["type"] == "json_schema"
            elif response_format == "json_object":
                assert body["text"]["format"] == {"type": "json_object"}
            else:
                assert "text" not in body
        finally:
            await writer.close()
    asyncio.run(run())


def test_chat_accepts_full_json_fence_and_missing_usage(monkeypatch):
    async def run():
        body = chat_response('```json\n{"content":"Bài thử ✨","warnings":[]}\n```', usage=None)
        writer = mock_writer(monkeypatch, lambda _: httpx.Response(200, json=body), openai_response_format="text")
        try:
            result, input_tokens, output_tokens = await writer.parse(Draft, "Test", {}, 700)
            assert result.content == "Bài thử ✨"
            assert (input_tokens, output_tokens) == (0, 0)
        finally:
            await writer.close()
    asyncio.run(run())


@pytest.mark.parametrize("body", [
    chat_response("not a JSON object"),
    chat_response('{"content":"Missing warnings"}'),
    chat_response('{"content":123,"warnings":[]}'),
    chat_response('{"content":"Bài","warnings":[],"unexpected":"value"}'),
    chat_response('{"content":"Bài","warnings":"not-a-list"}'),
    chat_response(choices=[]),
    chat_response(choices=[{"index": 0, "finish_reason": "length", "message": {"role": "assistant", "content": '{"content":"valid JSON but incomplete","warnings":[]}'}}]),
    chat_response(choices=[{"index": 0, "finish_reason": "content_filter", "message": {"role": "assistant", "content": None}}]),
    chat_response(choices=[{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": None, "refusal": "refused"}}]),
    chat_response(choices=[{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": []}}]),
    chat_response(choices=[{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": None}}]),
    {"result": "A different, non-OpenAI envelope"},
])
def test_bad_or_incomplete_chat_results_fail_safely(monkeypatch, body):
    async def run():
        writer = mock_writer(monkeypatch, lambda _: httpx.Response(200, json=body))
        try:
            with pytest.raises(WritingError) as error:
                await writer.parse(Draft, "Test", {}, 700)
            assert error.value.status_code == 502
        finally:
            await writer.close()
    asyncio.run(run())


@pytest.mark.parametrize(("http_status", "expected_status"), [
    (400, 503), (401, 503), (403, 503), (404, 503), (405, 503),
    (422, 503), (429, 429), (500, 502), (501, 503),
])
def test_provider_errors_do_not_leak_details_or_switch_endpoint(monkeypatch, http_status, expected_status):
    async def run():
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(http_status, json={"error": {"message": "PRIVATE provider debug / API KEY / prompt"}})

        writer = mock_writer(monkeypatch, handler)
        try:
            with pytest.raises(WritingError) as error:
                await writer.parse(Draft, "Test", {}, 700)
            assert error.value.status_code == expected_status
            assert "PRIVATE" not in str(error.value)
            assert len(calls) == 1
            assert calls[0].url.path.endswith("/chat/completions")
        finally:
            await writer.close()
    asyncio.run(run())


def test_compatible_provider_runs_full_select_extract_and_write(monkeypatch):
    async def run():
        payloads = []
        contents = iter([
            {"format_id": "event-format", "reason": "Nguồn là hội thảo.", "confidence": 0.9,
             "facts": [{"label": "Tên", "value": "Workshop AI", "source_id": "source_1", "quote": "Workshop AI dành cho sinh viên"}], "warnings": []},
            {"content": "🎯 Workshop AI\n\nDành cho các bạn sinh viên.", "warnings": []},
        ])

        def handler(request):
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json=chat_response(json.dumps(next(contents), ensure_ascii=False)))

        writer = mock_writer(monkeypatch, handler, openai_response_format="json_object")
        try:
            result = await writer.write(
                {"name": "Project"},
                [{"id": "event-format", "name": "Hội thảo", "description": "Sự kiện một buổi",
                  "structure": "Tiêu đề → thông tin", "writing_guide": "Tiếng Việt", "samples": ["Mẫu cũ"], "detection_keywords": ["workshop"]}],
                [SourcePage("source_1", "Workshop", None, "Workshop AI dành cho sinh viên.")], "",
            )
            assert result.format["id"] == "event-format"
            assert "🎯" in result.content
            assert result.input_tokens == 240 and result.output_tokens == 80
            assert len(result.analysis.facts) == 1
            assert len(payloads) == 2
            assert payloads[0]["model"] == payloads[1]["model"] == "compatible-test-model"
            assert "source_1" in payloads[1]["messages"][1]["content"]
            # Nested structured fields also have strict schema definitions.
            assert Analysis.model_json_schema()["$defs"]["Fact"]["additionalProperties"] is False
        finally:
            await writer.close()
    asyncio.run(run())
