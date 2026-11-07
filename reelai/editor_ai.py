"""Choix des meilleurs passages par Claude : l'IA joue le rôle du monteur."""

from __future__ import annotations

import json
from typing import Callable, List

from .config import Settings
from .models import ReelPlan, Transcript

SYSTEM_PROMPT = """Tu es un monteur vidéo expert des formats courts verticaux \
(Instagram Reels, TikTok, YouTube Shorts). On te donne la transcription horodatée \
d'une vidéo longue. Ton travail : choisir les passages qui feront les reels les plus \
engageants.

Règles de montage :
- Chaque reel doit commencer par un HOOK fort dans les 2 premières secondes \
(question, affirmation surprenante, promesse, chiffre). Tu peux placer en premier un \
passage qui vient plus tard dans la vidéo si c'est le meilleur hook.
- Chaque reel doit être compréhensible seul, sans le reste de la vidéo, et se terminer \
sur une phrase complète (chute, conclusion ou punchline).
- Utilise uniquement des timecodes qui existent dans la transcription. Coupe aux \
frontières de phrases ou de mots, jamais au milieu d'un mot.
- Enlève les digressions, répétitions et faux départs : un reel peut être composé de \
plusieurs morceaux non contigus.
- Les reels ne doivent pas se recouvrir entre eux.
- Titre, description et hashtags sont écrits dans la langue de la vidéo."""

REEL_SCHEMA = {
    "type": "object",
    "properties": {
        "reels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "hook": {"type": "string"},
                    "description": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "segments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start": {"type": "number"},
                                "end": {"type": "number"},
                            },
                            "required": ["start", "end"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "hook", "description", "hashtags", "segments"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["reels"],
    "additionalProperties": False,
}


def format_transcript(transcript: Transcript) -> str:
    return "\n".join(f"[{s.start:.2f} - {s.end:.2f}] {s.text}" for s in transcript.segments)


def build_user_prompt(transcript: Transcript, settings: Settings) -> str:
    extra = f"\nConsignes du créateur : {settings.instructions.strip()}\n" if settings.instructions.strip() else ""
    return (
        f"Durée totale de la vidéo : {transcript.duration:.1f} s.\n"
        f"Propose jusqu'à {settings.reel_count} reel(s). Durée visée par reel : "
        f"~{settings.target_duration:.0f} s (minimum {settings.min_duration:.0f} s, "
        f"maximum {settings.max_duration:.0f} s). Classe-les du plus fort au moins fort.\n"
        f"{extra}\n"
        f"Transcription (timecodes en secondes) :\n{format_transcript(transcript)}"
    )


def _call_claude(client, settings: Settings, user_prompt: str):
    params = dict(
        model=settings.model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": REEL_SCHEMA},
        },
    )
    try:
        # Repli automatique sur un autre modèle si la requête est refusée.
        return client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params
        )
    except TypeError:
        # SDK plus ancien qui ne connaît pas encore `fallbacks`.
        return client.messages.create(**params)


def parse_response(text: str, duration: float) -> List[ReelPlan]:
    data = json.loads(text)
    plans = []
    for r in data.get("reels", []):
        segs = []
        for s in r.get("segments", []):
            start = max(0.0, float(s["start"]))
            end = float(s["end"])
            if duration:
                end = min(end, duration)
            if end - start > 0.2:
                segs.append((start, end))
        if not segs:
            continue
        tags = [t if t.startswith("#") else "#" + t for t in (h.strip().replace(" ", "") for h in r.get("hashtags", [])) if t]
        plans.append(
            ReelPlan(
                title=r.get("title", "").strip() or "Reel",
                hook=r.get("hook", "").strip(),
                description=r.get("description", "").strip(),
                hashtags=tags,
                segments=segs,
            )
        )
    return plans


def plan_reels(
    transcript: Transcript,
    settings: Settings,
    log: Callable[[str], None] = print,
    client=None,
) -> List[ReelPlan]:
    if not transcript.segments:
        raise RuntimeError("Aucune parole détectée dans la vidéo : impossible de choisir des passages.")

    if client is None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Le paquet « anthropic » n'est pas installé (voir README).") from exc
        api_key = settings.resolved_api_key()
        if not api_key:
            raise RuntimeError("Clé API Anthropic manquante : renseigne-la dans la fenêtre ReelAI.")
        client = anthropic.Anthropic(api_key=api_key)

    log(f"Claude analyse la transcription ({settings.model})...")
    response = _call_claude(client, settings, build_user_prompt(transcript, settings))

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude a refusé de traiter cette vidéo.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Réponse de Claude tronquée : réduis le nombre de reels demandés.")

    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
    plans = parse_response(text, transcript.duration)
    log(f"Claude propose {len(plans)} reel(s).")
    return plans[: settings.reel_count]
