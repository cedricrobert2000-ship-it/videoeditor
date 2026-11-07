"""Tout ce qui parle à l'API de script de DaVinci Resolve."""

from __future__ import annotations

import os
import re
import sys
from typing import List, Optional, Sequence, Tuple


def get_resolve(scope: Optional[dict] = None):
    """Trouve l'objet `resolve`, depuis le menu Scripts ou depuis un terminal (Studio)."""
    scope = scope or {}
    if scope.get("resolve"):
        return scope["resolve"]
    if scope.get("app"):
        try:
            return scope["app"].GetResolve()
        except Exception:
            pass
    if scope.get("bmd"):
        try:
            r = scope["bmd"].scriptapp("Resolve")
            if r:
                return r
        except Exception:
            pass

    try:
        import DaVinciResolveScript as dvr  # type: ignore
    except ImportError:
        for path in _default_module_paths():
            if os.path.isdir(path) and path not in sys.path:
                sys.path.append(path)
        try:
            import DaVinciResolveScript as dvr  # type: ignore
        except ImportError:
            return None
    return dvr.scriptapp("Resolve")


def _default_module_paths() -> List[str]:
    env = os.environ.get("RESOLVE_SCRIPT_API")
    paths = [os.path.join(env, "Modules")] if env else []
    if sys.platform.startswith("win"):
        paths.append(os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                                  "Blackmagic Design", "DaVinci Resolve", "Support",
                                  "Developer", "Scripting", "Modules"))
    elif sys.platform == "darwin":
        paths.append("/Library/Application Support/Blackmagic Design/DaVinci Resolve/"
                     "Developer/Scripting/Modules")
    else:
        paths.append("/opt/resolve/Developer/Scripting/Modules")
    return paths


