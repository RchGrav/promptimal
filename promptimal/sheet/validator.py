from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError


@dataclass(frozen=True)
class Diagnostic:
    code: str
    path: str
    message: str
    prompt_id: Optional[str] = None
    severity: str = "error"

    def __str__(self) -> str:
        owner = " [%s]" % self.prompt_id if self.prompt_id else ""
        return "%s%s: %s" % (self.path, owner, self.message)


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _dict_records(value: Any) -> List[Dict[str, Any]]:
    return [item for item in _as_list(value) if isinstance(item, dict)]


def _schema_document(schema_path: Optional[Path]) -> Dict[str, Any]:
    if schema_path:
        return json.loads(Path(schema_path).read_text(encoding="utf-8"))
    if hasattr(resources, "files"):
        text = (
            resources.files("promptimal.sheet")
            .joinpath("prompt-sheet.schema.json")
            .read_text(encoding="utf-8")
        )
    else:
        text = resources.read_text(
            "promptimal.sheet", "prompt-sheet.schema.json", encoding="utf-8"
        )
    return json.loads(text)


def _json_path(parts: Sequence[Any]) -> str:
    path = "$"
    for part in parts:
        if isinstance(part, int):
            path += "[%d]" % part
        elif str(part).isidentifier():
            path += ".%s" % part
        else:
            path += "[%s]" % json.dumps(str(part))
    return path


def _prompt_id_for_path(data: Any, parts: Sequence[Any]) -> Optional[str]:
    if len(parts) >= 2 and parts[0] == "prompts" and isinstance(parts[1], int):
        prompts = _as_list(data.get("prompts")) if isinstance(data, dict) else []
        if 0 <= parts[1] < len(prompts) and isinstance(prompts[parts[1]], dict):
            prompt_id = prompts[parts[1]].get("id")
            return prompt_id if isinstance(prompt_id, str) else None
    return None


def _duplicate_diagnostics(
    records: Iterable[Dict[str, Any]],
    path_prefix: str,
    label: str,
    prompt_id: Optional[str] = None,
) -> List[Diagnostic]:
    positions = defaultdict(list)
    for index, record in enumerate(_as_list(records)):
        if isinstance(record, dict) and isinstance(record.get("id"), str):
            positions[record["id"]].append(index)
    diagnostics = []
    for identifier, indexes in positions.items():
        if len(indexes) > 1:
            diagnostics.append(
                Diagnostic(
                    code="duplicate_id",
                    path=path_prefix,
                    message="Duplicate %s ID %r at indexes %s"
                    % (label, identifier, indexes),
                    prompt_id=prompt_id,
                )
            )
    return diagnostics


def _reference_error(
    path: str, message: str, prompt_id: Optional[str] = None
) -> Diagnostic:
    return Diagnostic("broken_reference", path, message, prompt_id)


