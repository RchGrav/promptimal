import asyncio
import copy
import json

import pytest

from promptimal.execution.openrouter import OpenRouterChatCompletionsAdapter
from promptimal.execution.runner import ExecutionRunner
from promptimal.sheet import PromptSheet

from conftest import FakeClient, response


def test_exact_matrix_and_request_snapshot(memory_sheet):
    client = FakeClient()
    result = asyncio.run(
        ExecutionRunner(memory_sheet, client=client).run(
            "namespace.aliases",
            test_case_ids=["cplusplus", "javascript"],
            runs_per_case=3,
        )
    )
    assert len(result["executions"]) == 2 * 2 * 3
    assert len(client.completions.calls) == 12
    assert client.completions.maximum_active <= 8
    call = client.completions.calls[0]
    assert call["model"] == "provider/model-a"
    assert call["extra_body"] == {"temperature": 0}
    assert "response_format" not in call["extra_body"]
    execution = result["executions"][0]
    assert execution["request"]["expanded_prompt"] == call["messages"][0]["content"]
    assert result["execution_profile_snapshot"]["runs_per_case"] == 3
    assert result["execution_profile_snapshot"]["max_concurrency"] == 8


def test_provider_routing_and_returned_metadata(memory_sheet):
    target = memory_sheet.execution_profiles[0]["targets"][0]
    target["provider_routing"] = {"order": ["provider-a"], "allow_fallbacks": False}
    client = FakeClient([response(model="fallback/model", provider="provider-b")])
    result = asyncio.run(
        ExecutionRunner(memory_sheet, client=client).run(
            "namespace.aliases",
            test_case_ids=["cplusplus"],
            target_ids=["frontier-a"],
            runs_per_case=1,
        )
    )
    assert (
        client.completions.calls[0]["extra_body"]["provider"]
        == target["provider_routing"]
    )
    recorded = result["executions"][0]["response"]
    assert recorded["returned_model"] == "fallback/model"
    assert recorded["provider"] == "provider-b"
    assert recorded["usage"]["cost"] == pytest.approx(0.001)


def test_retries_are_explicit_and_every_attempt_is_retained(memory_sheet):
    memory_sheet.execution_profiles[0]["max_transport_retries"] = 1
    client = FakeClient([ConnectionError("transient"), response()])
    result = asyncio.run(
        ExecutionRunner(memory_sheet, client=client).run(
            "namespace.aliases",
            test_case_ids=["cplusplus"],
            target_ids=["frontier-a"],
            runs_per_case=1,
        )
    )
    attempts = result["executions"][0]["response"]["transport_attempts"]
    assert [item["status"] for item in attempts] == ["api_error", "ok"]
    assert len(client.completions.calls) == 2


def test_non_retryable_api_error_is_not_replayed(memory_sheet):
    class BadRequestError(Exception):
        status_code = 400

    memory_sheet.execution_profiles[0]["max_transport_retries"] = 3
    client = FakeClient([BadRequestError("invalid request")])
    result = asyncio.run(
        ExecutionRunner(memory_sheet, client=client).run(
            "namespace.aliases",
            test_case_ids=["cplusplus"],
            target_ids=["frontier-a"],
            runs_per_case=1,
        )
    )
    assert len(client.completions.calls) == 1
    assert result["executions"][0]["response"]["status"] == "api_error"


def test_timeout_is_not_a_task_failure(memory_sheet):
    profile = memory_sheet.execution_profiles[0]
    profile["timeout_seconds"] = 0.001
    profile["max_transport_retries"] = 0
    client = FakeClient(delay=0.02)
    result = asyncio.run(
        ExecutionRunner(memory_sheet, client=client).run(
            "namespace.aliases",
            test_case_ids=["cplusplus"],
            target_ids=["frontier-a"],
            runs_per_case=1,
        )
    )
    execution = result["executions"][0]
    assert execution["response"]["status"] == "timeout"
    assert execution["evaluation"]["task"]["status"] == "not_run"
    assert result["summary"]["metrics"]["execution_coverage"] == 0


def test_concurrency_limit_is_respected(memory_sheet):
    memory_sheet.execution_profiles[0]["max_concurrency"] = 2
    client = FakeClient(delay=0.01)
    asyncio.run(
        ExecutionRunner(memory_sheet, client=client).run(
            "namespace.aliases", runs_per_case=2
        )
    )
    assert client.completions.maximum_active == 2


