"""Setup prompts in the style of clack (the CLI kit OpenClaw's onboarding uses): a thin rail down the left,
◆ for the question you're on, ◇ once answered, ● / ○ for single choice, ◼ / ◻ for tick boxes.
Only the mark changes as you move or tick; the row itself stays plain.

Works on macOS, Linux and Windows terminals. Without a terminal (piped input, tests) it falls back to
plain numbered questions.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time

# --------------------------------------------------------------------------- styling
_ON = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


_enable_windows_ansi()


def _c(code: str):
    return lambda s: f"\x1b[{code}m{s}\x1b[0m" if _ON else s


cyan, green, yellow, red, gray, dim, bold, inverse, underline = (_c("36"), _c("32"), _c("33"), _c("31"), _c("90"),
                                                                 _c("2"), _c("1"), _c("7"), _c("4"))
ACCENT = cyan

BAR, START, END = "│", "┌", "└"
ACTIVE, DONE, CANCEL, WARN = "◆", "◇", "■", "▲"
RADIO_ON, RADIO_OFF = "●", "○"
BOX_ON, BOX_OFF = "◼", "◻"

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _width() -> int:
    return max(40, shutil.get_terminal_size((100, 24)).columns)


def _fit(s: str, room: int) -> str:
    return s if len(s) <= room else s[: max(1, room - 1)] + "…"


def _out(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()


class Cancelled(KeyboardInterrupt):
    pass


# --------------------------------------------------------------------------- keys
class _Raw:
    """One keypress at a time, arrows included. Ctrl+C still interrupts."""

    def __enter__(self):
        self.old = None
        if os.name != "nt":
            import termios
            import tty
            self.old = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        _out("\x1b[?25l")                    # hide the cursor while choosing
        return self

    def __exit__(self, *a):
        _out("\x1b[?25h")
        if self.old is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old)

    def key(self, timeout: float | None = None) -> str | None:
        """'up' 'down' 'left' 'right' 'enter' 'space' 'esc' 'backspace', a character, or None on timeout."""
        if os.name == "nt":
            import msvcrt
            end = None if timeout is None else time.time() + timeout
            while not msvcrt.kbhit():
                if end is not None and time.time() > end:
                    return None
                time.sleep(0.02)
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(msvcrt.getwch(), "")
            if ch == "\x03":
                raise KeyboardInterrupt
            return {"\r": "enter", " ": "space", "\x1b": "esc", "\x08": "backspace"}.get(ch, ch)
        import select
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        if not r:
            return None
        ch = os.read(sys.stdin.fileno(), 1).decode(errors="ignore")
        if ch == "\x1b":
            r, _, _ = select.select([sys.stdin], [], [], 0.03)
            if not r:
                return "esc"
            seq = os.read(sys.stdin.fileno(), 2).decode(errors="ignore")
            return {"[A": "up", "[B": "down", "[C": "right", "[D": "left", "OA": "up", "OB": "down"}.get(seq, "")
        return {"\r": "enter", "\n": "enter", " ": "space", "\x7f": "backspace", "\x08": "backspace"}.get(ch, ch)


class Frame:
    """Redraws a block of lines in place."""

    def __init__(self):
        self.n = 0

    def draw(self, lines: list[str]) -> None:
        w = _width()
        buf = ""
        if self.n:
            buf += f"\x1b[{self.n}F"           # back to the first line we drew
        buf += "\x1b[J"
        for ln in lines:
            # never let a line wrap, or redrawing would leave stray copies behind
            plain = _ANSI.sub("", ln)
            if len(plain) > w - 1:
                ln = _fit(plain, w - 1)
            buf += ln + "\n"
        _out(buf)
        self.n = len(lines)

    def clear(self) -> None:
        if self.n:
            _out(f"\x1b[{self.n}F\x1b[J")
            self.n = 0


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


# --------------------------------------------------------------------------- framing
def intro(title: str) -> None:
    print(f"{gray(START)}  {inverse(' ' + title + ' ') if _ON else title}")
    print(gray(BAR))


def outro(message: str) -> None:
    print(f"{gray(END)}  {message}\n")


def note(message: str, title: str = "") -> None:
    lines = message.splitlines() or [""]
    w = min(_width() - 6, max([len(_ANSI.sub("", ln)) for ln in lines] + [len(title) + 2]) + 2)
    head = f"{green(DONE)}  {title} " + gray("─" * max(1, w - len(title) - 1) + "╮")
    print(head)
    print(gray(BAR) + " " * (w + 2) + gray(BAR))
    for ln in lines:
        pad = w - len(_ANSI.sub("", ln))
        print(f"{gray(BAR)}  {ln}{' ' * max(0, pad)}{gray(BAR)}")
    print(gray(BAR) + " " * (w + 2) + gray(BAR))
    print(gray("├" + "─" * (w + 2) + "╯"))
    print(gray(BAR))


def step(message: str, mark: str = DONE, color=green) -> None:
    print(f"{color(mark)}  {message}")
    print(gray(BAR))


def info(message: str) -> None:
    for i, ln in enumerate(message.splitlines()):
        print(f"{gray(BAR)}  {ln}" if i else f"{cyan('●')}  {ln}")
    print(gray(BAR))


def success(message: str) -> None:
    step(message, "◆", green)


def warn(message: str) -> None:
    step(message, WARN, yellow)


def _answered(title: str, answer: str) -> None:
    print(f"{green(DONE)}  {title}")
    print(f"{gray(BAR)}  {dim(answer)}")
    print(gray(BAR))


# --------------------------------------------------------------------------- questions
def select(title: str, options: list[tuple], initial=None) -> object:
    """options: (label, value) or (label, value, hint). Arrow keys, Enter."""
    opts = [o if len(o) == 3 else (o[0], o[1], "") for o in options]
    if not interactive():
        return _plain_select(title, opts, initial)
    i = next((n for n, o in enumerate(opts) if o[1] == initial), 0)
    f = Frame()

    def render():
        room = _width() - 8
        lines = [f"{cyan(ACTIVE)}  {bold(title)}"]
        for n, (label, _, hint) in enumerate(opts):
            on = n == i
            text = _fit(label + (f"  ({hint})" if hint and on else ""), room)
            if on and hint:
                base, h = text[: len(label)], text[len(label):]
                text = base + dim(h)
            lines.append(f"{cyan(BAR)} {cyan('›') if on else ' '} {green(RADIO_ON) if on else dim(RADIO_OFF)} {text if on else dim(text)}")
        lines.append(f"{cyan(END)}  {dim('↑/↓ to move · Enter to choose')}")
        return lines

    with _Raw() as kb:
        while True:
            f.draw(render())
            k = kb.key()
            if k in ("up", "k"):
                i = (i - 1) % len(opts)
            elif k in ("down", "j", "tab"):
                i = (i + 1) % len(opts)
            elif k == "enter":
                break
            elif k == "esc":
                f.clear()
                raise Cancelled
    f.clear()
    _answered(title, opts[i][0])
    return opts[i][1]


def multiselect(title: str, options: list[tuple], initial: list | None = None, required: bool = True,
                exclusive=None, limit: int = 0) -> list:
    """Tick boxes: arrow keys to move, Space to tick, a to tick all, Enter when done."""
    opts = [o if len(o) == 3 else (o[0], o[1], "") for o in options]
    if not interactive():
        return _plain_multi(title, opts, initial or [])
    picked = [o[1] in (initial or []) for o in opts]
    i = 0
    err = ""
    f = Frame()

    def render():
        room = _width() - 8
        lines = [f"{cyan(ACTIVE)}  {bold(title)}"]
        for n, (label, _, hint) in enumerate(opts):
            on, sel = n == i, picked[n]
            mark = green(BOX_ON) if sel else (cyan(BOX_OFF) if on else dim(BOX_OFF))
            text = _fit(label, room)
            # where you are: a pointer and underlined words; ticked rows stay bright, the rest dim
            text = underline(text) if on else (text if sel else dim(text))
            ptr = cyan("›") if on else " "
            lines.append(f"{cyan(BAR)} {ptr} {mark} {text}" + (f"  {dim('(' + hint + ')')}" if hint and on else ""))
        tail = yellow(err) if err else dim("↑/↓ to move · Space to tick · " + (f"up to {limit}" if limit else "a for all") + " · Enter when done")
        lines.append(f"{cyan(END)}  {tail}")
        return lines

    with _Raw() as kb:
        while True:
            f.draw(render())
            k = kb.key()
            err = ""
            if k in ("up", "k"):
                i = (i - 1) % len(opts)
            elif k in ("down", "j", "tab"):
                i = (i + 1) % len(opts)
            elif k in ("space", "right", "left", "x"):
                if limit and not picked[i] and sum(picked) >= limit:
                    err = f"Up to {limit}. Untick one first."
                    continue
                picked[i] = not picked[i]
                if picked[i] and exclusive is not None:      # "Anywhere" and specific places don't mix
                    for n, o in enumerate(opts):
                        if (opts[i][1] == exclusive) != (o[1] == exclusive):
                            picked[n] = False
            elif k == "a" and not limit:
                on = not all(picked)
                picked = [on] * len(opts)
            elif k == "enter":
                if required and not any(picked):
                    err = "Tick at least one (Space)."
                    continue
                break
            elif k == "esc":
                f.clear()
                raise Cancelled
    f.clear()
    chosen = [o for o, p in zip(opts, picked) if p]
    _answered(title, ", ".join(o[0] for o in chosen) or "none")
    return [o[1] for o in chosen]


def text(title: str, default: str = "", secret: bool = False) -> str:
    if not interactive():
        v = input(f"{title} " + (f"({default}) " if default else ""))
        return v.strip() or default
    print(f"{cyan(ACTIVE)}  {bold(title)}" + (f"  {dim('(' + default + ')')}" if default else ""))
    try:
        if secret:
            import getpass
            v = getpass.getpass(f"{cyan(BAR)}  ")
        else:
            v = input(f"{cyan(BAR)}  ")
    except EOFError:
        v = ""
    v = v.strip() or default
    _out("\x1b[2F\x1b[J")
    _answered(title, ("•" * min(len(v), 12)) if secret and v else (v or "skipped"))
    return v


def confirm(title: str, initial: bool = True) -> bool:
    return bool(select(title, [("Yes", True), ("No", False)], initial))


# --------------------------------------------------------------------------- plain fallbacks (no terminal)
def _plain_select(title, opts, initial):
    print(title)
    for n, (label, _, _) in enumerate(opts, 1):
        print(f"  {n}. {label}")
    dflt = next((n for n, o in enumerate(opts, 1) if o[1] == initial), 1)
    v = (input(f"Number ({dflt}): ").strip() or str(dflt))
    n = int(v) if v.isdigit() and 1 <= int(v) <= len(opts) else dflt
    return opts[n - 1][1]


def _plain_multi(title, opts, initial):
    print(title)
    for n, (label, _, _) in enumerate(opts, 1):
        print(f"  {n}. {label}")
    dflt = ",".join(str(n) for n, o in enumerate(opts, 1) if o[1] in initial) or "1"
    v = input(f"Numbers, separated by commas ({dflt}): ").strip() or dflt
    got = [opts[int(x) - 1][1] for x in re.findall(r"\d+", v) if 0 < int(x) <= len(opts)]
    return got or [o[1] for o in opts if o[1] in initial] or [opts[0][1]]
