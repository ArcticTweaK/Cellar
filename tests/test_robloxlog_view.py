"""Reading whole Roblox / Sober logs for the Roblox logs window (robloxlog.parse_line / read_log)."""

import os
import tempfile
import unittest
from pathlib import Path

from cellar import robloxlog

JOIN = ("2026-11-24T20:16:14.294Z,39.294300,4256b6c0,6 [FLog::Output] ! Joining game "
        "'c65be8de-c609-49f3-89e0-340c11fcafb6' place 2534724415 at 10.0.0.1")
ERR = ("2026-11-24T20:31:21.812Z,946.812134,42d6d6c0,6,Error [FLog::CreatorError] Error: "
       "Players.x.PlayerScripts.Lights:78: attempt to index nil with 'Parent'")
WARN = "2026-11-24T20:15:35.657Z,0.657838,d03e06c0,6,Warning [FLog::Output] Hello World"
DISC = "2026-11-24T21:00:00.000Z,10.0,1,6,Info [FLog::Network] Time to disconnect replication data: 0.1"


class ParseLine(unittest.TestCase):
    def test_join_without_severity_is_an_event(self):
        ln = robloxlog.parse_line(JOIN)
        self.assertEqual(ln.severity, "info")
        self.assertIn("Joined place 2534724415", ln.event)
        self.assertTrue(ln.text.startswith("[FLog::Output] ! Joining game"))
        self.assertRegex(ln.time, r"^\d\d:\d\d:\d\d$")             # local time, no date / no UTC 'Z'

    def test_severities(self):
        self.assertEqual(robloxlog.parse_line(ERR).severity, "error")
        self.assertEqual(robloxlog.parse_line(WARN).severity, "warning")
        self.assertEqual(robloxlog.parse_line(ERR).event, "")         # a game's script error is not an event
        self.assertTrue(robloxlog.parse_line(ERR).noise)
        self.assertFalse(robloxlog.parse_line(ERR).worth_showing)
        crit = "2026-11-24T20:15:35.1Z,0.1,d0,6,Critical [DFLog::Mimalloc] mi_option_show_errors=1"
        self.assertEqual(robloxlog.parse_line(crit).severity, "info")  # Roblox's 'Critical' = startup notes
        own = "2026-11-24T20:15:35.1Z,0.1,d0,6,Error [FLog::ExperienceContextHolder] Unsafe call"
        self.assertTrue(robloxlog.parse_line(own).worth_showing)
        self.assertTrue(robloxlog.parse_line(JOIN).worth_showing)

    def test_disconnect_and_sober_lines(self):
        self.assertEqual(robloxlog.parse_line(DISC).event, "Disconnected from the server")
        s = robloxlog.parse_line("error: app: could not open the GPU device")
        self.assertEqual((s.severity, s.text, s.time), ("error", "app: could not open the GPU device", ""))
        self.assertIsNone(robloxlog.parse_line("   "))
        self.assertEqual(robloxlog.parse_line("    at stack frame 3").severity, "info")

    def test_read_log_keeps_the_newest_lines(self):
        d = tempfile.mkdtemp()
        f = Path(d) / "x.log"
        f.write_text("\n".join([WARN] * 10 + [ERR]) + "\n")
        old = robloxlog.MAX_LINES
        robloxlog.MAX_LINES = 3
        try:
            lines, total = robloxlog.read_log(f)
        finally:
            robloxlog.MAX_LINES = old
            os.unlink(f)
            os.rmdir(d)
        self.assertEqual(total, 11)
        self.assertEqual([ln.severity for ln in lines], ["warning", "warning", "error"])


if __name__ == "__main__":
    unittest.main()
