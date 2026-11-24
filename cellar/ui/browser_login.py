"""In-app browser login (replaces the Windows app's Edge/Chrome debugging-port trick).

Opens roblox.com/login in a private, throw-away Qt WebEngine profile. You log in normally
(captcha, 2-step and passkeys all work); as soon as Roblox sets a valid .ROBLOSECURITY cookie
the window closes by itself and the session is discarded.
"""

import json
import re
from typing import Callable, Optional

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from .common import bg

# Imported on first use (see app.py): just check that it is there.
import importlib.util

HAVE_WEBENGINE = importlib.util.find_spec("PySide6.QtWebEngineWidgets") is not None

_profile = None


def _shared_profile():
    """One off-the-record profile for the whole app (wiped before and after every login), so a
    page is never left without its profile when a dialog goes away."""
    global _profile
    if _profile is None:
        from PySide6.QtWebEngineCore import QWebEngineProfile
        from PySide6.QtWidgets import QApplication
        _profile = QWebEngineProfile(QApplication.instance())     # no storage name = off the record
        _profile.setHttpUserAgent(re.sub(r"\s*QtWebEngine/\S+", "", _profile.httpUserAgent()))
    return _profile


_FILL_JS = """(function(){var u=document.querySelector('#login-username,input[name="username"]');
var p=document.querySelector('#login-password,input[type="password"]');
if(!u||!p)return 'wait';
var S=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
function f(e,v){S.call(e,v);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}
f(u,%s);f(p,%s);return 'done';})()"""


SIGNUP_URL = "https://www.roblox.com/CreateAccount"


class BrowserLogin(QDialog):
    """signup=True opens Roblox's own sign-up page instead: you fill it in and pass Roblox's checks
    yourself, exactly like on the website; the hub only picks up the login once the account exists."""

    def __init__(self, parent, validate: Callable[[str], bool], user: str = "", password: str = "",
                 signup: bool = False):
        super().__init__(parent)
        self.cookie: Optional[str] = None
        self._validate = validate
        self._checking = set()
        self._user, self._pass = user, password
        self._fill_tries = 0
        self.setWindowTitle("Create a Roblox account" if signup else "Log in to Roblox" + (f" - {user}" if user else ""))
        self.resize(560, 760)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        if signup:
            text = ("Fill in Roblox's sign-up form and finish its checks. As soon as the new account is logged in, "
                    "this window closes and the account is added. Then give it an email and 2-step verification "
                    "(roblox.com, Settings): new accounts without them are the easiest for Roblox to lock. ")
        elif user:
            text = "Username and password are filled in - press <b>Log In</b> (solve any captcha). "
        else:
            text = "Log in to the account you want to add. "
        self.info = QLabel(text + "This window closes by itself once you are logged in. Nothing is kept from this browser.")
        self.info.setWordWrap(True)
        self.info.setContentsMargins(10, 8, 10, 8)
        v.addWidget(self.info)

        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWebEngineWidgets import QWebEngineView
        self.profile = _shared_profile()
        self.profile.cookieStore().deleteAllCookies()
        self.page = QWebEnginePage(self.profile, self.view_parent())
        self.view = QWebEngineView(self)
        self.page.setParent(self.view)
        self.view.setPage(self.page)
        v.addWidget(self.view, 1)
        self.profile.cookieStore().cookieAdded.connect(self._on_cookie)
        if user:
            self.page.loadFinished.connect(lambda ok: QTimer.singleShot(600, self._fill))
        self.view.load(QUrl(SIGNUP_URL if signup else "https://www.roblox.com/login"))

    def view_parent(self):
        return self

    def _fill(self):
        if not self._user or self._fill_tries > 20:
            return
        self._fill_tries += 1

        def after(res):
            if res != "done":
                QTimer.singleShot(700, self._fill)
            else:
                self._user = ""        # filled once; you take over
        self.page.runJavaScript(_FILL_JS % (json.dumps(self._user), json.dumps(self._pass)), 0, after)

    def _on_cookie(self, c):
        try:
            name = bytes(c.name()).decode(errors="replace")
            if name != ".ROBLOSECURITY" or "roblox.com" not in c.domain():
                return
            val = bytes(c.value()).decode(errors="replace")
        except Exception:
            return
        if len(val) < 40 or val in self._checking or self.cookie:
            return
        self._checking.add(val)
        self.info.setText("Logged in - checking the account...")

        def done(ok):
            if ok and not self.cookie:
                self.cookie = val
                self.accept()
            elif not ok:
                self.info.setText("That login did not work yet - keep going.")
        bg(self._validate, val, done=done)

    def done(self, r):
        try:
            self.profile.cookieStore().cookieAdded.disconnect(self._on_cookie)
        except Exception:
            pass
        self.view.stop()
        self.profile.cookieStore().deleteAllCookies()
        super().done(r)
