from __future__ import annotations

import copy
import uuid
from typing import Any, Dict, Optional

from promptimal.evaluation.engine import empty_evaluation


def new_id(prefix: str) -> str:
    return "%s.%s" % (prefix, uuid.uuid4().hex)


def request_snapshot(
    target: Dict[str, Any], expanded_prompt: Optional[str]
) -> Dict[str, Any]:
    messages = (
        [{"role": "user", "content": expanded_prompt}]
        if expanded_prompt is not None
        else []
    )
    return {
        "model": target["model"],
        "expanded_prompt": expanded_prompt,
        "messages": messages,
        "parameters": copy.deepcopy(target.get("parameters", {})),
        "provider_routing": copy.deepcopy(target.get("provider_routing", {})),
    }


def empty_response(
    status: str,
    error: Optional[Dict[str, Any]] = None,
    transport_attempts=None,
) -> Dict[str, Any]:
    return {
        "status": status,
        "raw_output": None,
        "parsed_output": None,
        "response_id": None,
        "returned_model": None,
        "provider": None,
        "finish_reason": None,
        "native_finish_reason": None,
        "usage": None,
        "latency_ms": None,
        "error": copy.deepcopy(error),
        "transport_attempts": copy.deepcopy(transport_attempts or []),
    }


def planned_execution(
    execution_id: str,
    test_case_id: str,
    target: Dict[str, Any],
    trial: int,
    expanded_prompt: Optional[str],
    expansion_error: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    status = "expansion_error" if expansion_error else "cancelled"
    failure_tag = "expansion_error" if expansion_error else "cancelled"
    return {
        "id": execution_id,
        "test_case_id": test_case_id,
        "target_id": target["id"],
        "trial": trial,
        "request": request_snapshot(target, expanded_prompt),
        "response": empty_response(status, expansion_error),
        "evaluation": empty_evaluation(failure_tag),
    }
