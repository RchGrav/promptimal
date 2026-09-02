from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class FinalizedPrompt:
    prompt_id: str
    intent: str
    revision_id: str
    prompt_template: str
    variables: List[Dict[str, Any]]
    test_cases: List[Dict[str, Any]]
    output_contract: Dict[str, Any]
    behavioral_requirements: List[Dict[str, Any]]
    evaluation_plan: Dict[str, Any]
    source_references: List[str]

    def expand(self, case_values: Dict[str, Any]) -> str:
        from promptimal.template.expand import expand_template

        result = expand_template(self.prompt_template, self.variables, case_values)
        if result.diagnostics:
            raise ValueError("; ".join(item.message for item in result.diagnostics))
        return result.text


@dataclass
class PromptSheet:
    data: Dict[str, Any]
    path: Optional[Path] = None
    schema_path: Optional[Path] = None
    diagnostics: List[Any] = field(default_factory=list)

    @classmethod
    def load(cls, path: Any, schema_path: Optional[Any] = None) -> "PromptSheet":
        from promptimal.sheet.loader import load_prompt_sheet

        return load_prompt_sheet(path, schema_path=schema_path)

    @property
    def has_errors(self) -> bool:
        return any(item.severity == "error" for item in self.diagnostics)

    @property
    def prompts(self) -> List[Dict[str, Any]]:
        value = self.data.get("prompts", []) if isinstance(self.data, dict) else []
        return value if isinstance(value, list) else []

    @property
    def execution_profiles(self) -> List[Dict[str, Any]]:
        value = (
            self.data.get("execution_profiles", [])
            if isinstance(self.data, dict)
            else []
        )
        return value if isinstance(value, list) else []

    @property
    def result_sets(self) -> List[Dict[str, Any]]:
        value = self.data.get("result_sets", []) if isinstance(self.data, dict) else []
        return value if isinstance(value, list) else []

    @property
    def evolution_runs(self) -> List[Dict[str, Any]]:
        value = (
            self.data.get("evolution_runs", []) if isinstance(self.data, dict) else []
        )
        return value if isinstance(value, list) else []

    def validate(self) -> List[Any]:
        from promptimal.sheet.validator import validate_prompt_sheet

        self.diagnostics = validate_prompt_sheet(self.data, self.schema_path)
        return self.diagnostics

    def save(self, path: Optional[Any] = None) -> Path:
        from promptimal.sheet.store import save_prompt_sheet

        return save_prompt_sheet(self, path)

    def prompt(self, prompt_id: str) -> Dict[str, Any]:
        for prompt in self.prompts:
            if prompt.get("id") == prompt_id:
                return prompt
        raise KeyError("Unknown prompt ID: %s" % prompt_id)

    def execution_profile(self, profile_id: Optional[str] = None) -> Dict[str, Any]:
        selected_id = profile_id or self.data.get("default_execution_profile_id")
        for profile in self.execution_profiles:
            if profile.get("id") == selected_id:
                return profile
        raise KeyError("Unknown execution profile ID: %s" % selected_id)

    def revision(
        self, prompt: Dict[str, Any], revision_id: Optional[str] = None
    ) -> Dict[str, Any]:
        selected_id = revision_id or prompt.get("current_revision_id")
        for revision in prompt.get("revisions", []):
            if revision.get("id") == selected_id:
                return revision
        raise KeyError("Unknown revision ID: %s" % selected_id)

    def test_case(self, prompt: Dict[str, Any], test_case_id: str) -> Dict[str, Any]:
        for test_case in prompt.get("test_cases", []):
            if test_case.get("id") == test_case_id:
                return test_case
        raise KeyError("Unknown test-case ID: %s" % test_case_id)

    def create_revision(
        self,
        prompt_id: str,
        prompt_template: str,
        origin_kind: str = "manual",
        source_candidate_id: Optional[str] = None,
        note: Optional[str] = None,
        created_at: Optional[str] = None,
        force: bool = False,
        parent_revision_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        prompt = self.prompt(prompt_id)
        parent = self.revision(prompt, parent_revision_id)
        if prompt_template == parent.get("prompt_template") and not force:
            return parent

        sequence = (
            max(
                (
                    revision.get("sequence", 0)
                    for revision in prompt.get("revisions", [])
                ),
                default=0,
            )
            + 1
        )
        existing_ids = {revision.get("id") for revision in prompt.get("revisions", [])}
        revision_id = "%s.r%04d" % (prompt_id, sequence)
        while revision_id in existing_ids:
            sequence += 1
            revision_id = "%s.r%04d" % (prompt_id, sequence)

        revision = {
            "id": revision_id,
            "sequence": sequence,
            "parent_revision_id": parent.get("id"),
            "prompt_template": prompt_template,
            "origin": {
                "kind": origin_kind,
                "source_candidate_id": source_candidate_id,
                "note": note,
            },
            "created_at": created_at or utc_now(),
        }
        prompt.setdefault("revisions", []).append(revision)
        prompt["current_revision_id"] = revision_id
        prompt["state"] = "in_refinement"
        return revision

    def select_revision(self, prompt_id: str, revision_id: str) -> Dict[str, Any]:
        prompt = self.prompt(prompt_id)
        revision = self.revision(prompt, revision_id)
        prompt["current_revision_id"] = revision_id
        self.refresh_prompt_state(prompt_id)
        return revision

    def refresh_prompt_state(self, prompt_id: str) -> str:
        prompt = self.prompt(prompt_id)
        revision_id = prompt.get("current_revision_id")
        finalization = prompt.get("finalization")
        if finalization and finalization.get("revision_id") == revision_id:
            state = "finalized"
        elif any(
            result.get("prompt_id") == prompt_id
            and result.get("revision_id") == revision_id
            and result.get("status") == "completed"
            and result.get("id")
            not in {
                candidate.get("result_set_id")
                for run in self.evolution_runs
                for generation in run.get("generations", [])
                for candidate in generation.get("candidates", [])
            }
            for result in self.result_sets
        ):
            state = "tested"
        else:
            revision = self.revision(prompt, revision_id)
            state = (
                "unreviewed"
                if revision.get("origin", {}).get("kind") == "extracted"
                and revision.get("sequence") == 1
                else "in_refinement"
            )
        prompt["state"] = state
        return state

    def finalize(
        self,
        prompt_id: str,
        note: Optional[str] = None,
        finalized_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        prompt = self.prompt(prompt_id)
        event = {
            "revision_id": prompt["current_revision_id"],
            "finalized_at": finalized_at or utc_now(),
            "note": note,
        }
        prompt["finalization"] = copy.deepcopy(event)
        prompt.setdefault("finalization_history", []).append(copy.deepcopy(event))
        prompt["state"] = "finalized"
        return event

    def finalized_prompts(self) -> Iterable[FinalizedPrompt]:
        for prompt in self.prompts:
            finalization = prompt.get("finalization")
            if not finalization:
                continue
            revision = self.revision(prompt, finalization["revision_id"])
            yield FinalizedPrompt(
                prompt_id=prompt["id"],
                intent=prompt["intent"],
                revision_id=revision["id"],
                prompt_template=revision["prompt_template"],
                variables=copy.deepcopy(prompt["variables"]),
                test_cases=copy.deepcopy(prompt["test_cases"]),
                output_contract=copy.deepcopy(prompt["output_contract"]),
                behavioral_requirements=copy.deepcopy(
                    prompt["behavioral_requirements"]
                ),
                evaluation_plan=copy.deepcopy(prompt["evaluation_plan"]),
                source_references=list(prompt["source_references"]),
            )

    def operation_snapshot(self, prompt_id: str) -> Dict[str, Any]:
        prompt = self.prompt(prompt_id)
        return copy.deepcopy(
            {
                "intent": prompt["intent"],
                "variables": prompt["variables"],
                "test_cases": prompt["test_cases"],
                "output_contract": prompt["output_contract"],
                "behavioral_requirements": prompt["behavioral_requirements"],
                "evaluation_plan": prompt["evaluation_plan"],
            }
        )

    def candidate(self, candidate_id: str) -> Dict[str, Any]:
        for run in self.evolution_runs:
            for generation in run.get("generations", []):
                for candidate in generation.get("candidates", []):
                    if candidate.get("id") == candidate_id:
                        return candidate
        raise KeyError("Unknown candidate ID: %s" % candidate_id)

    def evolution_run(self, run_id: str) -> Dict[str, Any]:
        for run in self.evolution_runs:
            if run.get("id") == run_id:
                return run
        raise KeyError("Unknown evolution-run ID: %s" % run_id)

    def adopt_candidate(
        self, run_id: str, candidate_id: str, note: Optional[str] = None
    ) -> Dict[str, Any]:
        run = self.evolution_run(run_id)
        candidate = next(
            (
                candidate
                for generation in run.get("generations", [])
                for candidate in generation.get("candidates", [])
                if candidate.get("id") == candidate_id
            ),
            None,
        )
        if candidate is None:
            raise ValueError("Candidate does not belong to evolution run %s" % run_id)
        template = candidate.get("prompt_template")
        if not template:
            raise ValueError("Candidate has no prompt template")
        revision = self.create_revision(
            run["prompt_id"],
            template,
            origin_kind="candidate_adoption",
            source_candidate_id=candidate_id,
            note=note,
            force=True,
            parent_revision_id=run["parent_revision_id"],
        )
        run["selected_candidate_id"] = candidate_id
        run["adopted_revision_id"] = revision["id"]
        return revision
