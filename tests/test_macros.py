import unittest

from cellar import macros


class Macros(unittest.TestCase):
    def test_steps(self):
        steps, errors = macros.parse("tap space\nkey w 800\nclick 640 360\nwait 1000-3000\nscroll up\n")
        self.assertEqual(errors, [])
        self.assertEqual([s[0] for s in steps], ["tap", "key", "click", "wait", "scroll"])
        self.assertEqual(steps[3][1], (1000, 3000))

    def test_type_keeps_hash(self):
        steps, errors = macros.parse("type gg #1\nwait 100")
        self.assertEqual(steps[0], ("type", ("gg #1",)))

    def test_comments(self):
        steps, errors = macros.parse("# only a comment\ntap e  # open the shop\nwait 50")
        self.assertEqual(errors, [])
        self.assertEqual(len(steps), 2)

    def test_errors_name_the_line(self):
        _, errors = macros.parse("wait 100\nfly away\nclick 5")
        self.assertTrue(any(e.startswith("line 2") for e in errors))
        self.assertTrue(any(e.startswith("line 3") for e in errors))

    def test_loop_needs_a_pause(self):
        _, errors = macros.parse("tap space")
        self.assertTrue(errors)


class Blocks(unittest.TestCase):
    def test_repeat_and_random(self):
        steps, errors = macros.parse("repeat 3 {\n  tap e\n  random {\n    tap 1\n    tap 2\n  }\n}\nwait 10\n")
        self.assertEqual(errors, [])
        self.assertEqual(steps[0][0], "repeat")
        n, body = steps[0][1]
        self.assertEqual(n, 3)
        self.assertEqual([op for op, _ in body], ["tap", "random"])

    def test_block_errors(self):
        self.assertTrue(any("never closed" in e for e in macros.parse("repeat 2 {\ntap e\nwait 5")[1]))
        self.assertTrue(any("without" in e for e in macros.parse("}\nwait 5")[1]))
        self.assertTrue(any("repeat 5 {" in e for e in macros.parse("repeat x {\n}\nwait 5")[1]))
        self.assertTrue(any("empty" in e for e in macros.parse("repeat 2 {\n}\nwait 5")[1]))

    def test_pause_inside_a_block_counts(self):
        self.assertEqual(macros.parse("repeat 2 {\ntap e\nwait 100\n}")[1], [])

    def test_stop_after(self):
        steps, errors = macros.parse("stop after 30m\ntap e\nwait 5")
        self.assertEqual(errors, [])
        self.assertEqual(macros._stop_after(steps), 1800)
        self.assertTrue(macros.parse("stop after soon\nwait 5")[1])

    def test_runner_runs_blocks_in_order(self):
        class FakeVNC:
            def __init__(self):
                self.taps = []

            def tap(self, sym, hold=0.05):
                self.taps.append(sym)
        r = macros.Runner.__new__(macros.Runner)
        import threading
        r._stop, r.deadline, r.timed_out, r.logf, r.who, r.name = threading.Event(), 0, False, print, "t", "m"
        steps, _ = macros.parse("repeat 2 {\ntap a\nrepeat 2 {\ntap b\n}\n}\nwait 1")
        v = FakeVNC()
        self.assertTrue(r._exec(v, steps, set()))
        a, b = ord("a"), ord("b")
        self.assertEqual(v.taps, [a, b, b, a, b, b])
