import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from promptimal.sheet.models import PromptSheet


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sheet_data():
    return json.loads(
        (ROOT / "examples" / "prompt-sheet.example.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def memory_sheet(sheet_data):
    return PromptSheet(copy.deepcopy(sheet_data))


def response(
    content='["c++", "cpp"]',
    model="returned/model",
    provider="provider-a",
    cost=0.001,
):
    message = SimpleNamespace(content=content, model_extra={})
    choice = SimpleNamespace(
        message=message,
        finish_reason="stop",
        native_finish_reason="stop",
        model_extra={},
    )
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=4,
        total_tokens=14,
        cost=cost,
        model_extra={},
    )
    return SimpleNamespace(
        id="response-id",
        model=model,
        provider=provider,
        choices=[choice],
        usage=usage,
        model_extra={},
    )


class FakeCompletions:
    def __init__(self, outcomes=None, delay=0):
        self.outcomes = list(outcomes or [])
        self.delay = delay
        self.calls = []
        self.active = 0
        self.maximum_active = 0

    async def create(self, **kwargs):
        import asyncio

        self.calls.append(copy.deepcopy(kwargs))
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            outcome = self.outcomes.pop(0) if self.outcomes else response()
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        finally:
            self.active -= 1


class FakeClient:
    def __init__(self, outcomes=None, delay=0):
        self.completions = FakeCompletions(outcomes, delay)
        self.chat = SimpleNamespace(completions=self.completions)
