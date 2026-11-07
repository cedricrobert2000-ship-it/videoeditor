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
        if any(_clip_type(i) == "timeline" for i in selected):
            raise RuntimeError(
                "Tu as sélectionné une TIMELINE. Clique sur un CLIP VIDÉO (un fichier comme "
                "M2U00041) dans le Media Pool, puis relance."
            )

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

    # ------------------------------------------------------------ media pool
    def _walk(self, folder, skip=("ReelAI",)):
        for item in folder.GetClipList() or []:
            yield item
        for sub in folder.GetSubFolderList() or []:
            if sub.GetName() not in skip:
                yield from self._walk(sub, skip)

    def list_clips(self, kind: str = "video", min_seconds: float = 1.0) -> List[dict]:
        """Clips du Media Pool : kind="video" (plans) ou "audio" (musiques)."""
        out = []
        for item in self._walk(self.media_pool.GetRootFolder()):
            t = _clip_type(item)
            if kind == "video" and "video" not in t:
                continue
            if kind == "audio" and (t != "audio" and not t.startswith("audio")):
                continue
            path = item.GetClipProperty("File Path") or ""
            if not path or not os.path.exists(path):
                continue
            fps = _parse_fps(item.GetClipProperty("FPS"))
            try:
                frames = int(float(item.GetClipProperty("Frames") or 0))
            except ValueError:
                frames = 0
            duration = frames / fps if frames else _parse_duration(item.GetClipProperty("Duration"), fps)
            if duration < min_seconds:
                continue
            res = re.findall(r"\d+", str(item.GetClipProperty("Resolution") or ""))
            w, h = (int(res[0]), int(res[1])) if len(res) >= 2 else (1920, 1080)
            out.append({"id": len(out) + 1, "name": item.GetName(), "path": path,
                        "fps": fps, "frames": frames or int(duration * fps), "duration": round(duration, 3),
                        "width": w, "height": h, "item": item})
        return out

    def selected_audio_name(self) -> str:
        """Nom de la musique sélectionnée dans le Media Pool (ou "")."""
        try:
            selected = self.media_pool.GetSelectedClips() or []
            if isinstance(selected, dict):
                selected = list(selected.values())
            for item in selected:
                if _clip_type(item).startswith("audio"):
                    return item.GetName()
        except Exception:
            pass
        return ""

    def build_montage_timeline(self, name: str, shots: List[dict], clips_by_id: dict,
                               music: Optional[dict] = None, music_info: Optional[dict] = None,
                               vertical: bool = True, width: int = 1080, height: int = 1920, log=print,
                               look: str = "Naturel", music_start: Optional[float] = None):
        """Crée la timeline. Renvoie (timeline, positions) avec positions[index du plan] =
        (frame d'enregistrement, durée en frames de timeline)."""
        self.media_pool.SetCurrentFolder(self._bin())
        timeline = self.media_pool.CreateEmptyTimeline(self._unique_timeline_name(name))
        if not timeline:
            raise RuntimeError("Resolve n'a pas pu créer la timeline.")
        self.project.SetCurrentTimeline(timeline)
        if vertical:
            ok = timeline.SetSetting("useCustomSettings", "1")
            ok = timeline.SetSetting("timelineResolutionWidth", str(width)) and ok
            ok = timeline.SetSetting("timelineResolutionHeight", str(height)) and ok
            timeline.SetSetting("timelineInputResMismatchBehavior", "scaleToCrop")
            if not ok:
                log("Attention : format vertical non appliqué.")

        tfps = self.timeline_fps(timeline)
        infos, placed, cum = [], [], 0.0
        positions, record = {}, timeline.GetStartFrame()
        for index, s in enumerate(shots):
            clip = clips_by_id[s["clip"]]
            length = s["end"] - s["start"]
            t_frames = int(round((cum + length) * tfps)) - int(round(cum * tfps))
            cum += length
            src_start = int(round(s["start"] * clip["fps"]))
            src_len = max(1, int(round(t_frames * clip["fps"] / tfps)))
            src_end = min(src_start + src_len, clip["frames"]) - 1
            if src_end <= src_start:
                continue
            info = {"mediaPoolItem": clip["item"], "startFrame": src_start, "endFrame": src_end}
            if music:
                info["mediaType"] = 1  # image seule : la musique remplace le son
            infos.append(info)
            placed.append((s, clip))
            positions[index] = (record, t_frames)
            record += t_frames
        items = self.media_pool.AppendToTimeline(infos) if infos else None
        if not items:
            raise RuntimeError("Resolve a refusé d'ajouter les plans sur la timeline.")

        styled = 0
        for ti, (s, clip) in zip(list(items), placed):
            styled += self._style_shot(ti, s, clip, width, height, vertical, look)
        if styled:
            log(f"Recadrage, zoom et look « {look} » appliqués sur {styled} plan(s).")

        if music:
            mfps = music["fps"] or tfps
            offset = music_start if music_start is not None else (music_info or {}).get("first_beat", 0.0)
            start = int(round(offset * mfps))
            end = min(start + int(round(cum * mfps)), music["frames"]) - 1
            ok = self.media_pool.AppendToTimeline([{
                "mediaPoolItem": music["item"], "startFrame": start, "endFrame": end,
                "mediaType": 2, "trackIndex": 1, "recordFrame": timeline.GetStartFrame()}])
            if ok:
                log(f"Musique « {music['name']} » posée sur A1 à partir de {offset:.1f} s, calée sur les temps.")
            else:
                log("Musique non posée automatiquement : glisse-la sur la piste audio A1.")

        return timeline, positions

    # Étalonnages simples (CDL) appliqués au 1er nœud de chaque plan.
    LOOKS = {
        "Chaud doré": ("1.06 1.0 0.9", "0.01 0.004 -0.012", "1.0 1.0 1.02", "1.08"),
        "Film doux": ("0.94 0.94 0.95", "0.035 0.033 0.04", "1.06 1.05 1.04", "0.82"),
        "Lumineux clean": ("1.08 1.08 1.08", "0.012 0.012 0.015", "0.94 0.94 0.94", "1.05"),
        "Noir & blanc": ("1.06 1.06 1.06", "0.0 0.0 0.0", "1.12 1.12 1.12", "0.0"),
    }

    def _style_shot(self, ti, shot: dict, clip: dict, width: int, height: int,
                    vertical: bool, look: str) -> int:
        try:
            zoom = float(shot.get("zoom", 1.0))
            if vertical and clip.get("width") and clip.get("height"):
                # Image recadrée pour remplir le 9:16, puis décalée vers le sujet.
                scale = max(width / clip["width"], height / clip["height"]) * zoom
                scaled_w = clip["width"] * scale
                max_pan = max(0.0, (scaled_w - width) / 2)
                pan = (0.5 - float(shot.get("subject_x", 0.5))) * scaled_w
                ti.SetProperty("Pan", max(-max_pan, min(max_pan, pan)))
            if zoom != 1.0:
                ti.SetProperty("ZoomX", zoom)
                ti.SetProperty("ZoomY", zoom)
            if look in self.LOOKS:
                slope, offset, power, sat = self.LOOKS[look]
                ti.SetCDL({"NodeIndex": "1", "Slope": slope, "Offset": offset,
                           "Power": power, "Saturation": sat})
            return 1
        except Exception:
            return 0

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

    def insert_overlay(self, timeline, media_path: str, record_frame: int, track: int = 2,
                       max_frames: int = 0):
        """Pose un clip sur une piste au-dessus. max_frames : durée max en frames de timeline."""
        self.project.SetCurrentTimeline(timeline)
        self.media_pool.SetCurrentFolder(self._bin())
        items = self.media_pool.ImportMedia([media_path]) or []
        if not items:
            raise RuntimeError(f"Resolve n'a pas pu importer {media_path}")
        item = items[0]
        for key in ("Alpha mode", "Alpha Mode"):  # textes ReelAI : transparence (alpha droit)
            try:
                if media_path.lower().endswith(".mov") and item.SetClipProperty(key, "Straight"):
                    break
            except Exception:
                pass
        while (timeline.GetTrackCount("video") or 0) < track:
            timeline.AddTrack("video")
        try:
            frames = int(item.GetClipProperty("Frames") or 0)
        except ValueError:
            frames = 0
        info = {"mediaPoolItem": item, "startFrame": 0, "trackIndex": track,
                "recordFrame": record_frame, "mediaType": 1}
        if max_frames > 0:
            src_fps = _parse_fps(item.GetClipProperty("FPS"))
            wanted = int(round(max_frames * src_fps / self.timeline_fps(timeline)))
            frames = min(frames, wanted) if frames > 0 else wanted
        if frames > 0:
            info["endFrame"] = frames - 1
        if not self.media_pool.AppendToTimeline([info]):
            raise RuntimeError("Resolve a refusé de poser le motion sur la timeline.")

    def insert_title(self, timeline, text: str, record_frame: int, track: int = 3,
                     seconds: float = 5.0, rgb=(1.0, 1.0, 1.0), animate: bool = False,
                     duration_frames: int = 0) -> bool:
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
            if animate:
                self._animate_text(tool, duration_frames or int(seconds * self.timeline_fps(timeline)),
                                   self.timeline_fps(timeline))
            return True
        except Exception:
            return False

    @staticmethod
    def _animate_text(tool, duration: int, fps: float) -> None:
        """Animation Text+ : apparition en fondu + léger grossissement, disparition en fin de plan."""
        intro, outro = int(fps * 0.5), int(fps * 0.35)
        end = max(duration - 1, intro + outro + 1)
        keys = {
            "Size": [(0, 0.075), (intro, 0.09), (end, 0.095)],
            "Opacity1": [(0, 0.0), (intro, 1.0), (end - outro, 1.0), (end, 0.0)],
        }
        for name, points in keys.items():
            try:
                tool.AddModifier(name, "BezierSpline")
                for frame, value in points:
                    tool.SetInput(name, value, frame)
            except Exception:
                pass
        try:
            tool.SetInput("Center", {1: 0.5, 2: 0.3})  # tiers bas : ne cache pas les visages
        except Exception:
            pass

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


def _clip_type(item) -> str:
    try:
        return (item.GetClipProperty("Type") or "").lower()
    except Exception:
        return ""


def _is_video(item) -> bool:
    return "video" in _clip_type(item)


def _parse_fps(value) -> float:
    try:
        fps = float(str(value).replace(",", ".").split()[0])
    except (ValueError, IndexError):
        fps = 0.0
    return fps if fps > 0 else 25.0


def _parse_duration(value, fps: float) -> float:
    """« 00:00:12:10 » -> secondes."""
    parts = [int(p) for p in re.split(r"[:;.]", str(value or "")) if p.isdigit()]
    if len(parts) != 4:
        return 0.0
    h, m, s, f = parts
    return h * 3600 + m * 60 + s + f / max(fps, 1)
