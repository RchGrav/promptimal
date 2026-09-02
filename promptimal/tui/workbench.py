from __future__ import annotations

import asyncio
from typing import Optional

import urwid

from promptimal.tui.candidates import CandidatesScreen
from promptimal.tui.controller import WorkbenchController
from promptimal.tui.editor import EditorScreen
from promptimal.tui.evolution import EvolutionScreen
from promptimal.tui.history import HistoryScreen
from promptimal.tui.model_config import ModelConfigScreen
from promptimal.tui.prompt_list import PromptListScreen
from promptimal.tui.responses import ResponsesScreen
from promptimal.tui.test_run import TestRunScreen
from promptimal.tui.widgets import action, action_bar, pretty, scrollable, section


class PromptWorkbenchScreen(urwid.WidgetWrap):
    def __init__(self, app) -> None:
        self.app = app
        controller = app.controller
        prompt = controller.prompt
        revision = controller.revision
        test_case = controller.selected_case
        expansion = controller.expanded()
        result_set = controller.latest_result()
        summary = (result_set or {}).get("summary") or {}
        expanded_text = expansion.text
        if expansion.diagnostics:
            expanded_text = "\n".join(
                "%s: %s" % (item.code, item.message) for item in expansion.diagnostics
            )
        template_pair = urwid.Columns(
            [
                section("Template", revision["prompt_template"]),
                section("Expanded · %s" % test_case["label"], expanded_text),
            ],
            dividechars=1,
        )
        rows = [
            urwid.Text(
                (
                    "title",
                    "Prompt: %s   State: %s   Revision: %s"
                    % (prompt["id"], prompt["state"], revision["id"]),
                )
            ),
            section("Intent", prompt["intent"]),
            template_pair,
            section(
                "Case and intended response",
                "%s\nValues: %s\nIntended: %s"
                % (
                    test_case["label"],
                    pretty(test_case["values"]),
                    pretty(test_case["intended_response"]),
                ),
            ),
            section("Variables", pretty(prompt["variables"])),
            section("Output contract", pretty(prompt["output_contract"])),
            section(
                "Behavioral requirements", pretty(prompt["behavioral_requirements"])
            ),
            section(
                "Revision",
                "Current: %s\nParent: %s\nOrigin: %s"
                % (
                    revision["id"],
                    revision.get("parent_revision_id"),
                    pretty(revision["origin"]),
                ),
            ),
            section(
                "Latest current-revision metrics", pretty(summary.get("metrics", {}))
            ),
            section("Model results", pretty(summary.get("per_target", []))),
            section("Case results", pretty(summary.get("per_case", []))),
            section("Weakest cells", pretty(summary.get("worst_cells", []))),
            section(
                "Failure distribution", pretty(summary.get("failure_distribution", []))
            ),
            section(
                "History",
                "%d revisions · %d finalizations · %d evolution runs"
                % (
                    len(prompt.get("revisions", [])),
                    len(prompt.get("finalization_history", [])),
                    len(
                        [
                            run
                            for run in controller.sheet.evolution_runs
                            if run.get("prompt_id") == prompt["id"]
                        ]
                    ),
                ),
            ),
        ]
        footer = action_bar(
            [
                action("Edit Prompt", lambda _: app.show_editor()),
                action("Test Current Prompt", lambda _: app.show_test_run()),
                action("Inspect Responses", lambda _: app.show_responses()),
                action("Try Evolution", lambda _: app.show_evolution()),
                action("Compare Candidates", self._candidates),
                action("Finalize", self._finalize),
                action("Revision History", lambda _: app.show_history()),
                action("Select Next Case", self._next_case),
                action("Previous Prompt", self._previous),
                action("Next Prompt", self._next),
                action("Prompt List", lambda _: app.show_prompt_list()),
            ]
        )
        super().__init__(urwid.Frame(scrollable(rows), footer=footer))

    def _finalize(self, _):
        event = self.app.controller.finalize()
        self.app.set_status("Finalized revision %s" % event["revision_id"])
        self.app.show_workbench()

    def _next_case(self, _):
        self.app.controller.next_case()
        self.app.show_workbench()

    def _next(self, _):
        self.app.controller.next_prompt()
        self.app.show_workbench()

    def _previous(self, _):
        self.app.controller.previous_prompt()
        self.app.show_workbench()

    def _candidates(self, _):
        runs = [
            run
            for run in self.app.controller.sheet.evolution_runs
            if run.get("prompt_id") == self.app.controller.prompt["id"]
        ]
        if not runs:
            self.app.set_status("No evolution run exists for this prompt")
            return
        self.app.show_candidates(runs[-1])


