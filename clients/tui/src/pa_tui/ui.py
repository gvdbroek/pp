"""Small curses helpers: safe drawing, a one-line prompt, a list picker, $EDITOR."""

from __future__ import annotations

import curses
import os
import shlex
import subprocess
from pathlib import Path

ENTER = ("\n", "\r", curses.KEY_ENTER)
BACKSPACE = (curses.KEY_BACKSPACE, "\x7f", "\x08")
ESC = "\x1b"

# Editors that accept `+<line> <file>`.
PLUS_LINE = {"vi", "vim", "nvim", "gvim", "view", "nano", "emacs", "emacsclient",
             "micro", "kak", "joe", "ne", "mg"}


def add(win, y: int, x: int, text: str, attr: int = 0) -> None:
    """addstr that clips to the window and never raises."""
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    room = w - x - (1 if y == h - 1 else 0)  # curses errors on the bottom-right cell
    try:
        win.addstr(y, x, text.replace("\t", "    ")[: max(0, room)], attr)
    except curses.error:
        pass


def _cursor(visible: bool) -> None:
    try:
        curses.curs_set(1 if visible else 0)
    except curses.error:
        pass


def prompt(scr, label: str, initial: str = "") -> str | None:
    """Read one line on the bottom row. Enter accepts, Esc cancels (returns None).
    Supports arrows, Home/End, Ctrl-A/E, Ctrl-U and Backspace/Delete."""
    buf, pos = list(initial), len(initial)
    _cursor(True)
    try:
        while True:
            h, w = scr.getmaxyx()
            text = label + "".join(buf)
            start = max(0, len(label) + pos - (w - 2))
            scr.move(h - 1, 0)
            scr.clrtoeol()
            add(scr, h - 1, 0, text[start:], curses.A_BOLD)
            scr.move(h - 1, min(w - 2, len(label) + pos - start))
            scr.refresh()
            try:
                k = scr.get_wch()
            except curses.error:
                continue
            if k in ENTER:
                return "".join(buf)
            if k == ESC:
                return None
            if k in BACKSPACE:
                if pos:
                    del buf[pos - 1]
                    pos -= 1
            elif k == curses.KEY_DC:
                if pos < len(buf):
                    del buf[pos]
            elif k == curses.KEY_LEFT:
                pos = max(0, pos - 1)
            elif k == curses.KEY_RIGHT:
                pos = min(len(buf), pos + 1)
            elif k in (curses.KEY_HOME, "\x01"):
                pos = 0
            elif k in (curses.KEY_END, "\x05"):
                pos = len(buf)
            elif k == "\x15":
                del buf[:pos]
                pos = 0
            elif isinstance(k, str) and k.isprintable():
                buf.insert(pos, k)
                pos += 1
    finally:
        _cursor(False)


def pick(scr, title: str, options: list[str], current: str | None = None) -> str | None:
    """Full-screen list picker with j/k, g/G, Enter; Esc or q cancels."""
    if not options:
        return None
    i = options.index(current) if current in options else 0
    while True:
        h, w = scr.getmaxyx()
        scr.erase()
        add(scr, 0, 0, f" {title} ".ljust(w), curses.A_REVERSE)
        rows = max(1, h - 2)
        top = max(0, i - rows + 1)
        for r, opt in enumerate(options[top : top + rows]):
            add(scr, 1 + r, 2, opt, curses.A_REVERSE if top + r == i else 0)
        add(scr, h - 1, 0, " j/k move  enter select  esc cancel", curses.A_DIM)
        scr.refresh()
        try:
            k = scr.get_wch()
        except curses.error:
            continue
        if k in ("j", curses.KEY_DOWN):
            i = min(len(options) - 1, i + 1)
        elif k in ("k", curses.KEY_UP):
            i = max(0, i - 1)
        elif k in ("g", curses.KEY_HOME):
            i = 0
        elif k in ("G", curses.KEY_END):
            i = len(options) - 1
        elif k in ENTER or k == " ":
            return options[i]
        elif k in (ESC, "q"):
            return None


def show_keymap(scr, title: str, keymap: list[tuple[str, str]]) -> None:
    """Full-screen list of (keys, description); any key closes it."""
    width = max(len(k) for k, _ in keymap) + 4
    while True:
        h, w = scr.getmaxyx()
        scr.erase()
        add(scr, 0, 0, f" {title} ".ljust(w), curses.A_REVERSE)
        for i, (keys, desc) in enumerate(keymap[: max(0, h - 2)]):
            add(scr, 1 + i, 2, keys, curses.A_BOLD)
            add(scr, 1 + i, 2 + width, desc)
        add(scr, h - 1, 0, " press any key to close", curses.A_DIM)
        scr.refresh()
        try:
            k = scr.get_wch()
        except curses.error:
            continue
        if k != curses.KEY_RESIZE:
            return


def editor_cmd(path: Path | str, line: int | None = None, env=None) -> list[str]:
    """Command to open `path` in $VISUAL / $EDITOR, at `line` when the editor allows."""
    env = os.environ if env is None else env
    editor = env.get("VISUAL") or env.get("EDITOR") or ("notepad" if os.name == "nt" else "vi")
    cmd = shlex.split(editor, posix=os.name != "nt")
    name = Path(cmd[0]).stem.lower()
    if line and name in PLUS_LINE:
        return [*cmd, f"+{line}", str(path)]
    if line and name in ("hx", "helix"):
        return [*cmd, f"{path}:{line}"]
    return [*cmd, str(path)]


def run_editor(scr, cmd: list[str]) -> str | None:
    """Suspend curses, run the editor, restore. Returns an error message or None."""
    curses.def_prog_mode()
    curses.endwin()
    try:
        subprocess.run(cmd)
        return None
    except OSError as e:
        return f"cannot start editor {cmd[0]!r}: {e}"
    finally:
        curses.reset_prog_mode()
        scr.clear()
        scr.refresh()
