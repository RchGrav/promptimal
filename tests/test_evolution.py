import asyncio
import copy

from promptimal.optimizer.candidates import rank_candidates
from promptimal.optimizer.evolution import EvolutionRunner
from promptimal.optimizer.generate import mutator_context


def _summary(overall, worst):
    metrics = {
        "total_executions": 1,
        "execution_coverage": 1.0,
        "evaluation_coverage": 1.0,
        "task_success_rate": overall,
        "contract_compliance_rate": 1.0,
        "full_pass_rate": overall,
        "within_model_repeatability": 1.0,
        "cross_model_agreement": 1.0,
    }
    cell = copy.deepcopy(metrics)
    cell["full_pass_rate"] = worst
    cell["task_success_rate"] = worst
    return {
        "metrics": metrics,
        "worst_cells": [{"target_id": "m", "test_case_id": "c", "metrics": cell}],
        "failure_distribution": [],
        "per_target": [],
        "per_case": [],
    }


def test_mutator_context_contains_no_cases_or_intended_answers(memory_sheet):
    context = mutator_context(
        memory_sheet.operation_snapshot("namespace.aliases"), ["parent {name}"], 2
    )
    assert "test_cases" not in context
    assert "intended_response" not in str(context)
    assert context["parent_templates"] == ["parent {name}"]


def test_ranking_prefers_worst_cell_before_average(memory_sheet):
    candidate_a = {"id": "a", "result_set_id": "result.a"}
    candidate_b = {"id": "b", "result_set_id": "result.b"}
    results = [
        {"id": "result.a", "summary": _summary(0.99, 0.20)},
        {"id": "result.b", "summary": _summary(0.80, 0.70)},
    ]
    assert rank_candidates([candidate_a, candidate_b], results)[0]["id"] == "b"


def test_malformed_candidate_is_retained_as_not_executable(memory_sheet):
    runner = EvolutionRunner(memory_sheet)
    candidate = runner._candidate("{name", ["parent"])
    run = {
        "prompt_id": "namespace.aliases",
        "parent_revision_id": "namespace.aliases.r0001",
        "execution_profile_id": "frontier-core",
    }
    asyncio.run(runner._test_candidate(candidate, run, None, None, None))
    assert candidate["status"] == "not_executable"
    assert candidate["prompt_template"] == "{name"
    assert candidate["generation_error"]["diagnostics"]


def test_evolution_starts_at_current_revision_and_never_adopts_automatically(
    monkeypatch, memory_sheet
):
    snapshot = memory_sheet.operation_snapshot("namespace.aliases")
    current = memory_sheet.revision(memory_sheet.prompt("namespace.aliases"))
    runner = EvolutionRunner(memory_sheet)

    async def stop_after_baseline(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runner, "_test_generation", stop_after_baseline)
    monkeypatch.setattr(runner, "automatic_selection_ready", lambda _generation: False)
    run = asyncio.run(
        runner.start(
            "namespace.aliases",
            copy.deepcopy(memory_sheet.execution_profiles[0]["targets"][0]),
            population_size=2,
            generation_limit=1,
        )
    )
    baseline = run["generations"][0]["candidates"][0]
    assert baseline["prompt_template"] == current["prompt_template"]
    assert run["selected_candidate_id"] is None
    assert run["adopted_revision_id"] is None
    assert memory_sheet.operation_snapshot("namespace.aliases") == snapshot
    assert (
        memory_sheet.prompt("namespace.aliases")["current_revision_id"] == current["id"]
    )


def test_reject_preserves_generation_and_current_revision(memory_sheet):
    runner = EvolutionRunner(memory_sheet)
    current_id = memory_sheet.prompt("namespace.aliases")["current_revision_id"]
    run = {
        "id": "run.reject",
        "prompt_id": "namespace.aliases",
        "parent_revision_id": current_id,
        "execution_profile_id": "frontier-core",
        "mutator_target": copy.deepcopy(
            memory_sheet.execution_profiles[0]["targets"][0]
        ),
        "population_size": 1,
        "generation_limit": 1,
        "status": "running",
        "started_at": "2026-09-02T00:00:00Z",
        "completed_at": None,
        "generations": [{"index": 0, "candidates": []}],
        "selected_candidate_id": None,
        "adopted_revision_id": None,
    }
    memory_sheet.evolution_runs.append(run)
    runner.reject("run.reject")
    assert run["status"] == "rejected"
    assert run["generations"] == [{"index": 0, "candidates": []}]
    assert memory_sheet.prompt("namespace.aliases")["current_revision_id"] == current_id


def test_adoption_is_explicit_and_branches_from_run_parent(memory_sheet):
    prompt = memory_sheet.prompt("namespace.aliases")
    parent = memory_sheet.revision(prompt)
    run = {
        "id": "run.adopt",
        "prompt_id": prompt["id"],
        "parent_revision_id": parent["id"],
        "execution_profile_id": "frontier-core",
        "mutator_target": copy.deepcopy(
            memory_sheet.execution_profiles[0]["targets"][0]
        ),
        "population_size": 1,
        "generation_limit": 1,
        "status": "completed",
        "started_at": "2026-09-02T00:00:00Z",
        "completed_at": "2026-09-02T00:01:00Z",
        "generations": [
            {
                "index": 1,
                "candidates": [
                    {
                        "id": "candidate.adopt",
                        "parent_candidate_ids": [],
                        "prompt_template": parent["prompt_template"],
                        "status": "tested",
                        "generation_error": None,
                        "result_set_id": None,
                        "ranking": None,
                    }
                ],
            }
        ],
        "selected_candidate_id": None,
        "adopted_revision_id": None,
    }
    memory_sheet.evolution_runs.append(run)
    memory_sheet.create_revision(prompt["id"], "manual branch {name}")
    adopted = memory_sheet.adopt_candidate("run.adopt", "candidate.adopt")
    assert adopted["id"] != parent["id"]
    assert adopted["parent_revision_id"] == parent["id"]
    assert adopted["origin"]["source_candidate_id"] == "candidate.adopt"
    assert run["adopted_revision_id"] == adopted["id"]
