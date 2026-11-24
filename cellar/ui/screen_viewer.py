"""Live view of a background account's invisible screen (VNC), with input and macro recording."""

import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from .. import background, log, macros, store
from ..models import Instance, Macro

_QT_KEYS = {
    Qt.Key_Space: "space", Qt.Key_Return: "enter", Qt.Key_Enter: "enter", Qt.Key_Escape: "esc", Qt.Key_Tab: "tab",
    Qt.Key_Backspace: "backspace", Qt.Key_Delete: "delete", Qt.Key_Insert: "insert", Qt.Key_Home: "home",
    Qt.Key_End: "end", Qt.Key_PageUp: "pageup", Qt.Key_PageDown: "pagedown", Qt.Key_Left: "left", Qt.Key_Up: "up",
    Qt.Key_Right: "right", Qt.Key_Down: "down", Qt.Key_Shift: "shift", Qt.Key_Control: "ctrl", Qt.Key_Alt: "alt",
    Qt.Key_CapsLock: "capslock",
}
_QT_KEYS.update({getattr(Qt, f"Key_F{i}"): f"f{i}" for i in range(1, 13)})


def key_name(ev) -> Optional[str]:
    k = ev.key()
    if Qt.Key_A <= k <= Qt.Key_Z:
        return chr(ord("a") + k - Qt.Key_A)
    if Qt.Key_0 <= k <= Qt.Key_9:
        return chr(ord("0") + k - Qt.Key_0)
    if k in _QT_KEYS:
        return _QT_KEYS[k]
    t = ev.text()
    return t if len(t) == 1 and 0x20 < ord(t) < 0x7F else None


class _Frames(QObject):
    frame = Signal(QImage)
    failed = Signal(str)


