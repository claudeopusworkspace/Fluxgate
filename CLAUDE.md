# Fluxgate — project conventions

Procedural neon tower-defense roguelite. Python 3.12 + pygame + numpy.

## Architecture (respect the split)
- `fluxgate/core/` — **pure deterministic simulation**. stdlib only (no pygame,
  no numpy). Everything gameplay-affecting lives here and is reproducible from a
  single seed. If you add randomness, draw it from a `Rng` stream so headless
  runs stay deterministic.
- `fluxgate/render/` — pygame view. **Never mutate the sim from here.** All
  visuals are generated procedurally; do not add image/audio asset files.
- `fluxgate/ai/` — heuristic AI player used for balance testing.
- `fluxgate/sim/` — headless balance harness.
- `tests/` — pytest (logic + headless render smoke via `SDL_VIDEODRIVER=dummy`).

## Balance
- All tunables live in `fluxgate/core/config.py` — change numbers there, nowhere
  else.
- After any balance-relevant change, re-run `python -m fluxgate.sim.balance
  --all --games 40` and keep normal near ~55–65% AI win with deaths clustered in
  the late game. Keep enemy *count* growth flat and *HP* growth steep (see the
  config comment — this prevents the kill-income runaway loop).
- The GUI and harness must keep driving the same `GameState.tick(DT)`; don't fork
  gameplay logic into the renderer.

## Workflow
- Run tests before committing: `pytest -q`.
- Conventional commits. Keep the sim deterministic — a failing
  `test_determinism_same_seed` means something pulled non-seeded randomness.
