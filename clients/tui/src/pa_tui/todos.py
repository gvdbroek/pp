"""pa-todos: today's todo list for one project.

    j/k gg/G  move              x/space  toggle done
    o / O     add below/above   a        add sub-item
    i / cw    edit text         dd       delete
    >> / <<   indent/outdent    e        open file in $EDITOR at this item
    p         switch project    r        reload        ?  keymap    q  quit
"""

from __future__ import annotations

import argparse
import curses
import sys
from pathlib import Path

from . import ui
from .app import App, run_app


def flatten(data: dict) -> list[dict]:
    """Todo tree → display rows in file order, each with the line it sits on in the file
    (for $EDITOR +line)."""
    out: list[dict] = []
    line = 1 + len(data.get("preamble") or [])

    def walk(items: list[dict], depth: int) -> None:
        nonlocal line
        for it in items:
            out.append({"path": it["path"], "depth": depth, "text": it["text"],
                        "done": it["done"], "line": line})
            line += 1 + len(it.get("extra") or [])
            walk(it["children"], depth + 1)

    walk(data.get("items") or [], 0)
    return out


def next_sibling(path: str) -> str:
    parts = path.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


class TodosApp(App):
    kind = "todos"
    hints = "x toggle  o/O add  a sub  i edit  dd del  >>/<< indent  e $EDITOR  ? keys  q quit"
    keymap = [
        ("x / space", "toggle done"),
        ("o / O", "add todo below / above"),
        ("a", "add sub-item"),
        ("i", "edit text"),
        ("cw", "replace text"),
        ("dd", "delete"),
        (">> / <<", "indent / outdent"),
        ("e", "open file in $EDITOR at this todo"),
    ]
    empty_text = "no todos, press o to add one"

    def __init__(self, scr, api, code):
        super().__init__(scr, api, code)
        self.data: dict = {}
        self.items: list[dict] = []

    def load(self) -> None:
        self.set_data(self.api.request("GET", f"/projects/{self.code}/todos"))

    def set_data(self, data: dict, select: str | None = None) -> None:
        cur = self.current()
        keep = select or (cur["path"] if cur else None)
        self.data, self.items = data, flatten(data)
        paths = [r["path"] for r in self.items]
        if keep in paths:
            self.cursor = paths.index(keep)
        self.clamp()

    def current(self) -> dict | None:
        return self.items[self.cursor] if 0 <= self.cursor < len(self.items) else None

    def count(self) -> int:
        return len(self.items)

    def subtitle(self) -> str:
        d = self.data.get("date") or ""
        return f" · {d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else ""

    def rows(self) -> list[tuple[str, int]]:
        return [
            (f" {'  ' * r['depth']}{'[x]' if r['done'] else '[ ]'} {r['text']}",
             curses.A_DIM if r["done"] else 0)
            for r in self.items
        ]

    def mutate(self, method: str, suffix: str, body: dict | None = None) -> bool:
        def go():
            resp = self.api.request(method, f"/projects/{self.code}/todos{suffix}", body)
            self.set_data(resp["todos"], resp["path"])

        return self.guard(go)

    def ask(self, label: str, initial: str = "") -> str | None:
        text = ui.prompt(self.scr, label, initial)
        return text.strip() if text and text.strip() else None

    def handle(self, key: str) -> None:
        cur = self.current()
        if key in ("o", "O", "a"):
            label = {"o": "add below: ", "O": "add above: ", "a": "add sub-item: "}[key]
            text = self.ask(label)
            if not text:
                return
            if cur is None:
                self.mutate("POST", "", {"text": text})
            elif key == "a":
                self.mutate("POST", "", {"text": text, "parent": cur["path"],
                                         "expect_parent": cur["text"]})
            else:
                target = next_sibling(cur["path"]) if key == "o" else cur["path"]
                self.mutate("POST", f"/{target}/insert", {"text": text})
            return
        if key == "e":
            line = cur["line"] if cur else None
            self.edit_file(self.api.root / f"{self.code}.todos.{self.data.get('date')}.md", line)
            return
        if cur is None:
            return
        expect = {"expect": cur["text"]}
        if key in ("x", " "):
            self.mutate("POST", f"/{cur['path']}/toggle", expect)
        elif key == "dd":
            if self.mutate("DELETE", f"/{cur['path']}", expect):
                self.notify(f"deleted: {cur['text']}")
        elif key in ("i", "cw"):
            text = self.ask("edit: ", "" if key == "cw" else cur["text"])
            if text and text != cur["text"]:
                self.mutate("PATCH", f"/{cur['path']}", {"text": text, **expect})
        elif key == ">>":
            self.mutate("POST", f"/{cur['path']}/indent", expect)
        elif key == "<<":
            self.mutate("POST", f"/{cur['path']}/outdent", expect)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pa-todos", description="pa todo list (vim keys)")
    ap.add_argument("project", nargs="?", help="project code (default: pick one)")
    ap.add_argument("--root", type=Path, default=None, help="data folder (default $PA_HOME or ~/pa)")
    args = ap.parse_args(argv)
    return run_app(TodosApp, "pa-todos", args.project, args.root)


if __name__ == "__main__":
    sys.exit(main())
