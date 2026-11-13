"""Filesystem store: the files under the root folder are the only source of truth.

    <root>/<code>.todos.<YYYYMMDD>.md   active todo list; the date is the day it is for
    <root>/<code>.notes.md              note log
    <root>/history/<code>.todos.<YYYYMMDD>.md   rolled-over snapshots

Rollover is lazy: whenever a project's todos are accessed and the active file is dated
before today, it is moved to history and a fresh file with the carried-over open work
is created. The filename is authoritative, file mtimes are never consulted for dates.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from . import notes as notes_mod
from .todos import TodoList

CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
TODOS_RE = re.compile(r"^(?P<code>[a-z0-9][a-z0-9_-]*)\.todos\.(?P<date>\d{8})\.md$")
NOTES_RE = re.compile(r"^(?P<code>[a-z0-9][a-z0-9_-]*)\.notes\.md$")
INBOX = "inbox"
HISTORY = "history"


class ProjectError(ValueError):
    """Invalid project code."""


class UnknownProject(ProjectError, LookupError):
    pass


class ProjectExists(ProjectError):
    pass


def default_root() -> Path:
    return Path(os.environ.get("PA_HOME") or Path.home() / "pa")


def validate_code(code: str) -> str:
    if not CODE_RE.match(code or ""):
        raise ProjectError(
            f"invalid project code {code!r}: use lowercase letters, digits, '-' or '_'"
        )
    return code


def _stamp(d: date) -> str:
    return d.strftime("%Y%m%d")


def atomic_write(path: Path, text: str, retries: int = 10) -> None:
    """Write via temp file + rename. Retries because on Windows the rename fails while
    another process (editor, antivirus scanner) briefly holds the target open."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    for attempt in range(retries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == retries - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05 * (attempt + 1))


class Store:
    def __init__(self, root: Path | None = None, today: Callable[[], date] = date.today):
        self.root = Path(root) if root else default_root()
        self.history = self.root / HISTORY
        self.today = today
        self.lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)

    # --- projects --------------------------------------------------------------

    def projects(self) -> list[str]:
        codes = {INBOX}
        for p in self.root.iterdir():
            m = TODOS_RE.match(p.name) or NOTES_RE.match(p.name)
            if m:
                codes.add(m["code"])
        return sorted(codes)

    def exists(self, code: str) -> bool:
        return code in self.projects()

    def create_project(self, code: str) -> None:
        validate_code(code)
        with self.lock:
            if self._active_files(code):
                raise ProjectExists(f"project {code!r} already exists")
            atomic_write(self._todos_path(code, self.today()), "")

    def _require(self, code: str) -> None:
        validate_code(code)
        if code != INBOX and not self.exists(code):
            raise UnknownProject(f"unknown project {code!r}")

    # --- todos -----------------------------------------------------------------

    def _todos_path(self, code: str, d: date) -> Path:
        return self.root / f"{code}.todos.{_stamp(d)}.md"

    def _active_files(self, code: str) -> list[Path]:
        """All non-history todo files for a project, oldest first."""
        files = [
            p for p in self.root.iterdir()
            if (m := TODOS_RE.match(p.name)) and m["code"] == code
        ]
        return sorted(files, key=lambda p: p.name)

    def _to_history(self, path: Path) -> None:
        self.history.mkdir(exist_ok=True)
        dest = self.history / path.name
        n = 1
        while dest.exists():
            dest = self.history / f"{path.stem}.{n}.md"
            n += 1
        os.replace(path, dest)

    def todos_path(self, code: str) -> Path:
        """Path of today's todo file, rolling over first if needed."""
        self._require(code)
        with self.lock:
            today_path = self._todos_path(code, self.today())
            files = self._active_files(code)
            stale = [p for p in files if p != today_path]
            if not stale:
                if not today_path.exists():
                    atomic_write(today_path, "")
                return today_path

            # Normally there is exactly one stale file. If several exist (copied in by
            # hand, synced from another machine) merge their open work, newest first.
            carried = TodoList()
            if today_path.exists():
                carried = TodoList.parse(today_path.read_text(encoding="utf-8"))
            for p in reversed(stale):
                old = TodoList.parse(p.read_text(encoding="utf-8"))
                nxt = old.carry_over()
                carried.preamble = carried.preamble or nxt.preamble
                carried.items.extend(nxt.items)
            atomic_write(today_path, carried.dump())
            for p in stale:
                if p.stat().st_size == 0:
                    p.unlink()  # nothing worth keeping in history
                else:
                    self._to_history(p)
            return today_path

    def todos_date(self, code: str) -> str:
        """YYYYMMDD of the active todo file (after rollover)."""
        return TODOS_RE.match(self.todos_path(code).name)["date"]

    def read_todos(self, code: str) -> TodoList:
        return TodoList.parse(self.todos_path(code).read_text(encoding="utf-8"))

    def write_todos(self, code: str, todos: TodoList) -> None:
        with self.lock:
            atomic_write(self.todos_path(code), todos.dump())

    def update_todos(self, code: str, fn: Callable[[TodoList], object]):
        """Read-modify-write under the store lock. Returns whatever `fn` returns."""
        with self.lock:
            todos = self.read_todos(code)
            result = fn(todos)
            self.write_todos(code, todos)
            return result

    def rollover_all(self) -> None:
        for code in self.projects():
            if self._active_files(code) or code == INBOX:
                self.todos_path(code)

    def history_files(self, code: str) -> list[Path]:
        validate_code(code)
        if not self.history.exists():
            return []
        return sorted(
            (p for p in self.history.iterdir() if p.name.startswith(f"{code}.todos.")),
            reverse=True,
        )

    # --- notes -----------------------------------------------------------------

    def notes_path(self, code: str) -> Path:
        self._require(code)
        return self.root / f"{code}.notes.md"

    def read_notes(self, code: str) -> list[notes_mod.Note]:
        path = self.notes_path(code)
        if not path.exists():
            return []
        return notes_mod.parse(path.read_text(encoding="utf-8"))

    def append_note(
        self, code: str, body: str, title: str | None = None, when: datetime | None = None
    ) -> None:
        entry = notes_mod.format_entry(body, title, when)
        with self.lock:
            path = self.notes_path(code)
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            if not existing or existing.endswith("\n\n"):
                sep = ""
            else:
                sep = "\n" if existing.endswith("\n") else "\n\n"
            with path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(sep + entry)
