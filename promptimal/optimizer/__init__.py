__all__ = ["EvolutionRunner", "optimize"]


def __getattr__(name):
    if name == "optimize":
        try:
            from promptimal.optimizer.main import optimize
        except ImportError:
            from optimizer.main import optimize

        return optimize
    if name == "EvolutionRunner":
        try:
            from promptimal.optimizer.evolution import EvolutionRunner
        except ImportError:
            from optimizer.evolution import EvolutionRunner

        return EvolutionRunner
    raise AttributeError(name)
