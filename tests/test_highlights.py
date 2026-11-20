import unittest

from maker import chat, clipstyle, facecam, highlights, loudness
from maker.twitch import parse_duration


class ChatSpikeTests(unittest.TestCase):
    def test_spike_is_3x_median_and_hype_counts(self):
        msgs = []
        for t in range(0, 600):  # 1 message per second = 10 per bucket
            msgs.append({"t": float(t), "user": "u", "text": "hello"})
        for k in range(60):  # +60 messages in the 300-310 s bucket -> 7x
            msgs.append({"t": 300 + k / 10, "user": "u", "text": "KEKW NO WAY"})
        rows = chat.buckets(sorted(msgs, key=lambda m: m["t"]), 0, 600)
        found, median = chat.spikes(rows)
        self.assertEqual(median, 10)
        self.assertEqual(found[0]["t"], 300)
        self.assertGreaterEqual(found[0]["ratio"], 3)
        self.assertGreater(found[0]["hype"], 60)
        self.assertEqual(len(found), 1)

    def test_hype_words(self):
        self.assertEqual(chat.hype_count("KEKW that was insane 💀 W"), 4)
        self.assertEqual(chat.hype_count("Wow what a Lucky play"), 0)

    def test_parse_twitchdownloader_json(self):
        data = {"comments": [{"content_offset_seconds": 12.5, "commenter": {"display_name": "Kev"},
                              "message": {"body": "LUL"}},
                             {"content_offset_seconds": 3, "commenter": {"display_name": "Mo"},
                              "message": {"fragments": [{"text": "NO "}, {"text": "WAY"}]}}]}
        out = chat.parse_chat(data)
        self.assertEqual([m["text"] for m in out], ["NO WAY", "LUL"])

    def test_popups_pick_hype_messages_near_peak(self):
        msgs = [{"t": 9.5, "user": "a", "text": "ok"}, {"t": 10.2, "user": "b", "text": "KEKW"},
                {"t": 30, "user": "c", "text": "LUL far away"}]
        self.assertEqual([m["user"] for m in chat.popups(msgs, 10)], ["a", "b"])


class LoudnessAndWindowTests(unittest.TestCase):
    def test_peak_and_spike(self):
        levels = [-30.0] * 200
        levels[150] = -18.0
        pk = loudness.peak(levels)
        self.assertEqual(pk["t"], 150)
        self.assertTrue(pk["spike"])
        self.assertEqual(pk["jump"], 12.0)

    def test_window_starts_before_action(self):
        self.assertEqual(clipstyle.choose_window(30, 20), (0.0, 30))
        start, length = clipstyle.choose_window(60, 40)
        self.assertEqual((start, length), (15.0, 45))  # 12 s lead, capped so it ends with the clip
        self.assertEqual(clipstyle.choose_window(60, 5), (0.0, 45))

    def test_duration_parse(self):
        self.assertEqual(parse_duration("3h12m5s"), 11525)
        self.assertEqual(parse_duration("45s"), 45)


class LookTests(unittest.TestCase):
    def test_keywords_and_emoji_stripped(self):
        self.assertTrue(clipstyle.is_keyword("POLICE"))
        self.assertTrue(clipstyle.is_keyword("$5,000"))
        self.assertFalse(clipstyle.is_keyword("the"))
        self.assertEqual(clipstyle.clean("NO WAY 💀"), "NO WAY")

    def test_ass_has_hook_via_captions_and_chat(self):
        words = [{"word": "NO", "start": 1, "end": 1.3}, {"word": "WAY", "start": 1.3, "end": 1.6}]
        ass = clipstyle.build_ass(30, words, "He robbed the cops 😳", "Lirik", 10,
                                  [{"user": "kev", "text": "KEKW"}], split=True)
        self.assertIn(",Hook,,0,0,0,,{\\fad(0,250)}HE ROBBED THE COPS", ass)
        self.assertIn("via @Lirik", ass)
        self.assertEqual(ass.count(",Caption,"), 2)
        self.assertIn("kev: ", ass)

    def test_facecam_crop_keeps_panel_shape(self):
        x, y, w, h = facecam.crop_around((1600, 800, 120, 120), (1920, 1080))
        self.assertAlmostEqual(w / h, 1080 / 672, delta=0.03)
        self.assertLessEqual(x + w, 1920)
        self.assertLessEqual(y + h, 1080)

    def test_score_is_0_to_100(self):
        self.assertLessEqual(highlights.score_clip(10_000_000, {"jump": 50}, 99), 100)
        self.assertGreater(highlights.score_clip(50_000, {"jump": 10}, 4), highlights.score_clip(500, {"jump": 2}, 0))


class RealDataBugTests(unittest.TestCase):
    """Bugs found on the first real Twitch run."""

    def test_numpy_face_boxes(self):
        import numpy as np
        import statistics
        boxes = [tuple(int(v) for v in np.array([1600, 800, 120, 120], dtype=np.int32)) for _ in range(4)]
        self.assertEqual(statistics.median(b[0] for b in boxes), 1600)
        self.assertEqual(statistics.pstdev([b[0] for b in boxes]), 0)

    def test_muted_parts_do_not_fake_spikes(self):
        levels = [-25.0] * 150 + [-70.0] * 60 + [-24.0] * 100
        pk = loudness.peak(levels)
        self.assertLess(pk["jump"], 8)

    def test_only_english_clips(self):
        from unittest import mock
        from maker.config import Config
        tw = mock.Mock()
        tw.game_id.return_value = "1"
        tw.top_clips.return_value = [
            {"url": "u1", "title": "a", "broadcaster_name": "x", "view_count": 9, "duration": 20, "language": "ru"},
            {"url": "u2", "title": "b", "broadcaster_name": "y", "view_count": 5, "duration": 20, "language": "en"}]
        cands = highlights.clip_candidates(Config(), tw, set(), log=lambda *_: None)
        self.assertEqual([c["url"] for c in cands], ["u2"])


if __name__ == "__main__":
    unittest.main()
