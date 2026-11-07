"""Orchestration : vidéo source -> transcription -> choix IA -> timelines 9:16 prêtes."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .config import Settings
from .cuts import build_cuts, remap_words, to_frames
from .editor_ai import plan_reels
from .models import ReelPlan
from .resolve_bridge import ResolveSession
from .subtitles import chunk_words, to_srt
from .transcribe import transcribe


@dataclass
class ReelResult:
    plan: ReelPlan
    timeline_name: str
    srt_path: Optional[str] = None
    caption_path: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


def _safe_name(text: str) -> str:
    text = re.sub(r"[^\w\- ]+", "", text, flags=re.UNICODE).strip()
    return (text or "Reel")[:50]


def output_dir_for(settings: Settings, media_path: str) -> str:
    out = settings.output_dir or os.path.join(os.path.dirname(media_path), "ReelAI")
    os.makedirs(out, exist_ok=True)
    return out


def run(
    session: ResolveSession,
    settings: Settings,
    log: Callable[[str], None] = print,
    ai_client=None,
    transcriber=transcribe,
) -> List[ReelResult]:
    source = session.find_source_clip()
    media_path, fps, clip_name = session.clip_info(source)
    log(f"Vidéo source : {clip_name} ({fps:g} i/s)")
    out_dir = output_dir_for(settings, media_path)

    transcript = transcriber(media_path, settings.whisper_model, settings.language, log=log)
    plans = plan_reels(transcript, settings, log=log, client=ai_client)
    if not plans:
        raise RuntimeError("L'IA n'a trouvé aucun passage exploitable.")

    words = transcript.words
    results: List[ReelResult] = []
    render_jobs: List[str] = []

    for i, plan in enumerate(plans, 1):
        plan.cuts = build_cuts(
            plan.segments,
            words,
            remove_silences=settings.remove_silences,
            max_silence=settings.max_silence,
            padding=settings.padding,
            fillers=settings.filler_words if settings.remove_fillers else (),
            media_duration=transcript.duration,
        )
        frames = to_frames(plan.cuts, fps)
        if not frames:
            log(f"Reel {i} ignoré : aucune coupe valide.")
            continue

        base = f"Reel {i} - {_safe_name(plan.title)}"
        log(f"Montage de « {base} » : {len(frames)} coupes, {plan.duration:.1f} s")
        timeline = session.build_timeline(
            base, source, frames, settings.vertical, settings.width, settings.height, log=log
        )
        result = ReelResult(plan=plan, timeline_name=timeline.GetName())

        note = "\n".join(filter(None, [plan.hook, plan.description, " ".join(plan.hashtags)]))
        session.add_marker(timeline, plan.title, note)

        file_base = os.path.join(out_dir, _safe_name(timeline.GetName()))
        result.caption_path = file_base + " - legende.txt"
        with open(result.caption_path, "w", encoding="utf-8") as fh:
            fh.write(f"{plan.title}\n\n{plan.description}\n\n{' '.join(plan.hashtags)}\n")

        if settings.subtitles:
            chunks = chunk_words(
                remap_words(plan.cuts, fps),
                max_words=settings.subtitle_max_words,
                max_chars=settings.subtitle_max_chars,
            )
            result.srt_path = file_base + ".srt"
            with open(result.srt_path, "w", encoding="utf-8") as fh:
                fh.write(to_srt(chunks, uppercase=settings.subtitle_uppercase))
            if not session.add_subtitles(timeline, result.srt_path):
                msg = f"Sous-titres non posés automatiquement : glisse {result.srt_path} sur la timeline."
                result.warnings.append(msg)
                log(msg)

        if settings.render:
            job = session.queue_render(timeline, out_dir, _safe_name(timeline.GetName()))
            if job:
                render_jobs.append(job)
            else:
                result.warnings.append("Impossible d'ajouter le rendu à la file d'attente.")

        results.append(result)

    if render_jobs:
        log(f"Lancement du rendu de {len(render_jobs)} reel(s) dans {out_dir}")
        session.start_render(render_jobs)

    log(f"Terminé : {len(results)} reel(s) créés. Fichiers dans {out_dir}")
    return results
