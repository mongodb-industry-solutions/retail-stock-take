"""Grove CV provider (cloud). Mirrors the Ollama client's contract —
`analyze_shelf_image(image_bytes, model, fallback) -> (CVResponse, str)` — so
callers stay provider-agnostic (see `cv/__init__.py`). Base URL, model, and key
are env-configurable.
"""

from __future__ import annotations

import base64
import json
import logging
import os

import httpx
from pydantic import ValidationError

from cv.json_utils import loads_tolerant
from cv.prompt import SYSTEM_PROMPT, USER_PROMPT
from cv.validator import CVResponse

log = logging.getLogger("grove")

_base = os.environ.get(
    "GROVE_BASE_URL",
    "https://ai-gateway.corp.mongodb.com/openai/v1",
).rstrip("/")
_api_key = os.environ.get("GROVE_API_KEY", "")
_timeout = float(os.environ.get("GROVE_REQUEST_TIMEOUT_SECONDS", "120"))
_max_tokens = int(os.environ.get("GROVE_MAX_COMPLETION_TOKENS", "1024"))
# Bounded same-model retries (mirrors the Ollama client): one malformed
# generation shouldn't fail the capture.
_max_attempts = int(os.environ.get("CV_MAX_ATTEMPTS", "2"))


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
        # portable across the gateway's models, unlike strict json_schema which
        # only the newest GPT builds honour.
        "response_format": {"type": "json_object"},
        "max_completion_tokens": _max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=_timeout) as client:
        try:
            r = await client.post(
                f"{_base}/chat/completions", json=payload, headers=headers
            )
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
        raise GroveError(
            f"unexpected grove response shape: {e}; body={str(body)[:200]!r}"
        ) from e
    if not content:
        raise GroveError("grove returned empty content")

    try:
        return loads_tolerant(content)
    except json.JSONDecodeError as e:
        raise GroveError(
            f"model output not valid JSON: {e}; content={content[:200]!r}"
        ) from e


async def analyze_shelf_image(
    image_bytes: bytes, model: str, fallback_model: str
) -> tuple[CVResponse, str]:
    """
    Call Grove with the primary model, retrying it a bounded number of times on
    JSON/validation failure; then retry once with the fallback (if configured).
    Returns the validated response and the model name that succeeded.
    """
    data_url = _data_url(image_bytes)

    plan: list[tuple[str, int]] = [(model, _max_attempts)]
    if fallback_model:
        plan.append((fallback_model, 1))

    last_err: Exception | None = None
    for attempt_model, attempts in plan:
        if not attempt_model:
            continue
        for attempt in range(1, attempts + 1):
            try:
                raw = await _call(attempt_model, data_url)
                validated = CVResponse.model_validate(raw)
                log.info(
                    "grove %s succeeded: %d items", attempt_model, len(validated.items)
                )
                return validated, attempt_model
            except (GroveError, ValidationError) as e:
                log.warning(
                    "grove %s attempt %d/%d failed: %s",
                    attempt_model,
                    attempt,
                    attempts,
                    e,
                )
                last_err = e
                continue

    raise GroveError(f"all attempts failed; last error: {last_err}")
