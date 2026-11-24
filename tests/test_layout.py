import unittest

from cellar import layout
from cellar.models import LayoutSettings


def overlaps(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


class Layout(unittest.TestCase):
    area = (0, 0, 2560, 1440)

    def test_grid_fits_without_overlap(self):
        for n in (1, 2, 3, 4, 5, 7, 9, 12):
            rects, over = layout.compute_rects(n, self.area, LayoutSettings())
            self.assertEqual(len(rects), n)
            self.assertFalse(over)
            for i, a in enumerate(rects):
                self.assertTrue(0 <= a[0] and a[0] + a[2] <= 2560 and 0 <= a[1] and a[1] + a[3] <= 1440, a)
                for b in rects[i + 1:]:
                    self.assertFalse(overlaps(a, b), (a, b))

    def test_fixed_grid(self):
        s = LayoutSettings(mode="Grid", cols=3)
        rects, _ = layout.compute_rects(6, self.area, s)
        self.assertEqual(len({r[0] for r in rects}), 3)

    def test_too_many_windows_overlap(self):
        rects, over = layout.compute_rects(200, (0, 0, 1280, 720), LayoutSettings())
        self.assertEqual(len(rects), 200)
        self.assertTrue(over)

    def test_capacity(self):
        self.assertGreaterEqual(layout.capacity(self.area, LayoutSettings()), 1)
