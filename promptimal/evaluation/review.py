from __future__ import annotations

from typing import Any, Dict, List, Optional

from promptimal.sheet.models import utc_now


def apply_human_review(
    execution: Dict[str, Any],
    status: str,
    details: Optional[str] = None,
    score: Optional[float] = None,
    requirement_results: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if status not in ("pass", "fail", "unknown"):
        raise ValueError("Human task status must be pass, fail, or unknown")
    task_result = {
        "status": status,
        "score": score,
        "method": "human_review",
        "details": details,
        "provenance": "human",
    }
    observation = {
        "id": "%s.review.%04d"
        % (
            execution["id"],
            len(execution.get("evaluation", {}).get("observations", [])) + 1,
        ),
        "kind": "human",
        "evaluator_target_id": None,
        "recorded_at": utc_now(),
        "request": None,
        "response": {"details": details},
        "requirement_results": requirement_results or [],
        "task_result": task_result,
    }
    evaluation = execution["evaluation"]
    evaluation.setdefault("observations", []).append(observation)
    evaluation["task"] = task_result
    evaluation["failure_tags"] = [
        item for item in evaluation["failure_tags"] if not item.startswith("task:")
    ]
    if status == "fail" and "task:human_review" not in evaluation["failure_tags"]:
        evaluation["failure_tags"].append("task:human_review")
    return observation
