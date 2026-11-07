import io
import json
import os
from types import SimpleNamespace

import pytest

from reelai import pipeline
from reelai.config import Settings
from reelai.cuts import build_cuts, remap_words, to_frames
from reelai.editor_ai import build_user_prompt, parse_response, plan_reels
from reelai.models import Segment, Transcript, Word
from reelai.resolve_bridge import ResolveSession
from reelai.subtitles import chunk_words, to_srt
from reelai.backend import LocalBackend, SubprocessBackend


def make_transcript():
    words = [
        Word(0.0, 0.4, "Salut"), Word(0.5, 0.9, "tout"), Word(1.0, 1.4, "le"), Word(1.5, 2.0, "monde."),
        Word(4.0, 4.3, "euh"), Word(4.5, 5.0, "Voici"), Word(5.1, 5.5, "mon"), Word(5.6, 6.2, "secret."),
        Word(10.0, 10.5, "Fin"), Word(10.6, 11.0, "ici."),
    ]
    segs = [
        Segment(0.0, 2.0, "Salut tout le monde.", words[:4]),
        Segment(4.0, 6.2, "euh Voici mon secret.", words[4:8]),
        Segment(10.0, 11.0, "Fin ici.", words[8:]),
    ]
    return Transcript(segs, "fr", 12.0)


# ----------------------------------------------------------------- cuts
def test_silence_split_and_fillers():
    t = make_transcript()
    cuts = build_cuts([(0.0, 6.2)], t.words, max_silence=0.45, padding=0.05, fillers=["euh"])
    assert len(cuts) == 2  # blanc de 2 s coupé
    assert cuts[0].start == pytest.approx(0.0) and cuts[0].end == pytest.approx(2.05)
    assert [w.text for w in cuts[1].words] == ["Voici", "mon", "secret."]  # « euh » retiré
    assert cuts[1].start == pytest.approx(4.45)


def test_no_silence_removal_keeps_one_cut():
    t = make_transcript()
    cuts = build_cuts([(0.0, 6.2)], t.words, remove_silences=False)
    assert len(cuts) == 1


def test_overlapping_padding_is_split():
    words = [Word(0.0, 1.0, "a"), Word(1.5, 2.0, "b")]
    cuts = build_cuts([(0, 2)], words, max_silence=0.3, padding=0.4)
    assert len(cuts) == 2 and cuts[0].end == cuts[1].start == pytest.approx(1.25)


def test_frames_and_remap():
    t = make_transcript()
    cuts = build_cuts([(10.0, 11.0), (0.0, 2.0)], t.words, padding=0.0)  # hook déplacé en premier
    assert to_frames(cuts, 25) == [(250, 275), (0, 50)]
    remapped = remap_words(cuts, 25)
    assert remapped[0].text == "Fin" and remapped[0].start == pytest.approx(0.0)
    assert remapped[2].text == "Salut" and remapped[2].start == pytest.approx(1.0)


# ------------------------------------------------------------ subtitles
def test_subtitle_chunks_and_srt():
    words = [Word(0, 0.3, "Un"), Word(0.3, 0.6, "deux"), Word(0.6, 0.9, "trois"),
             Word(0.9, 1.2, "quatre."), Word(1.3, 1.6, "Cinq")]
    chunks = chunk_words(words, max_words=3)
    assert [c[2] for c in chunks] == ["Un deux trois", "quatre.", "Cinq"]
    assert chunks[0][1] == pytest.approx(0.9)  # reste affiché jusqu'au suivant
    srt = to_srt(chunks, uppercase=True)
    assert srt.startswith("1\n00:00:00,000 --> 00:00:00,900\nUN DEUX TROIS\n")


# ------------------------------------------------------------- IA
def fake_client(payload):
    def create(**kwargs):
        fake_client.last_kwargs = kwargs
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(payload))])
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


PAYLOAD = {"reels": [{
    "title": "Mon secret", "hook": "Voici mon secret", "description": "Desc",
    "hashtags": ["reel", "#astuce"],
    "segments": [{"start": 4.0, "end": 6.2}, {"start": 0.0, "end": 2.0}, {"start": 20, "end": 19}],
}]}


