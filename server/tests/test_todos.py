import unittest

from pa_server.todos import PathError, StaleError, TodoList

SAMPLE = """\
- [ ] todo 1
- [x] todo 2
- [ ] todo with subtasks
  - [ ] subtask 1
  - [X] subtask 2
    - [ ] deep
"""


class ParseDump(unittest.TestCase):
    def test_roundtrip(self):
        tl = TodoList.parse(SAMPLE)
        self.assertEqual(tl.dump(), SAMPLE.replace("[X]", "[x]"))

    def test_structure(self):
        tl = TodoList.parse(SAMPLE)
        self.assertEqual([t.text for t in tl.items], ["todo 1", "todo 2", "todo with subtasks"])
        self.assertTrue(tl.get("2").done)
        self.assertEqual(tl.get("3.2.1").text, "deep")

    def test_normalises_indent_and_bullets(self):
        tl = TodoList.parse("* [ ] a\n\t+ [x] b\n\n    - [ ] c\n")
        self.assertEqual(tl.dump(), "- [ ] a\n  - [x] b\n  - [ ] c\n")

    def test_keeps_stray_lines(self):
        text = "# heading\n- [ ] a\n  some detail\n- [ ] b\n"
        tl = TodoList.parse(text)
        self.assertEqual(tl.preamble, ["# heading"])
        self.assertEqual(tl.get("1").extra, ["some detail"])
        self.assertEqual(tl.dump(), text)

    def test_empty(self):
        self.assertEqual(TodoList.parse("").dump(), "")

    def test_walk(self):
        paths = [(p, d) for p, d, _ in TodoList.parse(SAMPLE).walk()]
        self.assertEqual(paths, [("1", 0), ("2", 0), ("3", 0), ("3.1", 1), ("3.2", 1), ("3.2.1", 2)])


class Mutations(unittest.TestCase):
    def setUp(self):
        self.tl = TodoList.parse(SAMPLE)

    def test_add(self):
        self.assertEqual(self.tl.add("new"), "4")
        self.assertEqual(self.tl.add("child", parent="3"), "3.3")
        self.assertEqual(self.tl.get("3.3").text, "child")

    def test_insert(self):
        self.tl.insert("1", "first")
        self.assertEqual(self.tl.get("1").text, "first")
        self.tl.insert("4.3", "end of subtasks")
        self.assertEqual(self.tl.get("4.3").text, "end of subtasks")
        with self.assertRaises(PathError):
            self.tl.insert("9", "x")

    def test_toggle_edit_delete(self):
        self.assertTrue(self.tl.toggle("1", expect="todo 1").done)
        self.tl.edit("1", "renamed")
        self.assertEqual(self.tl.delete("1").text, "renamed")
        self.assertEqual(self.tl.get("1").text, "todo 2")

    def test_expect_guards_against_stale_paths(self):
        with self.assertRaises(StaleError):
            self.tl.toggle("1", expect="todo 2")
        self.assertFalse(self.tl.get("1").done)

    def test_bad_paths(self):
        for p in ["0", "9", "1.1", "x", "", "3..1"]:
            with self.assertRaises(PathError, msg=p):
                self.tl.get(p)

    def test_indent_outdent(self):
        new = self.tl.indent("2")
        self.assertEqual(new, "1.1")
        self.assertEqual(self.tl.get("1.1").text, "todo 2")
        back = self.tl.outdent("1.1")
        self.assertEqual(back, "2")
        self.assertEqual(self.tl.dump(), TodoList.parse(SAMPLE).dump())
        with self.assertRaises(PathError):
            self.tl.indent("1")
        with self.assertRaises(PathError):
            self.tl.outdent("1")


class CarryOver(unittest.TestCase):
    def test_rules(self):
        text = """\
- [x] parent
  - [x] done child
  - [ ] open child
- [x] finished thing
  - [x] finished child
- [ ] open
  - [x] done under open
"""
        self.assertEqual(
            TodoList.parse(text).carry_over().dump(),
            "- [x] parent\n  - [ ] open child\n- [ ] open\n",
        )

    def test_does_not_mutate_original(self):
        tl = TodoList.parse(SAMPLE)
        tl.carry_over()
        self.assertEqual(tl.dump(), SAMPLE.replace("[X]", "[x]"))


if __name__ == "__main__":
    unittest.main()
