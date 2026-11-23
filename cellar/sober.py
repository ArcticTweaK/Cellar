"""Everything that talks to Sober (the Flatpak that runs Roblox on Linux).

Sober only allows one copy per machine: every copy claims the same localhost port and a
second one quits ("An instance of Sober is already running"). Multi-instance therefore
isolates, per account, the things the copies would otherwise share:

  * its own Sober profile    - a separate HOME, so ~/.var/app/org.vinegarhq.Sober (login,
                               settings, Roblox files) is private to that account. New
                               profiles are copy-on-write clones of your normal Sober profile
                               (cp --reflink: no extra disk on btrfs/xfs);
  * its own network namespace - private localhost/ports (so the copies don't see each other's
                               port), created by `unshare --net` and connected to the internet by
                               attaching `pasta` (package passt, rootless) to it. pasta must NOT be
                               the one that starts Sober: it would also put it in a new PID
                               namespace, Flatpak then records PIDs the desktop portal can't find,
                               every portal call is refused (NetworkMonitor too), and Roblox waits
                               ~120 s before connecting and is then often ignored (error 279);
  * its own time / IPC namespace - `unshare --time --ipc`; without the time namespace later
                               copies abort a few minutes in. The same unshare maps the user to
                               your real uid, so D-Bus and the portals accept the clients;
  * its own XDG_RUNTIME_DIR   - with links to the real Wayland / PipeWire / Pulse / D-Bus sockets.

Every client is started with a roblox-player: link that carries the account's unique
browsertrackerid, which also shows up on the command line of Sober's window process - that
is how windows and processes are mapped back to accounts.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from . import log, paths
from .models import Account, AppSettings, LaunchSpec

SOBER_ID = paths.SOBER_ID
PASTA_ARGS = ["--config-net", "-t", "none", "-u", "none", "-T", "none", "-U", "none", "--no-map-gw", "-q"]

# Runs a command in its own user + network + IPC + time namespace - but in the normal PID namespace,
# see the module docstring - and attaches pasta for internet access before the command starts.
# usage: sh -c NETNS_SCRIPT cellar-netns READYFILE UID GID UNSHARE PASTA [PASTA-ARGS...] -- COMMAND [ARGS...]
NETNS_SCRIPT = r'''
ready=$1 uid=$2 gid=$3 unshare_bin=$4 pasta_bin=$5
shift 5
pasta_args=
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do pasta_args="$pasta_args $1"; shift; done
[ "$#" -gt 0 ] && shift
rm -f "$ready" "$ready.pasta"
"$unshare_bin" --user --map-user="$uid" --map-group="$gid" --net --ipc --time --fork \
    sh -c 'while [ ! -e "$0" ]; do sleep 0.02; done; exec "$@"' "$ready" "$@" &
child=$!
trap 'kill "$child" 2>/dev/null' TERM INT HUP
host_ns=$(readlink "/proc/$$/ns/net")
i=0
while :; do
    ns=$(readlink "/proc/$child/ns/net" 2>/dev/null) || { wait "$child"; exit $?; }
    [ "$ns" != "$host_ns" ] && break
    i=$((i + 1))
    if [ "$i" -gt 1000 ]; then echo "cellar-netns: the network namespace did not appear" >&2; kill "$child"; exit 1; fi
    sleep 0.01
done
if ! "$pasta_bin" $pasta_args -P "$ready.pasta" "$child"; then
    echo "cellar-netns: pasta could not connect the network namespace" >&2; kill "$child"; exit 1
fi
touch "$ready"
wait "$child"; rc=$?
[ -s "$ready.pasta" ] && kill "$(cat "$ready.pasta")" 2>/dev/null
rm -f "$ready" "$ready.pasta"
exit "$rc"
'''
# Processes that may belong to one of our clients (only these are ever signalled).
OWN_COMMS = ("pasta", "passt", "unshare", "flatpak", "bwrap", "sober", "Main", "xdg-dbus-proxy", "sober_services")
_TRACKER_RE = re.compile(r"browsertrackerid:(\d+)")

_cache: Dict[str, object] = {}


# ---------------------------------------------------------------- tools
def which(name: str) -> Optional[str]:
    # PATH first; the fixed folders cover apps started from a desktop entry with a short PATH.
    p = shutil.which(name)
    if p:
        return p
    for d in ("/run/current-system/sw/bin", "/usr/bin", "/usr/local/bin", "/bin"):
        c = os.path.join(d, name)
        if os.access(c, os.X_OK):
            return c
    return None


def sober_installed() -> bool:
    if _cache.get("sober"):
        return True
    fp = which("flatpak")
    if not fp:
        return False
    try:
        ok = subprocess.run([fp, "info", SOBER_ID], capture_output=True, timeout=15).returncode == 0
    except Exception:
        ok = False
    if ok:
        _cache["sober"] = True
    return ok


def sober_version() -> str:
    fp = which("flatpak")
    try:
        out = subprocess.run([fp, "info", SOBER_ID], capture_output=True, text=True, timeout=15).stdout
        m = re.search(r"Version:\s*(\S+)", out)
        return m.group(1) if m else ""
    except Exception:
        return ""


def multi_instance_support() -> Tuple[bool, str]:
    """(available, reason if not)."""
    missing = [t for t in ("pasta", "unshare", "flatpak") if not which(t)]
    if missing:
        return False, "missing: " + ", ".join(missing) + (" (install the 'passt' package)" if "pasta" in missing else "")
    return True, ""


# ---------------------------------------------------------------- profiles
def profile_home(a: Account) -> Path:
    return paths.PROFILES_DIR / a.id


def profile_app(a: Account) -> Path:
    return profile_home(a) / ".var" / "app" / SOBER_ID


def main_app() -> Path:
    return paths.MAIN_SOBER_DIR


def _reflink_copy(src: Path, dst_dir: Path) -> bool:
    """Copy src into dst_dir as copy-on-write clones when the filesystem supports it."""
    cp = which("cp")
    try:
        r = subprocess.run([cp, "-a", "--reflink=auto", str(src), str(dst_dir) + "/"], capture_output=True, timeout=600)
        if r.returncode != 0:
            log.write(f"Copying {src.name} failed: {r.stderr.decode(errors='replace').strip()}")
        return r.returncode == 0
    except Exception as ex:
        log.write(f"Copying {src.name} failed: {ex}")
        return False


# account-specific bits of a Sober profile that must never be cloned into another account
_PRIVATE = ["data/sober/cookies", "data/sober/sober_logs", "data/sober/crashes", "data/sober/appData/logs",
            "data/sober/appData/LocalStorage", "data/sober/appData/rbx-storage", "data/sober/appData/rbx-storage-sc",
            "data/sober/appData/rbx-storage.db", "data/sober/appData/rbx-storage.db-wal",
            "data/sober/appData/rbx-storage.db-shm", "data/sober/appData/rbx-storage.id",
            "data/sober/appData/tmp-capture-storage"]


def _rm(p: Path) -> None:
    try:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        elif p.exists() or p.is_symlink():
            p.unlink()
    except OSError:
        pass


def _read_state(app: Path) -> dict:
    try:
        return json.loads((app / "data" / "sober" / "state").read_text())
    except Exception:
        return {}


def _version_tuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def app_version(app: Path) -> str:
    return str(_read_state(app).get("v1", {}).get("app_version", ""))


def _seed_caches(main: Path, app: Path) -> None:
    """Gives a profile Roblox's settings ("fast flag") cache and Vulkan shader cache when it has none.
    Saves a new profile from starting with no saved settings and compiling every shader on its first game.
    (It does NOT fix the 120 s wait before isolated clients connect; profiles with a cache wait too.)
    Nothing account-specific is in these."""
    src, dst = main / "cache" / "sober", app / "cache" / "sober"
    for name in ("cache", "shadercachevk.bin"):
        if (src / name).exists() and not (dst / name).exists():
            dst.mkdir(parents=True, exist_ok=True)
            _reflink_copy(src / name, dst)


def ensure_profile(a: Account, s: AppSettings, logf) -> Path:
    """Creates this account's Sober profile (cloned from your main Sober) or refreshes its Roblox files."""
    app = profile_app(a)
    main = main_app()
    have_main = (main / "data" / "sober").is_dir()
    if have_main and (app / "data" / "sober").is_dir():
        _seed_caches(main, app)
    if (app / "data" / "sober").is_dir():
        if s.keep_profiles_updated and have_main:
            mv, pv = app_version(main), app_version(app)
            if mv and pv and _version_tuple(mv) > _version_tuple(pv):
                logf(f"[{a.name}] updating its Roblox files {pv} -> {mv} from your main Sober...")
                for d in ("packages", "assets"):
                    if (main / "data" / "sober" / d).is_dir():
                        _rm(app / "data" / "sober" / d)
                        _reflink_copy(main / "data" / "sober" / d, app / "data" / "sober")
                st = _read_state(app)
                st.setdefault("v1", {})["app_version"] = mv
                (app / "data" / "sober" / "state").write_text(json.dumps(st, indent=4))
        return app

    (app / "data" / "sober").mkdir(parents=True, exist_ok=True)
    (app / "config").mkdir(parents=True, exist_ok=True)
    (app / "cache").mkdir(parents=True, exist_ok=True)
    if have_main:
        logf(f"[{a.name}] creating its own Sober profile (copy-on-write clone of your Sober)...")
        for d in ("packages", "assets", "appData"):
            if (main / "data" / "sober" / d).is_dir():
                _reflink_copy(main / "data" / "sober" / d, app / "data" / "sober")
        if (main / "config" / "sober").is_dir():
            _reflink_copy(main / "config" / "sober", app / "config")
        _seed_caches(main, app)
        st = _read_state(main)
        st.pop("v6", None)                       # remembers the logged-in user id
        try:
            (app / "data" / "sober" / "state").write_text(json.dumps(st, indent=4))
        except OSError:
            pass
        for rel in _PRIVATE:
            _rm(app / rel)
    else:
        logf(f"[{a.name}] new empty Sober profile (Sober was never started normally, so it downloads Roblox once).")
    return app


