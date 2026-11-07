"""ReelAI - script de menu pour DaVinci Resolve (Workspace > Scripts > ReelAI).

Copié dans le dossier Scripts de Resolve par install.py, qui remplit REELAI_PATH.
"""

import os
import sys

REELAI_PATH = r"__REELAI_PATH__"

if REELAI_PATH.startswith("__"):  # lancé directement depuis le dépôt
    REELAI_PATH = os.path.dirname(os.path.abspath(__file__))
if REELAI_PATH not in sys.path:
    sys.path.insert(0, REELAI_PATH)

from reelai.launcher import launch  # noqa: E402

# Resolve injecte `resolve`, `fusion`, `bmd` et/ou `app` dans les scripts du menu.
launch({name: globals().get(name) for name in ("resolve", "fusion", "bmd", "app")})
