from promptimal.template.expand import expand_template


VARIABLES = [
    {
        "name": "name",
        "description": "name",
        "required": True,
        "value_schema": {"type": "string"},
    }
]


def test_exact_expansion_and_literal_braces():
    result = expand_template("  {{literal}}\n{name}!  ", VARIABLES, {"name": "Ada"})
    assert result.valid
    assert result.text == "  {literal}\nAda!  "


def test_missing_undeclared_and_invalid_values_are_reported():
    missing = expand_template("{name}", VARIABLES, {})
    undeclared = expand_template("{other}", VARIABLES, {"name": "Ada"})
    invalid = expand_template("{name}", VARIABLES, {"name": 42})
    assert {item.code for item in missing.diagnostics} == {"missing_value"}
    assert "undeclared_field" in {item.code for item in undeclared.diagnostics}
    assert "invalid_value" in {item.code for item in invalid.diagnostics}


def test_python_expressions_and_malformed_braces_never_execute():
    expression = expand_template("{name.upper()}", VARIABLES, {"name": "Ada"})
    malformed = expand_template("{name", VARIABLES, {"name": "Ada"})
    assert not expression.valid
    assert "invalid_field" in {item.code for item in expression.diagnostics}
    assert "malformed_braces" in {item.code for item in malformed.diagnostics}
