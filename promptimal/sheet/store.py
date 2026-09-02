from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from promptimal.sheet.models import PromptSheet, utc_now


def write_json_atomic(data: Dict[str, Any], path: Any) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".%s." % destination.name,
        suffix=".tmp",
        dir=str(destination.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return destination


def save_prompt_sheet(sheet: PromptSheet, path: Optional[Any] = None) -> Path:
    destination = Path(path) if path is not None else sheet.path
    if destination is None:
        raise ValueError("No prompt-sheet path was supplied")

    timestamp = utc_now()
    candidate = copy.deepcopy(sheet.data)
    candidate["updated_at"] = timestamp
    written = write_json_atomic(candidate, destination)
    sheet.data["updated_at"] = timestamp
    sheet.path = written
    return written
