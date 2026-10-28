"""The .cpg project format.

A .cpg file is an ordinary zip archive:

    project.json          manifest (format version, name, entry file)
    files/<path>          every project file, at its project-relative path
    files/<dir>/          empty directories (so they survive a save)

In memory a Project is a virtual directory tree (paths -> bytes). The IDE edits it directly and
only touches the .cpg on disk when saving, so users never have to manage the archive by hand.
"""
from __future__ import annotations

import json
import os
import posixpath
import tempfile
import zipfile

FORMAT_VERSION = 1
EXTENSION = ".cpg"
MANIFEST = "project.json"
FILES_PREFIX = "files/"
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_FILES = 5000
DEFAULT_ENTRY = "main.py"


class ProjectError(Exception):
    """Anything wrong with a project path, operation or .cpg file; the message is user-facing."""


def normalize_path(path: str) -> str:
    """Validate a project-relative path and return it in clean posix form.

    Rejects anything that could escape the project or misbehave on Windows: absolute paths, drive
    letters, backslashes, '.' / '..' segments, empty segments, control characters and names that
    end in a space or dot.
    """
    if not isinstance(path, str) or not path.strip():
        raise ProjectError("Path is empty.")
    if "\\" in path:
        raise ProjectError("Use '/' as the path separator (no backslashes).")
    if any(ord(c) < 32 for c in path):
        raise ProjectError("Path contains control characters.")
    path = path.rstrip("/")
    if not path or path.startswith("/"):
        raise ProjectError("Path must be relative to the project (no leading '/').")
    for part in path.split("/"):
        if part in ("", ".", ".."):
            raise ProjectError("Path %r has an empty, '.' or '..' segment." % path)
        if ":" in part:
            raise ProjectError("Path %r contains ':'." % path)
        if part != part.rstrip(" .") or part != part.lstrip(" "):
            raise ProjectError("Names can't start with a space or end with a space or dot: %r" % part)
        if len(part) > 200:
            raise ProjectError("Name is too long: %r" % part[:40])
    if len(path) > 500:
        raise ProjectError("Path is too long.")
    return path


def _parents(path: str):
    """Yield every ancestor directory of `path`, shallowest first."""
    parts = path.split("/")[:-1]
    for i in range(1, len(parts) + 1):
        yield "/".join(parts[:i])


