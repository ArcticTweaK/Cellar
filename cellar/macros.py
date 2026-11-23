"""Macros for background accounts: plain text, one step per line, sent over the account's VNC screen.

    tap space          press and release a key          (key names: a-z, 0-9, space, enter, esc,
    down w / up w      hold / let go of a key            tab, shift, ctrl, alt, left, right, up,
    key w 800          hold a key for 800 ms              down, f1-f12, backspace, ...)
    type hello         type text
    click 640 360      left click at x y on the 1280x720 screen  (rclick = right click)
    move 640 360       move the mouse
    scroll up 640 360  scroll (or: scroll down x y)
    wait 1500          pause for 1500 ms   (wait 1000-3000 = a random pause in that range)
    # anything after # is a comment

A macro runs once or loops until you stop it. Every account runs its own copy, so one alt can
farm one thing while another does something else - none of it touches your desktop.
"""

import random
import threading
import time
from typing import Callable, List, Optional, Tuple

from . import background, log

Step = Tuple[str, tuple]
HELP = __doc__.split("\n\n", 1)[1].rsplit("\n\n", 1)[0]


def parse(text: str) -> Tuple[List[Step], List[str]]:
    """Returns (steps, errors). Errors name the line, e.g. 'line 3: unknown key 'spce''."""
    steps: List[Step] = []
    errors: List[str] = []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        op, _, rest = line.partition(" ")
        op, rest = op.lower(), rest.strip()
        a = rest.split()
        try:
            if op in ("tap", "down", "up"):
                steps.append((op, (background.keysym(rest),)))
            elif op == "key":
                steps.append(("key", (background.keysym(a[0]), int(a[1]) if len(a) > 1 else 100)))
            elif op == "type":
                steps.append(("type", (rest,)))
            elif op in ("click", "rclick", "move"):
                steps.append((op, (int(a[0]), int(a[1]))))
            elif op == "scroll":
                steps.append(("scroll", (a[0].lower() == "up", int(a[1]) if len(a) > 1 else background.W // 2,
                                         int(a[2]) if len(a) > 2 else background.H // 2)))
            elif op == "wait":
                lo, _, hi = a[0].partition("-")
                steps.append(("wait", (int(lo), int(hi) if hi else int(lo))))
            else:
                raise ValueError(f"unknown step '{op}'")
        except (IndexError, ValueError) as ex:
            errors.append(f"line {i}: {ex if str(ex) and 'index' not in str(ex) else 'missing value'} - {raw.strip()}")
    if steps and not any(op == "wait" or op == "key" for op, _ in steps):
        errors.append("add at least one 'wait' - a loop without pauses would flood the game with input")
    return steps, errors


class Runner:
    """Runs one macro for one account in its own thread until it ends or stop() is called."""

    def __init__(self, screen: background.Screen, name: str, text: str, loop: bool,
                 logf: Callable[[str], None], who: str):
        self.screen, self.name, self.loop, self.logf, self.who = screen, name, loop, logf, who
        self.steps, errors = parse(text)
        if errors:
            raise ValueError("; ".join(errors))
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"macro {who}")
        self.rounds = 0

    def start(self) -> "Runner":
        self.thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return self.thread.is_alive()

    def _sleep(self, ms: float) -> bool:
        return self._stop.wait(max(0.0, ms) / 1000.0)

    def _run(self) -> None:
        v: Optional[background.VNC] = None
        held: set = set()
        try:
            v = background.VNC(self.screen.vnc)
            while not self._stop.is_set():
                for op, args in self.steps:
                    if self._stop.is_set():
                        break
                    if op == "tap":
                        v.tap(args[0])
                    elif op == "down":
                        v.key(args[0], True)
                        held.add(args[0])
                    elif op == "up":
                        v.key(args[0], False)
                        held.discard(args[0])
                    elif op == "key":
                        v.key(args[0], True)
                        held.add(args[0])
                        stopped = self._sleep(args[1])
                        v.key(args[0], False)
                        held.discard(args[0])
                        if stopped:
                            break
                    elif op == "type":
                        v.type_text(args[0])
                    elif op == "click":
                        v.click(*args)
                    elif op == "rclick":
                        v.click(*args, button=3)
                    elif op == "move":
                        v.pointer(*args)
                    elif op == "scroll":
                        v.scroll(args[1], args[2], args[0])
                    elif op == "wait":
                        if self._sleep(random.randint(args[0], args[1])):
                            break
                self.rounds += 1
                if not self.loop:
                    break
            if not self._stop.is_set():
                self.logf(f"[{self.who}] macro '{self.name}' finished.")
        except Exception as ex:
            log.error("macro", ex)
            self.logf(f"[{self.who}] macro '{self.name}' stopped: {ex}")
        finally:
            if v:
                for k in held:                  # never leave a key held down
                    try:
                        v.key(k, False)
                    except Exception:
                        pass
                v.close()


def from_recording(events: List[tuple]) -> str:
    """events: (seconds, kind, data) with kind 'down'/'up' (key name) or 'click'/'rclick' ((x, y)).
    Gives macro text with the recorded timing."""
    lines, last = [], None
    for t, kind, data in events:
        if last is not None:
            gap = int((t - last) * 1000)
            if gap >= 15:
                lines.append(f"wait {gap}")
        last = t
        if kind in ("down", "up"):
            lines.append(f"{kind} {data}")
        else:
            lines.append(f"{kind} {data[0]} {data[1]}")
    return "\n".join(lines) + ("\n" if lines else "")
