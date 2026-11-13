"""JSON-over-HTTP API on loopback, stdlib only.

Every request except GET /health needs `Authorization: Bearer <token>`; the token
lives in <root>/.token. Local web pages can reach localhost too, so the token is what
keeps them out.

    GET    /health
    GET    /projects
    POST   /projects                          {"code"}
    GET    /projects/<code>/todos
    POST   /projects/<code>/todos             {"text", "parent"?, "expect_parent"?}
    POST   /projects/<code>/todos/<path>/insert   {"text"}         new item lands at <path>
    PATCH  /projects/<code>/todos/<path>      {"text"?, "done"?, "expect"?}
    DELETE /projects/<code>/todos/<path>      {"expect"?}
    POST   /projects/<code>/todos/<path>/toggle   {"expect"?}
    POST   /projects/<code>/todos/<path>/indent   {"expect"?}
    POST   /projects/<code>/todos/<path>/outdent  {"expect"?}
    GET    /projects/<code>/notes
    POST   /projects/<code>/notes             {"body", "title"?}
    POST   /capture                           {"text", "kind"?, "project"?} or a text/plain body
    GET    /events                            server-sent events stream

Errors are {"error": message} with 400 (bad input), 401, 404 (unknown project, path or
route) or 409 (project exists / stale `expect`).
"""

from __future__ import annotations

import hmac
import json
import logging
import queue
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .capture import CaptureError
from .events import Bus
from .service import Service
from .store import ProjectError, ProjectExists, UnknownProject
from .todos import PathError, StaleError

log = logging.getLogger(__name__)
HEARTBEAT = 15.0

P = r"(?P<code>[a-z0-9][a-z0-9_-]*)"
T = r"(?P<path>\d+(?:\.\d+)*)"
ROUTES: list[tuple[str, re.Pattern, str]] = [
    (m, re.compile(f"^{p}$"), h)
    for m, p, h in [
        ("GET", "/health", "health"),
        ("GET", "/projects", "list_projects"),
        ("POST", "/projects", "create_project"),
        ("GET", f"/projects/{P}/todos", "get_todos"),
        ("POST", f"/projects/{P}/todos", "add_todo"),
        ("POST", f"/projects/{P}/todos/{T}/insert", "insert_todo"),
        ("PATCH", f"/projects/{P}/todos/{T}", "update_todo"),
        ("DELETE", f"/projects/{P}/todos/{T}", "delete_todo"),
        ("POST", f"/projects/{P}/todos/{T}/toggle", "toggle_todo"),
        ("POST", f"/projects/{P}/todos/{T}/indent", "indent_todo"),
        ("POST", f"/projects/{P}/todos/{T}/outdent", "outdent_todo"),
        ("GET", f"/projects/{P}/notes", "get_notes"),
        ("POST", f"/projects/{P}/notes", "append_note"),
        ("POST", "/capture", "capture"),
        ("GET", "/events", "events"),
    ]
]


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _status_for(exc: Exception) -> int:
    if isinstance(exc, ApiError):
        return exc.status
    if isinstance(exc, (UnknownProject, PathError)):
        return 404
    if isinstance(exc, (ProjectExists, StaleError)):
        return 409
    if isinstance(exc, (ProjectError, CaptureError, ValueError, TypeError)):
        return 400
    return 500


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, service: Service, bus: Bus, token: str):
        self.service, self.bus, self.token = service, bus, token
        super().__init__(addr, Handler)

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"


class Handler(BaseHTTPRequestHandler):
    server: ApiServer
    server_version = "pa-server"

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.address_string(), fmt % args)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_PUT(self):
        self._dispatch("PUT")

    # --- plumbing --------------------------------------------------------------

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype == "text/plain":
            return {"text": raw.decode("utf-8")}
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ApiError(400, f"invalid JSON: {e}") from None
        if not isinstance(body, dict):
            raise ApiError(400, "body must be a JSON object")
        return body

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization") or ""
        scheme, _, token = header.partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(
            token.strip().encode(), self.server.token.encode()
        )

    def _dispatch(self, method: str) -> None:
        url_path = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            allowed = False
            for m, rx, name in ROUTES:
                match = rx.match(url_path)
                if not match:
                    continue
                allowed = True
                if m != method:
                    continue
                if name != "health" and not self._authorized():
                    raise ApiError(401, "missing or invalid token")
                result = getattr(self, "h_" + name)(**match.groupdict())
                if result is not None:
                    self._send(200, result)
                return
            raise ApiError(405 if allowed else 404, f"no route for {method} {url_path}")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            status = _status_for(e)
            if status == 500:
                log.exception("error handling %s %s", method, url_path)
            self._send(status, {"error": str(e) if status != 500 else "internal error"})

    def _req(self, body: dict, key: str):
        if key not in body:
            raise ApiError(400, f"missing field {key!r}")
        return body[key]

    # --- handlers --------------------------------------------------------------

    @property
    def svc(self) -> Service:
        return self.server.service

    def h_health(self):
        return {"ok": True}

    def h_list_projects(self):
        return self.svc.list_projects()

    def h_create_project(self):
        return self.svc.create_project(self._req(self._body(), "code"))

    def h_get_todos(self, code):
        return self.svc.get_todos(code)

    def h_add_todo(self, code):
        b = self._body()
        return self.svc.add_todo(code, self._req(b, "text"), b.get("parent"), b.get("expect_parent"))

    def h_insert_todo(self, code, path):
        return self.svc.insert_todo(code, path, self._req(self._body(), "text"))

    def h_update_todo(self, code, path):
        b = self._body()
        return self.svc.update_todo(code, path, b.get("text"), b.get("done"), b.get("expect"))

    def h_delete_todo(self, code, path):
        return self.svc.delete_todo(code, path, self._body().get("expect"))

    def h_toggle_todo(self, code, path):
        return self.svc.toggle_todo(code, path, self._body().get("expect"))

    def h_indent_todo(self, code, path):
        return self.svc.indent_todo(code, path, self._body().get("expect"))

    def h_outdent_todo(self, code, path):
        return self.svc.outdent_todo(code, path, self._body().get("expect"))

    def h_get_notes(self, code):
        return self.svc.get_notes(code)

    def h_append_note(self, code):
        b = self._body()
        return self.svc.append_note(code, self._req(b, "body"), b.get("title"))

    def h_capture(self):
        b = self._body()
        return self.svc.capture(self._req(b, "text"), b.get("kind"), b.get("project"))

    def h_events(self):
        q = self.server.bus.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = q.get(timeout=HEARTBEAT)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                else:
                    if event is None:
                        return None
                    self.wfile.write(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode())
                self.wfile.flush()
        finally:
            self.server.bus.unsubscribe(q)