class Project:
    def __init__(self, name: str = "untitled", entry: str = DEFAULT_ENTRY):
        self.name = name
        self.entry = normalize_path(entry)
        self.path: str | None = None       # where it was last saved/opened
        self.dirty = False
        self._files: dict[str, bytes] = {}
        self._dirs: set[str] = set()       # explicitly created directories

    # ---- queries -------------------------------------------------------------------------
    def files(self) -> list[str]:
        return sorted(self._files)

    def dirs(self) -> list[str]:
        """Every directory, including implicit parents of files."""
        out = set(self._dirs)
        for f in self._files:
            out.update(_parents(f))
        return sorted(out)

    def is_file(self, path: str) -> bool:
        return normalize_path(path) in self._files

    def is_dir(self, path: str) -> bool:
        path = normalize_path(path)
        return path in self._dirs or any(f.startswith(path + "/") for f in self._files)

    def exists(self, path: str) -> bool:
        return self.is_file(path) or self.is_dir(path)

    def children(self, directory: str = "") -> tuple[list[str], list[str]]:
        """(subdirectory names, file names) directly inside `directory` ('' is the root)."""
        directory = normalize_path(directory) if directory else ""
        prefix = directory + "/" if directory else ""
        dirs = sorted({d[len(prefix):] for d in self.dirs()
                       if d.startswith(prefix) and "/" not in d[len(prefix):]})
        files = sorted(f[len(prefix):] for f in self._files
                       if f.startswith(prefix) and "/" not in f[len(prefix):])
        return dirs, files

    def read_bytes(self, path: str) -> bytes:
        path = normalize_path(path)
        try:
            return self._files[path]
        except KeyError:
            raise ProjectError("No such file: %s" % path) from None

    def read_text(self, path: str) -> str:
        data = self.read_bytes(path)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            raise ProjectError("%s is not a UTF-8 text file." % path) from None

    # ---- mutations -----------------------------------------------------------------------
    def _check_free(self, path: str):
        """`path` must not collide with an existing file/dir or sit inside a file."""
        for parent in _parents(path):
            if parent in self._files:
                raise ProjectError("%r is a file, so nothing can be created inside it." % parent)

    def write_bytes(self, path: str, data: bytes) -> None:
        path = normalize_path(path)
        if len(data) > MAX_FILE_BYTES:
            raise ProjectError("%s is too large (limit %d MB)." % (path, MAX_FILE_BYTES // 2**20))
        if path in self._files:
            if self._files[path] == data:
                return
        else:
            if self.is_dir(path):
                raise ProjectError("%r is a folder." % path)
            self._check_free(path)
            if len(self._files) >= MAX_FILES:
                raise ProjectError("Too many files (limit %d)." % MAX_FILES)
        self._files[path] = bytes(data)
        self.dirty = True

    def write_text(self, path: str, text: str) -> None:
        self.write_bytes(path, text.encode("utf-8"))

    def make_dir(self, path: str) -> None:
        path = normalize_path(path)
        if path in self._files:
            raise ProjectError("%r is a file." % path)
        self._check_free(path)
        if not self.is_dir(path):
            self._dirs.add(path)
            self.dirty = True

    def delete(self, path: str) -> None:
        path = normalize_path(path)
        if path in self._files:
            del self._files[path]
        elif self.is_dir(path):
            prefix = path + "/"
            for f in [f for f in self._files if f.startswith(prefix)]:
                del self._files[f]
            self._dirs = {d for d in self._dirs if d != path and not d.startswith(prefix)}
        else:
            raise ProjectError("No such file or folder: %s" % path)
        self.dirty = True

    def rename(self, old: str, new: str) -> None:
        """Rename or move a file or folder (the entry point follows along)."""
        old, new = normalize_path(old), normalize_path(new)
        if old == new:
            return
        if not self.exists(old):
            raise ProjectError("No such file or folder: %s" % old)
        if self.exists(new):
            raise ProjectError("%s already exists." % new)
        if new.startswith(old + "/"):
            raise ProjectError("Can't move a folder into itself.")
        self._check_free(new)
        if old in self._files:
            self._files[new] = self._files.pop(old)
        else:
            op, np_ = old + "/", new + "/"
            for f in [f for f in self._files if f.startswith(op)]:
                self._files[np_ + f[len(op):]] = self._files.pop(f)
            self._dirs = {np_ + d[len(op):] if d.startswith(op) else d for d in self._dirs if d != old}
            self._dirs.add(new)
        if self.entry == old:
            self.entry = new
        elif self.entry.startswith(old + "/"):
            self.entry = new + self.entry[len(old):]
        self.dirty = True

    def set_entry(self, path: str) -> None:
        path = normalize_path(path)
        if path not in self._files:
            raise ProjectError("No such file: %s" % path)
        if path != self.entry:
            self.entry = path
            self.dirty = True

    # ---- disk ----------------------------------------------------------------------------
    def manifest(self) -> dict:
        from .. import __version__
        return {"format": FORMAT_VERSION, "name": self.name, "entry": self.entry,
                "app": "cardputer-studio", "app_version": __version__}

    def save(self, path: str | None = None) -> str:
        """Write the .cpg atomically (temp file + rename) and return the path used."""
        path = path or self.path
        if not path:
            raise ProjectError("No file name chosen for this project yet.")
        path = os.path.abspath(path)
        directory = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(prefix=".cpg-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "wb") as raw, zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr(MANIFEST, json.dumps(self.manifest(), indent=2))
                for d in sorted(self._dirs):
                    if not any(f.startswith(d + "/") for f in self._files):
                        z.writestr(FILES_PREFIX + d + "/", b"")
                for f in sorted(self._files):
                    z.writestr(FILES_PREFIX + f, self._files[f])
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self.path = path
        self.dirty = False
        return path

    @classmethod
    def load(cls, path: str) -> "Project":
        try:
            zf = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as e:
            raise ProjectError("Can't open %s: not a valid .cpg file (%s)." % (os.path.basename(path), e)) from None
        with zf:
            try:
                manifest = json.loads(zf.read(MANIFEST).decode("utf-8"))
            except (KeyError, ValueError):
                raise ProjectError("%s has no valid project.json." % os.path.basename(path)) from None
            fmt = manifest.get("format")
            if not isinstance(fmt, int) or fmt < 1:
                raise ProjectError("Unknown project format in %s." % os.path.basename(path))
            if fmt > FORMAT_VERSION:
                raise ProjectError("%s was made by a newer Cardputer Studio (format %d)." % (os.path.basename(path), fmt))
            proj = cls(str(manifest.get("name") or "untitled"), str(manifest.get("entry") or DEFAULT_ENTRY))
            total = 0
            for info in zf.infolist():
                if not info.filename.startswith(FILES_PREFIX):
                    continue
                rel = info.filename[len(FILES_PREFIX):]
                if not rel:
                    continue
                is_dir = rel.endswith("/")
                rel = normalize_path(rel)
                if is_dir:
                    proj._dirs.add(rel)
                    continue
                if info.file_size > MAX_FILE_BYTES:
                    raise ProjectError("%s is too large inside the project." % rel)
                total += info.file_size
                if total > MAX_TOTAL_BYTES or len(proj._files) >= MAX_FILES:
                    raise ProjectError("Project is too large to open.")
                proj._files[rel] = zf.read(info)
        proj.path = os.path.abspath(path)
        proj.dirty = False
        return proj

    def extract_to(self, directory: str) -> None:
        """Write the project into a real directory (used to run it)."""
        root = os.path.realpath(directory)
        os.makedirs(root, exist_ok=True)
        for d in self.dirs():
            os.makedirs(os.path.join(root, *d.split("/")), exist_ok=True)
        for f, data in self._files.items():
            target = os.path.realpath(os.path.join(root, *f.split("/")))
            if os.path.commonpath([root, target]) != root:
                raise ProjectError("Refusing to write outside the run folder: %s" % f)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(data)

    @staticmethod
    def suggest_name(path: str) -> str:
        return posixpath.splitext(os.path.basename(path))[0] or "untitled"
