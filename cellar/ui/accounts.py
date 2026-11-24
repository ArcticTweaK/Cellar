"""MainWindow part: The account list: filtering, selection, right-click menu, adding / editing / removing accounts.

A mixin of ui.main_window.MainWindow - `self` is the main window."""

import subprocess
import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog, QMenu

from .. import api, paths, sober, store, theme, util
from ..models import Account
from .accounts_model import ACCOUNT_ROLE, TAG_FILTER
from .browser_login import HAVE_WEBENGINE, BrowserLogin
from .common import ask, bg, popup, warn
from .dialogs import BulkEditDialog, EditAccountDialog, PasswordDialog, PasteDialog, TextDialog


class AccountsMixin:
    def refresh_accounts(self, select: Optional[set] = None):
        """select: account ids to select afterwards. Pass it when store.accounts was reordered: the current
        selection is read by row, and those rows now hold other accounts."""
        sel = select if select is not None else {a.id for a in self.selected_accounts()}
        self.model.reload()
        self.apply_sort()
        sm = self.table.selectionModel()
        for r in range(self.proxy.rowCount()):
            a = self.proxy.index(r, 0).data(ACCOUNT_ROLE)
            if a and a.id in sel:
                sm.select(self.proxy.index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.refresh_groups()
        self.on_selection()
        self.autohide_columns()

    def refresh_groups(self):
        keep = self.group_filter.currentData()
        self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem("All groups", None)
        for g in store.all_groups():
            self.group_filter.addItem(g, g)
        if any(not a.group for a in store.accounts) and store.all_groups():
            self.group_filter.addItem("(no group)", "")
        used = {a.color for a in store.accounts}
        for key, (label, *_) in theme.TAGS.items():
            if key in used:
                self.group_filter.addItem(theme.tag_icon(key), f"{label} tag", TAG_FILTER + key)
        i = self.group_filter.findData(keep)
        self.group_filter.setCurrentIndex(i if i >= 0 else 0)
        self.group_filter.blockSignals(False)

    def apply_sort(self):
        k = self.sort.currentData()
        self.proxy.manual = k == "Manual"
        col = {"Name": 0, "Group": 1, "Status": 2, "Usage": 3, "Last": 5}.get(k, 0)
        self.proxy.sort(col, Qt.AscendingOrder)
        self.proxy.invalidate()

    def selected_accounts(self) -> List[Account]:
        # any selected cell counts: the card view selects only column 0, the table whole rows
        rows = sorted({i.row() for i in self.table.selectionModel().selectedIndexes()})
        return [a for a in (self.proxy.index(r, 0).data(ACCOUNT_ROLE) for r in rows) if a]

    def filtered_accounts(self) -> List[Account]:
        return [a for a in (self.proxy.index(r, 0).data(ACCOUNT_ROLE) for r in range(self.proxy.rowCount())) if a]

    def any_cookie(self) -> Optional[str]:
        sel = self.selected_accounts()
        a = sel[0] if sel else next((x for x in store.accounts if x.cookie and not store.live(x).cookie_bad), None)
        return a.cookie if a else None

    def on_selection(self):
        self.launch_page.update_selection(self.selected_accounts())

    @staticmethod
    def _volume_of(a: Account) -> int:
        s = store.settings
        return a.volume if a.volume >= 0 else (0 if s.mute_alts and not a.full_quality else 100)

    def select_accounts(self, accs: List[Account]):
        """Makes exactly these accounts the selection (both views share it)."""
        sm = self.table.selectionModel()
        sm.clearSelection()
        ids = {a.id for a in accs}
        for r in range(self.proxy.rowCount()):
            a = self.proxy.index(r, 0).data(ACCOUNT_ROLE)
            if a and a.id in ids:
                sm.select(self.proxy.index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)

    def main_account(self) -> Optional[Account]:
        """Whose friends fill 'Follow a friend', whose favourites fill 'Your games' and whose friends the friend
        notifications are about: Settings > Main account, else the one marked Full quality, else the first."""
        a = store.find_by_id(store.settings.home_account)
        if a and a.cookie and a.user_id:
            return a
        cands = sorted((x for x in store.accounts if x.cookie and x.user_id), key=lambda x: (not x.full_quality, x.order))
        return cands[0] if cands else None

    def context_menu(self, pos, view=None):
        view = view or self.table
        sel = self.selected_accounts()
        if not sel:
            return
        leader = view.indexAt(pos).data(ACCOUNT_ROLE) or sel[0]
        m = QMenu(self)
        m.addAction("Launch", self.launch_selected)
        m.addAction("Stop", self.stop_selected)
        bm = m.addMenu(f"Bring accounts to {leader.name}'s server")
        others = [a for a in sel if a is not leader]
        if others:
            bm.addAction(f"The {len(others)} other selected account(s)", lambda: self.bring_here(leader, others))
        for g in sorted({a.group for a in store.accounts if a.group and a is not leader}):
            accs = [a for a in store.accounts if a.group == g and a is not leader]
            bm.addAction(f"Group '{g}' ({len(accs)})", lambda accs=accs: self.bring_here(leader, accs))
        rest = [a for a in store.accounts if a is not leader]
        if rest:
            bm.addAction(f"All other accounts ({len(rest)})", lambda: self.bring_here(leader, rest))
        bg_insts = [i for a in sel for i in self.launcher.instances_of(a) if i.screen]
        if len(sel) == 1 and not bg_insts:
            m.addAction("Focus its window", lambda: self.focus_account(sel[0]))
        if bg_insts:
            m.addSeparator()
            if len(bg_insts) == 1:
                m.addAction("View screen", lambda: self.view_screen(bg_insts[0]))
            m.addAction("Screen wall (all background accounts)", self.open_screen_wall)
            mm = m.addMenu("Run macro")
            for mac in store.settings.macros:
                mm.addAction(mac.name, lambda n=mac.name: [self.launcher.start_macro(i, n, self.log) for i in bg_insts])
            if not store.settings.macros:
                mm.addAction("(none yet - see the Macros tab)").setEnabled(False)
            if any(i.macro for i in bg_insts):
                m.addAction("Stop macro", lambda: [self.launcher.stop_macro(i) for i in bg_insts])
        insts = [i for a in sel for i in self.launcher.instances_of(a) if self.launcher.is_alive(i)]
        if insts:
            if any(not i.frozen for i in insts):
                m.addAction("Freeze (0% CPU, keeps it open)",
                            lambda: bg(lambda: [self.launcher.freeze(i, True, self.log) for i in insts if not i.frozen]))
            if any(i.frozen for i in insts):
                m.addAction("Resume", lambda: bg(lambda: [self.launcher.freeze(i, False, self.log)
                                                          for i in insts if i.frozen]))
        if len(sel) == 1:
            m.addAction("Use in my normal Sober", lambda: self.use_in_main_sober(sel[0]))
        if any(store.live(a).cookie_bad for a in sel) and len(sel) == 1:
            m.addAction("Log in again...", lambda: self.add_browser(sel[0].username))
        m.addAction("Add to app menu (launch shortcut)", lambda: self.add_shortcuts(sel))
        muted = all(self._volume_of(a) == 0 for a in sel)
        m.addAction("Unmute" if muted else "Mute", lambda: self.set_volume(sel, 100 if muted else 0))
        pin = not all(a.pinned for a in sel)
        m.addAction("Pin to top" if pin else "Unpin", lambda: self.set_pinned(sel, pin))
        cm = m.addMenu(theme.tag_icon(sel[0].color if len({a.color for a in sel}) == 1 else ""), "Colour tag")
        now = {a.color for a in sel}
        for key, label in [("", "None")] + [(k, t[0]) for k, t in theme.TAGS.items()]:
            # a check mark: with the swatch icon the style draws no check box for checkable actions
            cm.addAction(theme.tag_icon(key), label + ("  ✓" if now == {key} else ""),
                         lambda key=key: self.set_color(sel, key))
        m.addSeparator()
        m.addAction("Edit...", self.edit_selected)
        m.addAction("Details", self.details_selected)
        if len(sel) == 1 and sel[0].user_id:
            from .launch_pages import open_url
            m.addAction("Open profile on roblox.com",
                        lambda: open_url(f"https://www.roblox.com/users/{sel[0].user_id}/profile"))
        m.addAction("Copy cookie", lambda: self.copy([a.cookie for a in sel]))
        m.addAction("Copy username", lambda: self.copy([a.username for a in sel]))
        m.addAction("Export to a file...", lambda: self.export_accounts(sel))
        m.addSeparator()
        if self.sort.currentData() == "Manual":
            m.addAction("Move up", lambda: self.move_selected(-1))
            m.addAction("Move down", lambda: self.move_selected(1))
            m.addSeparator()
        if len(sel) == 1:
            m.addAction("Open its Sober profile folder", lambda: sober.open_folder(sober.profile_app(sel[0])
                                                                                 if sober.profile_app(sel[0]).exists() else paths.PROFILES_DIR))
        m.addAction("Reset Sober profile", self.reset_selected_profiles)
        m.addSeparator()
        m.addAction("Remove", self.remove_selected)
        popup(m, view.viewport().mapToGlobal(pos))

    def copy(self, items: List[str]):
        QGuiApplication.clipboard().setText("\n".join(items))
        self.log(f"Copied {len(items)} item(s) to the clipboard.")

    def add_shortcuts(self, accs: List[Account]):
        from .. import cli
        for a in accs:
            avatar = paths.AVATAR_DIR / f"{a.user_id}.png"
            cli.add_shortcut(f"Launch {a.name}", ["launch", a.username or a.alias],
                             str(avatar) if avatar.exists() else "")
        self.log(f"Added {len(accs)} shortcut(s) to your app menu (search 'Launch {accs[0].name}'). They start the "
                 "account in its own game, or the game on the Launch page.")

    def set_pinned(self, accs: List[Account], on: bool):
        for a in accs:
            a.pinned = on
        store.save_accounts()
        self.refresh_accounts()

    def set_color(self, accs: List[Account], key: str):
        for a in accs:
            a.color = key
        store.save_accounts()
        self.refresh_accounts()

    def restore_backup(self):
        from .dialogs import RestoreBackupDialog
        d = RestoreBackupDialog(self)
        if d.exec() and d.chosen is not None:
            n_before = len(store.accounts)
            store.restore(d.chosen)
            self.refresh_accounts()
            self.fetch_avatars()
            self.log(f"Restored {len(store.accounts)} account(s) from a backup (you had {n_before}; that list is "
                     "kept as a backup too).")

    def drop_reorder(self, target: Account, after: bool):
        """Drag and drop in the account list: the selected accounts go right before / after `target`."""
        if self.sort.currentData() != "Manual":
            self.toast("To rearrange accounts by dragging, set the list to 'Your order' (next to the group list).")
            return
        sel = {a.id for a in self.selected_accounts()}
        ids = sel - {target.id}
        moved = [a for a in store.accounts if a.id in ids]
        if not moved:
            return
        rest = [a for a in store.accounts if a.id not in ids]
        i = next(n for n, a in enumerate(rest) if a.id == target.id) + (1 if after else 0)
        store.accounts[:] = rest[:i] + moved + rest[i:]
        store.renumber()                        # "Your order" sorts by .order
        store.save_accounts()
        self.refresh_accounts(select=sel)

    def move_selected(self, d: int):
        sel = self.selected_accounts()
        if not sel:
            return
        accs = store.accounts
        idx = sorted(accs.index(a) for a in sel)
        if d < 0 and idx[0] == 0 or d > 0 and idx[-1] == len(accs) - 1:
            return
        for i in (idx if d < 0 else reversed(idx)):
            accs[i], accs[i + d] = accs[i + d], accs[i]
        store.renumber()
        store.save_accounts()
        self.refresh_accounts(select={a.id for a in sel})

    def _validate(self, cookie: str) -> bool:
        return api.authenticated(cookie).valid

    def add_cookies(self, cookies: List[str], password_for: dict = None):
        """Validates cookies on a worker thread and adds / updates the accounts."""
        if not cookies:
            self.log("No .ROBLOSECURITY cookies found in that text.")
            return
        self.log(f"Checking {len(cookies)} cookie(s)...")

        def work():
            out = []
            for c in cookies:
                u = api.authenticated(c)
                out.append((c, u))
                time.sleep(0.25)
            return out

        def done(results):
            added = updated = bad = 0
            for c, u in results:
                if not u.valid:
                    bad += 1
                    self.log(f"Cookie rejected: {u.error}")
                    continue
                a = store.find_by_user_id(u.id)
                if a:
                    a.cookie = c
                    updated += 1
                else:
                    a = Account(username=u.name, user_id=u.id, display_name=u.display, cookie=c, order=len(store.accounts))
                    store.accounts.append(a)
                    added += 1
                a.username, a.display_name, a.login_lost = u.name, u.display, False
                if password_for and u.name.lower() in password_for:
                    a.password = password_for[u.name.lower()]
                li = store.live(a)
                li.cookie_bad = li.locked = False
            store.save_accounts()
            self.refresh_accounts()
            self.log(f"Accounts: {added} added, {updated} updated" + (f", {bad} invalid." if bad else "."))
            self.fetch_avatars()
        bg(work, done=done)

    def add_browser(self, user: str = "", password: str = ""):
        if not HAVE_WEBENGINE:
            warn(self, "Browser login", "Qt WebEngine is not available. Paste the account's cookie instead.")
            return None
        d = BrowserLogin(self, self._validate, user, password)
        if d.exec() and d.cookie:
            self.add_cookies([d.cookie], {user.lower(): password} if user and password else None)
            return d.cookie
        return None

    def add_signup(self):
        """Roblox's real sign-up page in the built-in browser; you fill it in, the hub adds the login."""
        if not HAVE_WEBENGINE:
            warn(self, "Create account", "Qt WebEngine is not available. Sign up on roblox.com and paste the cookie.")
            return
        d = BrowserLogin(self, self._validate, signup=True)
        if d.exec() and d.cookie:
            self.add_cookies([d.cookie])

    def add_userpass(self):
        d = PasteDialog(self, "Add accounts with username:password",
                        "One account per line as <b>username:password</b>. For each one a login window opens with the "
                        "form filled in; you press Log In (and solve any captcha). The password is saved with the account.",
                        "user1:password1\nuser2:password2")
        if not d.exec():
            return
        pairs = []
        for line in d.text().splitlines():
            if ":" in line.strip():
                u, p = line.strip().split(":", 1)
                if u.strip():
                    pairs.append((u.strip(), p))
        for i, (u, p) in enumerate(pairs):
            self.log(f"Login {i + 1}/{len(pairs)}: {u}")
            if self.add_browser(u, p) is None and i < len(pairs) - 1:
                if not ask(self, "Browser login", f"The login for {u} was closed. Continue with the next account?"):
                    break

    def add_paste(self):
        d = PasteDialog(self, "Paste cookies", "Paste text containing one or more <tt>.ROBLOSECURITY</tt> cookies "
                        "(<tt>_|WARNING:-DO-NOT-SHARE-THIS...</tt>). Anything else in the text is ignored.")
        if d.exec():
            self.add_cookies(util.extract_cookies(d.text()))

    def add_file(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Import cookies", str(Path.home()), "Text files (*.txt *.json *.csv);;All files (*)")
        if fn:
            try:
                self.add_cookies(util.extract_cookies(Path(fn).read_text(errors="replace")))
            except OSError as ex:
                warn(self, "Import", str(ex))

    def add_from_sober(self):
        c = sober.main_cookie()
        if not c:
            warn(self, "Import from Sober", "No login was found in your Sober profile "
                 f"({sober.main_app() / 'data/sober/cookies'}). Log in inside Sober first "
                 "(and keep 'use_libsecret' off).")
            return
        self.add_cookies([c])

    def use_in_main_sober(self, a: Account):
        """Account switcher for your normal Sober: logs it into this account (for playing on your main desktop
        without multi-instance). The account Sober had before is saved to Cellar first, so you can switch back."""
        if not a.cookie:
            return warn(self, "Use in my Sober", f"{a.name} has no login saved.")
        if sober.main_sober_running():
            return warn(self, "Use in my Sober", "Close your normal Sober first, then try again.")
        if sober.main_sober_settings().get("use_libsecret"):
            return warn(self, "Use in my Sober", "Your Sober keeps its login in the system keyring "
                        "('use_libsecret' in Sober's settings), which Cellar cannot write to. Turn that option off "
                        "in Sober's config.json to use the account switcher.")

        def check_current():
            cur = sober.main_cookie()
            if not cur or cur == a.cookie:
                return cur, None
            return cur, api.authenticated(cur)

        def switch():
            sober.set_main_cookie(a.cookie)
            self.log(f"[{a.name}] is now the account in your normal Sober.")
            if ask(self, "Use in my Sober", f"Your normal Sober is now logged in as {a.name}.\n\nStart Sober now?"):
                fp = sober.which("flatpak")
                if fp:
                    subprocess.Popen([fp, "run", sober.SOBER_ID], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)

        def done(res):
            cur, who = res
            if who is not None and who.valid:
                known = store.find_by_user_id(who.id)
                if known:
                    if known.cookie != cur:         # Roblox may have refreshed it while Sober used it: keep the new one
                        known.cookie = cur
                        store.save_accounts()
                elif ask(self, "Use in my Sober", f"Your Sober is logged in as {who.name}, who is not in Cellar.\n\n"
                                                  f"Add {who.name} to Cellar first, so you can switch back later?"):
                    self.add_cookies([cur])
            switch()
        bg(check_current, done=done, err=lambda ex: warn(self, "Use in my Sober", str(ex)))

    def export_accounts(self, accs: List[Account]):
        if not accs:
            return
        fn, _ = QFileDialog.getSaveFileName(self, "Export accounts", str(Path.home() / "cellar-accounts.dat"),
                                            "Accounts file (*.dat)")
        if not fn:
            return
        pw = PasswordDialog.ask(self, "Export accounts", "A password for this file (you need it to import it):",
                                confirm=True)
        if not pw:
            return
        try:
            store.export_accounts(Path(fn), accs, pw)
        except Exception as ex:
            return warn(self, "Export accounts", str(ex))
        self.log(f"Exported {len(accs)} account(s) to {fn}. It holds their logins - keep it private. On the other "
                 "PC: Add account > Import accounts file.")

    def add_windows_file(self, fn: str = ""):
        if not fn:
            fn, _ = QFileDialog.getOpenFileName(self, "Import accounts file", str(Path.home()),
                                                "Accounts file (*.dat);;All files (*)")
        if not fn:
            return
        raw = Path(fn).read_bytes()
        if raw[:1] == b"D":
            warn(self, "Import", "This file is encrypted with Windows DPAPI and can only be opened on that Windows PC.\n\n"
                 "In the Windows app set a password (Settings > Encryption), then copy accounts.dat again.")
            return
        pw = None
        if raw[:1] == b"P":
            pw = PasswordDialog.ask(self, "Import accounts file", "Password of that accounts file:")
            if pw is None:
                return
        try:
            accs = store.accounts_from_json(store.decrypt_file(raw, pw))
        except Exception as ex:
            warn(self, "Import", str(ex))
            return
        added = 0
        for a in accs:
            if not a.cookie or store.find_by_user_id(a.user_id) or store.find_by_cookie(a.cookie):
                continue
            a.order = len(store.accounts)
            store.accounts.append(a)
            added += 1
        store.save_accounts()
        self.refresh_accounts()
        self.log(f"Imported {added} of {len(accs)} account(s) (accounts you already have were skipped).")
        self.fetch_avatars()

    def edit_selected(self):
        sel = self.selected_accounts()
        if not sel:
            return
        if len(sel) == 1:
            d = EditAccountDialog(self, sel[0])
            if d.exec():
                changed = d.apply()
                store.save_accounts()
                self.refresh_accounts()
                if changed:
                    self.add_cookies([sel[0].cookie])
        else:
            d = BulkEditDialog(self, sel)
            if d.exec():
                d.apply(sel)
                store.save_accounts()
                self.refresh_accounts()

    def remove_selected(self):
        sel = self.selected_accounts()
        if not sel:
            return
        names = ", ".join(a.name for a in sel[:6]) + ("..." if len(sel) > 6 else "")
        if not ask(self, "Remove accounts", f"Remove {len(sel)} account(s)?\n\n{names}\n\n"
                   "Their isolated Sober profiles are deleted too."):
            return
        for a in sel:
            store.accounts.remove(a)
        store.save_accounts()
        self.refresh_accounts()
        self.log(f"Removed {len(sel)} account(s).")

        def cleanup():
            for a in sel:
                self.launcher.stop_account(a)
                sober.reset_profile(a)
        bg(cleanup, done=lambda _: self.update_running())

    def details_selected(self):
        sel = self.selected_accounts()
        if not sel:
            return
        d = TextDialog(self, "Account details", "Loading...")

        def work():
            return ("\n\n" + "-" * 40 + "\n\n").join(api.details(a) for a in sel)
        bg(work, done=d.set_text)
        d.exec()

    def reset_selected_profiles(self):
        sel = self.selected_accounts()
        if not sel:
            self.log("Select the accounts whose Sober profile should be reset.")
            return
        if not ask(self, "Reset Sober profile", f"Delete the isolated Sober profile of {len(sel)} account(s)? "
                   "It is created again (from your normal Sober) on the next launch."):
            return

        def work():
            for a in sel:
                self.launcher.stop_account(a)
                sober.reset_profile(a)
        bg(work, done=lambda _: (self.update_running(), self.log(f"Reset the Sober profile of {len(sel)} account(s).")))

    def check_logins(self):
        accs = [a for a in store.accounts if a.cookie]

        def work():
            out = []
            for a in accs:
                out.append((a, api.authenticated(a.cookie)))
                time.sleep(0.3)
            return out

        def done(results):
            lost = []
            for a, u in results:
                li = store.live(a)
                if u.valid:
                    li.cookie_bad = False
                    a.login_lost = False
                    if u.name and u.name != a.username:
                        a.username = u.name
                    a.display_name = u.display or a.display_name
                    if not a.user_id:
                        a.user_id = u.id
                elif u.locked:
                    li.locked = True
                elif "expired" in u.error.lower():
                    li.cookie_bad = True
                    if not a.login_lost:
                        lost.append(a.name)
                        a.login_lost = True
            store.save_accounts()
            self.model.refresh_status()
            if lost:
                self.log("Signed out by Roblox (log in again): " + ", ".join(lost))
                self.desktop_notify("login", "Signed out by Roblox: " + ", ".join(lost))
                if self.isVisible():
                    warn(self, "Logins", "These accounts were signed out by Roblox and need a new login:\n\n" + "\n".join(lost))
            else:
                self.log(f"Startup check: {sum(1 for _, u in results if u.valid)} of {len(results)} login(s) valid.")
        bg(work, done=done)

    def fetch_avatars(self):
        ids = [a.user_id for a in store.accounts if a.user_id and not (paths.AVATAR_DIR / f"{a.user_id}.png").exists()]
        if not ids:
            return

        def work():
            urls = api.avatar_urls(ids)
            n = 0
            for uid, url in urls.items():
                data = api.download(url)
                if data:
                    (paths.AVATAR_DIR / f"{uid}.png").write_bytes(data)
                    n += 1
            return n

        def done(n):
            if n:
                self.model.forget_icons()
                self.model.reload()
                self.apply_sort()
        bg(work, done=done)

    def autohide_columns(self):
        """Group, Usage and Game only take room when some account has something in them."""
        m = self.model
        for col in (1, 3, 4):
            empty = not any(m.data(m.index(r, col)) for r in range(m.rowCount()))
            if self.table.isColumnHidden(col) != empty:
                self.table.setColumnHidden(col, empty)
