"""Data model (port of Models.cs). Plain dataclasses that round-trip through JSON."""

import dataclasses
import typing
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------- JSON helpers
def to_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, list):
        return [to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


def _convert(tp: Any, value: Any) -> Any:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if value is None:
        return None
    if origin is typing.Union:                      # Optional[X]
        inner = [a for a in args if a is not type(None)]
        return _convert(inner[0], value) if inner else value
    if origin in (list, List):
        return [_convert(args[0], v) for v in value] if isinstance(value, list) else []
    if origin in (dict, Dict):
        return dict(value) if isinstance(value, dict) else {}
    if dataclasses.is_dataclass(tp):
        return from_dict(tp, value) if isinstance(value, dict) else tp()
    if tp is bool:
        return bool(value)
    if tp is int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    if tp is float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    if tp is str:
        return "" if value is None else str(value)
    return value


def from_dict(cls, data: Dict[str, Any]):
    """Builds cls from a dict, ignoring unknown keys and keeping defaults for missing ones."""
    obj = cls()
    if not isinstance(data, dict):
        return obj
    hints = typing.get_type_hints(cls)
    for f in dataclasses.fields(cls):
        if f.name in data:
            try:
                setattr(obj, f.name, _convert(hints[f.name], data[f.name]))
            except Exception:
                pass
    return obj


def clone(obj):
    return from_dict(type(obj), to_dict(obj))


# ---------------------------------------------------------------- accounts
@dataclass
class Account:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    username: str = ""
    user_id: int = 0
    display_name: str = ""
    cookie: str = ""            # the .ROBLOSECURITY value. Treat like a password!
    password: str = ""          # optional, only stored if typed in
    alias: str = ""
    description: str = ""
    group: str = ""
    saved_place_id: str = ""
    saved_job_id: str = ""
    fps_cap: int = 0            # 0 = use the global FPS cap
    full_quality: bool = False  # your main: skip the global (alt) FPS cap and graphics preset
    background: bool = False    # run on its own invisible screen (background.py) - needs multi-instance
    auto_macro: str = ""        # macro (by name) to start when this account is launched in the background
    game_link: str = ""         # game link / Place ID this account joins by default
    tracker_id: int = 0         # stable "browser tracker id" (also identifies its Sober window)
    last_used: float = 0.0      # unix time
    order: int = 0
    login_lost: bool = False
    pinned: bool = False        # always at the top of the list
    volume: int = -1            # 0-100 %, -1 = default (Settings > Mute alts decides) - audio.py
    gfx_preset: str = ""        # its own graphics preset (gfx.PRESETS key), "" = the global one / full quality
    color: str = ""             # colour tag (theme.TAGS key), "" = none

    @property
    def name(self) -> str:
        return self.alias or self.username or "(unnamed)"


@dataclass
class LiveInfo:
    """Runtime-only info about an account (never saved)."""
    presence_type: int = -1     # -1 unknown, 0 offline, 1 online, 2 in game, 3 studio
    where: str = ""
    cookie_bad: bool = False
    locked: bool = False
    locked_alerted: bool = False


# ---------------------------------------------------------------- settings
@dataclass
class LayoutSettings:
    mode: str = "Auto"          # Auto | Grid | FixedSize
    rows: int = 0
    cols: int = 0
    monitor: str = ""           # KWin output name ("DP-3"), "" = the first one
    use_work_area: bool = True  # keep clear of panels
    gap: int = 0
    margin: int = 0
    scale: int = 100            # percent of each grid cell a window fills
    fixed_w: int = 800
    fixed_h: int = 600
    stretch_last: bool = True
    borderless: bool = False
    always_on_top: bool = False
    skip_taskbar: bool = False
    auto_capture: bool = False  # arrange new Sober windows automatically
    auto_capture_delay_ms: int = 2500
    sort_mode: str = "Manual"   # Manual | Name | Launch
    min_w: int = 320
    min_h: int = 240


@dataclass
class GfxSettings:
    # Defaults = the "Lowest" preset (gfx.apply_preset): this applies to alts; mark your main "Full quality".
    preset: str = "Lowest"      # Default | Light | LowCpu | Lowest | Custom
    quality: int = 1
    texture: int = 0
    msaa: int = 1
    no_grass: bool = True
    pause_voxelizer: bool = True
    gray_sky: bool = True
    low_csg: bool = True
    write_unlisted: bool = False


@dataclass
class SoberSettings:
    """Options written into every per-account Sober profile's config.json."""
    use_opengl: bool = False
    graphics_optimization_mode: str = "balanced"    # quality | balanced | performance
    enable_gamemode: bool = True
    close_on_leave: bool = False
    discord_rpc_enabled: bool = False
    server_location_indicator_enabled: bool = False
    enable_hidpi: bool = False
    initialized: bool = False   # copied from the main Sober config once


@dataclass
class GameEntry:
    place_id: int = 0
    name: str = ""
    ts: float = 0.0


@dataclass
class PrivateServer:
    """A saved private server link (Launch > Private server > Save...)."""
    place_id: int = 0
    name: str = ""
    link: str = ""


@dataclass
class JoinRecord:
    """One session: an account in one server (from its Roblox log) - History (sessions.py)."""
    ts: float = 0.0
    account_id: str = ""
    account: str = ""
    place_id: int = 0
    job_id: str = ""
    end: float = 0.0            # when it left that server; 0 = still there (or unknown: from before 1.1)


@dataclass
class LaunchSpec:
    kind: str = "Game"          # Game | Job | Private | Follow
    place_id: int = 0
    job_id: str = ""
    link_code: str = ""
    share_code: str = ""        # new-style share link, resolved per account at launch
    follow_user_id: int = 0
    follow_name: str = ""

    def copy(self) -> "LaunchSpec":
        return clone(self)

    def describe(self) -> str:
        if self.kind == "Job":
            return f"place {self.place_id} / server {self.job_id}"
        if self.kind == "Private" and self.place_id <= 0 and self.share_code:
            return "private server (share link)"
        if self.kind == "Private":
            return f"private server of place {self.place_id}"
        if self.kind == "Follow":
            return "following " + (self.follow_name or str(self.follow_user_id))
        return f"place {self.place_id}"


@dataclass
class PresetEntry:
    account_id: str = ""
    username: str = ""
    spec: Optional[LaunchSpec] = None
    grid_index: int = -1
    include: bool = True
    has_rect: bool = False
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    borderless: bool = False
    minimized: bool = False


@dataclass
class NamedLayout:
    """A window layout kept under a name (Windows tab > Saved layouts) - apart from presets."""
    name: str = ""
    layout: LayoutSettings = field(default_factory=LayoutSettings)


@dataclass
class PresetSettings:
    gfx: GfxSettings = field(default_factory=GfxSettings)
    sober: SoberSettings = field(default_factory=SoberSettings)
    custom_flags: str = ""
    fps_cap: int = 0
    priority: str = "Normal"
    ram_cap_mb: int = 0
    layout: LayoutSettings = field(default_factory=LayoutSettings)
    launch_delay_sec: int = 8
    auto_close_last: bool = True
    max_instances: int = 0
    use_saved_per_account: bool = True
    auto_relaunch: bool = False
    watcher_sec: int = 60
    watcher_use_presence: bool = False
    anti_afk: bool = False
    anti_afk_min: int = 12
    anti_afk_action: str = "Zoom"
    last_mode: str = "Game"
    last_place_id: str = ""
    last_job_id: str = ""
    last_private: str = ""
    last_follow: str = ""

    _KEYS = ("custom_flags", "fps_cap", "priority", "ram_cap_mb", "launch_delay_sec", "auto_close_last",
             "max_instances", "use_saved_per_account", "auto_relaunch", "watcher_sec", "watcher_use_presence",
             "anti_afk", "anti_afk_min", "anti_afk_action", "last_mode", "last_place_id", "last_job_id",
             "last_private", "last_follow")

    @classmethod
    def capture(cls, s: "AppSettings") -> "PresetSettings":
        p = cls()
        p.gfx = clone(s.gfx)
        p.sober = clone(s.sober)
        p.layout = clone(s.layout)
        for k in cls._KEYS:
            setattr(p, k, getattr(s, k))
        return p

    def apply_to(self, s: "AppSettings") -> None:
        s.gfx = clone(self.gfx)
        s.sober = clone(self.sober)
        s.layout = clone(self.layout)
        for k in self._KEYS:
            setattr(s, k, getattr(self, k))


@dataclass
class Preset:
    name: str = ""
    saved: float = 0.0
    entries: List[PresetEntry] = field(default_factory=list)
    settings: PresetSettings = field(default_factory=PresetSettings)


@dataclass
class Schedule:
    """Run a preset at a time of day (and optionally stop its accounts later) - Presets tab > Schedule."""
    preset: str = ""
    start: str = "18:00"            # HH:MM
    stop: str = ""                  # HH:MM, "" = leave them running
    days: List[int] = field(default_factory=lambda: list(range(7)))     # 0 = Monday
    enabled: bool = True
    last_start: str = ""            # date it last fired (YYYY-MM-DD), so it fires once a day
    last_stop: str = ""


@dataclass
class Macro:
    name: str = ""
    text: str = ""              # macros.py step language
    loop: bool = True


@dataclass
class AppSettings:
    first_run_done: bool = False
    theme: str = "blossom"         # theme.THEMES key (Settings > Appearance)
    accent: str = ""                # your own accent colour (#rrggbb) on Cellar's themes, "" = the theme's own
    ui_scale: str = "auto"          # auto | 90 | 100 | 115 | 130 | 150 (% - Qt scale factor, applied at start)
    auto_scale: float = 1.0         # what "auto" uses: picked from the screen size at the previous start
    home_account: str = ""          # Settings > Main account: whose friends / favourites the launch panel shows ("" = auto)
    check_updates: bool = True      # ask GitHub for a newer release, at most once a day
    last_update_check: float = 0.0
    last_seen_version: str = ""     # shows "What's new" once after an update
    multi_instance: bool = True     # True = isolated Sober profile per account (pasta); False = one Sober at a time
    launch_delay_sec: int = 8
    auto_close_last: bool = True
    max_instances: int = 0
    refresh_cookie_on_launch: bool = False
    show_presence: bool = True
    presence_sec: int = 30
    custom_flags: str = ""
    gfx: GfxSettings = field(default_factory=GfxSettings)
    sober: SoberSettings = field(default_factory=SoberSettings)
    priority: str = "Normal"        # Normal | BelowNormal | Idle
    ram_cap_mb: int = 0             # MemoryHigh per Sober window, 0 = off
    # Alt defaults, measured 2026-11-23 on an i5-12600K: an alt in a game takes 0.82 CPU cores at
    # 240 FPS / default graphics and 0.17 at 30 FPS / "Lowest" - RAM (~1 GB each) becomes the limit.
    fps_cap: int = 30               # 0 = leave Roblox's own setting alone; accounts marked full_quality skip it
    settings_version: int = 4       # 2 = alt defaults, 3 = MultiHub layout, 4 = sessions (see store.load_settings)
    auto_relaunch: bool = False
    watcher_sec: int = 60
    watcher_use_presence: bool = False
    crash_breaker: bool = True
    crash_breaker_max: int = 3
    crash_breaker_window_min: int = 3
    crash_breaker_cooldown_min: int = 10
    anti_afk: bool = False
    anti_afk_min: int = 12
    anti_afk_action: str = "Zoom"   # Zoom | Space | Nudge
    place_launcher_url: str = "https://www.roblox.com/Game/PlaceLauncher.ashx"
    last_mode: str = "Game"
    last_place_id: str = ""
    last_job_id: str = ""
    last_private: str = ""
    last_follow: str = ""
    use_saved_per_account: bool = True
    groups: List[str] = field(default_factory=list)
    recent: List[GameEntry] = field(default_factory=list)
    history: List[JoinRecord] = field(default_factory=list)     # sessions, newest first (sessions.KEEP)
    last_quit: float = 0.0          # when Cellar last quit (sessions of clients that closed meanwhile end there)
    lock_after_min: int = 0         # password mode: lock the window after this long in the background (0 = never)
    private_servers: List[PrivateServer] = field(default_factory=list)
    layout: LayoutSettings = field(default_factory=LayoutSettings)
    saved_layouts: List[NamedLayout] = field(default_factory=list)
    presets: List[Preset] = field(default_factory=list)
    macros: List[Macro] = field(default_factory=lambda: [Macro(
        name="Stay active (example)", loop=True,
        text="# Jumps and turns the camera now and then, so Roblox doesn't kick for being idle.\n"
             "tap space\nwait 500\nkey left 300\nwait 20000-40000\n")])
    startup_preset: str = ""
    schedules: List[Schedule] = field(default_factory=list)
    preset_exact_servers: bool = False
    check_logins_at_startup: bool = True
    start_minimized_to_tray: bool = False
    close_to_tray: bool = True
    ui_tab: int = 0                 # unused since the tools layout (Cellar always opens on Accounts); kept for old files
    ui_sort: str = "Manual"
    accounts_view: str = "table"    # the account list: table | cards
    ui_header: str = ""             # QHeaderView.saveState(), base64
    win_w: int = 1360
    win_h: int = 820
    split: List[int] = field(default_factory=list)
    split_v: List[int] = field(default_factory=list)    # main window: tools / log heights
    mute_alts: bool = False         # accounts not marked Full quality play without sound (unless given a volume)
    min_free_ram_mb: int = 0        # before each launch, wait (up to 3 min) while less RAM than this is free
    low_ram_close_mb: int = 0       # watcher: free RAM below this -> close the newest alt (not "full quality")
    # Freeze: wake the alt for a moment every few seconds so it keeps answering the game server (a client that
    # stays frozen is dropped as "lost connection"). Off = frozen solid (0% CPU, but kicked after a while).
    freeze_keep_connected: bool = True
    freeze_wake_every_sec: int = 10
    freeze_wake_ms: int = 1500
    rejoin_on_kick: bool = False    # kicked / disconnected (seen in the Roblox log) -> relaunch right away
    notify: bool = True             # desktop notifications (through the tray icon)
    notify_kick: bool = True
    notify_crash: bool = True
    notify_launch_done: bool = False
    notify_login_lost: bool = True
    notify_friends: bool = False    # a friend of the main account comes online / starts a game (checked every minute)
    webhook: bool = False
    webhook_url: str = ""
    webhook_crash: bool = True
    webhook_relaunch: bool = True
    webhook_batch: bool = True
    webhook_locked: bool = True
    webhook_screenshot: bool = True     # background accounts: a picture of their screen with "Disconnected"
    keep_profiles_updated: bool = True   # refresh each profile's Roblox files from your main Sober when it updates


@dataclass
class Instance:
    """A Sober client this app started (runtime only)."""
    account: Account = None
    tracker: int = 0
    launch_pid: int = 0         # the pasta / flatpak process we spawned
    unit: str = ""              # systemd scope we started it in
    pid: int = 0                # Sober's window process ("Main"), 0 until found
    started: float = 0.0
    spec: LaunchSpec = None
    isolated: bool = True
    user_closed: bool = False
    strikes: int = 0
    reported: bool = False      # "Client closed" webhook already sent (the watcher may see it dead many times)
    offline_logged: bool = False
    frozen: bool = False        # paused with the cgroup freezer (0% CPU) - see sober.freeze
    place_id: int = 0           # the server it is in now, from the Roblox log (robloxlog)
    job_id: str = ""
    screen: Any = None          # background.Screen when it runs on an invisible screen
    macro: Any = None           # macros.Runner while a macro runs on it