class Canvas(QWidget):
    """Draws the remote screen scaled to fit and turns mouse / keys into VNC input."""

    def __init__(self, parent, on_event: Callable[[str, object], None]):
        super().__init__(parent)
        self.img: Optional[QImage] = None
        self.on_event = on_event
        self.on_pos: Optional[Callable[[tuple], None]] = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(640, 360)
        self._last_move = 0.0

    def target(self) -> QRect:
        if not self.img:
            return self.rect()
        s = self.img.size().scaled(self.size(), Qt.KeepAspectRatio)
        return QRect(QPoint((self.width() - s.width()) // 2, (self.height() - s.height()) // 2), s)

    def map(self, p) -> Optional[tuple]:
        r = self.target()
        if not self.img or not r.contains(p.toPoint()):
            return None
        return (int((p.x() - r.x()) * self.img.width() / r.width()),
                int((p.y() - r.y()) * self.img.height() / r.height()))

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(20, 20, 20))
        if self.img:
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(self.target(), self.img)
        else:
            p.setPen(QColor(200, 200, 200))
            p.drawText(self.rect(), Qt.AlignCenter, "Connecting to its screen...")

    def focusNextPrevChild(self, _next):        # Tab goes to the game, not to the next button
        return False

    def mouseMoveEvent(self, ev):
        xy = self.map(ev.position())
        if xy and self.on_pos:
            self.on_pos(xy)
        if xy and time.time() - self._last_move > 0.02:
            self._last_move = time.time()
            self.on_event("move", xy)

    def mousePressEvent(self, ev):
        self.setFocus()
        xy = self.map(ev.position())
        if xy:
            self.on_event("press", (xy, {Qt.LeftButton: 1, Qt.MiddleButton: 2, Qt.RightButton: 3}.get(ev.button(), 1)))

    def mouseReleaseEvent(self, ev):
        xy = self.map(ev.position())
        if xy:
            self.on_event("release", (xy, {Qt.LeftButton: 1, Qt.MiddleButton: 2, Qt.RightButton: 3}.get(ev.button(), 1)))

    def wheelEvent(self, ev):
        xy = self.map(ev.position())
        if xy:
            self.on_event("scroll", (xy, ev.angleDelta().y() > 0))

    def keyPressEvent(self, ev):
        n = key_name(ev)
        if n and not ev.isAutoRepeat():
            self.on_event("down", n)

    def keyReleaseEvent(self, ev):
        n = key_name(ev)
        if n and not ev.isAutoRepeat():
            self.on_event("up", n)


class ScreenViewer(QDialog):
    def __init__(self, parent, inst: Instance, logf: Callable[[str], None], macros_changed: Callable[[], None]):
        super().__init__(parent)
        self.inst, self.logf, self.macros_changed = inst, logf, macros_changed
        self.setWindowTitle(f"{inst.account.name} - background screen")
        self.resize(1000, 640)
        self.vnc: Optional[background.VNC] = None
        self._stop = threading.Event()
        self.recording: Optional[List[tuple]] = None
        self.buttons = 0

        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.rec = QPushButton("Record a macro")
        self.rec.setCheckable(True)
        self.rec.toggled.connect(self._toggle_record)
        macro_on = bool(inst.macro and inst.macro.running)
        self.control = QCheckBox("Control it")
        self.control.setToolTip("Off = only watch: your mouse and keys are not sent, so a running macro\n"
                                "(and its mouse position) is left alone. The picture shows the account's own cursor.")
        self.control.setChecked(not macro_on)
        self.control.toggled.connect(self._control_changed)
        self.used_input = False
        self.status = QLabel("")
        bar.addWidget(self.control)
        bar.addWidget(self.rec)
        shot = QPushButton("Screenshot")
        shot.setToolTip("Saves what this screen shows now to your Pictures folder (Cellar)")
        shot.clicked.connect(self.screenshot)
        bar.addWidget(shot)
        bar.addWidget(self.status, 1)
        self.pos = QLabel("mouse: -")
        self.pos.setToolTip("Where the mouse is on this account's 1280x720 screen.\n"
                            "Use the numbers in macros:  move X Y  /  click X Y  /  rclick X Y")
        self.pos.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bar.addWidget(self.pos)
        v.addLayout(bar)
        self.canvas = Canvas(self, self._input)
        self.canvas.on_pos = lambda xy: self.pos.setText(f"mouse: x {xy[0]}  y {xy[1]}")
        v.addWidget(self.canvas, 1)

        self._control_changed(self.control.isChecked())
        self.sig = _Frames()
        self.sig.frame.connect(self._show)
        self.sig.failed.connect(lambda m: self.status.setText("No connection to its screen: " + m))
        threading.Thread(target=self._reader, daemon=True, name="screen viewer").start()

    # ---- frames (worker thread)
    def _reader(self):
        try:
            self.vnc = background.VNC(self.inst.screen.vnc, timeout=10)
            v = self.vnc
            v.request(False)
            last = 0.0
            while not self._stop.is_set():
                if v.read_update():
                    now = time.time()
                    if now - last > 0.03:                   # up to ~30 fps, the alts' default cap
                        last = now
                        self.sig.frame.emit(QImage(bytes(v.fb), v.width, v.height, v.width * 4,
                                                   QImage.Format_RGB32).copy())
                    v.request(True)
        except Exception as ex:
            if not self._stop.is_set():
                log.write(f"screen viewer: {ex}")
                self.sig.failed.emit(str(ex))

    def _show(self, img: QImage):
        self.canvas.img = img
        self.canvas.update()

    def screenshot(self):
        from PySide6.QtCore import QStandardPaths
        img = self.canvas.img
        if img is None:
            self.status.setText("No picture yet.")
            return
        base = Path(QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or Path.home()) / "Cellar"
        base.mkdir(parents=True, exist_ok=True)
        f = base / f"{self.inst.account.name}-{time.strftime('%Y-%m-%d_%H-%M-%S')}.png"
        if img.save(str(f)):
            self.status.setText(f"Saved {f.name}")
            self.logf(f"[{self.inst.account.name}] screenshot saved: {f}")
        else:
            self.status.setText("Could not save the screenshot.")

    # ---- input
    def _control_changed(self, on: bool):
        if on:
            self.status.setText("Controlling it: your mouse and keys in the picture go to this account "
                                "(your own desktop is not touched).")
        else:
            running = self.inst.macro and self.inst.macro.running
            self.status.setText(("Watching only - the macro keeps control, the cursor you see is the account's own. "
                                 if running else "Watching only. ") + "Tick 'Control it' to take over.")
        if not on and self.rec.isChecked():
            self.rec.setChecked(False)

    def _input(self, kind: str, data):
        v = self.vnc
        if not v or not self.control.isChecked():
            return
        self.used_input = True
        t = time.time()
        try:
            if kind == "move":
                v.pointer(*data)
            elif kind in ("press", "release"):
                (x, y), b = data
                mask = {1: 1, 2: 2, 3: 4}[b]
                self.buttons = self.buttons | mask if kind == "press" else self.buttons & ~mask
                v.pointer(x, y, self.buttons)
                if self.recording is not None and kind == "press" and b in (1, 3):
                    self.recording.append((t, "click" if b == 1 else "rclick", (x, y)))
            elif kind == "scroll":
                (x, y), up = data
                v.scroll(x, y, up)
            elif kind in ("down", "up"):
                v.key(background.keysym(data), kind == "down")
                if self.recording is not None:
                    self.recording.append((t, kind, data))
        except Exception as ex:
            self.status.setText(f"Input failed: {ex}")

    # ---- recording
    def _toggle_record(self, on: bool):
        if on:
            self.control.setChecked(True)          # recording means you are playing it
            self.recording = []
            self.rec.setText("Stop recording")
            self.status.setText("Recording: everything you do in the picture (keys, clicks, timing) becomes a macro.")
            self.canvas.setFocus()
            return
        events, self.recording = self.recording or [], None
        self.rec.setText("Record a macro")
        text = macros.from_recording(events)
        if not text.strip():
            self.status.setText("Nothing was recorded.")
            return
        name, ok = QInputDialog.getText(self, "Save macro", f"Recorded {len(events)} actions. Name of the macro:",
                                        text=f"Recorded {time.strftime('%H:%M')}")
        if not ok or not name.strip():
            self.status.setText("Recording thrown away.")
            return
        name = name.strip()
        store.settings.macros = [m for m in store.settings.macros if m.name != name]
        store.settings.macros.append(Macro(name=name, text=text + "wait 1000\n", loop=True))
        store.save_settings()
        self.macros_changed()
        self.status.setText(f"Saved macro '{name}' - edit or run it on the Macros page.")
        self.logf(f"Saved macro '{name}' ({len(events)} recorded actions).")

    def done(self, r):
        self._stop.set()
        if self.vnc:
            if self.used_input:                         # only clean up input you actually sent
                try:
                    for k in ("shift", "ctrl", "alt"):  # never leave a modifier held down
                        self.vnc.key(background.keysym(k), False)
                    if self.buttons:
                        self.vnc.pointer(self.vnc.x, self.vnc.y, 0)
                except Exception:
                    pass
            self.vnc.close()
        super().done(r)


class _Tile(QWidget):
    """One background account on the screen wall: a small live picture, about one frame a second."""

    clicked = Signal()
    FPS = 1.0

    def __init__(self, inst: Instance):
        super().__init__()
        self.inst = inst
        self.img: Optional[QImage] = None
        self.error = ""
        self._stop = threading.Event()
        self.sig = _Frames()
        self.sig.frame.connect(self._show)
        self.sig.failed.connect(self._failed)
        self.setMinimumSize(256, 168)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to open its screen")
        threading.Thread(target=self._reader, daemon=True, name="screen wall").start()

    def _reader(self):
        v = None
        try:
            v = background.VNC(self.inst.screen.vnc, timeout=10)
            v.request(False)
            while not self._stop.is_set():
                if v.read_update():
                    # scaled down here, on the worker thread: the UI thread only draws small pictures
                    self.sig.frame.emit(QImage(bytes(v.fb), v.width, v.height, v.width * 4, QImage.Format_RGB32)
                                        .scaled(480, 270, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    if self._stop.wait(1.0 / self.FPS):
                        break
                    v.request(True)
        except Exception as ex:
            if not self._stop.is_set():
                self.sig.failed.emit(str(ex))
        finally:
            if v:
                v.close()

    def stop(self):
        self._stop.set()

    def _show(self, img: QImage):
        self.img, self.error = img, ""
        self.update()

    def _failed(self, msg: str):
        self.error = msg
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _):
        from .. import theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        bar = 26
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(theme.qc("border"))
        p.setBrush(theme.qc("surface"))
        p.drawRoundedRect(r, 8, 8)
        pic = QRect(r.x() + 6, r.y() + 6, r.width() - 12, r.height() - bar - 12)
        if self.img:
            s = self.img.size().scaled(pic.size(), Qt.KeepAspectRatio)
            p.drawImage(QRect(QPoint(pic.x() + (pic.width() - s.width()) // 2,
                                     pic.y() + (pic.height() - s.height()) // 2), s), self.img)
        else:
            p.fillRect(pic, QColor(12, 12, 14))
            p.setPen(theme.qc("muted"))
            p.drawText(pic, Qt.AlignCenter | Qt.TextWordWrap,
                       "No picture: " + self.error if self.error else "Connecting...")
        p.setPen(theme.qc("text"))
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRect(r.x() + 10, r.bottom() - bar, r.width() - 20, bar - 4), Qt.AlignVCenter | Qt.AlignLeft,
                   self.inst.account.name)
        badge = "❄ frozen" if self.inst.frozen else ("● macro" if self.inst.macro and self.inst.macro.running else "")
        if badge:
            f.setBold(False)
            p.setFont(f)
            p.setPen(theme.qc("warn" if self.inst.frozen else "accent"))
            p.drawText(QRect(r.x() + 10, r.bottom() - bar, r.width() - 20, bar - 4),
                       Qt.AlignVCenter | Qt.AlignRight, badge)


class ScreenWall(QDialog):
    """Every background account's screen in one window. Click one to open it (watch, control, record)."""

    def __init__(self, mw):
        super().__init__(mw)
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QGridLayout, QScrollArea
        self.mw = mw
        self.setWindowTitle("Screen wall - background accounts")
        self.resize(1180, 760)
        v = QVBoxLayout(self)
        self.info = QLabel()
        v.addWidget(self.info)
        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        self.grid = QGridLayout(inner)
        self.grid.setSpacing(10)
        area.setWidget(inner)
        v.addWidget(area, 1)
        self.tiles: dict = {}
        self.cols = 0
        self.timer = QTimer(self, interval=2000, timeout=self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self):
        insts = [i for i in self.mw.launcher.alive_instances() if i.screen]
        live = {id(i) for i in insts}
        for key in [k for k in self.tiles if k not in live]:
            t = self.tiles.pop(key)
            t.stop()
            t.deleteLater()
        for i in insts:
            if id(i) not in self.tiles:
                t = _Tile(i)
                t.clicked.connect(lambda inst=i: self.mw.view_screen(inst))
                self.tiles[id(i)] = t
        order = sorted(insts, key=lambda i: i.account.order)
        cols = max(1, min(4, (self.width() - 40) // 280))
        for t in self.tiles.values():
            self.grid.removeWidget(t)
        tile_w = (self.width() - 60 - 10 * (cols - 1)) // cols
        for n, i in enumerate(order):
            t = self.tiles[id(i)]
            t.setFixedHeight(max(168, tile_w * 9 // 16 + 38))      # 16:9 picture + name bar
            self.grid.addWidget(t, n // cols, n % cols)
        self.grid.setRowStretch(self.grid.rowCount(), 1)
        for t in self.tiles.values():
            t.update()                      # badges (macro / frozen)
        self.info.setText(f"{len(insts)} background account(s) - about one picture a second each. Click one to open "
                          "its screen." if insts else
                          "No account runs in the background. Edit an account > Run in the background, then launch it.")

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.refresh()

    def done(self, r):
        self.timer.stop()
        for t in self.tiles.values():
            t.stop()
        super().done(r)
