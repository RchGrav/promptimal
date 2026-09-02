from __future__ import annotations

import difflib

import urwid

from promptimal.tui.widgets import action, action_bar, scrollable


class HistoryScreen(urwid.WidgetWrap):
    def __init__(self, app) -> None:
        self.app = app
        prompt = app.controller.prompt
        current = app.controller.revision
        rows = []
        for revision in reversed(prompt.get("revisions", [])):
            marker = " [current]" if revision["id"] == current["id"] else ""
            rows.append(
                action(
                    "%s%s · %s · %s"
                    % (
                        revision["id"],
                        marker,
                        revision.get("origin", {}).get("kind"),
                        revision.get("created_at"),
                    ),
                    self._select,
                    revision["id"],
                )
            )
            if revision["id"] != current["id"]:
                diff = "".join(
                    difflib.unified_diff(
                        revision["prompt_template"].splitlines(True),
                        current["prompt_template"].splitlines(True),
                        fromfile=revision["id"],
                        tofile=current["id"],
                    )
                )
                rows.append(urwid.Text(("muted", diff or "No text difference")))
        for event in reversed(prompt.get("finalization_history", [])):
            rows.append(
                urwid.Text(
                    (
                        "success",
                        "Finalized %s at %s"
                        % (event["revision_id"], event["finalized_at"]),
                    )
                )
            )
        footer = action_bar([action("Back", lambda _: app.show_workbench())])
        super().__init__(
            urwid.Frame(
                scrollable(rows),
                header=urwid.Text(("title", "Revision and finalization history")),
                footer=footer,
            )
        )

    def _select(self, _, revision_id):
        self.app.controller.select_revision(revision_id)
        self.app.set_status("Selected revision %s" % revision_id)
        self.app.show_workbench()
