import tempfile
import unittest
from pathlib import Path

from pa_server import capture
from pa_server.capture import CaptureError
from pa_server.store import Store


class Parse(unittest.TestCase):
    def test_defaults(self):
        c = capture.parse("buy milk")
        self.assertEqual((c.kind, c.project, c.lines), ("todo", None, ["buy milk"]))
        c = capture.parse("line one\nline two")
        self.assertEqual(c.kind, "note")

    def test_header(self):
        c = capture.parse("@Work todo: fix it")
        self.assertEqual((c.kind, c.project, c.lines), ("todo", "work", ["fix it"]))
        c = capture.parse("@pa n: Title\nbody")
        self.assertEqual((c.kind, c.project, c.lines), ("note", "pa", ["Title", "body"]))
        c = capture.parse("note: just a line")
        self.assertEqual((c.kind, c.lines), ("note", ["just a line"]))

    def test_explicit_kind_and_project_are_defaults(self):
        c = capture.parse("a\nb", kind="todo", project="pa")
        self.assertEqual((c.kind, c.project), ("todo", "pa"))
        c = capture.parse("@x note: hi", kind="todo", project="pa")
        self.assertEqual((c.kind, c.project), ("note", "x"))

    def test_empty(self):
        for text in ["", "   \n\n", "@pa", "@pa todo:"]:
            with self.assertRaises(CaptureError, msg=repr(text)):
                capture.parse(text)

    def test_to_todos_handles_bullets_and_nesting(self):
        tl = capture.to_todos(["parent", "  - [ ] child", "- other", "", "  * deep"])
        self.assertEqual(tl.dump(), "- [ ] parent\n  - [ ] child\n- [ ] other\n  - [ ] deep\n")


class Apply(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.store.create_project("pa")

    def tearDown(self):
        self.tmp.cleanup()

    def test_todo(self):
        r = capture.apply(self.store, capture.parse("@pa todo: a\nb\n  c"))
        self.assertEqual(r, {"kind": "todo", "project": "pa", "rerouted": False, "paths": ["1", "2"]})
        self.assertEqual(self.store.read_todos("pa").dump(), "- [ ] a\n- [ ] b\n  - [ ] c\n")

    def test_note_with_and_without_title(self):
        capture.apply(self.store, capture.parse("@pa note: Title\nbody"))
        capture.apply(self.store, capture.parse("@pa note: only body"))
        got = [(n.title, n.body) for n in self.store.read_notes("pa")]
        self.assertEqual(got, [("Title", "body"), (None, "only body")])

    def test_unknown_project_goes_to_inbox(self):
        r = capture.apply(self.store, capture.parse("@nope call bob"))
        self.assertEqual((r["project"], r["rerouted"]), ("inbox", True))
        self.assertEqual(self.store.read_todos("inbox").get("1").text, "@nope call bob")


if __name__ == "__main__":
    unittest.main()
