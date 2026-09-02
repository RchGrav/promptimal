from __future__ import annotations

import asyncio
import copy
import json
from collections import defaultdict
from typing import Any, Dict, List, Optional

from promptimal.execution.openrouter import OpenRouterChatCompletionsAdapter
from promptimal.sheet.models import utc_now


SEMANTIC_EVALUATOR_SYSTEM_PROMPT = """Judge one model response against the defined inference operation, never against the wording quality of its prompt.
Return JSON only with this shape:
{"requirement_results":[{"id":"requirement-id","status":"pass|fail|unknown","details":"short evidence or null"}],"task_result":{"status":"pass|fail|unknown","score":0.0,"details":"short response-grounded evidence"},"explanation":"short response-grounded explanation"}
Return one result for every supplied behavioral requirement. Use unknown when the supplied evidence cannot establish a result."""


def evaluator_payload(
    operation: Dict[str, Any], test_case: Dict[str, Any], actual_response: str
) -> Dict[str, Any]:
    return {
        "intent": copy.deepcopy(operation["intent"]),
        "case_values": copy.deepcopy(test_case.get("values", {})),
        "intended_response": copy.deepcopy(test_case["intended_response"]),
        "output_contract": copy.deepcopy(operation["output_contract"]),
        "behavioral_requirements": copy.deepcopy(
            operation.get("behavioral_requirements", [])
        ),
        "actual_response": actual_response,
    }


def _unknown_task(method: str, details: str) -> Dict[str, Any]:
    return {
        "status": "unknown",
        "score": None,
        "method": method,
        "details": details,
        "provenance": "semantic_evaluator",
    }


def _parse_evaluator_output(
    raw_output: Optional[str], operation: Dict[str, Any]
) -> tuple:
    method = operation["evaluation_plan"]["task"].get("method", "semantic_criteria")
    try:
        value = json.loads(raw_output or "")
    except (TypeError, json.JSONDecodeError) as exc:
        return [], _unknown_task(method, "Evaluator output did not parse: %s" % exc)
    if not isinstance(value, dict):
        return [], _unknown_task(method, "Evaluator output is not an object")

    expected_ids = {item["id"] for item in operation.get("behavioral_requirements", [])}
    supplied = value.get("requirement_results", [])
    results = []
    if isinstance(supplied, list):
        for item in supplied:
            if not isinstance(item, dict) or item.get("id") not in expected_ids:
                continue
            status = item.get("status")
            if status not in ("pass", "fail", "unknown"):
                status = "unknown"
            results.append(
                {
                    "id": item["id"],
                    "status": status,
                    "details": item.get("details"),
                }
            )
    supplied_by_id = {item["id"] for item in results}
    for identifier in sorted(expected_ids - supplied_by_id):
        results.append(
            {
                "id": identifier,
                "status": "unknown",
                "details": "Evaluator omitted this requirement",
            }
        )

    task_value = value.get("task_result")
    if not isinstance(task_value, dict):
        task = _unknown_task(method, "Evaluator omitted task_result")
    else:
        status = task_value.get("status")
        if status not in ("pass", "fail", "unknown"):
            status = "unknown"
        score = task_value.get("score")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not 0 <= score <= 1
        ):
            score = None
        task = {
            "status": status,
            "score": score,
            "method": method,
            "details": task_value.get("details") or value.get("explanation"),
            "provenance": "semantic_evaluator",
        }
    return results, task


