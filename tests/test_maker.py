import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from maker import pipeline, render, sources, subs, voice
from maker.config import Config

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def tone(path, seconds=4):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
                    path], check=True)
    return path


class SubsTests(unittest.TestCase):
    def test_even_timing_covers_duration(self):
        words = subs.even_timing("GTA six is finally here", 5.0)
        self.assertEqual(len(words), 5)
        self.assertAlmostEqual(words[-1]["end"], 5.0, places=5)

    def test_groups_break_on_punctuation(self):
        words = [{"word": w, "start": i, "end": i + 1} for i, w in enumerate("Big news. Rockstar revealed the cast".split())]
        groups = subs.group_words(words)
        self.assertEqual([len(g) for g in groups], [2, 3, 1])

    def test_ass_has_all_layers_and_highlight(self):
        ass = subs.build_ass(6, subs.even_timing("one two three four", 4), hook="The {hook}", credit="Source: IGN",
                             banner="GTA 6 News")
        self.assertIn("Style: Caption", ass)
        self.assertIn(",Banner,,0,0,0,,GTA 6 NEWS", ass)
        self.assertIn("THE (HOOK)", ass)  # braces would break ASS
        self.assertIn(subs.YELLOW + "ONE" + subs.WHITE, ass)
        self.assertEqual(ass.count(",Caption,"), 4)

    def test_timestamps(self):
        self.assertEqual(subs.ts(65.5), "0:01:05.50")


class PickTests(unittest.TestCase):
    def test_pick_prefers_new_info_and_filters_streamers(self):
        items = [
            {"id": "a", "kind": "news", "score": 70, "new_info": 0, "title": "old"},
            {"id": "b", "kind": "news", "score": 66, "new_info": 1, "title": "fresh"},
            {"id": "c", "kind": "news", "score": 40, "new_info": 1, "title": "weak"},
            {"id": "d", "kind": "clip", "score": 90, "author": "xQc", "title": "x", "metric": 9},
            {"id": "e", "kind": "clip", "score": 80, "author": "Lirik", "title": "l", "metric": 5},
        ]
        cfg = Config(news_per_run=1, clips_per_run=2, clip_streamers=["lirik"])
        news, clips = pipeline.pick(items, cfg)
        self.assertEqual([n["id"] for n in news], ["b"])
        self.assertEqual([c["id"] for c in clips], ["e"])

    def test_sidecar_credits_source(self):
        meta = pipeline.sidecar({"title": "T", "caption": "C", "hashtags": ["#gta6"]},
                                {"kind": "clip", "author": "Lirik", "url": "https://clips.twitch.tv/x", "id": "1"})
        self.assertIn("full credit to the streamer", meta["description"])
        self.assertEqual(meta["youtube_title"], "T")


class ArticleTests(unittest.TestCase):
    def test_article_facts(self):
        page = """<html><head><meta property="og:image" content="https://img/x.jpg">
        <meta name="description" content="Rockstar revealed the cast &amp; more."></head><body>
        <nav><p>Menu menu menu menu menu menu menu menu menu menu menu menu menu menu</p></nav>
        <p>Jason is played by an actor whose name Rockstar confirmed today in a long post.</p>
        <p>Short.</p><p>Sign up to our newsletter for more GTA news and lots of other things to read.</p></body></html>"""
        facts, image = sources.article_facts(page)
        self.assertEqual(image, "https://img/x.jpg")
        self.assertTrue(facts.startswith("Rockstar revealed the cast & more."))
        self.assertIn("Jason is played", facts)
        self.assertNotIn("Menu", facts)
        self.assertNotIn("newsletter", facts)


class VoiceTests(unittest.TestCase):
    def test_voicestudio_request_and_fallback(self):
        cfg = Config(voicestudio_url="http://vs:3900", voicestudio_key="k", voicestudio_voice="Vinny")
        scout = mock.Mock()
        scout.tts.return_value = b"backup-mp3"
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "v.mp3")
            ok = mock.Mock(ok=True, content=b"mp3!", headers={"Content-Type": "audio/mpeg"})
            with mock.patch("maker.voice.requests.post", return_value=ok) as post:
                path, used = voice.speak(cfg, scout, "hello", dest, log=lambda *_: None)
            body = post.call_args.kwargs["json"]
            self.assertEqual(post.call_args.args[0], "http://vs:3900/v1/audio/speech")
            self.assertEqual((body["voice"], body["input"], body["response_format"]), ("Vinny", "hello", "mp3"))
            self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer k")
            self.assertEqual(used, "VoiceStudio")
            bad = mock.Mock(ok=False, status_code=500, text="engine not installed", content=b"", headers={})
            with mock.patch("maker.voice.requests.post", return_value=bad):
                path, used = voice.speak(cfg, scout, "hello", dest, log=lambda *_: None)
            self.assertEqual(used, "Cloudflare Aura (backup)")
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"backup-mp3")


