from __future__ import annotations

import difflib

import urwid

from promptimal.evaluation.clusters import response_clusters
from promptimal.evaluation.metrics import metric_set
from promptimal.tui.widgets import action, action_bar, pretty, scrollable, section


class ResponsesScreen(urwid.WidgetWrap):
    def __init__(
        self,
        app,
        result_set=None,
        filter_kind="all",
        target_id=None,
        test_case_id=None,
    ) -> None:
        self.app = app
        self.result_set = result_set or app.controller.latest_result()
        self.filter_kind = filter_kind
        self.target_id = target_id
        self.test_case_id = test_case_id
        rows = []
        if not self.result_set:
            rows.append(urwid.Text("No result set has been recorded for this prompt."))
        else:
            rows.extend(self._summary_rows())
            rows.extend(self._matrix_rows())
            rows.extend(self._cluster_rows())
            rows.extend(self._diff_rows())
            rows.extend(self._execution_rows())
        footer = action_bar(
            [
                action("Filter: %s" % filter_kind, self._cycle_filter),
                action("Model: %s" % (target_id or "all"), self._cycle_target),
                action("Case: %s" % (test_case_id or "all"), self._cycle_case),
                action("Run Again", lambda _: app.show_test_run()),
                action("Back", lambda _: app.show_workbench()),
            ]
        )
        super().__init__(
            urwid.Frame(
                scrollable(rows),
                header=urwid.Text(("title", "Actual responses and failures")),
                footer=footer,
            )
        )

    def _summary_rows(self):
        result = self.result_set
        summary = result.get("summary") or {}
        return [
            section(
                "Result %s · %s" % (result["id"], result["status"]),
                pretty(summary.get("metrics", {})),
            ),
            section("Weakest cells", pretty(summary.get("worst_cells", []))),
            section(
                "Failure distribution", pretty(summary.get("failure_distribution", []))
            ),
        ]

    def _filtered_executions(self):
        if not self.result_set:
            return []
        executions = self.result_set["executions"]
        if self.target_id:
            executions = [
                item for item in executions if item["target_id"] == self.target_id
            ]
        if self.test_case_id:
            executions = [
                item for item in executions if item["test_case_id"] == self.test_case_id
            ]
        if self.filter_kind == "failures":
            executions = [
                item
                for item in executions
                if item["response"]["status"] != "ok"
                or item["evaluation"].get("failure_tags")
            ]
        elif self.filter_kind == "contract":
            executions = [
                item
                for item in executions
                if item["evaluation"]["contract"]["status"] == "fail"
            ]
        elif self.filter_kind == "task":
            executions = [
                item
                for item in executions
                if item["evaluation"]["task"]["status"] == "fail"
            ]
        elif self.filter_kind == "transport":
            executions = [
                item for item in executions if item["response"]["status"] != "ok"
            ]
        elif self.filter_kind.startswith("requirement:"):
            identifier = self.filter_kind.split(":", 1)[1]
            executions = [
                item
                for item in executions
                if any(
                    result["id"] == identifier and result["status"] == "fail"
                    for result in item["evaluation"]["requirements"]
                )
            ]
        return executions

    def _matrix_rows(self):
        rows = []
        executions = self.result_set["executions"]
        for target in self.result_set["targets"]:
            for test_case in self.result_set["operation_snapshot"]["test_cases"]:
                selected = [
                    item
                    for item in executions
                    if item["target_id"] == target["id"]
                    and item["test_case_id"] == test_case["id"]
                ]
                metrics = metric_set(selected)
                failures = sum(
                    len(item["evaluation"].get("failure_tags", []))
                    + (1 if item["response"]["status"] != "ok" else 0)
                    for item in selected
                )
                rows.append(
                    "%s / %s · runs %d · task %s · contract %s · repeatability %s · failures %d"
                    % (
                        target["id"],
                        test_case["id"],
                        len(selected),
                        metrics["task_success_rate"],
                        metrics["contract_compliance_rate"],
                        metrics["within_model_repeatability"],
                        failures,
                    )
                )
        return [section("Model × case matrix", "\n".join(rows))]

    def _cluster_rows(self):
        clusters = response_clusters(self._filtered_executions())
        rows = []
        for index, cluster in enumerate(clusters, 1):
            rows.append(
                section(
                    "Response cluster %d · %d run(s)" % (index, cluster["count"]),
                    urwid.Pile(
                        [
                            urwid.Text(pretty(cluster)),
                            action(
                                "Human label: Pass",
                                self._label,
                                (cluster["execution_ids"], "pass"),
                            ),
                            action(
                                "Human label: Fail",
                                self._label,
                                (cluster["execution_ids"], "fail"),
                            ),
                            action(
                                "Human label: Unknown",
                                self._label,
                                (cluster["execution_ids"], "unknown"),
                            ),
                        ]
                    ),
                )
            )
        return rows or [section("Response clusters", "No comparable response clusters")]

    def _label(self, _, selection):
        execution_ids, status = selection
        self.result_set = self.app.controller.review_cluster(
            self.result_set["id"],
            execution_ids,
            status,
            "Applied to normalized response cluster in the TUI",
        )
        self.app.set_status(
            "Human label %s applied to %d run(s)" % (status, len(execution_ids))
        )
        self.app.show_responses(
            self.result_set, self.filter_kind, self.target_id, self.test_case_id
        )

    def _diff_rows(self):
        outputs = [
            item
            for item in self._filtered_executions()
            if item["response"].get("raw_output") is not None
        ]
        if len(outputs) < 2:
            return []
        left, right = outputs[:2]
        diff = "".join(
            difflib.unified_diff(
                left["response"]["raw_output"].splitlines(True),
                right["response"]["raw_output"].splitlines(True),
                fromfile=left["id"],
                tofile=right["id"],
            )
        )
        return [
            section(
                "First two selected raw responses · diff", diff or "No text difference"
            )
        ]

    def _execution_rows(self):
        rows = []
        for execution in self._filtered_executions():
            response = execution["response"]
            evaluation = execution["evaluation"]
            title = "%s / %s / trial %d · %s" % (
                execution["target_id"],
                execution["test_case_id"],
                execution["trial"],
                response["status"],
            )
            body = (
                "Expanded prompt:\n%s\n\nRaw output:\n%s\n\nEvaluation:\n%s\n\n"
                "Returned model/provider: %s / %s\nUsage: %s\nAttempts: %s"
                % (
                    execution["request"]["expanded_prompt"],
                    response.get("raw_output"),
                    pretty(evaluation),
                    response.get("returned_model"),
                    response.get("provider"),
                    pretty(response.get("usage")),
                    pretty(response.get("transport_attempts", [])),
                )
            )
            rows.append(section(title, body))
        return rows

    def _replace(
        self, filter_kind=None, target_id="unchanged", test_case_id="unchanged"
    ):
        self.app.show_responses(
            self.result_set,
            self.filter_kind if filter_kind is None else filter_kind,
            self.target_id if target_id == "unchanged" else target_id,
            self.test_case_id if test_case_id == "unchanged" else test_case_id,
        )

    def _cycle_filter(self, _):
        requirements = [
            "requirement:%s" % item["id"]
            for item in self.result_set["operation_snapshot"].get(
                "behavioral_requirements", []
            )
        ]
        choices = ["all", "failures", "contract", "task", "transport"] + requirements
        self._replace(
            filter_kind=choices[(choices.index(self.filter_kind) + 1) % len(choices)]
        )

    def _cycle_target(self, _):
        choices = [None] + [item["id"] for item in self.result_set["targets"]]
        self._replace(
            target_id=choices[(choices.index(self.target_id) + 1) % len(choices)]
        )

    def _cycle_case(self, _):
        choices = [None] + [
            item["id"] for item in self.result_set["operation_snapshot"]["test_cases"]
        ]
        self._replace(
            test_case_id=choices[(choices.index(self.test_case_id) + 1) % len(choices)]
        )
