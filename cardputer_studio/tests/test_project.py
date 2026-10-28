import json
import os
import tempfile
import unittest
import zipfile

from helpers import ROOT  # noqa: F401
from cpg_studio.core import templates
from cpg_studio.core.project import Project, ProjectError, normalize_path


class PathTests(unittest.TestCase):
    def test_valid_paths(self):
        self.assertEqual(normalize_path("main.py"), "main.py")
        self.assertEqual(normalize_path("assets/img/a.png"), "assets/img/a.png")
        self.assertEqual(normalize_path("assets/"), "assets")

    def test_rejected_paths(self):
        bad = ["", "  ", "/abs", "../x", "a/../b", "a//b", "a/./b", "C:/x", "a\\b", "x\x00y",
               "name.", "name ", " lead", "a/b/..", "."]
        for p in bad:
            with self.assertRaises(ProjectError, msg=repr(p)):
                normalize_path(p)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.p = Project("demo")
        self.p.write_text("main.py", "print(1)\n")
        self.p.write_text("assets/a.txt", "A")
        self.p.write_bytes("assets/img/b.bin", b"\x00\xff")
        self.p.make_dir("empty")
        self.p.dirty = False

    def test_tree_queries(self):
        self.assertEqual(self.p.files(), ["assets/a.txt", "assets/img/b.bin", "main.py"])
        self.assertEqual(self.p.dirs(), ["assets", "assets/img", "empty"])
        self.assertEqual(self.p.children(""), (["assets", "empty"], ["main.py"]))
        self.assertEqual(self.p.children("assets"), (["img"], ["a.txt"]))
        self.assertTrue(self.p.is_dir("assets/img") and self.p.is_file("main.py"))

    def test_dirty_only_when_changed(self):
        self.p.write_text("main.py", "print(1)\n")
        self.assertFalse(self.p.dirty)
        self.p.write_text("main.py", "print(2)\n")
        self.assertTrue(self.p.dirty)

    def test_text_vs_binary(self):
        self.assertEqual(self.p.read_text("main.py"), "print(1)\n")
        with self.assertRaises(ProjectError):
            self.p.read_text("assets/img/b.bin")
        with self.assertRaises(ProjectError):
            self.p.read_bytes("nope.py")

    def test_collisions(self):
        with self.assertRaises(ProjectError):
            self.p.write_text("main.py/inner.txt", "x")      # inside a file
        with self.assertRaises(ProjectError):
            self.p.write_text("assets", "x")                   # name of a folder
        with self.assertRaises(ProjectError):
            self.p.make_dir("main.py")

    def test_rename_file_and_entry(self):
        self.p.rename("main.py", "game.py")
        self.assertEqual(self.p.entry, "game.py")
        self.assertTrue(self.p.is_file("game.py") and not self.p.exists("main.py"))
        self.assertTrue(self.p.dirty)

    def test_rename_folder_moves_contents_and_entry(self):
        self.p.write_text("src/main.py", "x")
        self.p.set_entry("src/main.py")
        self.p.rename("src", "code")
        self.assertEqual(self.p.entry, "code/main.py")
        self.assertTrue(self.p.is_file("code/main.py"))
        self.p.rename("empty", "vacant")
        self.assertIn("vacant", self.p.dirs())
        self.assertNotIn("empty", self.p.dirs())

    def test_rename_errors(self):
        with self.assertRaises(ProjectError):
            self.p.rename("main.py", "assets")             # exists
        with self.assertRaises(ProjectError):
            self.p.rename("assets", "assets/sub")          # into itself
        with self.assertRaises(ProjectError):
            self.p.rename("ghost", "x")

    def test_delete(self):
        self.p.delete("assets")
        self.assertEqual(self.p.files(), ["main.py"])
        self.p.delete("empty")
        self.assertEqual(self.p.dirs(), [])
        with self.assertRaises(ProjectError):
            self.p.delete("assets")

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.cpg")
            self.p.set_entry("main.py")
            self.p.save(path)
            self.assertFalse(self.p.dirty)
            self.assertEqual(os.listdir(tmp), ["demo.cpg"])       # temp file cleaned up
            q = Project.load(path)
            self.assertEqual(q.files(), self.p.files())
            self.assertEqual(q.dirs(), self.p.dirs())             # includes the empty folder
            self.assertEqual(q.read_bytes("assets/img/b.bin"), b"\x00\xff")
            self.assertEqual((q.name, q.entry, q.path), ("demo", "main.py", os.path.abspath(path)))

    def test_it_is_a_real_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.cpg")
            self.p.save(path)
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                self.assertEqual(names[0], "project.json")
                self.assertIn("files/main.py", names)
                self.assertEqual(json.loads(z.read("project.json"))["format"], 1)

    def test_load_rejects_bad_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            junk = os.path.join(tmp, "junk.cpg")
            with open(junk, "wb") as f:
                f.write(b"not a zip")
            with self.assertRaises(ProjectError):
                Project.load(junk)
            with self.assertRaises(ProjectError):
                Project.load(os.path.join(tmp, "missing.cpg"))
            nomani = os.path.join(tmp, "nomani.cpg")
            with zipfile.ZipFile(nomani, "w") as z:
                z.writestr("files/main.py", "x")
            with self.assertRaises(ProjectError):
                Project.load(nomani)
            newer = os.path.join(tmp, "newer.cpg")
            with zipfile.ZipFile(newer, "w") as z:
                z.writestr("project.json", json.dumps({"format": 99}))
            with self.assertRaises(ProjectError):
                Project.load(newer)

    def test_load_rejects_zip_slip(self):
        with tempfile.TemporaryDirectory() as tmp:
            evil = os.path.join(tmp, "evil.cpg")
            with zipfile.ZipFile(evil, "w") as z:
                z.writestr("project.json", json.dumps({"format": 1}))
                z.writestr("files/../../escape.py", "boom")
            with self.assertRaises(ProjectError):
                Project.load(evil)

    def test_failed_save_leaves_old_file_and_no_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "keep.cpg")
            self.p.save(path)
            with open(path, "rb") as f:
                before = f.read()
            self.p.write_text("main.py", "changed\n")
            real_replace = os.replace

            def boom(src, dst):
                raise OSError("disk exploded")

            os.replace = boom
            try:
                with self.assertRaises(OSError):
                    self.p.save(path)
            finally:
                os.replace = real_replace
            with open(path, "rb") as f:
                self.assertEqual(f.read(), before)              # old file untouched
            self.assertEqual(os.listdir(tmp), ["keep.cpg"])     # no stray temp file
            self.assertTrue(self.p.dirty)                       # still unsaved

    def test_extract_to(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.p.extract_to(tmp)
            with open(os.path.join(tmp, "assets", "a.txt")) as f:
                self.assertEqual(f.read(), "A")
            self.assertTrue(os.path.isdir(os.path.join(tmp, "empty")))

    def test_save_without_name_fails(self):
        with self.assertRaises(ProjectError):
            Project().save()


class TemplateTests(unittest.TestCase):
    def test_all_templates_are_valid_python_projects(self):
        for key in templates.TEMPLATES:
            p = templates.new_project(key)
            self.assertFalse(p.dirty)
            self.assertTrue(p.is_file(p.entry))
            compile(p.read_text(p.entry), key, "exec")


if __name__ == "__main__":
    unittest.main()