class ResolveSession:
    def __init__(self, resolve):
        if resolve is None:
            raise RuntimeError(
                "Impossible de se connecter à DaVinci Resolve. Lance ReelAI depuis "
                "Workspace > Scripts > ReelAI dans Resolve."
            )
        self.resolve = resolve
        self.project = resolve.GetProjectManager().GetCurrentProject()
        if not self.project:
            raise RuntimeError("Aucun projet ouvert dans DaVinci Resolve.")
        self.media_pool = self.project.GetMediaPool()

    # ------------------------------------------------------------------ source
    def find_source_clip(self):
        """Clip sélectionné dans le Media Pool, sinon le 1er clip de la timeline courante."""
        selected = []
        if hasattr(self.media_pool, "GetSelectedClips"):
            selected = self.media_pool.GetSelectedClips() or []
            if isinstance(selected, dict):
                selected = list(selected.values())
        for item in selected:
            if _is_video(item):
                return item

        timeline = self.project.GetCurrentTimeline()
        if timeline:
            current = timeline.GetCurrentVideoItem() if hasattr(timeline, "GetCurrentVideoItem") else None
            candidates = [current] if current else []
            candidates += timeline.GetItemListInTrack("video", 1) or []
            for ti in candidates:
                mpi = ti.GetMediaPoolItem() if ti else None
                if mpi and _is_video(mpi):
                    return mpi
        raise RuntimeError(
            "Sélectionne une vidéo dans le Media Pool (ou ouvre une timeline qui en contient une)."
        )

    @staticmethod
    def clip_info(item) -> Tuple[str, float, str]:
        path = item.GetClipProperty("File Path")
        if not path or not os.path.exists(path):
            raise RuntimeError(f"Fichier source introuvable sur le disque : {path!r}")
        fps = _parse_fps(item.GetClipProperty("FPS"))
        return path, fps, item.GetName()

    # ---------------------------------------------------------------- timeline
    def _bin(self, name: str = "ReelAI"):
        root = self.media_pool.GetRootFolder()
        for sub in root.GetSubFolderList() or []:
            if sub.GetName() == name:
                return sub
        return self.media_pool.AddSubFolder(root, name) or root

    def _unique_timeline_name(self, base: str) -> str:
        existing = set()
        for i in range(1, (self.project.GetTimelineCount() or 0) + 1):
            tl = self.project.GetTimelineByIndex(i)
            if tl:
                existing.add(tl.GetName())
        name, n = base, 2
        while name in existing:
            name = f"{base} ({n})"
            n += 1
        return name

    def build_timeline(
        self,
        name: str,
        source_item,
        frame_ranges: Sequence[Tuple[int, int]],
        vertical: bool = True,
        width: int = 1080,
        height: int = 1920,
        log=print,
    ):
        self.media_pool.SetCurrentFolder(self._bin())
        timeline = self.media_pool.CreateEmptyTimeline(self._unique_timeline_name(name))
        if not timeline:
            raise RuntimeError("Resolve n'a pas pu créer la timeline.")
        self.project.SetCurrentTimeline(timeline)

        if vertical:
            ok = timeline.SetSetting("useCustomSettings", "1")
            ok = timeline.SetSetting("timelineResolutionWidth", str(width)) and ok
            ok = timeline.SetSetting("timelineResolutionHeight", str(height)) and ok
            # Remplit le cadre 9:16 en recadrant au centre l'image 16:9.
            timeline.SetSetting("timelineInputResMismatchBehavior", "scaleToCrop")
            if not ok:
                log("Attention : format vertical non appliqué (règle-le dans les paramètres de la timeline).")

        clip_infos = [
            {"mediaPoolItem": source_item, "startFrame": a, "endFrame": b - 1}
            for a, b in frame_ranges
        ]
        appended = self.media_pool.AppendToTimeline(clip_infos)
        if not appended:
            raise RuntimeError("Resolve a refusé d'ajouter les coupes sur la timeline.")
        return timeline

    def add_subtitles(self, timeline, srt_path: str) -> bool:
        """Importe le SRT et le pose sur la piste de sous-titres. Renvoie False si échec."""
        self.project.SetCurrentTimeline(timeline)
        items = self.media_pool.ImportMedia([srt_path]) or []
        if not items:
            return False
        try:
            return bool(self.media_pool.AppendToTimeline(items))
        except Exception:
            return False

    @staticmethod
    def add_marker(timeline, name: str, note: str) -> None:
        try:
            timeline.AddMarker(0, "Blue", name[:60], note, 1)
        except Exception:
            pass

    # ------------------------------------------------------------------ motion
    @staticmethod
    def timeline_fps(timeline) -> float:
        return _parse_fps(timeline.GetSetting("timelineFrameRate"))

    def playhead_frame(self, timeline) -> int:
        """Position de la tête de lecture en frames absolues (comme GetStart())."""
        tc = timeline.GetCurrentTimecode() or ""
        parts = [int(p) for p in re.split(r"[:;.]", tc) if p.isdigit()]
        if len(parts) != 4:
            return timeline.GetStartFrame()
        h, m, s, f = parts
        nominal = int(round(self.timeline_fps(timeline)))
        return ((h * 3600 + m * 60 + s) * nominal) + f

    @staticmethod
    def _subtitle_items(timeline):
        try:
            if (timeline.GetTrackCount("subtitle") or 0) < 1:
                return []
            return timeline.GetItemListInTrack("subtitle", 1) or []
        except Exception:
            return []

    def subtitle_at_playhead(self, timeline) -> str:
        frame = self.playhead_frame(timeline)
        for item in self._subtitle_items(timeline):
            if item.GetStart() <= frame < item.GetEnd():
                return item.GetName() or ""
        return ""

    def reel_context(self, timeline) -> str:
        notes = []
        try:
            for marker in (timeline.GetMarkers() or {}).values():
                notes.append(f"{marker.get('name', '')}: {marker.get('note', '')}")
        except Exception:
            pass
        words = " ".join(i.GetName() or "" for i in self._subtitle_items(timeline))
        if words:
            notes.append("Transcript: " + words[:3000])
        return "\n".join(notes)

    def insert_overlay(self, timeline, media_path: str, record_frame: int, track: int = 2):
        self.project.SetCurrentTimeline(timeline)
        self.media_pool.SetCurrentFolder(self._bin())
        items = self.media_pool.ImportMedia([media_path]) or []
        if not items:
            raise RuntimeError(f"Resolve n'a pas pu importer {media_path}")
        item = items[0]
        while (timeline.GetTrackCount("video") or 0) < track:
            timeline.AddTrack("video")
        try:
            frames = int(item.GetClipProperty("Frames") or 0)
        except ValueError:
            frames = 0
        info = {"mediaPoolItem": item, "startFrame": 0, "trackIndex": track,
                "recordFrame": record_frame, "mediaType": 1}
        if frames > 0:
            info["endFrame"] = frames - 1
        if not self.media_pool.AppendToTimeline([info]):
            raise RuntimeError("Resolve a refusé de poser le motion sur la timeline.")

    def insert_title(self, timeline, text: str, record_frame: int, track: int = 3,
                     seconds: float = 5.0, rgb=(1.0, 1.0, 1.0)) -> bool:
        """Ajoute un titre Text+ net (typo parfaite) au-dessus du motion."""
        try:
            while (timeline.GetTrackCount("video") or 0) < track:
                timeline.AddTrack("video")
            timeline.SetCurrentTimecode(self._frame_to_tc(timeline, record_frame))
            item = timeline.InsertFusionTitleIntoTimeline("Text+")
            if not item:
                return False
            comp = item.GetFusionCompByIndex(1)
            tools = list((comp.GetToolList(False, "TextPlus") or {}).values())
            if not tools:
                return False
            tool = tools[0]
            tool.SetInput("StyledText", text)
            tool.SetInput("Size", 0.09)
            for name, value in zip(("Red1", "Green1", "Blue1"), rgb):
                tool.SetInput(name, value)
            return True
        except Exception:
            return False

    def _frame_to_tc(self, timeline, frame: int) -> str:
        nominal = int(round(self.timeline_fps(timeline)))
        s, f = divmod(frame, nominal)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"

    # ------------------------------------------------------------------ render
    def queue_render(self, timeline, output_dir: str, name: str) -> Optional[str]:
        self.project.SetCurrentTimeline(timeline)
        self.project.SetCurrentRenderFormatAndCodec("mp4", "H264")
        self.project.SetRenderSettings(
            {"SelectAllFrames": True, "TargetDir": output_dir, "CustomName": name}
        )
        return self.project.AddRenderJob() or None

    def start_render(self, job_ids: List[str]) -> None:
        if job_ids:
            self.project.StartRendering(job_ids, False)


def _is_video(item) -> bool:
    try:
        kind = (item.GetClipProperty("Type") or "").lower()
    except Exception:
        return False
    return "video" in kind


def _parse_fps(value) -> float:
    try:
        fps = float(str(value).replace(",", ".").split()[0])
    except (ValueError, IndexError):
        fps = 0.0
    return fps if fps > 0 else 25.0
