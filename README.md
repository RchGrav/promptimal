# promptimal

**Refine and verify reusable prompts against real behavior across an OpenRouter model matrix.**

Promptimal's prompt-sheet workbench keeps intent, test cases, intended responses,
output contracts, requirements, prompt revisions, actual model responses, and
finalization decisions in one machine-readable JSON file. You can edit manually,
run repeated cross-model tests, inspect every response, optionally breed candidate
templates from observed failures, and explicitly choose the revision that downstream
tools should use.

The original single-prompt optimizer remains available for compatibility.

![Demo](./assets/demo.gif)

## Installation

```bash
> pipx install promptimal
```

Once installed, add your OpenRouter API key to your environment:

```bash
> export OPENROUTER_API_KEY="..."
```

Promptimal uses `openai/gpt-4o` by default. Set another OpenRouter model slug with
`OPENROUTER_MODEL` or `--model`. The selected model must support structured outputs.

```bash
> export OPENROUTER_MODEL="openai/gpt-4o"
```

## Prompt-sheet quickstart

Start with [the example prompt sheet](./examples/prompt-sheet.example.json), or
produce a sheet from a written specification using
[the bundled schema](./promptimal/sheet/prompt-sheet.schema.json). Validate it
before opening the workbench:

```bash
promptimal validate prompt-sheet.json
promptimal workbench prompt-sheet.json
```

The TUI exposes prompt navigation, manual template editing and live expansion,
execution-profile configuration, repeated tests, raw response and failure
inspection, revision history, optional behavioral evolution, candidate adoption,
and explicit finalization. Opening a JSON file directly is shorthand for the
workbench command:

```bash
promptimal prompt-sheet.json
```

You can also run a test matrix without the TUI:

```bash
promptimal test prompt-sheet.json \
  --prompt namespace.aliases \
  --profile frontier-core \
  --runs 5
```

Each enabled target receives only its configured model, messages, inference
parameters, and provider-routing object. Promptimal does not infer structured
output settings or add sampling parameters. Transport retries, returned model and
provider metadata, raw output, usage, cost, latency, deterministic checks, and
evaluation provenance are retained in the sheet.

After reviewing a prompt and selecting **Finalize**, export the exact downstream
projection:

```bash
promptimal export prompt-sheet.json \
  --finalized \
  --output finalized-prompts.json
```

Or load finalized definitions directly:

```python
from promptimal import PromptSheet

sheet = PromptSheet.load("prompt-sheet.json")
for prompt in sheet.finalized_prompts():
    print(prompt.prompt_id, prompt.prompt_template)
```

Stored observations can also be projected into a reproducible model/prompt
capability matrix:

```bash
promptimal capabilities prompt-sheet.json \
  --output capability-matrix.json \
  --cost-ceiling 0.002
```

The complete data and behavior contract is in the
[Prompt Refinement Workbench specification](./docs/Promptimal-Prompt-Refinement-Workbench-Specification.md).

## Legacy single-prompt quickstart

Open the tool from your terminal:

```bash
> promptimal
```

You'll be asked to input your initial prompt and what you want to improve. Alternatively, you can specify these inputs as command-line arguments:

```bash
> promptimal \
    --prompt "You will be provided with a piece of code, and your task is to explain it in a concise way." \
    --improve "Summaries need to include less code references and be more high-level." \
    --model "openai/gpt-4o"
```

Once you're done, a UI will open in your terminal for monitoring the legacy optimization process:

<img src="./assets/demo.png" width="720" />

## Advanced usage

### Hyperparameters

You can control the optimization parameters by passing additional command-line arguments:

```bash
> promptimal --num_iters=10 --num_samples=20 --threshold=0.7
```

1. `num_iters`: Number of iterations to run the optimization loop for. Equivalent to the number of "generations" in an evolutionary algorithm.
2. `num_samples`: Number of candidate prompts to generate in each iteration. Equivalent to the "population size" in an evolutionary algorithm.
3. `threshold`: Termination threshold for the loop. If a candidate prompt gets a score higher than this threshold, the optimization loop will stop. Default is 1.0.

### Custom evaluators

By default, promptimal uses an LLM-as-judge approach (with self-consistency) to evaluate prompt candidates. But to boost performance, you may want to evaluate prompts against a dataset or use some other evaluation technique. To do this, first create a Python file called `evaluator.py`. Then copy/paste the code below into that file and define your own evaluation function:

```python
import argparse

def evaluator(prompt: str) -> float:
    # Your code goes here
    # Must return value between 0 and 1

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True, type=str)
    args = parser.parse_args()

    score = evaluator(args.prompt)
    print(score)

if __name__ == "__main__":
    main()
```

Once finished, specify the path to `evaluator.py` when you run promptimal:

```bash
> promptimal --evaluator="path/to/evaluator.py"
```

This file will effectively serve as a script that promptimal uses to evaluate prompts.

## Roadmap

1. Evolve not only the prompts, but the meta-prompts (based on the [PromptBreeder paper](https://arxiv.org/pdf/2309.16797)).
2. Pre-define some mutation operators.
3. Generate synthetic tests as part of the evaluation process.
