# Cellar — notes for Claude

Multi-account Roblox launcher for Linux, built on **Sober** (Flatpak `org.vinegarhq.Sober`). Python 3.10+ / PySide6
(Qt 6) desktop app, ~15k lines, unit tests in `tests/`. Author: ArcticTweaK. GPL-3.0. Started as a port of the Windows app
"Roblox MultiHub" (C#) — many modules say "port of X.cs"; old name `roblox-multihub` still appears for migration.

The developer's machine: **NixOS, KDE Plasma 6, Wayland**.

## Run / verify

- Checks before calling anything done: `python3 -m py_compile cellar/*.py cellar/ui/*.py`,
  `nix develop -c ruff check cellar tests tools`, `nix develop -c python -m unittest discover -s tests -t .`
- **Memory growth**: `nix develop -c python tools/soak.py [rounds]` fast-forwards hours of use off-screen (fake
  accounts, no network: ticks, log lines, page switches, real menus + dialogs closed by a timer, Home shelves, theme
  switches) and prints RSS / widget / QObject counts per round. Widgets and QObjects must stay flat; RSS may only
  climb until the capped caches fill (game pictures: 400). Run it after UI changes that create widgets.
- **Look at UI changes** without disturbing the user's running Cellar: `nix develop -c python tools/screenshot.py
  OUT_DIR [themes] [tabs]` renders the main window off-screen with fake accounts and fake recent games, no network
  (tabs: 0 Launch, 1 Presets, 2 Macros, 3 Anti-AFK, 4 Windows, 5 My Sober, 6 Performance, 7 Settings, 8 Help;
  EMPTY=1 = no accounts, TABLE=1 = table view), then Read the PNGs.
- README picture: `nix develop -c python tools/readme_screenshot.py` rewrites docs/screenshot.png (made-up account
  names: ArcticTweaK + altaccount1..5, real game icons from ~/.cache/cellar, names from Roblox's public API).
- Run from source: `nix develop -c python -m cellar` (devShell has PySide6, requests, cryptography, secretstorage,
  pasta, sway, wayvnc). Or `nix build` / `nix run .` (`result` symlink in repo is a nix build output, gitignored).
- Non-Nix: `./install.sh` (venv in `~/.local/share/cellar-app`, symlink `~/.local/bin/cellar`).
- Only one copy runs at a time (QLocalSocket `cellar-<uid>`); a second start just raises the first window (or, with
  a roblox link argument, sends `open <uri>`). Quit the running Cellar before testing a new build.
- Installed on the dev machine as a Nix profile package: `git add -A && nix profile upgrade Cellar` (new files must
  be git-added or the flake build leaves them out).
- Qt WebEngine is imported lazily inside browser_login (AA_ShareOpenGLContexts is still set in app.py before the
  QApplication) - don't import it at module level anywhere (+36 MB at start).
- **Never** use an app-wide Python event filter (`app.installEventFilter`): it segfaulted Qt WebEngine (browser
  login) on NVIDIA + Wayland. Touch widgets where they are created instead (e.g. `theme.pad_spin`).
- Version lives in exactly one place: `cellar/__init__.py` `__version__` (pyproject + nix read it).

## Layout

```
cellar/
  app.py          entry (main): single-instance socket, old-name migration, unlock accounts, MainWindow
  paths.py        XDG paths (config ~/.config/cellar, data ~/.local/share/cellar, cache ~/.cache/cellar)
  log.py          log.write() -> log.txt + UI listeners; collapses repeats as "(2x)"; log.error() adds traceback
  util.py         cookie regex, place-id / share-code / private-link parsing, ago(), natural_key()
  models.py       ALL dataclasses: Account, LiveInfo, AppSettings (+Gfx/Sober/Layout), LaunchSpec, Preset*, Macro,
                  Instance. Generic to_dict/from_dict JSON round-trip (unknown keys ignored, missing -> default)
  store.py        global state: store.settings, store.accounts, store.live(a); load/save settings (plain JSON)
                  and accounts.dat (encrypted); backups (last 10); settings migrations (settings_version)
  crypto.py       accounts.dat formats: 'P' password (Windows-app compatible PBKDF2+AES-CBC+HMAC),
                  'K' keyring key (Secret Service / KWallet via busctl / 0600 key file) + AES-GCM; 'D' = DPAPI (unsupported)
  api.py          Roblox web API, blocking requests (auth ticket, cookie rotate, presence, friends, servers,
                  avatars, game search, share-link resolve, details). CSRF handshake in _post_csrf
  specs.py        LaunchForm (snapshot of Launch page) -> LaunchSpec; saved per-account game -> LaunchSpec
  sober.py        THE CORE: per-account Sober profile (reflink clone of ~/.var/app/org.vinegarhq.Sober),
                  profile config.json + FPS cap in GlobalBasicSettings xml, roblox-player: URI, sandbox command
                  (systemd-run scope -> env -> sh NETNS_SCRIPT -> unshare user/net/ipc/time -> pasta attached
                  after -> flatpak run sober), /proc scanning, stop, CPU weight / MemoryHigh limits
  launcher.py     Launcher: instances list, launch() (ticket -> profile -> optional background screen -> spawn ->
                  wait ≤90 s for window pid), stop, adopt_running after restart, watcher (auto-relaunch,
                  presence check, crash breaker), macros start/stop
  background.py   "Background mode": headless sway (1280x720) + wayvnc on a unix socket per account, run as
                  systemd user units; minimal RFB 3.8 VNC client (raw encoding) for frames + key/pointer input
  macros.py       macro text language parser + Runner thread (sends over VNC); from_recording()
  antiafk.py      for normal (non-background) windows: focus via KWin, key via ydotool, restore focus
  wm.py           window control on Hyprland (hyprctl) and Sway (swaymsg) with KWin's interface; wm.pick() chooses
                  (MainWindow.kwin holds whichever backend - the name is historical). Sway: measured border/order
                  quirks are in the comments; Hyprland is written from its docs (not tested on a real Hyprland yet)
  kwin.py         KDE window control: writes a JS file, loads it into KWin over D-Bus, script calls back into
                  our exported D-Bus object (service io.github.ArcticTweaK.Cellar) with JSON results
  layout.py       pure grid math for arranging windows
  gfx.py          graphics Fast Flags presets + Roblox allowlist filtering
  usage.py        CPU/RAM of all clients from cgroup v2 (header stats)
  webhook.py      Discord webhook posts (async thread)
  crash.py        sys/threading excepthook -> log + one friendly dialog; faulthandler -> crash.txt (reported next start
                  as crash-last.txt); scrub() removes cookies from anything copied into a bug report
  requirements.py system checks (Sober, pasta, sway/wayvnc, ydotool, KWin) + distro install commands (setup + System check)
  updates.py      GitHub releases check (once a day, opt-out), release notes for "What's new", how_to_update()
  audio.py        per-account sound: pw-dump streams -> pid (pipewire.sec.pid) -> cgroup = the instance; wpctl
                  set-mute / set-volume. LiveMixin.audio_tick every 5 s; Account.volume (-1 = Mute alts decides)
  schedule.py     scheduled presets: due() fires starts / stops once a day within a 15 min grace (overnight stops)
  sessions.py     session history on settings.history (JoinRecord ts..end): start / end / close_missing / totals;
                  times come from the Roblox log lines (robloxlog Event.ts) so re-read logs add nothing
  games.py        "Your games" data: recent places -> games (from_places, one per universe), the main account's
                  favourites, details (fill), place->universe (disk cache), game icons in ~/.cache/cellar (blocking)
  playlink.py     roblox-player: / roblox: links from the website -> LaunchSpec; xdg-mime handler on/off; forward to Sober
  cli.py          `cellar list|launch|preset|stop|show` -> "cmd <json>" over the single-instance socket (plain AF_UNIX
                  client, path <tempdir>/cellar-<uid>); MainWindow.run_command answers (reply ends with \0);
                  add_shortcut() writes app-menu .desktop entries
  robloxlog.py    tails each client's Roblox log (appData/logs): joined / teleport / left / disconnected (+ reason);
                  parse_line / read_log / log_files for the Roblox logs window (ui/log_viewer.py; NOISE channels)
  theme.py        colour themes: Theme tokens -> QPalette (Fusion) + one app style sheet; apply(key) at any time;
                  c()/qc()/span() give the active theme's colours; mono_font(); 'system' = desktop's own style;
                  TAGS / tag_qc() / tag_icon() = account colour tags (Account.color), dark + light shade each
  ui/
    common.py     ui(fn) / bg(fn, *args, done=, err=) threading glue; widget helpers btn/chk/spin/combo/row/hint/group; ask/info/warn;
                  Dialog (base of every dialog, frees itself after exec) + popup(menu, pos) for one-off menus
    main_window.py  MainWindow = AccountsMixin + LaunchMixin + LiveMixin + QMainWindow: __init__ (header, account
                  list, tool tabs, log, shortcuts, tray, timers), show_page(), theme switch, startup(), quit
    accounts.py   AccountsMixin: account list (refresh / sort / selection), right-click menu, add / import / export /
                  edit / remove accounts, account switcher, login check, avatars, main_account()
    launching.py  LaunchMixin: launch sequences (run_sequence on a worker), stop, Bring-here, website Play links,
                  run_command (CLI), join history / recent games
    live.py       LiveMixin: timers - status + usage, presence, watcher, Roblox-log tick, notifications, screen viewer
                  / wall, anti-AFK, update check / What's new / versions
    widgets.py    StatBlock (header numbers), AccountTable + AccountCards (same proxy model AND the same selection
                  model - selected_accounts() counts any selected cell; drag to reorder), Toast, graphs, eyebrow()
    palette.py    Ctrl+K command palette: commands(mw) builds the list each time, score() = word-prefix match
    accounts_model.py  QAbstractTableModel + filter proxy for the account list (status column from LiveInfo + running set)
    dialogs.py    Text/Paste/Password dialogs, EditAccountDialog, BulkEditDialog, GamePicker (search by name),
                  ServerTable/ServerPicker (+ Quick join: emptiest / busy with room for `need` accounts)
    launch_pages.py  LaunchPage = the Launch tab: mode tabs Game / Server / Private server / Friend (rb_game /
                  rb_job / rb_private / rb_follow are checkable buttons) over a QStackedWidget; GameStrip = "Your
                  games" tile grid (painted by _TileDelegate; recent + main account's favourites; search field takes
                  words or a link); the chosen game is set_place() / place_text(); the launch bar button text says
                  what happens (update_launch_text). LaunchQueue, HistoryDialog, play_menu() = the shared "Play
                  with..." menu (selected / main / groups / normal Sober)
    windows_page.py (KWin grid + preview), presets_page.py, macros_page.py,
    settings_pages.py (PerfPage, AutomationSettings = watcher + anti-AFK, SettingsPage via _Bound binding helper,
                  HelpPage HTML),
    screen_viewer.py (live VNC view of a background account, input, macro recording),
    browser_login.py (QtWebEngine off-the-record login / sign-up; grabs .ROBLOSECURITY cookie)
    setup_wizard.py  first-run SetupWizard (theme, system checks with Copy buttons, add accounts) + SystemCheckDialog
    my_sober_page.py "My Sober" tab: the user's NORMAL Sober - config.json options, FPS cap, Fast Flag table
                  (allowlist column), repair (clear caches / crash dumps, reset config)
