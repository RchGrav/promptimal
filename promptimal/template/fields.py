from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from typing import List


_SIMPLE_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class TemplateDiagnostic:
    code: str
    message: str


@dataclass
class TemplateInspection:
    fields: List[str] = field(default_factory=list)
    diagnostics: List[TemplateDiagnostic] = field(default_factory=list)


def inspect_template(template: str) -> TemplateInspection:
    result = TemplateInspection()
    formatter = string.Formatter()
    try:
        parsed = list(formatter.parse(template))
    except ValueError as exc:
        result.diagnostics.append(TemplateDiagnostic("malformed_braces", str(exc)))
        return result

    for _, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if not _SIMPLE_FIELD.fullmatch(field_name):
            result.diagnostics.append(
                TemplateDiagnostic(
                    "invalid_field",
                    "Template field %r is not a simple named field" % field_name,
                )
            )
            continue
        if conversion:
            result.diagnostics.append(
                TemplateDiagnostic(
                    "unsupported_conversion",
                    "Template field %r uses unsupported conversion !%s"
                    % (field_name, conversion),
                )
            )
        if format_spec:
            result.diagnostics.append(
                TemplateDiagnostic(
                    "unsupported_format_spec",
                    "Template field %r uses an unsupported format specification"
                    % field_name,
                )
            )
        if field_name not in result.fields:
            result.fields.append(field_name)
    return result
