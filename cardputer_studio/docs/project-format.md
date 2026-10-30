# The project format (`.cpg`)

## On disk

A `.cpg` file is a normal zip archive with a different extension. Rename it to `.zip` to look inside.

```
project.json            {"format": 1, "name": "...", "entry": "main.py"}
files/main.py           every project file at its project-relative path
files/assets/hero.png
files/assets/            (a trailing slash marks an empty folder so it survives a save)
```

Why a zip: one file to share, every language has a zip reader, compression is free, and a damaged project can
still be opened by hand.

## In memory: `Project`

`core/project.py`. A `Project` is a virtual folder: a dict of `path -> bytes` plus a set of folder names. The IDE
edits this object directly. The zip is only written when you save, so you never manage the archive yourself.

Key methods: `read_bytes/read_text`, `write_bytes/write_text`, `make_dir`, `delete`, `rename`, `children`,
`set_entry`, `save`, `Project.load`, `extract_to`.

Rules enforced (`normalize_path` and the `write_*` methods):
- Paths use forward slashes and are relative. No `..` or `.` parts, no backslashes, no absolute paths, no `:` (drive
  letters), no empty parts, no control characters, no names starting with a space or ending in a space or dot
  (Windows can't store those), and length limits.
- Limits: 16 MB per file, 128 MB total, 5000 files.
- A path can't be both a file and a folder.

`dirty` is set by any change and shown as the `*` in the window title.

## Saving safely

`save()` writes to a temporary file in the same folder and then calls `os.replace`, which swaps it in atomically.
If the program or the computer dies mid-save, the old file is still intact.

## Loading safely

`Project.load` treats the zip as untrusted: it validates every entry name with the same path rules (so a crafted
zip can't write outside the project), checks the declared sizes against the limits before reading each file, and raises `ProjectError` with a
readable message instead of crashing.

## Running a project

`extract_to(folder)` writes every file out to a temp folder. The runner then works on real files, so normal
Python features (`import utils`, `open("assets/level.txt")`) work without any special loader.
