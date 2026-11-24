"""Macros tab: write / check / run macros for background accounts."""

import re
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import (QColor, QFont, QKeySequence, QShortcut, QSyntaxHighlighter, QTextCharFormat, QTextCursor,
                           QTextFormat)

from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPlainTextEdit,
                               QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget)

from .. import macros, store, theme
from ..models import Macro
from .common import btn, hint, ui


_OPS = {"tap", "down", "up", "key", "type", "click", "rclick", "move", "scroll", "wait", "repeat", "random", "stop"}


class MacroHighlighter(QSyntaxHighlighter):
    """Steps in the accent colour, numbers and times highlighted, comments grey, unknown steps red."""

    def __init__(self, doc):
        super().__init__(doc)
        self.bad_lines: set = set()

    def _fmt(self, token: str, bold: bool = False) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(theme.qc(token))
        if bold:
            f.setFontWeight(QFont.Bold)
        return f

    def highlightBlock(self, text: str):
        stripped = text.lstrip()
        start = len(text) - len(stripped)
        if not stripped:
            return
        if stripped.startswith("#"):
            self.setFormat(0, len(text), self._fmt("muted"))
            return
        op = stripped.split(" ", 1)[0]
        known = op.lower() in _OPS or op == "}"
        self.setFormat(start, len(op), self._fmt("accent" if known else "bad", bold=True))
        if op.lower() == "type":                # the rest is literal text, '#' included
            return
        body = stripped[len(op):]
        hash_at = body.find("#")
        code = body if hash_at < 0 else body[:hash_at]
        for m in re.finditer(r"\b\d+(?:-\d+)?(?:ms|s|m|h)?\b|[{}]", code):
            self.setFormat(start + len(op) + m.start(), m.end() - m.start(),
                           self._fmt("accent" if m.group() in "{}" else "warn"))
        if hash_at >= 0:
            self.setFormat(start + len(op) + hash_at, len(body) - hash_at, self._fmt("muted"))
        if self.currentBlock().blockNumber() + 1 in self.bad_lines:     # keep the colours, add a red wave
            for i in range(start, len(text)):
                cur = self.format(i)
                cur.setUnderlineStyle(QTextCharFormat.WaveUnderline)
                cur.setUnderlineColor(theme.qc("bad"))
                self.setFormat(i, 1, cur)


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
        row = QHBoxLayout()
        for text, fn, tip in (("Import...", self._import, "Load macros from .txt files (shared by friends)"),
                              ("Export...", self._export, "Save this macro as a .txt file to share")):
            b = QPushButton(text)
            b.setToolTip(tip)
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
        self.text.setFont(theme.mono_font())
        self.text.setPlaceholderText("tap space\nwait 1000")
        self.hl = MacroHighlighter(self.text.document())
        self._live = QTimer(self, singleShot=True, interval=400, timeout=lambda: self._check(live=True))
        self.text.textChanged.connect(self._live.start)
        rv.addWidget(self.text, 1)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        rv.addWidget(self.result)
        row = QHBoxLayout()
        self.run_buttons = []
        for text, fn, tip in (("Save", self._save, ""), ("Run on selected accounts", self._run, ""),
                              ("Run once (test)", self._run_once, "Runs the text as it is now, once, saved or not"),
                              ("Step by step", self._step, "Runs it one step at a time on the selected account: the "
                               "line it is on is highlighted, Next step (F10) does it. Waits are skipped."),
                              ("Stop on selected accounts", self._stop, "")):
            b = QPushButton(text)
            b.clicked.connect(fn)
            b.setToolTip(tip)
            row.addWidget(b)
            self.run_buttons.append(b)
        rv.addLayout(row)
        # step by step: what comes next, Next step / Stop (shown while stepping)
        self.step_bar = QWidget()
        sb = QHBoxLayout(self.step_bar)
        sb.setContentsMargins(0, 0, 0, 0)
        self.step_label = QLabel("")
        sb.addWidget(self.step_label, 1)
        self.b_next = btn("Next step  (F10)", self._next, primary=True)
        sb.addWidget(self.b_next)
        sb.addWidget(btn("Stop stepping", self._end_step))
        self.step_bar.setVisible(False)
        rv.addWidget(self.step_bar)
        self._stepping = None           # the Instance being stepped through
        self._step_n = 0
        self._step_poll = QTimer(self, interval=300, timeout=self._step_alive)
        QShortcut(QKeySequence("F10"), self, self._next)
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

    # ---- share
    def _export(self):
        m = self._current()
        if not m:
            return
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in m.name).strip() or "macro"
        fn, _ = QFileDialog.getSaveFileName(self, "Export macro", str(Path.home() / f"{safe}.txt"),
                                            "Cellar macro (*.txt)")
        if not fn:
            return
        try:
            Path(fn).write_text(f"# Cellar macro: {m.name}\n# loop: {'yes' if m.loop else 'no'}\n{m.text}",
                                encoding="utf-8")
            self.result.setText(f"Saved to {fn}.")
        except OSError as ex:
            self.result.setText(theme.span("bad", f"Could not save: {ex}"))

    def _import(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import macros", str(Path.home()),
                                                "Cellar macros (*.txt);;All files (*)")
        done, bad, last = 0, [], ""
        for fn in files:
            try:
                text = Path(fn).read_text(encoding="utf-8", errors="replace")
            except OSError as ex:
                bad.append(f"{Path(fn).name}: {ex}")
                continue
            name, loop, body = Path(fn).stem, True, []
            for line in text.splitlines():
                low = line.strip().lower()
                if low.startswith("# cellar macro:"):
                    name = line.split(":", 1)[1].strip() or name
                elif low.startswith("# loop:"):
                    loop = low.split(":", 1)[1].strip() in ("yes", "true", "1")
                else:
                    body.append(line)
            body_text = "\n".join(body).strip() + "\n"
            _, errors = macros.parse(body_text)
            if errors:
                bad.append(f"{Path(fn).name}: {errors[0]}")
                continue
            last = self._unique(name)
            store.settings.macros.append(Macro(name=last, text=body_text, loop=loop))
            done += 1
        if done:
            store.save_settings()
            self.load(last)
        msg = f"Imported {done} macro(s)." if done else ""
        if bad:
            msg += ("<br>" if msg else "") + theme.span("bad", "Skipped: " + "<br>".join(bad))
        if msg:
            self.result.setText(msg)

    # ---- edit
    def _check(self, live: bool = False) -> bool:
        """Runs while you type (live) and before saving / running: mistakes are underlined on their line."""
        text = self.text.toPlainText()
        steps, errors = macros.parse(text)
        bad = {int(m.group(1)) for e in errors if (m := re.match(r"line (\d+):", e))}
        if bad != self.hl.bad_lines:
            self.hl.bad_lines = bad
            self.hl.rehighlight()
        if errors:
            self.result.setText(theme.span("bad", "<br>".join(errors)))
            return False
        if not text.strip():
            self.result.setText("")
            return not live
        self.result.setText(theme.span("good", f"✓ OK - {_count(steps)} steps."))
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

    def _run_once(self):
        """Runs the text as it is in the editor once (saved or not) - to try a change before saving it."""
        if not self._check():
            return
        insts = self._targets()
        if not insts:
            self.mw.log("Select running background accounts first (Edit account > Run in the background, then launch).")
            return
        name = (self.name.text().strip() or "macro") + " (test)"
        for i in insts:
            self.mw.launcher.start_macro_text(i, name, self.text.toPlainText(), False, self.mw.log)

    # ---- step by step
    def _step(self):
        if self._stepping is not None or not self._check():
            return
        insts = self._targets()
        if not insts:
            self.mw.log("Select a running background account first (Edit account > Run in the background, then launch).")
            return
        inst = insts[0]
        name = (self.name.text().strip() or "macro") + " (step by step)"
        on_step = lambda line, what: ui(lambda: self._show_step(line, what))      # noqa: E731 - worker thread
        if not self.mw.launcher.start_macro_text(inst, name, self.text.toPlainText(), False, self.mw.log, on_step):
            return
        self._stepping, self._step_n = inst, 0
        self.text.setReadOnly(True)             # the highlighted line must stay the line that runs
        for b in self.run_buttons:
            b.setEnabled(False)
        self.step_bar.setVisible(True)
        self.step_label.setText(f"Stepping through on <b>{inst.account.name}</b>" + (
            f" (only this one of the {len(insts)} selected)" if len(insts) > 1 else "") + "...")
        self._step_poll.start()

    def _show_step(self, line: int, what: str):
        if self._stepping is None:
            return
        self._step_n += 1
        block = self.text.document().findBlockByNumber(max(0, line - 1))
        what = block.text().strip() or what            # the line as you wrote it ("tap e", not the key code)
        self.step_label.setText(f"<b>{self._stepping.account.name}</b> · step {self._step_n} · line {line}: "
                                f"<tt>{what.replace('&', '&amp;').replace('<', '&lt;')}</tt>  - press Next step to do it")
        sel = QTextEdit.ExtraSelection()
        bg_ = QColor(theme.c("accent"))
        bg_.setAlphaF(0.22)
        sel.format.setBackground(bg_)
        sel.format.setProperty(QTextFormat.FullWidthSelection, True)
        sel.cursor = QTextCursor(block)
        self.text.setExtraSelections([sel])
        self.text.setTextCursor(QTextCursor(block))
        self.text.ensureCursorVisible()

    def _next(self):
        r = self._stepping.macro if self._stepping is not None else None
        if r is not None:
            r.next_step()

    def _step_alive(self):
        r = self._stepping.macro if self._stepping is not None else None
        if r is None or not r.running:
            self._end_step(finished=True)

    def _end_step(self, finished: bool = False):
        inst, self._stepping = self._stepping, None
        self._step_poll.stop()
        if inst is not None and not finished:
            self.mw.launcher.stop_macro(inst)
        self.text.setExtraSelections([])
        self.text.setReadOnly(False)
        for b in self.run_buttons:
            b.setEnabled(True)
        self.step_bar.setVisible(False)
        if inst is not None:
            self.result.setText(theme.span("good" if finished else "muted",
                                           f"Step by step on {inst.account.name}: " +
                                           (f"finished after {self._step_n} steps." if finished else "stopped.")))

    def _stop(self):
        if self._stepping is not None:
            self._end_step()
        n = sum(1 for i in self._targets() if self.mw.launcher.stop_macro(i))
        self.mw.log(f"Stopped {n} macro(s)." if n else "No macros were running on the selected accounts.")


def _count(steps) -> int:
    n = 0
    for op, args in steps:
        n += 1 + (_count(args[-1]) if op in ("repeat", "random") else 0)
    return n