def test_parse_response_cleans_data():
    plans = parse_response(json.dumps(PAYLOAD), 12.0)
    assert plans[0].hashtags == ["#reel", "#astuce"]
    assert plans[0].segments == [(4.0, 6.2), (0.0, 2.0)]  # segment invalide retiré, ordre gardé


def test_plan_reels_request_shape():
    client = fake_client(PAYLOAD)
    s = Settings(reel_count=2, instructions="ton drôle")
    plans = plan_reels(make_transcript(), s, log=lambda m: None, client=client)
    assert len(plans) == 1
    kw = fake_client.last_kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert "ton drôle" in kw["messages"][0]["content"]
    assert "[4.00 - 6.20] euh Voici mon secret." in build_user_prompt(make_transcript(), s)


# ---------------------------------------------------- pipeline (faux Resolve)
class FakeTI:
    def __init__(self): self.props, self.cdl = {}, None
    def SetProperty(self, k, v): self.props[k] = v; return True
    def SetCDL(self, cdl): self.cdl = cdl; return True


class FakeTimeline:
    def __init__(self, name):
        self.name, self.settings, self.markers, self.clips, self.items = name, {}, [], [], []

    def GetName(self): return self.name
    def SetSetting(self, k, v): self.settings[k] = v; return True
    def AddMarker(self, *a): self.markers.append(a); return True


class FakeItem:
    def __init__(self, path):
        self.props = {"File Path": path, "FPS": "25", "Type": "Video + Audio"}
    def GetClipProperty(self, k): return self.props.get(k)
    def GetName(self): return "source.mp4"


class FakeMediaPool:
    def __init__(self, item):
        self.item, self.timelines, self.current = item, [], None
    def GetSelectedClips(self): return [self.item]
    def GetRootFolder(self): return SimpleNamespace(GetSubFolderList=lambda: [], GetName=lambda: "root")
    def AddSubFolder(self, root, name): return SimpleNamespace(GetName=lambda: name)
    def SetCurrentFolder(self, f): return True
    def CreateEmptyTimeline(self, name):
        tl = FakeTimeline(name); self.timelines.append(tl); self.current = tl; return tl
    def AppendToTimeline(self, infos):
        self.current.clips.extend(infos)
        items = [FakeTI() for _ in infos]
        self.current.items.extend(items)
        return items
    def ImportMedia(self, paths): return [SimpleNamespace(path=p) for p in paths]


class FakeProject:
    def __init__(self, mp): self.mp, self.jobs = mp, []
    def GetMediaPool(self): return self.mp
    def GetCurrentTimeline(self): return self.mp.current
    def SetCurrentTimeline(self, tl): self.mp.current = tl; return True
    def GetTimelineCount(self): return len(self.mp.timelines)
    def GetTimelineByIndex(self, i): return self.mp.timelines[i - 1]
    def SetCurrentRenderFormatAndCodec(self, f, c): return True
    def SetRenderSettings(self, s): self.render_settings = s; return True
    def AddRenderJob(self): self.jobs.append("job%d" % len(self.jobs)); return self.jobs[-1]
    def StartRendering(self, jobs, interactive): self.started = jobs; return True


def test_full_pipeline(tmp_path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"x")
    mp = FakeMediaPool(FakeItem(str(media)))
    project = FakeProject(mp)
    resolve = SimpleNamespace(GetProjectManager=lambda: SimpleNamespace(GetCurrentProject=lambda: project))
    session = ResolveSession(resolve)

    s = Settings(render=True, output_dir=str(tmp_path / "out"), source_mode="selected")
    import reelai.transcribe as tr
    orig = tr.transcribe
    tr.transcribe = lambda *a, **k: make_transcript()
    try:
        results = pipeline.run(session, s, log=lambda m: None, backend=LocalBackend(ai_client=fake_client(PAYLOAD)))
    finally:
        tr.transcribe = orig

    assert len(results) == 1
    tl = mp.timelines[0]
    assert tl.name == "Reel 1 - Mon secret"
    assert tl.settings["timelineResolutionHeight"] == "1920"
    # coupe 1 : « Voici mon secret » sans le « euh », coupe 2 : intro
    assert [(c["startFrame"], c["endFrame"]) for c in tl.clips if isinstance(c, dict)] == [(110, 156), (0, 51)]
    srt = open(results[0].srt_path, encoding="utf-8").read()
    assert "VOICI MON SECRET." in srt and "EUH" not in srt
    assert os.path.exists(results[0].caption_path)
    assert project.started == ["job0"]


