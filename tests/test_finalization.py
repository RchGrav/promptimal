import copy
import json

from promptimal.sheet.export import export_finalized, finalized_projection


def test_finalization_is_explicit_and_score_independent(memory_sheet):
    prompt = memory_sheet.prompt("namespace.aliases")
    assert prompt["finalization"] is None
    event = memory_sheet.finalize(prompt["id"], note="approved by reviewer")
    assert prompt["state"] == "finalized"
    assert event == prompt["finalization_history"][-1]


def test_edit_after_finalization_keeps_downstream_revision(memory_sheet):
    prompt = memory_sheet.prompt("namespace.aliases")
    finalized_id = memory_sheet.finalize(prompt["id"])["revision_id"]
    memory_sheet.create_revision(prompt["id"], "edited {name}")
    assert prompt["state"] == "in_refinement"
    assert prompt["finalization"]["revision_id"] == finalized_id
    selected = list(memory_sheet.finalized_prompts())[0]
    assert selected.revision_id == finalized_id
    assert selected.prompt_template != "edited {name}"


def test_projection_omits_unfinalized_and_benchmark_observations(memory_sheet):
    second = copy.deepcopy(memory_sheet.prompts[0])
    second["id"] = "second.prompt"
    second["current_revision_id"] = "second.prompt.r0001"
    second["revisions"][0]["id"] = "second.prompt.r0001"
    second["revisions"][0]["parent_revision_id"] = None
    memory_sheet.prompts.append(second)
    memory_sheet.finalize("namespace.aliases")
    projection = finalized_projection(memory_sheet)
    assert list(projection["prompts"]) == ["namespace.aliases"]
    assert projection["omitted_unfinalized_ids"] == ["second.prompt"]
    assert "result_sets" not in projection
    assert "evolution_runs" not in projection


def test_export_is_machine_readable(tmp_path, memory_sheet):
    memory_sheet.finalize("namespace.aliases")
    path = tmp_path / "finalized.json"
    export_finalized(memory_sheet, path)
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["format"] == "promptimal.finalized-prompts"
    assert (
        value["prompts"]["namespace.aliases"]["revision_id"]
        == "namespace.aliases.r0001"
    )
