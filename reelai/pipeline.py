"""Orchestration des deux modes :
- media_pool : Claude regarde tous les plans du Media Pool et monte des reels sur la musique ;
- selected   : vidéo parlée sélectionnée -> transcription -> meilleurs passages -> reels sous-titrés.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .backend import get_backend
from .config import Settings
from .cuts import build_cuts, remap_words, to_frames
from .models import ReelPlan
from .resolve_bridge import ResolveSession
from .subtitles import chunk_words, to_srt
from .transcribe import transcript_from_dict


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


def _write_caption(out_dir: str, timeline_name: str, plan: ReelPlan) -> str:
    path = os.path.join(out_dir, _safe_name(timeline_name) + " - legende.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"{plan.title}\n\n{plan.description}\n\n{' '.join(plan.hashtags)}\n")
    return path


def _finish(session, settings, results, render_jobs, out_dir, log):
    if render_jobs:
        log(f"Lancement du rendu de {len(render_jobs)} reel(s) dans {out_dir}")
        session.start_render(render_jobs)
    log(f"Terminé : {len(results)} reel(s) créés dans le chutier ReelAI. Fichiers : {out_dir}")
    return results


def run(session: ResolveSession, settings: Settings, log: Callable[[str], None] = print,
        backend=None) -> List[ReelResult]:
    backend = backend or get_backend(settings, log)
    if settings.source_mode == "selected":
        return run_selected(session, settings, log, backend)
    return run_media_pool(session, settings, log, backend)


# ------------------------------------------------------------ Media Pool
def run_media_pool(session, settings, log, backend) -> List[ReelResult]:
    clips = session.list_clips("video")
    if not clips:
        raise RuntimeError("Aucun clip vidéo trouvé dans le Media Pool.")
    log(f"{len(clips)} clip(s) vidéo trouvés dans le Media Pool.")

    music = None
    if settings.music_name != "-":
        musics = session.list_clips("audio")
        if settings.music_name:
            music = next((m for m in musics if m["name"] == settings.music_name), None)
            if not music:
                log(f"Musique « {settings.music_name} » introuvable dans le Media Pool.")
        else:
            selected = session.selected_audio_name()
            music = next((m for m in musics if m["name"] == selected), None) or (musics[0] if musics else None)
        if music:
            log(f"Musique : {music['name']}")
    if not music:
        log("Aucune musique : coupes libres, sans calage sur le tempo.")

    payload_clips = [{k: c[k] for k in ("id", "name", "path", "duration")} for c in clips]
    plan = backend.run("plan_montage", {"clips": payload_clips, "music": music["path"] if music else None},
                       settings, log)
    if not plan["reels"]:
        raise RuntimeError("L'IA n'a pas proposé de montage.")

    by_id = {c["id"]: c for c in clips}
    out_dir = output_dir_for(settings, clips[0]["path"])
    results, jobs = [], []
    for i, r in enumerate(plan["reels"], 1):
        rp = ReelPlan(title=r["title"], hook="", description=r["description"], hashtags=r["hashtags"],
                      segments=[(s["start"], s["end"]) for s in r["shots"]])
        total = sum(s["end"] - s["start"] for s in r["shots"])
        name = f"Reel {i} - {_safe_name(rp.title)}"
        log(f"Montage de « {name} » : {len(r['shots'])} plans, {total:.1f} s")
        timeline, positions = session.build_montage_timeline(
            name, r["shots"], by_id, music=music, music_info=plan.get("music"),
            vertical=settings.vertical, width=settings.width, height=settings.height, log=log,
            look=r.get("look", "Naturel"), music_start=r.get("music_start"))
        res = ReelResult(plan=rp, timeline_name=timeline.GetName())
        texts = [t for t in r.get("texts", []) if t["shot"] in positions]
        save_plan(timeline.GetName(), {
            "texts": texts, "shots": r["shots"], "look": r.get("look", ""), "out_dir": out_dir,
            "positions": {str(k): v for k, v in positions.items()},
            "paths": {str(c["id"]): c["path"] for c in clips}})
        if texts:
            listing = " · ".join(f"« {t['text']} »" for t in texts)
            if settings.montage_texts and settings.text_animation == "reelai":
                res.warnings += add_shot_texts(session, timeline, texts, r["shots"], positions,
                                               {c["id"]: c["path"] for c in clips}, settings, out_dir,
                                               backend, log, look=r.get("look", ""), mode="reelai")
            else:
                log(f"Textes proposés : {listing}. Ajoute-les quand tu veux avec « ✍️ Ajouter les textes ».")
        session.add_marker(timeline, rp.title, "\n".join([rp.description, " ".join(rp.hashtags)]))
        res.caption_path = _write_caption(out_dir, timeline.GetName(), rp)
        if settings.render:
            job = session.queue_render(timeline, out_dir, _safe_name(timeline.GetName()))
            jobs.append(job) if job else res.warnings.append("Rendu non ajouté à la file d'attente.")
        results.append(res)
    return _finish(session, settings, results, jobs, out_dir, log)


# ---------------------------------------------------------------- textes
def _plan_path(timeline_name: str) -> str:
    from .config import CONFIG_DIR
    return os.path.join(str(CONFIG_DIR), "plans", _safe_name(timeline_name) + ".json")


def save_plan(timeline_name: str, data: dict) -> None:
    import json
    path = _plan_path(timeline_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)


def load_plan(timeline_name: str) -> Optional[dict]:
    import json
    try:
        with open(_plan_path(timeline_name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


TEXT_COLORS = {"Chaud doré": "warm ivory white with a subtle golden glow",
               "Noir & blanc": "pure white", "Film doux": "soft cream white"}


def add_shot_texts(session, timeline, texts, shots, positions, clip_paths, settings, out_dir,
                   backend, log, look: str = "", mode: str = "reelai") -> List[str]:
    """Pose les textes sur les plans choisis.
    mode "reelai" : typo animée rendue par ReelAI (rapide) sur V3.
    mode "higgsfield" : le plan est réanimé par Higgsfield avec le texte intégré (V2) ;
    en cas d'échec, ce plan reçoit le texte ReelAI."""
    warnings: List[str] = []
    fps = session.timeline_fps(timeline)
    pending = list(texts)

    if mode == "higgsfield":
        if not (settings.higgsfield_key or os.environ.get("HF_KEY")):
            log("Pas de clé Higgsfield : textes animés par ReelAI à la place.")
        else:
            items = []
            for t in texts:
                shot = shots[t["shot"]]
                _, frames = positions[t["shot"]]
                items.append({"path": clip_paths[shot["clip"]], "time": (shot["start"] + shot["end"]) / 2,
                              "subject_x": shot.get("subject_x", 0.5), "text": t["text"],
                              "seconds": frames / fps,
                              "color": TEXT_COLORS.get(look, "white with a soft shadow")})
            try:
                outcomes = backend.run("animate_texts", {"items": items, "folder": out_dir}, settings, log)["results"]
            except Exception as exc:
                log(f"Higgsfield indisponible ({exc}) : textes animés par ReelAI à la place.")
                outcomes = [{"error": str(exc)}] * len(texts)
            pending = []
            for t, outcome in zip(texts, outcomes):
                record, frames = positions[t["shot"]]
                if outcome.get("path"):
                    try:
                        session.insert_overlay(timeline, outcome["path"], record, track=2, max_frames=frames)
                        continue
                    except Exception as exc:
                        log(f"Clip Higgsfield non posé ({exc})")
                pending.append(t)

    if pending:
        log(f"Rendu de {len(pending)} texte(s) animé(s)...")
        items = [{"text": t["text"], "frames": positions[t["shot"]][1], "fps": fps,
                  "position": t.get("position", "bottom"), "uppercase": settings.subtitle_uppercase,
                  "name": f"{_safe_name(timeline.GetName())[:20]} - "} for t in pending]
        try:
            outcomes = backend.run("render_texts", {"items": items, "folder": out_dir}, settings, log)["results"]
        except Exception as exc:
            outcomes = [{"error": str(exc)}] * len(pending)
        for t, outcome in zip(pending, outcomes):
            record, frames = positions[t["shot"]]
            try:
                if not outcome.get("path"):
                    raise RuntimeError(outcome.get("error", "rendu impossible"))
                session.insert_overlay(timeline, outcome["path"], record, track=3, max_frames=frames)
            except Exception as exc:
                warnings.append(f"Texte « {t['text']} » non ajouté ({str(exc)[:120]}).")
                log(warnings[-1])
    if texts:
        log(f"{len(texts) - len(warnings)} texte(s) ajouté(s) sur les plans.")
    return warnings