def reset_profile(a: Account) -> None:
    _rm(profile_home(a))


# ---------------------------------------------------------------- per-profile settings
_HEADER = ("// Managed by Cellar for one account. Changes here are overwritten on the next launch;\n"
           "// use the Performance page of Cellar instead.\n")


def read_sober_config(app: Path) -> dict:
    try:
        text = (app / "config" / "sober" / "config.json").read_text(encoding="utf-8")
        body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//"))
        d = json.loads(body)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _basic_settings_file(app: Path) -> Optional[Path]:
    best, best_n = None, -1
    for f in (app / "data" / "sober" / "appData").glob("GlobalBasicSettings_*.xml"):
        m = re.match(r"GlobalBasicSettings_(\d+)\.xml$", f.name)
        if m and int(m.group(1)) > best_n:
            best, best_n = f, int(m.group(1))
    return best


_FPS_RE = re.compile(r'(<int name="FramerateCap">)(-?\d+)(</int>)')


def read_fps_cap(app: Path) -> Optional[int]:
    f = _basic_settings_file(app)
    if not f:
        return None
    m = _FPS_RE.search(f.read_text(encoding="utf-8", errors="replace"))
    return int(m.group(2)) if m else None


def write_fps_cap(app: Path, cap: int) -> str:
    """Puts cap into Roblox's own settings file of that profile. Returns '' or the reason it failed."""
    f = _basic_settings_file(app)
    if not f:
        return "Roblox's settings file does not exist yet in this profile (start it once)"
    xml = f.read_text(encoding="utf-8", errors="replace")
    m = _FPS_RE.search(xml)
    if not m:
        return "the settings file has no FramerateCap entry yet"
    if int(m.group(2)) != cap:
        f.write_text(xml[:m.start(2)] + str(cap) + xml[m.end(2):], encoding="utf-8")
    return ""


