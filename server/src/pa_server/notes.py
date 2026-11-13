"""Notes: one append-only markdown log per project, one `## <timestamp>` heading per entry.

    ## 2026-11-13 14:32
    body...

    ## 2026-11-13 16:05 - optional title
    body...
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

HEADING_RE = re.compile(
    r"^## (?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2})(?:\s+[-—]\s+(?P<title>.*))?\s*$"
)
TS_FORMAT = "%Y-%m-%d %H:%M"


@dataclass
class Note:
    timestamp: str
    title: str | None
    body: str
    line: int  # 1-based line of the heading, for `$EDITOR +line`


def parse(text: str) -> list[Note]:
    notes: list[Note] = []
    body: list[str] = []

    def close() -> None:
        if notes:
            notes[-1].body = "\n".join(body).strip("\n")

    for lineno, line in enumerate(text.splitlines(), 1):
        m = HEADING_RE.match(line)
        if m:
            close()
            body = []
            notes.append(Note(m["ts"], m["title"] or None, "", lineno))
        elif notes:
            body.append(line)
    close()
    return notes


def format_entry(body: str, title: str | None = None, when: datetime | None = None) -> str:
    ts = (when or datetime.now()).strftime(TS_FORMAT)
    heading = f"## {ts}" + (f" - {title.strip()}" if title and title.strip() else "")
    return f"{heading}\n{body.strip()}\n"
