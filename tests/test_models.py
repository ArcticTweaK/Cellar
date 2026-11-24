import unittest

from cellar.models import Account, AppSettings, from_dict, to_dict


class Models(unittest.TestCase):
    def test_round_trip(self):
        s = AppSettings()
        s.theme, s.fps_cap = "midnight", 45
        s.gfx.quality = 7
        back = from_dict(AppSettings, to_dict(s))
        self.assertEqual(to_dict(back), to_dict(s))

    def test_old_files_load(self):
        # unknown keys are ignored, missing keys keep their defaults, wrong types are skipped
        s = from_dict(AppSettings, {"fps_cap": 60, "no_such_setting": 1, "gfx": {"quality": 3, "gone": True},
                                    "launch_delay_sec": "not a number"})
        self.assertEqual(s.fps_cap, 60)
        self.assertEqual(s.gfx.quality, 3)
        self.assertEqual(s.theme, AppSettings().theme)

    def test_account(self):
        a = from_dict(Account, {"username": "x", "pinned": True})
        self.assertTrue(a.pinned)
        self.assertEqual(a.name, "x")


class Graphics(unittest.TestCase):
    def test_own_preset_beats_the_global_one(self):
        from cellar import gfx
        s = AppSettings()
        gfx.apply_preset(s.gfx, "Lowest")
        lowest, _ = gfx.final(s)
        light, _ = gfx.final(s, preset="Light")
        main, _ = gfx.final(s, full_quality=True)
        self.assertIn("FFlagDebugSkyGray", lowest)
        self.assertNotIn("FFlagDebugSkyGray", light)
        self.assertEqual(light.get("DFIntTextureQualityOverride"), "2")
        self.assertEqual(main, {})
        self.assertEqual(s.gfx.preset, "Lowest")          # the global setting itself is untouched
