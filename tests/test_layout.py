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


class Spread(unittest.TestCase):
    def test_share_by_size(self):
        big, small = (0, 0, 2560, 1440), (2560, 0, 1920, 1080)
        self.assertEqual(sum(layout.share(10, [big, small])), 10)
        self.assertEqual(layout.share(10, [big, small]), [6, 4])          # 3.7 M vs 2.1 M pixels
        self.assertEqual(layout.share(1, [big, small]), [1, 0])
        self.assertEqual(layout.share(0, [big, small]), [0, 0])

    def test_spread_stays_on_each_screen(self):
        from cellar.models import LayoutSettings
        left, right = (0, 0, 1920, 1080), (1920, 0, 1920, 1080)
        rects, overlap = layout.spread(8, [right, left], LayoutSettings())      # given in any order
        self.assertEqual(len(rects), 8)
        self.assertFalse(overlap)
        first, second = rects[:4], rects[4:]
        self.assertTrue(all(x + w <= 1920 for x, _, w, _ in first))         # left screen first
        self.assertTrue(all(x >= 1920 and x + w <= 3840 for x, _, w, _ in second))

    def test_bounds(self):
        self.assertEqual(layout.bounds([(0, 0, 1920, 1080), (1920, -200, 2560, 1440)]), (0, -200, 4480, 1440))

