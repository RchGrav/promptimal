from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ParseResult:
    status: str
    value: Any = None
    error: Optional[str] = None


def parse_output(raw_output: str, media_type: str) -> ParseResult:
    normalized_media_type = (media_type or "").split(";", 1)[0].strip().lower()
    if normalized_media_type == "application/json" or normalized_media_type.endswith(
        "+json"
    ):
        try:
            return ParseResult("pass", json.loads(raw_output))
        except (TypeError, json.JSONDecodeError) as exc:
            return ParseResult("fail", error=str(exc))
    if normalized_media_type == "text/plain":
        return ParseResult("pass", raw_output)
    return ParseResult("not_run", error="Unsupported media type %r" % media_type)
