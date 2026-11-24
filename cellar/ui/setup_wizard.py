"""First-run setup: pick a look, check the system (with copyable install commands), add accounts.

Shown once on a fresh install (no accounts yet); Settings > Run setup again opens it any time.
"""

import subprocess

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, requirements, sober, store, theme
from .common import Dialog, bg, btn, hint


def _title(text: str) -> QLabel:
    l = QLabel(text)
    f = l.font()
    f.setPointSizeF(f.pointSizeF() * 1.5)
    f.setBold(True)
    l.setFont(f)
    return l


class _CheckRow(QFrame):
    def __init__(self, c: requirements.Check):
        super().__init__()
        g = QGridLayout(self)
        g.setContentsMargins(0, 6, 0, 6)
        g.setHorizontalSpacing(10)
        mark = QLabel(theme.span("good", "✓") if c.ok else theme.span("bad" if c.required else "warn", "✗"))
        mark.setTextFormat(Qt.RichText)
        mark.setFixedWidth(16)
        g.addWidget(mark, 0, 0, Qt.AlignTop)
        what = "needed" if c.required else "optional"
        name = QLabel(f"<b>{c.name}</b> &nbsp;<span style='color: {theme.c('muted')}'>{what} - for {c.needed_for}"
                      "</span>")
        name.setWordWrap(True)
        g.addWidget(name, 0, 1)
        r = 1
        if not c.ok and c.note:
            g.addWidget(hint(c.note), r, 1)
            r += 1
        if not c.ok and c.fix:
            cmd = QLineEdit(c.fix)
            cmd.setReadOnly(True)
            cmd.setFont(theme.mono_font())
            cmd.setCursorPosition(0)
            cp = QPushButton("Copy")
            cp.clicked.connect(lambda: (QGuiApplication.clipboard().setText(c.fix), cp.setText("Copied")))
            h = QHBoxLayout()
            h.addWidget(cmd, 1)
            h.addWidget(cp)
            g.addLayout(h, r, 1)
        g.setColumnStretch(1, 1)