def write_profile_settings(a: Account, s: AppSettings, flags: Dict[str, object], logf) -> None:
    app = profile_app(a)
    cfg_path = app / "config" / "sober" / "config.json"
    cfg = read_sober_config(app)
    so = s.sober
    cfg.update({
        "use_opengl": so.use_opengl,
        "graphics_optimization_mode": so.graphics_optimization_mode,
        # GameMode raises the priority of "the" game; for a row of alts that only takes CPU away from
        # your main (which keeps it in your normal Sober), so isolated profiles keep it off.
        "enable_gamemode": False,
        "close_on_leave": so.close_on_leave,
        "discord_rpc_enabled": so.discord_rpc_enabled,
        "server_location_indicator_enabled": so.server_location_indicator_enabled,
        "enable_hidpi": so.enable_hidpi,
        "use_libsecret": False,            # keep each profile's login inside its own folder
        "fflags": flags,
    })
    try:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(_HEADER + json.dumps(cfg, indent=4) + "\n", encoding="utf-8")
    except OSError as ex:
        logf(f"[{a.name}] could not write its Sober settings: {ex}")

    # The global cap is the alt cap: an account marked "Full quality" (your main) only uses its own.
    cap = a.fps_cap if a.fps_cap > 0 else (0 if a.full_quality else s.fps_cap)
    if cap <= 0:
        cap = read_fps_cap(main_app()) or 0     # 0 = same as your normal Sober
    if cap:
        err = write_fps_cap(app, cap)
        if err and a.fps_cap > 0:
            logf(f"[{a.name}] FPS cap not set: {err}")


