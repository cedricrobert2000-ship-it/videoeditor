"""Transcription mot à mot avec faster-whisper (local, gratuit), avec cache disque."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Optional

from .config import CACHE_DIR
from .models import Segment, Transcript, Word


def _cache_path(media_path: str, model_size: str, language: str) -> Path:
    stat = os.stat(media_path)
    key = f"{os.path.abspath(media_path)}|{stat.st_size}|{stat.st_mtime}|{model_size}|{language}"
    return CACHE_DIR / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")


def transcript_to_dict(t: Transcript) -> dict:
    return {
        "language": t.language,
        "duration": t.duration,
        "segments": [
            {
                "start": s.start,
                "end": s.end,
                "text": s.text,
                "words": [[w.start, w.end, w.text] for w in s.words],
            }
            for s in t.segments
        ],
    }


def transcript_from_dict(d: dict) -> Transcript:
    return Transcript(
        language=d.get("language", ""),
        duration=d.get("duration", 0.0),
        segments=[
            Segment(
                start=s["start"],
                end=s["end"],
                text=s["text"],
                words=[Word(a, b, txt) for a, b, txt in s["words"]],
            )
            for s in d["segments"]
        ],
    )


def transcribe(
    media_path: str,
    model_size: str = "small",
    language: str = "",
    log: Callable[[str], None] = print,
    use_cache: bool = True,
) -> Transcript:
    cache: Optional[Path] = None
    if use_cache:
        cache = _cache_path(media_path, model_size, language)
        if cache.exists():
            log("Transcription trouvée en cache.")
            return transcript_from_dict(json.loads(cache.read_text(encoding="utf-8")))

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - dépend de l'installation
        raise RuntimeError(
            "faster-whisper n'est pas installé dans le Python utilisé par DaVinci Resolve. "
            "Lance : python install.py (voir README)."
        ) from exc

    log(f"Chargement du modèle Whisper « {model_size} »...")
    model = WhisperModel(model_size, device="auto")
    log("Transcription en cours (peut prendre quelques minutes)...")
    raw_segments, info = model.transcribe(
        media_path,
        language=language or None,
        word_timestamps=True,
        vad_filter=True,
    )

    segments = []
    for seg in raw_segments:
        words = [Word(float(w.start), float(w.end), w.word.strip()) for w in (seg.words or [])]
        segments.append(Segment(float(seg.start), float(seg.end), seg.text.strip(), words))

    transcript = Transcript(segments=segments, language=info.language, duration=float(info.duration))
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(transcript_to_dict(transcript), ensure_ascii=False), encoding="utf-8")
    log(f"Transcription terminée : {len(segments)} phrases, langue « {info.language} ».")
    return transcript
