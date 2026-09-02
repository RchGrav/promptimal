from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _response_executions(executions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        item for item in executions if item.get("response", {}).get("status") == "ok"
    ]


def _pairs_agreement(groups: Iterable[List[Dict[str, Any]]]) -> Optional[float]:
    rates = []
    for group in groups:
        equal = 0
        total = 0
        comparable = [
            item
            for item in group
            if item.get("evaluation", {}).get("normalized_output") is not None
        ]
        for left, right in itertools.combinations(comparable, 2):
            total += 1
            if (
                left["evaluation"]["normalized_output"]
                == right["evaluation"]["normalized_output"]
            ):
                equal += 1
        if total:
            rates.append(equal / total)
    return sum(rates) / len(rates) if rates else None


def _within_repeatability(executions: List[Dict[str, Any]]) -> Optional[float]:
    cells = defaultdict(list)
    for execution in _response_executions(executions):
        cells[(execution.get("target_id"), execution.get("test_case_id"))].append(
            execution
        )
    return _pairs_agreement(cells.values())


def _cross_model_agreement(executions: List[Dict[str, Any]]) -> Optional[float]:
    by_case = defaultdict(list)
    for execution in _response_executions(executions):
        by_case[execution.get("test_case_id")].append(execution)
    rates = []
    for group in by_case.values():
        equal = 0
        total = 0
        comparable = [
            item
            for item in group
            if item.get("evaluation", {}).get("normalized_output") is not None
        ]
        for left, right in itertools.combinations(comparable, 2):
            if left.get("target_id") == right.get("target_id"):
                continue
            total += 1
            if (
                left["evaluation"]["normalized_output"]
                == right["evaluation"]["normalized_output"]
            ):
                equal += 1
        if total:
            rates.append(equal / total)
    return sum(rates) / len(rates) if rates else None


def metric_set(executions: List[Dict[str, Any]]) -> Dict[str, Any]:
    model_responses = _response_executions(executions)
    evaluated = [
        item
        for item in model_responses
        if item.get("evaluation", {}).get("task", {}).get("status") in ("pass", "fail")
    ]
    task_passes = [
        item
        for item in evaluated
        if item.get("evaluation", {}).get("task", {}).get("status") == "pass"
    ]
    contract_passes = [
        item
        for item in model_responses
        if item.get("evaluation", {}).get("contract", {}).get("status") == "pass"
    ]

    fully_passing = []
    for execution in evaluated:
        evaluation = execution.get("evaluation", {})
        deterministic_failure = any(
            item.get("status") in ("fail", "not_run")
            for item in evaluation.get("requirements", [])
            if item.get("status") != "unknown"
        )
        if (
            evaluation.get("contract", {}).get("status") == "pass"
            and evaluation.get("task", {}).get("status") == "pass"
            and not deterministic_failure
        ):
            fully_passing.append(execution)

    response_count = len(model_responses)
    evaluated_count = len(evaluated)
    return {
        "total_executions": len(executions),
        "execution_coverage": response_count / len(executions) if executions else 0.0,
        "evaluation_coverage": evaluated_count / response_count
        if response_count
        else 0.0,
        "task_success_rate": len(task_passes) / evaluated_count
        if evaluated_count
        else None,
        "contract_compliance_rate": (
            len(contract_passes) / response_count if response_count else None
        ),
        "full_pass_rate": len(fully_passing) / evaluated_count
        if evaluated_count
        else None,
        "within_model_repeatability": _within_repeatability(executions),
        "cross_model_agreement": _cross_model_agreement(executions),
    }


def build_result_summary(executions: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_cell = defaultdict(list)
    by_target = defaultdict(list)
    by_case = defaultdict(list)
    failure_counts = Counter()
    for execution in executions:
        target_id = execution.get("target_id")
        case_id = execution.get("test_case_id")
        by_cell[(target_id, case_id)].append(execution)
        by_target[target_id].append(execution)
        by_case[case_id].append(execution)
        failure_counts.update(execution.get("evaluation", {}).get("failure_tags", []))
        status = execution.get("response", {}).get("status")
        if (
            status
            and status != "ok"
            and status not in execution.get("evaluation", {}).get("failure_tags", [])
        ):
            failure_counts[status] += 1

    cells = [
        {
            "target_id": target_id,
            "test_case_id": case_id,
            "metrics": metric_set(items),
        }
        for (target_id, case_id), items in by_cell.items()
    ]
    cells.sort(
        key=lambda item: (
            item["metrics"]["full_pass_rate"]
            if item["metrics"]["full_pass_rate"] is not None
            else -1.0,
            item["metrics"]["evaluation_coverage"],
            item["target_id"],
            item["test_case_id"],
        )
    )
    return {
        "metrics": metric_set(executions),
        "worst_cells": cells,
        "failure_distribution": [
            {"tag": tag, "count": count}
            for tag, count in sorted(
                failure_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "per_target": [
            {"target_id": target_id, "metrics": metric_set(items)}
            for target_id, items in sorted(by_target.items())
        ],
        "per_case": [
            {"test_case_id": case_id, "metrics": metric_set(items)}
            for case_id, items in sorted(by_case.items())
        ],
    }


def ranking_vector(summary: Dict[str, Any]) -> Tuple[float, ...]:
    metrics = summary["metrics"]
    cells = summary.get("worst_cells", [])

    def value(item):
        return item if item is not None else -1.0

    worst_full = min(
        (value(item["metrics"].get("full_pass_rate")) for item in cells),
        default=-1.0,
    )
    worst_task = min(
        (value(item["metrics"].get("task_success_rate")) for item in cells),
        default=-1.0,
    )
    return (
        worst_full,
        value(metrics.get("full_pass_rate")),
        worst_task,
        value(metrics.get("contract_compliance_rate")),
        value(metrics.get("within_model_repeatability")),
        value(metrics.get("cross_model_agreement")),
    )
