"""Macros for background accounts: plain text, one step per line, sent over the account's VNC screen.

    tap space          press and release a key          (key names: a-z, 0-9, space, enter, esc,
    down w / up w      hold / let go of a key            tab, shift, ctrl, alt, left, right, up,
    key w 800          hold a key for 800 ms              down, f1-f12, backspace, ...)
    type hello         type text (the whole rest of the line, # included)
    click 640 360      left click at x y on the 1280x720 screen  (rclick = right click)
    move 640 360       move the mouse
    scroll up 640 360  scroll (or: scroll down x y)
    wait 1500          pause for 1500 ms   (wait 1000-3000 = a random pause in that range)
    repeat 5 {         do the lines up to } five times (blocks can be inside blocks)
    random {           each time, do ONE of the lines up to } (picked at random)
    }                  ends a repeat / random block
    stop after 30m     end the macro after 30 minutes (also 90s, 2h)
    # a comment       (also after a step: tap e  # open the shop)

A macro runs once or loops until you stop it. Every account runs its own copy, so one alt can
farm one thing while another does something else - none of it touches your desktop.
"""

import random
import re
import threading
import time
from typing import Callable, List, Optional, Tuple

from . import background, log

Step = Tuple[str, tuple]
HELP = __doc__.split("\n\n", 1)[1].rsplit("\n\n", 1)[0]


def _seconds(text: str) -> float:
    """'30m' -> 1800, '90s' -> 90, '2h' -> 7200, '500ms' -> 0.5 (a plain number = seconds)."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s|m|min|h)?\s*", text or "")
    if not m:
        raise ValueError(f"'{text}' is not a time like 30m, 90s or 2h")
    return float(m.group(1)) * {"ms": 0.001, "s": 1, None: 1, "m": 60, "min": 60, "h": 3600}[m.group(2)]


def parse(text: str) -> Tuple[List[Step], List[str]]:
    """Returns (steps, errors). Errors name the line, e.g. 'line 3: unknown key 'spce''.
    Blocks become ('repeat', (n, steps)) and ('random', (steps,)); 'stop after' becomes ('stop_after', (s,))."""
    root: List[Step] = []
    stack: List[tuple] = [("root", 0, root, None)]       # (kind, line, steps, arg)
    errors: List[str] = []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        op, _, rest = line.partition(" ")
        op = op.lower()
        # 'type' keeps the whole rest of the line ("type gg #1" types "gg #1"); other steps allow a # comment
        rest = rest.strip() if op == "type" else rest.split("#", 1)[0].strip()
        steps = stack[-1][2]
        a = rest.split()
        try:
            if op == "}":
                if len(stack) == 1:
                    raise ValueError("'}' without a repeat / random block to end")
                kind, start, body, arg = stack.pop()
                if not body:
                    raise ValueError(f"the {kind} block from line {start} is empty")
                stack[-1][2].append((kind, (arg, body) if kind == "repeat" else (body,)))
            elif op == "repeat":
                if not a or a[-1] != "{":
                    raise ValueError("write it as: repeat 5 {")
                n = int(a[0]) if len(a) == 2 and a[0].isdigit() else -1
                if not 1 <= n <= 100000:
                    raise ValueError("repeat needs a number from 1 to 100000, like: repeat 5 {")
                stack.append(("repeat", i, [], n))
            elif op == "random":
                if a != ["{"]:
                    raise ValueError("write it as: random {")
                stack.append(("random", i, [], None))
            elif op == "stop":
                if not a or a[0].lower() != "after":
                    raise ValueError("write it as: stop after 30m")
                steps.append(("stop_after", (_seconds(" ".join(a[1:])),)))
            elif op in ("tap", "down", "up"):
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
    for kind, start, _, _ in stack[1:]:
        errors.append(f"line {start}: the {kind} block is never closed with }}")
    if root and not _has_pause(root):
        errors.append("add at least one 'wait' - a loop without pauses would flood the game with input")
    return root, errors


def _has_pause(steps: List[Step]) -> bool:
    for op, args in steps:
        if op in ("wait", "key"):
            return True
        if op == "repeat" and _has_pause(args[1]):
            return True
        if op == "random" and _has_pause(args[0]):
            return True
    return False


def _stop_after(steps: List[Step]) -> float:
    for op, args in steps:
        if op == "stop_after":
            return args[0]
        if op in ("repeat", "random"):
            t = _stop_after(args[-1])
            if t:
                return t
    return 0.0


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
        limit = _stop_after(self.steps)
        self.deadline = time.time() + limit if limit else 0.0
        self.timed_out = False

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

    def _expired(self) -> bool:
        if self.deadline and time.time() >= self.deadline:
            if not self._stop.is_set():
                self.logf(f"[{self.who}] macro '{self.name}' stopped: its 'stop after' time is up.")
            self._stop.set()
            self.timed_out = True
        return self._stop.is_set()

    def _exec(self, v, steps: List[Step], held: set) -> bool:
        """Runs steps (blocks recursively). False = stopped."""
        for op, args in steps:
            if self._expired():
                return False
            if op == "repeat":
                for _ in range(args[0]):
                    if not self._exec(v, args[1], held):
                        return False
            elif op == "random":
                if not self._exec(v, [random.choice(args[0])], held):
                    return False
            elif op == "stop_after":
                continue
            elif op == "tap":
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
                    return False
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
                    return False
        return True

    def _run(self) -> None:
        v: Optional[background.VNC] = None
        held: set = set()
        try:
            v = background.VNC(self.screen.vnc)
            while not self._stop.is_set():
                if not self._exec(v, self.steps, held):
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
