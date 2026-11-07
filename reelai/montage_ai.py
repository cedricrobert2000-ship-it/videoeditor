"""Montage de plans (B-roll) : Claude regarde les clips du Media Pool et monte un reel,
calé sur le tempo de la musique."""

from __future__ import annotations

import base64
import io
import json
import math
from typing import Callable, List, Optional

from .config import Settings

MAX_IMAGES = 90
PACE = {  # durée de plan visée, durée minimale (s)
    "Lent": (3.0, 2.0),
    "Moyen": (2.0, 1.2),
    "Rapide": (1.0, 0.5),
}

LOOKS = ["Naturel", "Chaud doré", "Film doux", "Lumineux clean", "Noir & blanc"]

SYSTEM_PROMPT = """Tu es un monteur vidéo senior qui fait des reels Instagram/TikTok \
haut de gamme pour des marques. On te montre des images extraites de chaque clip \
disponible (avec l'instant exact de chaque image dans le clip). Tu construis le montage \
final, vertical 9:16, comme le ferait un studio pro.

Narration :
- Les 2 premières secondes accrochent : ouvre sur un plan intrigant ou très beau.
- Raconte une mini-histoire (ex. salon de coiffure : ambiance du lieu, geste précis du \
coiffeur, détails texture/mèches/produits, transformation, résultat final en mouvement, \
cliente qui sourit). Termine sur le plan le plus fort.
- Alterne les valeurs de plan (large, moyen, gros plan, détail) ; jamais deux plans \
quasi identiques à la suite.
- N'utilise que des moments nets, bien exposés et bien cadrés ; écarte tout ce qui est \
flou, noir, tremblé ou accidentel.

Rythme (TRÈS IMPORTANT) :
- Les durées des plans doivent VARIER pour créer un rythme vivant ; des plans tous de la \
même durée sont une faute. Typiquement : 2-3 plans d'ouverture plus courts, des plans \
« héros » (geste clé, résultat) nettement plus longs, un plan final le plus long.
- Si une musique est indiquée, exprime chaque durée en nombre de temps (`beats`) : \
2, 3, 4, 6 ou 8 temps, en privilégiant 4 et 8 (une mesure, deux mesures) pour les plans \
importants. Sinon, `beats` = 0 et seules start/end comptent.

Cadrage 9:16 : le clip sera recadré en vertical. Pour chaque plan, `subject_x` = position \
horizontale du sujet principal dans l'image (0 = bord gauche, 0.5 = centre, 1 = bord droit), \
et `zoom` entre 1.0 et 1.3 (1.1-1.25 sur les détails pour plus d'impact, 1.0 sur les plans larges).

Finitions :
- `look` : étalonnage cohérent pour toute la vidéo, adapté à la marque.
- `texts` : textes affichés SUR des plans précis (`shot` = index du plan dans `shots`, à \
partir de 0). Uniquement si on te le demande, sinon liste vide. Quand on le demande : 2 à 4 \
textes pour ~30 s — une accroche sur le 1er plan, éventuellement un message fort au \
milieu, et un appel à l'action sur le dernier plan. 2 à 6 mots chacun, ton de la marque, \
pas de hashtag ni d'emoji. Choisis des plans d'au moins 2 s avec de l'espace libre (pas \
sur un visage en gros plan). Aucun texte sur deux plans qui se suivent.

Titre, description, hashtags et textes en français. Si plusieurs reels sont demandés, \
fais-les vraiment différents (ouverture, angle, plans)."""

SHOT = {
    "type": "object",
    "properties": {
        "clip": {"type": "integer"},
        "start": {"type": "number"},
        "end": {"type": "number"},
        "beats": {"type": "integer"},
        "subject_x": {"type": "number"},
        "zoom": {"type": "number"},
    },
    "required": ["clip", "start", "end", "beats", "subject_x", "zoom"],
    "additionalProperties": False,
}

