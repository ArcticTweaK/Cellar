"""An account's profile page: big avatar, name and status, Robux / Premium / friends / followers / groups, its recent
games (Cellar's own join history) and its newest badges. Opened from an account (View profile) or the top-right
account chip.
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,
                               QWidget)

from .. import games, paths, profiles, store, theme, util
from ..models import Account, LaunchSpec
from .common import bg, btn, hint
from .widgets import eyebrow


def _card() -> QFrame:
    f = QFrame()
    f.setObjectName("pcard")
    f.setAttribute(Qt.WA_StyledBackground, True)
    return f


def _big(text: str = "-") -> QLabel:
    l = QLabel(text)
    l.setObjectName("stat_value")
    return l


class ProfilePage(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.a: Optional[Account] = None
        self.p: Optional[profiles.Profile] = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(QLabel("Profile of"))
        self.pick = QComboBox()
        self.pick.currentIndexChanged.connect(self._picked)
        top.addWidget(self.pick)
        outer.addLayout(top)

        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 8, 0)
        v.setSpacing(14)

        # ---- header
        head = _card()
        hh = QHBoxLayout(head)
        hh.setContentsMargins(20, 20, 20, 20)
        hh.setSpacing(22)
        self.avatar = QLabel()
        self.avatar.setFixedSize(200, 200)
        self.avatar.setObjectName("bigavatar")
        self.avatar.setAlignment(Qt.AlignCenter)
        hh.addWidget(self.avatar, 0, Qt.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(4)
        self.name = QLabel()
        self.name.setObjectName("page_title")
        self.handle = QLabel()
        self.handle.setObjectName("page_sub")
        self.status = QLabel()
        self.status.setTextFormat(Qt.RichText)
        self.age = QLabel()
        self.age.setObjectName("page_sub")
        self.about = QLabel()
        self.about.setWordWrap(True)
        self.about.setObjectName("page_sub")
        self.about.setMaximumHeight(90)
        for w in (self.name, self.handle, self.status, self.age, self.about):
            info.addWidget(w)
        info.addStretch(1)
        acts = QHBoxLayout()
        self.launch_btn = btn("Launch", self._launch, icon="play", primary=True)
        self.launch_btn.setMinimumHeight(38)
        acts.addWidget(self.launch_btn)
        acts.addWidget(btn("Edit", lambda: self.a and self._with_selected(self.mw.edit_selected)))
        acts.addWidget(btn("Use in my normal Sober", lambda: self.a and self.mw.use_in_main_sober(self.a)))
        acts.addWidget(btn("Open on roblox.com", lambda: self.a and _open(
            f"https://www.roblox.com/users/{self.a.user_id}/profile")))
        acts.addStretch(1)
        info.addLayout(acts)
        hh.addLayout(info, 1)
        # numbers
        nums = QGridLayout()
        nums.setHorizontalSpacing(26)
        nums.setVerticalSpacing(4)
        self.nums = {}
        for i, key in enumerate(("Robux", "Premium", "Friends", "Followers", "Following", "Groups")):
            box = QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(eyebrow(key))
            self.nums[key] = _big()
            box.addWidget(self.nums[key])
            nums.addLayout(box, i // 2, i % 2)
        hh.addLayout(nums)
        v.addWidget(head)

        # ---- activity | badges + groups
        cols = QHBoxLayout()
        cols.setSpacing(14)
        act = _card()
        self.act_l = QVBoxLayout(act)
        self.act_l.setContentsMargins(18, 14, 18, 14)
        cols.addWidget(act, 2)
        side = QVBoxLayout()
        side.setSpacing(14)
        badges = _card()
        self.badge_l = QVBoxLayout(badges)
        self.badge_l.setContentsMargins(18, 14, 18, 14)
        side.addWidget(badges)
        groups = _card()
        self.group_l = QVBoxLayout(groups)
        self.group_l.setContentsMargins(18, 14, 18, 14)
        side.addWidget(groups)
        side.addStretch(1)
        cols.addLayout(side, 1)
        v.addLayout(cols)
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

    # ------------------------------------------------------------ showing an account
    def fill_accounts(self):
        cur = self.a.id if self.a else None
        self.pick.blockSignals(True)
        self.pick.clear()
        for a in store.accounts:
            self.pick.addItem(a.name, a.id)
        i = self.pick.findData(cur)
        if i >= 0:
            self.pick.setCurrentIndex(i)
        self.pick.blockSignals(False)

    def _picked(self, _):
        a = store.find_by_id(self.pick.currentData() or "")
        if a and a is not self.a:
            self.set_account(a)

    def set_account(self, a: Account):
        self.a, self.p = a, None
        self.fill_accounts()
        self._render()
        uid = a.user_id

        def work():
            p = profiles.load(a)
            profiles.fetch_pictures(uid, [b for b, _ in p.badges])
            return p

        def done(p):
            if self.a is a:
                self.p = p
                self._render()
        bg(work, done=done)

    def _render(self):
        a, p = self.a, self.p
        if a is None:
            return
        pm = QPixmap(str(profiles.body_path(a.user_id))) if profiles.body_path(a.user_id).exists() else \
            QPixmap(str(paths.AVATAR_DIR / f"{a.user_id}.png"))
        self.avatar.setPixmap(pm.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation) if not pm.isNull()
                              else QPixmap())
        self.name.setText((p.display if p and p.display else a.display_name) or a.name)
        self.handle.setText(f"@{a.username}" + (f"  ·  ID {a.user_id}" if a.user_id else "")
                            + (f"  ·  alias “{a.alias}”" if a.alias else ""))
        text, token = self.mw.model.status(a)
        self.status.setText(theme.span(token, "● " + (text.replace("▶ ", "") or "Status unknown")))
        if p and p.age_days is not None:
            y, d = divmod(p.age_days, 365)
            years = (f"{y} year" + ("s" if y != 1 else "") + ", ") if y else ""
            self.age.setText(f"Account age: {years}{d} days (since {p.created:%d %b %Y})"
                             + ("  ·  BANNED" if p.banned else ""))
        else:
            self.age.setText("Loading..." if p is None else "")
        self.about.setText(p.about if p else "")
        self.about.setVisible(bool(p and p.about))
        n = self.nums
        n["Robux"].setText("-" if not p or p.robux is None else f"{p.robux:,}")
        n["Premium"].setText("-" if not p or p.premium is None else ("Yes" if p.premium else "No"))
        for key, val in (("Friends", p.friends if p else -1), ("Followers", p.followers if p else -1),
                         ("Following", p.following if p else -1)):
            n[key].setText(games.short(val) if val >= 0 else "-")
        n["Groups"].setText(str(len(p.groups)) if p else "-")
        self._activity()
        self._badges()
        self._groups()

    def _clear(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                self._clear(it.layout())

    def _activity(self):
        lay = self.act_l
        self._clear(lay)
        lay.addWidget(eyebrow("Recent activity"))
        names = {e.place_id: e.name for e in store.settings.recent if e.name}
        recs = [h for h in store.settings.history if h.account_id == self.a.id][:12]
        if not recs:
            lay.addWidget(hint("No games yet - every server this account joins while Cellar runs shows up here."))
        for h in recs:
            row = QHBoxLayout()
            ic = QLabel()
            ic.setFixedSize(40, 40)
            uni = games.cached_universe(h.place_id)
            path = games.icon_path(uni) if uni else None
            if path and path.exists():
                ic.setPixmap(QPixmap(str(path)).scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            row.addWidget(ic)
            t = QLabel(f"<b>{names.get(h.place_id) or h.place_id}</b><br>"
                       f"<span style='color:{theme.c('muted')}'>{util.ago(h.ts)}</span>")
            row.addWidget(t, 1)
            rej = btn("Rejoin", None)
            rej.clicked.connect(lambda _=False, h=h: self.mw.start_launch(
                [self.a], fixed=LaunchSpec(kind="Job", place_id=h.place_id, job_id=h.job_id), allow_saved=False))
            row.addWidget(rej)
            lay.addLayout(row)
        lay.addStretch(1)

    def _badges(self):
        lay = self.badge_l
        self._clear(lay)
        lay.addWidget(eyebrow("Newest badges"))
        if not self.p or not self.p.badges:
            lay.addWidget(hint("Loading..." if self.p is None else "No badges (or Roblox did not share them)."))
            return
        grid = QGridLayout()
        for i, (bid, name) in enumerate(self.p.badges[:9]):
            cell = QVBoxLayout()
            ic = QLabel()
            ic.setFixedSize(56, 56)
            if profiles.badge_path(bid).exists():
                ic.setPixmap(QPixmap(str(profiles.badge_path(bid))).scaled(56, 56, Qt.KeepAspectRatio,
                                                                            Qt.SmoothTransformation))
            ic.setToolTip(name)
            cell.addWidget(ic, 0, Qt.AlignHCenter)
            lab = QLabel(name)
            lab.setObjectName("page_sub")
            lab.setWordWrap(True)
            lab.setAlignment(Qt.AlignHCenter)
            lab.setMaximumWidth(96)
            cell.addWidget(lab)
            grid.addLayout(cell, i // 3, i % 3)
        lay.addLayout(grid)

    def _groups(self):
        lay = self.group_l
        self._clear(lay)
        lay.addWidget(eyebrow("Groups"))
        if not self.p or not self.p.groups:
            lay.addWidget(hint("Loading..." if self.p is None else "Not in any group."))
            return
        for g, role in self.p.groups[:8]:
            lay.addWidget(QLabel(f"<b>{g}</b> <span style='color:{theme.c('muted')}'>· {role}</span>"))
        if len(self.p.groups) > 8:
            lay.addWidget(hint(f"and {len(self.p.groups) - 8} more"))

    # ------------------------------------------------------------ actions
    def _with_selected(self, fn):
        self.mw.select_accounts([self.a])
        fn()

    def _launch(self):
        if self.a:
            self.mw.start_launch([self.a])

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.a is None and store.accounts:
            self.set_account(self.mw.home_page.home_account() or store.accounts[0])
        elif self.a is not None:
            self._render()                      # status / activity may have changed meanwhile


def _open(url: str):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl(url))
