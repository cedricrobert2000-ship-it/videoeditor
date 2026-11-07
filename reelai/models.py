"""Structures de données partagées."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: List[Word] = field(default_factory=list)


@dataclass
class Transcript:
    segments: List[Segment]
    language: str = ""
    duration: float = 0.0

    @property
    def words(self) -> List[Word]:
        return [w for s in self.segments for w in s.words]


@dataclass
class Cut:
    """Un morceau de la vidéo source (en secondes) qui sera posé sur la timeline."""

    start: float
    end: float
    words: List[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class ReelPlan:
    title: str
    hook: str
    description: str
    hashtags: List[str]
    segments: List[tuple]  # [(start, end), ...] dans l'ordre de montage
    cuts: List[Cut] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return sum(c.duration for c in self.cuts)
