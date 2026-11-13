"""Todo list model: parse/serialize markdown checklists, path addressing, rollover pruning.

A todo file contains nothing but checklist items. Anything else is tolerated so that
hand edits in $EDITOR never lose data: non-item lines are kept as `extra` lines on the
preceding item (or as a preamble before the first item). Blank lines are dropped and
indentation is normalised to two spaces per level on write.

Items are addressed by 1-based dotted paths: "2" is the second top-level item,
"2.1" its first child.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ITEM_RE = re.compile(r"^(?P<indent>[ \t]*)[-*+] \[(?P<mark>[ xX])\] ?(?P<text>.*)$")
INDENT = "  "


class PathError(LookupError):
    """A todo path does not exist in the list."""


class StaleError(ValueError):
    """The todo at a path does not have the text the caller expected."""


@dataclass
class Todo:
    text: str
    done: bool = False
    children: list[Todo] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)

    def has_open(self) -> bool:
        """True if this item or anything beneath it is still unchecked."""
        return not self.done or any(c.has_open() for c in self.children)


@dataclass
class TodoList:
    items: list[Todo] = field(default_factory=list)
    preamble: list[str] = field(default_factory=list)

    # --- parsing / serialising -------------------------------------------------

    @classmethod
    def parse(cls, text: str) -> TodoList:
        result = cls()
        stack: list[tuple[int, Todo]] = []  # (indent width, item)
        for line in text.splitlines():
            m = ITEM_RE.match(line)
            if m is None:
                stripped = line.strip()
                if not stripped:
                    continue
                if stack:
                    stack[-1][1].extra.append(stripped)
                else:
                    result.preamble.append(stripped)
                continue
            width = len(m["indent"].expandtabs(4))
            todo = Todo(text=m["text"].rstrip(), done=m["mark"] != " ")
            while stack and stack[-1][0] >= width:
                stack.pop()
            (stack[-1][1].children if stack else result.items).append(todo)
            stack.append((width, todo))
        return result

    def dump(self) -> str:
        lines = list(self.preamble)

        def walk(items: list[Todo], depth: int) -> None:
            for t in items:
                lines.append(f"{INDENT * depth}- [{'x' if t.done else ' '}] {t.text}")
                lines.extend(f"{INDENT * (depth + 1)}{e}" for e in t.extra)
                walk(t.children, depth + 1)

        walk(self.items, 0)
        return "\n".join(lines) + "\n" if lines else ""

    # --- addressing ------------------------------------------------------------

    @staticmethod
    def _split(path: str) -> list[int]:
        try:
            parts = [int(p) for p in str(path).split(".")]
        except ValueError:
            raise PathError(f"invalid path {path!r}") from None
        if not parts or any(p < 1 for p in parts):
            raise PathError(f"invalid path {path!r}")
        return parts

    def _locate(self, path: str) -> tuple[list[Todo], int]:
        """Return (containing list, 0-based index) for an existing item."""
        siblings = self.items
        parts = self._split(path)
        for depth, n in enumerate(parts):
            if n > len(siblings):
                raise PathError(f"no todo at {path!r}")
            if depth == len(parts) - 1:
                return siblings, n - 1
            siblings = siblings[n - 1].children
        raise AssertionError("unreachable")

    def get(self, path: str, expect: str | None = None) -> Todo:
        siblings, i = self._locate(path)
        todo = siblings[i]
        if expect is not None and todo.text != expect:
            raise StaleError(f"todo at {path!r} is {todo.text!r}, expected {expect!r}")
        return todo

    def walk(self):
        """Yield (path, depth, todo) in document order."""

        def rec(items: list[Todo], prefix: str, depth: int):
            for i, t in enumerate(items, 1):
                p = f"{prefix}{i}"
                yield p, depth, t
                yield from rec(t.children, p + ".", depth + 1)

        yield from rec(self.items, "", 0)

    # --- mutations -------------------------------------------------------------

    def add(self, text: str, parent: str | None = None, expect_parent: str | None = None) -> str:
        """Append a todo at the end of the top level, or under `parent`. Returns its path."""
        if parent is None:
            self.items.append(Todo(text))
            return str(len(self.items))
        p = self.get(parent, expect_parent)
        p.children.append(Todo(text))
        return f"{parent}.{len(p.children)}"

    def insert(self, path: str, text: str) -> str:
        """Insert a new todo so that it ends up at `path` (may be one past the end)."""
        parts = self._split(path)
        siblings = self.items if len(parts) == 1 else self.get(".".join(map(str, parts[:-1]))).children
        idx = parts[-1] - 1
        if idx > len(siblings):
            raise PathError(f"cannot insert at {path!r}")
        siblings.insert(idx, Todo(text))
        return path

    def set_done(self, path: str, done: bool, expect: str | None = None) -> Todo:
        todo = self.get(path, expect)
        todo.done = done
        return todo

    def toggle(self, path: str, expect: str | None = None) -> Todo:
        todo = self.get(path, expect)
        todo.done = not todo.done
        return todo

    def edit(self, path: str, text: str, expect: str | None = None) -> Todo:
        todo = self.get(path, expect)
        todo.text = text
        return todo

    def delete(self, path: str, expect: str | None = None) -> Todo:
        self.get(path, expect)
        siblings, i = self._locate(path)
        return siblings.pop(i)

    def indent(self, path: str, expect: str | None = None) -> str:
        """Make the item a child of its previous sibling. Returns its new path."""
        self.get(path, expect)
        siblings, i = self._locate(path)
        if i == 0:
            raise PathError(f"todo at {path!r} has no previous sibling to nest under")
        todo = siblings.pop(i)
        siblings[i - 1].children.append(todo)
        parts = self._split(path)
        parts[-1] -= 1
        return ".".join(map(str, parts)) + f".{len(siblings[i - 1].children)}"

    def outdent(self, path: str, expect: str | None = None) -> str:
        """Move the item out of its parent, directly after it. Returns its new path."""
        self.get(path, expect)
        parts = self._split(path)
        if len(parts) == 1:
            raise PathError(f"todo at {path!r} is already top level")
        parent_path = ".".join(map(str, parts[:-1]))
        grand, pi = self._locate(parent_path)
        siblings, i = self._locate(path)
        todo = siblings.pop(i)
        grand.insert(pi + 1, todo)
        return ".".join(map(str, parts[:-2] + [parts[-2] + 1]))

    # --- rollover --------------------------------------------------------------

    def carry_over(self) -> TodoList:
        """The list for the next day: keep items that are (or contain) open work,
        drop fully-checked subtrees. A checked parent survives if a child is open."""

        def prune(items: list[Todo]) -> list[Todo]:
            return [
                Todo(t.text, t.done, prune(t.children), list(t.extra))
                for t in items
                if t.has_open()
            ]

        return TodoList(prune(self.items), list(self.preamble))