```

Layout (main_window) = the Roblox MultiHub layout, fixed by DESIGN.md (read it before UI work; decided
2026-11-24 after a game-launcher and a section layout were tried and dropped): a header (`topbar`: brand,
`StatBlock` running / CPU / memory, update button, multi-instance pill `st_multi`); `self.vsplit` = top part +
the log (`logbox`: filter / search / Copy / Open / Clear over `logview`); top part `self.hsplit` = the account list
(`self.accounts_page`, always on screen; Add / Edit / Remove / Details / Launch / Stop / Stop all) + `self.tabs`
(QTabWidget of `tab_pages`: Launch, Presets, Macros, Anti-AFK & rejoin, Windows, My Sober, Performance, Settings,
Help; Ctrl+1..9). Cellar opens on Launch. `show_page(page)` opens the tab a page is on; check "is this page
showing" with `page.isVisible()`. `goto_items` = what Ctrl+K can open. Tab labels need `&&` for "&". Icons:
bundled Lucide SVGs (cellar/data/icons) via `theme.icon(name, token)`; `btn(icon=...)` only takes those names.
UI size = QT_SCALE_FACTOR set in app.py before the QApplication (setting `ui_scale`, "auto" uses `auto_scale`
measured at the previous start). Cellar sits next to roblox.com + RoValra: no website-browsing pages.

## Key mechanisms (know these before changing launch code)

- **Account ↔ process mapping = `tracker_id`** (browsertrackerid). Random 12-digit number stored on the Account,
  put in the `roblox-player:` URI; it shows up on Sober's `Main` process cmdline. `sober.window_pid(tracker)`,
  `tracker_of_pid()`, `all_sober_trackers()` scan `/proc`. KWin windows are matched to accounts via `w.pid` → tracker.
- **Multi-instance isolation** (`settings.multi_instance`): per account own `HOME` (`profiles/<account.id>`), own
  netns via unshare + pasta (pasta must attach *after*, never launch Sober itself — see sober.py docstring: PID
  namespace breaks portals → 120 s connect wait / error 279), time+ipc ns, private `XDG_RUNTIME_DIR`
  (`$XDG_RUNTIME_DIR/cellar-<id[:12]>`) with symlinks to real wayland/pipewire/bus sockets.
  systemd scope `cellar-<id[:12]>-<ts>.scope` per client. Without multi-instance only one Sober can run.
- **Profiles**: cloned from the main Sober profile with `cp --reflink=auto`; `_PRIVATE` paths (cookies, logs,
  storage) are deleted from the clone. Roblox files refreshed from main when main's app_version is newer.
  Before each launch `write_profile_settings` rewrites config.json (fflags, renderer…) and FramerateCap.
- **Alts vs main**: global `fps_cap` + gfx preset are *alt* settings; `Account.full_quality` skips them.
- **Background mode** (`Account.background`, needs multi-instance): sway+wayvnc units named
  `cellar-<id[:12]>-screen-<ts>.service` / `-vnc-`; Sober gets `WAYLAND_DISPLAY=wayland-cellar` (symlink in its
  runtime dir). `Instance.screen` holds the `background.Screen`; macros and background anti-AFK talk VNC to `screen.vnc`.
- **Restart survival**: `Launcher.adopt_running()` re-attaches running clients by tracker at startup;
  `_running_screen()` finds their screens. Cellar can quit leaving clients running.
- **Watcher** (main_window timer → `Launcher.watcher_tick` on a worker): dead = not `user_closed` and not alive;
  relaunch with the old spec, crash breaker per account. `Launcher.log_tick` (every 4 s) reads the Roblox logs:
  sets `Instance.place_id/job_id`, and on a disconnect notifies + (setting `rejoin_on_kick`) rejoins.
  `Launcher.notify(kind, inst, text)` is set by the UI → `MainWindow.desktop_notify`: an in-app `toast()` while the
  window is active, otherwise tray message / notify-send. `mw.toast(text, kind, action=(label, fn))` for any message.
- **Freeze**: `sober.freeze(pid)` freezes the client's *Flatpak* scope (Sober's processes are not in Cellar's own
  `cellar-*.scope`; that one only holds the netns/pasta helper). `Instance.frozen`; watcher/anti-AFK skip frozen. A client frozen solid gets dropped by the game server, so
  `Launcher._pulse_loop` thaws frozen clients for `freeze_wake_ms` every `freeze_wake_every_sec` (setting
  `freeze_keep_connected`). Stop / quit thaw first (a frozen process can't handle SIGTERM).
- **Normal Sober** (not a profile): `sober.main_app()`. Account switcher writes `data/sober/cookies` (one Cookie
  header line) via `set_main_cookie` (first switch keeps `cookies.before-cellar`); config via `write_main_config`
  (keeps Sober's `//` header, first save keeps `config.json.before-cellar`). Refuse while `main_sober_running()`.

