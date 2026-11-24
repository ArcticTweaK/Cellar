"""Reads the Roblox client's own log of each running account to see joins, teleports, leaves and disconnects
the moment they happen (seconds, instead of the minutes the presence watcher needs).

The log is the Roblox engine's (data/sober/appData/logs/*.log in the account's Sober folder). Lines used, the
same ones Bloxstrap's activity tracking reads:
    [FLog::Output] ! Joining game '<job id>' place <place id> at <ip>           -> joined a server
    [FLog::SingleSurfaceApp] initiateTeleport...                                 -> teleporting (not a kick)
    [FLog::SingleSurfaceApp] leaveUGCGameInternal                                -> left the game itself
    [FLog::Network] Time to disconnect replication data: ...                     -> connection to the server ended
A disconnect that is not part of a teleport or a leave is a kick / lost connection. The reason number
(267 kicked, 277 lost connection, 279 failed to connect...) is taken from the disconnect lines when Roblox
writes one.
"""

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

_JOIN = re.compile(r"! Joining game '([0-9a-fA-F-]{36})' place (\d+)")
_REASON = re.compile(r"[Rr]eason:?\s*(\d{3})\b")
_DISCONNECT = "[FLog::Network] Time to disconnect replication data"
_TELEPORT = "[FLog::SingleSurfaceApp] initiateTeleport"
_LEAVE = "[FLog::SingleSurfaceApp] leaveUGCGameInternal"

REASONS = {267: "kicked by the game", 268: "kicked (unexpected client behaviour)", 273: "logged in somewhere else",
           277: "lost connection", 278: "kicked for being idle", 279: "could not connect",
           285: "left the game (the client said goodbye)", 529: "Roblox had a problem"}


@dataclass
class Event:
    kind: str                   # joined | left | teleport | disconnected
    place_id: int = 0
    job_id: str = ""
    reason: int = 0
    ts: float = 0.0             # when (unix time, from the log line); 0 = unknown

    def describe(self) -> str:
        if self.kind == "disconnected":
            why = REASONS.get(self.reason, f"error {self.reason}" if self.reason else "disconnected")
            return why[0].upper() + why[1:]
        return self.kind


