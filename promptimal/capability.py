from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, Optional


def _cost(executions: Iterable[Dict[str, Any]]) -> Optional[float]:
    values = [
        (execution.get("response", {}).get("usage") or {}).get("cost")
        for execution in executions
    ]
    available = [float(value) for value in values if value is not None]
    return sum(available) if available else None


def quality_cost_views(evidence, cost_ceiling=None):
    by_prompt = defaultdict(list)
    for observation in evidence:
        quality = observation["metrics"].get("full_pass_rate")
        cost = observation.get("average_cost_per_planned_request")
        if quality is not None and cost is not None:
            by_prompt[observation["prompt_id"]].append(observation)
    views = {}
    for prompt_id, observations in by_prompt.items():
        frontier = []
        for candidate in observations:
            candidate_quality = candidate["metrics"]["full_pass_rate"]
            candidate_cost = candidate["average_cost_per_planned_request"]
            dominated = any(
                other is not candidate
                and other["metrics"]["full_pass_rate"] >= candidate_quality
                and other["average_cost_per_planned_request"] <= candidate_cost
                and (
                    other["metrics"]["full_pass_rate"] > candidate_quality
                    or other["average_cost_per_planned_request"] < candidate_cost
                )
                for other in observations
            )
            if not dominated:
                frontier.append(candidate)
        frontier.sort(
            key=lambda item: (
                item["average_cost_per_planned_request"],
                -item["metrics"]["full_pass_rate"],
                item["model"],
            )
        )
        strongest = None
        if cost_ceiling is not None:
            affordable = [
                item
                for item in observations
                if item["average_cost_per_planned_request"] <= cost_ceiling
            ]
            strongest = max(
                affordable,
                key=lambda item: (
                    item["metrics"]["full_pass_rate"],
                    -item["average_cost_per_planned_request"],
                ),
                default=None,
            )
        views[prompt_id] = {
            "cost_unit": "observed average cost per planned request",
            "cost_ceiling": cost_ceiling,
            "strongest_within_ceiling": (
                {
                    "model": strongest["model"],
                    "quality": strongest["metrics"]["full_pass_rate"],
                    "cost": strongest["average_cost_per_planned_request"],
                    "result_set_id": strongest["result_set_id"],
                }
                if strongest
                else None
            ),
            "pareto_frontier": [
                {
                    "model": item["model"],
                    "quality": item["metrics"]["full_pass_rate"],
                    "cost": item["average_cost_per_planned_request"],
                    "result_set_id": item["result_set_id"],
                }
                for item in frontier
            ],
        }
    return views


def capability_matrix(sheet, cost_ceiling=None) -> Dict[str, Any]:
    cells = defaultdict(list)
    evidence = []
    candidate_result_ids = {
        candidate.get("result_set_id")
        for run in sheet.evolution_runs
        for generation in run.get("generations", [])
        for candidate in generation.get("candidates", [])
        if candidate.get("result_set_id") is not None
    }
    for result_set in sheet.result_sets:
        if (
            result_set.get("status") != "completed"
            or not result_set.get("summary")
            or result_set.get("id") in candidate_result_ids
        ):
            continue
        target_by_id = {item["id"]: item for item in result_set.get("targets", [])}
        for target_summary in result_set["summary"].get("per_target", []):
            target = target_by_id.get(target_summary["target_id"], {})
            model = target.get("model", target_summary["target_id"])
            metrics = target_summary["metrics"]
            target_executions = [
                item
                for item in result_set["executions"]
                if item["target_id"] == target_summary["target_id"]
            ]
            observed_cost = _cost(target_executions)
            observation = {
                "prompt_id": result_set["prompt_id"],
                "revision_id": result_set["revision_id"],
                "model": model,
                "target_id": target_summary["target_id"],
                "result_set_id": result_set["id"],
                "execution_profile_id": result_set["execution_profile_id"],
                "started_at": result_set["started_at"],
                "completed_at": result_set["completed_at"],
                "test_case_ids": [
                    item["id"]
                    for item in result_set["operation_snapshot"]["test_cases"]
                ],
                "runs_per_case": result_set["runs_per_case"],
                "metrics": metrics,
                "planned_request_count": len(target_executions),
                "model_response_count": len(
                    [
                        item
                        for item in target_executions
                        if item["response"].get("status") == "ok"
                    ]
                ),
                "observed_cost": observed_cost,
                "average_cost_per_planned_request": (
                    observed_cost / len(target_executions)
                    if observed_cost is not None and target_executions
                    else None
                ),
                "average_latency_ms": (
                    sum(
                        item["response"]["latency_ms"]
                        for item in target_executions
                        if item["response"].get("latency_ms") is not None
                    )
                    / len(
                        [
                            item
                            for item in target_executions
                            if item["response"].get("latency_ms") is not None
                        ]
                    )
                    if any(
                        item["response"].get("latency_ms") is not None
                        for item in target_executions
                    )
                    else None
                ),
            }
            cells[(model, result_set["prompt_id"])].append(observation)
            evidence.append(observation)

    models = sorted({key[0] for key in cells})
    prompt_ids = [prompt["id"] for prompt in sheet.prompts]
    matrix = []
    for model in models:
        row = {"model": model, "prompts": {}}
        for prompt_id in prompt_ids:
            observations = cells.get((model, prompt_id), [])
            best = max(
                observations,
                key=lambda item: (
                    item["metrics"].get("full_pass_rate")
                    if item["metrics"].get("full_pass_rate") is not None
                    else -1.0,
                    item["completed_at"] or "",
                ),
                default=None,
            )
            row["prompts"][prompt_id] = (
                {
                    "observed_full_pass_rate": best["metrics"].get("full_pass_rate"),
                    "result_set_id": best["result_set_id"],
                    "revision_id": best["revision_id"],
                }
                if best
                else None
            )
        matrix.append(row)
    return {
        "format": "promptimal.capability-matrix",
        "format_version": "1.0.0",
        "source_sheet_id": sheet.data["sheet_id"],
        "prompt_ids": prompt_ids,
        "models": models,
        "matrix": matrix,
        "evidence": evidence,
        "quality_cost": quality_cost_views(evidence, cost_ceiling),
    }
