from __future__ import annotations

import urwid

from promptimal.tui.widgets import action, action_bar, scrollable, section


class EvolutionScreen(urwid.WidgetWrap):
    def __init__(self, app, starting_candidate_id=None) -> None:
        self.app = app
        self.starting_candidate_id = starting_candidate_id
        profile = app.controller.sheet.execution_profile(
            app.controller.execution_profile_id
        )
        self.targets = [item for item in profile["targets"] if item.get("enabled")]
        self.mutator_index = 0
        self.population = urwid.IntEdit("Population size: ", 5)
        self.generations = urwid.IntEdit("Generation limit: ", 5)
        self.elites = urwid.IntEdit("Elites retained: ", 1)
        self.runs = urwid.IntEdit("Runs per model/case: ", profile["runs_per_case"])
        self.mutator = urwid.Text("")
        self.case_checks = [
            (case["id"], urwid.CheckBox(case["label"], True))
            for case in app.controller.prompt["test_cases"]
        ]
        self.target_checks = [
            (target["id"], urwid.CheckBox(target["label"], True))
            for target in self.targets
        ]
        self.progress = urwid.Text("Evolution has not started.")
        self._refresh_mutator()
        rows = [
            self.population,
            self.generations,
            self.elites,
            self.runs,
            section("Mutator target", self.mutator),
            action("Next Mutator Target", self._next_mutator),
            section("Test cases", urwid.Pile([item[1] for item in self.case_checks])),
            section(
                "Execution targets",
                urwid.Pile(
                    [item[1] for item in self.target_checks]
                    or [urwid.Text("No enabled targets")]
                ),
            ),
            section("Live progress", self.progress),
        ]
        if starting_candidate_id:
            rows.insert(
                0, urwid.Text("Continue from candidate %s" % starting_candidate_id)
            )
        footer = action_bar(
            [
                action("Start Evolution", self._start),
                action("Cancel", self._cancel),
                action("Back", lambda _: app.show_workbench()),
            ]
        )
        super().__init__(
            urwid.Frame(
                scrollable(rows),
                header=urwid.Text(("title", "Behavioral evolution (optional)")),
                footer=footer,
            )
        )

    def _refresh_mutator(self):
        if self.targets:
            target = self.targets[self.mutator_index]
            self.mutator.set_text("%s · %s" % (target["id"], target["model"]))
        else:
            self.mutator.set_text(("error", "No enabled target is available"))

    def _next_mutator(self, _):
        if self.targets:
            self.mutator_index = (self.mutator_index + 1) % len(self.targets)
            self._refresh_mutator()

    def _start(self, _):
        if not self.targets:
            self.app.set_status("Enable a model target before evolution", error=True)
            return
        population = self.population.value()
        generations = self.generations.value()
        elites = self.elites.value()
        runs = self.runs.value()
        if (
            population < 1
            or generations < 1
            or runs < 1
            or not 0 <= elites <= population
        ):
            self.app.set_status(
                "Evolution counts are outside their valid ranges", error=True
            )
            return
        case_ids = [identifier for identifier, box in self.case_checks if box.state]
        target_ids = [identifier for identifier, box in self.target_checks if box.state]
        if not case_ids or not target_ids:
            self.app.set_status(
                "Select at least one case and execution target", error=True
            )
            return

        async def progress(result_set, execution):
            self.progress.set_text(
                "%s · %s / %s / %d · %s"
                % (
                    result_set["id"],
                    execution["target_id"],
                    execution["test_case_id"],
                    execution["trial"],
                    execution["response"]["status"],
                )
            )
            self.app.redraw()

        coroutine = self.app.controller.start_evolution(
            self.targets[self.mutator_index],
            population,
            generations,
            progress_callback=progress,
            test_case_ids=case_ids,
            target_ids=target_ids,
            runs_per_case=runs,
            elite_count=elites,
            starting_candidate_id=self.starting_candidate_id,
        )

        def finished(run):
            if run["status"] == "running":
                self.app.set_status(
                    "Evolution paused: task evaluation coverage requires review or a manual parent"
                )
            else:
                self.app.set_status("Evolution %s" % run["status"])
            self.app.show_candidates(run)

        self.app.run_coroutine(coroutine, finished)

    def _cancel(self, _):
        self.app.cancel_active_task()
        self.app.set_status("Evolution cancellation requested")
