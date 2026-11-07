"""Motion design par IA : Claude écrit le brief, Higgsfield génère la vidéo 9:16."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from typing import Callable, List, Optional

from .config import Settings

STYLES = {
    "Auto": "choose the style that best fits the message and the creator's tone",
    "Minimal premium": "minimal Apple-keynote aesthetic, soft gradients, glassmorphism, slow elegant moves",
    "Cinématique": "cinematic, anamorphic lighting, volumetric light, film grain, dramatic slow dolly",
    "Tech / néon": "futuristic tech, neon accents, dark background, data particles, glowing lines",
    "Luxe": "luxury brand, black and gold, macro textures, silk, slow reveals",
    "Énergique": "high energy, bold shapes, fast whip transitions, vibrant contrasting colors, punchy rhythm",
    "Nature / lifestyle": "organic, warm golden hour light, natural textures, gentle handheld feel",
}

BRIEF_SYSTEM = """You are a senior motion designer who makes premium short-form \
video graphics for top creators and brands. You turn one key sentence from a reel into \
a precise brief for an AI video generator. The result must look like it was made by a \
high-end studio: one strong visual idea that illustrates the MEANING of the sentence \
(metaphor, not literal clip-art), coherent palette, controlled camera move, clean \
composition, no clutter, no stock-footage look, no people's faces unless essential."""

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "concept": {"type": "string"},
        "video_prompt": {"type": "string"},
        "palette": {"type": "string"},
        "text_color": {"type": "string"},
    },
    "required": ["concept", "video_prompt", "palette", "text_color"],
    "additionalProperties": False,
}


@dataclass
class MotionBrief:
    concept: str
    video_prompt: str
    palette: str
    text_color: str  # hex, ex. "#FFFFFF"


@dataclass
class MotionResult:
    brief: MotionBrief
    file_path: str
    source_url: str


def write_brief(text: str, context: str, settings: Settings, client=None) -> MotionBrief:
    if client is None:
        import anthropic

        api_key = settings.resolved_api_key()
        if not api_key:
            raise RuntimeError("Clé API Anthropic manquante.")
        client = anthropic.Anthropic(api_key=api_key)

    overlay = settings.motion_text_overlay
    user = (
        f"Key sentence: \"{text}\"\n"
        f"Reel context: {context or 'n/a'}\n"
        f"Style: {STYLES.get(settings.motion_style, STYLES['Auto'])}\n"
        f"Format: vertical 9:16, {settings.motion_duration} seconds, seamless and smooth.\n"
        + (
            "The sentence will be added afterwards as crisp typography in the CENTER of the "
            "frame: the video must contain NO text, letters or logos, and must keep a calm, "
            "uncluttered area in the middle third for the title.\n"
            if overlay
            else f"The video must display this exact text as elegant kinetic typography, "
            f"spelled exactly: \"{text}\".\n"
        )
        + "Write video_prompt in English, 60-120 words: subject, environment, lighting, "
        "camera movement, pacing, palette, mood, render quality. text_color: a hex color "
        "readable on top of this video."
    )
    params = dict(
        model=settings.model,
        max_tokens=4000,
        system=BRIEF_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": BRIEF_SCHEMA}},
    )
    try:
        resp = client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params
        )
    except TypeError:
        resp = client.messages.create(**params)
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude a refusé ce texte.")
    data = json.loads(next(b.text for b in resp.content if getattr(b, "type", "") == "text"))
    color = data.get("text_color", "#FFFFFF")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color or ""):
        color = "#FFFFFF"
    return MotionBrief(data["concept"], data["video_prompt"], data["palette"], color)


def _pick_video_url(urls: List[str]) -> Optional[str]:
    for u in urls:
        if re.search(r"\.(mp4|mov|webm)(\?|$)", u, re.I):
            return u
    return None


def generate_video(brief: MotionBrief, settings: Settings, log: Callable[[str], None] = print,
                   hf_client=None) -> str:
    """Demande la vidéo à l'agent Higgsfield et renvoie son URL."""
    if hf_client is None:
        try:
            from higgsfield_client import SyncClient
        except ImportError as exc:
            raise RuntimeError("Le paquet « higgsfield-client » n'est pas installé : relance install.py.") from exc
        key = settings.higgsfield_key or os.environ.get("HF_KEY", "")
        if not key:
            raise RuntimeError("Clé Higgsfield manquante (format « key-id:key-secret », sur cloud.higgsfield.ai).")
        hf_client = SyncClient(api_key=key)

    prompt = (
        f"Generate ONE premium motion design video clip. Vertical 9:16, "
        f"{settings.motion_duration} seconds, highest quality model you have for this look.\n\n"
        f"{brief.video_prompt}\n\nPalette: {brief.palette}.\n\n"
        "Do not ask me questions: make the creative decisions yourself. "
        "When finished, reply with the direct URL of the final MP4 file."
    )
    log("Higgsfield génère le motion (1 à 5 minutes)...")
    session = hf_client.agents.sessions.create()
    result = hf_client.agents.sessions.run(
        session.session_id,
        prompt,
        on_question=lambda q: "Use your best judgment for a premium result, vertical 9:16, no text.",
        timeout=15 * 60,
    )
    if result.status != "completed":
        raise RuntimeError(f"Higgsfield n'a pas terminé la génération ({result.status}) : {result.text[:300]}")
    url = _pick_video_url(result.asset_urls)
    if not url:
        raise RuntimeError(f"Higgsfield n'a pas renvoyé de vidéo. Réponse : {result.text[:300]}")
    return url