def line_time(line: str) -> float:
    """Unix time of a Roblox log line ("2026-11-24T20:16:14.294Z,..." - UTC); 0 if it has none."""
    from datetime import datetime, timezone
    try:
        return datetime.strptime(line[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


@dataclass
class Tail:
    """Follows the newest log file of one client."""
    folder: Path
    since: float                # only files written after this (the client's start)
    path: Optional[Path] = None
    offset: int = 0
    buf: str = ""
    teleporting: float = 0.0
    leaving: bool = False
    place_id: int = 0
    job_id: str = ""
    pending_reason: int = 0
    events: List[Event] = field(default_factory=list)

    def _newest(self) -> Optional[Path]:
        try:
            files = [f for f in self.folder.glob("*.log") if f.stat().st_mtime >= self.since - 5]
        except OSError:
            return None
        return max(files, key=lambda f: f.stat().st_mtime, default=None)

    def poll(self) -> List[Event]:
        newest = self._newest()
        if newest is None:
            return []
        if newest != self.path:             # Roblox starts a new file per session (also after some teleports)
            self.path, self.offset, self.buf = newest, 0, ""
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                data = f.read(4 * 1024 * 1024)
                self.offset += len(data)
        except OSError:
            return []
        text = self.buf + data.decode(errors="replace")
        lines = text.split("\n")
        self.buf = lines.pop()              # an unfinished last line waits for the next poll
        out: List[Event] = []
        for line in lines:
            ev = self._line(line)
            if ev:
                out.append(ev)
        return out

    def _line(self, line: str) -> Optional[Event]:
        ev = self._event(line)
        if ev is not None:
            ev.ts = line_time(line)
        return ev

    def _event(self, line: str) -> Optional[Event]:
        m = _JOIN.search(line)
        if m:
            self.job_id, self.place_id = m.group(1).lower(), int(m.group(2))
            self.teleporting, self.leaving, self.pending_reason = 0.0, False, 0
            return Event("joined", self.place_id, self.job_id)
        if _TELEPORT in line:
            self.teleporting = time.time()
            return Event("teleport", self.place_id, self.job_id)
        if _LEAVE in line:
            self.leaving = True
            return Event("left", self.place_id, self.job_id)
        if "disconnect" in line.lower():
            r = _REASON.search(line)
            if r:
                self.pending_reason = int(r.group(1))
        if _DISCONNECT in line:
            if self.leaving or time.time() - self.teleporting < 60:
                return None
            return Event("disconnected", self.place_id, self.job_id, self.pending_reason)
        return None


class Watcher:
    """One Tail per running client, keyed by the instance's tracker id."""

    def __init__(self):
        self.tails: Dict[int, Tail] = {}

    def poll(self, items: Dict[int, tuple]) -> Dict[int, List[Event]]:
        """items: tracker -> (logs folder, client start time). Returns tracker -> new events."""
        for t in [t for t in self.tails if t not in items]:
            del self.tails[t]
        out: Dict[int, List[Event]] = {}
        for tracker, (folder, started) in items.items():
            tail = self.tails.get(tracker)
            if tail is None:
                tail = self.tails[tracker] = Tail(Path(folder), started)
            evs = tail.poll()
            if evs:
                out[tracker] = evs
        return out

    def where(self, tracker: int) -> tuple:
        t = self.tails.get(tracker)
        return (t.place_id, t.job_id) if t else (0, "")


def logs_folder(app: Path) -> Path:
    return app / "data" / "sober" / "appData" / "logs"


# ---------------------------------------------------------------- reading a whole log (the Roblox logs window)
# "2026-11-24T20:16:14.294Z,39.29,4256b6c0,6,Error [DFLog::AssetProvider] text" - the severity is missing on some
# lines ("...,6 [FLog::Output] ! Joining game ..."). Times are UTC.
_LINE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z,[\d.]+,[0-9a-fA-F]+,\d+(?:,(\w+))?\s+(.*)$")
_SOBER = re.compile(r"^(info|warn|warning|error|debug|trace):\s*(.*)$", re.I)
# Roblox calls its own startup notes "Critical" (memory allocator settings, build id): those are not problems
_SEVERITY = {"error": "error", "fatal": "error", "warning": "warning", "warn": "warning"}
# Measured on a 9,312-line session: 5,905 "Error" lines, all but 2 from these - the engine's animation chatter,
# the game's own scripts, asset downloads and cache housekeeping. Not something a player (or Cellar) can fix.
NOISE = ("[DFLog::SlimRendererAnimation]", "[FLog::CreatorError]", "[DFLog::AssetProvider]",
         "[DFLog::SQLite] Database::walCheckpoint")      # Roblox's own cache database housekeeping


@dataclass
class LogLine:
    time: str                   # local HH:MM:SS ("" when the line has none)
    severity: str               # error | warning | info
    text: str                   # the line without its time / thread prefix
    event: str = ""             # what happened, in plain words (joins, teleports, leaves, disconnects)
    noise: bool = False         # a NOISE channel (the game's own errors, engine chatter)

    @property
    def worth_showing(self) -> bool:
        """'What happened': events and errors of Roblox / Sober themselves."""
        return bool(self.event) or (self.severity == "error" and not self.noise)


def _local_time(iso: str) -> str:
    from datetime import datetime, timezone
    try:
        return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).astimezone().strftime("%H:%M:%S")
    except ValueError:
        return ""


def parse_line(raw: str) -> Optional[LogLine]:
    raw = raw.rstrip("\r\n")
    if not raw.strip():
        return None
    m = _LINE.match(raw)
    if m:
        sev = _SEVERITY.get((m.group(2) or "").lower(), "info")
        text = m.group(3)
        ln = LogLine(_local_time(m.group(1)), sev, text, noise=text.startswith(NOISE))
        j = _JOIN.search(text)
        if j:
            ln.event = f"Joined place {j.group(2)} (server {j.group(1)[:8]}...)"
        elif _TELEPORT in text:
            ln.event = "Teleporting to another place"
        elif _LEAVE in text:
            ln.event = "Left the game"
        elif _DISCONNECT in text:
            ln.event = "Disconnected from the server"
        elif "disconnect" in text.lower() and _REASON.search(text):
            code = int(_REASON.search(text).group(1))
            ln.event = f"Disconnect reason {code}: {REASONS.get(code, 'see Roblox error codes')}"
        return ln
    s = _SOBER.match(raw)                   # Sober's own log
    if s:
        return LogLine("", _SEVERITY.get(s.group(1).lower(), "info"), s.group(2))
    return LogLine("", "info", raw)         # a continuation line (stack traces...)


def log_files(app: Path) -> List[tuple]:
    """(label, path) of every Roblox log (newest first), then Sober's own logs, in one Sober folder."""
    from datetime import datetime
    out = []
    for kind, folder in (("Roblox", logs_folder(app)), ("Sober", app / "data" / "sober" / "sober_logs")):
        try:
            files = sorted((f for f in folder.glob("*.log") if f.is_file()), key=lambda f: -f.stat().st_mtime)
        except OSError:
            continue
        for f in files:
            st = f.stat()
            when = datetime.fromtimestamp(st.st_mtime).strftime("%a %d %b %H:%M")
            out.append((f"{kind} log - {when} ({st.st_size / 1024:.0f} KB)", f))
    return out


MAX_LINES = 30000                   # a long session writes 100k+ lines; the newest ones are the interesting ones


def read_log(path: Path) -> tuple:
    """Worker: (lines, total) - the newest MAX_LINES parsed lines and how many the file has."""
    try:
        raw = path.read_text(errors="replace").splitlines()
    except OSError:
        return [], 0
    lines = [ln for ln in (parse_line(r) for r in raw[-MAX_LINES:]) if ln]
    return lines, len(raw)


def available(app: Path) -> bool:
    return os.path.isdir(logs_folder(app))
