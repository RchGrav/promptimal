from __future__ import annotations

import asyncio
import copy
import os
import time
from typing import Any, Dict, Optional

from openai import AsyncOpenAI

from promptimal.execution.models import empty_response
from promptimal.sheet.models import utc_now


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _extra(value: Any) -> Dict[str, Any]:
    extra = getattr(value, "model_extra", None)
    return extra if isinstance(extra, dict) else {}


def _field(value: Any, name: str, default=None):
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(name, default)
    direct = getattr(value, name, None)
    if direct is not None:
        return direct
    return _extra(value).get(name, default)


def _error(exc: BaseException) -> Dict[str, Any]:
    details = {"type": type(exc).__name__, "message": str(exc)}
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        details["status_code"] = status_code
    request_id = getattr(exc, "request_id", None)
    if request_id:
        details["request_id"] = request_id
    return details


def _number(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string(value: Any) -> Optional[str]:
    if value is None or isinstance(value, str):
        return value
    return str(value)


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _usage(response: Any) -> Optional[Dict[str, Any]]:
    value = _field(response, "usage")
    if value is None:
        return None
    if isinstance(value, dict):
        result = copy.deepcopy(value)
    elif callable(getattr(value, "model_dump", None)):
        result = value.model_dump(mode="json")
    else:
        result = copy.deepcopy(_extra(value))
    result.update(
        {
            "prompt_tokens": _integer(_field(value, "prompt_tokens")),
            "completion_tokens": _integer(_field(value, "completion_tokens")),
            "total_tokens": _integer(_field(value, "total_tokens")),
            "cost": _number(_field(value, "cost")),
        }
    )
    for key, item in _extra(value).items():
        if key not in result:
            result[key] = copy.deepcopy(item)
    return result


def _retryable(exc: BaseException, status: str) -> bool:
    if status == "timeout" or isinstance(exc, ConnectionError):
        return True
    name = type(exc).__name__.casefold()
    if "connection" in name:
        return True
    status_code = getattr(exc, "status_code", None)
    return status_code in (408, 409, 429) or (
        isinstance(status_code, int) and status_code >= 500
    )


def _choice(response: Any) -> Any:
    choices = _field(response, "choices", []) or []
    return choices[0] if choices else None


class OpenRouterChatCompletionsAdapter:
    """Execute one exact, non-streaming OpenRouter chat-completion request."""

    adapter_name = "openrouter-chat-completions"

    def __init__(
        self,
        timeout_seconds: float,
        max_transport_retries: int,
        api_key: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_transport_retries = max_transport_retries
        self.client = client or AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key or os.environ.get("OPENROUTER_API_KEY"),
            # Disable SDK retries so every transport attempt remains observable below.
            max_retries=0,
        )

    @staticmethod
    def request_kwargs(target: Dict[str, Any], messages: list) -> Dict[str, Any]:
        extra_body = copy.deepcopy(target.get("parameters", {}))
        provider_routing = target.get("provider_routing", {})
        if provider_routing:
            extra_body["provider"] = copy.deepcopy(provider_routing)
        request = {
            "model": target["model"],
            "messages": copy.deepcopy(messages),
        }
        if extra_body:
            request["extra_body"] = extra_body
        return request

    async def execute(self, target: Dict[str, Any], messages: list) -> Dict[str, Any]:
        attempts = []
        total_started = time.monotonic()
        last_status = "api_error"
        last_error = None

        for attempt_number in range(1, self.max_transport_retries + 2):
            started_at = utc_now()
            should_retry = False
            try:
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        **self.request_kwargs(target, messages)
                    ),
                    timeout=self.timeout_seconds,
                )
                completed_at = utc_now()
                attempts.append(
                    {
                        "attempt": attempt_number,
                        "started_at": started_at,
                        "completed_at": completed_at,
                        "status": "ok",
                        "error": None,
                    }
                )
                choice = _choice(response)
                message = _field(choice, "message")
                raw_output = _field(message, "content")
                if raw_output is not None and not isinstance(raw_output, str):
                    raw_output = str(raw_output)
                provider = _string(_field(response, "provider"))
                finish_reason = _string(_field(choice, "finish_reason"))
                native_finish_reason = _string(_field(choice, "native_finish_reason"))
                if native_finish_reason is None:
                    native_finish_reason = _string(
                        _field(response, "native_finish_reason")
                    )
                return {
                    "status": "ok",
                    "raw_output": raw_output,
                    "parsed_output": None,
                    "response_id": _string(_field(response, "id")),
                    "returned_model": _string(_field(response, "model")),
                    "provider": provider,
                    "finish_reason": finish_reason,
                    "native_finish_reason": native_finish_reason,
                    "usage": _usage(response),
                    "latency_ms": (time.monotonic() - total_started) * 1000.0,
                    "error": None,
                    "transport_attempts": attempts,
                }
            except asyncio.CancelledError:
                raise
            except (asyncio.TimeoutError, TimeoutError) as exc:
                last_status = "timeout"
                last_error = _error(exc)
                should_retry = _retryable(exc, last_status)
            except Exception as exc:  # The SDK exposes multiple transport subclasses.
                last_status = (
                    "timeout"
                    if "timeout" in type(exc).__name__.casefold()
                    else "api_error"
                )
                last_error = _error(exc)
                should_retry = _retryable(exc, last_status)

            attempts.append(
                {
                    "attempt": attempt_number,
                    "started_at": started_at,
                    "completed_at": utc_now(),
                    "status": last_status,
                    "error": copy.deepcopy(last_error),
                }
            )
            if not should_retry:
                break

        result = empty_response(last_status, last_error, attempts)
        result["latency_ms"] = (time.monotonic() - total_started) * 1000.0
        return result
