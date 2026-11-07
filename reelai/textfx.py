"""Textes animés « pro » rendus par ReelAI : vidéo transparente (ProRes 4444) à poser
au-dessus d'un plan. Animation mot par mot (fondu + glissé vers le haut), maintien,
puis disparition. Durée exacte au frame près, indépendante de Fusion."""

from __future__ import annotations

import os
import sys
import textwrap
from typing import List, Optional, Tuple

W, H = 1080, 1920
POSITIONS = {"top": 0.22, "middle": 0.5, "bottom": 0.74}

FONT_CANDIDATES = [
    "/System/Library/Fonts/Avenir Next.ttc",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Supplemental/Futura.ttc",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
_FONT_CACHE: dict = {}


def load_font(size: int):
    """Police grasse élégante disponible sur la machine (Avenir Next Demi Bold sur Mac)."""
    from PIL import ImageFont

    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    for path in FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        best = None
        for index in range(0, 16 if path.endswith(".ttc") else 1):
            try:
                font = ImageFont.truetype(path, size, index=index)
            except Exception:
                break
            style = " ".join(font.getname()).lower()
            if "italic" in style or "oblique" in style or "condensed" in style:
                continue
            if "demi bold" in style or "demibold" in style:
                best = font
                break
            if "bold" in style and "heavy" not in style and best is None:
                best = font
        if best is None:
            try:
                best = ImageFont.truetype(path, size)
            except Exception:
                continue
        _FONT_CACHE[size] = best
        return best
    _FONT_CACHE[size] = ImageFont.load_default()
    return _FONT_CACHE[size]


def _ease_out(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def balanced_lines(text: str, max_chars: int = 16) -> List[str]:
    """Coupe en lignes de longueurs proches (plus élégant que le remplissage glouton)."""
    words = text.split()
    n = max(1, len(textwrap.wrap(text, max_chars)))
    if n == 1 or len(words) < 2:
        return [text]
    best, best_score = None, None
    def splits(ws, k):
        if k == 1:
            yield [" ".join(ws)]
            return
        for i in range(1, len(ws) - k + 2):
            for rest in splits(ws[i:], k - 1):
                yield [" ".join(ws[:i])] + rest
    for cand in splits(words, n):
        score = max(len(l) for l in cand) - min(len(l) for l in cand)
        if best_score is None or score < best_score:
            best, best_score = cand, score
    return best


def _layout(text: str, font, max_chars: int = 16) -> List[List[Tuple[str, int, int]]]:
    """Découpe en lignes et renvoie, par ligne, (mot, x, largeur) centrés."""
    lines = balanced_lines(text, max_chars)
    space = font.getlength(" ")
    out = []
    for line in lines:
        words = line.split()
        widths = [int(font.getlength(w)) for w in words]
        total = sum(widths) + space * (len(words) - 1)
        x = (W - total) / 2
        row = []
        for w, wd in zip(words, widths):
            row.append((w, int(x), wd))
            x += wd + space
        out.append(row)
    return out


def _word_sprites(text: str, font, color, shadow: bool):
    """Pré-rend chaque mot (avec ombre douce) une seule fois."""
    from PIL import Image, ImageDraw, ImageFilter

    ascent, descent = font.getmetrics()
    h = ascent + descent
    pad = 30
    img = Image.new("RGBA", (int(font.getlength(text)) + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((pad, pad), text, font=font, fill=color + (255,))
    if shadow:
        alpha = img.getchannel("A").filter(ImageFilter.GaussianBlur(10))
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sh.putalpha(alpha.point(lambda a: int(a * 0.55)))
        sh = sh.transform(sh.size, Image.AFFINE, (1, 0, 0, 0, 1, -4))
        img = Image.alpha_composite(sh, img)
    return img, pad


def render_frames(text: str, frames: int, fps: float, position: str = "bottom",
                  color=(255, 255, 255), uppercase: bool = False, size: int = 92):
    """Générateur d'images RGBA (PIL) de l'animation."""
    from PIL import Image

    text = text.upper() if uppercase else text
    font = load_font(size)
    layout = _layout(text, font)
    line_h = int(size * 1.18)
    y0 = int(H * POSITIONS.get(position, POSITIONS["bottom"]) - line_h * len(layout) / 2)

    sprites = []
    order = 0
    for li, row in enumerate(layout):
        for word, x, _ in row:
            img, pad = _word_sprites(word, font, color, shadow=True)
            sprites.append((img, x - pad, y0 + li * line_h - pad, order))
            order += 1

    stagger, appear, slide = 0.07 * fps, 0.38 * fps, 46
    fade_out = max(1, int(0.3 * fps))
    for f in range(frames):
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        out_k = 1.0 if f < frames - fade_out else max(0.0, (frames - 1 - f) / fade_out)
        for img, x, y, k in sprites:
            p = _ease_out((f - k * stagger) / appear)
            a = p * out_k
            if a <= 0.01:
                continue
            sprite = img if a >= 0.99 else _fade(img, a)
            canvas.alpha_composite(sprite, (x, int(y + (1 - p) * slide)))
        yield canvas


def _fade(img, a: float):
    alpha = img.getchannel("A").point(lambda v: int(v * a))
    out = img.copy()
    out.putalpha(alpha)
    return out


def render_text_clip(text: str, out_path: str, frames: int, fps: float, position: str = "bottom",
                     color=(255, 255, 255), uppercase: bool = False) -> str:
    """Écrit une vidéo transparente (ProRes 4444 ; QuickTime Animation si indisponible)."""
    import av
    import numpy as np

    rate = _fraction(fps)
    for codec, pix, opts in (("prores_ks", "yuva444p10le", {"profile": "4", "vendor": "apl0"}),
                             ("qtrle", "argb", {})):
        try:
            with av.open(out_path, "w") as container:
                stream = container.add_stream(codec, rate=rate, options=opts)
                stream.width, stream.height, stream.pix_fmt = W, H, pix
                stream.codec_context.thread_type = "AUTO"
                for img in render_frames(text, frames, fps, position, color, uppercase):
                    frame = av.VideoFrame.from_ndarray(np.asarray(img), format="rgba")
                    for packet in stream.encode(frame):
                        container.mux(packet)
                for packet in stream.encode():
                    container.mux(packet)
            return out_path
        except Exception as exc:  # codec absent : on essaie le suivant
            last = exc
            if os.path.exists(out_path):
                os.remove(out_path)
    raise RuntimeError(f"Impossible d'encoder le texte animé : {last}")


def _fraction(fps: float):
    from fractions import Fraction
    for num, den in ((24000, 1001), (30000, 1001), (60000, 1001)):
        if abs(fps - num / den) < 0.01:
            return Fraction(num, den)
    return Fraction(fps).limit_denominator(1000)


def hex_to_rgb255(color: Optional[str]):
    try:
        c = (color or "").lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (255, 255, 255)


def render_many(items: List[dict], folder: str, log=print) -> List[dict]:
    """Rend plusieurs textes en parallèle. items : text, frames, fps, position, color, name."""
    from concurrent.futures import ThreadPoolExecutor

    os.makedirs(folder, exist_ok=True)

    def one(item):
        safe = "".join(ch for ch in item["text"] if ch.isalnum() or ch in " -")[:30].strip() or "texte"
        path = os.path.join(folder, f"Texte - {item.get('name', '')}{safe}.mov")
        try:
            render_text_clip(item["text"], path, item["frames"], item["fps"], item.get("position", "bottom"),
                             hex_to_rgb255(item.get("color")), item.get("uppercase", False))
            log(f"✔ Texte animé : « {item['text']} »")
            return {"path": path}
        except Exception as exc:
            return {"error": str(exc)}

    with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 2, max(1, len(items)))) as pool:
        return list(pool.map(one, items))


if __name__ == "__main__":  # aperçu rapide : python -m reelai.textfx "Mon texte"
    render_text_clip(sys.argv[1] if len(sys.argv) > 1 else "Ta coupe, ta signature",
                     "apercu_texte.mov", 75, 25.0)
    print("apercu_texte.mov")
