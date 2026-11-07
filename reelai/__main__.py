"""Lancement depuis un terminal (DaVinci Resolve Studio, scripting externe activé).

    python -m reelai            # ouvre la fenêtre
    python -m reelai --headless # utilise ~/.reelai/config.json sans fenêtre
"""

import sys

from .launcher import launch

if __name__ == "__main__":
    launch(headless="--headless" in sys.argv)
