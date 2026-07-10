import base64
import json
import logging
import os

import httpx
from pydantic import ValidationError

from cv.prompt import SYSTEM_PROMPT, USER_PROMPT
from cv.validator import CVResponse

log = logging.getLogger("ollama")

_base = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
_timeout = float(os.environ.get("OLLAMA_REQUEST_TIMEOUT_SECONDS", "120"))
_response_schema = CVResponse.model_json_schema()


class OllamaError(RuntimeError):
    pass


async def _call(model: str, image_b64: str) -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT, "images": [image_b64]},
        ],
        # Schema-constrained decoding (not just "format": "json") keeps the
        # model inside the exact {"items": [...]} shape instead of drifting
        # into a free-form dict, and terminates cleanly instead of rambling
        # into a runaway generation that gets cut off mid-string.
        "format": _response_schema,
        "stream": False,
        "options": {"num_ctx": 4096, "num_predict": 1024},
    }
    async with httpx.AsyncClient(timeout=_timeout) as client:
        try:
            r = await client.post(f"{_base}/api/chat", json=payload)
        except httpx.HTTPError as e:
            raise OllamaError(f"transport failure: {e}") from e

    if r.status_code != 200:
        raise OllamaError(f"ollama returned {r.status_code}: {r.text[:200]}")

    try:
        body = r.json()
    except ValueError as e:
        raise OllamaError(f"ollama returned non-JSON: {e}") from e

    content = body.get("message", {}).get("content", "")
    if not content:
        raise OllamaError("ollama returned empty content")

    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise OllamaError(f"model output not valid JSON: {e}; content={content[:200]!r}") from e


async def analyze_shelf_image(
    image_bytes: bytes, model: str, fallback_model: str
) -> tuple[CVResponse, str]:
    """
    Call Ollama with the primary model; on JSON/validation failure, retry with the fallback.
    Returns the validated response and the model name that succeeded.
    """
    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    last_err: Exception | None = None
    for attempt_model in (model, fallback_model):
        if not attempt_model:
            continue
        try:
            raw = await _call(attempt_model, image_b64)
            validated = CVResponse.model_validate(raw)
            log.info("ollama %s succeeded: %d items", attempt_model, len(validated.items))
            return validated, attempt_model
        except (OllamaError, ValidationError) as e:
            log.warning("ollama %s failed: %s", attempt_model, e)
            last_err = e
            continue

    raise OllamaError(f"all models failed; last error: {last_err}")