class SetupWizard(Dialog):
    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self.setWindowTitle(f"Set up {APP_NAME}")
        self.resize(820, 600)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        self.steps = QLabel()
        self.steps.setObjectName("eyebrow")
        self.steps.setFont(theme.mono_font(7.5, 1.4))
        v.addWidget(self.steps)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        self.names = ["Look", "System", "Accounts", "Done"]
        for page in (self._look(), self._system(), self._accounts(), self._done()):
            self.stack.addWidget(page)

        h = QHBoxLayout()
        self.skip = btn("Skip setup", self.finish)
        self.back = btn("Back", lambda: self.go(-1))
        self.next = btn("Next", lambda: self.go(1), primary=True)
        h.addWidget(self.skip)
        h.addStretch(1)
        h.addWidget(self.back)
        h.addWidget(self.next)
        v.addLayout(h)
        self.go(0)

    # ------------------------------------------------------------ pages
    def _page(self, title: str, text: str):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 6)
        v.setSpacing(10)
        v.addWidget(_title(title))
        if text:
            v.addWidget(hint(text))
        return w, v

    def _look(self):
        from .settings_pages import ThemePicker
        w, v = self._page(f"Welcome to {APP_NAME}",
                          "Run many Roblox accounts at once through Sober - each in its own isolated copy, on your "
                          "desktop or on invisible screens in the background. This takes a minute: pick a look, "
                          "check that your system has what it needs, and add your accounts.")
        self.picker = ThemePicker(store.settings.theme, self._pick_theme)
        v.addWidget(self.picker)
        v.addWidget(hint("You can change this any time in Settings."))
        v.addStretch(1)
        return w

    def _pick_theme(self, key: str):
        self.mw.apply_theme(key)
        self.picker.refresh()
        self._fill_checks()         # the check marks use theme colours

    def _system(self):
        w, v = self._page("Check your system", "")
        self.sys_summary = hint("")
        v.addWidget(self.sys_summary)
        self.checks_box = QVBoxLayout()
        self.checks_box.setSpacing(0)
        v.addLayout(self.checks_box)
        v.addStretch(1)
        h = QHBoxLayout()
        self.open_sober = btn("Open Sober", self._open_sober, tip="Starts your normal Sober so it can finish setting "
                                                                  "itself up")
        h.addWidget(btn("Check again", self.recheck))
        h.addWidget(self.open_sober)
        h.addStretch(1)
        v.addLayout(h)
        self.checks = []
        return w

    def recheck(self):
        sober._cache.pop("sober_checked", None)
        kw = self.mw.kwin is not None and self.mw.kwin.available()
        bg(requirements.run, kw, done=self._got_checks)

    def _got_checks(self, checks):
        self.checks = checks
        self._fill_checks()

    def _fill_checks(self):
        while self.checks_box.count():
            it = self.checks_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for c in self.checks:
            self.checks_box.addWidget(_CheckRow(c))
        bad = [c for c in self.checks if not c.ok and c.required]
        opt = [c for c in self.checks if not c.ok and not c.required]
        if not self.checks:
            text = "Checking..."
        elif bad:
            n = "1 thing is" if len(bad) == 1 else f"{len(bad)} things are"
            text = theme.span("bad", f"<b>{n} needed</b> before accounts can launch.") + \
                " Copy the command, run it in a terminal, then press Check again."
        elif opt:
            text = theme.span("good", "<b>Ready to launch.</b>") + \
                " The optional parts below unlock more features - add them now or later."
        else:
            text = theme.span("good", "<b>Everything is ready.</b>")
        self.sys_summary.setText(text)
        self.open_sober.setVisible(any(c.key == "profile" and not c.ok for c in self.checks)
                                   and any(c.key == "sober" and c.ok for c in self.checks))

    def _open_sober(self):
        fp = sober.which("flatpak")
        if fp:
            subprocess.Popen([fp, "run", sober.SOBER_ID], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)

    def _accounts(self):
        w, v = self._page("Add your accounts",
                          "Pick how you want to add them. You can add more any time with <b>Add account</b>. "
                          "Accounts are stored encrypted on this computer only.")
        mw = self.mw
        grid = QGridLayout()
        grid.setSpacing(10)
        opts = [("Log in with browser", "A private login window - captcha, 2-step and passkeys work.", mw.add_browser),
                ("Import my Sober account", "The account your normal Sober is logged in with.", mw.add_from_sober),
                ("Paste cookies", ".ROBLOSECURITY cookies, many at once.", mw.add_paste),
                ("Import accounts file", "A Cellar export from another PC, or Roblox MultiHub's accounts.dat.",
                 mw.add_windows_file)]
        for i, (t, d, fn) in enumerate(opts):
            b = btn(t, fn, primary=(i == 0))
            b.setMinimumHeight(34)
            grid.addWidget(b, i, 0)
            grid.addWidget(hint(d), i, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        self.acc_count = QLabel()
        v.addWidget(self.acc_count)
        # accounts are added on worker threads after their dialogs close: keep the count current
        self._acc_timer = QTimer(self, interval=1000, timeout=self.refresh_accounts)
        self._acc_timer.start()
        v.addStretch(1)
        return w

    def _done(self):
        w, v = self._page("You're set", "")
        tips = [
            ("Play", "On <b>Accounts</b>, select accounts (Ctrl / Shift for several), pick a game (Your games or "
                     "Search game...) and press <b>Launch selected</b>. Or press Play on roblox.com - turn that on "
                     "in Settings > Launching."),
            ("Background", "Right-click an account > Edit > <b>Run in the background</b> to run it on an invisible "
                           "screen - nothing appears on your desktop. Right-click > View screen to watch it."),
            ("Presets", "Save a whole setup (accounts, games, window places) as a preset and start it in one click "
                        "(Automation)."),
            ("Stay safe", "Give every account a verified email and 2-step verification. Running several clients "
                          "and macros is against Roblox's rules - use your own accounts at your own risk."),
            ("Help", "Help (the ? at the top right) explains everything; Settings > System check shows what your computer has."),
        ]
        for t, d in tips:
            v.addWidget(hint(f"<b style='color: {theme.c('text')}'>{t}</b> &nbsp;{d}"))
        v.addSpacing(8)
        upd = QCheckBox("Tell me when a new version of Cellar is out (asks GitHub once a day)")
        upd.setChecked(store.settings.check_updates)
        upd.toggled.connect(lambda on: setattr(store.settings, "check_updates", on))
        v.addWidget(upd)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------ flow
    def go(self, step: int):
        i = max(0, min(self.stack.count() - 1, self.stack.currentIndex() + step))
        self.stack.setCurrentIndex(i)
        self.steps.setText("   ·   ".join(n.upper() if k == i else n for k, n in enumerate(self.names)))
        self.back.setEnabled(i > 0)
        last = i == self.stack.count() - 1
        self.next.setText("Start using Cellar" if last else "Next")
        self.next.clicked.disconnect()
        self.next.clicked.connect(self.finish if last else (lambda: self.go(1)))
        self.skip.setVisible(not last)
        if i == 1 and not self.checks:
            self.recheck()
        if i == 2:
            self.refresh_accounts()

    def refresh_accounts(self):
        n = len(store.accounts)
        self.acc_count.setText(theme.span("good", f"✓ {n} account{'s' if n != 1 else ''} added.") if n else
                               theme.span("muted", "No accounts yet."))

    def finish(self):
        store.settings.first_run_done = True
        store.save_settings()
        self.accept()


class SystemCheckDialog(Dialog):
    """Settings > System check: what is missing (with the command to fix it) + a full report to copy."""

    def __init__(self, parent, mw, details: str):
        super().__init__(parent)
        self.setWindowTitle("System check")
        self.resize(760, 640)
        self.details = details
        v = QVBoxLayout(self)
        v.addWidget(_title("System check"))
        rows = QVBoxLayout()
        rows.setSpacing(0)
        v.addLayout(rows)
        kw = mw.kwin is not None and mw.kwin.available()
        bg(requirements.run, kw, done=lambda checks: [rows.addWidget(_CheckRow(c)) for c in checks])
        self.text = QPlainTextEdit(details)
        self.text.setReadOnly(True)
        self.text.setFont(theme.mono_font())
        v.addWidget(self.text, 1)
        h = QHBoxLayout()
        h.addWidget(hint("<b>Copy report</b> adds the recent log (cookies removed) - paste it into a bug report."), 1)
        h.addWidget(btn("Copy report", self.copy_report, primary=True))
        h.addWidget(btn("Close", self.reject))
        v.addLayout(h)

    def copy_report(self):
        from .. import crash, paths
        parts = [self.details]
        try:
            lines = paths.LOG_FILE.read_text(errors="replace").splitlines()[-150:]
            parts += ["", "--- recent log ---", *lines]
        except OSError:
            pass
        try:
            if crash.LAST_CRASH_FILE.exists():
                parts += ["", "--- last crash ---", crash.LAST_CRASH_FILE.read_text(errors="replace")[-6000:]]
        except OSError:
            pass
        QGuiApplication.clipboard().setText(crash.scrub("\n".join(parts)))
        self.sender().setText("Copied")