## Conventions — follow these

- **Threading**: backend modules (api, sober, launcher, background, specs.resolve_*) block. From the UI call them
  with `bg(fn, *args, done=..., err=...)`; `done` runs on the UI thread. From worker threads touch Qt only via
  `ui(lambda: ...)`. `log.write` / `mw.log` are thread-safe. Exceptions: kwin.py and antiafk.py run on the UI
  thread (they spin a local QEventLoop).
- **Menus and dialogs free themselves** (else each one stays a child of its parent until Cellar quits - measured):
  one-off menus are a plain `QMenu(parent)` shown with `common.popup(m, pos)` (exec, then deleteLater); dialogs
  subclass `common.Dialog` (exec() frees it afterwards; reading `d.x` right after exec() is fine). Never subclass
  QMenu (exec() on a Python QMenu subclass segfaults in PySide 6.12) and don't use WA_DeleteOnClose / aboutToHide
  for this (a dialog popping up over an open menu would free it inside a nested loop). Non-modal windows
  (ScreenViewer / ScreenWall) call deleteLater() at the end of done(); look them up with `shiboken6.isValid`.
- **Logging style**: per-account messages are `f"[{a.name}] ..."` (`who` prefix in launcher). Plain, friendly
  English sentences that tell the user what to do next. No jargon in user-facing text; the same tone in README/HELP.
