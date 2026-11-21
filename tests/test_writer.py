import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncOpenAI

from backend.ai_writer import (
    AIWriter,
    Analysis,
    Draft,
    Fact,
    WritingError,
    clean_plain_text,
    verified_facts,
)
from backend.config import Settings
from backend.extractor import SourcePage


def sources():
    return [SourcePage("source_1", "Workshop AI", None, "Workshop AI diễn ra ngày 30/12/2026. Tham dự miễn phí.")]


def analysis(format_id="format-1"):
    return Analysis(format_id=format_id, reason="Phù hợp hội thảo", confidence=0.5, facts=[
        Fact(label="Tên", value="Workshop AI", source_id="source_1", quote="Workshop AI diễn ra ngày 30/12/2026"),
        Fact(label="Học phí", value="10 USD", source_id="source_1", quote="Completely fabricated quote"),
    ], warnings=[])


def test_quote_verification_drops_missing_or_wrong_sources():
    facts, warnings = verified_facts(analysis(), sources())
    assert len(facts) == 1
    assert warnings


def test_plain_text_preserves_emoji_and_hashtags():
    value = "# Tiêu đề\n\n**Workshop** 🎯\n- Miễn phí\n[Đăng ký](https://example.org)\n#Workshop"
    output = clean_plain_text(value)
    assert "**" not in output
    assert "🎯" in output and "#Workshop" in output
    assert "Đăng ký: https://example.org" in output
    assert "• Miễn phí" in output
    assert clean_plain_text("<p>Bài viết 🎯</p>") == "Bài viết 🎯"


def test_writer_chooses_only_project_format_and_tracks_usage():
    async def run():
        writer = AIWriter(Settings(_env_file=None, openai_api_key=""))
        writer.parse = AsyncMock(side_effect=[(analysis(), 100, 200), (Draft(content="**Bài mới** 🎯", warnings=[]), 300, 400)])
        formats = [{"id": "format-1", "name": "Hội thảo", "description": "Sự kiện", "structure": "Tiêu đề, thời gian", "writing_guide": "Tiếng Việt", "samples": ["Mẫu cũ"], "detection_keywords": ["workshop"]}]
        result = await writer.write({"name": "Project"}, formats, sources(), "")
        assert result.content == "Bài mới 🎯"
        assert result.input_tokens == 400 and result.output_tokens == 600
        assert len(result.analysis.facts) == 1
        assert any("chưa chắc chắn" in warning for warning in result.warnings)
        generation_payload = writer.parse.await_args_list[1].args[2]
        assert len(generation_payload["facts"]) == 1
        assert generation_payload["format"]["samples"] == ["Mẫu cũ"]
        assert "sources" not in generation_payload
    asyncio.run(run())


def test_unknown_format_never_falls_back_to_another_project():
    async def run():
        writer = AIWriter(Settings(_env_file=None, openai_api_key=""))
        writer.parse = AsyncMock(return_value=(analysis("another-project-id"), 0, 0))
        with pytest.raises(WritingError, match="Không có dạng bài"):
            await writer.write({}, [], sources(), "")
    asyncio.run(run())


def test_no_grounded_facts_fails_instead_of_fabricating():
    async def run():
        writer = AIWriter(Settings(_env_file=None, openai_api_key=""))
        invalid = analysis()
        invalid.facts = invalid.facts[1:]
        writer.parse = AsyncMock(return_value=(invalid, 0, 0))
        with pytest.raises(WritingError, match="có căn cứ"):
            await writer.write({}, [{"id": "format-1", "name": "Hội thảo", "description": "Sự kiện", "detection_keywords": [], "structure": "Tiêu đề", "writing_guide": "Tiếng Việt"}], sources(), "")
    asyncio.run(run())


def test_openai_sdk_response_contract_without_network():
    async def run():
        received = []

        def handler(request):
            received.append(json.loads(request.content))
            return httpx.Response(200, json={
                "id": "resp_test", "object": "response", "created_at": 1780000000,
                "model": "gpt-5-mini", "status": "completed",
                "output": [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": json.dumps({"content": "Bài thử 🎯", "warnings": []}), "annotations": []}]}],
                "usage": {"input_tokens": 120, "output_tokens": 40, "total_tokens": 160},
                "parallel_tool_calls": False, "tools": [], "tool_choice": "auto",
            })

        writer = AIWriter(Settings(_env_file=None, openai_api_key=""))
        writer.client = AsyncOpenAI(api_key="sk-fake", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            result, in_tokens, out_tokens = await writer.parse(Draft, "Test", {"text": "Example"}, 500)
            assert result.content == "Bài thử 🎯"
            assert (in_tokens, out_tokens) == (120, 40)
            assert received[0]["store"] is False
            assert received[0]["text"]["format"]["strict"] is True
        finally:
            await writer.close()
    asyncio.run(run())