def main_sober_settings() -> dict:
    return read_sober_config(main_app())


def main_cookie() -> Optional[str]:
    """The .ROBLOSECURITY cookie your normal Sober is logged in with (if stored in plain text)."""
    from .util import extract_cookies
    try:
        found = extract_cookies((main_app() / "data" / "sober" / "cookies").read_text(errors="replace"))
        return found[0] if found else None
    except OSError:
        return None


# ---------------------------------------------------------------- launching
# Runtime folders and systemd units of the clients: <prefix><first 12 chars of the account id>...
PREFIX = "cellar-"
OLD_PREFIX = "rmh-"         # clients started by Roblox MultiHub for Linux, before the rename


def runtime_dir_path(a: Account, prefix: str = PREFIX) -> Path:
    return paths.runtime_dir() / (prefix + a.id[:12])


def old_clients_running() -> bool:
    """True while clients started under the old name are still running."""
    try:
        out = subprocess.run([which("systemctl") or "systemctl", "--user", "list-units", "--plain", "--no-legend",
                              f"{OLD_PREFIX}*"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return True                 # unknown: keep what they might need
    return bool(out.strip())


def runtime_dir_for(a: Account) -> Path:
    base = paths.runtime_dir()
    d = runtime_dir_path(a)
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    wayland = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
    # .flatpak: Flatpak's per-instance info (bwrapinfo.json) must be where the portals look for
    # it, or they refuse requests such as GameMode's RegisterGame.
    names = [wayland, "pulse", "pipewire-0", "pipewire-0-manager", "bus", ".flatpak", "doc"]
    for n in names:
        src, dst = base / n, d / n
        if not src.exists():
            continue
        if os.path.islink(dst) and os.readlink(dst) == str(src):
            continue
        try:
            if os.path.lexists(dst):          # stale link or a folder a client created here before
                if os.path.isdir(dst) and not os.path.islink(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                else:
                    os.unlink(dst)
            os.symlink(src, dst)
        except OSError as ex:
            log.write(f"runtime dir link {n} failed: {ex}")
    return d


def place_launcher_url(s: AppSettings, spec: LaunchSpec, tracker: int) -> str:
    b = (s.place_launcher_url or "").strip() or "https://www.roblox.com/Game/PlaceLauncher.ashx"
    if spec.kind == "Job":
        return (f"{b}?request=RequestGameJob&browserTrackerId={tracker}&placeId={spec.place_id}"
                f"&gameId={spec.job_id}&isPlayTogetherGame=false")
    if spec.kind == "Private":
        return f"{b}?request=RequestPrivateGame&placeId={spec.place_id}&linkCode={spec.link_code}"
    if spec.kind == "Follow":
        return f"{b}?request=RequestFollowUser&userId={spec.follow_user_id}"
    return f"{b}?request=RequestGame&browserTrackerId={tracker}&placeId={spec.place_id}&isPlayTogetherGame=false"


def _urlencode(s: str) -> str:
    # Uppercase percent-escapes, like the Roblox website (encodeURIComponent). Sober only enters the game
    # straight from the link with "%3A%2F..."; the lowercase "%3a%2f..." that .NET's HttpUtility.UrlEncode
    # (Windows app) produces makes Sober load its home screen instead and join from there, very slowly.
    return quote(s, safe="")


def build_uri(ticket: str, launch_ms: int, pl_url: str, tracker: int) -> str:
    return ("roblox-player:1+launchmode:play+gameinfo:" + ticket + "+launchtime:" + str(launch_ms)
            + "+placelauncherurl:" + _urlencode(pl_url) + "+browsertrackerid:" + str(tracker)
            + "+robloxLocale:en_us+gameLocale:en_us+channel:+LaunchExp:InApp")


def build_command(uri: str, a: Account, isolated: bool,
                  wayland: Optional[str] = None) -> Tuple[List[str], Dict[str, str], str]:
    """Returns (argv, env, systemd unit name or ''). wayland: socket name (in the account's runtime
    dir) of another display - background mode's invisible screen - instead of your desktop."""
    env = dict(os.environ)
    if wayland:
        env["WAYLAND_DISPLAY"] = wayland
    flatpak = which("flatpak") or "flatpak"
    sober = [flatpak, "run", "--command=sober", SOBER_ID, "--", uri]
    if isolated:
        real_rt = paths.runtime_dir()
        if not env.get("DBUS_SESSION_BUS_ADDRESS"):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={real_rt}/bus"
        # HOME / XDG_RUNTIME_DIR only for what runs inside: systemd-run itself needs the real
        # runtime dir to find the systemd user manager.
        rt = runtime_dir_for(a)
        inner = [f"HOME={profile_home(a)}", f"XDG_RUNTIME_DIR={rt}"]
        argv = [which("env") or "env", *inner,
                which("sh") or "sh", "-c", NETNS_SCRIPT, "cellar-netns", str(rt / ".netns-ready"),
                str(os.getuid()), str(os.getgid()), which("unshare") or "unshare", which("pasta") or "pasta",
                *PASTA_ARGS, "--", *sober]
    else:
        argv = sober
    # Own systemd scope per client: one handle to stop everything it started and to put
    # CPU / memory limits on (Flatpak may still move the sandbox into a scope of its own).
    run = which("systemd-run")
    unit = ""
    if run:
        unit = f"{PREFIX}{a.id[:12]}-{int(time.time())}.scope"
        argv = [run, "--user", "--scope", "--quiet", "--collect", f"--unit={unit}",
                f"--description=Cellar: {a.name}", "--", *argv]
    return argv, env, unit


def spawn(argv: List[str], env: Dict[str, str], log_file: Path) -> subprocess.Popen:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    out = open(log_file, "ab")
    try:
        out.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} launch =====\n".encode())
        out.flush()
        return subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True, cwd=str(paths.HOME))
    finally:
        out.close()


# ---------------------------------------------------------------- processes
@dataclass
class Proc:
    pid: int
    ppid: int
    comm: str
    cmdline: str


def scan() -> List[Proc]:
    out = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", "rb") as f:
                st = f.read().decode(errors="replace")
            r = st.rfind(")")
            comm = st[st.find("(") + 1:r]
            ppid = int(st[r + 2:].split()[1])
            with open(f"/proc/{name}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode(errors="replace")
            out.append(Proc(int(name), ppid, comm, cmd))
        except (OSError, ValueError, IndexError):
            continue
    return out


def tracker_of(cmdline: str) -> int:
    m = _TRACKER_RE.search(cmdline or "")
    return int(m.group(1)) if m else 0


def is_own_comm(comm: str) -> bool:
    return any(comm.startswith(c) for c in OWN_COMMS)


def window_pid(tracker: int, procs: List[Proc] = None) -> int:
    """PID of Sober's window process ("Main" - the one KWin reports for the window), or 0."""
    needle = f"browsertrackerid:{tracker}+"
    for p in procs if procs is not None else scan():
        if p.comm == "Main" and needle in p.cmdline + "+":
            return p.pid
    return 0


def client_starting(tracker: int, procs: List[Proc] = None) -> bool:
    """True while Sober runs for this tracker but has not created its window process yet."""
    needle = f"browsertrackerid:{tracker}+"
    return any(p.comm in ("sober", "bwrap") and needle in p.cmdline + "+"
               for p in (procs if procs is not None else scan()))


def tracker_of_pid(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return tracker_of(f.read().replace(b"\0", b" ").decode(errors="replace"))
    except OSError:
        return 0


def all_sober_trackers(procs: List[Proc] = None) -> Dict[int, int]:
    """tracker -> window pid, for every running Sober client (ours or not)."""
    res: Dict[int, int] = {}
    for p in procs if procs is not None else scan():
        if p.comm in ("Main", "sober") and "roblox-player:" in p.cmdline:
            t = tracker_of(p.cmdline)
            if t and (p.comm == "Main" or t not in res):
                res[t] = p.pid
    return res


def sober_running_unmanaged(known: List[int], procs: List[Proc] = None) -> bool:
    """True when a Sober client runs that this app did not start (e.g. your normal Sober)."""
    for p in procs if procs is not None else scan():
        if p.comm == "sober" and p.cmdline.startswith("/proc/self/exe"):
            t = tracker_of(p.cmdline)
            if not t or t not in known:
                return True
    return False


def alive(pid: int, tracker: int) -> bool:
    if pid <= 0:
        return False
    return tracker_of_pid(pid) == tracker if tracker else os.path.exists(f"/proc/{pid}")


def descendants(root: int, procs: List[Proc]) -> List[int]:
    kids: Dict[int, List[int]] = {}
    for p in procs:
        kids.setdefault(p.ppid, []).append(p.pid)
    out, todo = [], [root]
    while todo:
        cur = todo.pop()
        for k in kids.get(cur, []):
            if k not in out:
                out.append(k)
                todo.append(k)
    return out


def scope_of(pid: int) -> Optional[str]:
    """The systemd scope this client runs in: Flatpak's (app-flatpak-org.vinegarhq.Sober-N.scope)
    or the one this app created for it (cellar-....scope, rmh-....scope before the rename)."""
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            for line in f:
                m = re.search(r"/(app-flatpak-org\.vinegarhq\.Sober-[^/]+\.scope|(?:cellar|rmh)-[^/]+\.scope)\s*$", line.strip())
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


def instance_pids(launch_pid: int, tracker: int) -> List[int]:
    procs = scan()
    by_pid = {p.pid: p for p in procs}
    pids = set()
    if launch_pid and launch_pid in by_pid:
        pids.add(launch_pid)
        pids.update(descendants(launch_pid, procs))
    if tracker:
        needle = f"browsertrackerid:{tracker}+"
        for p in procs:
            if needle in p.cmdline + "+":
                pids.add(p.pid)
                pids.update(descendants(p.pid, procs))
    return [p for p in pids if p in by_pid and is_own_comm(by_pid[p].comm)]


def stop(launch_pid: int, tracker: int, wait: float = 3.0, unit: str = "") -> int:
    """Closes one client completely (sandbox, pasta, everything). Returns how many processes it signalled."""
    pids = instance_pids(launch_pid, tracker)
    scopes = {s for s in (scope_of(p) for p in pids) if s}
    if unit:
        scopes.add(unit)
    sc = which("systemctl")
    for s in scopes:
        if sc:
            subprocess.run([sc, "--user", "--no-block", "stop", s], capture_output=True, timeout=10)
    for p in pids:
        try:
            os.kill(p, signal.SIGTERM)
        except OSError:
            pass
    end = time.time() + wait
    while time.time() < end and any(os.path.exists(f"/proc/{p}") for p in pids):
        time.sleep(0.15)
    for p in pids:
        try:
            os.kill(p, signal.SIGKILL)
        except OSError:
            pass
    return len(pids)


# ---------------------------------------------------------------- CPU priority / RAM cap
CPU_WEIGHT = {"Normal": "100", "BelowNormal": "40", "Idle": "idle"}
NICE = {"Normal": 0, "BelowNormal": 10, "Idle": 19}


def apply_limits(window_pid_: int, priority: str, ram_cap_mb: int) -> str:
    """CPU weight + memory cap through the client's systemd scope; renice as a fallback.
    Returns '' on success or a short reason."""
    scope = scope_of(window_pid_)
    sc = which("systemctl")
    err = "no systemd scope found for this window"
    if scope and sc:
        props = [f"CPUWeight={CPU_WEIGHT.get(priority, '100')}",
                 f"MemoryHigh={ram_cap_mb}M" if ram_cap_mb > 0 else "MemoryHigh=infinity"]
        r = subprocess.run([sc, "--user", "set-property", "--runtime", scope, *props], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return ""
        err = (r.stderr or r.stdout).strip() or f"systemctl failed ({r.returncode})"
        if priority == "Normal" and ram_cap_mb <= 0:
            return ""
    # fallback for the CPU part: raise the nice value of every thread (lowering it again needs root)
    nice = NICE.get(priority, 0)
    if nice <= 0:
        return "" if ram_cap_mb <= 0 else err
    try:
        for t in os.listdir(f"/proc/{window_pid_}/task"):
            try:
                os.setpriority(os.PRIO_PROCESS, int(t), nice)
            except OSError:
                pass
        return "" if ram_cap_mb <= 0 else "CPU priority set; RAM cap not possible: " + err
    except OSError as ex:
        return str(ex)


def open_folder(p: Path) -> None:
    xo = which("xdg-open")
    if xo:
        subprocess.Popen([xo, str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