# ------------------------------------------------------------- motion
from reelai import motion as motion_mod


class FakeTool:
    def __init__(self): self.inputs = {}
    def SetInput(self, k, v): self.inputs[k] = v


class FakeTitleItem:
    def __init__(self): self.tool = FakeTool()
    def GetFusionCompByIndex(self, i):
        return SimpleNamespace(GetToolList=lambda sel, kind: {1: self.tool})


class FakeSub:
    def __init__(self, start, end, text): self.s, self.e, self.t = start, end, text
    def GetStart(self): return self.s
    def GetEnd(self): return self.e
    def GetName(self): return self.t


class MotionTimeline(FakeTimeline):
    def __init__(self):
        super().__init__("Reel 1")
        self.tracks, self.tc, self.title = 1, "01:00:02:05", None
        self.settings["timelineFrameRate"] = "25"
    def GetSetting(self, k): return self.settings.get(k)
    def GetCurrentTimecode(self): return self.tc
    def SetCurrentTimecode(self, tc): self.tc = tc; return True
    def GetStartFrame(self): return 90000
    def GetTrackCount(self, kind): return {"video": self.tracks, "subtitle": 1}[kind]
    def AddTrack(self, kind): self.tracks += 1; return True
    def GetItemListInTrack(self, kind, i): return [FakeSub(90000, 90050, "Salut"), FakeSub(90050, 90100, "MON SECRET")]
    def GetMarkers(self): return {0: {"name": "Mon secret", "note": "hook"}}
    def InsertFusionTitleIntoTimeline(self, name): self.title = FakeTitleItem(); return self.title


def test_motion_end_to_end(tmp_path):
    tl = MotionTimeline()
    mp = FakeMediaPool(FakeItem("x"))
    mp.current = tl
    mp.ImportMedia = lambda paths: [SimpleNamespace(GetClipProperty=lambda k: "125", path=paths[0])]
    project = FakeProject(mp)
    session = ResolveSession(SimpleNamespace(GetProjectManager=lambda: SimpleNamespace(GetCurrentProject=lambda: project)))

    assert session.playhead_frame(tl) == 90055
    assert session.subtitle_at_playhead(tl) == "MON SECRET"

    brief = {"concept": "Coffre-fort", "video_prompt": "A vault opening", "palette": "gold", "text_color": "#FFCC00"}
    calls = {}

    def run(session_id, prompt, on_question=None, timeout=0):
        calls["prompt"] = prompt
        return SimpleNamespace(status="completed", text="Done: https://cdn.x/a.png https://cdn.x/v.mp4",
                               asset_urls=["https://cdn.x/a.png", "https://cdn.x/v.mp4"])
    hf = SimpleNamespace(agents=SimpleNamespace(sessions=SimpleNamespace(
        create=lambda: SimpleNamespace(session_id="s1"), run=run)))

    s = Settings(output_dir=str(tmp_path), motion_style="Luxe")
    orig = motion_mod.download
    motion_mod.download = lambda url, folder, name: f"{folder}/m.mp4"
    try:
        res = motion_mod.create_motion(session, s, "Mon secret", log=lambda m: None,
                                       backend=LocalBackend(ai_client=fake_client(brief), hf_client=hf))
    finally:
        motion_mod.download = orig

    assert res.source_url == "https://cdn.x/v.mp4"
    assert "A vault opening" in calls["prompt"] and "9:16" in calls["prompt"]
    user_prompt = fake_client.last_kwargs["messages"][0]["content"]
    assert "NO text" in user_prompt and "black and gold" in user_prompt and "hook" in user_prompt
    placed = tl.clips[0]
    assert placed["trackIndex"] == 2 and placed["recordFrame"] == 90055 and placed["endFrame"] == 124
    assert tl.tracks == 3
    assert tl.title.tool.inputs["StyledText"] == "Mon secret"
    assert tl.title.tool.inputs["Red1"] == pytest.approx(1.0)
    assert tl.tc == "01:00:02:05"


# ------------------------------------------------- montage Media Pool
import sys
import numpy as np
from reelai import montage_ai