SCHEMA = {
    "type": "object",
    "properties": {
        "reels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "look": {"type": "string", "enum": LOOKS},
                    "shots": {"type": "array", "items": SHOT},
                    "texts": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"shot": {"type": "integer"}, "text": {"type": "string"}},
                        "required": ["shot", "text"],
                        "additionalProperties": False,
                    }},
                },
                "required": ["title", "description", "hashtags", "look", "shots", "texts"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["reels"],
    "additionalProperties": False,
}


# ------------------------------------------------------------ images
def extract_frames(path: str, times: List[float], max_side: int = 480) -> List[Optional[str]]:
    """Images JPEG (base64) aux instants demandés. None si l'image n'a pas pu être lue."""
    import av

    out: List[Optional[str]] = []
    with av.open(path) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        for t in times:
            img = None
            try:
                container.seek(int(t / stream.time_base), stream=stream, backward=True, any_frame=False)
                for frame in container.decode(stream):
                    if frame.time is None or frame.time >= t - 0.05:
                        img = frame.to_image()
                        break
            except Exception:
                img = None
            if img is None:
                out.append(None)
                continue
            img.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=72)
            out.append(base64.b64encode(buf.getvalue()).decode("ascii"))
    return out


# ------------------------------------------------------------- musique
def detect_beats(path: str, max_seconds: float = 240.0) -> dict:
    """Tempo et premier temps fort d'une musique (détection simple par énergie)."""
    import av
    import numpy as np

    sr, hop = 22050, 512
    chunks = []
    with av.open(path) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=sr)
        total = 0
        for frame in container.decode(stream):
            for f in resampler.resample(frame):
                arr = f.to_ndarray().reshape(-1)
                chunks.append(arr)
                total += arr.size
            if total > max_seconds * sr:
                break
    if not chunks:
        raise RuntimeError("Musique illisible.")
    y = np.concatenate(chunks).astype(np.float32)
    n = (y.size - 1024) // hop
    if n < 50:
        raise RuntimeError("Musique trop courte.")
    idx = np.arange(1024)[None, :] + hop * np.arange(n)[:, None]
    window = np.hanning(1024).astype(np.float32)
    spec = np.abs(np.fft.rfft(y[idx] * window, axis=1))
    flux = np.maximum(0.0, np.diff(np.log1p(spec), axis=0)).sum(axis=1)
    flux = flux - np.convolve(flux, np.ones(16) / 16, mode="same")
    flux = np.maximum(flux, 0)

    fps = sr / hop
    ac = np.correlate(flux, flux, mode="full")[flux.size - 1:]
    lags = np.arange(ac.size)
    bpm = np.where(lags > 0, 60.0 * fps / np.maximum(lags, 1), 0)
    valid = (bpm >= 70) & (bpm <= 180)
    lag = int(lags[valid][np.argmax(ac[valid])])

    # Affine la période (au centième de trame) et la phase sur toute la musique.
    best = (-1.0, float(lag), 0)
    for period_frames in np.arange(lag - 1.0, lag + 1.0, 0.02):
        count = int((flux.size - lag) / period_frames)
        if count < 4:
            continue
        steps = np.arange(count) * period_frames
        for o in range(int(period_frames)):
            pos = np.rint(o + steps).astype(int)
            pos = pos[pos < flux.size]
            score = float(flux[pos].sum())
            if score > best[0]:
                best = (score, float(period_frames), o)
    _, period_frames, o = best
    period = period_frames / fps
    # trame d'attaque -> instant (fenêtre de 1024 échantillons, différence entre trames)
    first = ((o + 1) * hop + 512) / sr
    first = first % period
    return {"bpm": round(60.0 / period, 1), "beat": period, "first_beat": first,
            "duration": y.size / sr}


def _clamp(v, lo, hi, default):
    try:
        return min(max(float(v), lo), hi)
    except (TypeError, ValueError):
        return default


