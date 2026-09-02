from __future__ import annotations

from typing import Any, Dict

from promptimal.evaluation.contract import evaluate_contract
from promptimal.evaluation.normalize import normalize_output
from promptimal.evaluation.parse import parse_output
from promptimal.evaluation.requirements import evaluate_requirements
from promptimal.evaluation.task import evaluate_task


def empty_evaluation(failure_tag: str, details: str = None) -> Dict[str, Any]:
    return {
        "contract": {"status": "not_run", "checks": []},
        "requirements": [],
        "task": {
            "status": "not_run",
            "score": None,
            "method": "not_run",
            "details": details or "No model response was obtained",
            "provenance": "none",
        },
        "observations": [],
        "normalized_output": None,
        "failure_tags": [failure_tag],
    }


def evaluate_response(
    raw_output: str,
    operation: Dict[str, Any],
    test_case: Dict[str, Any],
) -> Dict[str, Any]:
    contract_definition = operation["output_contract"]
    parsed = parse_output(raw_output, contract_definition["media_type"])
    contract = evaluate_contract(raw_output, parsed, contract_definition)
    requirements = evaluate_requirements(
        parsed.value,
        raw_output,
        operation.get("behavioral_requirements", []),
        operation.get("variables", []),
        test_case.get("values", {}),
        parsed.status == "pass",
    )
    task = evaluate_task(
        parsed.value,
        test_case["intended_response"],
        operation["evaluation_plan"],
        parsed.status == "pass",
    )
    similarity_method = operation["evaluation_plan"].get("similarity", {}).get("method")
    normalized = (
        normalize_output(parsed.value, operation["evaluation_plan"])
        if parsed.status == "pass" and similarity_method == "normalized_equality"
        else None
    )

    failure_tags = []
    if contract["status"] == "fail":
        failure_tags.extend(
            "contract:%s" % item["id"]
            for item in contract["checks"]
            if item["status"] == "fail"
        )
    failure_tags.extend(
        "requirement:%s" % item["id"]
        for item in requirements
        if item["status"] == "fail"
    )
    if task["status"] == "fail":
        failure_tags.append("task:%s" % task["method"])

    return {
        "contract": contract,
        "requirements": requirements,
        "task": task,
        "observations": [],
        "normalized_output": normalized,
        "failure_tags": failure_tags,
    }
