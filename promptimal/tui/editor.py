from __future__ import annotations

import re

import urwid

from promptimal.tui.widgets import action, action_bar, pretty, scrollable, section


class EditorScreen(urwid.WidgetWrap):
    def __init__(self, app, template=None, source_candidate_id=None) -> None:
        self.app = app
        self.source_candidate_id = source_candidate_id
        self.editor = urwid.Edit(
            edit_text=(
                template
                if template is not None
                else app.controller.revision["prompt_template"]
            ),
            multiline=True,
        )
        self.preview = urwid.Text("")
        self.highlighted = urwid.Text("")
        self.case_label = urwid.Text("")
        self.variables = urwid.Text("")
        urwid.connect_signal(self.editor, "change", self._changed)
        self._refresh_preview(self.editor.edit_text)
        body = scrollable(
            [
                section("Template", self.editor),
                section("Named fields", self.highlighted),
                section("Expanded prompt", self.preview),
                section("Selected case", self.case_label),
                section("Variable declarations and values", self.variables),
            ]
        )
        footer = action_bar(
            [
                action("Save Revision", self._save),
                action("Test Buffer", self._test),
                action("Next Case", self._next_case),
                action("Discard / Back", lambda _: app.show_workbench()),
            ]
        )
        super().__init__(
            urwid.Frame(
                body,
                header=urwid.Text(("title", "Manual template editor")),
                footer=footer,
            )
        )

    def _changed(self, _, text):
        self._refresh_preview(text)

    def _refresh_preview(self, text):
        case = self.app.controller.selected_case
        result = self.app.controller.expanded(text)
        markup = []
        position = 0
        for match in re.finditer(r"(?<!\{)\{[A-Za-z_][A-Za-z0-9_]*\}(?!\})", text):
            markup.append(text[position : match.start()])
            markup.append(("field", match.group(0)))
            position = match.end()
        markup.append(text[position:])
        self.highlighted.set_text(markup)
        self.case_label.set_text("%s · values %r" % (case["label"], case["values"]))
        self.variables.set_text(
            pretty(
                [
                    {
                        **variable,
                        "selected_value": case["values"].get(variable["name"]),
                    }
                    for variable in self.app.controller.prompt["variables"]
                ]
            )
        )
        if result.diagnostics:
            self.preview.set_text(
                [
                    ("error", "%s: %s\n" % (item.code, item.message))
                    for item in result.diagnostics
                ]
            )
        else:
            self.preview.set_text(result.text)
        self.app.redraw()

    def _save(self, _):
        revision = self.app.controller.save_edit(
            self.editor.edit_text,
            note=(
                "Manually edited from candidate %s" % self.source_candidate_id
                if self.source_candidate_id
                else None
            ),
            source_candidate_id=self.source_candidate_id,
        )
        self.app.set_status("Saved revision %s" % revision["id"])
        self.app.show_workbench()

    def _test(self, _):
        self.app.show_test_run(self.editor.edit_text, self.source_candidate_id)

    def _next_case(self, _):
        self.app.controller.next_case()
        self._refresh_preview(self.editor.edit_text)
