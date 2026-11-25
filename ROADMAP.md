# Cellar roadmap

**North star (decided 2026-11-24):** Cellar is the multi-account launcher and Sober companion for Linux - the
missing piece *next to* roblox.com and RoValra, not a replacement for them. Browse and find games on the website
(with RoValra), press Play, and Cellar decides which accounts go and runs them. Cellar is for what a browser
can't do: many isolated Sobers at once, background mode, macros, anti-AFK, freeze, auto-rejoin, an account
switcher and a real settings / Fast Flag editor for Sober. **Benefits outweigh cost:** a feature is never cut or
watered down to look lightweight; efficiency only means no waste. Keep the polished look (themes, cards, toasts,
Ctrl+K); cut what only serves browsing Roblox.

Size: **S** = an evening, **M** = a few days, **L** = a week or more. ⚠ = more automation, so more risk of
Roblox moderation; keep it opt-in with a clear warning. 🔬 = research first (Sober or Roblox may not allow it).

## T. Layout (decided: the Roblox MultiHub layout - see DESIGN.md)

- [x] **S** DESIGN.md: the layout and the UI rules, so the layout stops changing page by page
- [x] **M** MultiHub layout with themes: header numbers, account list always on the left, tool tabs (Launch first),
      log at the bottom; Home / Library / game pages / profile pages / Friends / Servers removed (their useful
      parts are in the Launch tab)
- [x] **M** Launch tab: Game / Server / Private server / Friend; Your games as tiles (recent + the main account's
      favourites); search or paste a link; Quick join + History; saved private servers; friends online to follow;
      a launch button that says what will happen
- [x] **S** Audit Settings / Performance against DESIGN.md: one-line intro (measurements in the FPS cap tooltip),
      memory options that say what they measure, normal-size buttons, the accent hint on its own line, "Join
      address (advanced)" explained, alert options grey out while their switch is off

## Parked (website features: roblox.com + RoValra do these; not Cellar's job)

- Home tab (discover / popular / trending rows), Library tab, game pages, profile pages (built in 1.1, removed
  for the MultiHub layout)
- Game page screenshots and badges; RoValra-style website QOLs (mutual friends, catalog / outfit tools)

## E. Efficiency (no waste - never at the cost of a feature)

Measured 2026-11-23: bare Qt window 93 MB, + WebEngine import 129 MB, full Cellar window 220 MB (off-screen);
the real running app was ~450 MB after hours.
- [x] **S** Load Qt WebEngine only when the browser login opens (-36 MB at start; tested on NVIDIA + Wayland)
- [x] ~~Build tabs on first open~~ - measured: all 11 tabs together are ~22 MB; not worth the rewiring
- [x] **S** Find what grows over hours and cap it (`tools/soak.py`, 2026-11-24): every right-click menu and every
      dialog (game page, Edit account, browser login...) stayed alive until Cellar quit, and the game / avatar picture
      cache never shrank. Before: +75 widgets, +344 Qt objects, ~5.5 MB per soak round; after: flat, and RSS levels
      off once the picture cache is full (400 pictures, ~35 MB). Log view (3000 lines) and graphs (1 hour) were
      already capped
- [ ] **S** Measure the real app after a few hours with this build (it was 277 MB after 7 min on NVIDIA + Wayland,
      ~100 MB of that is file-backed / GL driver); target < 200 MB of our own memory

## 0. Fix first (found while reading the code)

- [x] Browser login / Create account closed Cellar (segfault in Qt WebEngine): the theme's app-wide spin box
      event filter touched WebEngine's own widgets. Replaced by `theme.pad_spin()`

- [x] **S** Watcher sends the same "Client closed" webhook every check while the internet is down (dead clients
      are only removed after `internet_ok()`), in `launcher.watcher_tick`
