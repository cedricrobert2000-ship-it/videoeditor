"""Installe ReelAI dans DaVinci Resolve.

Lance-le avec le MÊME Python que celui utilisé par Resolve :
    python install.py            # installe les dépendances + le script de menu
    python install.py --no-deps  # seulement le script de menu
"""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def scripts_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ["APPDATA"]) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Blackmagic Design" / "DaVinci Resolve" / "Fusion"
    else:
        base = Path.home() / ".local" / "share" / "DaVinciResolve" / "Fusion"
    return base / "Scripts" / "Utility"


def main() -> None:
    if "--no-deps" not in sys.argv:
        print("Installation des dépendances Python...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(HERE / "requirements.txt")])

    target_dir = scripts_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    source = (HERE / "ReelAI.py").read_text(encoding="utf-8")
    target = target_dir / "ReelAI.py"
    target.write_text(source.replace("__REELAI_PATH__", str(HERE)), encoding="utf-8")

    # Mémorise ce Python : ReelAI l'utilisera si celui de Resolve n'a pas les paquets.
    sys.path.insert(0, str(HERE))
    from reelai.config import load_settings, save_settings
    settings = load_settings()
    settings.python_path = sys.executable
    save_settings(settings)

    print(f"\n✔ Script installé : {target}")
    print("Redémarre DaVinci Resolve puis ouvre : Workspace > Scripts > ReelAI")
    print(f"(Python utilisé : {sys.executable} {sys.version.split()[0]})")


if __name__ == "__main__":
    main()
