"""Gemini 响应中间件：将 fileData (URL) 自动转换为 inlineData (base64)。

仅对 Gemini 格式接口生效：
- /models/{model}:generateContent
- /v1beta/models/{model}:generateContent
- /models/{model}:streamGenerateContent
- /v1beta/models/{model}:streamGenerateContent
"""

import base64
import json
import re
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from curl_cffi.requests import AsyncSession

from ..core.logger import debug_logger


_GEMINI_PATH_RE = re.compile(
    r"/(v1beta/)?models/[^/]+(%3A|:)(generateContent|streamGenerateContent)"
)


def _is_gemini_path(path: str) -> bool:
    return bool(_GEMINI_PATH_RE.search(path))


async def _download_image_as_base64(url: str) -> Optional[tuple[str, str]]:
    """下载图片并返回 (mime_type, base64_data)，失败返回 None。"""
    try:
        async with AsyncSession() as session:
            response = await session.get(
                url,
                timeout=60,
                headers={
                    "Accept": "image/*,*/*;q=0.8",
                    "Referer": "https://labs.google/",
                },
                impersonate="chrome120",
                verify=False,
            )
            if response.status_code != 200 or not response.content:
                debug_logger.log_warning(
                    f"[GeminiMiddleware] 图片下载失败: status={response.status_code}, url={url[:80]}..."
                )
                return None

            content = response.content
            # 检测 mime type
            if content.startswith(b"\xff\xd8\xff"):
                mime = "image/jpeg"
            elif content.startswith(b"\x89PNG\r\n\x1a\n"):
                mime = "image/png"
            elif content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
                mime = "image/gif"
            elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
                mime = "image/webp"
            else:
                mime = "image/png"

            return mime, base64.b64encode(content).decode("ascii")
    except Exception as e:
        debug_logger.log_warning(f"[GeminiMiddleware] 图片下载异常: {e}")
        return None


async def _convert_parts(parts: list) -> list:
    """将 parts 中的 fileData 转换为 inlineData。"""
    new_parts = []
    for part in parts:
        if isinstance(part, dict) and "fileData" in part:
            file_data = part["fileData"]
            uri = file_data.get("fileUri", "")
            mime = file_data.get("mimeType", "image/png")

            # 只转换图片类型的 fileData
            if mime.startswith("image/") and uri.startswith("http"):
                result = await _download_image_as_base64(uri)
                if result:
                    new_parts.append({
                        "inlineData": {
                            "mimeType": result[0],
                            "data": result[1],
                        }
                    })
                    continue

            # 非图片或下载失败，保留原样
            new_parts.append(part)
        else:
            new_parts.append(part)
    return new_parts


async def _transform_gemini_payload(data: dict) -> dict:
    """转换完整的 Gemini 响应 payload。"""
    candidates = data.get("candidates", [])
    for candidate in candidates:
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        if parts:
            content["parts"] = await _convert_parts(parts)
    return data


async def _transform_stream_line(line: str) -> str:
    """转换流式响应中的单行 SSE data。"""
    if not line.startswith("data: "):
        return line

    payload_text = line[6:].strip()
    if payload_text == "[DONE]":
        return line

    try:
        payload = json.loads(payload_text)
        transformed = await _transform_gemini_payload(payload)
        return f"data: {json.dumps(transformed, ensure_ascii=False)}\n\n"
    except (json.JSONDecodeError, Exception):
        return line


class GeminiInlineDataMiddleware(BaseHTTPMiddleware):
    """拦截 Gemini 响应，将 fileData URL 转为 inlineData base64。"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if not _is_gemini_path(path):
            return await call_next(request)

        response = await call_next(request)

        content_type = response.headers.get("content-type", "")

        # 流式响应
        if "text/event-stream" in content_type:
            original_body = b""
            async for chunk in response.body_iterator:
                if isinstance(chunk, str):
                    original_body += chunk.encode("utf-8")
                else:
                    original_body += chunk

            lines = original_body.decode("utf-8").split("\n\n")
            transformed_lines = []
            for line in lines:
                line = line.strip()
                if line:
                    transformed_lines.append(await _transform_stream_line(line))

            async def generate():
                for tl in transformed_lines:
                    if not tl.endswith("\n\n"):
                        yield tl + "\n\n"
                    else:
                        yield tl

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # 非流式 JSON 响应
        if "application/json" in content_type:
            body = b""
            async for chunk in response.body_iterator:
                if isinstance(chunk, str):
                    body += chunk.encode("utf-8")
                else:
                    body += chunk

            try:
                data = json.loads(body)
                transformed = await _transform_gemini_payload(data)
                new_body = json.dumps(transformed, ensure_ascii=False).encode("utf-8")
                return Response(
                    content=new_body,
                    status_code=response.status_code,
                    media_type="application/json",
                )
            except (json.JSONDecodeError, Exception):
                return Response(
                    content=body,
                    status_code=response.status_code,
                    media_type="application/json",
                )

        return response
