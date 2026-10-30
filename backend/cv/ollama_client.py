import base64
import json
import logging
import os

import httpx
from pydantic import ValidationError

from cv.json_utils import loads_tolerant
from cv.prompt import SYSTEM_PROMPT, USER_PROMPT
from cv.validator import CVResponse

log = logging.getLogger("ollama")

_base = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
_timeout = float(os.environ.get("OLLAMA_REQUEST_TIMEOUT_SECONDS", "120"))
_response_schema = CVResponse.model_json_schema()
# Bounded same-model retries: a single malformed/truncated generation is common
# for small VLMs, so retry the primary before giving up on the capture.
_max_attempts = int(os.environ.get("CV_MAX_ATTEMPTS", "2"))
# Generation bounds. A single shelf photo tokenizes into ~4k visual tokens, so
# num_ctx must be well above that (4096 rejects the request). num_predict caps
# the (schema-constrained) output; both are env-tunable per host.
_num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))
_num_predict = int(os.environ.get("OLLAMA_NUM_PREDICT", "1024"))


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
        "options": {"num_ctx": _num_ctx, "num_predict": _num_predict},
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
        return loads_tolerant(content)
    except json.JSONDecodeError as e:
        raise OllamaError(
            f"model output not valid JSON: {e}; content={content[:200]!r}"
        ) from e


async def analyze_shelf_image(
    image_bytes: bytes, model: str, fallback_model: str
) -> tuple[CVResponse, str]:
    """
    Call Ollama with the primary model, retrying it a bounded number of times on
    JSON/validation failure; then retry once with the fallback (if configured).
    Returns the validated response and the model name that succeeded.
    """
    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    # (model, attempts): primary gets the retry budget, fallback gets one shot.
    plan: list[tuple[str, int]] = [(model, _max_attempts)]
    if fallback_model:
        plan.append((fallback_model, 1))

    last_err: Exception | None = None
    for attempt_model, attempts in plan:
        if not attempt_model:
            continue
        for attempt in range(1, attempts + 1):
            try:
                raw = await _call(attempt_model, image_b64)
                validated = CVResponse.model_validate(raw)
                log.info(
                    "ollama %s succeeded: %d items", attempt_model, len(validated.items)
                )
                return validated, attempt_model
            except (OllamaError, ValidationError) as e:
                log.warning(
                    "ollama %s attempt %d/%d failed: %s",
                    attempt_model,
                    attempt,
                    attempts,
                    e,
                )
                last_err = e
                continue

    raise OllamaError(f"all attempts failed; last error: {last_err}")
