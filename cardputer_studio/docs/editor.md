# The code editor

`ui/editor.py` holds `CodeEditor` (one file) and `EditorTabs` (the tab strip). Almost all the *decisions* live in
`core/` as plain functions; the editor just asks them questions and draws the answers.

## Highlighting

`core/syntax.py: highlight_line(text, state, api_names) -> (spans, state)`

Highlighting is done one line at a time. `state` carries what has to survive a line break (inside a triple-quoted
string, for example). `ui/highlighter.py` is a thin `QSyntaxHighlighter` that calls it and sets colours from
`theme.SYNTAX`. Token kinds: keyword, variable, constant, builtin, api (engine names get their own colour so you can
see what's yours and what's engine), string, comment, number, decorator, definition, self.

## Diagnostics (errors and warnings)

`core/diagnostics.py: check_source(text, path, api_names)` runs `ast.parse` for syntax errors and, if installed,
pyflakes for things like undefined names. Engine names are passed in so they are not reported as undefined.
A 400 ms single-shot timer in the main window re-runs it after you stop typing. Results are drawn as wavy underlines
(Qt "extra selections") and a dot in the line-number gutter, and listed in the Problems panel.

## Line numbers

Qt has no built-in gutter. The standard trick: a child `QWidget` (`_LineNumberArea`) sits in the left margin of
the editor, the editor reserves room with `setViewportMargins`, and the gutter paints the numbers itself by
walking the visible text blocks.

## Autocomplete

`core/completion.py: complete(text, offset, path, index) -> (replace_len, [Completion])`

Sources, in ranking order: names assigned in this file, project functions/classes/variables, engine API, builtins,
keywords. After `self.` it lists the class's methods and attributes (found by indentation, so it works while the file
doesn't parse). After `module.` it lists that module's members: for your own files from the symbol index, for a few
safe stdlib modules (`math`, `random`, ...) by importing them. It returns nothing inside strings and comments, right
after `def` or `class`, and when there is nothing typed.

The popup is a `QCompleter` in `UnfilteredPopupCompletion` mode: Qt doesn't filter (we already did), it only shows
the list. The visible text is `name   detail`, but the item's `UserRole` holds just the name, and the completer's
completion role is set to `UserRole`, so the inserted text is the bare name. `Enter`, `Tab`, `Escape` are ignored by
the editor while the popup is visible so the popup handles them.

## Hover with a call tree

`core/symbols.py` builds `SymbolIndex` from every `.py` file: functions, methods, classes, their signatures,
docstrings, and which names each one calls. From that it can answer "what does this call" and "what calls this" and
draw the result as a tree (`call_tree`, depth 3, loop-safe). If a file doesn't currently parse (you're mid-edit) the
index keeps what it knew about that file instead of forgetting it.

`core/hover.py: hover_html(...)` finds the dotted name under the mouse and decides what it is: a project symbol
(signature, docstring, where it is defined, Calls and Called-by trees), an engine function (its documentation),
a builtin, or a stdlib member. It resolves `self.method()`, `module.func()`, imported names and plain calls. It does
**not** guess the type of a variable, so `player.move()` is not linked to `Player.move`. That would need type
inference.

In the editor the tooltip event builds one rich-text tooltip that combines the line's diagnostics with the hover info.

## Find and replace

`core/search.py` is the whole engine: `compile_query` (plain text is escaped, "whole word" adds look-arounds, regex
is passed through), `find_all`, `replace_edits` (supports `\1` in regex mode), `next_index`/`prev_index`.
`ui/findbar.py` is only the widgets: two text fields, three toggles, buttons. It asks the editor to select a range,
apply edits (one undo step for Replace All) and draw match highlights.

## Multiple cursors

The primary cursor is Qt's own `textCursor()`. The others are a list of extra `QTextCursor` objects. A
`QTextCursor` automatically adjusts when the document changes, which is what makes this workable: to type a
character on every cursor we run all the inserts inside one edit block, **last position first**, so an insert never
shifts a cursor that still has to be processed.

- `_edit_all(fn)` runs an edit on every cursor as one undo step. Typing, Backspace, Delete, Enter, Tab, paste, cut use it.
- `_move_all(...)` moves every cursor for arrows, Home, End (and Shift to extend).
- `_commit(cursors)` makes the first one primary and drops duplicates/overlaps (`core/multicursor.keep_indices`).
- Extra carets are painted by hand in `paintEvent`; their selections are extra selections.
- Middle-mouse drag: press records `(line, visual column)`; each move calls `core/multicursor.column_spans`, which
  returns one `(line, start, end)` per line (short lines get a caret at their end). Visual columns count a tab as
  advancing to the next multiple of 4, so columns line up even with tabs.
- Alt+click adds a cursor; Ctrl+Alt+Up/Down add one above/below; Ctrl+D selects the word, then each next occurrence;
  Esc returns to one cursor.
- Pasting: if the clipboard has exactly one line per cursor, each cursor gets its own line (VS Code behaviour).

The middle button is handled completely in `mousePressEvent` without calling the base class, because on Linux the
base class would paste the X11 selection.

## Python index vs Qt position

Python strings index by code point; Qt positions count UTF-16 units. They only differ for characters outside the
BMP (emoji), but then every highlight and completion would be off by one. `core/textpos.py` converts, and is the
identity for plain ASCII text.

## EditorTabs

Keeps `path -> widget`. `open_path` opens text files in a `CodeEditor`; `open_asset(path, make_widget)` opens the
sprite/tilemap/sound editors in the same tab strip. Renaming a file renames the tab; deleting closes it. The `Project` is
the source of truth: every text edit emits `text_edited(path, full_text)` and the main window writes it in.
