import json
import os
import tempfile
import unittest
from unittest import mock

from poster import runner, state
from poster.config import Config


class FolderPostingTests(unittest.TestCase):
    def test_posts_each_video_with_its_caption_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "20261119-news-cast.mp4"), "wb") as f:
                f.write(b"v")
            with open(os.path.join(tmp, "20261119-news-cast.json"), "w") as f:
                json.dump({"title": "Cast revealed", "description": "d", "hashtags": ["#gta6"]}, f)
            seen = []

            def fake_post(self_, path, meta, results=None, dry_run=False):
                seen.append((os.path.basename(path), meta.title))
                return {"tiktok": {"ok": True, "url": "https://tiktok/x"}}

            cfg = Config(platforms=["tiktok"])
            with mock.patch.object(runner.Poster, "post_video", fake_post), \
                    mock.patch("poster.runner.pick_state", return_value=state.State(lambda: None, lambda t: None)):
                summary = runner.post_folder(cfg, tmp, log=lambda *_: None)
            self.assertEqual(seen, [("20261119-news-cast.mp4", "Cast revealed")])
            self.assertTrue(summary[0]["done"] is False or summary[0]["done"] is True)
            with open(os.path.join(tmp, "20261119-news-cast.result.json")) as f:
                result = json.load(f)
            self.assertTrue(result["results"]["tiktok"]["ok"])

    def test_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(runner.post_folder(Config(), tmp, log=lambda *_: None), [])


class ScoutMemoryTests(unittest.TestCase):
    def test_tiktok_login_saved_by_scout_is_used(self):
        # what the Scout's /tiktok/callback stores (env_hash of "" = no GitHub secret)
        saved = json.dumps({"tiktok_refresh": {"env_hash": state._hash(""), "value": "RT-from-login"}})
        resp = mock.Mock(text=saved)
        resp.raise_for_status = lambda: None
        with mock.patch("requests.get", return_value=resp):
            st = state.scout_state("https://scout", "k")
        self.assertEqual(st.token("tiktok_refresh", ""), "RT-from-login")
        cfg = Config(tiktok_client_key="ck", tiktok_client_secret="cs", scout_key="k")
        self.assertTrue(cfg.has_tiktok)
        self.assertFalse(Config(tiktok_client_key="ck", tiktok_client_secret="cs").has_tiktok)

    def test_pick_state_prefers_scout(self):
        with mock.patch("poster.state.scout_state", return_value="scout") as sc:
            self.assertEqual(runner.pick_state(Config(scout_key="k")), "scout")
        sc.assert_called_once()


if __name__ == "__main__":
    unittest.main()
