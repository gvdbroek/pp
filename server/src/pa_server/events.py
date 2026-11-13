"""Change notifications and background housekeeping.

The watcher polls the root folder with stat() only (no file reads, so no antivirus
scans) and publishes a `changed` event per project/kind whenever a file appears,
disappears or changes. It sees the server's own writes and outside edits alike, so it
is the single source of change events. It also runs the midnight rollover.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
from datetime import date
from pathlib import Path

from .store import NOTES_RE, TODOS_RE, Store

log = logging.getLogger(__name__)


class Bus:
    def __init__(self) -> None:
        self._subs: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subs.discard(q)

    def publish(self, event: dict | None) -> None:
        """Send an event to every subscriber. `None` tells streams to close."""
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                log.warning("dropping event for slow subscriber")


def _scan(root: Path) -> dict[str, tuple[int, int]]:
    out = {}
    with os.scandir(root) as it:
        for e in it:
            if e.is_file() and not e.name.startswith("."):
                st = e.stat()
                out[e.name] = (st.st_mtime_ns, st.st_size)
    return out


def _classify(name: str) -> tuple[str, str] | None:
    if m := TODOS_RE.match(name):
        return m["code"], "todos"
    if m := NOTES_RE.match(name):
        return m["code"], "notes"
    return None


class Watcher(threading.Thread):
    def __init__(self, store: Store, bus: Bus, interval: float = 0.5):
        super().__init__(name="pa-watcher", daemon=True)
        self.store, self.bus, self.interval = store, bus, interval
        self._halt = threading.Event()
        self._day: date | None = None
        self._snap: dict[str, tuple[int, int]] = {}

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        self._snap = _scan(self.store.root)
        while not self._halt.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("watcher tick failed")
            self._halt.wait(self.interval)

    def tick(self) -> None:
        today = self.store.today()
        if today != self._day:
            self._day = today
            self.store.rollover_all()
        self.diff()

    def diff(self) -> None:
        new = _scan(self.store.root)
        changed = {n for n in new.keys() | self._snap.keys() if new.get(n) != self._snap.get(n)}
        self._snap = new
        for code, kind in sorted({c for n in changed if (c := _classify(n))}):
            self.bus.publish({"type": "changed", "project": code, "kind": kind})
