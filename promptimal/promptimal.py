# Standard library
import os
import argparse
import subprocess
from typing import Optional, Tuple

# Local
try:
    from promptimal.app import App
    from promptimal.dtos import PromptCandidate, TokenCount
except ImportError:
    from app import App
    from dtos import PromptCandidate, TokenCount


#########
# HELPERS
#########


def generate_evaluator(evaluator_path: Optional[str]) -> Optional[callable]:
    if not evaluator_path:
        return None

    async def evaluator(
        candidate: PromptCandidate, *args
    ) -> Tuple[PromptCandidate, TokenCount]:
        if candidate.fitness != None:
            return candidate, TokenCount(0, 0)

        result = subprocess.run(
            ["python", evaluator_path, "--prompt", candidate.prompt],
            capture_output=True,
            text=True,
            check=True,
        )
        candidate.fitness = float(result.stdout.strip())
        return candidate, TokenCount(0, 0)

    return evaluator


######
# MAIN
######


def main():
    parser = argparse.ArgumentParser(
        description="Optimize your prompts using a genetic algorithm."
    )
    parser.add_argument(
        "--prompt",
        default="",
        required=False,
        type=str,
        help="Initial prompt to optimize.",
    )
    parser.add_argument(
        "--improve",
        default="",
        required=False,
        type=str,
        help="Description of what you want to improve about the prompt.",
    )
    parser.add_argument(
        "--num_iters",
        default=5,
        required=False,
        type=int,
        help="Number of iterations to run the optimization loop for.",
    )
    parser.add_argument(
        "--num_samples",
        default=10,
        required=False,
        type=int,
        help="Number of prompts to generate in each iteration.",
    )
    parser.add_argument(
        "--threshold",
        default=1.0,
        required=False,
        type=float,
        help="Score threshold to stop the optimization loop.",
    )
    parser.add_argument(
        "--openrouter_api_key",
        default="",
        required=False,
        type=str,
        help="OpenRouter API key.",
    )
    parser.add_argument(
        "--model",
        default=None,
        required=False,
        type=str,
        help="OpenRouter model slug. Defaults to OPENROUTER_MODEL or openai/gpt-4o.",
    )
    parser.add_argument(
        "--evaluator",
        default="",
        required=False,
        type=str,
        help="Path to your custom evaluator script.",
    )
    args = parser.parse_args()

    api_key = args.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("\033[1;31mOpenRouter API key not found.\033[0m")
        return

    init_prompt = (
        input("\033[1;90mInitial prompt (use \\n for newlines):\033[0m\n\n")
        if not args.prompt
        else args.prompt
    ).replace("\\n", "\n")
    improvement_request = (
        input("\n\033[1;90mWhat do you want to improve:\033[0m\n\n")
        if not args.improve
        else args.improve
    ).replace("\\n", "\n")

    app = App(init_prompt)
    optimized_prompt, is_finished = app.start(
        improvement_request=improvement_request,
        num_iters=args.num_iters,
        population_size=args.num_samples,
        threshold=args.threshold,
        api_key=api_key,
        model=args.model,
        evaluator=generate_evaluator(args.evaluator),
    )

    if args.prompt:
        print(f"\033[1;90mInitial prompt:\033[0m\n\n{init_prompt}")
    if args.improve:
        print(
            f"\n\033[1;90mWhat do you want to improve:\033[0m\n\n{improvement_request}"
        )
    if is_finished:
        print(
            f"\n🧬 \033[1;35mOPTIMIZED PROMPT\033[0m 🧬\n\n\033[35m{optimized_prompt}\033[0m"
        )
    else:
        print(f"\n\033[1;31mOptimization loop terminated.\033[0m")
