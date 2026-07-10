"""Grove CV provider — MongoDB's internal GenAI gateway (Azure-backed).

Grove exposes an OpenAI-compatible, vision-capable chat/completions endpoint
authenticated with an `api-key` header. This client mirrors the Ollama client's
contract — `analyze_shelf_image(image_bytes, model, fallback) -> (CVResponse,
str)` — so callers stay provider-agnostic (see `cv/__init__.py`).

The base URL, model, and API key are all provisioned per Grove request, so they
are env-configurable. Local runs use Ollama instead; Grove is the cloud path.
"""
from __future__ import annotations

import base64
import json
import logging
import os

import httpx
from pydantic import ValidationError

from cv.prompt import SYSTEM_PROMPT, USER_PROMPT
from cv.validator import CVResponse

log = logging.getLogger("grove")

_base = os.environ.get(
    "GROVE_BASE_URL",
    "https://grove-gateway-prod.azure-api.net/grove-foundry-prod/openai/v1",
).rstrip("/")
_api_key = os.environ.get("GROVE_API_KEY", "")
_timeout = float(os.environ.get("GROVE_REQUEST_TIMEOUT_SECONDS", "120"))
_max_tokens = int(os.environ.get("GROVE_MAX_COMPLETION_TOKENS", "1024"))


class GroveError(RuntimeError):
    pass


def _data_url(image_bytes: bytes) -> str:
    """Build a `data:` URL, sniffing the MIME type from the magic bytes."""
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif image_bytes[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "image/jpeg"
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def _call(model: str, data_url: str) -> dict:
    if not _api_key:
        raise GroveError("GROVE_API_KEY is not set")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": USER_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        # The prompt fully specifies the {"items": [...]} shape. json_object is
        # portable across Grove's OpenAI-format models, unlike strict
        # json_schema which only the newest GPT builds honour.
        "response_format": {"type": "json_object"},
        "max_completion_tokens": _max_tokens,
    }
    headers = {"api-key": _api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=_timeout) as client:
        try:
            r = await client.post(f"{_base}/chat/completions", json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise GroveError(f"transport failure: {e}") from e

    if r.status_code != 200:
        raise GroveError(f"grove returned {r.status_code}: {r.text[:200]}")

    try:
        body = r.json()
    except ValueError as e:
        raise GroveError(f"grove returned non-JSON: {e}") from e

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise GroveError(f"unexpected grove response shape: {e}; body={str(body)[:200]!r}") from e
    if not content:
        raise GroveError("grove returned empty content")

    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise GroveError(f"model output not valid JSON: {e}; content={content[:200]!r}") from e


async def analyze_shelf_image(
    image_bytes: bytes, model: str, fallback_model: str
) -> tuple[CVResponse, str]:
    """
    Call Grove with the primary model; on JSON/validation failure, retry with
    the fallback. Returns the validated response and the model name that
    succeeded.
    """
    data_url = _data_url(image_bytes)

    last_err: Exception | None = None
    for attempt_model in (model, fallback_model):
        if not attempt_model:
            continue
        try:
            raw = await _call(attempt_model, data_url)
            validated = CVResponse.model_validate(raw)
            log.info("grove %s succeeded: %d items", attempt_model, len(validated.items))
            return validated, attempt_model
        except (GroveError, ValidationError) as e:
            log.warning("grove %s failed: %s", attempt_model, e)
            last_err = e
            continue

    raise GroveError(f"all models failed; last error: {last_err}")
