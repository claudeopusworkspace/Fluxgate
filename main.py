#!/usr/bin/env python3
"""Fluxgate — launch the GUI.

    python main.py                 # menu
    python main.py --seed 42 --difficulty hard
    python main.py --smoke 300     # headless render smoke (no window)
"""
from fluxgate.render.app import main

if __name__ == "__main__":
    main()