def test_partial_results_survive_cancellation(tmp_path, sheet_data):
    path = tmp_path / "sheet.json"
    sheet = PromptSheet(copy.deepcopy(sheet_data), path=path)
    sheet.execution_profiles[0]["max_concurrency"] = 1
    client = FakeClient(delay=0.02)

    async def cancel_mid_run():
        task = asyncio.create_task(
            ExecutionRunner(sheet, client=client).run(
                "namespace.aliases", runs_per_case=4
            )
        )
        for _ in range(100):
            if sheet.result_sets and any(
                item["response"]["status"] == "ok"
                for item in sheet.result_sets[-1]["executions"]
            ):
                break
            await asyncio.sleep(0.01)
        task.cancel()
        return await task

    result = asyncio.run(cancel_mid_run())
    assert result["status"] == "cancelled"
    assert any(item["response"]["status"] == "ok" for item in result["executions"])
    assert any(
        item["response"]["status"] == "cancelled" for item in result["executions"]
    )
    reloaded = PromptSheet.load(path)
    assert reloaded.result_sets[-1]["status"] == "cancelled"
    assert len(reloaded.result_sets[-1]["executions"]) == 2 * 3 * 4


def test_expansion_errors_create_records_without_requests(memory_sheet):
    memory_sheet.prompt("namespace.aliases")["revisions"][0]["prompt_template"] = (
        "{missing}"
    )
    client = FakeClient()
    result = asyncio.run(
        ExecutionRunner(memory_sheet, client=client).run(
            "namespace.aliases",
            test_case_ids=["cplusplus"],
            target_ids=["frontier-a"],
        )
    )
    assert not client.completions.calls
    assert all(
        item["response"]["status"] == "expansion_error" for item in result["executions"]
    )


def test_adapter_omits_empty_extra_body_fields():
    target = {
        "model": "provider/model",
        "parameters": {},
        "provider_routing": {},
    }
    request = OpenRouterChatCompletionsAdapter.request_kwargs(
        target, [{"role": "user", "content": "exact"}]
    )
    assert request == {
        "model": "provider/model",
        "messages": [{"role": "user", "content": "exact"}],
    }


def test_semantic_evaluator_repeats_and_retains_observations(memory_sheet):
    prompt = memory_sheet.prompt("namespace.aliases")
    prompt["test_cases"][0]["intended_response"] = {
        "kind": "criteria",
        "description": "Contains only common aliases",
        "criteria": ["Only common aliases"],
        "provenance": {"kind": "human_review", "reference": None, "note": None},
    }
    prompt["evaluation_plan"]["task"]["method"] = "semantic_criteria"
    prompt["evaluation_plan"]["task"]["evaluator_profile_id"] = "judge-profile"
    judge = copy.deepcopy(memory_sheet.execution_profiles[0])
    judge["id"] = "judge-profile"
    judge["runs_per_case"] = 2
    judge["targets"] = [copy.deepcopy(judge["targets"][0])]
    judge["targets"][0]["id"] = "judge"
    memory_sheet.execution_profiles.append(judge)
    evaluator_output = json.dumps(
        {
            "requirement_results": [
                {"id": item["id"], "status": "pass", "details": "observed"}
                for item in prompt["behavioral_requirements"]
            ],
            "task_result": {
                "status": "pass",
                "score": 1.0,
                "details": "Meets the stated criteria",
            },
            "explanation": "Grounded in the actual response",
        }
    )
    client = FakeClient(
        [response(), response(evaluator_output), response(evaluator_output)]
    )
    result = asyncio.run(
        ExecutionRunner(memory_sheet, client=client).run(
            "namespace.aliases",
            test_case_ids=["cplusplus"],
            target_ids=["frontier-a"],
            runs_per_case=1,
        )
    )
    evaluation = result["executions"][0]["evaluation"]
    assert evaluation["task"]["status"] == "pass"
    assert evaluation["task"]["provenance"] == "semantic_evaluator"
    assert len(evaluation["observations"]) == 2
    assert all(
        item["request"]["model"] == "provider/model-a"
        for item in evaluation["observations"]
    )
    assert memory_sheet.validate() == []
