"""Shared view machinery: main loop, vim-style key sequences, live reload, status line.

Subclasses implement load(), rows(), count() and handle(key).
"""

from __future__ import annotations

import curses
import locale
import os
import queue
import sys
import threading
from pathlib import Path

from . import ui
from .api import Api, ApiError

SEQUENCES = ("gg", "dd", ">>", "<<", "cw")
KEYMAP = {
    curses.KEY_DOWN: "j",
    curses.KEY_UP: "k",
    curses.KEY_HOME: "gg",
    curses.KEY_END: "G",
    curses.KEY_ENTER: "\n",
}


COMMON_KEYS = [
    ("j / k", "move down / up"),
    ("gg / G", "jump to first / last"),
    ("p", "switch project"),
    ("r", "reload"),
    ("?", "show this keymap"),
    ("q", "quit"),
]


class App:
    kind = ""  # "todos" | "notes", matches the server's change events
    hints = ""
    keymap: list[tuple[str, str]] = []  # view-specific keys, shown by `?` before COMMON_KEYS
    empty_text = "nothing here yet"

    def __init__(self, scr, api: Api, code: str):
        self.scr, self.api, self.code = scr, api, code
        self.cursor = 0
        self.top = 0
        self.pending = ""
        self.message = ""
        self.error = False
        self.running = True
        self.events: queue.Queue = queue.Queue()
        self.stop = threading.Event()

    # --- for subclasses ----------------------------------------------------------

    def load(self) -> None:
        raise NotImplementedError

    def count(self) -> int:
        raise NotImplementedError

    def rows(self) -> list[tuple[str, int]]:
        raise NotImplementedError

    def handle(self, key: str) -> None:
        pass

    def subtitle(self) -> str:
        return ""

    def list_height(self, h: int) -> int:
        return h - 2

    def draw_below(self, y0: int, y1: int, w: int) -> None:
        pass

    # --- helpers -----------------------------------------------------------------

    def notify(self, message: str, error: bool = False) -> None:
        self.message, self.error = message, error

    def guard(self, fn) -> bool:
        """Run an API call; show errors in the status line. On a stale-edit conflict
        (someone changed the file meanwhile) reload so the user sees the new state."""
        try:
            fn()
            return True
        except ApiError as e:
            self.notify(str(e), error=True)
            if e.status == 409:
                self.reload(quiet=True)
            return False

    def reload(self, quiet: bool = False) -> None:
        try:
            self.load()
        except ApiError as e:
            if not quiet:
                self.notify(str(e), error=True)

    def clamp(self) -> None:
        self.cursor = max(0, min(self.cursor, self.count() - 1))

    def edit_file(self, path: Path, line: int | None = None) -> None:
        err = ui.run_editor(self.scr, ui.editor_cmd(path, line))
        if err:
            self.notify(err, error=True)
        self.reload()

    def switch_project(self) -> None:
        try:
            projects = self.api.projects()
        except ApiError as e:
            return self.notify(str(e), error=True)
        code = ui.pick(self.scr, "project", projects, self.code)
        if code and code != self.code:
            self.code, self.cursor, self.top = code, 0, 0
            self.notify("")
            self.reload()

    # --- loop ----------------------------------------------------------------------

    def run(self) -> None:
        ui._cursor(False)
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        self.scr.timeout(200)  # wake up regularly to apply server events
        threading.Thread(target=self.api.listen, args=(self.events, self.stop), daemon=True).start()
        self.reload()
        try:
            while self.running:
                self.apply_events()
                self.draw()
                try:
                    key = self.scr.get_wch()
                except curses.error:
                    continue
                self.on_key(key)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop.set()

    def apply_events(self) -> None:
        dirty = False
        while True:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            if ev.get("type") == "connected" or (
                ev.get("type") == "changed"
                and ev.get("project") == self.code
                and ev.get("kind") == self.kind
            ):
                dirty = True
        if dirty:
            self.reload(quiet=True)

    def on_key(self, key) -> None:
        if isinstance(key, int):
            key = KEYMAP.get(key)
            if key is None:
                return
        if key == ui.ESC:
            self.pending = ""
            return
        seq = self.pending + key
        if seq in SEQUENCES:
            self.pending, key = "", seq
        elif any(s.startswith(seq) for s in SEQUENCES):
            self.pending = seq
            return
        else:
            self.pending = ""
        self.message = ""

        n = self.count()
        if key == "j":
            self.cursor = min(n - 1, self.cursor + 1) if n else 0
        elif key == "k":
            self.cursor = max(0, self.cursor - 1)
        elif key == "gg":
            self.cursor = 0
        elif key == "G":
            self.cursor = max(0, n - 1)
        elif key == "p":
            self.switch_project()
        elif key == "r":
            self.reload()
        elif key == "?":
            ui.show_keymap(self.scr, f"{self.kind} keys", self.keymap + COMMON_KEYS)
        elif key == "q":
            self.running = False
        else:
            self.handle(key)

    def draw(self) -> None:
        scr = self.scr
        scr.erase()
        h, w = scr.getmaxyx()
        ui.add(scr, 0, 0, f" {self.code} · {self.kind}{self.subtitle()} ".ljust(w), curses.A_REVERSE)

        body = max(1, self.list_height(h))
        rows = self.rows()
        self.clamp()
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + body:
            self.top = self.cursor - body + 1
        if not rows:
            ui.add(scr, 1, 2, self.empty_text, curses.A_DIM)
        for i in range(body):
            idx = self.top + i
            if idx >= len(rows):
                break
            text, attr = rows[idx]
            if idx == self.cursor:
                ui.add(scr, 1 + i, 0, text.ljust(w), attr | curses.A_REVERSE)
            else:
                ui.add(scr, 1 + i, 0, text, attr)
        self.draw_below(1 + body, h - 1, w)

        if self.message:
            ui.add(scr, h - 1, 0, " " + self.message, curses.A_BOLD if self.error else 0)
        else:
            ui.add(scr, h - 1, 0, " " + self.hints, curses.A_DIM)
        if self.pending:
            ui.add(scr, h - 1, max(0, w - len(self.pending) - 2), self.pending, curses.A_BOLD)
        scr.refresh()


def run_app(cls: type[App], prog: str, code: str | None, root: Path | None) -> int:
    os.environ.setdefault("ESCDELAY", "25")  # make Esc respond instantly
    locale.setlocale(locale.LC_ALL, "")
    try:
        api = Api(root)
        projects = api.projects()
    except ApiError as e:
        print(f"{prog}: {e}", file=sys.stderr)
        return 1
    if code and code not in projects:
        print(f"{prog}: unknown project {code!r} (known: {', '.join(projects)})", file=sys.stderr)
        return 1

    def main(scr):
        chosen = code or ui.pick(scr, "project", projects, "inbox")
        if chosen:
            cls(scr, api, chosen).run()

    curses.wrapper(main)
    return 0
