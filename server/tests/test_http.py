import json
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from urllib.error import HTTPError

from pa_server.events import Bus, Watcher
from pa_server.httpapi import ApiServer
from pa_server.service import Service
from pa_server.store import Store

TOKEN = "test-token"


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.bus = Bus()
        self.server = ApiServer(("127.0.0.1", 0), Service(self.store), self.bus, TOKEN)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.watcher = None

    def tearDown(self):
        if self.watcher and self.watcher.is_alive():
            self.watcher.stop()
            self.watcher.join(2)
        self.bus.publish(None)
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, token=TOKEN, raw=None, ctype="application/json"):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.server.url + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", ctype)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except HTTPError as e:
            return e.code, json.loads(e.read())

    def test_auth(self):
        self.assertEqual(self.call("GET", "/health", token=None), (200, {"ok": True}))
        self.assertEqual(self.call("GET", "/projects", token=None)[0], 401)
        self.assertEqual(self.call("GET", "/projects", token="wrong")[0], 401)

    def test_routing_errors(self):
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("PUT", "/projects")[0], 405)
        self.assertEqual(self.call("DELETE", "/projects")[0], 405)
        self.assertEqual(self.call("POST", "/projects", raw=b"{bad")[0], 400)
        self.assertEqual(self.call("POST", "/projects", {})[0], 400)

    def test_todo_flow(self):
        self.assertEqual(self.call("POST", "/projects", {"code": "pa"}), (200, {"project": "pa"}))
        self.assertEqual(self.call("POST", "/projects", {"code": "pa"})[0], 409)
        self.assertEqual(self.call("POST", "/projects", {"code": "Bad.Code"})[0], 400)
        self.assertIn("pa", self.call("GET", "/projects")[1]["projects"])

        s, r = self.call("POST", "/projects/pa/todos", {"text": "parent"})
        self.assertEqual((s, r["path"]), (200, "1"))
        s, r = self.call("POST", "/projects/pa/todos", {"text": "child", "parent": "1"})
        self.assertEqual(r["path"], "1.1")
        self.assertEqual(r["todos"]["items"][0]["children"][0]["path"], "1.1")

        self.assertEqual(self.call("POST", "/projects/pa/todos/1.1/toggle", {"expect": "wrong"})[0], 409)
        s, r = self.call("POST", "/projects/pa/todos/1.1/toggle", {"expect": "child"})
        self.assertTrue(r["todos"]["items"][0]["children"][0]["done"])

        s, r = self.call("PATCH", "/projects/pa/todos/1", {"text": "renamed", "done": True})
        self.assertEqual((r["todos"]["items"][0]["text"], r["todos"]["items"][0]["done"]), ("renamed", True))

        s, r = self.call("POST", "/projects/pa/todos/1.1/outdent")
        self.assertEqual(r["path"], "2")
        s, r = self.call("POST", "/projects/pa/todos/2/indent")
        self.assertEqual(r["path"], "1.1")
        s, r = self.call("POST", "/projects/pa/todos/1/insert", {"text": "first"})
        self.assertEqual(r["todos"]["items"][0]["text"], "first")

        s, r = self.call("DELETE", "/projects/pa/todos/1", {"expect": "first"})
        self.assertEqual([i["text"] for i in r["todos"]["items"]], ["renamed"])
        self.assertEqual(self.call("DELETE", "/projects/pa/todos/9")[0], 404)
        self.assertEqual(self.call("GET", "/projects/zzz/todos")[0], 404)

        files = sorted(p.name for p in self.root.iterdir())
        self.assertEqual(len([f for f in files if f.startswith("pa.todos.")]), 1)

    def test_notes_and_capture(self):
        self.call("POST", "/projects", {"code": "pa"})
        self.assertEqual(self.call("POST", "/projects/pa/notes", {"body": " "})[0], 400)
        self.call("POST", "/projects/pa/notes", {"body": "hello", "title": "T"})
        s, r = self.call("GET", "/projects/pa/notes")
        self.assertEqual((r["notes"][0]["title"], r["notes"][0]["body"]), ("T", "hello"))

        s, r = self.call("POST", "/capture", raw=b"@pa todo: from a script", ctype="text/plain")
        self.assertEqual((s, r["project"], r["paths"]), (200, "pa", ["1"]))
        s, r = self.call("POST", "/capture", {"text": "an idea\nmore", "project": "pa"})
        self.assertEqual(r["kind"], "note")
        self.assertEqual(self.call("POST", "/capture", {"text": ""})[0], 400)

    def test_events(self):
        self.store.create_project("pa")
        self.watcher = Watcher(self.store, self.bus, interval=0.05)
        self.watcher.start()
        time.sleep(0.2)  # let the watcher take its first snapshot

        req = urllib.request.Request(self.server.url + "/events")
        req.add_header("Authorization", f"Bearer {TOKEN}")
        events = []

        def listen():
            with urllib.request.urlopen(req, timeout=5) as r:
                for line in r:
                    if line.startswith(b"data: "):
                        events.append(json.loads(line[6:]))
                        return

        t = threading.Thread(target=listen, daemon=True)
        t.start()
        time.sleep(0.2)
        # an outside edit, as if made in $EDITOR
        self.store.todos_path("pa").write_text("- [ ] edited by hand\n")
        t.join(5)
        self.assertEqual(events, [{"type": "changed", "project": "pa", "kind": "todos"}])

if __name__ == "__main__":
    unittest.main()
