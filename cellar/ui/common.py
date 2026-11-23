"""Threading glue and small widget helpers."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from .. import log

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
                ui(lambda: err(ex))
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
def btn(text: str, slot=None, tip: str = "", icon: str = "", primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    if icon:
        b.setIcon(QIcon.fromTheme(icon))
    if slot:
        b.clicked.connect(lambda *_: slot())
    if tip:
        b.setToolTip(tip)
    if primary:
        b.setDefault(False)
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
