from __future__ import annotations

import copy
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from promptimal.execution.openrouter import OpenRouterChatCompletionsAdapter


MUTATOR_SYSTEM_PROMPT = """You mutate reusable prompt templates for observed behavior.
Return JSON only in this exact shape: {"candidates":[{"prompt_template":"..."}]}.
Change only prompt template text. Preserve every named placeholder exactly, including braces.
Do not add concrete benchmark inputs or intended benchmark answers."""


def mutator_context(
    operation: Dict[str, Any],
    parent_templates: Iterable[str],
    candidate_count: int,
    aggregate_failures: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "candidate_count": candidate_count,
        "intent": copy.deepcopy(operation["intent"]),
        "parent_templates": list(parent_templates),
        "variables": [
            {
                "name": variable.get("name"),
                "description": variable.get("description"),
                "required": variable.get("required"),
            }
            for variable in operation.get("variables", [])
        ],
        "output_contract": copy.deepcopy(operation.get("output_contract", {})),
        "behavioral_requirements": copy.deepcopy(
            operation.get("behavioral_requirements", [])
        ),
        "aggregate_failures": copy.deepcopy(list(aggregate_failures or [])),
    }


async def generate_templates(
    operation: Dict[str, Any],
    parent_templates: Iterable[str],
    candidate_count: int,
    target: Dict[str, Any],
    timeout_seconds: float,
    max_transport_retries: int,
    aggregate_failures: Optional[Iterable[Dict[str, Any]]] = None,
    api_key: Optional[str] = None,
    client: Optional[Any] = None,
) -> Tuple[List[str], Optional[Dict[str, Any]], Dict[str, Any]]:
    context = mutator_context(
        operation,
        parent_templates,
        candidate_count,
        aggregate_failures,
    )
    messages = [
        {"role": "system", "content": MUTATOR_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(context, ensure_ascii=False, sort_keys=True),
        },
    ]
    if target.get("adapter") != OpenRouterChatCompletionsAdapter.adapter_name:
        error = {
            "type": "UnknownAdapter",
            "message": "Unsupported mutator adapter %r" % target.get("adapter"),
        }
        return [], error, {"status": "api_error", "error": error}
    adapter = OpenRouterChatCompletionsAdapter(
        timeout_seconds=timeout_seconds,
        max_transport_retries=max_transport_retries,
        api_key=api_key,
        client=client,
    )
    response = await adapter.execute(target, messages)
    if response["status"] != "ok":
        return [], copy.deepcopy(response.get("error")), response
    try:
        payload = json.loads(response.get("raw_output") or "")
    except (TypeError, json.JSONDecodeError) as exc:
        return [], {"type": type(exc).__name__, "message": str(exc)}, response
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        return (
            [],
            {
                "type": "MutatorOutputError",
                "message": "Mutator output must contain a candidates array",
            },
            response,
        )
    templates = []
    for index, item in enumerate(payload["candidates"]):
        if not isinstance(item, dict) or not isinstance(
            item.get("prompt_template"), str
        ):
            return (
                templates,
                {
                    "type": "MutatorOutputError",
                    "message": "Candidate %d has no string prompt_template" % index,
                },
                response,
            )
        templates.append(item["prompt_template"])
    return templates[:candidate_count], None, response