- [x] **S** Macro `type` step cuts text at `#` (comment stripping runs before the op is parsed)
- [x] **S** `presets_page._place_when_ready` crashes if an account is removed while its preset is launching
- [x] **S** When Sober is not installed, the 2 s header tick runs `flatpak info` on the UI thread every time
      (only success is cached)
- [x] **S** Move up / Move down selected a different account afterwards (the selection was read back by row
      after the list had been reordered); `refresh_accounts(select=ids)` now
- [x] **S** Header said "8 / 6 running": relaunching an account whose client had just died (before the watcher
      cleared it) kept the dead record, and the new client (same tracker id) made it look alive - a later crash
      then relaunched the account twice. One record per account now (Launcher.forget_account)
- [x] **S** Restart (Settings > Size) did not bring Cellar back: the new copy found the old one still quitting
      (background jobs finishing) and handed over to it. The socket now closes when quitting starts, and the
      restarter waits for the old process (max 15 s). Same fix for reopening Cellar right after quitting

## 1. Look and feel

- [x] Theme system: Blossom, Midnight, Mint, Ember, Graphite, Daylight, System (Settings > Appearance)
- [x] New header (stat captions, status pill), card-style sections, monospace log, empty-state hint
- [x] **L** Launcher layout (like Steam's, Cellar's own look): top tabs HOME · LIBRARY · ACCOUNTS · FRIENDS · TOOLS,
      back / forward, bottom status bar, Library page with jump-back-in tile, per-account profile pages
- [x] **S** UI size (Auto / 90-150%, Qt scale factor) - Settings > Appearance > Size
- [x] (replaced by the launcher layout) **L** Sidebar app layout: grouped pages (Play / Manage / Sober), full-width pages with titles, Accounts page
      (list + launch panel), live stats + "Playing as" in the sidebar, log -> Activity page + status line,
      one bundled icon set (Lucide)
- [x] **S** Custom accent colour picker (any theme + your own accent)
- [x] **S** Size setting (scales everything) - see UI size above
- [x] **M** Account list as **cards** (big avatar, status dot, game, CPU/RAM) as an alternative to the table
- [x] **S** Wider Status column / tooltips with the full "In game: …" text; hide the Game column when empty
- [x] **M** In-app toast notifications (bottom-right) for launch finished / failed / kicked, instead of log-only
- [x] **S** Log moved to the Activity page (Copy / Open log file / Clear)
- [x] **S** Activity filter (problems only / one account / search)
- [x] **M** Command palette (Ctrl+K): "launch …", "stop …", "view screen …", "theme …"
- [x] **S** Keyboard shortcuts: Enter = launch, Ctrl+Shift+S = stop all, F2 = edit, Ctrl+1…9 = tabs
- [x] **S** Sober / Roblox version + multi-instance state in the header (free RAM: Performance tab estimate)
- [ ] **M** Translations (Qt linguist): start with Spanish, Portuguese, German, French
- [x] **S** Remember last tab, column widths and sort order

## 2. First run and setup

- [x] **M** First-run wizard: checks Sober / pasta / sway / wayvnc / ydotool, shows the exact install command
      for your distro with a Copy button, imports your Sober account, picks a theme
- [x] **S** "Fix it" buttons in System check (copy command, open docs) instead of plain text
- [x] **S** Check for updates (GitHub releases, opt-in) + "What's new" dialog after updating
- [x] **S** AUR `PKGBUILD` (`packaging/aur`) + a shared `packaging/cellar.desktop`
- [ ] **M** Publish: AUR account, nixpkgs PR, .deb / .rpm via CI; GitHub Releases with notes (needs you)
- [ ] 🔬 **L** Flatpak of Cellar itself (needs host access for unshare/pasta/systemd-run: `flatpak-spawn --host`)

## 3. Accounts

- [x] **M** **Account switcher for your normal Sober**: "Use this account in my Sober" writes its login into the
      main Sober profile (the killer feature for single-instance users and people with 2–3 accounts)
