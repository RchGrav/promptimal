from __future__ import annotations

import string
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from promptimal.template.fields import TemplateDiagnostic, inspect_template


@dataclass
class ExpansionResult:
    text: Optional[str] = None
    fields: List[str] = field(default_factory=list)
    diagnostics: List[TemplateDiagnostic] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.diagnostics


def expand_template(
    template: str,
    variable_definitions: List[Dict[str, Any]],
    values: Dict[str, Any],
) -> ExpansionResult:
    inspection = inspect_template(template)
    result = ExpansionResult(fields=list(inspection.fields))
    result.diagnostics.extend(inspection.diagnostics)

    definitions = {
        item.get("name"): item
        for item in variable_definitions
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    for name in inspection.fields:
        if name not in definitions:
            result.diagnostics.append(
                TemplateDiagnostic(
                    "undeclared_field",
                    "Template field %r has no variable declaration" % name,
                )
            )
        elif name not in values:
            result.diagnostics.append(
                TemplateDiagnostic(
                    "missing_value",
                    "Template field %r has no value in the selected case" % name,
                )
            )

    for name, value in values.items():
        definition = definitions.get(name)
        if not definition:
            result.diagnostics.append(
                TemplateDiagnostic(
                    "undeclared_value",
                    "Value %r has no variable declaration" % name,
                )
            )
            continue
        schema = definition.get("value_schema", {})
        try:
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
        except SchemaError as exc:
            result.diagnostics.append(
                TemplateDiagnostic(
                    "invalid_value_schema",
                    "Variable %r has an invalid value schema: %s" % (name, exc),
                )
            )
            continue
        for error in validator.iter_errors(value):
            result.diagnostics.append(
                TemplateDiagnostic(
                    "invalid_value",
                    "Value for %r is invalid: %s" % (name, error.message),
                )
            )

    if result.diagnostics:
        return result

    formatter = string.Formatter()
    output = []
    for literal, field_name, _, _ in formatter.parse(template):
        output.append(literal)
        if field_name is not None:
            output.append(str(values[field_name]))
    result.text = "".join(output)
    return result
