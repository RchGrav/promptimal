from __future__ import annotations

import urwid

from promptimal.tui.widgets import action, action_bar


class TestRunScreen(urwid.WidgetWrap):
    __test__ = False

    def __init__(self, app, template=None, source_candidate_id=None) -> None:
        self.app = app
        self.template = template
        self.source_candidate_id = source_candidate_id
        self.profile = app.controller.sheet.execution_profile(
            app.controller.execution_profile_id
        )
        self.enabled_targets = [
            target for target in self.profile["targets"] if target.get("enabled")
        ]
        self.target_checks = [
            (target["id"], urwid.CheckBox(target["label"], True))
            for target in self.enabled_targets
        ]
        self.case_checks = [
            (test_case["id"], urwid.CheckBox(test_case["label"], True))
            for test_case in app.controller.prompt["test_cases"]
        ]
        self.runs = urwid.IntEdit(
            "Runs per model/case: ", self.profile["runs_per_case"]
        )
        self.planned = 0
        self.completed = 0
        self.status = urwid.Text("Profile: %s" % self.profile["label"])
        for _, box in self.target_checks + self.case_checks:
            urwid.connect_signal(box, "change", self._selection_changed)
        urwid.connect_signal(self.runs, "change", self._runs_changed)
        self._update_plan()
        self.log = urwid.SimpleFocusListWalker([])
        self.start_button = action("Start Test", self._start)
        footer = action_bar(
            [
                self.start_button,
                action("Cancel", self._cancel),
                action("Back", lambda _: app.show_workbench()),
            ]
        )
        super().__init__(
            urwid.Frame(
                urwid.Pile(
                    [
                        ("pack", self.status),
                        ("pack", self.runs),
                        (
                            "pack",
                            urwid.Columns(
                                [
                                    urwid.LineBox(
                                        urwid.Pile(
                                            [item[1] for item in self.target_checks]
                                            or [urwid.Text("No enabled targets")]
                                        ),
                                        title="Targets",
                                    ),
                                    urwid.LineBox(
                                        urwid.Pile(
                                            [item[1] for item in self.case_checks]
                                        ),
                                        title="Cases",
                                    ),
                                ],
                                dividechars=1,
                            ),
                        ),
                        ("pack", urwid.Divider("─")),
                        ("weight", 1, urwid.ListBox(self.log)),
                    ]
                ),
                header=urwid.Text(("title", "Run repeated OpenRouter test matrix")),
                footer=footer,
            )
        )

    def _selection_changed(self, *_):
        self._update_plan()

    def _runs_changed(self, *_):
        self._update_plan()

    def _update_plan(self):
        targets = len([box for _, box in self.target_checks if box.state])
        cases = len([box for _, box in self.case_checks if box.state])
        runs = self.runs.value()
        self.planned = targets * cases * runs
        self.status.set_text(
            "Profile: %s · targets %d · cases %d · runs/cell %d · planned requests %d"
            % (self.profile["label"], targets, cases, runs, self.planned)
        )
        self.app.redraw()

    def _start(self, _):
        if self.app.active_task and not self.app.active_task.done():
            return
        target_ids = [identifier for identifier, box in self.target_checks if box.state]
        case_ids = [identifier for identifier, box in self.case_checks if box.state]
        runs = self.runs.value()
        if not target_ids or not case_ids or runs < 1:
            self.app.set_status(
                "Select at least one target and case, with one or more runs",
                error=True,
            )
            return
        self.planned = len(target_ids) * len(case_ids) * runs
        self.completed = 0
        self.log.append(urwid.Text("Starting %d planned executions…" % self.planned))

        async def progress(result_set, execution):
            self.completed += 1
            status = execution["response"]["status"]
            self.status.set_text(
                "%d/%d observed · result %s · status %s"
                % (self.completed, self.planned, result_set["id"], result_set["status"])
            )
            self.log.append(
                urwid.Text(
                    "%s / %s / trial %d: %s"
                    % (
                        execution["target_id"],
                        execution["test_case_id"],
                        execution["trial"],
                        status,
                    )
                )
            )
            self.app.redraw()

        coroutine = self.app.controller.test_current(
            template=self.template,
            progress_callback=progress,
            target_ids=target_ids,
            test_case_ids=case_ids,
            runs_per_case=runs,
            source_candidate_id=self.source_candidate_id,
        )

        def finished(result):
            self.app.set_status("Test run %s" % result["status"])
            self.app.show_responses(result)

        self.app.run_coroutine(coroutine, finished)

    def _cancel(self, _):
        self.app.cancel_active_task()
        self.app.set_status(
            "Cancellation requested; completed observations are retained"
        )