- [x] **S** Pin to top
- [x] **S** Colour tags per account (right-click > Colour tag, Edit / Bulk edit, filter by tag; bar on cards + table)
- [x] **S** Drop cookie files / text / accounts .dat onto the window to import
- [x] **S** Drag and drop to reorder accounts (cards and table, in "Your order"; several at once)
- [x] **S** Robux, Premium, account age, friends / followers / groups: on the profile page
- [x] **M** Encrypted export / import of accounts (password file, same format as accounts.dat)
- [x] **S** Restore from backup dialog (the backups already exist in `backups/`, just no UI)
- [x] **S** Re-login button on "Signed out" accounts that opens the browser login pre-filled
- [x] **S** Bulk edit: background mode, full quality, auto macro, group
- [x] **S** Auto-lock (password mode): after N minutes in the background the window locks (accounts keep
      running; dialogs close, shortcuts off); Ctrl+L / tray > Lock
- [x] **M** Full-body avatar refreshed on the profile page
- [x] **S** Headshot in the screen viewer title (window icon)

## 4. Launching and joining

- [x] **L** **Browser "Play" button opens Cellar**: register as `roblox-player:` / `roblox:` handler; Cellar asks
      which account(s) to join with (or uses a default), then forwards to Sober
- [x] **M** "Bring my alts here": all selected alts join the server your main is in (follow-by-presence, one click)
- [x] **M** Favourite games with thumbnails and player counts (Home)
- [x] **S** Recent servers list (Servers tab > History, with Rejoin)
- [x] **M** Server browser: quick join (emptiest / busy with room for everyone), auto-refresh, game name, Play menu
- [ ] 🔬 **M** Server region / ping estimate (needs the datacenter map)
- [x] **S** Private server list per game (game page > Your private servers)
- [x] **M** Launch queue with progress bar and per-account result (✓ / failed, why) + "retry failed"
- [x] **M** Scheduled launches (start preset X at 18:00, stop at 02:00) - Presets page > Schedule
- [x] **S** Desktop shortcuts per account / preset (`.desktop` files: "Launch ArcticTweaK in ABOVE")
- [x] **M** CLI: `cellar launch <account|preset> [--place ID]`, `cellar stop all`, `cellar list` (talks to the
      running Cellar over its local socket)
- [x] **M** Kick / disconnect detection from Sober's logs (error 267 / 277 / 279 …) → rejoin the same server,
      faster than the presence watcher
- [x] **S** Launch delay based on free RAM (wait while RAM < X GB) instead of a fixed pause

## 5. Background mode and macros

