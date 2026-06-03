"""A heuristic AI player used to verify balance headlessly.

It is intentionally *reasonable, not optimal*: it places towers on
high-coverage cells, maintains a role mix that unlocks with wave progress,
upgrades its best-placed towers when flush, and picks augments by a priority
table. If this baseline wins ~40-60% on normal, a thinking human should do
comfortably better — which is the balance target.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from ..core import config as C
from ..core.game import (GameState, PHASE_BUILD, PHASE_COMBAT, PHASE_DEFEAT,
                         PHASE_VICTORY)

# desired relative composition + earliest wave the AI will build the type
ROLE_WEIGHT = {
    "pulse": 3.0, "splinter": 2.0, "mortar": 2.0, "frost": 1.5,
    "arc": 1.5, "rail": 2.0, "venom": 1.2, "beacon": 1.0,
}
ROLE_UNLOCK = {
    "pulse": 1, "splinter": 1, "frost": 1, "mortar": 2,
    "arc": 4, "venom": 5, "rail": 5, "beacon": 6,
}

# augment priority (higher picked first); offense & economy favored early
AUGMENT_PRIORITY = {
    "dmg2": 10, "dmg1": 8, "exec": 9, "rate1": 7, "pierce_armor": 7,
    "chain_plus": 6, "splash_plus": 6, "overkill": 6, "dot_plus": 5,
    "range1": 5, "crit1": 6, "slow_hit": 6, "money1": 7, "discount": 6,
    "coreheal": 8, "firstkill": 6,
}


class HeuristicAI:
    def __init__(self, game: GameState):
        self.g = game
        self._coverage = self._compute_coverage()
        # buildable cells sorted best-coverage first
        self._spots: List[Tuple[int, int]] = sorted(
            game.map.buildable, key=lambda c: -self._coverage[c])

    # -- coverage precomputation -- #
    def _compute_coverage(self) -> Dict[Tuple[int, int], float]:
        m = self.g.map
        # sample the path densely
        samples = []
        n = max(2, int(m.total_length * 2))
        for i in range(n + 1):
            samples.append(m.pos_at(m.total_length * i / n))
        cov: Dict[Tuple[int, int], float] = {}
        R = 3.0
        R2 = R * R
        for cell in m.buildable:
            cx, cy = cell[0] + 0.5, cell[1] + 0.5
            score = 0.0
            for (sx, sy) in samples:
                d2 = (sx - cx) ** 2 + (sy - cy) ** 2
                if d2 <= R2:
                    score += 1.0 - math.sqrt(d2) / R
            cov[cell] = score
        return cov

    # -- main entry: advance one build phase worth of decisions -- #
    def take_build_actions(self) -> None:
        g = self.g
        if g.offered_augments:
            self._pick_augment()
        target_count = min(len(self._spots), 4 + g.wave_index)
        guard = 0
        while guard < 200:
            guard += 1
            acted = self._spend_step(target_count)
            if not acted:
                break

    def _pick_augment(self) -> None:
        g = self.g
        best = max(g.offered_augments,
                   key=lambda a: AUGMENT_PRIORITY.get(a["id"], 1))
        g.choose_augment(best["id"])

    def _open_spots(self) -> List[Tuple[int, int]]:
        return [c for c in self._spots if g_free(self.g, c)]

    def _spend_step(self, target_count: int) -> bool:
        g = self.g
        n_towers = len(g.towers)
        # Prefer building until we hit target count, then upgrade.
        if n_towers < target_count:
            if self._try_build():
                return True
            if self._try_upgrade():
                return True
            return False
        else:
            if self._try_upgrade():
                return True
            if self._try_build():
                return True
            return False

    def _try_build(self) -> bool:
        g = self.g
        ttype = self._choose_type()
        if ttype is None:
            return False
        if g.money < g.build_cost(ttype):
            return False
        spot = self._best_spot_for(ttype)
        if spot is None:
            return False
        return g.build_tower(spot[0], spot[1], ttype) is not None

    def _choose_type(self) -> Optional[str]:
        g = self.g
        counts: Dict[str, int] = {k: 0 for k in ROLE_WEIGHT}
        for t in g.towers:
            counts[t.ttype] = counts.get(t.ttype, 0) + 1
        best_type = None
        best_deficit = -1.0
        for ttype, weight in ROLE_WEIGHT.items():
            if g.wave_index < ROLE_UNLOCK[ttype]:
                continue
            if g.money < g.build_cost(ttype):
                continue
            # beacon only worth it once we have a cluster
            if ttype == "beacon" and len(g.towers) < 4:
                continue
            deficit = weight / (1.0 + counts[ttype])
            if deficit > best_deficit:
                best_deficit = deficit
                best_type = ttype
        return best_type

    def _best_spot_for(self, ttype: str) -> Optional[Tuple[int, int]]:
        g = self.g
        free = [c for c in self._spots if g_free(g, c)]
        if not free:
            return None
        if ttype == "beacon":
            # maximize number of existing towers within buff radius
            br = C.TOWERS["beacon"]["buff_radius"]
            def beacon_score(c):
                cx, cy = c[0] + 0.5, c[1] + 0.5
                return sum(1 for t in g.towers
                           if math.hypot(t.x - cx, t.y - cy) <= br)
            return max(free, key=beacon_score)
        # otherwise best coverage
        return free[0]  # already sorted by coverage desc

    def _try_upgrade(self) -> bool:
        g = self.g
        # upgrade the highest-coverage, non-maxed, affordable tower
        best = None
        best_key = -1.0
        for t in g.towers:
            price = g.upgrade_price(t)
            if price is None or g.money < price:
                continue
            if C.TOWERS[t.ttype]["kind"] == "support":
                continue
            key = self._coverage.get((t.cx, t.cy), 0.0) / (t.level + 1)
            if key > best_key:
                best_key = key
                best = t
        if best is None:
            return False
        return g.upgrade_tower(best)


def g_free(g: GameState, cell: Tuple[int, int]) -> bool:
    return g.tower_at(cell[0], cell[1]) is None


def play_game(seed: int, difficulty: str = "normal",
              max_seconds: float = 1800.0) -> GameState:
    """Run one full AI-played game headlessly and return the final state."""
    g = GameState(seed=seed, difficulty=difficulty)
    ai = HeuristicAI(g)
    max_ticks = int(max_seconds / C.DT)
    ticks = 0
    while ticks < max_ticks:
        if g.phase == PHASE_BUILD:
            ai.take_build_actions()
            if not g.start_wave():
                break
        if g.phase in (PHASE_VICTORY, PHASE_DEFEAT):
            break
        # run the combat phase to completion (or defeat)
        while g.phase == PHASE_COMBAT and ticks < max_ticks:
            g.tick(C.DT)
            ticks += 1
    return g
