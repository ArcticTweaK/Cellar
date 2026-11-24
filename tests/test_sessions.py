import unittest

from cellar import sessions


class Sessions(unittest.TestCase):
    def test_join_teleport_leave(self):
        h = []
        self.assertTrue(sessions.start(h, "a", "alt1", 111, "job1", now=100))
        self.assertTrue(sessions.start(h, "a", "alt1", 222, "job2", now=400))    # teleport: the first one ends
        self.assertEqual((h[1].place_id, h[1].end), (111, 400))
        self.assertTrue(sessions.end(h, "a", now=1000))
        self.assertEqual(sessions.duration(h[0]), 600)
        self.assertFalse(sessions.end(h, "a", now=1100))                      # nothing open any more

    def test_same_server_again_continues(self):
        h = []
        sessions.start(h, "a", "alt1", 111, "job1", now=100)
        self.assertFalse(sessions.start(h, "a", "alt1", 111, "job1", now=500))  # Cellar restarted, same client
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0].end, 0)

    def test_accounts_are_separate_and_missing_ones_close(self):
        h = []
        sessions.start(h, "a", "alt1", 111, "j1", now=100)
        sessions.start(h, "b", "alt2", 111, "j1", now=150)
        self.assertEqual(sessions.close_missing(h, {"b"}, now=300), 1)
        a = next(r for r in h if r.account_id == "a")
        b = next(r for r in h if r.account_id == "b")
        self.assertEqual((a.end, b.end), (300, 0))

    def test_totals_clip_to_the_window(self):
        h = []
        sessions.start(h, "a", "alt1", 111, "j1", now=0)
        sessions.end(h, "a", now=1000)
        sessions.start(h, "a", "alt1", 222, "j2", now=2000)
        sessions.start(h, "b", "alt2", 111, "j3", now=2000)
        rows = sessions.totals(h, since=500, now=2600)
        got = {(a, p): (n, s) for a, p, n, s in rows}
        self.assertEqual(got[("alt1", 111)], (1, 500))                        # only the part after `since`
        self.assertEqual(got[("alt1", 222)], (1, 600))                        # still playing: up to now
        self.assertEqual(got[("alt2", 111)], (1, 600))

    def test_replayed_log_adds_nothing(self):
        h = []
        sessions.start(h, "a", "alt1", 111, "jA", now=100)         # lobby
        sessions.start(h, "a", "alt1", 222, "jB", now=400)         # teleported to the match
        # Cellar restarts and reads the whole log again: the same two joins with their own times
        self.assertFalse(sessions.start(h, "a", "alt1", 111, "jA", now=100))
        self.assertFalse(sessions.start(h, "a", "alt1", 222, "jB", now=400))
        self.assertEqual(len(h), 2)
        self.assertEqual((h[0].job_id, h[0].end), ("jB", 0))
        self.assertFalse(sessions.end(h, "a", now=300))            # an old leave (before the open session)
        self.assertEqual(h[0].end, 0)

    def test_old_records_have_unknown_length(self):
        from cellar.models import JoinRecord
        h = [JoinRecord(100, "a", "alt1", 111, "j", end=-1)]
        self.assertEqual(sessions.duration(h[0]), -1)
        self.assertEqual(sessions.totals(h, since=0, now=1000), [])
        self.assertEqual(sessions.close_missing(h, set(), now=1000), 0)
        self.assertTrue(sessions.start(h, "a", "alt1", 111, "j2", now=2000))   # not treated as open

    def test_human(self):
        self.assertEqual(sessions.human(50), "50 s")
        self.assertEqual(sessions.human(3725), "1 h 2 min")
        self.assertEqual(sessions.human(600), "10 min")
        self.assertEqual(sessions.human(7200), "2 h")


if __name__ == "__main__":
    unittest.main()
