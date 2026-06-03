"""Fluxgate GUI application: main loop, input, and HUD/menus.

Drives the same deterministic ``GameState`` the headless harness uses, stepping
it at a fixed timestep with an accumulator so 1x/2x/3x speed never changes the
simulation outcome. All UI is drawn procedurally (generated shapes + fonts).
"""

from __future__ import annotations

import math
import os
import random
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pygame

from ..core import config as C
from ..core.entities import Tower, resolve_tower_stats
from ..core.game import (GameState, PHASE_BUILD, PHASE_COMBAT, PHASE_DEFEAT,
                         PHASE_VICTORY)
from . import draw, palette as P
from .renderer import Renderer, View

CELL = 42
TOPBAR_H = 56
PANEL_W = 312
MARGIN = 16
MAX_STEPS_PER_FRAME = 8

HOTKEYS = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2, pygame.K_4: 3,
           pygame.K_5: 4, pygame.K_6: 5, pygame.K_7: 6, pygame.K_8: 7}


@dataclass
class Btn:
    key: str
    rect: pygame.Rect
    label: str
    enabled: bool = True
    meta: Optional[dict] = None
    color: Tuple[int, int, int] = (120, 160, 220)


class App:
    def __init__(self, seed: Optional[int] = None, difficulty: str = "normal",
                 headless: bool = False):
        self.headless = headless
        if headless:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        pygame.init()
        pygame.font.init()
        self.fw = C.GRID_W * CELL
        self.fh = C.GRID_H * CELL
        self.W = MARGIN + self.fw + PANEL_W + MARGIN
        self.H = TOPBAR_H + MARGIN + self.fh + MARGIN
        flags = 0
        self.screen = pygame.display.set_mode((self.W, self.H), flags)
        pygame.display.set_caption("Fluxgate")
        self.clock = pygame.time.Clock()
        self.font_s = pygame.font.SysFont("consolas,dejavusansmono,monospace", 14)
        self.font_m = pygame.font.SysFont("consolas,dejavusansmono,monospace", 18)
        self.font_l = pygame.font.SysFont("consolas,dejavusansmono,monospace", 30, bold=True)
        self.font_xl = pygame.font.SysFont("consolas,dejavusansmono,monospace", 56, bold=True)

        self.state = "menu"           # menu | playing
        self.menu_diff = difficulty
        self.menu_seed = seed if seed is not None else random.randint(0, 999999)
        self.speed = 1
        self.paused = False
        self.accum = 0.0
        self.game: Optional[GameState] = None
        self.renderer: Optional[Renderer] = None
        self.view: Optional[View] = None
        self._buttons: List[Btn] = []
        self._show_help = False

    # ---------------------------------------------------------------- #
    def start_game(self) -> None:
        self.game = GameState(seed=self.menu_seed, difficulty=self.menu_diff)
        self.view = View(cell=CELL, ox=MARGIN, oy=TOPBAR_H + MARGIN)
        self.renderer = Renderer(self.view, self.fw, self.fh)
        self.state = "playing"
        self.speed = 1
        self.paused = False
        self.accum = 0.0

    # ---------------------------------------------------------------- #
    def run(self, max_frames: Optional[int] = None) -> None:
        frames = 0
        running = True
        while running:
            dt = self.clock.tick(60) / 1000.0
            dt = min(dt, 0.05)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                else:
                    self.handle_event(event)
            self.update(dt)
            self.draw()
            pygame.display.flip()
            frames += 1
            if max_frames is not None and frames >= max_frames:
                running = False
        pygame.quit()

    # ---------------------------------------------------------------- #
    def update(self, dt: float) -> None:
        if self.state != "playing" or self.game is None:
            return
        g = self.game
        if g.phase == PHASE_COMBAT and not self.paused:
            self.accum += dt * self.speed
            steps = 0
            while self.accum >= C.DT and steps < MAX_STEPS_PER_FRAME * self.speed:
                g.tick(C.DT)
                self.accum -= C.DT
                steps += 1
                if g.phase != PHASE_COMBAT:
                    break
        else:
            g.tick(C.DT)  # ages effects only (no-op for sim when not combat)
        # keep selection valid
        if self.view.selected and self.view.selected not in g.towers:
            self.view.selected = None

    # ---------------------------------------------------------------- #
    def handle_event(self, event: pygame.event.Event) -> None:
        if self.state == "menu":
            self._handle_menu_event(event)
            return
        g = self.game
        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            if self._in_field(mx, my):
                self.view.hover_cell = self.view.s2cell(mx, my)
            else:
                self.view.hover_cell = None
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                self._click(event.pos)
            elif event.button == 3:
                self.view.placing = None
                self.view.selected = None
        elif event.type == pygame.KEYDOWN:
            self._handle_key(event)

    def _handle_key(self, event) -> None:
        g = self.game
        k = event.key
        if g.offered_augments:
            if k in (pygame.K_1, pygame.K_2, pygame.K_3):
                idx = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2}[k]
                if idx < len(g.offered_augments):
                    g.choose_augment(g.offered_augments[idx]["id"])
            return
        if k == pygame.K_ESCAPE:
            if self.view.placing or self.view.selected:
                self.view.placing = None
                self.view.selected = None
            else:
                self.state = "menu"
        elif k in HOTKEYS:
            idx = HOTKEYS[k]
            if idx < len(C.TOWER_ORDER):
                self.view.placing = C.TOWER_ORDER[idx]
                self.view.selected = None
        elif k == pygame.K_SPACE:
            if g.phase == PHASE_BUILD:
                g.start_wave()
        elif k == pygame.K_p:
            self.paused = not self.paused
        elif k == pygame.K_TAB:
            self.speed = {1: 2, 2: 3, 3: 1}[self.speed]
        elif k == pygame.K_u and self.view.selected:
            g.upgrade_tower(self.view.selected)
        elif k == pygame.K_s and self.view.selected:
            g.sell_tower(self.view.selected)
            self.view.selected = None
        elif k == pygame.K_t and self.view.selected:
            modes = C.TARGET_MODES
            cur = modes.index(self.view.selected.target_mode)
            g.set_target_mode(self.view.selected, modes[(cur + 1) % len(modes)])
        elif k == pygame.K_h:
            self._show_help = not self._show_help

    def _click(self, pos: Tuple[int, int]) -> None:
        g = self.game
        mx, my = pos
        # overlays first
        if g.phase in (PHASE_VICTORY, PHASE_DEFEAT):
            for b in self._buttons:
                if b.rect.collidepoint(pos) and b.enabled:
                    self._do_button(b)
                    return
            return
        if g.offered_augments:
            for b in self._buttons:
                if b.key.startswith("aug:") and b.rect.collidepoint(pos):
                    g.choose_augment(b.key.split(":", 1)[1])
                    return
            return
        # panel buttons
        for b in self._buttons:
            if b.rect.collidepoint(pos) and b.enabled:
                self._do_button(b)
                return
        # field interaction
        if self._in_field(mx, my):
            cx, cy = self.view.s2cell(mx, my)
            if self.view.placing:
                g.build_tower(cx, cy, self.view.placing)  # stays in placing mode
            else:
                t = g.tower_at(cx, cy)
                self.view.selected = t

    def _do_button(self, b: Btn) -> None:
        g = self.game
        key = b.key
        if key.startswith("build:"):
            self.view.placing = key.split(":", 1)[1]
            self.view.selected = None
        elif key == "start":
            g.start_wave()
        elif key == "upgrade" and self.view.selected:
            g.upgrade_tower(self.view.selected)
        elif key == "sell" and self.view.selected:
            g.sell_tower(self.view.selected)
            self.view.selected = None
        elif key == "target" and self.view.selected:
            modes = C.TARGET_MODES
            cur = modes.index(self.view.selected.target_mode)
            g.set_target_mode(self.view.selected, modes[(cur + 1) % len(modes)])
        elif key == "speed":
            self.speed = {1: 2, 2: 3, 3: 1}[self.speed]
        elif key == "pause":
            self.paused = not self.paused
        elif key == "newrun":
            self.state = "menu"
        elif key == "endless":
            g.endless = True
            g.phase = PHASE_BUILD
            g._offer_augments()

    def _in_field(self, mx: int, my: int) -> bool:
        return (MARGIN <= mx < MARGIN + self.fw and
                TOPBAR_H + MARGIN <= my < TOPBAR_H + MARGIN + self.fh)

    # ---------------------------------------------------------------- #
    # Menu
    # ---------------------------------------------------------------- #
    def _handle_menu_event(self, event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for b in self._buttons:
                if b.rect.collidepoint(event.pos):
                    if b.key.startswith("diff:"):
                        self.menu_diff = b.key.split(":", 1)[1]
                    elif b.key == "play":
                        self.start_game()
                    elif b.key == "reseed":
                        self.menu_seed = random.randint(0, 999999)
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                self.start_game()
            elif event.key == pygame.K_r:
                self.menu_seed = random.randint(0, 999999)

    # ---------------------------------------------------------------- #
    # Drawing
    # ---------------------------------------------------------------- #
    def draw(self) -> None:
        self.screen.fill((8, 9, 18))
        if self.state == "menu":
            self.draw_menu()
            return
        dt = 1.0 / 60.0 if self.paused else self.clock.get_time() / 1000.0
        self.renderer.draw_world(self.screen, self.game, min(dt, 0.05))
        self._buttons = []
        self.draw_topbar()
        self.draw_panel()
        if self.game.offered_augments:
            self.draw_augments()
        if self.game.phase in (PHASE_VICTORY, PHASE_DEFEAT):
            self.draw_endcard()
        if self._show_help:
            self.draw_help()

    def _text(self, s: str, font, color, pos, center=False, right=False):
        img = font.render(s, True, color)
        r = img.get_rect()
        if center:
            r.center = pos
        elif right:
            r.midright = pos
        else:
            r.topleft = pos
        self.screen.blit(img, r)
        return r

    def _panel_button(self, key, rect, label, enabled=True, color=(120, 160, 220),
                      meta=None):
        b = Btn(key, rect, label, enabled, meta, color)
        self._buttons.append(b)
        return b

    def _draw_btn(self, b: Btn, hover_pos=None):
        bg = P.darken(b.color, 0.65) if b.enabled else (40, 42, 52)
        fg = P.lighten(b.color, 0.4) if b.enabled else (90, 92, 104)
        pygame.draw.rect(self.screen, bg, b.rect, border_radius=6)
        pygame.draw.rect(self.screen, fg, b.rect, 2, border_radius=6)
        self._text(b.label, self.font_m, fg, b.rect.center, center=True)

    def draw_topbar(self) -> None:
        g = self.game
        pygame.draw.rect(self.screen, (16, 18, 32), (0, 0, self.W, TOPBAR_H))
        pygame.draw.line(self.screen, (60, 70, 110), (0, TOPBAR_H), (self.W, TOPBAR_H), 2)
        # money
        self._text(f"$ {g.money}", self.font_l, P.hue("gold"), (MARGIN, 12))
        # core hp bar
        bx, by, bw, bh = 220, 18, 240, 22
        frac = g.core_hp / max(1.0, g.core_max_hp)
        pygame.draw.rect(self.screen, (30, 16, 20), (bx, by, bw, bh), border_radius=4)
        pygame.draw.rect(self.screen, P.health_color(frac),
                         (bx, by, int(bw * frac), bh), border_radius=4)
        pygame.draw.rect(self.screen, (120, 130, 160), (bx, by, bw, bh), 2, border_radius=4)
        self._text(f"CORE {int(g.core_hp)}/{int(g.core_max_hp)}", self.font_s,
                   (255, 255, 255), (bx + bw // 2, by + bh // 2), center=True)
        # wave + kills
        self._text(f"WAVE {g.wave_index}/{C.TOTAL_WAVES}", self.font_m,
                   (200, 220, 255), (bx + bw + 30, 12))
        self._text(f"KILLS {g.stats.kills}", self.font_s, (160, 180, 220),
                   (bx + bw + 30, 34))
        # speed + pause buttons (right side)
        sx = self.W - 220
        self._panel_button("speed", pygame.Rect(sx, 12, 70, 32),
                           f"{self.speed}x", True, (90, 200, 160))
        self._panel_button("pause", pygame.Rect(sx + 80, 12, 110, 32),
                           "PAUSED" if self.paused else "PAUSE", True,
                           (220, 160, 90) if self.paused else (120, 160, 220))
        for b in self._buttons:
            self._draw_btn(b)

    def draw_panel(self) -> None:
        g = self.game
        px = MARGIN + self.fw + MARGIN
        py = TOPBAR_H + MARGIN
        pw = PANEL_W - MARGIN
        pygame.draw.rect(self.screen, (14, 16, 28), (px, py, pw, self.fh), border_radius=8)
        pygame.draw.rect(self.screen, (50, 60, 95), (px, py, pw, self.fh), 2, border_radius=8)
        self._text("FLUXGATE", self.font_l, P.hue("cyan"), (px + 12, py + 8))
        y = py + 50
        self._text("BUILD  (1-8)", self.font_s, (150, 170, 210), (px + 12, y))
        y += 20
        # tower buttons grid 2 columns
        bw = (pw - 28) // 2
        bh = 46
        for i, ttype in enumerate(C.TOWER_ORDER):
            col = i % 2
            row = i // 2
            rx = px + 10 + col * (bw + 8)
            ry = y + row * (bh + 6)
            spec = C.TOWERS[ttype]
            cost = g.build_cost(ttype)
            enabled = g.money >= cost
            color = P.hue(spec["color"])
            rect = pygame.Rect(rx, ry, bw, bh)
            selected = self.view.placing == ttype
            bg = P.darken(color, 0.6 if not selected else 0.3)
            pygame.draw.rect(self.screen, bg, rect, border_radius=6)
            pygame.draw.rect(self.screen, color if enabled else (70, 72, 84),
                             rect, 2 if not selected else 3, border_radius=6)
            self._text(f"{i+1} {spec['name']}", self.font_s,
                       P.lighten(color, 0.4) if enabled else (90, 92, 104),
                       (rx + 8, ry + 6))
            self._text(f"${cost}", self.font_s,
                       P.hue("gold") if enabled else (90, 92, 104), (rx + 8, ry + 24))
            self._buttons.append(Btn(f"build:{ttype}", rect, spec["name"], enabled, color=color))
        y = y + 4 * (bh + 6) + 10

        # selected tower info OR placing hint
        info_top = y
        if self.view.selected:
            self._draw_tower_info(px, info_top, pw)
        elif self.view.placing:
            spec = C.TOWERS[self.view.placing]
            self._text(f"Placing: {spec['name']}", self.font_m, P.hue(spec["color"]),
                       (px + 12, info_top))
            self._wrap_text(spec["desc"], self.font_s, (180, 195, 225),
                            px + 12, info_top + 26, pw - 24)
            self._text("Click a tile. Right-click/ESC cancels.", self.font_s,
                       (130, 150, 185), (px + 12, info_top + 78))
        else:
            self._text("Select a tower or pick one to build.", self.font_s,
                       (130, 150, 185), (px + 12, info_top))
            self._text("[H] toggle help", self.font_s, (110, 130, 165),
                       (px + 12, info_top + 22))

        # START WAVE button (build phase)
        if g.phase == PHASE_BUILD and not g.offered_augments:
            r = pygame.Rect(px + 10, py + self.fh - 56, pw - 20, 44)
            self._panel_button("start", r, "START WAVE  [Space]", True, (90, 220, 140))
            self._draw_btn(self._buttons[-1])
        elif g.phase == PHASE_COMBAT:
            self._text(f"Enemies: {len(g.alive_enemies)}", self.font_m,
                       (255, 180, 120), (px + 12, py + self.fh - 40))

    def _draw_tower_info(self, px, y, pw) -> None:
        g = self.game
        t = self.view.selected
        spec = C.TOWERS[t.ttype]
        color = P.hue(spec["color"])
        st = t.stats()
        self._text(f"{spec['name']}  Lv{t.level}", self.font_m, color, (px + 12, y))
        y += 26
        lines = []
        if spec["kind"] != "support":
            dps = st["damage"] * st["fire_rate"] * g.mods.dmg_mult * (1 + t.buff_dmg)
            lines.append(f"DMG {st['damage']*g.mods.dmg_mult*(1+t.buff_dmg):.0f}"
                         f"  RATE {st['fire_rate']*g.mods.rate_mult:.1f}/s")
            lines.append(f"DPS {dps:.0f}   RANGE {st['range']*g.mods.range_mult*(1+t.buff_rng):.1f}")
            lines.append(f"Kills {t.kills}   Dealt {t.damage_dealt:.0f}")
            lines.append(f"Target: {t.target_mode}  [T]")
        else:
            lines.append(f"+{st['buff_damage']*100:.0f}% dmg / +{st['buff_range']*100:.0f}% rng")
            lines.append(f"Aura radius {st['buff_radius']:.1f}")
        for ln in lines:
            self._text(ln, self.font_s, (190, 205, 235), (px + 12, y))
            y += 18
        y += 6
        # upgrade / sell buttons
        up = g.upgrade_price(t)
        if up is not None:
            enabled = g.money >= up
            r = pygame.Rect(px + 10, y, (pw - 28) // 2, 34)
            self._panel_button("upgrade", r, f"Upgrade ${up}", enabled, (120, 200, 255))
        r2 = pygame.Rect(px + 10 + (pw - 28) // 2 + 8, y, (pw - 28) // 2, 34)
        refund = int(t.invested * C.SELL_REFUND)
        self._panel_button("sell", r2, f"Sell ${refund}", True, (220, 130, 110))
        if t.ttype != "beacon":
            r3 = pygame.Rect(px + 10, y + 40, pw - 20, 30)
            self._panel_button("target", r3, f"Target: {t.target_mode}", True, (160, 150, 220))
        for b in self._buttons:
            if b.key in ("upgrade", "sell", "target"):
                self._draw_btn(b)

    def _wrap_text(self, text, font, color, x, y, maxw):
        words = text.split()
        line = ""
        ly = y
        for w in words:
            test = (line + " " + w).strip()
            if font.size(test)[0] > maxw and line:
                self._text(line, font, color, (x, ly))
                ly += font.get_height() + 2
                line = w
            else:
                line = test
        if line:
            self._text(line, font, color, (x, ly))
        return ly

    def draw_augments(self) -> None:
        g = self.game
        overlay = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        overlay.fill((6, 8, 18, 200))
        self.screen.blit(overlay, (0, 0))
        self._text("CHOOSE AN AUGMENT", self.font_l, P.hue("gold"),
                   (self.W // 2, 80), center=True)
        self._text("(1 / 2 / 3 or click)", self.font_s, (180, 190, 220),
                   (self.W // 2, 116), center=True)
        n = len(g.offered_augments)
        cw, ch = 300, 200
        gap = 30
        total = n * cw + (n - 1) * gap
        x0 = (self.W - total) // 2
        y0 = 170
        rarity_col = {"common": (140, 170, 210), "uncommon": (130, 220, 170),
                      "rare": (235, 180, 90)}
        for i, a in enumerate(g.offered_augments):
            rx = x0 + i * (cw + gap)
            rect = pygame.Rect(rx, y0, cw, ch)
            col = rarity_col.get(a["rarity"], (140, 170, 210))
            pygame.draw.rect(self.screen, P.darken(col, 0.78), rect, border_radius=12)
            pygame.draw.rect(self.screen, col, rect, 3, border_radius=12)
            draw.blit_glow(self.screen, rect.center, 120, col, 0.25)
            self._text(f"[{i+1}]", self.font_m, col, (rx + 14, y0 + 10))
            self._text(a["rarity"].upper(), self.font_s, col,
                       (rx + cw - 14, y0 + 16), right=True)
            self._text(a["name"], self.font_l, P.lighten(col, 0.3),
                       (rx + cw // 2, y0 + 70), center=True)
            self._wrap_text(a["desc"], self.font_m, (210, 220, 240),
                            rx + 18, y0 + 110, cw - 36)
            self._buttons.append(Btn(f"aug:{a['id']}", rect, a["name"]))

    def draw_endcard(self) -> None:
        g = self.game
        overlay = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        overlay.fill((6, 8, 18, 215))
        self.screen.blit(overlay, (0, 0))
        won = g.phase == PHASE_VICTORY
        title = "VICTORY" if won else "CORE BREACHED"
        col = P.hue("gold") if won else P.hue("red")
        self._text(title, self.font_xl, col, (self.W // 2, 150), center=True)
        draw.blit_glow(self.screen, (self.W // 2, 150), 200, col, 0.3)
        stats = [
            f"Waves cleared : {g.stats.waves_cleared}/{C.TOTAL_WAVES}",
            f"Total kills   : {g.stats.kills}",
            f"Leaks         : {g.stats.leaks}",
            f"Towers built  : {len(g.towers)}",
            f"Seed {g.seed}  |  {g.difficulty}",
        ]
        y = 240
        for s in stats:
            self._text(s, self.font_m, (200, 215, 245), (self.W // 2, y), center=True)
            y += 30
        y += 14
        r = pygame.Rect(self.W // 2 - 220, y, 200, 50)
        self._panel_button("newrun", r, "NEW RUN", True, (120, 180, 255))
        self._draw_btn(self._buttons[-1])
        if won:
            r2 = pygame.Rect(self.W // 2 + 20, y, 200, 50)
            self._panel_button("endless", r2, "ENDLESS", True, (220, 170, 90))
            self._draw_btn(self._buttons[-1])

    def draw_help(self) -> None:
        overlay = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        overlay.fill((6, 8, 18, 220))
        self.screen.blit(overlay, (0, 0))
        lines = [
            "FLUXGATE — defend the core from waves along the path.",
            "",
            "1-8 / click  : select a tower to build, then click a tile",
            "Click tower  : inspect; U upgrade, S sell, T cycle targeting",
            "Space        : start the next wave",
            "Tab          : cycle game speed (1x/2x/3x)",
            "P            : pause     ESC: cancel / back to menu",
            "1/2/3        : pick the offered augment between waves",
            "",
            "Place towers where their range covers the most path.",
            "Beacons amplify nearby towers. Mix DPS, slows, splash & armor",
            "shred — enemy HP scales hard, so synergy beats brute force.",
            "",
            "[H] close help",
        ]
        y = 120
        for ln in lines:
            self._text(ln, self.font_m, (200, 215, 245), (self.W // 2, y), center=True)
            y += 28

    def draw_menu(self) -> None:
        # animated generated backdrop
        t = pygame.time.get_ticks() / 1000.0
        bg = draw.vertical_gradient(self.W, self.H, P.BG_TOP, P.BG_BOTTOM)
        self.screen.blit(bg, (0, 0))
        for i in range(40):
            a = t * 0.2 + i
            x = (self.W / 2) + math.cos(a) * (120 + i * 9)
            yy = (self.H / 2 - 40) + math.sin(a * 1.3) * (70 + i * 5)
            col = P.shift_hue(P.hue("cyan"), (i / 40))
            draw.blit_glow(self.screen, (x, yy), 26, col, 0.5)
        self._text("FLUXGATE", self.font_xl, P.hue("cyan"),
                   (self.W // 2, 110), center=True)
        draw.blit_glow(self.screen, (self.W // 2, 110), 220, P.hue("cyan"), 0.25)
        self._text("a procedural neon tower-defense roguelite",
                   self.font_m, (170, 195, 235), (self.W // 2, 158), center=True)

        self._buttons = []
        self._text("DIFFICULTY", self.font_m, (190, 205, 235),
                   (self.W // 2, 220), center=True)
        diffs = list(C.DIFFICULTY)
        bw = 150
        total = len(diffs) * bw + (len(diffs) - 1) * 14
        x0 = (self.W - total) // 2
        for i, d in enumerate(diffs):
            rx = x0 + i * (bw + 14)
            rect = pygame.Rect(rx, 250, bw, 46)
            sel = self.menu_diff == d
            col = (120, 200, 255) if sel else (90, 110, 150)
            pygame.draw.rect(self.screen, P.darken(col, 0.6 if sel else 0.75),
                             rect, border_radius=8)
            pygame.draw.rect(self.screen, col, rect, 3 if sel else 2, border_radius=8)
            self._text(d.upper(), self.font_m, P.lighten(col, 0.3), rect.center, center=True)
            self._buttons.append(Btn(f"diff:{d}", rect, d))

        self._text(f"SEED  {self.menu_seed}", self.font_m, (200, 215, 245),
                   (self.W // 2, 330), center=True)
        rseed = pygame.Rect(self.W // 2 - 90, 356, 180, 36)
        self._panel_button("reseed", rseed, "RESEED  [R]", True, (160, 150, 220))
        self._draw_btn(self._buttons[-1])

        play = pygame.Rect(self.W // 2 - 130, 420, 260, 60)
        self._panel_button("play", play, "PLAY  [Enter]", True, (90, 220, 140))
        self._draw_btn(self._buttons[-1])

        info = [
            "Defend the core along a procedurally generated path.",
            "8 towers, 10 enemy archetypes, 16 augments, 30 waves + endless.",
            "Each seed is a fresh map. Press H in-game for controls.",
        ]
        y = 510
        for ln in info:
            self._text(ln, self.font_s, (150, 170, 205), (self.W // 2, y), center=True)
            y += 22


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--difficulty", default="normal")
    ap.add_argument("--smoke", type=int, default=0,
                    help="run N headless frames (dummy video) then exit")
    args = ap.parse_args()
    if args.smoke:
        app = App(seed=args.seed or 1, difficulty=args.difficulty, headless=True)
        app.start_game()
        # auto-advance a few waves to exercise combat rendering paths
        app.run(max_frames=args.smoke)
    else:
        app = App(seed=args.seed, difficulty=args.difficulty)
        app.run()


if __name__ == "__main__":
    main()
