from __future__ import annotations

import random
from typing import Any, Dict, Iterable, Optional

from promptimal.optimizer.candidates import candidate_vector


def tournament_parent(
    candidates: Iterable[Dict[str, Any]],
    result_sets: Iterable[Dict[str, Any]],
    tournament_size: int = 3,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    population = list(candidates)
    if not population:
        raise ValueError("Cannot select a parent from an empty population")
    sampler = rng or random
    tournament = sampler.sample(population, min(tournament_size, len(population)))
    return max(
        tournament,
        key=lambda item: (candidate_vector(item, result_sets), item.get("id", "")),
    )
