from __future__ import annotations

import json
from typing import Any, Iterable

import urwid


def pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def action(label, callback, user_data=None):
    button = urwid.Button(label, on_press=callback, user_data=user_data)
    return urwid.AttrMap(button, None, focus_map="focus")


def action_bar(items: Iterable[Any]):
    return urwid.GridFlow(list(items), 22, 2, 1, "left")


def section(title: str, body: Any):
    widget = body if isinstance(body, urwid.Widget) else urwid.Text(str(body))
    return urwid.LineBox(urwid.Padding(widget, left=1, right=1), title=title)


def scrollable(widgets):
    return urwid.ListBox(urwid.SimpleFocusListWalker(widgets))
