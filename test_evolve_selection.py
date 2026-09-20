#!/usr/bin/env python3
"""Candidate-selection invariants for AlphaEvolve's MAP-Elites engine.

The MCP tool evolve_template reports whatever these pick, so a candidate that
genuinely scored 0.0 must still be selectable, and an archived solution must
survive the next generation's re-evaluation reset.

Run: python3 test_evolve_selection.py   (pure stdlib + declared deps)
"""
from types import SimpleNamespace

from alpha_evolve import AlphaEvolveEngine, Candidate, EvolutionState


def stub(grid_resolution=20, tournament_size=3):
    """Engine-less host for the pure selection methods."""
    return SimpleNamespace(config={"map_elites": {"grid_resolution": grid_resolution}},
                           tournament_size=tournament_size)


def state_with(*candidates):
    state = EvolutionState(evolution_id="t", template_name="t", goal="speed")
    state.populations = [list(candidates)]
    return state


def candidate(content, fitness, features=(0.0, 0.0, 0.0)):
    return Candidate(id=content, content=content, generation=0, fitness=fitness,
                     feature_vector=list(features))


def check(name, cond):
    if not cond:
        raise SystemExit(f"FAIL: {name}")
    print(f"ok: {name}")


# 1. A zero fitness is a real score, not a missing one.
zero = candidate("zero", 0.0)
state = state_with(zero)
check("best fitness keeps a 0.0 score",
      AlphaEvolveEngine._get_best_fitness(None, state) == 0.0)
check("best candidate keeps a 0.0-scoring candidate",
      (AlphaEvolveEngine._get_best_candidate(None, state) or zero).id == "zero")

# 2. A valid but unimproving candidate still outranks an invalid one.
#    (fitness -1.0 is the evaluator's invalid-syntax penalty)
valid, invalid = candidate("valid", 0.0), candidate("invalid", -1.0)
picked = AlphaEvolveEngine._tournament_select(stub(), [valid, invalid])
check("tournament prefers valid 0.0 over invalid -1.0", picked.id == "valid")

# 3. Archived solutions survive _evolve_populations resetting elite fitness
#    to None for re-evaluation (the archive holds snapshots, not references).
eng, live = stub(), candidate("mutant", 0.5)
state = state_with(live)
AlphaEvolveEngine._update_archive(eng, state)
live.fitness = None                      # elite carried into the next generation
best = AlphaEvolveEngine._get_best_candidate(eng, state)
check("archived snapshot outlives elite fitness reset",
      best is not None and best.content == "mutant" and best.fitness == 0.5)

print("all selection invariants hold")