def snap_shots(shots: List[dict], clips: dict, beat: Optional[float], pace: str) -> List[dict]:
    """Ajuste chaque plan pour que les coupes tombent sur les temps de la musique."""
    target, min_shot = PACE.get(pace, PACE["Moyen"])
    out = []
    for s in shots:
        clip = clips.get(s["clip"])
        if not clip:
            continue
        dur_clip = clip["duration"]
        start = min(max(0.0, float(s["start"])), max(0.0, dur_clip - 0.3))
        length = max(float(s["end"]) - start, min_shot)
        if beat:
            min_beats = max(1, math.ceil(min_shot / beat - 1e-6))
            n = int(s.get("beats") or 0) or int(round(length / beat))
            n = max(min_beats, n)
            while n > 1 and n * beat > dur_clip:
                n -= 1
            length = n * beat
        length = min(length, dur_clip)
        if start + length > dur_clip:
            start = max(0.0, dur_clip - length)
        out.append({"clip": s["clip"], "start": round(start, 3), "end": round(start + length, 3),
                    "subject_x": _clamp(s.get("subject_x"), 0.0, 1.0, 0.5),
                    "zoom": _clamp(s.get("zoom"), 1.0, 1.3, 1.0)})
    return out


def clean_texts(texts: List[dict], n_shots: int, limit: int = 5) -> List[dict]:
    """Garde des textes valides : un par plan, plans existants, ordre chronologique."""
    seen, out = set(), []
    for t in sorted(texts, key=lambda t: t.get("shot", 0)):
        i, text = t.get("shot"), str(t.get("text", "")).strip()
        if isinstance(i, int) and 0 <= i < n_shots and text and i not in seen:
            seen.add(i)
            out.append({"shot": i, "text": text[:60]})
    return out[:limit]


# ------------------------------------------------------------- plan IA
def _build_content(clips: List[dict], music: Optional[dict], settings: Settings,
                   log: Callable[[str], None]) -> List[dict]:
    try:  # échoue tout de suite (et une seule fois) si les outils image sont inutilisables
        import av  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception as exc:
        raise RuntimeError(f"Outils de lecture vidéo indisponibles : {exc}") from exc

    clips = sorted(clips, key=lambda c: -c["duration"])[:MAX_IMAGES]
    # 1 image par clip, puis les images restantes vont aux clips les plus longs (max 3).
    counts = {c["id"]: 1 for c in clips}
    spare = MAX_IMAGES - len(clips)
    while spare > 0 and any(v < 3 for v in counts.values()):
        for c in clips:
            if spare > 0 and counts[c["id"]] < 3:
                counts[c["id"]] += 1
                spare -= 1
    target, _ = PACE.get(settings.montage_pace, PACE["Moyen"])

    rhythm = f"Rythme demandé : {settings.montage_pace.lower()} (plans d'environ {target:.1f} s)."
    if music:
        rhythm += (f" Musique : {music['bpm']} BPM, un temps = {music['beat']:.2f} s ; donne la "
                   f"durée de chaque plan en `beats`, les coupes seront calées sur les temps.")
    else:
        rhythm += " Pas de musique : `beats` = 0."
    if settings.montage_look and settings.montage_look != "Auto":
        rhythm += f" Look imposé : {settings.montage_look}."
    rhythm += (" Ajoute des textes sur les plans (`texts`)." if settings.montage_texts
               else " Pas de texte : `texts` = [] sauf si les consignes du créateur en demandent.")
    extra = f"\nConsignes du créateur : {settings.instructions.strip()}" if settings.instructions.strip() else ""
    content: List[dict] = [{"type": "text", "text": (
        f"Monte {settings.reel_count} reel(s) vertical(aux) d'environ {settings.target_duration:.0f} s "
        f"(entre {settings.min_duration:.0f} et {settings.max_duration:.0f} s). {rhythm}{extra}\n\n"
        f"Voici les {len(clips)} clips disponibles :")}]

    for n, clip in enumerate(clips, 1):
        d = clip["duration"]
        k = counts[clip["id"]]
        times = [round(d * (i + 0.5) / k, 2) for i in range(k)]
        log(f"Analyse des images {n}/{len(clips)} : {clip['name']}")
        try:
            frames = extract_frames(clip["path"], times)
        except Exception as exc:
            log(f"  clip ignoré ({str(exc)[:150]})")
            continue
        shown = [(t, f) for t, f in zip(times, frames) if f]
        if not shown:
            continue
        content.append({"type": "text", "text": (
            f"Clip {clip['id']} « {clip['name']} » — durée {d:.1f} s — images à "
            + ", ".join(f"{t:.1f} s" for t, _ in shown))})
        for _, f in shown:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": f}})
    return content


