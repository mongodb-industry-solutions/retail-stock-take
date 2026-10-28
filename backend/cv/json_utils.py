"""Tolerant JSON extraction for VLM output.

Vision models occasionally return JSON wrapped in a markdown fence, or a
runaway generation that gets truncated mid-object. `loads_tolerant` first tries
a strict parse, then salvages the complete item objects it can find, so a single
bad generation degrades to a partial result instead of failing the whole
capture. Callers still validate the shape via `CVResponse`.
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("cv.json")

# Flat item objects (our schema has no nested braces) that carry a "name".
_OBJECT_RE = re.compile(r"\{[^{}]*\}")


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t[3:]
        nl = t.find("\n")
        if nl != -1:
            t = t[nl + 1 :]  # drop the language tag line
    if t.rstrip().endswith("```"):
        t = t.rstrip()[:-3]
    return t.strip()


def _salvage_items(text: str) -> list[dict]:
    items: list[dict] = []
    for match in _OBJECT_RE.finditer(text):
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("name") is not None:
            items.append(obj)
    return items


def loads_tolerant(content: str) -> dict:
    """Parse model output into a dict, salvaging truncated JSON if needed.

    Raises ``json.JSONDecodeError`` when nothing usable can be extracted.
    """
    text = _strip_fences(content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        items = _salvage_items(text)
        if items:
            log.warning("salvaged %d item(s) from malformed model JSON", len(items))
            return {"items": items}
        raise
