"""pa-notes: a project's note log, newest first, with a preview of the selected note.

    j/k gg/G   move               enter/e  open the notes file in $EDITOR at this note
    a          write a new note in $EDITOR (first line = title if more lines follow)
    p          switch project     r  reload     ?  keymap     q  quit
"""

from __future__ import annotations

import argparse
import curses
import os
import sys
import tempfile
import textwrap
from pathlib import Path

from . import ui
from .app import App, run_app


def split_note(text: str) -> tuple[str | None, str] | None:
    """Text from the editor → (title, body), or None if empty. Same rule as the
    server's capture format: with several lines, the first one is the title."""
    lines = text.strip().splitlines()
    if not lines:
        return None
    if len(lines) == 1:
        return None, lines[0].strip()
    body = "\n".join(lines[1:]).strip()
    return (lines[0].strip(), body) if body else (None, lines[0].strip())


class NotesApp(App):
    kind = "notes"
    hints = "enter/e open in $EDITOR  a add note  p project  ? keys  q quit"
    keymap = [
        ("enter / e", "open notes file in $EDITOR at this note"),
        ("a", "write a new note in $EDITOR (first line = title)"),
    ]
    empty_text = "no notes, press a to write one"

    def __init__(self, scr, api, code):
        super().__init__(scr, api, code)
        self.notes: list[dict] = []
        self.file = f"{code}.notes.md"

    def load(self) -> None:
        data = self.api.request("GET", f"/projects/{self.code}/notes")
        self.file = data["file"]
        self.notes = list(reversed(data["notes"]))
        self.clamp()

    def count(self) -> int:
        return len(self.notes)

    def rows(self) -> list[tuple[str, int]]:
        out = []
        for n in self.notes:
            label = n["title"] or (n["body"].strip().splitlines() or [""])[0]
            out.append((f" {n['timestamp']}  {label}", curses.A_BOLD if n["title"] else 0))
        return out

    def list_height(self, h: int) -> int:
        return max(3, (h - 2) // 2) if self.notes else h - 2

    def draw_below(self, y0: int, y1: int, w: int) -> None:
        if not self.notes or y0 >= y1:
            return
        ui.add(self.scr, y0, 0, "─" * w, curses.A_DIM)
        note = self.notes[self.cursor]
        lines: list[str] = []
        for para in note["body"].splitlines() or [""]:
            lines.extend(textwrap.wrap(para, max(10, w - 2)) or [""])
        for i, line in enumerate(lines[: max(0, y1 - y0 - 1)]):
            ui.add(self.scr, y0 + 1 + i, 1, line)

    def handle(self, key: str) -> None:
        if key in ("\n", "\r", "e"):
            line = self.notes[self.cursor]["line"] if self.notes else None
            self.edit_file(self.api.root / self.file, line)
        elif key == "a":
            self.compose()

    def compose(self) -> None:
        fd, tmp = tempfile.mkstemp(prefix="pa-note-", suffix=".md")
        os.close(fd)
        try:
            err = ui.run_editor(self.scr, ui.editor_cmd(tmp))
            text = Path(tmp).read_text(encoding="utf-8")
        finally:
            Path(tmp).unlink(missing_ok=True)
        if err:
            return self.notify(err, error=True)
        parsed = split_note(text)
        if parsed is None:
            return self.notify("empty note, nothing added")
        title, body = parsed
        if self.guard(lambda: self.api.request(
                "POST", f"/projects/{self.code}/notes", {"body": body, "title": title})):
            self.reload()
            self.cursor = 0
            self.notify("note added")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pa-notes", description="pa notes (vim keys)")
    ap.add_argument("project", nargs="?", help="project code (default: pick one)")
    ap.add_argument("--root", type=Path, default=None, help="data folder (default $PA_HOME or ~/pa)")
    args = ap.parse_args(argv)
    return run_app(NotesApp, "pa-notes", args.project, args.root)


if __name__ == "__main__":
    sys.exit(main())
