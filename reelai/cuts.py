"""Transforme les passages choisis par l'IA en coupes précises (sans blancs ni « euh »)."""

from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Tuple

from .models import Cut, Word

_PUNCT = re.compile(r"[^\w']+", re.UNICODE)


def _normalize(text: str) -> str:
    return _PUNCT.sub("", text.lower())


def words_in_range(words: Sequence[Word], start: float, end: float) -> List[Word]:
    """Mots dont le centre tombe dans [start, end]."""
    return [w for w in words if start <= (w.start + w.end) / 2 <= end]


def build_cuts(
    segments: Iterable[Tuple[float, float]],
    words: Sequence[Word],
    remove_silences: bool = True,
    max_silence: float = 0.45,
    padding: float = 0.08,
    fillers: Iterable[str] = (),
    media_duration: float = 0.0,
) -> List[Cut]:
    filler_set = {_normalize(f) for f in fillers}
    cuts: List[Cut] = []

    for seg_start, seg_end in segments:
        seg_words = words_in_range(words, seg_start, seg_end)
        if filler_set:
            seg_words = [w for w in seg_words if _normalize(w.text) not in filler_set]

        if not seg_words:
            # Pas de parole (musique, plan de coupe) : on garde le passage tel quel.
            cuts.append(Cut(seg_start, seg_end, []))
            continue

        # Regroupe les mots consécutifs ; un blanc trop long sépare deux groupes.
        groups: List[List[Word]] = [[seg_words[0]]]
        for w in seg_words[1:]:
            gap = w.start - groups[-1][-1].end
            if remove_silences and gap > max_silence:
                groups.append([w])
            else:
                groups[-1].append(w)

        local: List[Cut] = []
        for g in groups:
            start = max(0.0, g[0].start - padding)
            end = g[-1].end + padding
            if media_duration:
                end = min(end, media_duration)
            if local and start < local[-1].end:  # les marges se chevauchent
                mid = (local[-1].words[-1].end + g[0].start) / 2
                local[-1].end = mid
                start = mid
            local.append(Cut(start, end, list(g)))
        cuts.extend(local)

    return [c for c in cuts if c.duration > 0.05]


def to_frames(cuts: Sequence[Cut], fps: float) -> List[Tuple[int, int]]:
    """Convertit les coupes en (frame_début, frame_fin_exclue) dans le média source."""
    frames = []
    for c in cuts:
        a = int(round(c.start * fps))
        b = int(round(c.end * fps))
        if b > a:
            frames.append((a, b))
    return frames


def remap_words(cuts: Sequence[Cut], fps: float) -> List[Word]:
    """Position de chaque mot sur la nouvelle timeline (secondes depuis le début du reel)."""
    out: List[Word] = []
    offset = 0  # en frames, pour coller exactement à ce que Resolve pose
    for c in cuts:
        a = int(round(c.start * fps))
        b = int(round(c.end * fps))
        if b <= a:
            continue
        for w in c.words:
            s = (offset + w.start * fps - a) / fps
            e = (offset + min(w.end * fps, b) - a) / fps
            out.append(Word(max(s, offset / fps), e, w.text))
        offset += b - a
    return out
