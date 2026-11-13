"""pa-server command line.

    pa-server serve [--root DIR] [--host 127.0.0.1] [--port 47100] [-v]
    pa-server token [--root DIR]

`serve` writes <root>/.server ({"url", "pid"}) so clients can find it, and creates
<root>/.token once (kept across restarts so hotkey scripts can hard-code it).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import signal
import sys
import threading
from pathlib import Path

from .events import Bus, Watcher
from .httpapi import ApiServer
from .service import Service
from .store import Store, atomic_write, default_root

DEFAULT_PORT = 47100
log = logging.getLogger("pa_server")


def load_token(root: Path) -> str:
    path = root / ".token"
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    atomic_write(path, token + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows: the user profile folder is already private
    return token


def serve(root: Path, host: str, port: int) -> int:
    store = Store(root)
    bus = Bus()
    token = load_token(store.root)
    try:
        server = ApiServer((host, port), Service(store), bus, token)
    except OSError as e:
        log.error("cannot listen on %s:%s: %s", host, port, e)
        return 1
    watcher = Watcher(store, bus)
    watcher.start()
    info = store.root / ".server"
    atomic_write(info, json.dumps({"url": server.url, "pid": os.getpid()}) + "\n")
    log.info("pa-server on %s, root %s", server.url, store.root)

    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        bus.publish(None)
        server.server_close()
        info.unlink(missing_ok=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pa-server")
    ap.add_argument("--root", type=Path, default=None, help="data folder (default $PA_HOME or ~/pa)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the server")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=int(os.environ.get("PA_PORT", DEFAULT_PORT)))
    s.add_argument("-v", "--verbose", action="store_true")
    sub.add_parser("token", help="print the API token")
    args = ap.parse_args(argv)

    root = args.root or default_root()
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.cmd == "token":
        root.mkdir(parents=True, exist_ok=True)
        print(load_token(root))
        return 0
    return serve(root, args.host, args.port)


if __name__ == "__main__":
    sys.exit(main())
