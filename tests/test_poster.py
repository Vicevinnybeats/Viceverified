import json
import os
import tempfile
import unittest
from unittest import mock

from poster import captions, runner, tiktok, youtube
from poster.config import Config
from poster.meta import Meta, instagram_caption, parse_sidecar, tiktok_caption, youtube_fields
from poster.state import State


class FakeResp:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code = status
        self._data = data or {}
        self.headers = headers or {}
        self.text = json.dumps(self._data)
        self.ok = status < 400

    def json(self):
        return self._data


def video_file(size: int) -> str:
    f = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    f.write(b"\0" * size)
    f.close()
    return f.name


class MetaTests(unittest.TestCase):
    def test_txt_sidecar(self):
        m = parse_sidecar("clip.txt", "GTA 6 map is HUGE\nVice City from the air #gta6 #map", "clip.mp4")
        self.assertEqual(m.title, "GTA 6 map is HUGE")
        self.assertEqual(m.description, "Vice City from the air")
        self.assertEqual(m.hashtags, ["#gta6", "#map"])

    def test_json_sidecar_and_platforms(self):
        m = parse_sidecar("a.json", json.dumps({"hashtags": "gta6 gaming", "platforms": ["YouTube"]}), "lucia_heist.mp4")
        self.assertEqual(m.title, "Lucia heist")
        self.assertEqual(m.hashtags, ["#gta6", "#gaming"])
        self.assertEqual(m.platforms, ["youtube"])

    def test_youtube_adds_shorts_and_limits(self):
        title, desc, tags = youtube_fields(Meta(title="x" * 120, hashtags=["#gta6"]))
        self.assertLessEqual(len(title), 100)
        self.assertIn("#Shorts", desc)
        self.assertEqual(tags, ["gta6"])
        title, _, _ = youtube_fields(Meta(title="GTA 6 is out"))
        self.assertEqual(title, "GTA 6 is out #Shorts")

    def test_platform_captions(self):
        m = Meta(title="T", description="D", hashtags=[f"#t{i}" for i in range(40)], caption="Hook!")
        self.assertEqual(instagram_caption(m).count("#"), 30)
        self.assertTrue(tiktok_caption(m).startswith("Hook!"))


class CaptionTests(unittest.TestCase):
    def test_parse_qwen_with_thinking(self):
        out = captions.parse_ai_json('<think>hmm {no}</think>\nSure: {"caption": "c", "hashtags": ["#a"]}')
        self.assertEqual(out["caption"], "c")

    def test_extract_formats(self):
        self.assertEqual(captions._extract_text({"result": {"response": "hi"}}), "hi")
        self.assertEqual(captions._extract_text({"result": {"choices": [{"message": {"content": "yo"}}]}}), "yo")

    def test_enrich_keeps_user_title_and_falls_back(self):
        cfg = Config(cf_account_id="a", cf_api_token="t")
        with mock.patch.object(captions, "ask_qwen", return_value={
                "youtube_title": "AI title", "caption": "AI hook", "description": "AI desc", "hashtags": ["gta6", "vicecity"]}):
            m = captions.enrich(cfg, Meta(title="Mine"), log=lambda *_: None)
        self.assertEqual((m.title, m.caption, m.hashtags), ("Mine", "AI hook", ["#gta6", "#vicecity"]))
        with mock.patch.object(captions, "ask_qwen", side_effect=RuntimeError("down")):
            m = captions.enrich(cfg, Meta(title="Mine"), log=lambda *_: None)
        self.assertEqual(m.hashtags, captions.DEFAULT_HASHTAGS)


class TikTokTests(unittest.TestCase):
    def test_chunk_plan(self):
        self.assertEqual(tiktok.chunk_plan(3_000_000), (3_000_000, 1))
        size = 150 * tiktok.MiB + 123
        chunk, count = tiktok.chunk_plan(size)
        self.assertEqual((chunk, count), (tiktok.CHUNK, 15))
        self.assertLessEqual(size - chunk * (count - 1), 128 * tiktok.MiB)

    def test_privacy(self):
        self.assertEqual(tiktok.pick_privacy("PUBLIC_TO_EVERYONE", ["SELF_ONLY"]), "SELF_ONLY")
        self.assertEqual(tiktok.pick_privacy("PUBLIC_TO_EVERYONE", ["PUBLIC_TO_EVERYONE", "SELF_ONLY"]),
                         "PUBLIC_TO_EVERYONE")

    def test_direct_post_flow(self):
        path = video_file(70 * tiktok.MiB + 5)
        ranges = []

        def fake_post(url, **kw):
            if url.endswith("creator_info/query/"):
                return FakeResp(data={"data": {"privacy_level_options": ["SELF_ONLY"]}, "error": {"code": "ok"}})
            if url.endswith("video/init/"):
                self.assertEqual(kw["json"]["post_info"]["privacy_level"], "SELF_ONLY")
                self.assertEqual(kw["json"]["source_info"]["total_chunk_count"], 7)
                return FakeResp(data={"data": {"publish_id": "p1", "upload_url": "https://up"}, "error": {"code": "ok"}})
            if url.endswith("status/fetch/"):
                return FakeResp(data={"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [42]},
                                      "error": {"code": "ok"}})
            raise AssertionError(url)

        def fake_put(url, data=None, headers=None, **kw):
            ranges.append(headers["Content-Range"])
            self.assertEqual(int(headers["Content-Length"]), len(data))
            return FakeResp(201)

        with mock.patch("poster.tiktok.requests.post", side_effect=fake_post), \
                mock.patch("poster.tiktok.requests.put", side_effect=fake_put):
            out = tiktok.post(Config(), "tok", path, Meta(title="t"), sleep=lambda _: None)
        os.unlink(path)
        self.assertEqual(out["url"], "https://www.tiktok.com/video/42")
        self.assertEqual(len(ranges), 7)
        self.assertTrue(ranges[-1].endswith(f"-{70 * tiktok.MiB + 4}/{70 * tiktok.MiB + 5}"))

    def test_error_code_raises(self):
        resp = FakeResp(data={"error": {"code": "spam_risk_too_many_posts", "message": "slow down"}})
        with self.assertRaises(Exception) as ctx:
            tiktok._json(resp, "TikTok")
        self.assertIn("spam_risk", str(ctx.exception))


