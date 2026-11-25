"""Windows page: arrange Sober windows in a grid (KWin on KDE Plasma, or Hyprland / Sway - see wm.py)."""

import time
from typing import Dict, List, Optional, Set

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QSizePolicy,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QSplitter, QScrollArea)

from .. import layout, sober, store, theme, util
from ..kwin import Screen, Win
from ..models import NamedLayout, clone
from .common import btn, chk, combo, group, hint, row, spin


class Preview(QWidget):
    def __init__(self):
        super().__init__()
        self.area = (0, 0, 1920, 1080)
        self.full = (0, 0, 1920, 1080)
        self.rects = []
        self.labels = []
        self.overlap = False
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set(self, full, area, rects, labels, overlap):
        self.full, self.area, self.rects, self.labels, self.overlap = full, area, rects, labels, overlap
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fx, fy, fw, fh = self.full
        if fw <= 0 or fh <= 0:
            return
        sc = min((self.width() - 10) / fw, (self.height() - 10) / fh)
        ox = (self.width() - fw * sc) / 2
        oy = (self.height() - fh * sc) / 2

        def m(x, y, w, h):
            return QRect(int(ox + (x - fx) * sc), int(oy + (y - fy) * sc), max(1, int(w * sc)), max(1, int(h * sc)))
        pal = self.palette()
        p.fillRect(m(*self.full), pal.window().color().darker(115))
        p.setPen(QPen(pal.mid().color(), 1, Qt.DashLine))
        p.drawRect(m(*self.area))
        accent = theme.qc("accent")
        for i, r in enumerate(self.rects):
            rr = m(*r)
            c = QColor(accent)
            c.setAlpha(110)
            p.fillRect(rr, c)
            p.setPen(QPen(accent.lighter(130), 1))
            p.drawRect(rr)
            p.setPen(pal.text().color())
            txt = self.labels[i] if i < len(self.labels) else str(i + 1)
            p.drawText(rr.adjusted(3, 2, -3, -2), Qt.AlignCenter | Qt.TextWordWrap, txt)


