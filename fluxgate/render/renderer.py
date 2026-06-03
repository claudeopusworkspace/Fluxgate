"""Procedural world renderer.

Draws the entire game from generated shapes/gradients/glow — towers, enemies,
projectiles, the path, the core, and transient effects. The renderer is a pure
*view* of :class:`GameState`; it never mutates the sim. A small ``View`` holds
the world->screen transform and transient UI hover state.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pygame

from ..core import config as C
from ..core.entities import Enemy, Tower
from ..core.game import GameState
from . import draw, palette as P
from .particles import ParticleSystem

# enemy_type -> number of polygon sides (procedural silhouettes)
ENEMY_SIDES: Dict[str, int] = {
    "grunt": 4, "runner": 3, "tank": 6, "mite": 3, "shielded": 4,
    "healer": 5, "splitter": 4, "splitterling": 4, "phantom": 0, "boss": 8,
}
TOWER_SIDES: Dict[str, int] = {
    "pulse": 4, "splinter": 6, "mortar": 8, "frost": 4, "arc": 3,
    "rail": 5, "venom": 6, "beacon": 5,
}


@dataclass
class View:
    cell: int
    ox: int
    oy: int
    time: float = 0.0
    hover_cell: Optional[Tuple[int, int]] = None
    placing: Optional[str] = None
    selected: Optional[Tower] = None

    def w2s(self, x: float, y: float) -> Tuple[int, int]:
        return (int(self.ox + x * self.cell), int(self.oy + y * self.cell))

    def s2cell(self, sx: int, sy: int) -> Tuple[int, int]:
        return ((sx - self.ox) // self.cell, (sy - self.oy) // self.cell)


class Renderer:
    def __init__(self, view: View, field_w: int, field_h: int):
        self.view = view
        self.field_w = field_w
        self.field_h = field_h
        self.particles = ParticleSystem()
        self._bg: Optional[pygame.Surface] = None
        self._stars: List[Tuple[int, int, int, Tuple[int, int, int]]] = []
        self._seen_effects: set = set()
        self._last_kills = 0
        self._rng = random.Random(99)

    # --------------------------------------------------------------- #
    def build_background(self, game: GameState) -> None:
        v = self.view
        w = self.field_w
        h = self.field_h
        bg = draw.vertical_gradient(w, h, P.BG_TOP, P.BG_BOTTOM).copy()
        # generated starfield
        rng = random.Random(game.seed * 31 + 7)
        for _ in range(150):
            sx = rng.randint(0, w - 1)
            sy = rng.randint(0, h - 1)
            b = rng.randint(40, 160)
            pygame.draw.circle(bg, (b, b, min(255, b + 40)), (sx, sy),
                               rng.choice((1, 1, 2)))
        # subtle grid
        for cx in range(game.map.width + 1):
            x = v.ox + cx * v.cell - v.ox  # local coords (bg is field-local)
            x = cx * v.cell
            pygame.draw.line(bg, P.GRID_COLOR, (x, 0), (x, game.map.height * v.cell), 1)
        for cy in range(game.map.height + 1):
            y = cy * v.cell
            pygame.draw.line(bg, P.GRID_COLOR, (0, y), (game.map.width * v.cell, y), 1)
        self._bg = bg

    # --------------------------------------------------------------- #
    def draw_world(self, surf: pygame.Surface, game: GameState, dt: float) -> None:
        v = self.view
        v.time += dt
        if self._bg is None:
            self.build_background(game)
        # background blit at field origin
        surf.blit(self._bg, (v.ox, v.oy))

        self._ingest_effects(game)
        self.particles.ambient(self.field_w, self.field_h)
        self.particles.update(dt)

        self._draw_path(surf, game)
        self._draw_buildable_hint(surf, game)
        self._draw_range_preview(surf, game)
        self._draw_core(surf, game)
        self._draw_towers(surf, game)
        self._draw_enemies(surf, game)
        self._draw_projectiles(surf, game)
        self._draw_effects(surf, game)
        self.particles.draw(surf)

    # ---- path + core ---- #
    def _draw_path(self, surf: pygame.Surface, game: GameState) -> None:
        v = self.view
        pts = [v.w2s(x, y) for (x, y) in game.map.polyline]
        if len(pts) < 2:
            return
        cw = v.cell
        # glow underlay
        for a, b in zip(pts, pts[1:]):
            draw.neon_line(surf, a, b, P.PATH_CORE, int(cw * 0.62),
                           glow_color=P.PATH_GLOW, glow_radius=int(cw * 0.45))
        # solid track
        for a, b in zip(pts, pts[1:]):
            pygame.draw.line(surf, P.darken(P.PATH_GLOW, 0.35), a, b, int(cw * 0.42))
        # animated energy flow (dashes moving toward core)
        flow = (v.time * 2.2) % 1.0
        total = game.map.total_length
        n = max(2, int(total))
        for i in range(n * 2):
            d = (i / 2 + flow) % total
            x, y = game.map.pos_at(d)
            sx, sy = v.w2s(x, y)
            draw.blit_glow(surf, (sx, sy), int(cw * 0.18),
                           P.lighten(P.PATH_GLOW, 0.3), 0.7)
        # spawn portal
        spx, spy = v.w2s(*game.map.polyline[0])
        pulse = P.pulse(v.time, 0.5, 1.0, 0.8)
        draw.neon_circle(surf, (spx, spy), cw * 0.3,
                         P.darken((120, 80, 200), 0.2), (180, 140, 255),
                         (160, 100, 255), int(cw * 0.7), 3, pulse)

    def _draw_core(self, surf: pygame.Surface, game: GameState) -> None:
        v = self.view
        cx, cy = v.w2s(*game.map.polyline[-1])
        cw = v.cell
        frac = game.core_hp / max(1.0, game.core_max_hp)
        col = P.health_color(frac)
        pulse = P.pulse(v.time, 0.6, 1.0, 1.2)
        draw.blit_glow(surf, (cx, cy), int(cw * 1.4), col, 0.8 * pulse)
        rot = v.time * 0.6
        outer = draw.ngon_points(cx, cy, cw * 0.46, 6, rot)
        inner = draw.ngon_points(cx, cy, cw * 0.30, 6, -rot * 1.4)
        pygame.draw.polygon(surf, P.darken(col, 0.4), outer)
        pygame.draw.polygon(surf, col, outer, 3)
        pygame.draw.polygon(surf, P.lighten(col, 0.4), inner, 2)

    # ---- buildable / range previews ---- #
    def _draw_buildable_hint(self, surf: pygame.Surface, game: GameState) -> None:
        v = self.view
        if not v.placing or v.hover_cell is None:
            return
        cx, cy = v.hover_cell
        if not (0 <= cx < game.map.width and 0 <= cy < game.map.height):
            return
        ok = game.can_build(cx, cy, v.placing)
        color = (90, 255, 150) if ok else (255, 80, 80)
        x, y = v.w2s(cx, cy)
        rect = pygame.Rect(x, y, v.cell, v.cell)
        s = pygame.Surface((v.cell, v.cell), pygame.SRCALPHA)
        s.fill((*color, 55))
        surf.blit(s, (x, y))
        pygame.draw.rect(surf, color, rect, 2)

    def _draw_range_preview(self, surf: pygame.Surface, game: GameState) -> None:
        v = self.view
        # show range for placing tower at hover, or for selected tower
        center = None
        rng = 0.0
        if v.placing and v.hover_cell is not None:
            from ..core.entities import resolve_tower_stats
            st = resolve_tower_stats(v.placing, 1)
            rng = st["range"] * game.mods.range_mult
            cx, cy = v.hover_cell
            center = v.w2s(cx + 0.5, cy + 0.5)
        elif v.selected is not None:
            t = v.selected
            st = t.stats()
            rng = st["range"] * game.mods.range_mult * (1.0 + t.buff_rng)
            center = v.w2s(t.x, t.y)
            if C.TOWERS[t.ttype]["kind"] == "support":
                rng = st["buff_radius"]
        if center and rng > 0:
            r = int(rng * v.cell)
            ring = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(ring, (120, 200, 255, 28), (r + 2, r + 2), r)
            pygame.draw.circle(ring, (150, 220, 255, 120), (r + 2, r + 2), r, 2)
            surf.blit(ring, (center[0] - r - 2, center[1] - r - 2))

    # ---- towers ---- #
    def _draw_towers(self, surf: pygame.Surface, game: GameState) -> None:
        v = self.view
        cw = v.cell
        for t in game.towers:
            spec = C.TOWERS[t.ttype]
            col = P.hue(spec["color"])
            sx, sy = v.w2s(t.x, t.y)
            base_r = cw * 0.36
            sides = TOWER_SIDES.get(t.ttype, 4)
            # selection highlight
            if v.selected is t:
                pygame.draw.circle(surf, (255, 255, 255), (sx, sy), int(cw * 0.5), 2)
            glow_i = 0.7 + 0.3 * P.pulse(v.time + t.id, 0.0, 1.0, 0.5)
            if t.fire_flash > 0:
                glow_i += 1.0
            base_pts = draw.ngon_points(sx, sy, base_r, sides, v.time * 0.15 + t.id)
            draw.neon_poly(surf, base_pts, P.darken(col, 0.55), col, col,
                           int(cw * 0.7), 2, glow_i)
            # level pips: brighten inner shape per level
            inner_r = base_r * (0.45 + 0.12 * t.level)
            inner_pts = draw.ngon_points(sx, sy, inner_r, sides, -v.time * 0.25)
            pygame.draw.polygon(surf, P.lighten(col, 0.5), inner_pts, 2)
            # barrel aimed at target (non-support)
            if spec["kind"] != "support":
                ang = t.aim_angle
                blen = base_r * (1.15 + 0.15 * (t.level - 1))
                bw = max(2, int(cw * 0.12))
                bx = sx + math.cos(ang) * blen
                by = sy + math.sin(ang) * blen
                pygame.draw.line(surf, P.lighten(col, 0.3), (sx, sy), (bx, by), bw)
                pygame.draw.circle(surf, P.lighten(col, 0.6),
                                   (int(bx), int(by)), max(2, int(cw * 0.08)))
                if t.fire_flash > 0:
                    draw.blit_glow(surf, (bx, by), int(cw * 0.5), P.lighten(col, 0.5), 1.0)
            else:
                # beacon: rotating aura ring
                rr = int(cw * 0.5 * P.pulse(v.time, 0.7, 1.0, 0.7))
                pygame.draw.circle(surf, col, (sx, sy), rr, 2)

    # ---- enemies ---- #
    def _draw_enemies(self, surf: pygame.Surface, game: GameState) -> None:
        v = self.view
        cw = v.cell
        for e in game.alive_enemies:
            spec = C.ENEMIES[e.etype]
            col = P.hue(spec["color"])
            sx, sy = v.w2s(e.x, e.y)
            r = max(4, e.size * cw)
            phased = e.phased
            # status tint
            base = col
            if e.slow_factor < 1.0:
                base = P.mix(col, (120, 200, 255), 0.45)
            if e.poison_timer > 0:
                base = P.mix(base, (150, 255, 90), 0.35)
            glow_i = 0.85
            if e.hit_flash > 0:
                base = P.lighten(base, 0.6)
                glow_i = 1.4
            if phased:
                glow_i = 0.35
            sides = ENEMY_SIDES.get(e.etype, 4)
            # heading for oriented shapes
            head = self._enemy_heading(game, e)
            if sides == 0:  # phantom: circle
                draw.neon_circle(surf, (sx, sy), r, P.darken(base, 0.4), base,
                                 base, int(r * 2.4), 2, glow_i)
            else:
                rot = head + (0 if e.etype in ("runner", "mite") else v.time * 0.5)
                pts = draw.ngon_points(sx, sy, r, sides, rot)
                draw.neon_poly(surf, pts, P.darken(base, 0.45), base, base,
                               int(r * 2.3), 2, glow_i)
            if e.is_boss:
                ring = draw.ngon_points(sx, sy, r * 1.4, 8, -v.time * 0.8)
                pygame.draw.polygon(surf, P.lighten(col, 0.3), ring, 2)
            # shield ring
            if e.shield > 0:
                sr = int(r + cw * 0.12)
                pygame.draw.circle(surf, (120, 200, 255), (sx, sy), sr, 2)
            # heal aura
            if e.heal_aura > 0:
                ar = int(e.heal_radius * cw * P.pulse(v.time, 0.8, 1.0, 1.0))
                aura = pygame.Surface((ar * 2 + 2, ar * 2 + 2), pygame.SRCALPHA)
                pygame.draw.circle(aura, (90, 255, 150, 30), (ar + 1, ar + 1), ar)
                surf.blit(aura, (sx - ar, sy - ar))
            # hp bar
            self._draw_hp_bar(surf, e, sx, sy, r)

    def _enemy_heading(self, game: GameState, e: Enemy) -> float:
        a = game.map.pos_at(max(0.0, e.dist - 0.2))
        b = game.map.pos_at(e.dist + 0.2)
        return math.atan2(b[1] - a[1], b[0] - a[0]) + math.pi / 2

    def _draw_hp_bar(self, surf, e: Enemy, sx: int, sy: int, r: float) -> None:
        frac = max(0.0, e.hp / e.max_hp)
        if frac >= 0.999 and e.shield <= 0:
            return
        w = int(max(18, r * 2.2))
        h = 4
        x = sx - w // 2
        y = int(sy - r - 9)
        pygame.draw.rect(surf, (20, 24, 36), (x - 1, y - 1, w + 2, h + 2))
        pygame.draw.rect(surf, P.health_color(frac), (x, y, int(w * frac), h))
        if e.shield_max > 0 and e.shield > 0:
            sf = e.shield / e.shield_max
            pygame.draw.rect(surf, (120, 200, 255), (x, y - 4, int(w * sf), 2))

    # ---- projectiles ---- #
    def _draw_projectiles(self, surf: pygame.Surface, game: GameState) -> None:
        v = self.view
        cw = v.cell
        for p in game.projectiles:
            sx, sy = v.w2s(p.x, p.y)
            if p.kind == "splash":
                col = P.hue("orange")
                r = int(cw * 0.16)
            elif p.kind == "venom":
                col = P.hue("toxic")
                r = int(cw * 0.12)
            else:
                col = P.hue("cyan")
                r = int(cw * 0.1)
            if p.crit:
                col = P.lighten(col, 0.4)
            # trail toward last position
            lx, ly = v.w2s(p.last_x, p.last_y)
            draw.blit_glow(surf, (sx, sy), int(cw * 0.45), col, 1.0)
            pygame.draw.circle(surf, P.lighten(col, 0.5), (sx, sy), r)

    # ---- effects ---- #
    def _ingest_effects(self, game: GameState) -> None:
        """Spawn particles for newly-created effects (id by identity)."""
        for fx in game.effects:
            key = id(fx)
            if key in self._seen_effects:
                continue
            self._seen_effects.add(key)
            v = self.view
            if fx.kind == "death":
                sx, sy = v.w2s(fx.x, fx.y)
                self.particles.burst(sx, sy, P.hue(fx.color), n=16, speed=200,
                                     life=0.5, radius=3.0)
            elif fx.kind == "explosion":
                sx, sy = v.w2s(fx.x, fx.y)
                self.particles.burst(sx, sy, P.hue("orange"), n=24, speed=260,
                                     life=0.5, radius=4.0)
            elif fx.kind == "leak":
                sx, sy = v.w2s(fx.x, fx.y)
                self.particles.burst(sx, sy, (255, 80, 80), n=20, speed=160,
                                     life=0.6, radius=3.0)
            elif fx.kind == "frost":
                sx, sy = v.w2s(fx.x, fx.y)
                self.particles.burst(sx, sy, P.hue("ice"), n=12, speed=120,
                                     life=0.4, radius=2.5)
        # prune seen set
        if len(self._seen_effects) > 400:
            live = {id(fx) for fx in game.effects}
            self._seen_effects &= live

    def _draw_effects(self, surf: pygame.Surface, game: GameState) -> None:
        v = self.view
        cw = v.cell
        for fx in game.effects:
            t = fx.ttl / fx.max_ttl
            if fx.kind in ("explosion", "frost"):
                sx, sy = v.w2s(fx.x, fx.y)
                r = int(fx.radius * cw * (1.2 - t))
                col = P.hue("orange") if fx.kind == "explosion" else P.hue("ice")
                ring = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
                pygame.draw.circle(ring, (*col, int(160 * t)), (r + 2, r + 2), r, 3)
                surf.blit(ring, (sx - r - 2, sy - r - 2))
                draw.blit_glow(surf, (sx, sy), max(3, int(r * 0.8)), col, t)
            elif fx.kind == "beam":
                a = v.w2s(*fx.points[0])
                b = v.w2s(*fx.points[1])
                col = P.hue("red")
                draw.neon_line(surf, a, b, P.lighten(col, 0.6),
                               max(2, int(cw * 0.16 * t + 2)),
                               glow_color=col, glow_radius=int(cw * 0.4))
            elif fx.kind == "chain":
                col = P.hue("violet")
                rng = random.Random(int(fx.x * 1000) + len(fx.points))
                for a, b in zip(fx.points, fx.points[1:]):
                    sa = v.w2s(*a)
                    sb = v.w2s(*b)
                    jag = draw.jagged_line(sa, sb, 5, cw * 0.18, rng)
                    pygame.draw.lines(surf, P.lighten(col, 0.5), False, jag,
                                      max(2, int(cw * 0.08)))
                    for pt in (sa, sb):
                        draw.blit_glow(surf, pt, int(cw * 0.3), col, t)
