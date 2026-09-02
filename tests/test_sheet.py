import copy
import json

import pytest

from promptimal.sheet import PromptSheet, PromptSheetLoadError
from promptimal.sheet.store import write_json_atomic


def test_supplied_example_loads_and_expands(memory_sheet):
    assert memory_sheet.validate() == []
    prompt = memory_sheet.prompt("namespace.aliases")
    revision = memory_sheet.revision(prompt)
    for test_case in prompt["test_cases"]:
        from promptimal.template.expand import expand_template

        result = expand_template(
            revision["prompt_template"], prompt["variables"], test_case["values"]
        )
        assert result.valid
        assert result.text


def test_invalid_json_is_not_repaired(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"format": trailing}', encoding="utf-8")
    with pytest.raises(PromptSheetLoadError):
        PromptSheet.load(path)


def test_duplicate_and_broken_references_are_record_local(sheet_data):
    data = copy.deepcopy(sheet_data)
    data["prompts"].append(copy.deepcopy(data["prompts"][0]))
    data["prompts"][0]["current_revision_id"] = "missing.revision"
    sheet = PromptSheet(data)
    diagnostics = sheet.validate()
    assert any(item.code == "duplicate_id" for item in diagnostics)
    assert any(
        item.code == "broken_reference" and item.prompt_id == "namespace.aliases"
        for item in diagnostics
    )


def test_schema_invalid_record_is_reported_without_aborting_other_records(sheet_data):
    data = copy.deepcopy(sheet_data)
    data["prompts"][0]["evaluation_plan"] = None
    data["execution_profiles"][0]["targets"] = None
    sheet = PromptSheet(data)
    diagnostics = sheet.validate()
    assert any(item.code == "schema" for item in diagnostics)
    assert sheet.data["prompts"][0]["id"] == "namespace.aliases"


def test_round_trip_preserves_semantic_content(tmp_path, sheet_data):
    path = tmp_path / "sheet.json"
    path.write_text(json.dumps(sheet_data), encoding="utf-8")
    sheet = PromptSheet.load(path)
    before = copy.deepcopy(sheet.data)
    sheet.save()
    after = PromptSheet.load(path).data
    before.pop("updated_at")
    after.pop("updated_at")
    assert after == before


def test_atomic_failure_leaves_previous_file(monkeypatch, tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"old": true}\n', encoding="utf-8")

    def fail_replace(*_):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr("promptimal.sheet.store.os.replace", fail_replace)
    with pytest.raises(OSError):
        write_json_atomic({"new": True}, path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}


def test_candidate_parent_reference_is_validated(memory_sheet):
    memory_sheet.data["evolution_runs"] = [
        {
            "id": "run.1",
            "prompt_id": "namespace.aliases",
            "parent_revision_id": "namespace.aliases.r0001",
            "execution_profile_id": "frontier-core",
            "mutator_target": copy.deepcopy(
                memory_sheet.execution_profiles[0]["targets"][0]
            ),
            "population_size": 1,
            "generation_limit": 1,
            "status": "running",
            "started_at": "2026-09-02T00:00:00Z",
            "completed_at": None,
            "generations": [
                {
                    "index": 0,
                    "candidates": [
                        {
                            "id": "candidate.1",
                            "parent_candidate_ids": ["candidate.missing"],
                            "prompt_template": "{name} {description} {namespace} {identifier} {prefix}",
                            "status": "generated",
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
    ]
    diagnostics = memory_sheet.validate()
    assert any(
        item.code == "broken_reference" and "parent candidate" in item.message
        for item in diagnostics
    )
