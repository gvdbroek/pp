"""Operations exposed to clients. HTTP and MCP are thin adapters over this class.

Every todo mutation returns the affected path plus the full updated list, so clients
can re-render without a second request.
"""

from __future__ import annotations

from dataclasses import asdict

from . import capture
from .store import Store
from .todos import Todo, TodoList


def todo_json(todo: Todo, path: str) -> dict:
    return {
        "path": path,
        "text": todo.text,
        "done": todo.done,
        "extra": todo.extra,
        "children": [todo_json(c, f"{path}.{i}") for i, c in enumerate(todo.children, 1)],
    }


class Service:
    def __init__(self, store: Store):
        self.store = store

    # --- projects --------------------------------------------------------------

    def list_projects(self) -> dict:
        return {"projects": self.store.projects()}

    def create_project(self, code: str) -> dict:
        self.store.create_project(code)
        return {"project": code}

    # --- todos -----------------------------------------------------------------

    def _todos_json(self, code: str, tl: TodoList) -> dict:
        return {
            "project": code,
            "date": self.store.todos_date(code),
            "preamble": tl.preamble,
            "items": [todo_json(t, str(i)) for i, t in enumerate(tl.items, 1)],
        }

    def get_todos(self, code: str) -> dict:
        with self.store.lock:
            return self._todos_json(code, self.store.read_todos(code))

    def _mutate(self, code: str, fn) -> dict:
        with self.store.lock:
            holder = {}

            def run(tl: TodoList):
                holder["path"] = fn(tl)
                holder["tl"] = tl

            self.store.update_todos(code, run)
            return {"path": holder["path"], "todos": self._todos_json(code, holder["tl"])}

    def add_todo(self, code: str, text: str, parent: str | None = None,
                 expect_parent: str | None = None) -> dict:
        return self._mutate(code, lambda t: t.add(text, parent, expect_parent))

    def insert_todo(self, code: str, path: str, text: str) -> dict:
        return self._mutate(code, lambda t: t.insert(path, text))

    def update_todo(self, code: str, path: str, text: str | None = None,
                    done: bool | None = None, expect: str | None = None) -> dict:
        def fn(t: TodoList) -> str:
            t.get(path, expect)
            if text is not None:
                t.edit(path, text)
            if done is not None:
                t.set_done(path, bool(done))
            return path

        return self._mutate(code, fn)

    def toggle_todo(self, code: str, path: str, expect: str | None = None) -> dict:
        return self._mutate(code, lambda t: (t.toggle(path, expect), path)[1])

    def delete_todo(self, code: str, path: str, expect: str | None = None) -> dict:
        return self._mutate(code, lambda t: (t.delete(path, expect), path)[1])

    def indent_todo(self, code: str, path: str, expect: str | None = None) -> dict:
        return self._mutate(code, lambda t: t.indent(path, expect))

    def outdent_todo(self, code: str, path: str, expect: str | None = None) -> dict:
        return self._mutate(code, lambda t: t.outdent(path, expect))

    # --- notes -----------------------------------------------------------------

    def get_notes(self, code: str) -> dict:
        return {
            "project": code,
            "file": self.store.notes_path(code).name,
            "notes": [asdict(n) for n in self.store.read_notes(code)],
        }

    def append_note(self, code: str, body: str, title: str | None = None) -> dict:
        if not body or not body.strip():
            raise capture.CaptureError("empty note")
        self.store.append_note(code, body, title)
        return {"project": code}

    # --- capture ---------------------------------------------------------------

    def capture(self, text: str, kind: str | None = None, project: str | None = None) -> dict:
        return capture.apply(self.store, capture.parse(text, kind, project))
