"""Grid math for arranging client windows (port of WindowLayout.ComputeRects / GridSize)."""

import math
from typing import List, Tuple

from .models import LayoutSettings

Rect = Tuple[int, int, int, int]   # x, y, w, h


def grid_size(n: int, a: Rect, gap: int, s: LayoutSettings, min_w: int, min_h: int) -> Tuple[int, int]:
    if s.mode == "Grid" and (s.cols > 0 or s.rows > 0):
        if s.cols > 0 and s.rows > 0:
            cols, rows = s.cols, s.rows
            if cols * rows < n:
                rows = (n + cols - 1) // cols
        elif s.cols > 0:
            cols = s.cols
            rows = (n + cols - 1) // cols
        else:
            rows = s.rows
            cols = (n + rows - 1) // rows
        return cols, rows
    # Automatic: the grid whose cells are closest to a comfortable 3:2 shape, preferring
    # grids whose cells are at least the minimum window size.
    _, _, aw, ah = a
    best_f, best_a = math.inf, math.inf
    fc = fr = 0
    ac, ar = 1, n
    for c in range(1, n + 1):
        r = (n + c - 1) // c
        cw = (aw - gap * (c - 1)) / c
        ch = (ah - gap * (r - 1)) / r
        if cw < 1 or ch < 1:
            continue
        score = abs(math.log(cw / ch) - math.log(1.5)) + 0.05 * (c * r - n)
        if cw + 0.5 >= min_w and ch + 0.5 >= min_h and score < best_f - 1e-9:
            best_f, fc, fr = score, c, r
        if score < best_a - 1e-9:
            best_a, ac, ar = score, c, r
    return (fc, fr) if fc > 0 else (ac, ar)


def compute_rects(n: int, area: Rect, s: LayoutSettings) -> Tuple[List[Rect], bool]:
    """Returns (rects, overlap). overlap=True when windows of the minimum size do not fit side by side."""
    res: List[Rect] = []
    if n <= 0:
        return res, False
    min_w, min_h = max(100, s.min_w), max(80, s.min_h)
    ax, ay, aw, ah = area
    m = max(0, s.margin)
    a = (ax + m, ay + m, aw - 2 * m, ah - 2 * m)
    if a[2] < 100 or a[3] < 100:
        a = area
    ax, ay, aw, ah = a
    gap = max(0, s.gap)

    if s.mode == "FixedSize":
        fw, fh = max(200, s.fixed_w, min_w), max(150, s.fixed_h, min_h)
        x, y, off, overlap = ax, ay, 0, False
        for _ in range(n):
            if x + fw > ax + aw and x > ax + off:
                x, y = ax + off, y + fh + gap
            if y + fh > ay + ah and y > ay + off:
                off += 32
                x, y, overlap = ax + off, ay + off, True
            res.append((x, y, fw, fh))
            x += fw + gap
        return res, overlap

    cols, rows = grid_size(n, a, gap, s, min_w, min_h)
    cell_w = (aw - gap * (cols - 1)) / cols
    cell_h = (ah - gap * (rows - 1)) / rows
    used_rows = (n + cols - 1) // cols

    if cell_w + 0.5 >= min_w and cell_h + 0.5 >= min_h:
        scale = min(100, max(20, s.scale))
        for i in range(n):
            row, col = divmod(i, cols)
            cols_this = cols
            if s.stretch_last and row == used_rows - 1:
                cnt = n - row * cols
                if 0 < cnt < cols:
                    cols_this = cnt
            top = ay + round(row * (ah + gap) / rows)
            bottom = ay + round((row + 1) * (ah + gap) / rows) - gap
            left = ax + round(col * (aw + gap) / cols_this)
            right = ax + round((col + 1) * (aw + gap) / cols_this) - gap
            x, y, w, h = left, top, right - left, bottom - top
            if scale < 100:
                nw = min(w, max(min_w, w * scale // 100))
                nh = min(h, max(min_h, h * scale // 100))
                x, y, w, h = x + (w - nw) // 2, y + (h - nh) // 2, nw, nh
            res.append((x, y, w, h))
        return res, False

    # Not enough room for windows of the minimum size: spread them evenly with overlap.
    ow, oh = max(min_w, 200), max(min_h, 150)
    for i in range(n):
        row, col = divmod(i, cols)
        x = ax + round(col * (aw - ow) / (cols - 1)) if cols > 1 and aw > ow else ax
        y = ay + round(row * (ah - oh) / (rows - 1)) if rows > 1 and ah > oh else ay
        res.append((x, y, ow, oh))
    return res, True


def capacity(area: Rect, s: LayoutSettings) -> int:
    m, gap = max(0, s.margin), max(0, s.gap)
    min_w, min_h = max(100, s.min_w), max(80, s.min_h)
    c = max(1, (area[2] - 2 * m + gap) // (min_w + gap))
    r = max(1, (area[3] - 2 * m + gap) // (min_h + gap))
    return c * r
