from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Tuple

from jsonschema import Draft202012Validator, FormatChecker

from promptimal.template.expand import expand_template


def _result(identifier: str, status: str, details=None) -> Dict[str, Any]:
    return {"id": identifier, "status": status, "details": details}


def _normalize_scalar(value: Any, case_sensitive: bool) -> Any:
    if isinstance(value, str) and not case_sensitive:
        return value.casefold()
    return value


def _sequence_equal(
    actual: Iterable[Any],
    expected: Iterable[Any],
    ordered: bool,
    case_sensitive: bool,
    preserve_duplicates: bool,
) -> bool:
    actual_values = [_normalize_scalar(item, case_sensitive) for item in actual]
    expected_values = [_normalize_scalar(item, case_sensitive) for item in expected]
    if ordered:
        return actual_values == expected_values
    encoded_actual = [
        json.dumps(item, ensure_ascii=False, sort_keys=True) for item in actual_values
    ]
    encoded_expected = [
        json.dumps(item, ensure_ascii=False, sort_keys=True) for item in expected_values
    ]
    if preserve_duplicates:
        return Counter(encoded_actual) == Counter(encoded_expected)
    return set(encoded_actual) == set(encoded_expected)


def _json_pointer(value: Any, pointer: str) -> Tuple[bool, Any]:
    if pointer in (None, ""):
        return True, value
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return False, None
    current = value
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                return False, None
            try:
                index = int(token)
                if index < 0:
                    return False, None
                current = current[index]
            except (ValueError, IndexError):
                return False, None
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            return False, None
    return True, current


def _expanded_parameter(
    parameters: Dict[str, Any],
    variables: List[Dict[str, Any]],
    values: Dict[str, Any],
) -> Tuple[bool, Any, str]:
    if "template" in parameters:
        expanded = expand_template(parameters["template"], variables, values)
        if expanded.diagnostics:
            return False, None, "; ".join(item.message for item in expanded.diagnostics)
        return True, expanded.text, ""
    if "value" in parameters:
        return True, parameters["value"], ""
    return False, None, "Check parameters require 'template' or 'value'"


def evaluate_requirements(
    parsed_value: Any,
    raw_output: str,
    requirements: List[Dict[str, Any]],
    variables: List[Dict[str, Any]],
    case_values: Dict[str, Any],
    parse_succeeded: bool,
) -> List[Dict[str, Any]]:
    results = []
    for requirement in requirements:
        identifier = requirement.get("id", "requirement")
        check = requirement.get("check")
        if not check:
            results.append(
                _result(
                    identifier,
                    "unknown",
                    "Requirement requires semantic or human review",
                )
            )
            continue
        check_type = check.get("type")
        parameters = check.get("parameters", {})

        if check_type == "regex":
            pattern = parameters.get("pattern")
            if not isinstance(pattern, str):
                results.append(_result(identifier, "not_run", "Missing regex pattern"))
                continue
            flags = 0 if parameters.get("case_sensitive", True) else re.IGNORECASE
            try:
                matched = re.search(pattern, raw_output or "", flags) is not None
            except re.error as exc:
                results.append(
                    _result(identifier, "not_run", "Invalid regex: %s" % exc)
                )
                continue
            results.append(_result(identifier, "pass" if matched else "fail"))
            continue

        if not parse_succeeded:
            results.append(_result(identifier, "not_run", "Output did not parse"))
            continue

        location_ok, located = _json_pointer(parsed_value, parameters.get("path", ""))
        if not location_ok:
            results.append(
                _result(identifier, "fail", "Declared JSON location was not found")
            )
            continue

        if check_type == "json_schema":
            schema = parameters.get("schema")
            if not isinstance(schema, dict):
                results.append(_result(identifier, "not_run", "Missing JSON Schema"))
                continue
            try:
                Draft202012Validator.check_schema(schema)
                errors = list(
                    Draft202012Validator(
                        schema, format_checker=FormatChecker()
                    ).iter_errors(located)
                )
            except Exception as exc:
                results.append(
                    _result(identifier, "not_run", "Invalid JSON Schema: %s" % exc)
                )
                continue
            results.append(
                _result(
                    identifier,
                    "fail" if errors else "pass",
                    "; ".join(error.message for error in errors) if errors else None,
                )
            )
            continue

        value_checks = {
            "exact_equality",
            "json_deep_equality",
            "ordered_sequence_equality",
            "unordered_sequence_equality",
            "json_array_includes_expanded_exact_string",
            "json_location_includes_expanded_exact_value",
            "json_array_excludes_expanded_exact_string",
            "json_location_excludes_expanded_exact_value",
        }
        if check_type not in value_checks:
            results.append(
                _result(
                    identifier,
                    "unknown",
                    "Unsupported deterministic check %r" % check_type,
                )
            )
            continue

        value_ok, expected, value_error = _expanded_parameter(
            parameters, variables, case_values
        )
        if not value_ok:
            results.append(_result(identifier, "not_run", value_error))
            continue

        case_sensitive = parameters.get("case_sensitive", True)
        preserve_duplicates = parameters.get("preserve_duplicates", True)
        actual_normalized = _normalize_scalar(located, case_sensitive)
        expected_normalized = _normalize_scalar(expected, case_sensitive)

        if check_type in ("exact_equality", "json_deep_equality"):
            passed = actual_normalized == expected_normalized
        elif check_type in ("ordered_sequence_equality", "unordered_sequence_equality"):
            if not isinstance(located, list) or not isinstance(expected, list):
                results.append(
                    _result(identifier, "fail", "Compared value is not an array")
                )
                continue
            passed = _sequence_equal(
                located,
                expected,
                check_type == "ordered_sequence_equality",
                case_sensitive,
                preserve_duplicates,
            )
        elif check_type in (
            "json_array_includes_expanded_exact_string",
            "json_location_includes_expanded_exact_value",
        ):
            if not isinstance(located, list):
                results.append(
                    _result(identifier, "fail", "Compared value is not an array")
                )
                continue
            passed = expected_normalized in [
                _normalize_scalar(item, case_sensitive) for item in located
            ]
        elif check_type in (
            "json_array_excludes_expanded_exact_string",
            "json_location_excludes_expanded_exact_value",
        ):
            if not isinstance(located, list):
                results.append(
                    _result(identifier, "fail", "Compared value is not an array")
                )
                continue
            passed = expected_normalized not in [
                _normalize_scalar(item, case_sensitive) for item in located
            ]
        results.append(
            _result(
                identifier,
                "pass" if passed else "fail",
                None if passed else "Deterministic requirement check failed",
            )
        )
    return results
