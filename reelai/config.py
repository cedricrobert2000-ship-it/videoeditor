"""Réglages de ReelAI, sauvegardés dans ~/.reelai/config.json."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("REELAI_HOME", Path.home() / ".reelai"))
CONFIG_FILE = CONFIG_DIR / "config.json"
CACHE_DIR = CONFIG_DIR / "cache"


@dataclass
class Settings:
    # IA
    api_key: str = ""
    model: str = "claude-opus-5-5"
    instructions: str = ""  # consignes libres : ton, sujet à privilégier, public...

    # Source : "media_pool" (montage de tous les plans) ou "selected" (vidéo parlée sélectionnée)
    source_mode: str = "media_pool"
    music_name: str = ""  # clip audio du Media Pool ; "" = la 1re musique trouvée, "-" = aucune
    montage_pace: str = "Moyen"  # Lent, Moyen, Rapide
    montage_look: str = "Auto"  # Auto (choisi par l'IA), Naturel, Chaud doré, Film doux...
    montage_texts: bool = True  # textes sur certains plans (accroche, message, appel à l'action)
    text_animation: str = "reelai"  # "reelai" (typo animée, rapide) ou "higgsfield" (IA, après le montage)

    # Python où ReelAI est installé (écrit par install.py)
    python_path: str = ""

    # Reels
    reel_count: int = 3
    target_duration: float = 45.0  # secondes
    min_duration: float = 20.0
    max_duration: float = 60.0

    # Transcription
    language: str = "fr"  # "" = détection automatique
    whisper_model: str = "small"  # tiny, base, small, medium, large-v3

    # Montage
    remove_silences: bool = True
    max_silence: float = 0.45  # un blanc plus long que ça est coupé
    padding: float = 0.08  # marge gardée avant/après chaque mot
    remove_fillers: bool = True
    filler_words: list = field(
        default_factory=lambda: ["euh", "heu", "hum", "bah", "um", "uh", "erm"]
    )
    vertical: bool = True
    width: int = 1080
    height: int = 1920

    # Sous-titres
    subtitles: bool = True
    subtitle_max_words: int = 3
    subtitle_max_chars: int = 22
    subtitle_uppercase: bool = True

    # Motion design (Higgsfield)
    higgsfield_key: str = ""  # format "key-id:key-secret" (cloud.higgsfield.ai)
    motion_style: str = "Auto"
    motion_duration: int = 5
    motion_text_overlay: bool = True  # texte net ajouté par Resolve (recommandé)

    # Export
    render: bool = False
    output_dir: str = ""  # vide = dossier "ReelAI" à côté de la vidéo source

    def resolved_api_key(self) -> str:
        return self.api_key or os.environ.get("ANTHROPIC_API_KEY", "")


def load_settings(path: Path = CONFIG_FILE) -> Settings:
    settings = Settings()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return settings
        known = {f.name for f in fields(Settings)}
        for key, value in data.items():
            if key in known:
                setattr(settings, key, value)
    return settings


def save_settings(settings: Settings, path: Path = CONFIG_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(path, 0o600)  # contient la clé API
    except OSError:
        pass