def add_texts_to_current_timeline(session, settings, log: Callable[[str], None] = print,
                                  backend=None, mode: Optional[str] = None) -> List[str]:
    """Étape « après le montage » : ajoute les textes proposés sur la timeline ouverte."""
    timeline = session.project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("Ouvre d'abord la timeline d'un reel créé par ReelAI.")
    plan = load_plan(timeline.GetName())
    if not plan:
        raise RuntimeError(f"Pas de plan ReelAI pour « {timeline.GetName()} » : relance un montage.")
    if not plan["texts"]:
        raise RuntimeError("L'IA n'a pas proposé de texte pour ce reel : coche « Textes sur les plans » "
                           "et relance le montage, ou utilise le Motion design.")
    backend = backend or get_backend(settings, log)
    positions = {int(k): tuple(v) for k, v in plan["positions"].items()}
    paths = {int(k): v for k, v in plan["paths"].items()}
    log(f"Textes : " + " · ".join(f"« {t['text']} »" for t in plan["texts"]))
    return add_shot_texts(session, timeline, plan["texts"], plan["shots"], positions, paths, settings,
                          plan["out_dir"], backend, log, look=plan.get("look", ""),
                          mode=mode or settings.text_animation)


# ------------------------------------------------------- vidéo parlée
def run_selected(session, settings, log, backend) -> List[ReelResult]:
    source = session.find_source_clip()
    media_path, fps, clip_name = session.clip_info(source)
    log(f"Vidéo source : {clip_name} ({fps:g} i/s)")
    out_dir = output_dir_for(settings, media_path)

    transcript = transcript_from_dict(backend.run("transcribe", {"media": media_path}, settings, log))
    if not transcript.segments:
        raise RuntimeError("Aucune parole détectée : choisis plutôt la source « Tout le Media Pool ».")
    from .transcribe import transcript_to_dict
    raw = backend.run("plan_reels", {"transcript": transcript_to_dict(transcript)}, settings, log)["plans"]
    plans = [ReelPlan(title=p["title"], hook=p["hook"], description=p["description"],
                      hashtags=p["hashtags"], segments=[tuple(s) for s in p["segments"]]) for p in raw]
    if not plans:
        raise RuntimeError("L'IA n'a trouvé aucun passage exploitable.")

    words = transcript.words
    results, jobs = [], []
    for i, plan in enumerate(plans, 1):
        plan.cuts = build_cuts(
            plan.segments, words,
            remove_silences=settings.remove_silences, max_silence=settings.max_silence,
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
        timeline = session.build_timeline(base, source, frames, settings.vertical,
                                          settings.width, settings.height, log=log)
        result = ReelResult(plan=plan, timeline_name=timeline.GetName())
        session.add_marker(timeline, plan.title,
                           "\n".join(filter(None, [plan.hook, plan.description, " ".join(plan.hashtags)])))
        result.caption_path = _write_caption(out_dir, timeline.GetName(), plan)

        if settings.subtitles:
            chunks = chunk_words(remap_words(plan.cuts, fps), max_words=settings.subtitle_max_words,
                                 max_chars=settings.subtitle_max_chars)
            result.srt_path = os.path.join(out_dir, _safe_name(timeline.GetName()) + ".srt")
            with open(result.srt_path, "w", encoding="utf-8") as fh:
                fh.write(to_srt(chunks, uppercase=settings.subtitle_uppercase))
            if not session.add_subtitles(timeline, result.srt_path):
                msg = f"Sous-titres non posés automatiquement : glisse {result.srt_path} sur la timeline."
                result.warnings.append(msg)
                log(msg)

        if settings.render:
            job = session.queue_render(timeline, out_dir, _safe_name(timeline.GetName()))
            jobs.append(job) if job else result.warnings.append("Rendu non ajouté à la file d'attente.")
        results.append(result)

    return _finish(session, settings, results, jobs, out_dir, log)