class WorkbenchApp:
    palette = [
        ("title", "light magenta,bold", "default"),
        ("heading", "white,bold", "default"),
        ("muted", "dark gray", "default"),
        ("success", "light green", "default"),
        ("error", "light red", "default"),
        ("field", "light cyan,bold", "default"),
        ("focus", "black", "light magenta"),
    ]

    def __init__(self, sheet, api_key: Optional[str] = None) -> None:
        self.controller = WorkbenchController(sheet, api_key=api_key)
        self.status = urwid.Text("")
        self.main_loop = None
        self.asyncio_loop = None
        self.active_task = None
        self._screen = PromptListScreen(self)

    def _root(self, screen):
        return urwid.Frame(screen, footer=urwid.AttrMap(self.status, "muted"))

    def _switch(self, screen):
        self._screen = screen
        if self.main_loop is not None:
            self.main_loop.widget = self._root(screen)
            self.redraw()

    def show_prompt_list(self):
        self._switch(PromptListScreen(self))

    def show_workbench(self):
        try:
            screen = PromptWorkbenchScreen(self)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            self.set_status("Cannot open invalid prompt record: %s" % exc, error=True)
            return
        self._switch(screen)

    def show_editor(self, template=None, source_candidate_id=None):
        self._switch(EditorScreen(self, template, source_candidate_id))

    def show_test_run(self, template=None, source_candidate_id=None):
        self._switch(TestRunScreen(self, template, source_candidate_id))

    def show_responses(
        self,
        result_set=None,
        filter_kind="all",
        target_id=None,
        test_case_id=None,
    ):
        self._switch(
            ResponsesScreen(self, result_set, filter_kind, target_id, test_case_id)
        )

    def show_history(self):
        self._switch(HistoryScreen(self))

    def show_model_config(self):
        self._switch(ModelConfigScreen(self))

    def show_evolution(self, starting_candidate_id=None):
        self._switch(EvolutionScreen(self, starting_candidate_id))

    def show_candidates(self, run):
        self._switch(CandidatesScreen(self, run))

    def set_status(self, message: str, error: bool = False):
        self.status.set_text((("error" if error else "success"), " " + message))
        self.redraw()

    def redraw(self):
        if self.main_loop is not None:
            try:
                self.main_loop.draw_screen()
            except (AssertionError, RuntimeError):
                pass

    def run_coroutine(self, coroutine, on_success):
        if self.active_task and not self.active_task.done():
            self.set_status("Another operation is already running", error=True)
            return self.active_task
        self.active_task = self.asyncio_loop.create_task(coroutine)

        def done(task):
            try:
                result = task.result()
            except asyncio.CancelledError:
                self.set_status("Operation cancelled")
            except Exception as exc:
                self.set_status("Operation failed: %s" % exc, error=True)
            else:
                on_success(result)

        self.active_task.add_done_callback(done)
        return self.active_task

    def cancel_active_task(self):
        if self.active_task and not self.active_task.done():
            self.active_task.cancel()

    def _unhandled(self, key):
        if key == "esc":
            self.show_prompt_list()
        elif key in ("ctrl q",):
            self.exit()

    def exit(self):
        if self.active_task and not self.active_task.done():
            self.active_task.cancel()
        raise urwid.ExitMainLoop()

    def start(self):
        self.asyncio_loop = asyncio.new_event_loop()
        event_loop = urwid.AsyncioEventLoop(loop=self.asyncio_loop)
        self.main_loop = urwid.MainLoop(
            self._root(self._screen),
            self.palette,
            unhandled_input=self._unhandled,
            event_loop=event_loop,
        )
        try:
            self.main_loop.run()
        finally:
            pending = asyncio.all_tasks(self.asyncio_loop)
            for task in pending:
                task.cancel()
            if pending:
                self.asyncio_loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self.asyncio_loop.close()


def run_workbench(sheet, api_key: Optional[str] = None):
    return WorkbenchApp(sheet, api_key=api_key).start()