def make_video(path, seconds=4, fps=25):
    import av
    with av.open(str(path), "w") as c:
        st = c.add_stream("mpeg4", rate=fps)
        st.width, st.height, st.pix_fmt = 160, 96, "yuv420p"
        for i in range(seconds * fps):
            img = np.zeros((96, 160, 3), dtype=np.uint8)
            img[:, :, 0] = (i * 3) % 255
            for pkt in st.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                c.mux(pkt)
        for pkt in st.encode():
            c.mux(pkt)


def make_click_track(path, bpm=120, seconds=12, sr=22050):
    import av
    y = np.zeros(int(seconds * sr), dtype=np.float32)
    period = 60 / bpm
    first = 0.25
    t = first
    while t < seconds - 0.1:
        i = int(t * sr)
        y[i:i + 800] += np.sin(np.arange(800) * 2 * np.pi * 1000 / sr) * np.exp(-np.arange(800) / 150)
        t += period
    with av.open(str(path), "w") as c:
        st = c.add_stream("pcm_s16le", rate=sr, layout="mono")
        pcm = (y * 20000).astype(np.int16).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(pcm, format="s16", layout="mono")
        frame.sample_rate = sr
        for pkt in st.encode(frame):
            c.mux(pkt)
        for pkt in st.encode():
            c.mux(pkt)


def test_extract_frames(tmp_path):
    v = tmp_path / "a.mp4"
    make_video(v)
    frames = montage_ai.extract_frames(str(v), [0.5, 2.0, 3.5])
    assert all(frames) and len(frames) == 3


def test_detect_beats(tmp_path):
    m = tmp_path / "m.wav"
    make_click_track(m, bpm=120)
    info = montage_ai.detect_beats(str(m))
    assert info["bpm"] == pytest.approx(120, abs=3)
    assert info["first_beat"] % info["beat"] == pytest.approx(0.25, abs=0.05)


def test_snap_shots_on_beats():
    clips = {1: {"duration": 10.0}, 2: {"duration": 1.2}}
    shots = montage_ai.snap_shots(
        [{"clip": 1, "start": 2.0, "end": 4.3}, {"clip": 2, "start": 0.5, "end": 3.0}, {"clip": 9, "start": 0, "end": 1}],
        clips, beat=0.5, pace="Moyen")
    assert shots[0] == {"clip": 1, "start": 2.0, "end": 4.5, "subject_x": 0.5, "zoom": 1.0}  # 4,6 temps -> 5
    assert shots[1]["end"] - shots[1]["start"] == pytest.approx(1.0)  # clip court : 2 temps
    assert shots[1]["end"] <= 1.2 and len(shots) == 2


class FakeFolder:
    def __init__(self, name, clips, subs=()):
        self.name, self.clips, self.subs = name, clips, list(subs)
    def GetName(self): return self.name
    def GetClipList(self): return self.clips
    def GetSubFolderList(self): return self.subs


class PoolItem:
    def __init__(self, name, path, kind, fps="25", frames="100"):
        self.name = name
        self.props = {"File Path": path, "Type": kind, "FPS": fps, "Frames": frames}
    def GetName(self): return self.name
    def GetClipProperty(self, k): return self.props.get(k)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    import reelai.config as cfg
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / "home")
    monkeypatch.setattr(cfg, "CACHE_DIR", tmp_path / "home" / "cache")


