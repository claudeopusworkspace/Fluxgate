"""Headless balance harness.

Runs the heuristic AI across many seeds/difficulties and reports aggregate
outcomes: win rate, average waves survived, where runs die, and economy. This
is the tool used to *verify the game's logic and balance* without any rendering.

Usage:
    python -m fluxgate.sim.balance --games 200 --difficulty normal
    python -m fluxgate.sim.balance --all          # sweep all difficulties
    python -m fluxgate.sim.balance --towers        # single-tower DPS table
"""

from __future__ import annotations

import argparse
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import List

from ..ai.heuristic import play_game
from ..core import config as C
from ..core.game import GameState, PHASE_VICTORY


@dataclass
class RunResult:
    seed: int
    won: bool
    waves: int
    core_hp: float
    kills: int
    leaks: int
    money_earned: int
    towers: int


def run_batch(games: int, difficulty: str, seed_start: int = 0) -> List[RunResult]:
    results = []
    for i in range(games):
        seed = seed_start + i
        g = play_game(seed, difficulty=difficulty)
        results.append(RunResult(
            seed=seed,
            won=(g.phase == PHASE_VICTORY),
            waves=g.stats.waves_cleared,
            core_hp=g.core_hp,
            kills=g.stats.kills,
            leaks=g.stats.leaks,
            money_earned=g.stats.money_earned,
            towers=len(g.towers),
        ))
    return results


def summarize(results: List[RunResult], difficulty: str) -> str:
    n = len(results)
    wins = sum(1 for r in results if r.won)
    waves = [r.waves for r in results]
    death_wave = Counter(r.waves + 1 for r in results if not r.won)
    lines = []
    lines.append(f"=== Difficulty: {difficulty}  (n={n}) ===")
    lines.append(f"  Win rate          : {wins}/{n} = {100*wins/n:.1f}%")
    lines.append(f"  Waves cleared     : mean {statistics.mean(waves):.1f}  "
                 f"median {statistics.median(waves):.0f}  "
                 f"min {min(waves)}  max {max(waves)}")
    if any(not r.won for r in results):
        survived = [r.core_hp for r in results if r.won]
        lines.append(f"  Core HP on win    : mean "
                     f"{statistics.mean(survived):.0f}" if survived else
                     "  Core HP on win    : (no wins)")
        top_deaths = death_wave.most_common(6)
        lines.append("  Death-wave histogram (where runs end):")
        for wv, cnt in sorted(top_deaths):
            bar = "#" * cnt
            lines.append(f"     wave {wv:>2}: {cnt:>3} {bar}")
    lines.append(f"  Kills/run         : mean {statistics.mean(r.kills for r in results):.0f}")
    lines.append(f"  Leaks/run         : mean {statistics.mean(r.leaks for r in results):.1f}")
    lines.append(f"  Towers built/run  : mean {statistics.mean(r.towers for r in results):.1f}")
    return "\n".join(lines)


def tower_dps_table() -> str:
    """Theoretical single-target DPS per tower per level (pre-modifiers)."""
    from ..core.entities import resolve_tower_stats
    lines = ["=== Tower DPS table (base, single-target, no buffs) ==="]
    lines.append(f"  {'tower':<10}{'lvl':<5}{'dmg':>8}{'rate':>7}{'dps':>9}"
                 f"{'range':>7}{'cost':>7}{'dps/cost':>10}")
    for ttype in C.TOWER_ORDER:
        spec = C.TOWERS[ttype]
        for lvl in range(1, spec["max_level"] + 2):
            s = resolve_tower_stats(ttype, lvl)
            dps = s["damage"] * s["fire_rate"]
            # account for multi-hit kinds (rough)
            if spec["kind"] == "chain":
                dps *= 1 + sum(0.7 ** i for i in range(1, int(s["chain_targets"])))
            cost = spec["cost"]
            dpc = dps / cost if cost else 0
            lines.append(f"  {ttype:<10}{lvl:<5}{s['damage']:>8.1f}"
                         f"{s['fire_rate']:>7.2f}{dps:>9.1f}{s['range']:>7.1f}"
                         f"{cost:>7}{dpc:>10.2f}")
    return "\n".join(lines)


def enemy_table() -> str:
    """Enemy HP at various waves to sanity-check scaling vs tower DPS."""
    from ..core.waves import _hp_scale
    lines = ["=== Enemy effective HP by wave ==="]
    waves = [1, 5, 10, 15, 20, 25, 30]
    header = f"  {'enemy':<12}" + "".join(f"w{w:>6}" for w in waves)
    lines.append(header)
    for etype, spec in C.ENEMIES.items():
        row = f"  {etype:<12}"
        for w in waves:
            hp = spec["base_hp"] * _hp_scale(w)
            row += f"{hp:>7.0f}"
        lines.append(row)
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=120)
    ap.add_argument("--difficulty", default="normal")
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--all", action="store_true", help="sweep all difficulties")
    ap.add_argument("--towers", action="store_true", help="print DPS table only")
    ap.add_argument("--enemies", action="store_true", help="print enemy HP table only")
    args = ap.parse_args()

    if args.towers:
        print(tower_dps_table())
        return
    if args.enemies:
        print(enemy_table())
        return

    diffs = list(C.DIFFICULTY) if args.all else [args.difficulty]
    for d in diffs:
        results = run_batch(args.games, d, args.seed_start)
        print(summarize(results, d))
        print()


if __name__ == "__main__":
    main()
