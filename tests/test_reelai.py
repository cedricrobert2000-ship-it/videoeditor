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
class FakeTimeline:
    def __init__(self, name):
        self.name, self.settings, self.markers, self.clips = name, {}, [], []

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
        self.current.clips.extend(infos); return [object()] * len(infos)
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

    s = Settings(render=True, output_dir=str(tmp_path / "out"))
    results = pipeline.run(session, s, log=lambda m: None, ai_client=fake_client(PAYLOAD),
                           transcriber=lambda *a, **k: make_transcript())

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
