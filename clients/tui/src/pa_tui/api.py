"""HTTP client for the pa server (stdlib only).

Finds the server through <root>/.server and <root>/.token, where root is $PA_HOME or
~/pa, the same folder the server uses.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

# Never send localhost traffic through an HTTP proxy from the environment.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def default_root() -> Path:
    return Path(os.environ.get("PA_HOME") or Path.home() / "pa")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def parse_sse_line(line: bytes) -> dict | None:
    """Return the event for a `data:` line of a server-sent events stream, else None."""
    if not line.startswith(b"data:"):
        return None
    try:
        return json.loads(line[5:].strip())
    except json.JSONDecodeError:
        return None


class Api:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else default_root()
        self.url = ""
        self.token = ""
        self.discover()

    def discover(self) -> None:
        info = self.root / ".server"
        try:
            self.url = json.loads(info.read_text(encoding="utf-8"))["url"]
            self.token = (self.root / ".token").read_text(encoding="utf-8").strip()
        except (OSError, ValueError, KeyError):
            raise ApiError(0, f"pa server is not running (no {info})") from None

    def _request(self, method: str, path: str, body: dict | None = None, timeout: float = 10):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        return _opener.open(req, timeout=timeout)

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            with self._request(method, path, body) as r:
                return json.loads(r.read())
        except HTTPError as e:
            try:
                message = json.loads(e.read()).get("error") or str(e)
            except ValueError:
                message = str(e)
            raise ApiError(e.code, message) from None
        except (URLError, OSError) as e:
            raise ApiError(0, f"cannot reach pa server: {getattr(e, 'reason', e)}") from None

    def projects(self) -> list[str]:
        return self.request("GET", "/projects")["projects"]

    def listen(self, out: queue.Queue, stop: threading.Event, retry: float = 2.0) -> None:
        """Forward server events to `out` until `stop` is set; reconnects on failure.
        Puts {"type": "connected"} on every (re)connect, since events may have been
        missed while disconnected."""
        while not stop.is_set():
            try:
                self.discover()  # the server may have restarted on another port
                with self._request("GET", "/events", timeout=30) as r:
                    out.put({"type": "connected"})
                    for line in r:
                        if stop.is_set():
                            return
                        if (event := parse_sse_line(line)) is not None:
                            out.put(event)
            except Exception:
                pass
            stop.wait(retry)
