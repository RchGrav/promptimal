import copy

from promptimal.evaluation.engine import evaluate_response
from promptimal.evaluation.metrics import build_result_summary
from promptimal.evaluation.review import apply_human_review
from promptimal.evaluation.semantic import apply_semantic_consensus, evaluator_payload


def operation(memory_sheet):
    return memory_sheet.operation_snapshot("namespace.aliases")


def test_malformed_json_is_not_repaired(memory_sheet):
    case = memory_sheet.prompt("namespace.aliases")["test_cases"][0]
    evaluated = evaluate_response(
        "```json\n['c++', 'cpp']\n```", operation(memory_sheet), case
    )
    assert evaluated["contract"]["status"] == "fail"
    assert evaluated["task"]["status"] == "not_run"
    assert evaluated["normalized_output"] is None


def test_unordered_comparison_preserves_duplicates(memory_sheet):
    case = copy.deepcopy(memory_sheet.prompt("namespace.aliases")["test_cases"][0])
    case["intended_response"]["value"] = ["cpp", "cpp", "c++"]
    passed = evaluate_response('["cpp", "c++", "cpp"]', operation(memory_sheet), case)
    failed = evaluate_response('["cpp", "c++"]', operation(memory_sheet), case)
    assert passed["task"]["status"] == "pass"
    assert failed["task"]["status"] == "fail"


def test_representative_answer_is_not_silently_treated_as_exhaustive(memory_sheet):
    case = copy.deepcopy(memory_sheet.prompt("namespace.aliases")["test_cases"][0])
    case["intended_response"]["kind"] = "representative"
    evaluated = evaluate_response('["c++", "cpp"]', operation(memory_sheet), case)
    assert evaluated["task"]["status"] == "unknown"


def _execution(identifier, target, case, normalized, task_status, response_status="ok"):
    return {
        "id": identifier,
        "target_id": target,
        "test_case_id": case,
        "response": {"status": response_status},
        "evaluation": {
            "normalized_output": normalized,
            "task": {"status": task_status},
            "contract": {"status": "pass" if response_status == "ok" else "not_run"},
            "requirements": [],
            "failure_tags": [],
        },
    }


def test_unanimous_wrong_is_agreement_not_correctness():
    executions = [
        _execution("a", "m1", "case", ["wrong"], "fail"),
        _execution("b", "m1", "case", ["wrong"], "fail"),
        _execution("c", "m2", "case", ["wrong"], "fail"),
        _execution("d", "m2", "case", ["wrong"], "fail"),
    ]
    metrics = build_result_summary(executions)["metrics"]
    assert metrics["task_success_rate"] == 0
    assert metrics["within_model_repeatability"] == 1
    assert metrics["cross_model_agreement"] == 1


def test_transport_errors_are_excluded_from_behavioral_denominators():
    executions = [
        _execution("a", "m1", "case", ["ok"], "pass"),
        _execution("b", "m1", "case", None, "not_run", "timeout"),
    ]
    metrics = build_result_summary(executions)["metrics"]
    assert metrics["execution_coverage"] == 0.5
    assert metrics["task_success_rate"] == 1
    assert metrics["within_model_repeatability"] is None


def test_human_review_retains_provenance():
    execution = _execution("a", "m1", "case", ["answer"], "unknown")
    execution["evaluation"]["observations"] = []
    observation = apply_human_review(execution, "pass", "reviewed cluster", 1.0)
    assert observation["kind"] == "human"
    assert execution["evaluation"]["task"]["provenance"] == "human"


def test_semantic_payload_excludes_prompt_template_and_consensus_is_visible(
    memory_sheet,
):
    op = operation(memory_sheet)
    case = copy.deepcopy(memory_sheet.prompt("namespace.aliases")["test_cases"][0])
    case["intended_response"]["kind"] = "representative"
    payload = evaluator_payload(op, case, '["cpp"]')
    assert "prompt_template" not in payload
    evaluation = evaluate_response('["other"]', op, case)
    observation = {
        "id": "obs.1",
        "kind": "semantic_evaluator",
        "evaluator_target_id": "judge",
        "recorded_at": "2026-09-02T00:00:00Z",
        "request": {},
        "response": {},
        "requirement_results": [
            {"id": item["id"], "status": "pass", "details": "observed"}
            for item in op["behavioral_requirements"]
        ],
        "task_result": {
            "status": "fail",
            "score": 0.0,
            "method": "semantic_criteria",
            "details": "wrong response",
            "provenance": "semantic_evaluator",
        },
    }
    apply_semantic_consensus(evaluation, [observation])
    assert evaluation["task"]["status"] == "fail"
    assert evaluation["task"]["provenance"] == "semantic_evaluator"
    assert evaluation["observations"][0]["response"] == {}
