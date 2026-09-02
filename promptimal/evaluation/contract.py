from __future__ import annotations

from typing import Any, Dict, List

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from promptimal.evaluation.parse import ParseResult


def _check(identifier: str, status: str, details=None) -> Dict[str, Any]:
    return {"id": identifier, "status": status, "details": details}


def _presentation_check(
    identifier: str,
    constraint: str,
    raw_output: str,
    parse_result: ParseResult,
    media_type: str,
) -> Dict[str, Any]:
    lowered = constraint.casefold()
    stripped = (raw_output or "").strip()
    if "markdown" in lowered and "code fence" in lowered:
        failed = stripped.startswith("```") or stripped.endswith("```")
        return _check(
            identifier,
            "fail" if failed else "pass",
            "Response uses a Markdown code fence" if failed else None,
        )
    if media_type.split(";", 1)[0].strip().lower() == "application/json" and (
        "surrounding prose" in lowered
        or "json array only" in lowered
        or "json object only" in lowered
    ):
        return _check(
            identifier,
            "pass" if parse_result.status == "pass" else "fail",
            parse_result.error,
        )
    return _check(
        identifier,
        "unknown",
        "No deterministic presentation check is defined for this constraint",
    )


def evaluate_contract(
    raw_output: str,
    parsed: ParseResult,
    contract: Dict[str, Any],
) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    checks.append(_check("parse", parsed.status, parsed.error))

    if parsed.status == "pass":
        try:
            Draft202012Validator.check_schema(contract.get("schema", {}))
            validator = Draft202012Validator(
                contract.get("schema", {}), format_checker=FormatChecker()
            )
            errors = list(validator.iter_errors(parsed.value))
            checks.append(
                _check(
                    "schema",
                    "fail" if errors else "pass",
                    "; ".join(error.message for error in errors) if errors else None,
                )
            )
        except SchemaError as exc:
            checks.append(
                _check("schema", "not_run", "Invalid contract schema: %s" % exc)
            )
    else:
        checks.append(_check("schema", "not_run", "Output did not parse"))

    for index, constraint in enumerate(contract.get("presentation_constraints", []), 1):
        checks.append(
            _presentation_check(
                "presentation.%d" % index,
                constraint,
                raw_output,
                parsed,
                contract.get("media_type", ""),
            )
        )

    statuses = {item["status"] for item in checks}
    if "fail" in statuses:
        status = "fail"
    elif "unknown" in statuses or "not_run" in statuses:
        status = "not_run"
    else:
        status = "pass"
    return {"status": status, "checks": checks}
