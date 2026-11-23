"""Macros tab: write / check / run macros for background accounts."""

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton,
                               QSplitter, QVBoxLayout, QWidget)

from .. import macros, store
from ..models import Macro
from .common import hint


class MacrosPage(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        v = QVBoxLayout(self)
        v.addWidget(hint("Macros run on accounts in <b>background mode</b> (Edit account &gt; Run in the background): "
                         "each one on its own invisible screen, so one alt can do one thing while another does "
                         "something else and your desktop stays yours. Record one from <i>View screen</i>, or write "
                         "it here. Automating input is against Roblox's rules - only on accounts you can lose."))
        split = QSplitter()
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._pick)
        lv.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, fn in (("New", self._new), ("Duplicate", self._dup), ("Delete", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        lv.addLayout(row)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(QLabel("Name"))
        self.name = QLineEdit()
        top.addWidget(self.name, 1)
        self.loop = QCheckBox("Loop until stopped")
        top.addWidget(self.loop)
        rv.addLayout(top)
        self.text = QPlainTextEdit()
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.text.setPlaceholderText("tap space\nwait 1000")
        rv.addWidget(self.text, 1)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        rv.addWidget(self.result)
        row = QHBoxLayout()
        for text, fn in (("Check", self._check), ("Save", self._save),
                         ("Run on selected accounts", self._run), ("Stop on selected accounts", self._stop)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        rv.addLayout(row)
        help_ = QLabel("<pre>" + macros.HELP.replace("&", "&amp;").replace("<", "&lt;") + "</pre>")
        help_.setTextInteractionFlags(help_.textInteractionFlags())
        rv.addWidget(help_)
        split.addWidget(right)
        split.setSizes([220, 700])
        v.addWidget(split, 1)
        self.load()

    # ---- list
    def load(self, select: str = ""):
        cur = select or (self.list.currentItem().text() if self.list.currentItem() else "")
        self.list.blockSignals(True)
        self.list.clear()
        names = [m.name for m in store.settings.macros]
        self.list.addItems(names)
        self.list.blockSignals(False)
        self.list.setCurrentRow(names.index(cur) if cur in names else (0 if names else -1))
        self._pick(self.list.currentRow())

    def _current(self):
        r = self.list.currentRow()
        return store.settings.macros[r] if 0 <= r < len(store.settings.macros) else None

    def _pick(self, _row):
        m = self._current()
        self.name.setText(m.name if m else "")
        self.loop.setChecked(m.loop if m else True)
        self.text.setPlainText(m.text if m else "")
        self.result.setText("")

    def _unique(self, base: str) -> str:
        names = {m.name for m in store.settings.macros}
        n, i = base, 2
        while n in names:
            n, i = f"{base} {i}", i + 1
        return n

    def _new(self):
        m = Macro(name=self._unique("New macro"), text="tap space\nwait 1000\n", loop=True)
        store.settings.macros.append(m)
        store.save_settings()
        self.load(m.name)

    def _dup(self):
        m = self._current()
        if m:
            c = Macro(name=self._unique(m.name + " copy"), text=m.text, loop=m.loop)
            store.settings.macros.append(c)
            store.save_settings()
            self.load(c.name)

    def _delete(self):
        m = self._current()
        if m:
            store.settings.macros.remove(m)
            store.save_settings()
            self.load()

    # ---- edit
    def _check(self) -> bool:
        steps, errors = macros.parse(self.text.toPlainText())
        if errors:
            self.result.setText("<span style='color:#c0392b'>" + "<br>".join(errors) + "</span>")
            return False
        self.result.setText(f"OK - {len(steps)} steps.")
        return True

    def _save(self):
        m = self._current()
        if not m or not self._check():
            return
        name = self.name.text().strip() or m.name
        if name != m.name and any(x.name == name for x in store.settings.macros):
            self.result.setText("Another macro already has that name.")
            return
        for a in store.accounts:                    # keep auto-start links working after a rename
            if a.auto_macro == m.name:
                a.auto_macro = name
        m.name, m.loop, m.text = name, self.loop.isChecked(), self.text.toPlainText()
        store.save_settings()
        store.save_accounts()
        self.load(name)
        self.result.setText("Saved.")

    # ---- run
    def _targets(self):
        out = []
        for a in self.mw.selected_accounts():
            out += [i for i in self.mw.launcher.instances_of(a) if i.screen]
        return out

    def _run(self):
        m = self._current()
        if not m:
            return
        self._save()
        insts = self._targets()
        if not insts:
            self.mw.log("Select running background accounts first (Edit account > Run in the background, then launch).")
            return
        for i in insts:
            self.mw.launcher.start_macro(i, m.name, self.mw.log)

    def _stop(self):
        n = sum(1 for i in self._targets() if self.mw.launcher.stop_macro(i))
        self.mw.log(f"Stopped {n} macro(s)." if n else "No macros were running on the selected accounts.")