class FakeScout:
    def __init__(self):
        self.marked = []

    def write(self, payload):
        return {"hook": "Cast revealed", "voiceover": "Rockstar revealed the cast. Follow for daily GTA 6 news.",
                "title": "GTA 6 cast revealed", "caption": "Big news", "hashtags": ["#gta6"], "safe": True}

    def tts(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            with open(tone(os.path.join(tmp, "t.mp3"), 3), "rb") as f:
                return f.read()

    def transcribe(self, path):
        return {"text": "x", "words": [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4}
                                        for i, w in enumerate("Rockstar revealed the cast today".split())]}

    def mark(self, item_id, status):
        self.marked.append((item_id, status))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class EndToEndTests(unittest.TestCase):
    def test_news_short_lands_in_out_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(out_dir=os.path.join(tmp, "out"), use_article_image=False)
            outbox = pipeline.Outbox.__new__(pipeline.Outbox)
            outbox.cfg, outbox.log, outbox.drive = cfg, (lambda *_: None), None
            os.makedirs(cfg.out_dir)
            scout = FakeScout()
            item = {"id": "abc", "kind": "news", "title": "Cast list", "author": "Eurogamer", "url": "https://e/x"}
            with mock.patch("maker.sources.fetch_article", return_value=("Rockstar revealed the cast.", "")):
                res = pipeline.make_news(cfg, scout, outbox, item, log=lambda *_: None)
            self.assertEqual(res["status"], "made")
            self.assertEqual(res["voice"], "Cloudflare Aura (backup)")
            video = os.path.join(cfg.out_dir, res["file"] + ".mp4")
            with open(os.path.join(cfg.out_dir, res["file"] + ".json")) as f:
                meta = json.load(f)
            self.assertGreater(render.duration(video), 3)
            self.assertIn("Source: Eurogamer", meta["description"])
            self.assertEqual(scout.marked, [("abc", "used")])

    def test_unsafe_story_is_skipped(self):
        scout = FakeScout()
        scout.write = lambda payload: {"safe": False}
        cfg = Config()
        with mock.patch("maker.sources.fetch_article", return_value=("", "")):
            res = pipeline.make_news(cfg, scout, None, {"id": "z", "title": "t", "url": "u"}, log=lambda *_: None)
        self.assertTrue(res["status"].startswith("skipped"))
        self.assertEqual(scout.marked, [("z", "skip")])

    def test_clip_short(self):
        with tempfile.TemporaryDirectory() as tmp:
            clip = os.path.join(tmp, "clip.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:d=3:r=30",
                            "-f", "lavfi", "-i", "sine=duration=3", "-shortest", "-c:v", "libx264", "-c:a", "aac", clip],
                           check=True)
            cfg = Config(out_dir=os.path.join(tmp, "out"))
            outbox = pipeline.Outbox.__new__(pipeline.Outbox)
            outbox.cfg, outbox.log, outbox.drive = cfg, (lambda *_: None), None
            os.makedirs(cfg.out_dir)
            scout = FakeScout()
            item = {"id": "c1", "kind": "clip", "title": "LMAO", "author": "Lirik", "url": "https://clips.twitch.tv/x"}
            with mock.patch("maker.sources.twitch_clip", return_value=clip):
                res = pipeline.make_clip(cfg, scout, outbox, item, log=lambda *_: None)
            self.assertEqual(res["status"], "made")
            out = os.path.join(cfg.out_dir, res["file"] + ".mp4")
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                                    "stream=width,height", "-of", "csv=p=0", out], capture_output=True, text=True)
            self.assertEqual(probe.stdout.strip(), "1080,1920")


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class SplitModeTests(unittest.TestCase):
    """plan -> voices -> render, as the GitHub workflow runs it."""

    def test_plan_voices_render(self):
        items = [{"id": "n1", "kind": "news", "score": 80, "new_info": 1, "title": "Cast", "author": "IGN", "url": "https://i/x"},
                 {"id": "n2", "kind": "news", "score": 79, "new_info": 1, "title": "Bad", "author": "IGN", "url": "https://i/y"}]
        scout = FakeScout()
        scout.items = lambda: items
        real_write = scout.write
        scout.write = lambda payload: {"safe": False} if payload["title"] == "Bad" else real_write(payload)
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(news_per_run=2, clips_per_run=0, out_dir=os.path.join(tmp, "out"), use_article_image=False,
                         voicestudio_url="http://vs")
            with mock.patch("maker.pipeline.Scout", return_value=scout), \
                    mock.patch("maker.sources.fetch_article", return_value=("facts", "")):
                planned = pipeline.plan(cfg, log=lambda *_: None)
            self.assertEqual([e["item"]["id"] for e in planned["news"]], ["n1"])
            self.assertIn(("n2", "skip"), scout.marked)
            planned = json.loads(json.dumps(planned))  # survives the trip through an artifact

            voices = os.path.join(tmp, "voices")
            def fake_vs(cfg_, text, dest):
                return tone(dest, 3)
            with mock.patch("maker.voice.voicestudio", side_effect=fake_vs):
                self.assertEqual(pipeline.record_voices(cfg, planned, voices, log=lambda *_: None), 1)
            self.assertTrue(os.path.exists(os.path.join(voices, "n1.mp3")))

            with mock.patch("maker.pipeline.Scout", return_value=scout), \
                    mock.patch("maker.pipeline.Outbox") as ob:
                ob.return_value.deliver.return_value = "GitHub run files"
                ob.return_value.broll.return_value = None
                results = pipeline.render_plan(cfg, planned, voices, log=lambda *_: None)
            self.assertEqual(results[0]["status"], "made")
            self.assertEqual(results[0]["voice"], "VoiceStudio")

    def test_render_without_voices_uses_backup(self):
        scout = FakeScout()
        planned = {"news": [{"item": {"id": "n9", "title": "T", "author": "VGC", "url": "u"},
                             "script": {"hook": "h", "voiceover": "Hello there.", "title": "T", "safe": True}}],
                   "clips": []}
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(out_dir=os.path.join(tmp, "out"), use_article_image=False)
            with mock.patch("maker.pipeline.Scout", return_value=scout), mock.patch("maker.pipeline.Outbox") as ob:
                ob.return_value.deliver.return_value = "GitHub run files"
                ob.return_value.broll.return_value = None
                results = pipeline.render_plan(cfg, planned, os.path.join(tmp, "no-voices"), log=lambda *_: None)
        self.assertEqual(results[0]["voice"], "Cloudflare Aura (backup)")


if __name__ == "__main__":
    unittest.main()
