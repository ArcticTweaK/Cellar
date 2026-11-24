# Cellar design rules

Decided 2026-11-24, after trying a game-launcher layout (Home / Library) and a section layout: Cellar keeps the
**Roblox MultiHub layout** it started with. It looks like what it is made to do. Change these rules on purpose,
not page by page.

## The layout (fixed)

```
 Cellar   RUNNING 3/5   CPU 14%   MEMORY 7.2 GB                       [update]  ● Multi-instance on
 search · groups · order · Cards/Table   | Launch · Presets · Macros · Anti-AFK & rejoin · Windows ·
 the account list (always on screen)     |   My Sober · Performance · Settings · Help
                                         |   (one tool per tab)
 Add account · Edit · Remove · Details · ▶Launch · Stop · Stop all
 LOG  filter · search · Copy · Open log file · Clear
 the log (always on screen)
```

- The account list and the log never leave the screen. Every tool is one tab next to the list.
- Launch is the first tab and the one Cellar opens on.
- New features go into an existing tab, or become a new tab only when they are a tool of their own.
  No hidden pages, no back / forward, no pages inside pages.

## The rules

1. **Looks like what it does.** A tool for running accounts: the numbers, the list, the tools, the log. No
   decoration that does not show state.
2. **Next to the website, not instead of it.** Browsing Roblox is roblox.com's job (with RoValra). Cellar shows a
   game only to launch into it (Your games, search, a pasted link).
3. **Two clicks.** Anything you do often: select accounts, click a game, launch.
4. **Say what will happen.** Buttons name their effect ("Launch 3 accounts into ABOVE"); every option has a
   tooltip in plain words; nothing unexplained.
5. **Never frozen.** Network and disk work runs in the background (`bg`); the window stays responsive.
6. **One look.** Colours come from the theme (`theme.c` / style sheet), shapes from the shared style sheet.
   The System theme must still work (the desktop's own look).
7. **Same everywhere.** Right-click = the same kind of menu; double-click = do it; Enter = launch.
8. **Measured, not guessed.** New UI that creates widgets is checked with `tools/soak.py` (no growth) and
   `tools/screenshot.py` (every theme).
