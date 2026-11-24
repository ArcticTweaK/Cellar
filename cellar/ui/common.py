"""Threading glue and small widget helpers."""

import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMenu,
                               QMessageBox, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from .. import log, theme

_pool = ThreadPoolExecutor(max_workers=10, thread_name_prefix="cellar")


class _Invoker(QObject):
    sig = Signal(object)

    def __init__(self):
        super().__init__()
        self.sig.connect(self._run, Qt.QueuedConnection)

    @staticmethod
    def _run(fn):
        try:
            fn()
        except Exception as ex:
            log.error("UI callback", ex)


_inv: Optional[_Invoker] = None


def init_threading() -> None:
    global _inv
    _inv = _Invoker()


def ui(fn: Callable[[], None]) -> None:
    """Run fn on the UI thread (safe to call from any thread)."""
    _inv.sig.emit(fn)


def bg(fn: Callable, *args, done: Callable = None, err: Callable = None) -> None:
    """Run fn(*args) on a worker thread; done(result) / err(exception) run back on the UI thread."""
    def run():
        try:
            r = fn(*args)
        except Exception as ex:
            log.error(getattr(fn, "__name__", "background task"), ex)
            if err:
                ui(lambda e=ex: err(e))     # bind it now: Python deletes `ex` when the except block ends
            return
        if done:
            ui(lambda: done(r))
    _pool.submit(run)


def app_icon() -> QIcon:
    here = Path(__file__).resolve().parent.parent
    for p in (here / "data" / "cellar.png", here.parent / "data" / "cellar.png"):
        if p.exists():
            return QIcon(str(p))
    return QIcon.fromTheme("applications-games")


# ---------------------------------------------------------------- widgets
_icon_buttons: list = []


# A menu or dialog made with a parent stays that parent's child until the parent dies - for the main window, until
# Cellar quits (tools/soak.py: +60 widgets / +520 Qt objects per round of right-clicks before this). deleteLater()
# right after exec() frees it once control is back in the event loop that called exec(): the code after exec()
# can still read the dialog, even across a message box (Qt's rule; WA_DeleteOnClose fires inside the dialog's own
# loop instead, so a later message box could free it under you).
def popup(m: QMenu, pos) -> None:
    """Shows a one-off menu (right-click, Play with...) and frees it afterwards. Not a QMenu subclass: exec() on
    any Python subclass of QMenu segfaults in PySide 6.12. Not aboutToHide -> deleteLater either: a dialog popping
    up while the menu is open would close it inside the dialog's loop and free it while QMenu.exec still runs."""
    try:
        m.exec(pos)
    finally:
        m.deleteLater()


class Dialog(QDialog):
    """Base of Cellar's own dialogs: exec() once, then it frees itself (see above)."""

    def exec(self) -> int:
        try:
            return super().exec()
        finally:
            self.deleteLater()


def _icon_token(primary: bool) -> str:
    # filled accent buttons only exist in Cellar's own themes; System keeps the desktop's normal buttons
    return "on_accent" if primary and theme.current().key != "system" else "text"


def refresh_icons() -> None:
    """After a theme change: buttons get their icon again in the new colours."""
    alive = []
    for ref, name, primary in _icon_buttons:
        b = ref()
        try:
            if b is not None:
                b.setIcon(theme.icon(name, _icon_token(primary)))
                alive.append((ref, name, primary))
        except RuntimeError:        # the Qt object is gone
            pass
    _icon_buttons[:] = alive


def btn(text: str, slot=None, tip: str = "", icon: str = "", primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    if icon and (theme._ICON_SRC / f"{icon}.svg").exists():
        # only Cellar's own icon set: desktop icon themes mixed styles (and differ on every distro)
        b.setIcon(theme.icon(icon, _icon_token(primary)))
        _icon_buttons.append((weakref.ref(b), icon, primary))
        if len(_icon_buttons) % 256 == 0:           # dialogs come and go: drop buttons that are gone
            _icon_buttons[:] = [x for x in _icon_buttons if x[0]() is not None]
    if slot:
        b.clicked.connect(lambda *_: slot())
    if tip:
        b.setToolTip(tip)
    if primary:
        b.setDefault(False)
        b.setProperty("primary", True)
        f = b.font()
        f.setBold(True)
        b.setFont(f)
    return b


def chk(text: str, checked: bool, on_change=None, tip: str = "") -> QCheckBox:
    c = QCheckBox(text)
    c.setChecked(bool(checked))
    if tip:
        c.setToolTip(tip)
    if on_change:
        c.toggled.connect(on_change)
    return c


def spin(lo: int, hi: int, val: int, on_change=None, suffix: str = "", tip: str = "", special: str = "") -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(int(val))
    if suffix:
        s.setSuffix(suffix)
    if special:
        s.setSpecialValueText(special)
    if tip:
        s.setToolTip(tip)
    if on_change:
        s.valueChanged.connect(on_change)
    theme.pad_spin(s)
    return s


def combo(items, current=None, on_change=None, tip: str = "") -> QComboBox:
    """items: list of (data, label) or plain strings."""
    c = QComboBox()
    for it in items:
        if isinstance(it, tuple):
            c.addItem(it[1], it[0])
        else:
            c.addItem(str(it), it)
    if current is not None:
        i = c.findData(current)
        if i >= 0:
            c.setCurrentIndex(i)
    if tip:
        c.setToolTip(tip)
    if on_change:
        c.currentIndexChanged.connect(lambda *_: on_change(c.currentData()))
    return c


def row(*widgets, stretch: bool = True) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        if isinstance(x, str):
            h.addWidget(QLabel(x))
        elif x is None:
            h.addStretch(1)
        else:
            h.addWidget(x)
    if stretch:
        h.addStretch(1)
    return w


def hint(text: str) -> QLabel:
    l = QLabel(text)
    l.setWordWrap(True)
    l.setTextFormat(Qt.RichText)
    l.setOpenExternalLinks(True)
    l.setStyleSheet("color: palette(placeholder-text);")
    l.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    return l


def group(title: str):
    """Returns (QGroupBox, QFormLayout)."""
    g = QGroupBox(title)
    f = QFormLayout(g)
    f.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    return g, f


def vbox(parent: QWidget = None) -> QVBoxLayout:
    v = QVBoxLayout(parent) if parent else QVBoxLayout()
    return v


def ask(parent, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes


def info(parent, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def warn(parent, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)
