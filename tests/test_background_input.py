import unittest
from pathlib import Path
from unittest import mock

from cellar import background


class _Conn:
    def __init__(self, fail=False):
        self.fail, self.broken, self.sent = fail, False, []

    def tap(self, sym, hold=0.05):
        if self.fail:
            self.broken = True
            raise BrokenPipeError("the screen closed the connection")
        self.sent.append(sym)

    def close(self):
        self.broken = True

    def drain(self):
        pass


class SharedInput(unittest.TestCase):
    """Everything that types into one screen must use one connection (one virtual keyboard in its sway)."""

    def setUp(self):
        background._inputs.clear()
        self.scr = background.Screen(dir=Path("/x"), vnc=Path("/x/vnc.sock"))

    def tearDown(self):
        background._inputs.clear()

    def test_viewer_macro_and_antiafk_share_one_connection(self):
        made = []
        with mock.patch.object(background, "VNC", side_effect=lambda *a, **k: made.append(_Conn()) or made[-1]):
            background.Input(self.scr).tap(1)
            background.Input(self.scr).tap(2)
            background.poke(self.scr, "Space")
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0].sent, [1, 2, 0x20])

    def test_a_broken_connection_is_replaced_once(self):
        conns = [_Conn(fail=True), _Conn()]
        with mock.patch.object(background, "VNC", side_effect=lambda *a, **k: conns.pop(0)):
            first = background.input_of(self.scr)
            background.Input(self.scr).tap(7)
        self.assertTrue(first.broken)
        self.assertEqual(background._inputs[str(self.scr.vnc)].sent, [7])


if __name__ == "__main__":
    unittest.main()
