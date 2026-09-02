from __future__ import annotations

import asyncio
import copy
from typing import Any, Dict, Iterable, List, Optional

from promptimal.execution.models import new_id
from promptimal.execution.runner import ExecutionRunner
from promptimal.optimizer.candidates import (
    candidate_summary,
    has_complete_task_coverage,
    rank_candidates,
)
from promptimal.optimizer.generate import generate_templates
from promptimal.optimizer.select import tournament_parent
from promptimal.sheet.models import PromptSheet, utc_now
from promptimal.template.expand import expand_template
from promptimal.template.fields import inspect_template


class EvolutionRunner:
    def __init__(
        self,
        sheet: PromptSheet,
        api_key: Optional[str] = None,
        client: Optional[Any] = None,
        progress_callback=None,
    ) -> None:
        self.sheet = sheet
        self.api_key = api_key
        self.client = client
        self.progress_callback = progress_callback

    def _persist(self) -> None:
        if self.sheet.path is not None:
            self.sheet.save()

    @staticmethod
    def _candidate(
        template: Optional[str],
        parents: Iterable[str],
        status: str = "generated",
        generation_error: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "id": new_id("candidate"),
            "parent_candidate_ids": list(parents),
            "prompt_template": template,
            "status": status,
            "generation_error": copy.deepcopy(generation_error),
            "result_set_id": None,
            "ranking": None,
        }

    @staticmethod
    def _executable_diagnostics(
        template: str,
        operation: Dict[str, Any],
        test_case_ids: Optional[Iterable[str]],
    ) -> List[Dict[str, str]]:
        inspection = inspect_template(template)
        diagnostics = [
            {"code": item.code, "message": item.message}
            for item in inspection.diagnostics
        ]
        required_fields = {
            item.get("name")
            for item in operation.get("variables", [])
            if item.get("required") is True
        }
        for name in sorted(required_fields - set(inspection.fields)):
            diagnostics.append(
                {
                    "code": "missing_declared_field",
                    "message": "Candidate omits required declared field %r" % name,
                }
            )
        selected_ids = set(test_case_ids) if test_case_ids is not None else None
        for test_case in operation.get("test_cases", []):
            if selected_ids is not None and test_case.get("id") not in selected_ids:
                continue
            expanded = expand_template(
                template,
                operation.get("variables", []),
                test_case.get("values", {}),
            )
            diagnostics.extend(
                {
                    "code": item.code,
                    "message": "%s: %s" % (test_case.get("id"), item.message),
                }
                for item in expanded.diagnostics
            )
        unique = []
        seen = set()
        for item in diagnostics:
            key = (item["code"], item["message"])
            if key not in seen:
                unique.append(item)
                seen.add(key)
        return unique

    async def _test_candidate(
        self,
        candidate: Dict[str, Any],
        run: Dict[str, Any],
        test_case_ids: Optional[Iterable[str]],
        target_ids: Optional[Iterable[str]],
        runs_per_case: Optional[int],
    ) -> None:
        operation = self.sheet.operation_snapshot(run["prompt_id"])
        diagnostics = self._executable_diagnostics(
            candidate["prompt_template"], operation, test_case_ids
        )
        if diagnostics:
            candidate["status"] = "not_executable"
            candidate["generation_error"] = {
                "type": "TemplateValidationError",
                "diagnostics": diagnostics,
            }
            self._persist()
            return

        runner = ExecutionRunner(
            self.sheet,
            api_key=self.api_key,
            client=self.client,
            progress_callback=self.progress_callback,
        )
        result_set = await runner.run(
            run["prompt_id"],
            revision_id=run["parent_revision_id"],
            execution_profile_id=run["execution_profile_id"],
            test_case_ids=test_case_ids,
            target_ids=target_ids,
            runs_per_case=runs_per_case,
            prompt_template=candidate["prompt_template"],
        )
        candidate["result_set_id"] = result_set["id"]
        candidate["ranking"] = copy.deepcopy(result_set["summary"]["metrics"])
        candidate["status"] = (
            "tested" if result_set["status"] == "completed" else "cancelled"
        )
        self._persist()

    async def _test_generation(
        self,
        generation: Dict[str, Any],
        run: Dict[str, Any],
        test_case_ids: Optional[Iterable[str]],
        target_ids: Optional[Iterable[str]],
        runs_per_case: Optional[int],
    ) -> None:
        for candidate in generation["candidates"]:
            if candidate["status"] == "generated":
                await self._test_candidate(
                    candidate, run, test_case_ids, target_ids, runs_per_case
                )

    def automatic_selection_ready(self, generation: Dict[str, Any]) -> bool:
        testable = [
            item for item in generation["candidates"] if item["status"] == "tested"
        ]
        return bool(testable) and all(
            has_complete_task_coverage(item, self.sheet.result_sets)
            for item in testable
        )

    async def start(
        self,
        prompt_id: str,
        mutator_target: Dict[str, Any],
        population_size: int = 5,
        generation_limit: int = 5,
        execution_profile_id: Optional[str] = None,
        test_case_ids: Optional[Iterable[str]] = None,
        target_ids: Optional[Iterable[str]] = None,
        runs_per_case: Optional[int] = None,
        elite_count: int = 1,
        starting_candidate_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if population_size < 1 or generation_limit < 1:
            raise ValueError("Population size and generation limit must be positive")
        if not 0 <= elite_count <= population_size:
            raise ValueError("elite_count must be between zero and population_size")
        prompt = self.sheet.prompt(prompt_id)
        revision = self.sheet.revision(prompt)
        profile = self.sheet.execution_profile(execution_profile_id)
        run = {
            "id": new_id("evolution"),
            "prompt_id": prompt_id,
            "parent_revision_id": revision["id"],
            "execution_profile_id": profile["id"],
            "mutator_target": copy.deepcopy(mutator_target),
            "population_size": population_size,
            "generation_limit": generation_limit,
            "status": "running",
            "started_at": utc_now(),
            "completed_at": None,
            "generations": [],
            "selected_candidate_id": None,
            "adopted_revision_id": None,
        }
        baseline_template = revision["prompt_template"]
        baseline_parents = []
        if starting_candidate_id is not None:
            source_candidate = self.sheet.candidate(starting_candidate_id)
            source_run = next(
                (
                    item
                    for item in self.sheet.evolution_runs
                    if any(
                        candidate.get("id") == starting_candidate_id
                        for generation in item.get("generations", [])
                        for candidate in generation.get("candidates", [])
                    )
                ),
                None,
            )
            if source_run is None or source_run.get("prompt_id") != prompt_id:
                raise ValueError("Starting candidate does not belong to this prompt")
            if not source_candidate.get("prompt_template"):
                raise ValueError("Starting candidate has no prompt template")
            baseline_template = source_candidate["prompt_template"]
            baseline_parents = [starting_candidate_id]
        generation_zero = {
            "index": 0,
            "candidates": [self._candidate(baseline_template, baseline_parents)],
        }
        run["generations"].append(generation_zero)
        self.sheet.evolution_runs.append(run)
        self._persist()
        try:
            await self._test_generation(
                generation_zero, run, test_case_ids, target_ids, runs_per_case
            )
            if not any(
                item["status"] == "tested" for item in generation_zero["candidates"]
            ):
                return run

            parent_generation = generation_zero
            for generation_index in range(1, generation_limit + 1):
                ranked = rank_candidates(
                    [
                        item
                        for item in parent_generation["candidates"]
                        if item["status"] == "tested"
                    ],
                    self.sheet.result_sets,
                )
                elites = ranked[: min(elite_count, len(ranked))]
                candidates = [
                    self._candidate(
                        elite["prompt_template"], [elite["id"]], status="tested"
                    )
                    for elite in elites
                ]
                for candidate_index, clone in enumerate(candidates):
                    elite = elites[candidate_index]
                    clone["result_set_id"] = elite["result_set_id"]
                    clone["ranking"] = copy.deepcopy(elite["ranking"])

                child_count = population_size - len(candidates)
                parent_ids = []
                parent_templates = []
                for _ in range(max(child_count, 1)):
                    parent = tournament_parent(ranked, self.sheet.result_sets)
                    if parent["id"] not in parent_ids:
                        parent_ids.append(parent["id"])
                        parent_templates.append(parent["prompt_template"])
                    if len(parent_ids) == min(2, len(ranked)):
                        break
                failures = []
                for parent in ranked[:2]:
                    summary = candidate_summary(parent, self.sheet.result_sets)
                    if summary:
                        failures.extend(summary.get("failure_distribution", []))
                if child_count:
                    templates, generation_error, _ = await generate_templates(
                        self.sheet.operation_snapshot(prompt_id),
                        parent_templates,
                        child_count,
                        mutator_target,
                        profile["timeout_seconds"],
                        profile["max_transport_retries"],
                        failures,
                        self.api_key,
                        self.client,
                    )
                else:
                    templates, generation_error = [], None
                candidates.extend(
                    self._candidate(template, parent_ids) for template in templates
                )
                while len(candidates) < population_size:
                    candidates.append(
                        self._candidate(
                            None,
                            parent_ids,
                            status="generation_error",
                            generation_error=generation_error
                            or {
                                "type": "MutatorOutputError",
                                "message": "Mutator returned fewer candidates than requested",
                            },
                        )
                    )
                generation = {
                    "index": generation_index,
                    "candidates": candidates[:population_size],
                }
                run["generations"].append(generation)
                self._persist()
                await self._test_generation(
                    generation, run, test_case_ids, target_ids, runs_per_case
                )
                parent_generation = generation
                if not self.automatic_selection_ready(generation):
                    return run

            run["status"] = "completed"
            run["completed_at"] = utc_now()
            self._persist()
            return run
        except asyncio.CancelledError:
            run["status"] = "cancelled"
            run["completed_at"] = utc_now()
            for generation in run["generations"]:
                for candidate in generation["candidates"]:
                    if candidate["status"] == "generated":
                        candidate["status"] = "cancelled"
            self._persist()
            return run

    def reject(self, run_id: str) -> Dict[str, Any]:
        run = self.sheet.evolution_run(run_id)
        run["status"] = "rejected"
        run["completed_at"] = utc_now()
        self._persist()
        return run
