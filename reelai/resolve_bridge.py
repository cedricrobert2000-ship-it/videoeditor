"""Tout ce qui parle à l'API de script de DaVinci Resolve."""

from __future__ import annotations

import os
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
