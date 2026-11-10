#!/usr/bin/env python3
"""Tests for build.py: the layer rule, the join, and that ./reveille is what src/ builds.
No systemd, GTK or network needed.   Run: python3 test_build.py"""
import contextlib, importlib.util, io, os, shutil, sys, tempfile, unittest

sys.dont_write_bytecode = True          # don't leave a __pycache__ next to build.py in the repository
HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("build", os.path.join(HERE, "build.py"))
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def frags(self, *texts):
        """Write fragments 00, 01, ... into a fresh folder and return what build.problems says about them."""
        shutil.rmtree(self.dir); os.makedirs(self.dir)
        for i, t in enumerate(texts):
            with open(f"{self.dir}/{i:02d}_f.py", "w", newline="") as f: f.write(t)
        return build.problems(build.fragments(self.dir))


class LayerRule(Tmp):
    def test_using_a_lower_layer_is_fine(self):
        self.assertEqual(self.frags("X = 1\n", "def f():\n    return X\n", "Y = f()\n"), [])

    def test_a_forward_reference_inside_one_layer_is_fine(self):
        self.assertEqual(self.frags("def a():\n    return b()\ndef b():\n    return 1\n"), [])

    def test_a_function_using_a_higher_layer_is_refused(self):
        bad = self.frags("def a():\n    return b()\n", "def b():\n    return 1\n")
        self.assertEqual(len(bad), 1); self.assertIn("uses b", bad[0]); self.assertIn("01_f.py", bad[0])

    def test_module_level_use_of_a_higher_layer_is_refused(self):
        self.assertTrue(self.frags("X = later()\n", "def later():\n    return 1\n"))

    def test_uses_inside_nested_functions_and_classes_are_seen(self):
        deep = "def outer():\n    class C:\n        def m(self):\n            return lambda: later()\n    return C\n"
        self.assertTrue(self.frags(deep, "def later():\n    return 1\n"))

    def test_a_local_that_shares_a_name_with_a_higher_layer_is_not_a_use(self):
        self.assertEqual(self.frags("def a(later):\n    later = later + 1\n    return later\n", "def later():\n    return 1\n"), [])

    def test_a_name_defined_twice_is_refused(self):
        bad = self.frags("def f():\n    pass\n", "def f():\n    pass\n")
        self.assertEqual(len(bad), 1); self.assertIn("f is defined in both", bad[0])

    def test_a_fragment_that_does_not_parse_is_reported(self):
        self.assertIn("does not parse", self.frags("def (:\n")[0])

    def test_names_that_exist_nowhere_are_not_this_checks_business(self):
        self.assertEqual(self.frags("def a():\n    return len([]) + missing_somewhere\n"), [])


class Join(Tmp):
    def test_notes_are_dropped_and_everything_else_is_kept_byte_for_byte(self):
        self.frags("#: layer 00: notes\n#: more notes\n#!/x\nA = 1\r\n", "B = 2\n\n\n")
        self.assertEqual(build.build(self.dir)[0], "#!/x\nA = 1\r\nB = 2\n\n\n")

    def test_a_note_line_below_code_is_kept(self):
        self.frags("A = 1\n#: not a note any more\n")
        self.assertEqual(build.build(self.dir)[0], "A = 1\n#: not a note any more\n")

    def test_fragments_must_be_numbered_without_gaps(self):
        self.frags("A = 1\n", "B = 1\n")
        os.rename(f"{self.dir}/01_f.py", f"{self.dir}/02_f.py")
        with self.assertRaises(ValueError): build.fragments(self.dir)

    def test_other_files_in_src_are_ignored(self):
        self.frags("A = 1\n")
        for n in ("notes.txt", "1_short.py", "01_Upper.py"): open(f"{self.dir}/{n}", "w").close()
        self.assertEqual([n for n, _ in build.fragments(self.dir)], ["00_f.py"])

    def test_a_broken_fragment_is_reported_by_build(self):
        self.frags("if True:\n", "    pass\n")                 # neither half parses alone, so build() reports it
        self.assertTrue(build.build(self.dir)[1])


class TheRepository(unittest.TestCase):
    def test_the_real_fragments_follow_the_layer_rule(self):
        text, bad = build.build(os.path.join(HERE, "src")); self.assertEqual(bad, [])

    def test_reveille_is_exactly_what_src_builds(self):
        text, _ = build.build(os.path.join(HERE, "src"))
        with open(os.path.join(HERE, "reveille"), newline="") as f: self.assertEqual(f.read(), text)

    def test_check_mode(self):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        out = os.path.join(d, "reveille")
        def run(*a):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return build.main([*a, "-o", out])
        self.assertEqual(run("--check"), 1)                    # nothing there yet
        self.assertEqual(run(), 0); self.assertEqual(run("--check"), 0)
        self.assertEqual(os.stat(out).st_mode & 0o777, 0o755)
        with open(out, "a") as f: f.write("# edited by hand\n")
        self.assertEqual(run("--check"), 1)                    # a hand edit of the built file is noticed
        self.assertEqual(run(), 0); self.assertEqual(run("--check"), 0)


if __name__ == "__main__":
    unittest.main()
