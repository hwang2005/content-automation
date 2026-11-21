"""Explicit AI diagnostic. Makes one small logical request (SDK retries may apply).

Run in the SAME environment as the backend: python -m backend.check_ai
This may incur provider charges. Never run automatically in health checks/builds.
"""

import argparse
import asyncio
import json

from pydantic import ValidationError

from backend.ai_writer import AIWriter, Draft, WritingError
from backend.config import Settings, get_settings


async def check_ai(settings: Settings) -> tuple[dict, int]:
    writer = AIWriter(settings)
    context = {
        "api_mode": settings.ai_api_mode,
        "response_format": settings.openai_response_format,
        "model": settings.openai_model,
    }
    try:
        result, input_tokens, output_tokens = await writer.parse(
            Draft,
            'Return only a JSON object with content equal to "OK" and warnings equal to an empty array.',
            {"task": "connection_check"},
            1024,
        )
        if result.content != "OK" or result.warnings:
            raise WritingError("AI phản hồi nhưng không tuân thủ yêu cầu kiểm tra JSON.", code="AI_CHECK_OUTPUT_INVALID")
        return {
            "ok": True, **context, "input_tokens": input_tokens, "output_tokens": output_tokens,
            "detail": "Đã gọi thành công endpoint AI bằng cấu hình backend hiện tại. Chưa kiểm tra Supabase hoặc nguồn web.",
        }, 0
    except WritingError as error:
        # Only sanitized application messages; never print the SDK exception/body.
        return {
            "ok": False, **context, "code": error.code, "upstream_status": error.upstream_status,
            "detail": str(error),
        }, 1
    finally:
        await writer.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check the configured AI endpoint. Makes a small potentially billable request; never run in health checks.")
    parser.parse_args(argv)
    try:
        settings = get_settings()
    except ValidationError:
        # ValidationError includes input values; do not echo secrets from .env.
        print(json.dumps({"ok": False, "code": "CONFIG_INVALID", "detail": "Cấu hình môi trường không hợp lệ. Kiểm tra tên/giá trị biến theo .env.example."}))
        return 2
    result, exit_code = asyncio.run(check_ai(settings))
    # ASCII-escaped JSON also works on Windows terminals using a legacy code page.
    print(json.dumps(result))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
