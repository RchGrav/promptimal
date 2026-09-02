from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from promptimal.sheet.models import PromptSheet
from promptimal.sheet.validator import validate_prompt_sheet


class PromptSheetLoadError(ValueError):
    pass


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PromptSheetLoadError("Duplicate JSON object key: %s" % key)
        result[key] = value
    return result


def load_prompt_sheet(path: Any, schema_path: Optional[Any] = None) -> PromptSheet:
    source_path = Path(path)
    try:
        with source_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle, object_pairs_hook=_reject_duplicate_keys)
    except PromptSheetLoadError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PromptSheetLoadError(
            "Unable to load %s: %s" % (source_path, exc)
        ) from exc

    resolved_schema = Path(schema_path) if schema_path else None
    sheet = PromptSheet(data=data, path=source_path, schema_path=resolved_schema)
    sheet.diagnostics = validate_prompt_sheet(data, resolved_schema)
    return sheet