class YouTubeTests(unittest.TestCase):
    def test_upload(self):
        path = video_file(1000)
        with mock.patch("poster.youtube.requests.post",
                        return_value=FakeResp(headers={"Location": "https://resume"})) as p, \
                mock.patch("poster.youtube.requests.put", return_value=FakeResp(data={"id": "abc"})):
            out = youtube.post(Config(), "tok", path, Meta(title="GTA 6"))
        os.unlink(path)
        body = p.call_args.kwargs["json"]
        self.assertEqual(body["snippet"]["title"], "GTA 6 #Shorts")
        self.assertEqual(body["snippet"]["categoryId"], "20")
        self.assertEqual(out["url"], "https://youtube.com/shorts/abc")


class StateTests(unittest.TestCase):
    def test_new_secret_beats_saved_token(self):
        saved = {}
        s = State(lambda: None, lambda t: saved.update(text=t))
        s.set_token("tiktok_refresh", "env-old", "rotated")
        s.save()
        s2 = State(lambda: saved["text"], lambda t: None)
        self.assertEqual(s2.token("tiktok_refresh", "env-old"), "rotated")
        self.assertEqual(s2.token("tiktok_refresh", "env-NEW"), "env-NEW")


class FakeDrive:
    def __init__(self, files):
        self.folders = {"Viceverified": "root-v", "Inbox": "in", "Posted": "posted", "Failed": "failed",
                        "_poster": "sys"}
        self.files = files  # id -> dict(name, parent, text)
        self.n = 0

    def ensure_folder(self, name, parent="root"):
        return self.folders[name]

    def list_children(self, folder_id, extra_q=""):
        return [{"id": i, "name": f["name"], "mimeType": "video/mp4" if f["name"].endswith(".mp4") else "text/plain"}
                for i, f in self.files.items() if f["parent"] == folder_id]

    def find(self, name, parent, folder=None):
        return next((x for x in self.list_children(parent) if x["name"] == name), None)

    def read_text(self, fid):
        return self.files[fid]["text"]

    def write_text(self, name, parent, text, file_id=None, mime=""):
        if file_id:
            self.files[file_id]["text"] = text
            return file_id
        self.n += 1
        fid = f"new{self.n}"
        self.files[fid] = {"name": name, "parent": parent, "text": text}
        return fid

    def download(self, fid, dest):
        with open(dest, "wb") as f:
            f.write(b"video")

    def move(self, fid, new, old):
        assert self.files[fid]["parent"] == old
        self.files[fid]["parent"] = new


class InboxTests(unittest.TestCase):
    def run_inbox(self, drive, cfg, outcomes):
        def fake_post(self_, path, meta, results=None, dry_run=False):
            for p in self_.wanted_platforms(meta):
                if not (results.get(p) or {}).get("ok"):
                    results[p] = {"ok": outcomes[p]} if outcomes[p] else {"ok": False, "error": "boom"}
            return results

        with mock.patch("poster.runner.google.access_token", return_value="t"), \
                mock.patch("poster.runner.google.Drive", return_value=drive), \
                mock.patch.object(runner.Poster, "post_video", fake_post):
            return runner.process_inbox(cfg, log=lambda *_: None)

    def test_success_moves_to_posted(self):
        drive = FakeDrive({
            "v": {"name": "leak.mp4", "parent": "in", "text": ""},
            "s": {"name": "leak.txt", "parent": "in", "text": "New GTA 6 leak\n#gta6"},
        })
        cfg = Config(platforms=["youtube", "tiktok"])
        out = self.run_inbox(drive, cfg, {"youtube": True, "tiktok": True})
        self.assertTrue(out[0]["done"])
        self.assertEqual({f["parent"] for f in drive.files.values()}, {"posted"})
        result = next(f for f in drive.files.values() if f["name"] == "leak.result.json")
        self.assertEqual(json.loads(result["text"])["meta"]["title"], "New GTA 6 leak")

    def test_partial_failure_retries_then_fails(self):
        drive = FakeDrive({"v": {"name": "clip.mp4", "parent": "in", "text": ""}})
        cfg = Config(platforms=["youtube", "tiktok"], max_attempts=2)
        self.run_inbox(drive, cfg, {"youtube": True, "tiktok": False})
        self.assertEqual(drive.files["v"]["parent"], "in")
        self.run_inbox(drive, cfg, {"youtube": True, "tiktok": False})
        self.assertEqual(drive.files["v"]["parent"], "failed")
        result = next(f for f in drive.files.values() if f["name"] == "clip.result.json")
        rec = json.loads(result["text"])
        self.assertEqual(rec["attempts"], 2)
        self.assertTrue(rec["results"]["youtube"]["ok"])


if __name__ == "__main__":
    unittest.main()