def test_media_pool_montage(tmp_path):
    v1, v2, music = tmp_path / "v1.mp4", tmp_path / "v2.mp4", tmp_path / "m.wav"
    make_video(v1)
    make_video(v2)
    make_click_track(music, seconds=30)
    items = [PoolItem("Plan A", str(v1), "Video + Audio", fps="50", frames="200"),
             PoolItem("Plan B", str(v2), "Video", frames="100"),
             PoolItem("Timeline 1", "", "Timeline"),
             PoolItem("Olivia", str(music), "Audio", frames="750")]
    mp = FakeMediaPool(items[0])
    mp.GetRootFolder = lambda: FakeFolder("Master", items[:2], [FakeFolder("Sons", items[2:]),
                                                                   FakeFolder("ReelAI", [PoolItem("old", str(v1), "Video")])])
    mp.AddSubFolder = lambda root, name: FakeFolder(name, [])
    project = FakeProject(mp)
    session = ResolveSession(SimpleNamespace(GetProjectManager=lambda: SimpleNamespace(GetCurrentProject=lambda: project)))
    FakeTimeline.GetSetting = lambda self, k: "25"
    FakeTimeline.GetStartFrame = lambda self: 90000

    items[0].props["Resolution"] = "3840x2160"
    payload = {"reels": [{"title": "Avant / après", "description": "Transformation", "hashtags": ["coiffure"],
                          "look": "Chaud doré", "music_choice": 1,
                          "texts": [{"shot": 5, "text": "hors plan", "position": "top"},
                                    {"shot": 0, "text": "Avant", "position": "top"}],
                          "shots": [{"clip": 2, "start": 0.0, "end": 1.9, "beats": 4, "subject_x": 0.5, "zoom": 1.0},
                                    {"clip": 1, "start": 1.0, "end": 2.1, "beats": 3, "subject_x": 0.8, "zoom": 1.2}]}]}
    client = fake_client(payload)
    s = Settings(output_dir=str(tmp_path / "out"), music_name="", montage_pace="Moyen", instructions="simple",
                 montage_texts=False, target_duration=4)
    results = pipeline.run(session, s, log=lambda m: None, backend=LocalBackend(ai_client=client))

    content = fake_client.last_kwargs["messages"][0]["content"]
    assert sum(1 for b in content if b["type"] == "image") == 2  # une planche par clip
    assert "simple" in content[0]["text"] and "BPM" in content[0]["text"] and "1 = B" in content[0]["text"]
    tl = mp.timelines[0]
    video = [c for c in tl.clips if c.get("mediaType") == 1]
    audio = [c for c in tl.clips if c.get("mediaType") == 2]
    # plan B : 2 s (4 temps) à 25 i/s ; plan A : 3 temps allongés à 4 pour finir sur une mesure, à 50 i/s
    assert [(c["startFrame"], c["endFrame"]) for c in video] == [(0, 49), (50, 149)]
    info = montage_ai.detect_beats(str(music))
    chosen = montage_ai.music_candidates(info, s.target_duration)[1]["start"]
    assert audio[0]["trackIndex"] == 1 and audio[0]["recordFrame"] == 90000
    assert audio[0]["startFrame"] == round(chosen * 25)
    # textes proposés mais non posés (case décochée), plan sauvegardé pour l'étape suivante
    saved = pipeline.load_plan(tl.GetName())
    assert saved["texts"] == [{"shot": 0, "text": "Avant", "position": "top"}]
    assert not [c for c in tl.clips if c.get("trackIndex") == 3]
    assert results[0].plan.hashtags == ["#coiffure"]
    # plan A (4K, sujet à droite, zoom 1.2) : décalé vers la gauche, borné au bord de l'image
    ta = tl.items[1]
    scaled_w = 3840 * (1920 / 2160) * 1.2
    assert ta.props["ZoomX"] == pytest.approx(1.2)
    assert ta.props["Pan"] == pytest.approx(-0.3 * scaled_w)
    assert ta.cdl["Saturation"] == "1.08"
    # plan B : résolution inconnue -> 1920x1080 par défaut, centré
    assert tl.items[0].props["Pan"] == pytest.approx(0.0)
    assert os.path.exists(results[0].caption_path)


def test_subprocess_backend_reports_errors():
    b = SubprocessBackend(sys.executable)
    with pytest.raises(RuntimeError, match="Tâche inconnue"):
        b.run("nope", {}, Settings(), log=lambda m: None)


def test_worker_command_forces_arm64_on_apple_silicon(monkeypatch):
    from reelai import backend as be
    monkeypatch.setattr(be, "_apple_silicon", lambda: True)
    monkeypatch.setattr(be.os.path, "exists", lambda p: True)
    assert be.worker_command("/py")[:3] == ["/usr/bin/arch", "-arm64", "/py"]
    monkeypatch.setattr(be, "_apple_silicon", lambda: False)
    assert be.worker_command("/py") == ["/py", "-m", "reelai.worker"]


