from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List


def _task_result(status, method, details=None, score=None, provenance="deterministic"):
    return {
        "status": status,
        "score": score,
        "method": method,
        "details": details,
        "provenance": provenance,
    }


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


def _unordered_equal(
    actual: List[Any], expected: List[Any], preserve_duplicates: bool
) -> bool:
    encoded_actual = [
        json.dumps(item, ensure_ascii=False, sort_keys=True) for item in actual
    ]
    encoded_expected = [
        json.dumps(item, ensure_ascii=False, sort_keys=True) for item in expected
    ]
    if preserve_duplicates:
        return Counter(encoded_actual) == Counter(encoded_expected)
    return set(encoded_actual) == set(encoded_expected)


def evaluate_task(
    parsed_value: Any,
    intended_response: Dict[str, Any],
    plan: Dict[str, Any],
    parse_succeeded: bool,
) -> Dict[str, Any]:
    task = plan.get("task", {})
    method = task.get("method", "unknown")
    parameters = task.get("parameters", {})
    if not parse_succeeded:
        return _task_result(
            "not_run", method, "Output did not parse", provenance="none"
        )
    if intended_response.get("kind") != "exact" or "value" not in intended_response:
        return _task_result(
            "unknown",
            method,
            "Representative or criteria-based responses require semantic or human evaluation",
            provenance="none",
        )

    actual = _normalize_strings(parsed_value, parameters.get("case_sensitive", True))
    expected = _normalize_strings(
        intended_response.get("value"), parameters.get("case_sensitive", True)
    )

    if method in ("exact_match", "exact_scalar_equality", "json_deep_equality"):
        passed = actual == expected
    elif method == "ordered_exact_match":
        passed = (
            isinstance(actual, list)
            and isinstance(expected, list)
            and actual == expected
        )
    elif method in ("unordered_exact_match", "multiset_exact_match"):
        if not isinstance(actual, list) or not isinstance(expected, list):
            return _task_result("fail", method, "Compared value is not an array", 0.0)
        passed = _unordered_equal(
            actual, expected, parameters.get("preserve_duplicates", True)
        )
    elif method in ("semantic_criteria", "human_review", "response_cluster_labels"):
        return _task_result(
            "unknown",
            method,
            "No semantic-evaluator or human observation is available",
            provenance="none",
        )
    else:
        return _task_result(
            "unknown", method, "Unsupported task evaluator", provenance="none"
        )

    return _task_result(
        "pass" if passed else "fail",
        method,
        None if passed else "Actual response does not match the intended response",
        1.0 if passed else 0.0,
    )
