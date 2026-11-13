"""Capture: a tiny plain-text format so any client (modal, script) can add
todos or notes without knowing the API.

    [@code] [todo:|note:|t:|n:] first line
    more lines...

- `@code` picks the project; default is `inbox`. Unknown projects go to `inbox` with
  the `@code` kept in the text, so nothing is lost.
- Without a keyword, a single line is a todo and multiple lines are a note.
- todo: every non-empty line is a todo. Indented lines become subtasks of the line
  above. Leading `- ` or `- [ ] ` bullets are accepted and ignored.
- note: the rest of the first line is the title, the remaining lines the body. With
  no body, the first line becomes the body and there is no title.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .store import INBOX, Store
from .todos import TodoList

HEADER_RE = re.compile(
    r"^\s*(?:@(?P<code>[a-z0-9][a-z0-9_-]*)\s*)?(?:(?P<kind>todo|note|t|n)\s*:\s*)?(?P<rest>.*)$",
    re.IGNORECASE,
)
BULLET_RE = re.compile(r"^(?P<indent>\s*)(?:[-*+]\s+(?:\[[ xX]\]\s*)?)?(?P<text>.*)$")
KINDS = {"t": "todo", "todo": "todo", "n": "note", "note": "note"}


class CaptureError(ValueError):
    pass


@dataclass
class Capture:
    kind: str  # "todo" | "note"
    project: str | None
    lines: list[str]  # first line has header removed


def parse(text: str, kind: str | None = None, project: str | None = None) -> Capture:
    """Parse capture text. Explicit `kind`/`project` (e.g. from a dedicated note modal)
    act as defaults; an inline `@code` or `note:` still wins."""
    lines = text.replace("\r\n", "\n").strip("\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or not lines[0].strip():
        raise CaptureError("empty capture")
    m = HEADER_RE.match(lines[0])
    lines[0] = m["rest"].strip()
    k = KINDS[m["kind"].lower()] if m["kind"] else kind
    if k is None:
        k = "todo" if len(lines) == 1 else "note"
    if k not in ("todo", "note"):
        raise CaptureError(f"unknown kind {k!r}")
    if not any(line.strip() for line in lines):
        raise CaptureError("empty capture")
    return Capture(k, (m["code"] or "").lower() or project, lines)


def to_todos(lines: list[str]) -> TodoList:
    md = []
    for line in lines:
        if not line.strip():
            continue
        b = BULLET_RE.match(line)
        md.append(f"{b['indent']}- [ ] {b['text'].strip()}")
    return TodoList.parse("\n".join(md))


def apply(store: Store, cap: Capture) -> dict:
    """Write a capture to the store. Returns a summary."""
    code, lines = cap.project or INBOX, list(cap.lines)
    rerouted = False
    if code != INBOX and not store.exists(code):
        lines[0] = f"@{code} {lines[0]}".rstrip()
        code, rerouted = INBOX, True

    if cap.kind == "todo":
        new = to_todos(lines)
        if not new.items:
            raise CaptureError("no todo text")

        def add(t: TodoList) -> int:
            start = len(t.items) + 1
            t.items.extend(new.items)
            return start

        first = store.update_todos(code, add)
        paths = [str(first + i) for i in range(len(new.items))]
        return {"kind": "todo", "project": code, "rerouted": rerouted, "paths": paths}

    title, body = lines[0], "\n".join(lines[1:]).strip()
    if not body:
        title, body = None, title
    store.append_note(code, body, title=title or None)
    return {"kind": "note", "project": code, "rerouted": rerouted}