class WindowsPage(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.wins: List[Win] = []
        self.screens: List[Screen] = []
        self.order: List[int] = []          # manual order (tracker ids, or -pid for unmanaged windows)
        self.excluded: Set[int] = set()
        self.seen: Set[str] = set()
        self.capture_due = 0.0
        self._loading = False

        outer = QHBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split)

        # ---- left: settings
        left = QWidget()
        lv = QVBoxLayout(left)
        L = lambda: store.settings.layout
        self.no_kwin = hint("<b>No window control found.</b> Window layout needs KDE Plasma, Hyprland or Sway.")
        self.no_kwin.setVisible(False)
        lv.addWidget(self.no_kwin)

        g, f = group("Grid")
        self.saved = QComboBox()
        self.saved.setToolTip("Layouts you saved: pick one to use it (its grid, monitor and window options)")
        self.saved.activated.connect(self._use_saved)
        f.addRow("Saved layouts", row(self.saved, btn("Save as...", self._save_layout,
                                                      tip="Keep the settings below under a name"),
                                      btn("Delete", self._delete_layout), stretch=False))
        self.monitor = QComboBox()
        self.monitor.currentIndexChanged.connect(lambda *_: self._set("monitor", self.monitor.currentData() or ""))
        f.addRow("Monitor", self.monitor)
        self.mode = combo([("Auto", "Automatic grid"), ("Grid", "Fixed rows / columns"), ("FixedSize", "Fixed window size")],
                          L().mode, lambda d: self._set("mode", d))
        f.addRow("Mode", self.mode)
        self.cols = spin(0, 20, L().cols, lambda v: self._set("cols", v), special="auto")
        self.rows = spin(0, 20, L().rows, lambda v: self._set("rows", v), special="auto")
        f.addRow("Columns / rows", row(self.cols, self.rows))
        self.fw = spin(200, 7680, L().fixed_w, lambda v: self._set("fixed_w", v), " px")
        self.fh = spin(150, 4320, L().fixed_h, lambda v: self._set("fixed_h", v), " px")
        f.addRow("Fixed size", row(self.fw, QLabel("x"), self.fh))
        self.gap = spin(0, 200, L().gap, lambda v: self._set("gap", v), " px")
        self.margin = spin(0, 400, L().margin, lambda v: self._set("margin", v), " px")
        f.addRow("Gap / margin", row(self.gap, self.margin))
        self.scale = spin(20, 100, L().scale, lambda v: self._set("scale", v), " %",
                          "How much of its grid cell each window fills.")
        f.addRow("Window scale", self.scale)
        self.minw = spin(100, 2000, L().min_w, lambda v: self._set("min_w", v), " px")
        self.minh = spin(80, 2000, L().min_h, lambda v: self._set("min_h", v), " px")
        f.addRow("Smallest window", row(self.minw, QLabel("x"), self.minh))
        self.stretch = chk("Stretch the last row", L().stretch_last, lambda v: self._set("stretch_last", v))
        self.workarea = chk("Keep clear of panels", L().use_work_area, lambda v: self._set("use_work_area", v))
        f.addRow(row(self.stretch, self.workarea))
        lv.addWidget(g)

        g, f = group("Window options")
        self.borderless = chk("Borderless (no title bar)", L().borderless, lambda v: self._set("borderless", v))
        self.ontop = chk("Always on top", L().always_on_top, lambda v: self._set("always_on_top", v))
        self.skiptb = chk("Hide from taskbar / Alt+Tab", L().skip_taskbar, lambda v: self._set("skip_taskbar", v))
        f.addRow(self.borderless)
        f.addRow(self.ontop)
        f.addRow(self.skiptb)
        self.sort = combo([("Manual", "Manual order (Up / Down)"), ("Name", "By account name"), ("Launch", "By launch time")],
                          L().sort_mode, lambda d: self._set("sort_mode", d))
        f.addRow("Fill order", self.sort)
        self.auto = chk("Arrange new windows automatically", L().auto_capture, lambda v: self._set("auto_capture", v))
        self.auto_delay = spin(500, 30000, L().auto_capture_delay_ms, lambda v: self._set("auto_capture_delay_ms", v), " ms")
        f.addRow(row(self.auto, self.auto_delay))
        lv.addWidget(g)
        lv.addWidget(row(btn("Arrange now", self.arrange, icon="view-grid", primary=True),
                         btn("Restore borders", self.restore_borders),
                         btn("Screen wall", lambda: self.mw.open_screen_wall(),
                             tip="Live pictures of every background account in one window")))
        lv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(left)
        scroll.setMinimumWidth(left.sizeHint().width() + 24)
        split.addWidget(scroll)

        # ---- right: preview + list
        right = QWidget()
        rv = QVBoxLayout(right)
        self.preview = Preview()
        rv.addWidget(self.preview, 2)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["In grid", "Account", "PID", "Position / size", "State"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self.focus())
        rv.addWidget(self.tree, 3)
        rv.addWidget(row(btn("Refresh", self.refresh, icon="view-refresh"), btn("Up", lambda: self.move(-1), icon="go-up"),
                         btn("Down", lambda: self.move(1), icon="go-down"), btn("Focus", self.focus),
                         btn("Minimize", self.minimize), btn("Close", self.close_windows, icon="window-close")))
        self.info = QLabel("")
        self.info.setWordWrap(True)
        rv.addWidget(self.info)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        self._mode_ui()
        self._fill_saved()

    # ------------------------------------------------------------ settings
    def _set(self, attr, value):
        if self._loading:
            return
        setattr(store.settings.layout, attr, value)
        store.save_settings()
        self._mode_ui()
        self.update_preview()

    def _mode_ui(self):
        m = store.settings.layout.mode
        self.cols.setEnabled(m == "Grid")
        self.rows.setEnabled(m == "Grid")
        self.fw.setEnabled(m == "FixedSize")
        self.fh.setEnabled(m == "FixedSize")
        self.scale.setEnabled(m != "FixedSize")
        self.stretch.setEnabled(m != "FixedSize")

    # ------------------------------------------------------------ saved layouts
    def _fill_saved(self, select: str = ""):
        self.saved.clear()
        self.saved.addItem("(pick one)" if store.settings.saved_layouts else "(none yet - Save as...)", "")
        for n in store.settings.saved_layouts:
            self.saved.addItem(n.name, n.name)
        self.saved.setCurrentIndex(max(0, self.saved.findData(select)))

    def _use_saved(self, i: int):
        name = self.saved.itemData(i)
        n = next((x for x in store.settings.saved_layouts if x.name == name), None)
        if n is None:
            return
        store.settings.layout = clone(n.layout)
        store.save_settings()
        self.load()
        self.mw.log(f"Window layout '{name}' - press Arrange now to use it on the open windows.")

    def _save_layout(self):
        from PySide6.QtWidgets import QInputDialog
        cur = self.saved.currentData() or ""
        name, ok = QInputDialog.getText(self, "Save layout", "A name for this layout:",
                                        text=cur or f"Layout {len(store.settings.saved_layouts) + 1}")
        name = name.strip()
        if not ok or not name:
            return
        keep = [x for x in store.settings.saved_layouts if x.name != name]
        store.settings.saved_layouts = keep + [NamedLayout(name, clone(store.settings.layout))]
        store.save_settings()
        self._fill_saved(name)
        self.mw.log(f"Saved window layout '{name}'.")

    def _delete_layout(self):
        name = self.saved.currentData()
        if not name:
            return
        store.settings.saved_layouts = [x for x in store.settings.saved_layouts if x.name != name]
        store.save_settings()
        self._fill_saved()

    def load(self):
        """Puts the settings back into the widgets (after a preset was applied)."""
        self._loading = True
        L = store.settings.layout
        for w, v in ((self.cols, L.cols), (self.rows, L.rows), (self.fw, L.fixed_w), (self.fh, L.fixed_h),
                     (self.gap, L.gap), (self.margin, L.margin), (self.scale, L.scale), (self.minw, L.min_w),
                     (self.minh, L.min_h), (self.auto_delay, L.auto_capture_delay_ms)):
            w.setValue(v)
        for w, v in ((self.stretch, L.stretch_last), (self.workarea, L.use_work_area), (self.borderless, L.borderless),
                     (self.ontop, L.always_on_top), (self.skiptb, L.skip_taskbar), (self.auto, L.auto_capture)):
            w.setChecked(v)
        for w, v in ((self.mode, L.mode), (self.sort, L.sort_mode), (self.monitor, L.monitor)):
            i = w.findData(v)
            if i >= 0:
                w.setCurrentIndex(i)
        self._loading = False
        self._mode_ui()
        self.update_preview()

    # ------------------------------------------------------------ data
    def key_of(self, w: Win) -> int:
        t = sober.tracker_of_pid(w.pid)
        return t if t else -w.pid

    def account_of(self, w: Win):
        t = sober.tracker_of_pid(w.pid)
        return store.find_by_tracker(t) if t else None

    def screen(self) -> Optional[Screen]:
        if not self.screens:
            return None
        want = store.settings.layout.monitor
        return (next((s for s in self.screens if s.name == want), None)
                or next((s for s in self.screens if s.active), self.screens[0]))

    def area(self):
        s = self.screen()
        if s is None:
            return (0, 0, 1920, 1080), (0, 0, 1920, 1080)
        full = (s.x, s.y, s.w, s.h)
        return full, ((s.wx, s.wy, s.ww, s.wh) if store.settings.layout.use_work_area else full)

    def areas(self):
        """[(full, usable)] of every screen windows go on: all of them for "All monitors", else the one."""
        if store.settings.layout.monitor != "*" or len(self.screens) < 2:
            return [self.area()]
        work = store.settings.layout.use_work_area
        return [((s.x, s.y, s.w, s.h), (s.wx, s.wy, s.ww, s.wh) if work else (s.x, s.y, s.w, s.h))
                for s in self.screens]

    def compute(self, n: int):
        """(rects, overlap) for n windows on the chosen screen(s)."""
        areas = [a for _, a in self.areas()]
        L = store.settings.layout
        return layout.spread(n, areas, L) if len(areas) > 1 else layout.compute_rects(n, areas[0], L)

    def ordered(self) -> List[Win]:
        """Sober windows in grid order (only the ones in the grid)."""
        wins = [w for w in self.wins if self.key_of(w) not in self.excluded]
        mode = store.settings.layout.sort_mode
        if mode == "Name":
            wins.sort(key=lambda w: util.natural_key(self.account_of(w).name if self.account_of(w) else "~"))
        elif mode == "Launch":
            def started(w):
                inst = self.mw.launcher.find_by_tracker(self.key_of(w))
                return inst.started if inst else 1e18
            wins.sort(key=started)
        else:
            for w in wins:
                k = self.key_of(w)
                if k not in self.order:
                    self.order.append(k)
            wins.sort(key=lambda w: self.order.index(self.key_of(w)))
        return wins

    def refresh(self):
        kw = self.mw.kwin
        if kw is None or not kw.available():
            self.no_kwin.setVisible(True)
            return
        self.no_kwin.setVisible(False)
        self.wins = kw.windows()
        scr = kw.screens()
        if scr and [s.name for s in scr] != [s.name for s in self.screens]:
            self.screens = scr
            self._loading = True
            self.monitor.clear()
            self.monitor.addItem("The screen I am using", "")
            if len(scr) > 1:
                self.monitor.addItem(f"All monitors - spread out ({len(scr)} screens)", "*")
            for s in scr:
                self.monitor.addItem(s.label, s.name)
            i = self.monitor.findData(store.settings.layout.monitor)
            self.monitor.setCurrentIndex(max(0, i))
            self._loading = False
        elif scr:
            self.screens = scr
        sig = (tuple((w.id, w.x, w.y, w.w, w.h, w.minimized, w.active, w.no_border) for w in self.wins),
               tuple(sorted(self.excluded)), tuple(self.order), store.settings.layout.sort_mode)
        if sig != getattr(self, "_sig", None):      # only rebuild when something changed
            self._sig = sig
            self._fill_tree()
            self.update_preview()

    def _fill_tree(self):
        self._loading = True
        sel = {it.data(0, Qt.UserRole) for it in self.tree.selectedItems()}
        self.tree.clear()
        grid = self.ordered()
        rest = [w for w in self.wins if w not in grid]
        for w in grid + rest:
            a = self.account_of(w)
            name = a.name if a else "(not started by Cellar)"
            st = "minimized" if w.minimized else ("active" if w.active else "")
            if w.no_border:
                st = (st + ", borderless").strip(", ")
            it = QTreeWidgetItem(["", name, str(w.pid), f"{w.x},{w.y}  {w.w} x {w.h}", st])
            it.setData(0, Qt.UserRole, w.id)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Unchecked if self.key_of(w) in self.excluded else Qt.Checked)
            self.tree.addTopLevelItem(it)
            if w.id in sel:
                it.setSelected(True)
        self._loading = False
        self._info()

    def _info(self):
        many = self.areas()
        cap = sum(layout.capacity(a, store.settings.layout) for _, a in many)
        where = "these monitors" if len(many) > 1 else "this monitor"
        self.info.setText(f"{len(self.wins)} Sober window(s). Room for about {cap} windows of the smallest size on "
                          f"{where} without overlap.")

    def _item_changed(self, it, col):
        if self._loading or col != 0:
            return
        w = next((x for x in self.wins if x.id == it.data(0, Qt.UserRole)), None)
        if w is None:
            return
        k = self.key_of(w)
        if it.checkState(0) == Qt.Checked:
            self.excluded.discard(k)
        else:
            self.excluded.add(k)
        self.update_preview()

    def update_preview(self):
        many = self.areas()
        full, area = layout.bounds([f for f, _ in many]), layout.bounds([a for _, a in many])
        grid = self.ordered()
        n = max(1, len(grid)) if grid else (4 * len(many))
        rects, overlap = self.compute(n)
        self._info()
        labels = []
        for i in range(len(rects)):
            if i < len(grid):
                a = self.account_of(grid[i])
                labels.append(a.name if a else f"PID {grid[i].pid}")
            else:
                labels.append(f"example {i + 1}")
        self.preview.set(full, area, rects, labels, overlap)

    def selected_ids(self) -> List[str]:
        return [it.data(0, Qt.UserRole) for it in self.tree.selectedItems()]

    # ------------------------------------------------------------ actions
    def arrange(self, quiet: bool = False):
        kw = self.mw.kwin
        if kw is None or not kw.available():
            self.mw.log("Window layout needs KDE Plasma, Hyprland or Sway.")
            return
        self.wins = kw.windows()
        grid = self.ordered()
        if not grid:
            if not quiet:
                self.mw.log("No Sober windows to arrange.")
            self._fill_tree()
            return
        L = store.settings.layout
        rects, overlap = self.compute(len(grid))
        items = []
        for w, (x, y, ww, hh) in zip(grid, rects):
            items.append({"id": w.id, "x": x, "y": y, "w": ww, "h": hh, "noBorder": L.borderless,
                          "keepAbove": L.always_on_top, "skipTaskbar": L.skip_taskbar, "raise": overlap})
        kw.place(items)
        if not quiet:
            self.mw.log(f"Arranged {len(items)} window(s)" + (" (with overlap - not enough room)." if overlap else "."))
        QTimer.singleShot(600, self.refresh)

    def place_saved(self, rects: Dict[str, tuple]) -> None:
        """rects: window id -> (x, y, w, h, borderless, minimized) (used by presets)."""
        kw = self.mw.kwin
        items = []
        L = store.settings.layout
        for wid, (x, y, w, h, nb, _m) in rects.items():
            items.append({"id": wid, "x": x, "y": y, "w": w, "h": h, "noBorder": nb, "keepAbove": L.always_on_top,
                          "skipTaskbar": L.skip_taskbar})
        kw.place(items)
        mins = [wid for wid, r in rects.items() if r[5]]
        if mins:
            kw.minimize(mins)

    def restore_borders(self):
        if self.mw.kwin:
            self.mw.kwin.set_flags([w.id for w in self.mw.kwin.windows()], noBorder=False, keepAbove=False, skipTaskbar=False)
            self.mw.log("Borders, taskbar entries and stacking restored on all Sober windows.")
            QTimer.singleShot(400, self.refresh)

    def move(self, d: int):
        ids = self.selected_ids()
        if len(ids) != 1 or store.settings.layout.sort_mode != "Manual":
            if store.settings.layout.sort_mode != "Manual":
                self.mw.log("Up / Down needs the fill order 'Manual order'.")
            return
        w = next((x for x in self.wins if x.id == ids[0]), None)
        if w is None:
            return
        self.ordered()
        k = self.key_of(w)
        i = self.order.index(k)
        j = max(0, min(len(self.order) - 1, i + d))
        self.order[i], self.order[j] = self.order[j], self.order[i]
        self._fill_tree()
        self.update_preview()

    def focus(self):
        ids = self.selected_ids()
        if ids and self.mw.kwin:
            self.mw.kwin.activate(ids[0])

    def minimize(self):
        ids = self.selected_ids()
        if ids and self.mw.kwin:
            self.mw.kwin.minimize(ids)
            QTimer.singleShot(400, self.refresh)

    def close_windows(self):
        ids = set(self.selected_ids())
        if not ids:
            return
        for w in self.wins:
            if w.id not in ids:
                continue
            inst = self.mw.launcher.find_by_tracker(self.key_of(w))
            if inst:
                self.mw.stop_instances([inst])
            elif self.mw.kwin:
                self.mw.kwin.close([w.id])
        QTimer.singleShot(1500, self.refresh)

    # ------------------------------------------------------------ auto capture
    def auto_tick(self):
        """Called every couple of seconds by the main window."""
        L = store.settings.layout
        if not L.auto_capture or self.mw.kwin is None:
            return
        # only clients with a window on your desktop (background ones have none): asking KWin loads a script each
        # time, on the UI thread - not worth doing every 2 s while nothing could have opened a window
        ours = {i.tracker for i in self.mw.launcher.snapshot() if not i.screen}
        if not ours:
            self.seen = set()
            return
        wins = self.mw.kwin.windows()
        new = [w for w in wins if w.id not in self.seen and sober.tracker_of_pid(w.pid) in ours]
        self.seen = {w.id for w in wins}
        if new:
            self.capture_due = time.time() + L.auto_capture_delay_ms / 1000
        if self.capture_due and time.time() >= self.capture_due:
            self.capture_due = 0
            self.arrange(quiet=True)