def download(url: str, folder: str, name: str) -> str:
    os.makedirs(folder, exist_ok=True)
    ext = os.path.splitext(url.split("?")[0])[1] or ".mp4"
    safe = re.sub(r"[^\w\- ]+", "", name, flags=re.UNICODE).strip()[:40] or "motion"
    path = os.path.join(folder, f"Motion - {safe}{ext}")
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"Motion - {safe} ({n}){ext}")
        n += 1
    req = urllib.request.Request(url, headers={"User-Agent": "ReelAI"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(path, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    return path


def hex_to_rgb(color: str):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def create_motion(session, settings: Settings, text: str, log: Callable[[str], None] = print,
                  backend=None) -> MotionResult:
    """Génère le motion et le pose sur la timeline courante, à la tête de lecture."""
    from .backend import get_backend

    text = text.strip()
    if not text:
        raise RuntimeError("Écris (ou choisis) le texte du motion.")
    timeline = session.project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("Ouvre d'abord la timeline du reel.")
    record_frame = session.playhead_frame(timeline)
    folder = settings.output_dir or os.path.join(os.path.expanduser("~"), "Movies", "ReelAI")

    backend = backend or get_backend(settings, log)
    log("Claude conçoit le motion design...")
    res = backend.run("motion", {"text": text, "context": session.reel_context(timeline), "folder": folder},
                      settings, log)
    brief = MotionBrief(**res["brief"])
    log(f"Motion téléchargé : {res['path']}")

    session.insert_overlay(timeline, res["path"], record_frame, track=2)
    if settings.motion_text_overlay:
        if not session.insert_title(timeline, text, record_frame, track=3,
                                    seconds=settings.motion_duration, rgb=hex_to_rgb(brief.text_color)):
            log("Titre non ajouté automatiquement : ajoute un Text+ sur V3 avec ton texte.")
    log("✔ Motion ajouté sur la timeline.")
    return MotionResult(brief, res["path"], res["url"])


# ------------------------------------------------- textes animés sur les plans
TEXT_PROMPT = """Animate this exact image into a {seconds}-second vertical 9:16 video: {url}

Keep the SAME scene, people, framing, colors and lighting as the image (image-to-video, \
no new people, no change of place). Add a subtle, smooth cinematic camera push-in and \
natural micro-movements.

Integrate this text into the shot as premium kinetic typography: "{text}"
- spelled EXACTLY like that, with the same accents and capitals; no other text or logo;
- elegant modern typeface (clean sans-serif or refined serif), {color};
- smooth reveal animation (letters or words gliding/fading in), then it holds, readable;
- placed in empty space of the frame, never covering faces; high-end beauty brand look.

Do not ask me questions. When finished, reply with the direct URL of the final MP4."""


def animate_text_shot(item: dict, settings: Settings, hf_client, log: Callable[[str], None]) -> str:
    """Envoie l'image du plan à Higgsfield et renvoie l'URL de la vidéo animée avec le texte."""
    from .montage_ai import vertical_frame

    image = vertical_frame(item["path"], item["time"], item.get("subject_x", 0.5))
    url = hf_client.agents.media.upload(image, extension="jpeg", type="image")
    seconds = max(3, min(10, int(round(item.get("seconds", 5)))))
    prompt = TEXT_PROMPT.format(seconds=seconds, url=url, text=item["text"],
                                color=item.get("color") or "white with a soft shadow")
    session = hf_client.agents.sessions.create()
    result = hf_client.agents.sessions.run(
        session.session_id, prompt,
        on_question=lambda q: "Use your best judgment: keep the scene identical, premium animated text.",
        timeout=15 * 60,
    )
    if result.status != "completed":
        raise RuntimeError(f"Higgsfield : {result.status} {result.text[:200]}")
    video = _pick_video_url(result.asset_urls)
    if not video:
        raise RuntimeError(f"Higgsfield n'a pas renvoyé de vidéo ({result.text[:200]})")
    return video


def animate_texts(items: List[dict], folder: str, settings: Settings,
                  log: Callable[[str], None] = print, hf_client=None) -> List[dict]:
    """Anime plusieurs plans en parallèle. Renvoie [{"path": ...} ou {"error": ...}] dans l'ordre."""
    from concurrent.futures import ThreadPoolExecutor

    if hf_client is None:
        from higgsfield_client import SyncClient
        key = settings.higgsfield_key or os.environ.get("HF_KEY", "")
        if not key:
            raise RuntimeError("Clé Higgsfield manquante (colonne de droite de la fenêtre ReelAI).")
        hf_client = SyncClient(api_key=key)

    log(f"Higgsfield anime {len(items)} texte(s) en parallèle (1 à 5 minutes)...")

    def one(item):
        try:
            url = animate_text_shot(item, settings, hf_client, log)
            path = download(url, folder, item["text"])
            log(f"✔ Texte animé : « {item['text']} »")
            return {"path": path}
        except Exception as exc:
            log(f"✖ « {item['text']} » non animé par Higgsfield ({str(exc)[:150]})")
            return {"error": str(exc)}

    with ThreadPoolExecutor(max_workers=min(4, max(1, len(items)))) as pool:
        return list(pool.map(one, items))
