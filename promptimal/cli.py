from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from promptimal.capability import capability_matrix
from promptimal.execution.runner import ExecutionRunner
from promptimal.sheet import PromptSheet, PromptSheetLoadError
from promptimal.sheet.export import export_finalized
from promptimal.sheet.store import write_json_atomic


def _load(path, schema=None):
    try:
        return PromptSheet.load(path, schema_path=schema)
    except PromptSheetLoadError as exc:
        print("promptimal: %s" % exc, file=sys.stderr)
        return None


def _diagnostics(sheet) -> int:
    for diagnostic in sheet.diagnostics:
        print("%s: %s" % (diagnostic.severity, diagnostic))
    return 1 if sheet.has_errors else 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="promptimal", description="Prompt-sheet refinement workbench"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    workbench = commands.add_parser(
        "workbench", help="Open the captive prompt-sheet TUI"
    )
    workbench.add_argument("sheet")
    workbench.add_argument("--schema")

    validate = commands.add_parser("validate", help="Validate a prompt sheet")
    validate.add_argument("sheet")
    validate.add_argument("--schema")

    test = commands.add_parser(
        "test", help="Execute a prompt revision through OpenRouter"
    )
    test.add_argument("sheet")
    test.add_argument("--prompt", required=True, dest="prompt_id")
    test.add_argument("--revision")
    test.add_argument("--profile")
    test.add_argument("--case", action="append", dest="case_ids")
    test.add_argument("--target", action="append", dest="target_ids")
    test.add_argument("--runs", type=int)

    export = commands.add_parser("export", help="Export downstream prompt definitions")
    export.add_argument("sheet")
    export.add_argument("--finalized", action="store_true", required=True)
    export.add_argument("--output", required=True)

    capabilities = commands.add_parser(
        "capabilities", help="Derive a model/prompt observation matrix"
    )
    capabilities.add_argument("sheet")
    capabilities.add_argument("--output", required=True)
    capabilities.add_argument(
        "--cost-ceiling",
        type=float,
        help="Maximum observed average cost per planned request",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    sheet = _load(args.sheet, getattr(args, "schema", None))
    if sheet is None:
        return 2

    if args.command == "validate":
        code = _diagnostics(sheet)
        if not sheet.diagnostics:
            print("Prompt sheet is valid: %s" % args.sheet)
        return code

    if args.command == "workbench":
        if sheet.diagnostics:
            _diagnostics(sheet)
        from promptimal.tui import run_workbench

        run_workbench(sheet, api_key=os.environ.get("OPENROUTER_API_KEY"))
        return 0

    if args.command == "test":
        if not os.environ.get("OPENROUTER_API_KEY"):
            print(
                "promptimal: OPENROUTER_API_KEY is required for execution",
                file=sys.stderr,
            )
            return 2

        async def execute():
            result = await ExecutionRunner(sheet).run(
                args.prompt_id,
                revision_id=args.revision,
                execution_profile_id=args.profile,
                test_case_ids=args.case_ids,
                target_ids=args.target_ids,
                runs_per_case=args.runs,
            )
            print(json.dumps(result["summary"], indent=2, ensure_ascii=False))

        asyncio.run(execute())
        return 0

    if args.command == "export":
        if _diagnostics(sheet):
            return 1
        export_finalized(sheet, args.output)
        print("Exported finalized prompts to %s" % args.output)
        return 0

    if args.command == "capabilities":
        write_json_atomic(
            capability_matrix(sheet, cost_ceiling=args.cost_ceiling), args.output
        )
        print("Exported capability observations to %s" % args.output)
        return 0
    return 2
