from __future__ import annotations

import difflib

import urwid

from promptimal.optimizer.candidates import candidate_summary, candidate_vector
from promptimal.tui.widgets import action, action_bar, pretty, scrollable, section


class CandidatesScreen(urwid.WidgetWrap):
    def __init__(self, app, run) -> None:
        self.app = app
        self.run = run
        current = app.controller.revision["prompt_template"]
        rows = [
            urwid.Text(
                "Run %s · %s · parent revision %s"
                % (run["id"], run["status"], run["parent_revision_id"])
            )
        ]
        for generation in reversed(run["generations"]):
            rows.append(urwid.Text(("heading", "Generation %d" % generation["index"])))
            for candidate in generation["candidates"]:
                summary = candidate_summary(candidate, app.controller.sheet.result_sets)
                result_set = next(
                    (
                        item
                        for item in app.controller.sheet.result_sets
                        if item.get("id") == candidate.get("result_set_id")
                    ),
                    None,
                )
                cost_values = [
                    (item.get("response", {}).get("usage") or {}).get("cost")
                    for item in (result_set or {}).get("executions", [])
                ]
                observed_cost = (
                    sum(float(value) for value in cost_values if value is not None)
                    if any(value is not None for value in cost_values)
                    else None
                )
                diff = ""
                if candidate.get("prompt_template") is not None:
                    diff = "".join(
                        difflib.unified_diff(
                            current.splitlines(True),
                            candidate["prompt_template"].splitlines(True),
                            fromfile="current revision",
                            tofile=candidate["id"],
                        )
                    )
                body = [
                    urwid.Text("Status: %s" % candidate["status"]),
                    urwid.Text(
                        "Lineage: %s"
                        % (candidate["parent_candidate_ids"] or "baseline")
                    ),
                    urwid.Text(
                        "Vector: %s"
                        % (
                            candidate_vector(
                                candidate, app.controller.sheet.result_sets
                            ),
                        )
                    ),
                    urwid.Text(("muted", diff or "No template difference")),
                    urwid.Text(
                        "Metrics / weakest cells / failures:\n%s"
                        % pretty(summary or {})
                    ),
                    urwid.Text(
                        "Requests: %d · observed cost: %s"
                        % (
                            len((result_set or {}).get("executions", [])),
                            "unavailable"
                            if observed_cost is None
                            else "%.8f" % observed_cost,
                        )
                    ),
                ]
                if candidate.get("prompt_template") is not None:
                    body.extend(
                        [
                            action("Adopt Candidate", self._adopt, candidate["id"]),
                            action(
                                "Continue Breeding", self._continue, candidate["id"]
                            ),
                            action("Edit as Revision", self._edit, candidate["id"]),
                        ]
                    )
                    if result_set is not None:
                        body.append(
                            action(
                                "Inspect Actual Responses",
                                self._responses,
                                result_set["id"],
                            )
                        )
                rows.append(section(candidate["id"], urwid.Pile(body)))
        footer = action_bar(
            [
                action("Reject Run", self._reject),
                action("Manual Editing", lambda _: app.show_editor()),
                action("Back", lambda _: app.show_workbench()),
            ]
        )
        super().__init__(
            urwid.Frame(
                scrollable(rows),
                header=urwid.Text(("title", "Candidate comparison")),
                footer=footer,
            )
        )

    def _adopt(self, _, candidate_id):
        revision = self.app.controller.adopt_candidate(self.run["id"], candidate_id)
        self.app.set_status("Adopted %s as %s" % (candidate_id, revision["id"]))
        self.app.show_workbench()

    def _continue(self, _, candidate_id):
        self.app.show_evolution(candidate_id)

    def _edit(self, _, candidate_id):
        candidate = self.app.controller.sheet.candidate(candidate_id)
        self.app.show_editor(candidate["prompt_template"], candidate_id)

    def _responses(self, _, result_set_id):
        result_set = next(
            item
            for item in self.app.controller.sheet.result_sets
            if item.get("id") == result_set_id
        )
        self.app.show_responses(result_set)

    def _reject(self, _):
        self.app.controller.reject_evolution(self.run["id"])
        self.app.set_status("Evolution run rejected; current revision was unchanged")
        self.app.show_workbench()
