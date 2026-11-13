import queue
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from pa_tui import ui
from pa_tui.api import Api, ApiError, parse_sse_line
from pa_tui.notes import split_note
from pa_tui.todos import flatten, next_sibling

# The integration tests run a real server from the sibling sub-project.
SERVER_SRC = Path(__file__).resolve().parents[3] / "server" / "src"
sys.path.insert(0, str(SERVER_SRC))
try:
    from pa_server.events import Bus, Watcher
    from pa_server.httpapi import ApiServer
    from pa_server.service import Service
    from pa_server.store import Store
except ImportError:  # pragma: no cover
    ApiServer = None


class Helpers(unittest.TestCase):
    def test_flatten_paths_depths_and_file_lines(self):
        data = {
            "preamble": ["# heading"],
            "items": [
                {"path": "1", "text": "a", "done": False, "extra": ["detail"], "children": [
                    {"path": "1.1", "text": "b", "done": True, "extra": [], "children": []},
                ]},
                {"path": "2", "text": "c", "done": False, "extra": [], "children": []},
            ],
        }
        rows = [(r["path"], r["depth"], r["line"]) for r in flatten(data)]
        # line 1: heading, 2: a, 3: detail, 4: b, 5: c
        self.assertEqual(rows, [("1", 0, 2), ("1.1", 1, 4), ("2", 0, 5)])

    def test_next_sibling(self):
        self.assertEqual(next_sibling("3"), "4")
        self.assertEqual(next_sibling("2.9"), "2.10")

    def test_split_note(self):
        self.assertIsNone(split_note("  \n\n"))
        self.assertEqual(split_note("one line"), (None, "one line"))
        self.assertEqual(split_note("Title\n\nbody\nmore"), ("Title", "body\nmore"))
        self.assertEqual(split_note("Title\n   \n"), (None, "Title"))

    def test_editor_cmd(self):
        self.assertEqual(ui.editor_cmd("f.md", 3, {"EDITOR": "nvim"}), ["nvim", "+3", "f.md"])
        self.assertEqual(ui.editor_cmd("f.md", 3, {"VISUAL": "hx", "EDITOR": "vi"}), ["hx", "f.md:3"])
        self.assertEqual(ui.editor_cmd("f.md", 3, {"EDITOR": "code --wait"}), ["code", "--wait", "f.md"])
        self.assertEqual(ui.editor_cmd("f.md", None, {"EDITOR": "vim"}), ["vim", "f.md"])

    def test_parse_sse_line(self):
        self.assertEqual(parse_sse_line(b'data: {"type": "changed"}\n'), {"type": "changed"})
        self.assertIsNone(parse_sse_line(b": ping\n"))
        self.assertIsNone(parse_sse_line(b"event: changed\n"))
        self.assertIsNone(parse_sse_line(b"data: not json\n"))

    def test_no_server(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ApiError):
                Api(Path(d))


@unittest.skipIf(ApiServer is None, "server sub-project not importable")
class AgainstServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.create_project("pa")
        self.bus = Bus()
        self.server = ApiServer(("127.0.0.1", 0), Service(self.store), self.bus, "tok")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.watcher = Watcher(self.store, self.bus, interval=0.05)
        self.watcher.start()
        (self.root / ".token").write_text("tok\n")
        (self.root / ".server").write_text(f'{{"url": "{self.server.url}"}}')
        self.api = Api(self.root)

    def tearDown(self):
        self.watcher.stop()
        self.bus.publish(None)
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def test_requests_and_errors(self):
        self.assertIn("pa", self.api.projects())
        r = self.api.request("POST", "/projects/pa/todos", {"text": "x"})
        self.assertEqual(r["path"], "1")
        with self.assertRaises(ApiError) as cm:
            self.api.request("POST", "/projects/pa/todos/1/toggle", {"expect": "wrong"})
        self.assertEqual(cm.exception.status, 409)
        r = self.api.request("DELETE", "/projects/pa/todos/1", {"expect": "x"})
        self.assertEqual(r["todos"]["items"], [])

    def test_listen_receives_changes(self):
        q, stop = queue.Queue(), threading.Event()
        threading.Thread(target=self.api.listen, args=(q, stop), daemon=True).start()
        self.assertEqual(q.get(timeout=5), {"type": "connected"})
        self.store.update_todos("pa", lambda t: t.add("from elsewhere"))
        want = {"type": "changed", "project": "pa", "kind": "todos"}
        # other events may arrive first (e.g. the watcher creating today's inbox file)
        seen = []
        while want not in seen:
            seen.append(q.get(timeout=5))
        stop.set()


if __name__ == "__main__":
    unittest.main()
