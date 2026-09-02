# promptimal

**CLI for quickly improving your AI prompts through OpenRouter. No dataset needed.**

Just submit your prompt and a description of what you want to improve. Promptimal will then use a genetic algorithm to iteratively refine the prompt until it's better than the original. An LLM evaluates the modified prompts to guide the process, but you can also define your own evaluation function.

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

## Quickstart

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

Once you're done, a UI will open in your terminal for monitoring the optimization process:

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
