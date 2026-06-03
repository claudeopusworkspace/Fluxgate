"""Headless rendering smoke tests.

Use SDL's dummy video driver so the entire procedural render pipeline (world,
towers, enemies, projectiles, effects, particles, HUD, panel, augment overlay,
endcard, menu) executes without a display. Verifies the GUI code paths don't
crash and actually produce non-blank frames — i.e. the game can run as a GUI.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
import pytest  # noqa: E402

from fluxgate.core import config as C  # noqa: E402
from fluxgate.core.game import PHASE_BUILD, PHASE_COMBAT  # noqa: E402
from fluxgate.ai.heuristic import HeuristicAI  # noqa: E402


def _nonblank(surface) -> bool:
    arr = pygame.surfarray.array3d(surface)
    return bool(arr.sum() > 0)


def test_menu_renders():
    from fluxgate.render.app import App
    app = App(seed=1, difficulty="normal", headless=True)
    app.draw()
    assert _nonblank(app.screen)
    pygame.quit()


def test_combat_renders_many_frames():
    """Play with the AI while rendering every frame; exercise all draw paths."""
    from fluxgate.render.app import App
    app = App(seed=7, difficulty="normal", headless=True)
    app.start_game()
    ai = HeuristicAI(app.game)
    g = app.game
    frames = 0
    saw_combat = False
    saw_augment = False
    # run ~8 waves worth of frames
    while frames < 6000 and g.wave_index < 8 and not g.defeat:
        if g.phase == PHASE_BUILD:
            if g.offered_augments:
                # render the augment overlay before anything consumes it
                app.draw()
                assert _nonblank(app.screen)
                saw_augment = True
            ai.take_build_actions()   # picks the augment + builds/upgrades
            g.start_wave()
        # step + render a combat frame
        for _ in range(3):
            if g.phase == PHASE_COMBAT:
                g.tick(C.DT)
                saw_combat = True
        # also exercise selection/placing render states
        if g.towers:
            app.view.selected = g.towers[0]
        app.draw()
        assert _nonblank(app.screen)
        frames += 1
    assert saw_combat
    assert saw_augment
    pygame.quit()


def test_endcard_renders():
    from fluxgate.render.app import App
    from fluxgate.core.game import PHASE_DEFEAT, PHASE_VICTORY
    app = App(seed=3, difficulty="normal", headless=True)
    app.start_game()
    app.game.phase = PHASE_DEFEAT
    app.draw()
    assert _nonblank(app.screen)
    app.game.phase = PHASE_VICTORY
    app.draw()
    assert _nonblank(app.screen)
    pygame.quit()