def test_snap_uses_beats_and_varies_lengths():
    clips = {1: {"duration": 20.0}}
    shots = montage_ai.snap_shots(
        [{"clip": 1, "start": 0, "end": 1, "beats": 8, "subject_x": 2, "zoom": 3},
         {"clip": 1, "start": 5, "end": 6, "beats": 2, "subject_x": 0.2, "zoom": 1.1}],
        clips, beat=0.5, pace="Rapide")
    assert [round(s["end"] - s["start"], 2) for s in shots] == [4.0, 1.0]
    assert shots[0]["subject_x"] == 1.0 and shots[0]["zoom"] == 1.3  # bornés


def test_clean_texts():
    t = montage_ai.clean_texts([{"shot": 3, "text": " Fin "}, {"shot": 0, "text": "Hook"}, {"shot": 0, "text": "x"},
                                {"shot": 9, "text": "hors"}, {"shot": 1, "text": ""}], n_shots=4)
    assert t == [{"shot": 0, "text": "Hook", "position": "bottom"}, {"shot": 3, "text": "Fin", "position": "bottom"}]


class TextTimeline(MotionTimeline):
    def __init__(self):
        super().__init__()
        self.titles = []
    def InsertFusionTitleIntoTimeline(self, name):
        item = FakeTitleItem()
        self.titles.append((self.tc, item))
        return item


class AnimTool(FakeTool):
    def __init__(self):
        super().__init__(); self.keys, self.mods = [], []
    def AddModifier(self, name, kind): self.mods.append(name); return True
    def SetInput(self, k, v, t=None):
        if t is None: self.inputs[k] = v
        else: self.keys.append((k, t, v))


def make_text_session(tmp_path):
    tl = TextTimeline()
    mp = FakeMediaPool(FakeItem("x"))
    mp.current = tl
    imported = []
    def import_media(paths):
        imported.extend(paths)
        return [SimpleNamespace(GetClipProperty=lambda k: {"Frames": "250", "FPS": "50"}.get(k), path=paths[0])]
    mp.ImportMedia = import_media
    session = ResolveSession(SimpleNamespace(GetProjectManager=lambda: SimpleNamespace(
        GetCurrentProject=lambda: FakeProject(mp))))
    return session, tl, imported


def test_shot_texts_higgsfield_with_fallback(tmp_path):
    v = tmp_path / "v.mp4"
    make_video(v, seconds=4)
    session, tl, imported = make_text_session(tmp_path)
    shots = [{"clip": 1, "start": 0.0, "end": 2.0, "subject_x": 0.3},
             {"clip": 1, "start": 2.0, "end": 3.5, "subject_x": 0.5}]
    positions = {0: (90000, 50), 1: (90050, 38)}
    texts = [{"shot": 0, "text": "Ta coupe, ta signature"}, {"shot": 1, "text": "Réserve"}]
    clips = {1: str(v)}

    uploads, prompts = [], []
    def run(sid, prompt, on_question=None, timeout=0):
        prompts.append(prompt)
        if "Réserve" in prompt:
            return SimpleNamespace(status="failed", text="nope", asset_urls=[])
        return SimpleNamespace(status="completed", text="", asset_urls=["https://cdn/x.mp4"])
    hf = SimpleNamespace(agents=SimpleNamespace(
        media=SimpleNamespace(upload=lambda data, extension, type: uploads.append((len(data), extension)) or "https://up/img.jpg"),
        sessions=SimpleNamespace(create=lambda: SimpleNamespace(session_id="s"), run=run)))

    orig = motion_mod.download
    motion_mod.download = lambda url, folder, name: f"{folder}/{name}.mp4"
    try:
        s = Settings(higgsfield_key="k:s", text_animation="higgsfield")
        warnings = pipeline.add_shot_texts(session, tl, texts, shots, positions, clips, s, str(tmp_path),
                                           LocalBackend(hf_client=hf), log=lambda m: None, look="Chaud doré",
                                           mode="higgsfield")
    finally:
        motion_mod.download = orig

    assert warnings == []
    assert all(ext == "jpeg" and n > 1000 for n, ext in uploads)
    assert any('"Ta coupe, ta signature"' in p and "golden" in p and "https://up/img.jpg" in p for p in prompts)
    # plan 0 : clip Higgsfield posé sur V2 et coupé à la durée du plan (50 frames à 25 -> 100 à 50 i/s)
    placed = [c for c in tl.clips if c.get("trackIndex") == 2]
    assert placed[0]["recordFrame"] == 90000 and placed[0]["endFrame"] == 99
    # plan 1 : Higgsfield a échoué -> texte animé rendu par ReelAI, posé sur V3 à 90050
    fallback = [c for c in tl.clips if c.get("trackIndex") == 3]
    assert len(fallback) == 1 and fallback[0]["recordFrame"] == 90050 and fallback[0]["endFrame"] == 75
    assert imported[-1].endswith(".mov") and os.path.exists(imported[-1])


