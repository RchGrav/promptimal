# Standard library
import asyncio
import random
from statistics import mean
from typing import List, Tuple

# Third party
import json_repair
from openai import AsyncOpenAI

# Local
try:
    from promptimal.dtos import PromptCandidate, TokenCount
    from promptimal.optimizer.prompts import (
        INIT_POPULATION_PROMPT,
        EVAL_PROMPT,
        CROSSOVER_PROMPT,
    )
except ImportError:
    from dtos import PromptCandidate, TokenCount
    from optimizer.prompts import (
        INIT_POPULATION_PROMPT,
        EVAL_PROMPT,
        CROSSOVER_PROMPT,
    )


async def init_population(
    prompt: str,
    improvement_request: str,
    population_size: int,
    client: AsyncOpenAI,
    model: str,
) -> Tuple[List[PromptCandidate], TokenCount]:
    """
    Initializes a population of candidate prompts.
    """

    system_message = {
        "role": "system",
        "content": INIT_POPULATION_PROMPT.format(
            population_size=population_size, improvement_request=improvement_request
        ),
    }
    user_message = {
        "role": "user",
        "content": f"Generate {population_size} better versions of the following prompt:\n\n<prompt>\n{prompt}\n</prompt>",
    }
    response = await client.chat.completions.create(
        messages=[system_message, user_message],
        model=model,
        temperature=1.0,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "better_prompts",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "prompts": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "description": "A better version of the provided prompt.",
                            },
                            "description": f"A list of {population_size} prompts that are better versions of the provided prompt.",
                        }
                    },
                    "required": ["prompts"],
                    "additionalProperties": False,
                },
            },
        },
    )
    output = json_repair.loads(response.choices[0].message.content)
    population = [PromptCandidate(prompt) for prompt in output["prompts"]]
    population = [PromptCandidate(prompt)] + population  # Add initial prompt

    return population, _get_token_count(response)


async def evaluate_fitness(
    candidate: PromptCandidate,
    initial_prompt: PromptCandidate,
    improvement_request: str,
    client: AsyncOpenAI,
    model: str,
    num_samples=5,
) -> Tuple[PromptCandidate, TokenCount]:
    """
    Evaluates a prompt candidate using a LLM + self-consistency.
    """

    # Elite, already evaluated from the previous generation
    if candidate.fitness:
        return candidate, TokenCount(0, 0)

    # Generate `n_samples` self-evaluations
    request = {
        "messages": [
            {
                "role": "system",
                "content": EVAL_PROMPT.format(
                    initial_prompt=initial_prompt,
                    improvement_request=improvement_request,
                ),
            },
            {
                "role": "user",
                "content": f"Evaluate the following prompt:\n\n<prompt>\n{candidate.prompt}\n</prompt>",
            },
        ],
        "model": model,
        "temperature": 1.0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "evaluation",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "evaluation": {
                            "type": "string",
                            "description": "Justification for your score.",
                        },
                        "score": {
                            "type": "number",
                            "description": "A score between 1-10 for the prompt, with 10 being the highest.",
                        },
                    },
                    "required": ["evaluation", "score"],
                    "additionalProperties": False,
                },
            },
        },
    }
    responses = await asyncio.gather(
        *(client.chat.completions.create(**request) for _ in range(num_samples))
    )
    outputs = [
        json_repair.loads(response.choices[0].message.content)
        for response in responses
    ]

    # Consolidate results
    candidate.fitness = mean(output["score"] for output in outputs) / 10
    candidate.reflection = outputs[0]["evaluation"]  # 1st evaluation is best

    token_count = TokenCount(0, 0)
    for response in responses:
        token_count += _get_token_count(response)

    return candidate, token_count


def select_parent(
    population: List[PromptCandidate], tournament_size=3
) -> PromptCandidate:
    tournament = random.sample(population, tournament_size)
    return max(tournament, key=lambda candidate: candidate.fitness)


async def crossover(
    parent1: PromptCandidate,
    parent2: PromptCandidate,
    initial_prompt: str,
    improvement_request: str,
    client: AsyncOpenAI,
    model: str,
) -> Tuple[PromptCandidate, TokenCount]:
    system_message = {
        "role": "system",
        "content": CROSSOVER_PROMPT.format(
            initial_prompt=initial_prompt, improvement_request=improvement_request
        ),
    }
    user_message = {
        "role": "user",
        "content": f"Combine the following prompts into a better one:\n\n<prompt_1>\n{parent1.prompt}\n</prompt_1>\n\n<prompt_2>\n{parent2.prompt}\n</prompt_2>",
    }
    response = await client.chat.completions.create(
        messages=[system_message, user_message],
        model=model,
        temperature=1.0,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "prompt_crossover_response",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "analysis": {
                            "type": "string",
                            "description": "Your step-by-step analysis of the two prompts.",
                        },
                        "prompt": {
                            "type": "string",
                            "description": "The combined and improved prompt.",
                        },
                    },
                    "required": ["analysis", "prompt"],
                    "additionalProperties": False,
                },
            },
        },
    )
    output = json_repair.loads(response.choices[0].message.content)

    return PromptCandidate(output["prompt"]), _get_token_count(response)


def _get_token_count(response) -> TokenCount:
    usage = response.usage
    if not usage:
        return TokenCount(0, 0)

    cost = getattr(usage, "cost", None)
    if cost is None:
        cost = (getattr(usage, "model_extra", None) or {}).get("cost", 0.0)

    return TokenCount(
        usage.prompt_tokens or 0,
        usage.completion_tokens or 0,
        float(cost or 0.0),
    )
