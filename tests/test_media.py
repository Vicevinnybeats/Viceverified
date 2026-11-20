import os
import tempfile
import unittest
from unittest import mock

from poster import instagram, media
from poster.config import Config
from poster.meta import Meta


class MediaLinkTests(unittest.TestCase):
    def test_scout_link_used_without_r2_and_deleted_after_posting(self):
        cfg = Config(ig_user_id="1", ig_access_token="t", scout_key="k", scout_url="https://scout")
        self.assertTrue(cfg.has_instagram)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v.mp4")
            with open(path, "wb") as f:
                f.write(b"video")
            put = mock.Mock(status_code=200, json=lambda: {"url": "https://scout/media/x.mp4"})
            posts = []

            def ig_post(url, timeout=None, data=None):
                posts.append((url, data))
                return mock.Mock(status_code=200, json=lambda: {"id": "C1" if url.endswith("/media") else "M1"})

            status = mock.Mock(status_code=200, ok=True, json=lambda: {"status_code": "FINISHED", "permalink": "https://ig/p/1"})
            with mock.patch("poster.media.requests.put", return_value=put) as p_put, \
                    mock.patch("poster.media.requests.delete") as p_del, \
                    mock.patch("poster.instagram.requests.post", side_effect=ig_post), \
                    mock.patch("poster.instagram.requests.get", return_value=status):
                out = instagram.post(cfg, "t", path, Meta(title="GTA 6"), sleep=lambda _: None)
        self.assertTrue(p_put.call_args.args[0].startswith("https://scout/api/media/"))
        self.assertEqual(posts[0][1]["video_url"], "https://scout/media/x.mp4")
        self.assertEqual(posts[0][1]["media_type"], "REELS")
        p_del.assert_called_once()
        self.assertEqual(out["id"], "M1")

    def test_no_instagram_without_link_source(self):
        self.assertFalse(Config(ig_user_id="1", ig_access_token="t").has_instagram)


if __name__ == "__main__":
    unittest.main()
