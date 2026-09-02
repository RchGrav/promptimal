from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from promptimal.evaluation.metrics import ranking_vector


def candidate_summary(
    candidate: Dict[str, Any], result_sets: Iterable[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    result_id = candidate.get("result_set_id")
    for result_set in result_sets:
        if result_set.get("id") == result_id:
            return result_set.get("summary")
    return None


def candidate_vector(
    candidate: Dict[str, Any], result_sets: Iterable[Dict[str, Any]]
) -> Tuple[float, ...]:
    summary = candidate_summary(candidate, result_sets)
    return ranking_vector(summary) if summary else (-1.0,) * 6


def has_complete_task_coverage(
    candidate: Dict[str, Any], result_sets: Iterable[Dict[str, Any]]
) -> bool:
    summary = candidate_summary(candidate, result_sets)
    if not summary:
        return False
    return summary.get("metrics", {}).get("evaluation_coverage") == 1.0


def rank_candidates(
    candidates: Iterable[Dict[str, Any]],
    result_sets: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    result_sets = list(result_sets)
    return sorted(
        candidates,
        key=lambda item: (candidate_vector(item, result_sets), item.get("id", "")),
        reverse=True,
    )
