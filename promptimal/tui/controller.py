from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, List, Optional

from promptimal.execution.runner import ExecutionRunner
from promptimal.evaluation.metrics import build_result_summary
from promptimal.evaluation.review import apply_human_review
from promptimal.optimizer.evolution import EvolutionRunner
from promptimal.sheet.models import PromptSheet
from promptimal.template.expand import ExpansionResult, expand_template


class WorkbenchController:
    """State and actions shared by the urwid screens and programmatic callers."""

    def __init__(self, sheet: PromptSheet, api_key: Optional[str] = None) -> None:
        self.sheet = sheet
        self.api_key = api_key
        self.prompt_index = 0
        self.state_filter: Optional[str] = None
        self._case_by_prompt: Dict[str, str] = {}
        self.execution_profile_id = sheet.data.get("default_execution_profile_id")

    @property
    def visible_prompts(self) -> List[Dict[str, Any]]:
        if self.state_filter is None:
            return self.sheet.prompts
        return [
            prompt
            for prompt in self.sheet.prompts
            if prompt.get("state") == self.state_filter
        ]

    @property
    def prompt(self) -> Dict[str, Any]:
        prompts = self.visible_prompts
        if not prompts:
            raise IndexError("No prompts match the selected state filter")
        self.prompt_index %= len(prompts)
        return prompts[self.prompt_index]

    @property
    def revision(self) -> Dict[str, Any]:
        return self.sheet.revision(self.prompt)

    @property
    def selected_case(self) -> Dict[str, Any]:
        prompt = self.prompt
        cases = prompt.get("test_cases", [])
        if not cases:
            raise IndexError("Prompt has no test cases")
        selected_id = self._case_by_prompt.get(prompt["id"], cases[0]["id"])
        try:
            return self.sheet.test_case(prompt, selected_id)
        except KeyError:
            return cases[0]

    def set_prompt(self, prompt_id: str) -> Dict[str, Any]:
        for index, prompt in enumerate(self.visible_prompts):
            if prompt.get("id") == prompt_id:
                self.prompt_index = index
                return prompt
        raise KeyError("Unknown visible prompt ID: %s" % prompt_id)

    def next_prompt(self) -> Dict[str, Any]:
        self.prompt_index = (self.prompt_index + 1) % len(self.visible_prompts)
        return self.prompt

    def previous_prompt(self) -> Dict[str, Any]:
        self.prompt_index = (self.prompt_index - 1) % len(self.visible_prompts)
        return self.prompt

    def set_filter(self, state: Optional[str]) -> None:
        if state not in (None, "unreviewed", "in_refinement", "tested", "finalized"):
            raise ValueError("Unknown prompt state %r" % state)
        self.state_filter = state
        self.prompt_index = 0

    def select_case(self, test_case_id: str) -> Dict[str, Any]:
        case = self.sheet.test_case(self.prompt, test_case_id)
        self._case_by_prompt[self.prompt["id"]] = test_case_id
        return case

    def next_case(self) -> Dict[str, Any]:
        cases = self.prompt["test_cases"]
        current = self.selected_case
        index = next(i for i, item in enumerate(cases) if item["id"] == current["id"])
        return self.select_case(cases[(index + 1) % len(cases)]["id"])

    def expanded(self, template: Optional[str] = None) -> ExpansionResult:
        return expand_template(
            template if template is not None else self.revision["prompt_template"],
            self.prompt.get("variables", []),
            self.selected_case.get("values", {}),
        )

    def save_edit(
        self,
        template: str,
        note: Optional[str] = None,
        source_candidate_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        revision = self.sheet.create_revision(
            self.prompt["id"],
            template,
            origin_kind="manual",
            source_candidate_id=source_candidate_id,
            note=note,
        )
        self.sheet.save()
        return revision

    def select_revision(self, revision_id: str) -> Dict[str, Any]:
        revision = self.sheet.select_revision(self.prompt["id"], revision_id)
        self.sheet.save()
        return revision

    def finalize(self, note: Optional[str] = None) -> Dict[str, Any]:
        event = self.sheet.finalize(self.prompt["id"], note)
        self.sheet.save()
        return event

    def latest_result(self, prompt: Optional[Dict[str, Any]] = None):
        prompt = prompt or self.prompt
        candidate_result_ids = {
            candidate.get("result_set_id")
            for run in self.sheet.evolution_runs
            for generation in run.get("generations", [])
            for candidate in generation.get("candidates", [])
            if candidate.get("result_set_id") is not None
        }
        for result_set in reversed(self.sheet.result_sets):
            if (
                result_set.get("prompt_id") == prompt.get("id")
                and result_set.get("revision_id") == prompt.get("current_revision_id")
                and result_set.get("id") not in candidate_result_ids
            ):
                return result_set
        return None

    async def test_current(
        self,
        template: Optional[str] = None,
        progress_callback=None,
        test_case_ids: Optional[Iterable[str]] = None,
        target_ids: Optional[Iterable[str]] = None,
        runs_per_case: Optional[int] = None,
        source_candidate_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if template is not None and template != self.revision["prompt_template"]:
            self.save_edit(
                template,
                "Created automatically before testing edited buffer",
                source_candidate_id=source_candidate_id,
            )
        runner = ExecutionRunner(
            self.sheet,
            api_key=self.api_key,
            progress_callback=progress_callback,
        )
        return await runner.run(
            self.prompt["id"],
            execution_profile_id=self.execution_profile_id,
            test_case_ids=test_case_ids,
            target_ids=target_ids,
            runs_per_case=runs_per_case,
        )

    async def start_evolution(
        self,
        mutator_target: Dict[str, Any],
        population_size: int,
        generation_limit: int,
        progress_callback=None,
        **settings,
    ) -> Dict[str, Any]:
        runner = EvolutionRunner(
            self.sheet,
            api_key=self.api_key,
            progress_callback=progress_callback,
        )
        return await runner.start(
            self.prompt["id"],
            mutator_target,
            population_size,
            generation_limit,
            execution_profile_id=self.execution_profile_id,
            **settings,
        )

    def adopt_candidate(self, run_id: str, candidate_id: str) -> Dict[str, Any]:
        revision = self.sheet.adopt_candidate(run_id, candidate_id)
        self.sheet.save()
        return revision

    def reject_evolution(self, run_id: str) -> Dict[str, Any]:
        run = EvolutionRunner(self.sheet, api_key=self.api_key).reject(run_id)
        return run

    def review_cluster(
        self,
        result_set_id: str,
        execution_ids: Iterable[str],
        status: str,
        details: Optional[str] = None,
    ) -> Dict[str, Any]:
        result_set = next(
            item for item in self.sheet.result_sets if item.get("id") == result_set_id
        )
        selected = set(execution_ids)
        for execution in result_set["executions"]:
            if execution.get("id") in selected:
                apply_human_review(execution, status, details)
        result_set["summary"] = build_result_summary(result_set["executions"])
        for run in self.sheet.evolution_runs:
            for generation in run.get("generations", []):
                for candidate in generation.get("candidates", []):
                    if candidate.get("result_set_id") == result_set_id:
                        candidate["ranking"] = copy.deepcopy(
                            result_set["summary"]["metrics"]
                        )
        self.sheet.save()
        return result_set

    def operation_snapshot(self) -> Dict[str, Any]:
        return copy.deepcopy(self.sheet.operation_snapshot(self.prompt["id"]))
