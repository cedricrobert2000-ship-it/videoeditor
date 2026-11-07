"""Génère des sous-titres style reel (2-3 mots, gros, dynamiques) au format SRT."""

from __future__ import annotations

from typing import List, Sequence, Tuple

from .models import Word

_END_PUNCT = (".", "!", "?", ",", ";", ":", "…")


def chunk_words(
    words: Sequence[Word], max_words: int = 3, max_chars: int = 22, max_gap: float = 0.6
) -> List[Tuple[float, float, str]]:
    chunks: List[Tuple[float, float, str]] = []
    current: List[Word] = []

    def flush():
        if current:
            chunks.append((current[0].start, current[-1].end, " ".join(w.text for w in current)))
            current.clear()

    for w in words:
        if current:
            text_len = len(" ".join(x.text for x in current)) + 1 + len(w.text)
            if (
                len(current) >= max_words
                or text_len > max_chars
                or w.start - current[-1].end > max_gap
                or current[-1].text.endswith(_END_PUNCT)
            ):
                flush()
        current.append(w)
    flush()

    # Chaque sous-titre reste affiché jusqu'au suivant (pas de clignotement).
    out = []
    for i, (s, e, t) in enumerate(chunks):
        if i + 1 < len(chunks):
            nxt = chunks[i + 1][0]
            if nxt - e < 0.5:
                e = nxt
        out.append((s, max(e, s + 0.2), t))
    return out


def _ts(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(chunks: Sequence[Tuple[float, float, str]], uppercase: bool = False) -> str:
    lines = []
    for i, (s, e, t) in enumerate(chunks, 1):
        text = t.upper() if uppercase else t
        lines.append(f"{i}\n{_ts(s)} --> {_ts(e)}\n{text}\n")
    return "\n".join(lines)
