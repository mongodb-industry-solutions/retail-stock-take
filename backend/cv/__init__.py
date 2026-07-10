"""CV provider selector.

Chooses the vision backend by `CV_PROVIDER` (config-only). Both providers expose
the identical contract —
`analyze_shelf_image(image_bytes, model, fallback) -> (CVResponse, str)` — so
callers (see `api/inventory.py`) stay provider-agnostic and catch a single
`CVError`.

  Local (kind):    CV_PROVIDER=ollama  -> in-cluster Ollama (moondream)
  Cloud (Kanopy):  CV_PROVIDER=grove   -> Grove GenAI gateway (OpenAI-compatible, vision)
"""
from __future__ import annotations

import os

_provider = os.environ.get("CV_PROVIDER", "ollama").strip().lower()

if _provider == "grove":
    from cv.grove_client import GroveError as CVError
    from cv.grove_client import analyze_shelf_image

    CV_MODEL = os.environ.get("GROVE_MODEL", "gpt-5.5")
    CV_FALLBACK = os.environ.get("GROVE_FALLBACK_MODEL", "gpt-4o")
elif _provider == "ollama":
    from cv.ollama_client import OllamaError as CVError
    from cv.ollama_client import analyze_shelf_image

    CV_MODEL = os.environ.get("OLLAMA_MODEL", "moondream")
    CV_FALLBACK = os.environ.get("OLLAMA_FALLBACK_MODEL", "")
else:
    raise ValueError(
        f"unsupported CV_PROVIDER {_provider!r} (expected 'ollama' or 'grove')"
    )

CV_PROVIDER = _provider

__all__ = ["analyze_shelf_image", "CVError", "CV_MODEL", "CV_FALLBACK", "CV_PROVIDER"]