def validate_prompt_sheet(
    data: Dict[str, Any], schema_path: Optional[Path] = None
) -> List[Diagnostic]:
    diagnostics: List[Diagnostic] = []
    try:
        schema = _schema_document(schema_path)
        Draft202012Validator.check_schema(schema)
    except (OSError, UnicodeError, json.JSONDecodeError, SchemaError) as exc:
        return [
            Diagnostic("invalid_schema", "$", "Invalid prompt-sheet schema: %s" % exc)
        ]

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
        parts = list(error.absolute_path)
        diagnostics.append(
            Diagnostic(
                code="schema",
                path=_json_path(parts),
                message=error.message,
                prompt_id=_prompt_id_for_path(data, parts),
            )
        )

    if not isinstance(data, dict):
        return diagnostics

    profiles = _dict_records(data.get("execution_profiles"))
    prompts = _dict_records(data.get("prompts"))
    result_sets = _dict_records(data.get("result_sets"))
    evolution_runs = _dict_records(data.get("evolution_runs"))

    diagnostics.extend(
        _duplicate_diagnostics(profiles, "$.execution_profiles", "profile")
    )
    diagnostics.extend(_duplicate_diagnostics(prompts, "$.prompts", "prompt"))
    diagnostics.extend(
        _duplicate_diagnostics(result_sets, "$.result_sets", "result-set")
    )
    diagnostics.extend(
        _duplicate_diagnostics(evolution_runs, "$.evolution_runs", "evolution-run")
    )

    profile_ids = {
        item.get("id") for item in profiles if isinstance(item.get("id"), str)
    }
    default_profile_id = data.get("default_execution_profile_id")
    if isinstance(default_profile_id, str) and default_profile_id not in profile_ids:
        diagnostics.append(
            _reference_error(
                "$.default_execution_profile_id",
                "Unknown execution profile ID %r" % default_profile_id,
            )
        )

    for profile_index, profile in enumerate(profiles):
        diagnostics.extend(
            _duplicate_diagnostics(
                _as_list(profile.get("targets")),
                "$.execution_profiles[%d].targets" % profile_index,
                "target",
            )
        )

    prompt_by_id = {
        item.get("id"): item for item in prompts if isinstance(item.get("id"), str)
    }
    revision_owner: Dict[str, str] = {}
    candidate_ids = set()
    all_candidate_ids = {
        candidate.get("id")
        for run in evolution_runs
        for generation in _as_list(run.get("generations"))
        if isinstance(generation, dict)
        for candidate in _as_list(generation.get("candidates"))
        if isinstance(candidate, dict) and isinstance(candidate.get("id"), str)
    }
    candidate_owner: Dict[str, Any] = {}
    result_ids = {
        item.get("id") for item in result_sets if isinstance(item.get("id"), str)
    }
    result_by_id = {
        item.get("id"): item for item in result_sets if isinstance(item.get("id"), str)
    }
    execution_ids = []

    for prompt_index, prompt in enumerate(prompts):
        prompt_id = prompt.get("id") if isinstance(prompt.get("id"), str) else None
        prompt_path = "$.prompts[%d]" % prompt_index
        revisions = _dict_records(prompt.get("revisions"))
        test_cases = _dict_records(prompt.get("test_cases"))
        variables = _dict_records(prompt.get("variables"))
        requirements = _dict_records(prompt.get("behavioral_requirements"))

        diagnostics.extend(
            _duplicate_diagnostics(
                revisions, prompt_path + ".revisions", "revision", prompt_id
            )
        )
        diagnostics.extend(
            _duplicate_diagnostics(
                test_cases, prompt_path + ".test_cases", "test-case", prompt_id
            )
        )
        diagnostics.extend(
            _duplicate_diagnostics(
                requirements,
                prompt_path + ".behavioral_requirements",
                "requirement",
                prompt_id,
            )
        )

        variable_positions = defaultdict(list)
        for variable_index, variable in enumerate(variables):
            if isinstance(variable.get("name"), str):
                variable_positions[variable.get("name")].append(variable_index)
        for name, positions in variable_positions.items():
            if isinstance(name, str) and len(positions) > 1:
                diagnostics.append(
                    Diagnostic(
                        "duplicate_id",
                        prompt_path + ".variables",
                        "Duplicate variable name %r at indexes %s" % (name, positions),
                        prompt_id,
                    )
                )

        revision_ids = {
            item.get("id") for item in revisions if isinstance(item.get("id"), str)
        }
        sequences = defaultdict(list)
        for revision_index, revision in enumerate(revisions):
            revision_id = revision.get("id")
            if isinstance(revision_id, str):
                if revision_id in revision_owner:
                    diagnostics.append(
                        Diagnostic(
                            "duplicate_id",
                            prompt_path + ".revisions[%d].id" % revision_index,
                            "Revision ID %r is also owned by prompt %r"
                            % (revision_id, revision_owner[revision_id]),
                            prompt_id,
                        )
                    )
                revision_owner[revision_id] = prompt_id
            if isinstance(revision.get("sequence"), int) and not isinstance(
                revision.get("sequence"), bool
            ):
                sequences[revision.get("sequence")].append(revision_index)
            parent_id = revision.get("parent_revision_id")
            if isinstance(parent_id, str) and parent_id not in revision_ids:
                diagnostics.append(
                    _reference_error(
                        prompt_path
                        + ".revisions[%d].parent_revision_id" % revision_index,
                        "Unknown parent revision ID %r" % parent_id,
                        prompt_id,
                    )
                )
        for sequence, positions in sequences.items():
            if sequence is not None and len(positions) > 1:
                diagnostics.append(
                    Diagnostic(
                        "duplicate_sequence",
                        prompt_path + ".revisions",
                        "Duplicate revision sequence %r at indexes %s"
                        % (sequence, positions),
                        prompt_id,
                    )
                )

        current_revision_id = prompt.get("current_revision_id")
        if (
            isinstance(current_revision_id, str)
            and current_revision_id not in revision_ids
        ):
            diagnostics.append(
                _reference_error(
                    prompt_path + ".current_revision_id",
                    "Unknown current revision ID %r" % current_revision_id,
                    prompt_id,
                )
            )
        finalization = prompt.get("finalization")
        if (
            isinstance(finalization, dict)
            and isinstance(finalization.get("revision_id"), str)
            and finalization.get("revision_id") not in revision_ids
        ):
            diagnostics.append(
                _reference_error(
                    prompt_path + ".finalization.revision_id",
                    "Unknown finalized revision ID %r"
                    % finalization.get("revision_id"),
                    prompt_id,
                )
            )
        for history_index, event in enumerate(
            _as_list(prompt.get("finalization_history"))
        ):
            if (
                isinstance(event, dict)
                and isinstance(event.get("revision_id"), str)
                and event.get("revision_id") not in revision_ids
            ):
                diagnostics.append(
                    _reference_error(
                        prompt_path
                        + ".finalization_history[%d].revision_id" % history_index,
                        "Unknown finalized revision ID %r" % event.get("revision_id"),
                        prompt_id,
                    )
                )

        declared = {
            item.get("name") for item in variables if isinstance(item.get("name"), str)
        }
        required = {
            item.get("name")
            for item in variables
            if item.get("required") is True and isinstance(item.get("name"), str)
        }
        schemas = {
            item.get("name"): item.get("value_schema")
            for item in variables
            if isinstance(item.get("name"), str)
            and isinstance(item.get("value_schema"), dict)
        }

        from promptimal.template.fields import inspect_template

        for revision_index, revision in enumerate(revisions):
            template = revision.get("prompt_template")
            inspection = inspect_template(template if isinstance(template, str) else "")
            revision_path = (
                prompt_path + ".revisions[%d].prompt_template" % revision_index
            )
            for item in inspection.diagnostics:
                diagnostics.append(
                    Diagnostic(item.code, revision_path, item.message, prompt_id)
                )
            for field_name in inspection.fields:
                if field_name not in declared:
                    diagnostics.append(
                        Diagnostic(
                            "undeclared_placeholder",
                            revision_path,
                            "Template field %r has no variable declaration"
                            % field_name,
                            prompt_id,
                        )
                    )

        for case_index, test_case in enumerate(test_cases):
            values = test_case.get("values", {})
            if not isinstance(values, dict):
                continue
            case_path = prompt_path + ".test_cases[%d].values" % case_index
            for name in sorted(required - set(values)):
                diagnostics.append(
                    Diagnostic(
                        "missing_case_value",
                        case_path,
                        "Required variable %r has no test-case value" % name,
                        prompt_id,
                    )
                )
            for name in sorted(set(values) - declared):
                diagnostics.append(
                    Diagnostic(
                        "undeclared_case_value",
                        case_path + "[%s]" % json.dumps(name),
                        "Test-case value %r has no variable declaration" % name,
                        prompt_id,
                    )
                )
            for name, value in values.items():
                if name not in schemas:
                    continue
                try:
                    value_validator = Draft202012Validator(
                        schemas[name], format_checker=FormatChecker()
                    )
                except SchemaError as exc:
                    diagnostics.append(
                        Diagnostic(
                            "invalid_value_schema",
                            case_path + "[%s]" % json.dumps(name),
                            "Invalid value schema for %r: %s" % (name, exc),
                            prompt_id,
                        )
                    )
                    continue
                for error in value_validator.iter_errors(value):
                    diagnostics.append(
                        Diagnostic(
                            "invalid_case_value",
                            case_path + "[%s]" % json.dumps(name),
                            error.message,
                            prompt_id,
                        )
                    )

        evaluation_plan = prompt.get("evaluation_plan")
        evaluation_plan = evaluation_plan if isinstance(evaluation_plan, dict) else {}
        task_plan = evaluation_plan.get("task")
        task_plan = task_plan if isinstance(task_plan, dict) else {}
        evaluator_profile_id = task_plan.get("evaluator_profile_id")
        if (
            isinstance(evaluator_profile_id, str)
            and evaluator_profile_id not in profile_ids
        ):
            diagnostics.append(
                _reference_error(
                    prompt_path + ".evaluation_plan.task.evaluator_profile_id",
                    "Unknown evaluator profile ID %r" % evaluator_profile_id,
                    prompt_id,
                )
            )

    for result_index, result in enumerate(result_sets):
        result_path = "$.result_sets[%d]" % result_index
        prompt_id = (
            result.get("prompt_id")
            if isinstance(result.get("prompt_id"), str)
            else None
        )
        prompt = prompt_by_id.get(prompt_id) if prompt_id is not None else None
        if not prompt:
            diagnostics.append(
                _reference_error(
                    result_path + ".prompt_id", "Unknown prompt ID %r" % prompt_id
                )
            )
        elif isinstance(result.get("revision_id"), str) and result.get(
            "revision_id"
        ) not in {
            item.get("id")
            for item in _as_list(prompt.get("revisions"))
            if isinstance(item, dict)
        }:
            diagnostics.append(
                _reference_error(
                    result_path + ".revision_id",
                    "Revision %r does not belong to prompt %r"
                    % (result.get("revision_id"), prompt_id),
                    prompt_id,
                )
            )
        if (
            isinstance(result.get("execution_profile_id"), str)
            and result.get("execution_profile_id") not in profile_ids
        ):
            diagnostics.append(
                _reference_error(
                    result_path + ".execution_profile_id",
                    "Unknown execution profile ID %r"
                    % result.get("execution_profile_id"),
                    prompt_id,
                )
            )
        snapshot = result.get("operation_snapshot")
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        case_ids = {
            item.get("id")
            for item in _as_list(snapshot.get("test_cases"))
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        target_ids = {
            item.get("id")
            for item in _as_list(result.get("targets"))
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        for execution_index, execution in enumerate(_as_list(result.get("executions"))):
            if not isinstance(execution, dict):
                continue
            execution_ids.append(
                (
                    execution.get("id"),
                    result_path + ".executions[%d].id" % execution_index,
                )
            )
            if (
                isinstance(execution.get("test_case_id"), str)
                and execution.get("test_case_id") not in case_ids
            ):
                diagnostics.append(
                    _reference_error(
                        result_path + ".executions[%d].test_case_id" % execution_index,
                        "Unknown snapshot test-case ID %r"
                        % execution.get("test_case_id"),
                        prompt_id,
                    )
                )
            if (
                isinstance(execution.get("target_id"), str)
                and execution.get("target_id") not in target_ids
            ):
                diagnostics.append(
                    _reference_error(
                        result_path + ".executions[%d].target_id" % execution_index,
                        "Unknown result target ID %r" % execution.get("target_id"),
                        prompt_id,
                    )
                )

    execution_positions = defaultdict(list)
    for execution_id, path in execution_ids:
        if isinstance(execution_id, str):
            execution_positions[execution_id].append(path)
    for execution_id, paths in execution_positions.items():
        if len(paths) > 1:
            diagnostics.append(
                Diagnostic(
                    "duplicate_id",
                    "$.result_sets",
                    "Duplicate execution ID %r at %s" % (execution_id, paths),
                )
            )

    candidate_locations = defaultdict(list)
    for run_index, run in enumerate(evolution_runs):
        run_path = "$.evolution_runs[%d]" % run_index
        prompt_id = (
            run.get("prompt_id") if isinstance(run.get("prompt_id"), str) else None
        )
        prompt = prompt_by_id.get(prompt_id) if prompt_id is not None else None
        if not prompt:
            diagnostics.append(
                _reference_error(
                    run_path + ".prompt_id", "Unknown prompt ID %r" % prompt_id
                )
            )
        else:
            revision_ids = {
                item.get("id")
                for item in _as_list(prompt.get("revisions"))
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            if (
                isinstance(run.get("parent_revision_id"), str)
                and run.get("parent_revision_id") not in revision_ids
            ):
                diagnostics.append(
                    _reference_error(
                        run_path + ".parent_revision_id",
                        "Unknown parent revision ID %r" % run.get("parent_revision_id"),
                        prompt_id,
                    )
                )
            adopted_revision = run.get("adopted_revision_id")
            if (
                isinstance(adopted_revision, str)
                and adopted_revision not in revision_ids
            ):
                diagnostics.append(
                    _reference_error(
                        run_path + ".adopted_revision_id",
                        "Unknown adopted revision ID %r" % adopted_revision,
                        prompt_id,
                    )
                )
        if (
            isinstance(run.get("execution_profile_id"), str)
            and run.get("execution_profile_id") not in profile_ids
        ):
            diagnostics.append(
                _reference_error(
                    run_path + ".execution_profile_id",
                    "Unknown execution profile ID %r" % run.get("execution_profile_id"),
                    prompt_id,
                )
            )
        for generation_index, generation in enumerate(_as_list(run.get("generations"))):
            if not isinstance(generation, dict):
                continue
            for candidate_index, candidate in enumerate(
                _as_list(generation.get("candidates"))
            ):
                if not isinstance(candidate, dict):
                    continue
                candidate_id = candidate.get("id")
                candidate_path = run_path + ".generations[%d].candidates[%d]" % (
                    generation_index,
                    candidate_index,
                )
                if isinstance(candidate_id, str):
                    candidate_ids.add(candidate_id)
                    candidate_owner.setdefault(candidate_id, prompt_id)
                    candidate_locations[candidate_id].append(candidate_path)
                result_id = candidate.get("result_set_id")
                if isinstance(result_id, str) and result_id not in result_ids:
                    diagnostics.append(
                        _reference_error(
                            candidate_path + ".result_set_id",
                            "Unknown result-set ID %r" % result_id,
                            prompt_id,
                        )
                    )
                elif (
                    isinstance(result_id, str)
                    and result_by_id[result_id].get("prompt_id") != prompt_id
                ):
                    diagnostics.append(
                        _reference_error(
                            candidate_path + ".result_set_id",
                            "Result set %r belongs to a different prompt" % result_id,
                            prompt_id,
                        )
                    )
        run_candidates = {
            candidate.get("id")
            for generation in _as_list(run.get("generations"))
            if isinstance(generation, dict)
            for candidate in _as_list(generation.get("candidates"))
            if isinstance(candidate, dict) and isinstance(candidate.get("id"), str)
        }
        for generation_index, generation in enumerate(_as_list(run.get("generations"))):
            if not isinstance(generation, dict):
                continue
            for candidate_index, candidate in enumerate(
                _as_list(generation.get("candidates"))
            ):
                if not isinstance(candidate, dict):
                    continue
                for parent_index, parent_id in enumerate(
                    _as_list(candidate.get("parent_candidate_ids"))
                ):
                    if (
                        isinstance(parent_id, str)
                        and parent_id not in all_candidate_ids
                    ):
                        diagnostics.append(
                            _reference_error(
                                run_path
                                + ".generations[%d].candidates[%d].parent_candidate_ids[%d]"
                                % (generation_index, candidate_index, parent_index),
                                "Unknown parent candidate ID %r" % parent_id,
                                prompt_id,
                            )
                        )
        selected = run.get("selected_candidate_id")
        if isinstance(selected, str):
            if selected not in run_candidates:
                diagnostics.append(
                    _reference_error(
                        run_path + ".selected_candidate_id",
                        "Unknown selected candidate ID %r" % selected,
                        prompt_id,
                    )
                )

    for candidate_id, locations in candidate_locations.items():
        if len(locations) > 1:
            diagnostics.append(
                Diagnostic(
                    "duplicate_id",
                    "$.evolution_runs",
                    "Duplicate candidate ID %r at %s" % (candidate_id, locations),
                )
            )

    for prompt_index, prompt in enumerate(prompts):
        prompt_id = prompt.get("id") if isinstance(prompt.get("id"), str) else None
        for revision_index, revision in enumerate(_as_list(prompt.get("revisions"))):
            if not isinstance(revision, dict):
                continue
            origin = revision.get("origin", {})
            source_candidate = (
                origin.get("source_candidate_id") if isinstance(origin, dict) else None
            )
            if (
                isinstance(source_candidate, str)
                and source_candidate not in candidate_ids
            ):
                diagnostics.append(
                    _reference_error(
                        "$.prompts[%d].revisions[%d].origin.source_candidate_id"
                        % (prompt_index, revision_index),
                        "Unknown source candidate ID %r" % source_candidate,
                        prompt_id,
                    )
                )
            elif (
                isinstance(source_candidate, str)
                and candidate_owner.get(source_candidate) != prompt_id
            ):
                diagnostics.append(
                    _reference_error(
                        "$.prompts[%d].revisions[%d].origin.source_candidate_id"
                        % (prompt_index, revision_index),
                        "Source candidate %r belongs to a different prompt"
                        % source_candidate,
                        prompt_id,
                    )
                )

    return diagnostics
