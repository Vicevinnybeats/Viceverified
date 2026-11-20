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



class ClipFallbackTests(unittest.TestCase):
    def test_next_clip_is_used_when_one_is_unsafe(self):
        planned = {"news": [], "clips_wanted": 1, "clips": [
            {"item": {"id": "c1", "title": "unsafe", "url": "u1"}},
            {"item": {"id": "c2", "title": "good", "url": "u2"}},
            {"item": {"id": "c3", "title": "extra", "url": "u3"}}]}
        made = []

        def fake_clip(cfg, scout, outbox, item, log):
            made.append(item["id"])
            return {"status": "skipped (not safe for Shorts)"} if item["id"] == "c1" else {"status": "made"}

        with mock.patch("maker.pipeline.Scout"), mock.patch("maker.pipeline.Outbox"), \
                mock.patch("maker.pipeline.make_clip", side_effect=fake_clip):
            results = pipeline.render_plan(Config(), planned, "nowhere", log=lambda *_: None)
        self.assertEqual(made, ["c1", "c2"])
        self.assertEqual([r["status"] for r in results], ["skipped (not safe for Shorts)", "made"])


class PhoneMessageTests(unittest.TestCase):
    def test_phone_text_lists_shorts_and_link(self):
        from maker.__main__ import phone_text
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "9", "GITHUB_REPOSITORY": "o/r"}):
            text = phone_text([{"kind": "news", "status": "made", "title": "T", "hook": "Cast revealed"},
                               {"kind": "clip", "status": "skipped (not safe for Shorts)", "title": "C"}])
        self.assertIn("1 new Short\n", text)
        self.assertIn("✅ news: Cast revealed", text)
        self.assertIn("⏭️ clip: C", text)
        self.assertIn("https://github.com/o/r/actions/runs/9", text)


class TelegramVideoTests(unittest.TestCase):
    def test_made_shorts_are_sent_as_videos(self):
        from maker import __main__ as cli
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(out_dir=tmp)
            with open(os.path.join(tmp, "n1.json"), "w") as f:
                json.dump({"youtube_title": "Cast revealed", "description": "Source: IGN", "hashtags": ["#gta6"]}, f)
            scout = mock.Mock()
            with mock.patch.object(cli, "Scout", return_value=scout):
                cli.notify_phone(cfg, [{"kind": "news", "status": "made", "file": "n1", "title": "T", "hook": "Big news"},
                                       {"kind": "clip", "status": "skipped (not safe for Shorts)", "title": "C"}])
        scout.notify.assert_called_once()
        path, caption = scout.send_video.call_args.args
        self.assertTrue(path.endswith("n1.mp4"))
        self.assertIn("🎬 Big news", caption)
        self.assertIn("#gta6", caption)
        self.assertEqual(scout.send_video.call_count, 1)


class VoiceSetupTests(unittest.TestCase):
    def test_installs_kitten_and_accepts_only_that_licence(self):
        cfg = Config(voicestudio_url="http://vs", voicestudio_key="k")
        calls = []

        def post(url, json=None, headers=None, timeout=None):
            calls.append(("POST", url, json))
            return mock.Mock(ok=True, status_code=200, text="ok")

        def get(url, headers=None, timeout=None):
            calls.append(("GET", url, None))
            if url.endswith("/models/install/status"):
                return mock.Mock(ok=True, json=lambda: {"jobs": []})
            return mock.Mock(ok=True, json=lambda: {"license": "apache-2.0", "state": "not_accepted",
                                                      "fingerprint": "v2:" + "a" * 64})

        with mock.patch("maker.voice.requests.post", side_effect=post), \
                mock.patch("maker.voice.requests.get", side_effect=get):
            voice.setup_voicestudio(cfg, log=lambda *_: None)
        self.assertEqual(calls[0], ("POST", "http://vs/models/install",
                                    {"repo_id": "KittenML/kitten-tts-mini-0.8", "target": "local"}))
        accept = [c for c in calls if c[1].endswith("/models/licenses/accept")]
        self.assertEqual(accept[0][2], {"repo_id": "KittenML/kitten-tts-mini-0.8",
                                        "fingerprint": "v2:" + "a" * 64, "accepted": True})

    def test_never_accepts_other_models(self):
        cfg = Config(voicestudio_url="http://vs", voicestudio_install="k2-fsa/OmniVoice",
                     voicestudio_accept="KittenML/kitten-tts-mini-0.8")
        with mock.patch("maker.voice.requests.post", return_value=mock.Mock(ok=True, status_code=200, text="")) as post, \
                mock.patch("maker.voice.requests.get", return_value=mock.Mock(ok=True, json=lambda: {"jobs": []})):
            voice.setup_voicestudio(cfg, log=lambda *_: None)
        self.assertFalse(any("licenses/accept" in c.args[0] for c in post.call_args_list))

    def test_speech_request_uses_kittentts(self):
        cfg = Config(voicestudio_url="http://vs")
        ok = mock.Mock(ok=True, content=b"x", headers={"Content-Type": "audio/mpeg"})
        with tempfile.TemporaryDirectory() as tmp, mock.patch("maker.voice.requests.post", return_value=ok) as post:
            voice.voicestudio(cfg, "hi", os.path.join(tmp, "a.mp3"))
        body = post.call_args.kwargs["json"]
        self.assertEqual((body["model"], body["voice"]), ("kittentts", "expr-voice-3-m"))


if __name__ == "__main__":
    unittest.main()
