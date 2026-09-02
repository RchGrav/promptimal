from __future__ import annotations

from typing import Any, Dict

from promptimal.sheet.models import PromptSheet, utc_now
from promptimal.sheet.store import write_json_atomic


def finalized_projection(sheet: PromptSheet) -> Dict[str, Any]:
    prompts = {}
    omitted = []
    for prompt in sheet.prompts:
        finalization = prompt.get("finalization")
        if not finalization:
            omitted.append(prompt["id"])
            continue
        revision = sheet.revision(prompt, finalization["revision_id"])
        prompts[prompt["id"]] = {
            "intent": prompt["intent"],
            "revision_id": revision["id"],
            "prompt_template": revision["prompt_template"],
            "variables": prompt["variables"],
            "test_cases": prompt["test_cases"],
            "output_contract": prompt["output_contract"],
            "behavioral_requirements": prompt["behavioral_requirements"],
            "evaluation_plan": prompt["evaluation_plan"],
            "source_references": prompt["source_references"],
        }
    return {
        "format": "promptimal.finalized-prompts",
        "format_version": "1.0.0",
        "source_sheet_id": sheet.data["sheet_id"],
        "generated_at": utc_now(),
        "prompts": prompts,
        "omitted_unfinalized_ids": omitted,
    }


def export_finalized(sheet: PromptSheet, path: Any):
    return write_json_atomic(finalized_projection(sheet), path)
