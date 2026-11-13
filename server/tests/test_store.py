import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from pa_server import notes
from pa_server.store import ProjectError, Store


class Clock:
    def __init__(self, d: date):
        self.d = d

    def __call__(self) -> date:
        return self.d


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.clock = Clock(date(2026, 11, 13))
        self.store = Store(self.root, today=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, d: Path | None = None) -> list[str]:
        return sorted(p.name for p in (d or self.root).iterdir() if p.is_file())

    def test_projects_and_create(self):
        self.assertEqual(self.store.projects(), ["inbox"])
        self.store.create_project("pa")
        self.assertEqual(self.store.projects(), ["inbox", "pa"])
        self.assertEqual(self.names(), ["pa.todos.20261113.md"])
        with self.assertRaises(ProjectError):
            self.store.create_project("pa")
        for bad in ["PA", "a.b", "", "-x"]:
            with self.assertRaises(ProjectError):
                self.store.create_project(bad)

    def test_unknown_project(self):
        with self.assertRaises(ProjectError):
            self.store.read_todos("nope")

    def test_inbox_always_available(self):
        self.store.update_todos("inbox", lambda t: t.add("capture"))
        self.assertEqual(self.store.read_todos("inbox").get("1").text, "capture")

    def test_rollover(self):
        self.store.create_project("pa")
        self.store.update_todos("pa", lambda t: (t.add("open"), t.add("done"), t.toggle("2")))
        self.clock.d = date(2026, 12, 20)  # untouched for weeks
        tl = self.store.read_todos("pa")
        self.assertEqual(tl.dump(), "- [ ] open\n")
        self.assertEqual(self.names(), ["pa.todos.20261220.md"])
        self.assertEqual(self.names(self.root / "history"), ["pa.todos.20261113.md"])
        self.assertEqual(
            (self.root / "history" / "pa.todos.20261113.md").read_text(),
            "- [ ] open\n- [x] done\n",
        )
        self.assertEqual([p.name for p in self.store.history_files("pa")], ["pa.todos.20261113.md"])

    def test_empty_file_is_not_kept_in_history(self):
        self.store.create_project("pa")
        self.clock.d = date(2026, 11, 14)
        self.store.read_todos("pa")
        self.assertFalse((self.root / "history").exists())
        self.assertEqual(self.names(), ["pa.todos.20261114.md"])

    def test_rollover_merges_multiple_stale_files(self):
        (self.root / "pa.todos.20261101.md").write_text("- [ ] old\n")
        (self.root / "pa.todos.20261110.md").write_text("- [ ] newer\n- [x] gone\n")
        self.assertEqual(self.store.read_todos("pa").dump(), "- [ ] newer\n- [ ] old\n")
        self.assertEqual(
            self.names(self.root / "history"), ["pa.todos.20261101.md", "pa.todos.20261110.md"]
        )

    def test_history_name_collision(self):
        (self.root / "history").mkdir()
        (self.root / "history" / "pa.todos.20261112.md").write_text("- [ ] earlier\n")
        (self.root / "pa.todos.20261112.md").write_text("- [ ] x\n")
        self.store.read_todos("pa")
        self.assertEqual(
            self.names(self.root / "history"), ["pa.todos.20261112.1.md", "pa.todos.20261112.md"]
        )

    def test_notes(self):
        self.store.create_project("pa")
        self.assertEqual(self.store.read_notes("pa"), [])
        self.store.append_note("pa", "first body", when=datetime(2026, 11, 13, 9, 5))
        self.store.append_note("pa", "second\nbody", title="Idea", when=datetime(2026, 11, 13, 10, 0))
        text = (self.root / "pa.notes.md").read_text()
        self.assertEqual(
            text, "## 2026-11-13 09:05\nfirst body\n\n## 2026-11-13 10:00 - Idea\nsecond\nbody\n"
        )
        got = self.store.read_notes("pa")
        self.assertEqual([(n.timestamp, n.title, n.body, n.line) for n in got], [
            ("2026-11-13 09:05", None, "first body", 1),
            ("2026-11-13 10:00", "Idea", "second\nbody", 4),
        ])

    def test_notes_tolerate_hand_edits(self):
        text = "stray intro\n## 2026-01-01 00:00 — em dash title\nbody\n## not a note\nmore\n"
        got = notes.parse(text)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].title, "em dash title")
        self.assertEqual(got[0].body, "body\n## not a note\nmore")


if __name__ == "__main__":
    unittest.main()
