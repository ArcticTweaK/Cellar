"""Turning the Launch page / an account's own game into a LaunchSpec (port of MainForm.Launch.cs).

resolve_* functions do network calls - run them on a worker thread.
"""

import re
from dataclasses import dataclass
from typing import Callable, Optional

from . import api, store, util
from .models import Account, LaunchSpec


@dataclass
class LaunchForm:
    """A snapshot of the Launch page (taken on the UI thread)."""
    mode: str = "Game"          # Game | Job | Private | Follow
    place: str = ""
    job: str = ""
    private: str = ""
    follow: str = ""


def saved_spec(a: Account) -> Optional[LaunchSpec]:
    """The game stored on one account, or None."""
    link = a.game_link or ""
    share = util.share_code_of(link)
    if share:
        return LaunchSpec(kind="Private", share_code=share)
    pid = util.parse_place_id(link) or util.parse_place_id(a.saved_place_id)
    if pid <= 0:
        return None
    code = util.private_link_code(link)
    if code:
        return LaunchSpec(kind="Private", place_id=pid, link_code=code)
    if util.looks_like_guid(a.saved_job_id):
        return LaunchSpec(kind="Job", place_id=pid, job_id=a.saved_job_id.strip())
    return LaunchSpec(kind="Game", place_id=pid)


def resolve_form(f: LaunchForm, first: Account, logf: Callable[[str], None]) -> Optional[LaunchSpec]:
    if f.mode in ("Game", "Job"):
        pid = util.parse_place_id(f.place)
        if pid <= 0:
            logf("Enter a valid Place ID (or paste a game link).")
            return None
        s = LaunchSpec(kind=f.mode, place_id=pid)
        if f.mode == "Job":
            if not util.looks_like_guid(f.job):
                logf("The Job ID must look like xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.")
                return None
            s.job_id = f.job.strip()
        return s
    if f.mode == "Private":
        link = f.private.strip()
        if not link:
            logf("Paste a private server link first.")
            return None
        game = re.search(r"/games/(\d+)", link)
        code = util.private_link_code(link)
        if game and code:
            return LaunchSpec(kind="Private", place_id=int(game.group(1)), link_code=code)
        share = util.share_code_of(link)
        if share:
            logf("Resolving the share link...")
            r = api.resolve_share(share, first.cookie)
            if r is None:
                logf("Could not resolve that link. The first selected account must be allowed to use this private server.")
            return r
        logf("That does not look like a private server link.")
        return None
    name = f.follow.strip()
    if not name:
        logf("Type the username of the player to follow.")
        return None
    u = api.user_by_name(name)
    if not u.valid:
        logf(f"Could not find user '{name}' ({u.error}).")
        return None
    pr = api.presence(first.cookie, [u.id]).get(u.id)
    if pr is not None:
        if pr.type == 2:
            logf(f"{u.name} is in a game: {pr.location}")
        else:
            logf(f"Heads-up: {u.name} does not look like they are in a game right now (or hide it). "
                 "Roblox may refuse the follow. Launching anyway.")
    return LaunchSpec(kind="Follow", follow_user_id=u.id, follow_name=u.name)


def resolve_saved_share(a: Account, per: LaunchSpec, logf: Callable[[str], None], save: bool = True) -> bool:
    """Resolves a share link with that account's login. save=True (the account's own saved link): also rewrites
    the saved link to the old form, so later launches skip this step. A one-off launch (Your games, a website Play link) must
    not touch what the account has saved."""
    logf(f"{a.name}: resolving its private server link...")
    r = api.resolve_share(per.share_code, a.cookie)
    if r is None or r.place_id <= 0 or not r.link_code:
        logf(f"{a.name}: skipped - could not open its private server link "
             "(the account must own this server or be invited to it).")
        return False
    per.kind, per.place_id, per.link_code, per.share_code = "Private", r.place_id, r.link_code, ""
    if not save:
        return True
    a.game_link = f"https://www.roblox.com/games/{r.place_id}?privateServerLinkCode={r.link_code}"
    a.saved_place_id = str(r.place_id)
    store.save_accounts()
    return True
