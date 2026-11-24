"""Roblox logs window: the Roblox client's own log (and Sober's) of your normal Sober or of any account's profile.

"What happened" is the default view: joins, teleports, leaves, disconnects and the errors of Roblox / Sober
themselves (robloxlog.LogLine.worth_showing) - a few dozen lines out of thousands, most of which are the game's
own script errors and engine chatter. "Copy for a bug report" removes cookies (crash.scrub).
"""

from typing import List, Optional

from PySide6.QtGui import QGuiApplication, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout

from .. import __version__, crash, robloxlog, sober, store, theme
from ..models import Account
from .common import Dialog, bg, btn, hint

_SHOW = (("what", "What happened"), ("errors", "All errors (also the game's own)"), ("all", "Everything"))


class _Colours(QSyntaxHighlighter):
    """ERROR / WARN tags and plain-word events in the theme's colours."""

    def highlightBlock(self, text: str):
        for tag, token in (("ERROR", "bad"), ("WARN ", "warn"), ("  >> ", "good")):
            i = text.find(tag, 0, 20)
            if i >= 0:
                f = QTextCharFormat()
                f.setForeground(theme.qc(token))
                self.setFormat(i, len(tag), f)
                if tag == "  >> ":
                    self.setFormat(i, len(text) - i, f)
        if len(text) > 8 and text[2:3] == ":":         # the time in front, quieter
            f = QTextCharFormat()
            f.setForeground(theme.qc("muted"))
            self.setFormat(0, 8, f)


class RobloxLogDialog(Dialog):
    def __init__(self, mw, account: Optional[Account] = None):
        super().__init__(mw)
        self.mw = mw
        self.lines: List[robloxlog.LogLine] = []
        self.total = 0
        self.setWindowTitle("Roblox logs")
        self.resize(1000, 680)
        v = QVBoxLayout(self)
        v.addWidget(hint("Roblox's own log of a session: when it joined, left or was disconnected, and what went "
                         "wrong. Sober keeps the last few sessions."))
        top = QHBoxLayout()
        self.source = QComboBox()
        self.source.addItem("Your normal Sober", "")
        for a in store.accounts:
            if (sober.profile_app(a) / "data" / "sober").is_dir():
                self.source.addItem(f"{a.name} (its own profile)", a.id)
        if account is not None:
            i = self.source.findData(account.id)
            self.source.setCurrentIndex(max(0, i))
        self.source.currentIndexChanged.connect(lambda *_: self._fill_files())
        self.file = QComboBox()
        self.file.currentIndexChanged.connect(lambda *_: self._load())
        top.addWidget(self.source)
        top.addWidget(self.file, 1)
        top.addWidget(btn("", self._load, icon="refresh-cw", tip="Read the file again (a running game keeps writing)"))
        v.addLayout(top)
        bar = QHBoxLayout()
        self.show_ = QComboBox()
        for key, label in _SHOW:
            self.show_.addItem(label, key)
        self.show_.currentIndexChanged.connect(lambda *_: self._render())
        self.find = QLineEdit()
        self.find.setPlaceholderText("Search this log...")
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(lambda *_: self._render())
        bar.addWidget(self.show_)
        bar.addWidget(self.find, 1)
        v.addLayout(bar)
        self.view = QPlainTextEdit()
        self.view.setObjectName("log")
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.view.setFont(theme.mono_font(max(7.5, self.font().pointSizeF() - 1)))
        self._hl = _Colours(self.view.document())
        v.addWidget(self.view, 1)
        self.status = QLabel("")
        self.status.setObjectName("stat_sub")
        v.addWidget(self.status)
        v.addLayout(_row(btn("Copy for a bug report", self._copy, primary=True,
                             tip="What is shown, with Cellar / Sober versions on top and cookies removed"),
                         btn("Open the folder", self._open_folder), None, btn("Close", self.reject)))
        self._fill_files()

    # ---- files
    def _app(self):
        aid = self.source.currentData()
        a = store.find_by_id(aid) if aid else None
        return sober.profile_app(a) if a else sober.main_app()

    def _fill_files(self):
        self.file.blockSignals(True)
        self.file.clear()
        for label, path in robloxlog.log_files(self._app()):
            self.file.addItem(label, str(path))
        self.file.blockSignals(False)
        if not self.file.count():
            self.lines, self.total = [], 0
            self.view.setPlainText("")
            self.status.setText("No logs here yet - they appear after the first time Roblox runs from this "
                                "profile (accounts' own profiles drop old logs when they are created).")
            return
        self._load()

    def _load(self):
        path = self.file.currentData()
        if not path:
            return
        self.status.setText("Reading...")
        from pathlib import Path

        def done(res):
            self.lines, self.total = res
            self._render()
        bg(robloxlog.read_log, Path(path), done=done)

    # ---- view
    def _shown(self) -> List[robloxlog.LogLine]:
        mode, q = self.show_.currentData(), self.find.text().strip().lower()
        out = []
        for ln in self.lines:
            if mode == "what" and not ln.worth_showing:
                continue
            if mode == "errors" and ln.severity != "error" and not ln.event:
                continue
            if q and q not in ln.text.lower() and q not in ln.event.lower():
                continue
            out.append(ln)
        return out

    @staticmethod
    def _fmt(ln: robloxlog.LogLine) -> str:
        tag = {"error": "ERROR", "warning": "WARN "}.get(ln.severity, "     ")
        if ln.event:
            return f"{ln.time or '        '}  >> {ln.event}"
        return f"{ln.time or '        '}  {tag}  {ln.text}"

    def _render(self):
        shown = self._shown()
        out: List[str] = []
        prev, repeat = None, 1
        for ln in shown:                    # the same line again and again: once, with "(4x)"
            text = self._fmt(ln)
            if text == prev:
                repeat += 1
                out[-1] = f"{text}  ({repeat}x)"
            else:
                prev, repeat = text, 1
                out.append(text)
        self.view.setPlainText("\n".join(out))
        errs = sum(1 for ln in self.lines if ln.severity == "error")
        noise = sum(1 for ln in self.lines if ln.severity == "error" and ln.noise)
        cut = (f" (the newest {robloxlog.MAX_LINES:,} of {self.total:,})" if self.total > robloxlog.MAX_LINES else "")
        empty = ("" if shown else "  ·  nothing to show - try Everything" if self.lines else "")
        self.status.setText(f"{len(shown):,} shown · {len(self.lines):,} lines{cut} · {errs:,} errors, of which "
                            f"{noise:,} are the game's own or engine chatter{empty}")

    # ---- actions
    def _copy(self):
        head = (f"Cellar {__version__} · Sober {sober.sober_version() or '?'} · Roblox "
                f"{sober.app_version(self._app()) or '?'} · {self.file.currentText()} · "
                f"{self.show_.currentText()}" + (f" · search '{self.find.text()}'" if self.find.text() else ""))
        text = crash.scrub(head + "\n\n" + self.view.toPlainText())
        QGuiApplication.clipboard().setText(text)
        self.status.setText(f"Copied {len(text.splitlines()) - 2:,} lines (cookies removed) - paste them into "
                            "your bug report.")

    def _open_folder(self):
        path = self.file.currentData()
        from pathlib import Path
        sober.open_folder(Path(path).parent if path else robloxlog.logs_folder(self._app()))


def _row(*widgets) -> QHBoxLayout:
    h = QHBoxLayout()
    for w in widgets:
        if w is None:
            h.addStretch(1)
        else:
            h.addWidget(w)
    return h
