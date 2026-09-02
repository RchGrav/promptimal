from __future__ import annotations

import urwid

from promptimal.tui.widgets import action, action_bar, scrollable


class PromptListScreen(urwid.WidgetWrap):
    def __init__(self, app) -> None:
        self.app = app
        rows = [
            urwid.Text(
                (
                    "heading",
                    "Prompt ID                     State          Revision            Portable pass / weakest cell",
                )
            ),
            urwid.Divider("─"),
        ]
        if app.controller.sheet.diagnostics:
            rows.append(
                urwid.Text(
                    (
                        "error",
                        "%d validation diagnostic(s); affected records remain visible below."
                        % len(app.controller.sheet.diagnostics),
                    )
                )
            )
            rows.extend(
                urwid.Text(("error", str(item)))
                for item in app.controller.sheet.diagnostics
            )
        prompts = app.controller.visible_prompts
        if not prompts:
            rows.append(urwid.Text("No prompts match this filter."))
        for prompt in prompts:
            result = app.controller.latest_result(prompt)
            worst = ((result or {}).get("summary", {}).get("worst_cells") or [None])[0]
            portable = worst.get("metrics", {}).get("full_pass_rate") if worst else None
            score = "—" if portable is None else "%5.1f%%" % (portable * 100)
            weakest = "—"
            if worst:
                weakest = "%s / %s" % (worst["target_id"], worst["test_case_id"])
            label = "%-29s %-14s %-19s %s  %s" % (
                prompt.get("id", ""),
                prompt.get("state", ""),
                prompt.get("current_revision_id", ""),
                score,
                weakest,
            )
            rows.append(action(label, self._open, prompt["id"]))
            rows.append(
                urwid.Text(("muted", "  " + prompt.get("intent", "").split("\n", 1)[0]))
            )
            rows.append(
                urwid.Text(
                    (
                        "muted",
                        "  Last test: %s · profile %s"
                        % (
                            (result or {}).get("completed_at") or "—",
                            (result or {}).get("execution_profile_id") or "—",
                        ),
                    )
                )
            )

        filter_label = self.app.controller.state_filter or "all"
        footer = action_bar(
            [
                action("Open Prompt", self._open_current),
                action("Test Selected", self._test_current),
                action("Filter: %s" % filter_label, self._cycle_filter),
                action("Configure Models", lambda _: app.show_model_config()),
                action("Save", self._save),
                action("Exit", lambda _: app.exit()),
            ]
        )
        frame = urwid.Frame(
            scrollable(rows),
            header=urwid.Text(("title", "Promptimal · Prompt Refinement Workbench")),
            footer=footer,
        )
        super().__init__(frame)

    def _open(self, _, prompt_id):
        self.app.controller.set_prompt(prompt_id)
        self.app.show_workbench()

    def _open_current(self, _):
        if self.app.controller.visible_prompts:
            self.app.show_workbench()

    def _test_current(self, _):
        if self.app.controller.visible_prompts:
            self.app.show_test_run()

    def _cycle_filter(self, _):
        choices = [None, "unreviewed", "in_refinement", "tested", "finalized"]
        current = self.app.controller.state_filter
        self.app.controller.set_filter(
            choices[(choices.index(current) + 1) % len(choices)]
        )
        self.app.show_prompt_list()

    def _save(self, _):
        self.app.controller.sheet.save()
        self.app.set_status("Prompt sheet saved atomically")