async def semantic_observations(
    execution: Dict[str, Any],
    operation: Dict[str, Any],
    test_case: Dict[str, Any],
    profile: Dict[str, Any],
    api_key: Optional[str] = None,
    client: Optional[Any] = None,
    semaphore: Optional[asyncio.Semaphore] = None,
) -> List[Dict[str, Any]]:
    payload = evaluator_payload(
        operation, test_case, execution["response"].get("raw_output")
    )
    messages = [
        {"role": "system", "content": SEMANTIC_EVALUATOR_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        },
    ]
    targets = [item for item in profile["targets"] if item.get("enabled")]
    semaphore = semaphore or asyncio.Semaphore(profile["max_concurrency"])

    async def observe(target, trial):
        adapter = OpenRouterChatCompletionsAdapter(
            profile["timeout_seconds"],
            profile["max_transport_retries"],
            api_key=api_key,
            client=client,
        )
        async with semaphore:
            response = await adapter.execute(target, messages)
        if response["status"] == "ok":
            requirement_results, task_result = _parse_evaluator_output(
                response.get("raw_output"), operation
            )
        else:
            requirement_results = []
            task_result = _unknown_task(
                operation["evaluation_plan"]["task"].get("method", "semantic_criteria"),
                "Evaluator transport failed: %s" % response["status"],
            )
        return {
            "id": "%s.semantic.%s.%d" % (execution["id"], target["id"], trial),
            "kind": "semantic_evaluator",
            "evaluator_target_id": target["id"],
            "recorded_at": utc_now(),
            "request": {
                "model": target["model"],
                "messages": copy.deepcopy(messages),
                "parameters": copy.deepcopy(target.get("parameters", {})),
                "provider_routing": copy.deepcopy(target.get("provider_routing", {})),
                "trial": trial,
            },
            "response": copy.deepcopy(response),
            "requirement_results": requirement_results,
            "task_result": task_result,
        }

    return list(
        await asyncio.gather(
            *(
                observe(target, trial)
                for target in targets
                for trial in range(1, profile["runs_per_case"] + 1)
            )
        )
    )


def apply_semantic_consensus(
    evaluation: Dict[str, Any], observations: List[Dict[str, Any]]
) -> None:
    task_was_unknown = evaluation.get("task", {}).get("status") == "unknown"
    evaluation.setdefault("observations", []).extend(copy.deepcopy(observations))
    task_results = [item["task_result"] for item in observations]
    decisive = [item for item in task_results if item["status"] in ("pass", "fail")]
    if (
        task_was_unknown
        and decisive
        and len(decisive) == len(task_results)
        and len({item["status"] for item in decisive}) == 1
    ):
        status = decisive[0]["status"]
        scores = [item["score"] for item in decisive if item.get("score") is not None]
        evaluation["task"] = {
            "status": status,
            "score": sum(scores) / len(scores)
            if scores
            else (1.0 if status == "pass" else 0.0),
            "method": decisive[0]["method"],
            "details": "Unanimous semantic evaluator result across %d observation(s)"
            % len(decisive),
            "provenance": "semantic_evaluator",
        }
    elif task_was_unknown and observations:
        evaluation["task"] = _unknown_task(
            task_results[0]["method"],
            "Semantic evaluator observations were incomplete or disagreed",
        )

    by_requirement = defaultdict(list)
    for observation in observations:
        for result in observation["requirement_results"]:
            by_requirement[result["id"]].append(result)
    for result in evaluation.get("requirements", []):
        if result["status"] != "unknown":
            continue
        observed = by_requirement.get(result["id"], [])
        statuses = {item["status"] for item in observed}
        if observed and len(statuses) == 1 and statuses <= {"pass", "fail"}:
            result.update(
                {
                    "status": observed[0]["status"],
                    "details": "Unanimous semantic evaluator result across %d observation(s)"
                    % len(observed),
                }
            )

    tags = list(evaluation.get("failure_tags", []))
    if task_was_unknown:
        tags = [item for item in tags if not item.startswith("task:semantic")]
    if task_was_unknown and evaluation["task"]["status"] == "fail":
        tags.append("task:semantic_evaluator")
    for result in evaluation.get("requirements", []):
        tag = "requirement:%s" % result["id"]
        if result["status"] == "fail" and tag not in tags:
            tags.append(tag)
    evaluation["failure_tags"] = tags
