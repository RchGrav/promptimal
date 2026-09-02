import asyncio

from promptimal.capability import capability_matrix
from promptimal.execution.runner import ExecutionRunner

from conftest import FakeClient


def test_capability_matrix_is_derived_from_stored_results(memory_sheet):
    result = asyncio.run(
        ExecutionRunner(memory_sheet, client=FakeClient()).run(
            "namespace.aliases",
            test_case_ids=["cplusplus"],
            target_ids=["frontier-a"],
            runs_per_case=1,
        )
    )
    view = capability_matrix(memory_sheet, cost_ceiling=0.01)
    assert view["models"] == ["provider/model-a"]
    cell = view["matrix"][0]["prompts"]["namespace.aliases"]
    assert cell["result_set_id"] == result["id"]
    quality_cost = view["quality_cost"]["namespace.aliases"]
    assert quality_cost["strongest_within_ceiling"]["model"] == "provider/model-a"