- [x] **M** **Screen wall**: one window with live thumbnails of every background account; click to open
- [x] **S** "macro" marker in the account list's status (live thumbnails: see the screen wall)
- [x] **S** Screenshot button in the viewer (saved to Pictures/Cellar)
- [x] **S** Attach screenshots to Discord alerts (disconnects of background accounts: their screen, before the rejoin)
- [x] **M** Macro editor: syntax highlighting, mistakes underlined live on their line, Run once (test)
- [x] **S** Macro step-by-step run (line highlighted, Next step / F10, waits skipped)
- [x] **M** More steps: `repeat N { }`, `random { }`, `stop after 30m` (nested blocks)
- [ ] ⚠ **L** `ifcolor x y #hex` / `waitcolor` (pixel checks on the account's own screen): react to the game
- [ ] **S** Better recording: mouse paths (optional), trim pauses, edit after recording
- [ ] **M** Global shortcut "stop all macros" (KDE global shortcuts / XDG GlobalShortcuts portal)
- [ ] 🔬 **S** Invisible screen size per account (540p) - macros use 1280x720 coordinates, would need scaling
- [x] **M** Per-account audio: Mute alts, Mute / Unmute, per-account volume (PipeWire pw-dump + wpctl, by cgroup)
- [x] **S** Macro library: import / export macros as files, share with friends

## 6. Performance and resources

- [x] **M** **Freeze / resume** an alt without closing it (`systemctl --user freeze` on its scope: 0 CPU while
      frozen, the game reconnects or kicks depending on how long)
- [x] **S** CPU / RAM per account in the list (usage.py already reads cgroups)
- [x] **M** Usage history graphs (CPU and memory, last hour, hover for values) on the Performance page
- [x] **S** "How many alts fit" estimate from free RAM and the measured cost per alt
- [x] **S** Per-account graphics preset (Edit account > Graphics)
- [ ] 🔬 **S** GPU choice per account on hybrid laptops (`DRI_PRIME`)
- [x] **S** Auto-close alts when RAM gets low (keep the main alive)

## 7. Window layouts

- [x] **M** Layouts on Sway (tested on a real headless sway) and Hyprland (from its docs - needs a tester)
- [x] **S** Saved layouts separate from presets; "All monitors" spreads windows by screen size (tested with a fake
      two-screen setup - needs a real multi-monitor try)
- [ ] 🔬 **M** GNOME (extension needed: no public window-move API)

## 8. Notifications and monitoring

- [x] **S** Desktop notifications (freedesktop) for crash / kick / launch done / login lost
- [ ] **M** Richer Discord webhooks: per-account uptime, screenshots, daily summary
- [x] **M** Session history: which account played what, for how long, time played in the last 7 days (local
      only; sessions from the Roblox log, safe against Cellar restarts re-reading a log)
- [ ] 🔬 **M** Discord bot / remote control from phone (start/stop/screenshot); careful with security

## 9. For every Sober user (single account too)

- [x] **M** **Sober settings editor** with plain-language options for the main Sober profile (config.json)
- [x] **M** **FastFlag editor**: search, allowlist hints, presets (FPS unlock, lighting, textures), import/export
- [x] **S** FPS unlock / cap for the main Sober profile
- [x] **M** Roblox log viewer: normal Sober or any account's profile, "What happened" (events + Roblox's own
      errors; 5,903 of 5,905 "errors" in a measured session were game scripts / engine chatter), search, copy for a
      bug report with cookies removed
- [x] **S** Repair tools: clear shader cache, clear Roblox cache, crash dumps, reset Sober settings
- [ ] **S** Repair: reinstall Roblox files
- [x] **S** Sober and Roblox version shown in the header
- [x] **S** Sober update check (header + log, also every 6 h)
- [x] **M** Join history (place, server, time, account) from the Roblox logs
- [ ] 🔬 **M** Server location on join (needs an IP -> Roblox datacenter map)
- [ ] 🔬 **L** Mods: custom fonts / sounds / cursor via Sober's asset overrides (check what Sober supports)

## 10. Friends and social

- [x] **S** Friend online / started-a-game notifications with Join (Settings > Desktop notifications)
- [ ] **M** Make your own alts friends with each other (bulk friend requests + accept)
- [x] **S** Join a friend with any account straight from the Friends tab's right-click menu

## 11. Code quality (keeps everything above shippable)

- [x] **M** Tests: `layout.compute_rects`, `macros.parse`, `specs`, `util`, crypto round-trips (P and K formats),
      `models.from_dict` with old settings files
- [x] **S** `ruff` + GitHub Actions CI (lint, tests, `nix build`)
- [x] **M** Split `main_window.py` (1627 -> 529 lines): accounts.py, launching.py, live.py, widgets.py mixins
- [x] **S** "Save debug bundle": log + system check + versions, with cookies scrubbed
- [x] **S** Crash handler: uncaught exceptions → log + friendly dialog instead of a silent failure

## Suggested order

1. Section 0 (bugs). 2. First-run wizard + update check. 3. Account switcher for normal Sober + FastFlag/Sober
settings editor (wins single-account users). 4. Browser "Play" opens Cellar. 5. Screen wall + freeze/resume +
per-account CPU/RAM. 6. Kick detection + desktop notifications. 7. Packaging (AUR / nixpkgs) to reach people.