- **Adding a setting**: add a field with a default to `AppSettings` (or Gfx/Sober/Layout settings) in models.py —
  JSON persistence is automatic. Bind it in the UI with `self.bind(widget, S, "attr", after)` (settings_pages
  `_Bound`). If presets should capture it, add it to `PresetSettings` fields **and** `_KEYS`. For changed
  defaults on existing installs, bump `settings_version` and migrate in `store.load_settings`.
- **Adding an account field**: add to `Account` (saved encrypted automatically); add to EditAccountDialog
  (and BulkEditDialog if it makes sense). Map it in `store.accounts_from_json` only if the Windows format has it.
- **Never change**: `crypto._AAD` (breaks every existing accounts.dat), the 'P' format (Windows compat),
  the `OLD_*` / `rmh-` compatibility names, `sober.OWN_COMMS` safety list (only those processes are ever signalled).
- **Saving**: `store.save_accounts()` / `store.save_settings()` are cheap and atomic; call after mutations.
  `store.loaded` guards against overwriting an unread accounts file.
- **Colours / styling**: never hard-code colours. Use `theme.c("good"|"warn"|"bad"|"accent"|"muted"|...)`,
  `theme.span(token, html)` for rich text, `theme.qc()` for QPainter. Style via the style sheet in theme.py
  (`_BASE` for every theme incl. System, `_FULL` for Cellar's own themes) using objectNames (`header`, `pill`,
  `eyebrow`, `stat_value`, `log`...) and properties (`primary` on buttons via `btn(primary=True)`; pill `state`
  + `theme.repolish(w)`). Things that cache colours must refresh in `MainWindow.apply_theme`. Style-sheet
  padding does not reach a spin box's text; theme.py's `_SpinPadding` event filter handles that.
