"""Live view of a background account's invisible screen (VNC), with input and macro recording."""

import threading
import time
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
        self.status.setText(f"Saved macro '{name}' - edit or run it on the Macros tab.")
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