def test_resolve_text_animation_keyframes(tmp_path):
    session, tl, _ = make_text_session(tmp_path)
    item = FakeTitleItem()
    item.tool = AnimTool()
    tl.InsertFusionTitleIntoTimeline = lambda name: item
    assert session.insert_title(tl, "Hello", 90000, animate=True, duration_frames=50)
    opacity = [(t, v) for k, t, v in item.tool.keys if k == "Opacity1"]
    assert opacity[0] == (0, 0.0) and opacity[-1] == (49, 0.0) and max(v for _, v in opacity) == 1.0
    assert "Size" in item.tool.mods and item.tool.inputs["Center"] == {1: 0.5, 2: 0.3}


def test_vertical_frame_is_9_16(tmp_path):
    from PIL import Image
    v = tmp_path / "v.mp4"
    make_video(v)
    data = montage_ai.vertical_frame(str(v), 1.0, subject_x=0.9)
    assert Image.open(io.BytesIO(data)).size == (1080, 1920)


def test_music_candidates_prefers_loud_section_on_bars():
    music = {"first_beat": 0.2, "bar": 2.0, "bars": [0.2] * 8 + [0.9] * 16 + [0.3] * 8}
    cands = montage_ai.music_candidates(music, target=16)
    starts = [c["start"] for c in cands]
    assert 0.2 + 8 * 2.0 in starts  # début de la partie énergique (montée)
    assert any("début de section" in c["label"] for c in cands)
    assert all(round((x - 0.2) / 2.0, 6).is_integer() for x in starts)  # toujours sur une mesure


def test_fit_to_bars():
    clips = {1: {"duration": 10.0}}
    shots = [{"clip": 1, "start": 0, "end": 1.0}, {"clip": 1, "start": 2, "end": 3.0}]  # 2 + 2 temps
    assert montage_ai.fit_to_bars(shots, clips, 0.5) == shots
    shots[1]["end"] = 3.5  # 2 + 3 temps -> le dernier plan passe à 6 temps
    assert montage_ai.fit_to_bars(shots, clips, 0.5)[-1]["end"] == 5.0  # 5 temps -> 8 temps


def test_contact_sheet_and_cache(tmp_path):
    v = tmp_path / "v.mp4"
    make_video(v, seconds=6)
    sheet = montage_ai.contact_sheet(str(v), 6.0)
    assert sheet["frames"] and all(0 <= f["t"] <= 6 for f in sheet["frames"])
    assert montage_ai.contact_sheet(str(v), 6.0) == sheet  # relu depuis le cache


def test_add_texts_after_montage(tmp_path):
    v = tmp_path / "v.mp4"
    make_video(v)
    session, tl, imported = make_text_session(tmp_path)
    tl.GetName = lambda: "Reel 1 - Test"
    pipeline.save_plan("Reel 1 - Test", {
        "texts": [{"shot": 1, "text": "Réserve ton rendez-vous", "position": "bottom"}],
        "shots": [{"clip": 1, "start": 0, "end": 2}, {"clip": 1, "start": 2, "end": 3}],
        "look": "", "out_dir": str(tmp_path / "out"),
        "positions": {"0": [90000, 50], "1": [90050, 25]}, "paths": {"1": str(v)}})
    warnings = pipeline.add_texts_to_current_timeline(session, Settings(), log=lambda m: None,
                                                      backend=LocalBackend(), mode="reelai")
    assert warnings == []
    placed = [c for c in tl.clips if c.get("trackIndex") == 3]
    assert placed[0]["recordFrame"] == 90050 and placed[0]["endFrame"] == 49  # 25 frames à 25 -> 50 à 50 i/s (faux import)
    import av
    with av.open(imported[-1]) as c:
        frames = list(c.decode(video=0))
        assert len(frames) == 25 and frames[0].format.name.startswith("yuva")
