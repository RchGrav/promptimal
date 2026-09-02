from __future__ import annotations

import copy
import json

import urwid

from promptimal.tui.widgets import action, action_bar, scrollable, section


class ModelConfigScreen(urwid.WidgetWrap):
    def __init__(self, app) -> None:
        self.app = app
        self.profile = app.controller.sheet.execution_profile(
            app.controller.execution_profile_id
        )
        self.runs = urwid.IntEdit("Runs per case: ", self.profile["runs_per_case"])
        self.concurrency = urwid.IntEdit(
            "Maximum concurrency: ", self.profile["max_concurrency"]
        )
        self.timeout = urwid.Edit(
            "Timeout seconds: ", str(self.profile["timeout_seconds"])
        )
        self.retries = urwid.IntEdit(
            "Transport retries: ", self.profile["max_transport_retries"]
        )
        self.target_widgets = []
        rows = [
            urwid.Text("Profile %s (%s)" % (self.profile["label"], self.profile["id"])),
            self.runs,
            self.concurrency,
            self.timeout,
            self.retries,
        ]
        for target in self.profile["targets"]:
            enabled = urwid.CheckBox("Enabled", target.get("enabled", False))
            model = urwid.Edit("OpenRouter model: ", target["model"])
            parameters = urwid.Edit(
                "Parameters JSON: ",
                json.dumps(target.get("parameters", {}), ensure_ascii=False),
                multiline=True,
            )
            routing = urwid.Edit(
                "Provider routing JSON: ",
                json.dumps(target.get("provider_routing", {}), ensure_ascii=False),
                multiline=True,
            )
            self.target_widgets.append((target, enabled, model, parameters, routing))
            rows.append(
                section(
                    "%s · %s" % (target["label"], target["id"]),
                    urwid.Pile([enabled, model, parameters, routing]),
                )
            )
        footer = action_bar(
            [
                action("Save Profile", self._save),
                action("Next Profile", self._next_profile),
                action("Discard / Back", lambda _: app.show_prompt_list()),
            ]
        )
        super().__init__(
            urwid.Frame(
                scrollable(rows),
                header=urwid.Text(("title", "OpenRouter execution profiles")),
                footer=footer,
            )
        )

    def _save(self, _):
        try:
            runs = self.runs.value()
            concurrency = self.concurrency.value()
            retries = self.retries.value()
            timeout = float(self.timeout.edit_text)
            if min(runs, concurrency) < 1 or retries < 0 or timeout <= 0:
                raise ValueError("Counts and timeout are outside their valid ranges")
            updates = []
            for target, enabled, model, parameters, routing in self.target_widgets:
                updates.append(
                    (
                        target,
                        enabled.state,
                        model.edit_text,
                        json.loads(parameters.edit_text),
                        json.loads(routing.edit_text),
                    )
                )
            if not all(
                isinstance(item[3], dict) and isinstance(item[4], dict)
                for item in updates
            ):
                raise ValueError("Parameters and provider routing must be JSON objects")
        except (ValueError, json.JSONDecodeError) as exc:
            self.app.set_status("Profile not saved: %s" % exc, error=True)
            return
        self.profile.update(
            {
                "runs_per_case": runs,
                "max_concurrency": concurrency,
                "timeout_seconds": timeout,
                "max_transport_retries": retries,
            }
        )
        for target, enabled, model, parameters, routing in updates:
            target.update(
                {
                    "enabled": enabled,
                    "model": model,
                    "parameters": copy.deepcopy(parameters),
                    "provider_routing": copy.deepcopy(routing),
                }
            )
        self.app.controller.sheet.save()
        self.app.set_status("Execution profile saved")
        self.app.show_prompt_list()

    def _next_profile(self, _):
        profiles = self.app.controller.sheet.execution_profiles
        current = next(
            i for i, item in enumerate(profiles) if item["id"] == self.profile["id"]
        )
        selected = profiles[(current + 1) % len(profiles)]
        self.app.controller.execution_profile_id = selected["id"]
        self.app.show_model_config()
