from __future__ import annotations

import json
from typing import Any, Dict


def _normalize_strings(value: Any, case_sensitive: bool) -> Any:
    if isinstance(value, str):
        return value if case_sensitive else value.casefold()
    if isinstance(value, list):
        return [_normalize_strings(item, case_sensitive) for item in value]
    if isinstance(value, dict):
        return {
            key: _normalize_strings(item, case_sensitive) for key, item in value.items()
        }
    return value


def normalize_output(value: Any, plan: Dict[str, Any]) -> Any:
    normalizer = plan.get("normalizer", {})
    normalizer_type = normalizer.get("type", "identity")
    parameters = normalizer.get("parameters", {})
    case_sensitive = parameters.get("case_sensitive", True)
    normalized = _normalize_strings(value, case_sensitive)

    if normalizer_type in ("identity", "json", "json_deep"):
        return normalized
    if normalizer_type == "stripped_text":
        return normalized.strip() if isinstance(normalized, str) else normalized
    if normalizer_type in ("json_string_array_unordered", "json_array_unordered"):
        if not isinstance(normalized, list):
            return normalized
        if not parameters.get("preserve_duplicates", True):
            normalized = list(
                {json.dumps(item, sort_keys=True): item for item in normalized}.values()
            )
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    return None