def plan_montage(clips: List[dict], music_path: Optional[str], settings: Settings,
                 log: Callable[[str], None] = print, client=None) -> dict:
    if not clips:
        raise RuntimeError("Aucun clip vidéo trouvé dans le Media Pool.")
    music = None
    if music_path:
        log("Analyse du tempo de la musique...")
        try:
            music = detect_beats(music_path)
            log(f"Musique : {music['bpm']} BPM")
        except Exception as exc:
            log(f"Tempo non détecté ({exc}) : coupes libres.")

    content = _build_content(clips, music, settings, log)
    if client is None:
        import anthropic
        key = settings.resolved_api_key()
        if not key:
            raise RuntimeError("Clé API Anthropic manquante.")
        client = anthropic.Anthropic(api_key=key)

    log("Claude regarde les plans et construit le montage...")
    params = dict(
        model=settings.model, max_tokens=16000, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    try:
        resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
    except TypeError:
        resp = client.messages.create(**params)
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude a refusé de traiter ces images.")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("Réponse de Claude tronquée : demande moins de reels.")
    data = json.loads(next(b.text for b in resp.content if getattr(b, "type", "") == "text"))

    by_id = {c["id"]: c for c in clips}
    beat = music["beat"] if music else None
    reels = []
    for r in data.get("reels", [])[: settings.reel_count]:
        raw_shots = [sh for sh in r.get("shots", []) if sh.get("clip") in by_id]
        shots = snap_shots(raw_shots, by_id, beat, settings.montage_pace)
        if shots:
            tags = ["#" + t.strip().lstrip("#").replace(" ", "") for t in r.get("hashtags", []) if t.strip()]
            look = r.get("look", "Naturel")
            if settings.montage_look and settings.montage_look != "Auto":
                look = settings.montage_look
            reels.append({"title": r.get("title", "Reel"), "description": r.get("description", ""),
                          "hashtags": tags, "shots": shots, "look": look,
                          "texts": clean_texts(r.get("texts", []), len(shots))})
    log(f"Claude propose {len(reels)} montage(s).")
    return {"music": music, "reels": reels}


def vertical_frame(path: str, t: float, subject_x: float = 0.5, size=(1080, 1920)) -> bytes:
    """Image JPEG du plan à l'instant t, recadrée en 9:16 sur le sujet (comme dans la timeline)."""
    import av

    with av.open(path) as container:
        stream = container.streams.video[0]
        container.seek(int(t / stream.time_base), stream=stream, backward=True, any_frame=False)
        img = None
        for frame in container.decode(stream):
            if frame.time is None or frame.time >= t - 0.05:
                img = frame.to_image()
                break
    if img is None:
        raise RuntimeError("image du plan illisible")
    w, h = img.size
    target_ratio = size[0] / size[1]
    if w / h > target_ratio:  # image plus large que 9:16 : on coupe les côtés autour du sujet
        crop_w = int(h * target_ratio)
        left = int(min(max(subject_x * w - crop_w / 2, 0), w - crop_w))
        img = img.crop((left, 0, left + crop_w, h))
    else:
        crop_h = int(w / target_ratio)
        top = (h - crop_h) // 2
        img = img.crop((0, top, w, top + crop_h))
    img = img.convert("RGB").resize(size)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()
