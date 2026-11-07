"""Travail lourd hors de Resolve : transcription, IA, analyse d'images, musique, Higgsfield.

Peut tourner dans le Python de Resolve (si les paquets y sont installés) ou dans
un Python séparé, lancé en sous-processus :
    python -m reelai.worker job.json result.json
Les messages de progression sont écrits sur stdout, préfixés par « LOG: ».
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import Callable

from .config import Settings


def _settings(payload: dict) -> Settings:
    s = Settings()
    for k, v in payload.get("settings", {}).items():
        if hasattr(s, k):
            setattr(s, k, v)
    return s


def run_task(task: str, payload: dict, log: Callable[[str], None] = print,
             ai_client=None, hf_client=None) -> dict:
    settings = _settings(payload)

    if task == "transcribe":
        from .transcribe import transcribe, transcript_to_dict
        t = transcribe(payload["media"], settings.whisper_model, settings.language, log=log)
        return transcript_to_dict(t)

    if task == "plan_reels":
        from .editor_ai import plan_reels
        from .transcribe import transcript_from_dict
        plans = plan_reels(transcript_from_dict(payload["transcript"]), settings, log=log, client=ai_client)
        return {"plans": [asdict(p) for p in plans]}

    if task == "plan_montage":
        from .montage_ai import plan_montage
        return plan_montage(payload["clips"], payload.get("music"), settings, log=log, client=ai_client)

    if task == "motion":
        from .motion import download, generate_video, write_brief
        brief = write_brief(payload["text"], payload.get("context", ""), settings, client=ai_client)
        log(f"Concept : {brief.concept}")
        url = generate_video(brief, settings, log=log, hf_client=hf_client)
        path = download(url, payload["folder"], payload["text"])
        return {"brief": asdict(brief), "url": url, "path": path}

    raise ValueError(f"Tâche inconnue : {task}")


def main(argv) -> int:
    job_path, out_path = argv[1], argv[2]
    with open(job_path, encoding="utf-8") as fh:
        job = json.load(fh)

    def log(msg):
        print("LOG:" + str(msg).replace("\n", " "), flush=True)

    try:
        result = {"ok": True, "result": run_task(job["task"], job["payload"], log=log)}
    except Exception as exc:  # renvoyé à Resolve pour affichage
        result = {"ok": False, "error": str(exc) or exc.__class__.__name__}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
