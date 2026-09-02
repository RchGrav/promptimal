from __future__ import annotations

import asyncio
import copy
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from promptimal.evaluation.engine import empty_evaluation, evaluate_response
from promptimal.evaluation.metrics import build_result_summary
from promptimal.evaluation.parse import parse_output
from promptimal.evaluation.semantic import (
    apply_semantic_consensus,
    semantic_observations,
)
from promptimal.execution.models import new_id, planned_execution
from promptimal.execution.openrouter import OpenRouterChatCompletionsAdapter
from promptimal.sheet.models import PromptSheet, utc_now
from promptimal.template.expand import expand_template


ProgressCallback = Callable[[Dict[str, Any], Dict[str, Any]], Optional[Awaitable[None]]]


class ExecutionRunner:
    def __init__(
        self,
        sheet: PromptSheet,
        api_key: Optional[str] = None,
        client: Optional[Any] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> None:
        self.sheet = sheet
        self.api_key = api_key
        self.client = client
        self.progress_callback = progress_callback
        self._save_lock = asyncio.Lock()
        self._evaluator_semaphores = {}

    async def _persist(self, result_set: Dict[str, Any]) -> None:
        result_set["summary"] = build_result_summary(result_set["executions"])
        if self.sheet.path is not None:
            async with self._save_lock:
                self.sheet.save()

    async def _notify(
        self, result_set: Dict[str, Any], execution: Dict[str, Any]
    ) -> None:
        if not self.progress_callback:
            return
        value = self.progress_callback(result_set, execution)
        if value is not None:
            await value

    @staticmethod
    def _selected(
        records: Iterable[Dict[str, Any]], selected_ids: Optional[Iterable[str]]
    ) -> List[Dict[str, Any]]:
        records = list(records)
        if selected_ids is None:
            return records
        wanted = set(selected_ids)
        selected = [item for item in records if item.get("id") in wanted]
        missing = wanted - {item.get("id") for item in selected}
        if missing:
            raise KeyError("Unknown selected IDs: %s" % ", ".join(sorted(missing)))
        return selected

    def prepare(
        self,
        prompt_id: str,
        revision_id: Optional[str] = None,
        execution_profile_id: Optional[str] = None,
        test_case_ids: Optional[Iterable[str]] = None,
        target_ids: Optional[Iterable[str]] = None,
        runs_per_case: Optional[int] = None,
        prompt_template: Optional[str] = None,
    ) -> Dict[str, Any]:
        prompt = self.sheet.prompt(prompt_id)
        revision = self.sheet.revision(prompt, revision_id)
        profile = self.sheet.execution_profile(execution_profile_id)
        cases = self._selected(prompt.get("test_cases", []), test_case_ids)
        enabled_targets = [
            item for item in profile.get("targets", []) if item.get("enabled") is True
        ]
        targets = self._selected(enabled_targets, target_ids)
        repeat_count = (
            profile["runs_per_case"] if runs_per_case is None else runs_per_case
        )
        if repeat_count < 1:
            raise ValueError("runs_per_case must be at least 1")
        if not cases:
            raise ValueError("At least one test case must be selected")
        if not targets:
            raise ValueError("At least one enabled target must be selected")

        operation_snapshot = self.sheet.operation_snapshot(prompt_id)
        operation_snapshot["test_cases"] = copy.deepcopy(cases)
        result_set_id = new_id("result")
        result_set = {
            "id": result_set_id,
            "prompt_id": prompt_id,
            "revision_id": revision["id"],
            "execution_profile_id": profile["id"],
            "execution_profile_snapshot": {
                **copy.deepcopy(profile),
                "runs_per_case": repeat_count,
                "targets": copy.deepcopy(targets),
            },
            "operation_snapshot": operation_snapshot,
            "status": "running",
            "started_at": utc_now(),
            "completed_at": None,
            "runs_per_case": repeat_count,
            "targets": copy.deepcopy(targets),
            "executions": [],
            "summary": None,
        }

        template = (
            prompt_template
            if prompt_template is not None
            else revision["prompt_template"]
        )
        expansions = {}
        for test_case in cases:
            expansion = expand_template(
                template, prompt.get("variables", []), test_case.get("values", {})
            )
            expansions[test_case["id"]] = expansion

        for target in targets:
            for test_case in cases:
                expansion = expansions[test_case["id"]]
                expansion_error = None
                if expansion.diagnostics:
                    expansion_error = {
                        "type": "TemplateExpansionError",
                        "diagnostics": [
                            {"code": item.code, "message": item.message}
                            for item in expansion.diagnostics
                        ],
                    }
                for trial in range(1, repeat_count + 1):
                    execution_id = "%s.%s.%s.%d" % (
                        result_set_id,
                        target["id"],
                        test_case["id"],
                        trial,
                    )
                    result_set["executions"].append(
                        planned_execution(
                            execution_id,
                            test_case["id"],
                            target,
                            trial,
                            expansion.text,
                            expansion_error,
                        )
                    )
        self.sheet.result_sets.append(result_set)
        return result_set

    async def run(
        self,
        prompt_id: str,
        revision_id: Optional[str] = None,
        execution_profile_id: Optional[str] = None,
        test_case_ids: Optional[Iterable[str]] = None,
        target_ids: Optional[Iterable[str]] = None,
        runs_per_case: Optional[int] = None,
        prompt_template: Optional[str] = None,
    ) -> Dict[str, Any]:
        testing_saved_revision = prompt_template is None
        result_set = self.prepare(
            prompt_id,
            revision_id,
            execution_profile_id,
            test_case_ids,
            target_ids,
            runs_per_case,
            prompt_template,
        )
        profile = self.sheet.execution_profile(result_set["execution_profile_id"])
        target_by_id = {item["id"]: item for item in result_set["targets"]}
        case_by_id = {
            item["id"]: item for item in result_set["operation_snapshot"]["test_cases"]
        }
        adapter = OpenRouterChatCompletionsAdapter(
            timeout_seconds=profile["timeout_seconds"],
            max_transport_retries=profile["max_transport_retries"],
            api_key=self.api_key,
            client=self.client,
        )
        semaphore = asyncio.Semaphore(profile["max_concurrency"])

        await self._persist(result_set)

        async def execute_one(execution: Dict[str, Any]) -> None:
            if execution["response"]["status"] == "expansion_error":
                await self._notify(result_set, execution)
                return
            target = target_by_id[execution["target_id"]]
            test_case = case_by_id[execution["test_case_id"]]
            if target.get("adapter") != adapter.adapter_name:
                execution["response"] = {
                    **execution["response"],
                    "status": "api_error",
                    "error": {
                        "type": "UnknownAdapter",
                        "message": "Unsupported adapter %r" % target.get("adapter"),
                    },
                }
                execution["evaluation"] = empty_evaluation("api_error")
            else:
                async with semaphore:
                    response = await adapter.execute(
                        target, execution["request"]["messages"]
                    )
                execution["response"] = response
                if response["status"] == "ok":
                    raw_output = response.get("raw_output")
                    try:
                        parsed = parse_output(
                            raw_output,
                            result_set["operation_snapshot"]["output_contract"][
                                "media_type"
                            ],
                        )
                        response["parsed_output"] = (
                            parsed.value if parsed.status == "pass" else None
                        )
                        execution["evaluation"] = evaluate_response(
                            raw_output,
                            result_set["operation_snapshot"],
                            test_case,
                        )
                    except Exception as exc:
                        execution["evaluation"] = empty_evaluation(
                            "evaluation_error",
                            "Evaluation failed with %s: %s" % (type(exc).__name__, exc),
                        )
                    else:
                        finish_reason = response.get("finish_reason")
                        if finish_reason not in (None, "stop"):
                            execution["evaluation"]["failure_tags"].append(
                                "finish_reason:%s" % finish_reason
                            )
                        evaluator_profile_id = result_set["operation_snapshot"][
                            "evaluation_plan"
                        ]["task"].get("evaluator_profile_id")
                        needs_semantic_evaluation = execution["evaluation"]["task"][
                            "status"
                        ] == "unknown" or any(
                            item["status"] == "unknown"
                            for item in execution["evaluation"]["requirements"]
                        )
                        if evaluator_profile_id and needs_semantic_evaluation:
                            try:
                                evaluator_profile = self.sheet.execution_profile(
                                    evaluator_profile_id
                                )
                                evaluator_semaphore = (
                                    self._evaluator_semaphores.setdefault(
                                        evaluator_profile_id,
                                        asyncio.Semaphore(
                                            evaluator_profile["max_concurrency"]
                                        ),
                                    )
                                )
                                observations = await semantic_observations(
                                    execution,
                                    result_set["operation_snapshot"],
                                    test_case,
                                    evaluator_profile,
                                    api_key=self.api_key,
                                    client=self.client,
                                    semaphore=evaluator_semaphore,
                                )
                                apply_semantic_consensus(
                                    execution["evaluation"], observations
                                )
                            except Exception as exc:
                                execution["evaluation"]["failure_tags"].append(
                                    "semantic_evaluation_error:%s" % type(exc).__name__
                                )
                                if (
                                    execution["evaluation"]["task"]["status"]
                                    == "unknown"
                                ):
                                    execution["evaluation"]["task"]["details"] = (
                                        "Semantic evaluation failed with %s: %s"
                                        % (type(exc).__name__, exc)
                                    )
                else:
                    execution["evaluation"] = empty_evaluation(response["status"])
            await self._persist(result_set)
            await self._notify(result_set, execution)

        tasks = [
            asyncio.create_task(execute_one(execution))
            for execution in result_set["executions"]
        ]
        try:
            if tasks:
                await asyncio.gather(*tasks)
            result_set["status"] = "completed"
            result_set["completed_at"] = utc_now()
            if testing_saved_revision:
                self.sheet.refresh_prompt_state(prompt_id)
            await self._persist(result_set)
            return result_set
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            result_set["status"] = "cancelled"
            result_set["completed_at"] = utc_now()
            await self._persist(result_set)
            return result_set
        except Exception:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            result_set["status"] = "failed"
            result_set["completed_at"] = utc_now()
            await self._persist(result_set)
            raise


async def run_prompt_test(
    sheet: PromptSheet, prompt_id: str, **kwargs
) -> Dict[str, Any]:
    runner_arguments = {
        key: kwargs.pop(key)
        for key in ("api_key", "client", "progress_callback")
        if key in kwargs
    }
    return await ExecutionRunner(sheet, **runner_arguments).run(prompt_id, **kwargs)
