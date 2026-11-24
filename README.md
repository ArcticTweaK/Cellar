<div align="center">

<img src="data/cellar.svg" width="96" alt="">

# Cellar

**Run many Roblox accounts at once on Linux, each on its own invisible screen if you want.**

Made by ArcticTweaK · free and open source (GPL-3.0) · runs on [Sober](https://sober.vinegarhq.org)

</div>

---

Cellar is an account manager and multi-instance launcher for Roblox on Linux. Add your accounts once, launch as
many as you want at the same time, and let them farm in the background while you keep using your PC.

## What it does

- **Feels like a game launcher.** Big HOME · LIBRARY · ACCOUNTS · FRIENDS tabs, back / forward, a status bar,
  and a size setting so text and buttons are easy to read (Settings > Appearance > Size).
- **Library and profiles.** Your games in one place (recent, favourites, private servers) with a "jump back in"
  tile, and a profile page for every account: avatar, Robux, Premium, friends, groups, badges and what it played.
- **Home.** Everything you'd open the Roblox website for: search games, continue playing, see which friends are
  online and join them, your favourites, and Roblox's popular and trending lists. Every game has a page with
  **Play** - pick which account plays, or play in your normal Sober - and your saved private servers. Quick join
  picks the emptiest server (or a busy one with room for all your accounts), and Cellar can tell you when a
  friend starts playing, with a Join button.
- **Many accounts at once.** Sober normally allows one copy per PC. Cellar gives every account its own isolated
  Sober, and your normal Sober keeps working next to them.
- **Background mode.** An account can run on its own invisible screen with its own mouse and keyboard. Nothing
  shows on your desktop and nothing steals your focus. Open **View screen** to watch it or take over.
- **Macros per account.** Plain text or recorded. One account spams F on a berry bush while another does
  something else, and your own mouse and keyboard stay yours.
- **Cheap alts.** Alts default to 30 FPS and the lowest graphics: about 0.17 CPU cores and 1 GB RAM each. Your
  main can stay on full quality. The header shows what all your accounts use together, the list what each one
  uses. Right-click > **Freeze** pauses an alt without closing it; it wakes for a moment every few seconds so it stays
  in the server.
- **Screen wall.** Live pictures of every background account in one window; click one to take over.
- **Kicks noticed in seconds.** Cellar reads each account's Roblox log: a kick or lost connection shows a desktop
  notification and can rejoin right away (the same server after a lost connection).
- **Joining.** Join by game, private server link, server browser, or follow a friend from the Friends tab.
  Right-click an account > **Bring accounts to its server** sends your alts into the exact server it is in.
- **The website's Play button.** Turn it on in Settings and pressing Play on roblox.com asks which of your
  accounts should join that game, server or private server - or sends it on to your normal Sober.
- **My Sober.** For your normal Sober too, even with one account: its settings in plain language, FPS cap,
  a Fast Flags editor that shows which flags Roblox really uses, and cleanup of caches and crash dumps.
- **Account switcher.** Right-click an account > **Use in my normal Sober** logs your normal Sober into it.
  The account it had is saved first, so you can always switch back.
- **Themes.** Blossom (pink), Midnight, Mint, Ember, Graphite, Daylight, or your desktop's own look
  (Settings > Appearance). It switches right away.
- **Moving PCs.** Export your accounts to a password-protected file and import them on the new PC. Every server
  your accounts joined is kept in a history you can rejoin from.
- **Easy start.** A short setup on first start checks your system and shows the exact install command for
  anything missing. Cellar tells you when a new version is out (once a day from GitHub; can be turned off).
- **The rest:** window layouts (KDE Plasma, Hyprland, Sway), anti-AFK, presets, per-account FPS/graphics, a RAM limit per alt,
  auto-relaunch when a window crashes or leaves the game, Discord webhooks, and encrypted accounts (your
  keyring or a password). If something goes wrong, Settings > System check > **Copy report** gives you a
  bug report with your cookies removed.

## Install

You need **Sober** and a few common packages. Copy the line for your distro:

| Distro | Command |
|---|---|
| Arch, CachyOS, EndeavourOS, Manjaro | `sudo pacman -S --needed flatpak passt sway wayvnc python libxkbfile xcb-util-cursor` |
| Fedora | `sudo dnf install flatpak passt sway wayvnc python3 libxkbfile xcb-util-cursor` |
| Ubuntu 24.04+, Debian 13+, Mint 22+, Pop!_OS | `sudo apt install flatpak passt sway wayvnc python3-venv libxkbfile1 libxcb-cursor0` |
| openSUSE Tumbleweed | `sudo zypper install flatpak passt sway wayvnc python3 libxkbfile1 libxcb-cursor0` |
| NixOS | see [NixOS](#nixos) below |

Then install Sober (start it once and log in), and Cellar itself:

```sh
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo   # once, if Flathub isn't set up
flatpak install flathub org.vinegarhq.Sober

git clone https://github.com/ArcticTweaK/Cellar.git
cd Cellar
./install.sh
```

`install.sh` installs Cellar for your user only (no sudo) and adds it to your app menu. Run `cellar` or start it
from the menu. It tells you if anything is still missing. To **update**: `git pull && ./install.sh`. To
**remove** it: `./uninstall.sh` (your accounts stay).

What each package is for: `passt` (pasta) and `util-linux` (unshare) run several accounts at once, `sway` +
`wayvnc` run background mode, `flatpak` runs Sober, and the two small libraries are for Qt (most desktops
already have them). Window layouts need KDE Plasma, Hyprland or Sway. Everything else works on any desktop.

### NixOS

Try it without installing:

```sh
nix run github:ArcticTweaK/Cellar
```

To install it, add the flake to your config:

```nix
# flake.nix
inputs.cellar.url = "github:ArcticTweaK/Cellar";
inputs.cellar.inputs.nixpkgs.follows = "nixpkgs";

# configuration.nix
environment.systemPackages = [ inputs.cellar.packages.x86_64-linux.default ];
services.flatpak.enable = true;   # then: flatpak install flathub org.vinegarhq.Sober
```

The package brings its own pasta, unshare, sway and wayvnc. Anti-AFK for normal windows also wants
`programs.ydotool.enable = true;`.

## Background mode and macros

Linux desktops (Wayland) never let one program type into another program's window. A normal Roblox window
only gets input while you have it focused. **Run in the background** (Edit account) gives the account its own
invisible 1280×720 screen instead: a headless `sway` that only its Sober draws on, shared over a private
`wayvnc` socket. Right-click the account > **View screen** to watch it, control it, or **record a macro**.
The mouse position you see there is what `move` / `click` use.

Macros (Macros tab) are one step per line:

```
# park the cursor on the bush and press F about 30 times a second
move 561 355
key f 15
wait 18
```

| Step | Does |
|---|---|
| `tap space` | press and release a key |
| `down w` / `up w` | hold / release a key |
| `key w 800` | hold a key for 800 ms |
| `type hello` | type text |
| `click 640 360` / `rclick x y` / `move x y` | mouse on the account's own screen |
| `scroll up` / `scroll down` | mouse wheel |
| `wait 1500` / `wait 1000-3000` | wait (a range picks a random time) |
| `repeat 5 {` … `}` | do the lines inside five times (blocks can be nested) |
| `random {` … `}` | each time, do one of the lines inside, picked at random |
| `stop after 30m` | end the macro after that long (`90s`, `2h` work too) |
| `# ...` | comment |

The editor colours the steps and underlines mistakes on their line while you type; **Run once (test)** runs
what is in the editor once, without saving it. A looping macro needs at least one `wait` or `key` step. Each background account runs its own macro, and one
can start by itself at launch (Edit account > Macro at launch).

## Command line and shortcuts

Control the running Cellar from a terminal, a script or a keyboard shortcut of your desktop:

```sh
cellar list                                  # accounts and what they are doing
cellar launch ArcticTweaK alt2               # each in its own game (or the one on the Launch page)
cellar launch group:Farm --place 920587237   # a whole group into one game
cellar launch all --job PLACE JOB_ID         # everyone into one exact server
cellar preset "Evening farm"                 # run a saved preset
cellar stop all
```

`launch` and `preset` start Cellar first if it is not running. Right-click an account (or a preset) >
**Add to app menu** makes a launcher entry for it.

In the window: **Ctrl+K** opens the command palette (type a few letters of an account, page, preset, game or
theme and press Enter), **Enter** launches the selected accounts, **F2** edits, **Ctrl+N** adds an account,
**Ctrl+Shift+S** stops all, **Ctrl+1…0** switch pages, **Ctrl+F** searches, **F5** refreshes the status.

## Measured numbers

i5-12600K, RTX 3070 Ti, 32 GB RAM, one alt standing in a game:

| Setting | CPU | RAM | Graphics memory |
|---|---|---|---|
| 240 FPS, Roblox default graphics | 0.82 cores | 1.0 GB | 245 MB |
| 30 FPS, lowest graphics (alt default) | 0.17 cores | 1.0 GB | 261 MB OpenGL / 400 MB Vulkan |
| + background mode | +0.11 cores | +0.19 GB | - |

RAM sets the limit: about 18-20 alts fit next to a desktop and browser on 32 GB. A join takes 5-10 seconds.

## How it works

Sober allows one copy per PC because every copy claims the same localhost port. Cellar runs each account in its
own little sandbox:

| Per account | How |
|---|---|
| Sober profile (login, settings) | Its own `HOME` in `~/.local/share/cellar/profiles/<id>`, a copy-on-write clone of your Sober profile (about 0 bytes extra on btrfs/xfs). Cookies and logs are not copied. |
| Network | Its own network namespace (`unshare --net`) with `pasta` attached for normal internet. pasta is attached *afterwards* on purpose: if pasta starts Sober itself, it also gets a new PID namespace, the desktop portal refuses it, and Roblox waits about 2 minutes before connecting and often fails with error 279. |
| Clock, IPC | `unshare --time --ipc` |
| Runtime folder | A private `XDG_RUNTIME_DIR` with links to the real Wayland, PipeWire and D-Bus sockets |
| Process tree | A systemd user scope (`cellar-….scope`), used to stop it and for its CPU weight and RAM limit |

Every client starts with a `roblox-player:` link containing the account's own `browsertrackerid`. That number
is how Cellar matches windows and processes back to accounts, including after Cellar restarts.

The Sober developers don't support multi-instancing, so a Sober update can break it. If that happens, turn
multi-instance off (Settings) to launch accounts one at a time through your normal Sober.

## Files

| What | Where |
|---|---|
| Settings, presets, macros | `~/.config/cellar/settings.json` |
| Accounts (encrypted) + backups | `~/.local/share/cellar/accounts.dat`, `backups/` |
| Per-account Sober profiles | `~/.local/share/cellar/profiles/<account id>/` |
| Log | `~/.local/share/cellar/log.txt` |
| The program itself | `~/.local/share/cellar-app/` |

## Warning

Running several Roblox clients and automating input is against Roblox's rules and **can get accounts
moderated**. Use accounts you can afford to lose, and give every account a verified email and 2-step
verification. A cookie is a login: never share it or your `accounts.dat`.

## Credits and license

Made by **ArcticTweaK**. Cellar started as a Linux port of [Roblox MultiHub](https://github.com/Roblox-MultiHub/Roblox-MultiHub)
(Windows, GPL-3.0) by the Roblox-MultiHub authors. It has been rewritten for Linux and Sober since, and has added
background mode, macros, the Friends tab and the multi-instance sandbox.

GPL-3.0: free to use, change and share, as long as what you share stays open source under the same license.
Not affiliated with Roblox Corporation or VinegarHQ (Sober).