- Roadmap / feature checklist: ROADMAP.md (tick items off when done). UI rules and the fixed layout: DESIGN.md.
- When a feature is user-visible, also update the **HELP** HTML in `ui/settings_pages.py` and **README.md**.
- Code comments explain *why* (measured numbers, Sober/Wayland quirks); keep that style, keep lines ≤ ~120 chars.
- New module inside `cellar/` or `cellar/ui/` needs no packaging change; a new sub-package must be added to
  `pyproject.toml` `[tool.setuptools] packages`. New data files: `cellar/data/` + package-data glob.
- New external tools: resolve with `sober.which()` (has NixOS fallbacks), list in install.sh `need`,
  `nix/package.nix` makeWrapperArgs PATH, the System check dialog, and README's package table.

## Gotchas

- Wayland: no app may inject input into or move another app's window. Hence compositor IPC for layout (KWin
  scripts, hyprctl, swaymsg) and ydotool / background-mode VNC (input). Window features need KDE Plasma, Hyprland
  or Sway; everything else works anywhere.
- `api` uses a thread-local `requests.Session`; Roblox POSTs need the CSRF retry (`_post_csrf`) and an empty JSON body.
- URI encoding must be uppercase percent-escapes (`sober._urlencode`) or Sober joins slowly via its home screen.
- Sober's `enable_gamemode` is forced off in isolated profiles on purpose.
- Users' accounts.dat / cookies are credentials: never log, print or send them anywhere.
