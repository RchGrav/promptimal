__all__ = [
    "ExecutionRunner",
    "OpenRouterChatCompletionsAdapter",
    "run_prompt_test",
]


def __getattr__(name):
    if name == "OpenRouterChatCompletionsAdapter":
        from promptimal.execution.openrouter import OpenRouterChatCompletionsAdapter

        return OpenRouterChatCompletionsAdapter
    if name in ("ExecutionRunner", "run_prompt_test"):
        from promptimal.execution.runner import ExecutionRunner, run_prompt_test

        return {"ExecutionRunner": ExecutionRunner, "run_prompt_test": run_prompt_test}[
            name
        ]
    raise AttributeError(name)
