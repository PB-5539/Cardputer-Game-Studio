"""The main window: VS Code-style layout built from dockable, resizable panels."""
from __future__ import annotations

import os
import posixpath

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog, QInputDialog, QLabel, QMainWindow,
                               QMessageBox, QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, firmware
from ..core import completion, hover, templates
from ..core.diagnostics import check_source
from ..core.project import EXTENSION, Project, ProjectError
from ..core.symbols import SymbolIndex
from ..runtime import api, api_docs
from . import theme
from .editor import EditorTabs
from .findbar import FindBar
from .panels import ConsolePanel, DocsPanel, ProblemsPanel, RuntimePanel
from .preview import PreviewPanel
from .runner_controller import RunnerController
from .workspace import WorkspaceTree


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.api_names = tuple(api.__all__)
        self.project = templates.new_project("starter")
        self.settings = QSettings("CardputerStudio", "Studio")
        self._diag_pending: set[str] = set()
        self.symbols = SymbolIndex(self.api_names)
        self._symbols_stale = True
        self._diag_timer = QTimer(self)
        self._diag_timer.setSingleShot(True)
        self._diag_timer.setInterval(400)
        self._diag_timer.timeout.connect(self._run_diagnostics)
        self._shown_once = False
        self._saved_layout = False

        self._make_actions()
        self._make_widgets()
        self._make_menus()
        self._wire()
        self.resize(1500, 900)
        self._restore_layout()
        self._load_project(self.project)

    # ---- construction ----------------------------------------------------------------------
    def _action(self, text, slot, shortcut=None, tip=None):
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(shortcut)
        if tip:
            act.setStatusTip(tip)
        act.triggered.connect(lambda checked=False: slot())
        return act

    def _make_actions(self):
        self.act_new = self._action("&New Project", lambda: self.new_project("starter"), "Ctrl+N")
        self.act_open = self._action("&Open Project…", lambda: self.open_project(None), "Ctrl+O")
        self.act_save = self._action("&Save", self.save_project, "Ctrl+S")
        self.act_save_as = self._action("Save &As…", self.save_project_as, "Ctrl+Shift+S")
        self.act_new_file = self._action("New &File…", lambda: self.new_file(None), "Ctrl+Shift+N")
        self.act_new_folder = self._action("New F&older…", lambda: self.new_folder(None))
        self.act_import = self._action("&Import File…", lambda: self.import_files(None))
        self.act_export_docs = self._action("Export API &Reference…", self.export_api_docs)
        self.act_quit = self._action("&Quit", self.close, "Ctrl+Q")
        self.act_undo = self._action("&Undo", lambda: self._edit("undo"), "Ctrl+Z")
        self.act_redo = self._action("&Redo", lambda: self._edit("redo"), "Ctrl+Shift+Z")
        self.act_cut = self._action("Cu&t", lambda: self._edit("cut"), "Ctrl+X")
        self.act_copy = self._action("&Copy", lambda: self._edit("copy"), "Ctrl+C")
        self.act_paste = self._action("&Paste", lambda: self._edit("paste"), "Ctrl+V")
        self.act_select_all = self._action("Select &All", lambda: self._edit("selectAll"), "Ctrl+A")
        self.act_find = self._action("&Find…", lambda: self._show_find(False), "Ctrl+F")
        self.act_replace = self._action("&Replace…", lambda: self._show_find(True), "Ctrl+H")
        self.act_find_next = self._action("Find &Next", lambda: self.findbar.find_next(), "F3")
        self.act_find_prev = self._action("Find Pre&vious", lambda: self.findbar.find_prev(), "Shift+F3")
        self.act_suggest = self._action("Trigger &Suggestions", lambda: self._editor_call("trigger_completion"), "Ctrl+Space")
        self.act_next_occurrence = self._action("Select Next &Occurrence", lambda: self._editor_call("select_next_occurrence"), "Ctrl+D")
        self.act_cursor_above = self._action("Add Cursor &Above", lambda: self._editor_call("add_cursor_above"), "Ctrl+Alt+Up")
        self.act_cursor_below = self._action("Add Cursor &Below", lambda: self._editor_call("add_cursor_below"), "Ctrl+Alt+Down")
        self.act_run = self._action("▶  Run", self.run_project, "F5", "Run the project in the preview")
        self.act_stop = self._action("■  Stop", self.stop_project, "Shift+F5")
        self.act_restart = self._action("⟳  Restart", self.run_project, "Ctrl+F5")
        self.act_stop.setEnabled(False)
        self.act_firmware = self._action("Export &Firmware (.bin)…", self.export_firmware,
                                         tip="Placeholder: not implemented yet")
        self.act_reset_layout = self._action("&Reset Layout", self.reset_layout)

    def _dock(self, title, widget, name):
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        return dock

    def _make_widgets(self):
        self.tabs = EditorTabs(self.api_names)
        self.welcome = QLabel("Open a file from the Workspace to start editing.\n\nF5 runs the project in the preview.")
        self.welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.welcome.setStyleSheet(f"color: {theme.MUTED}; font-size: 14px;")
        self.central = QStackedWidget()
        self.findbar = FindBar()
        self.editor_area = QWidget()
        area_layout = QVBoxLayout(self.editor_area)
        area_layout.setContentsMargins(0, 0, 0, 0)
        area_layout.setSpacing(0)
        area_layout.addWidget(self.findbar)
        area_layout.addWidget(self.tabs, 1)
        self.central.addWidget(self.welcome)
        self.central.addWidget(self.editor_area)
        self.tabs.set_providers(self._complete_at, self._hover_at)
        self.setCentralWidget(self.central)

        self.workspace = WorkspaceTree()
        self.preview = PreviewPanel(self.act_run, self.act_stop, self.act_restart)
        self.docs = DocsPanel()
        self.problems = ProblemsPanel()
        self.runtime_panel = RuntimePanel()
        self.side_tabs = QTabWidget()
        self.side_tabs.setDocumentMode(True)
        self.side_tabs.addTab(self.docs, "Docs")
        self.side_tabs.addTab(self.problems, "Problems")
        self.side_tabs.addTab(self.runtime_panel, "Runtime")
        self.console = ConsolePanel()
        self.runner = RunnerController(self)

        self.dock_workspace = self._dock("Workspace", self.workspace, "dock-workspace")
        self.dock_preview = self._dock("Preview", self.preview, "dock-preview")
        self.dock_side = self._dock("Docs and Tools", self.side_tabs, "dock-side")
        self.dock_console = self._dock("Console", self.console, "dock-console")
        # side docks run the full height; the console sits under the editor only
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)
        self.statusBar().showMessage("Ready")

    def _make_menus(self):
        mb = self.menuBar()
        file_menu = mb.addMenu("&File")
        file_menu.addAction(self.act_new)
        examples = file_menu.addMenu("New From E&xample")
        for key, (title, _files) in templates.TEMPLATES.items():
            act = QAction(title, self)
            act.triggered.connect(lambda checked=False, k=key: self.new_project(k))
            examples.addAction(act)
        file_menu.addAction(self.act_open)
        file_menu.addSeparator()
        for a in (self.act_save, self.act_save_as):
            file_menu.addAction(a)
        file_menu.addSeparator()
        for a in (self.act_new_file, self.act_new_folder, self.act_import):
            file_menu.addAction(a)
        file_menu.addSeparator()
        file_menu.addAction(self.act_export_docs)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        edit = mb.addMenu("&Edit")
        for a in (self.act_undo, self.act_redo):
            edit.addAction(a)
        edit.addSeparator()
        for a in (self.act_cut, self.act_copy, self.act_paste, self.act_select_all):
            edit.addAction(a)
        edit.addSeparator()
        for a in (self.act_find, self.act_replace, self.act_find_next, self.act_find_prev):
            edit.addAction(a)
        edit.addSeparator()
        for a in (self.act_suggest, self.act_next_occurrence, self.act_cursor_above, self.act_cursor_below):
            edit.addAction(a)

        run = mb.addMenu("&Run")
        for a in (self.act_run, self.act_stop, self.act_restart):
            run.addAction(a)

        build = mb.addMenu("&Build")
        build.addAction(self.act_firmware)

        view = mb.addMenu("&View")
        for dock, shortcut in ((self.dock_workspace, "Ctrl+B"), (self.dock_preview, None),
                               (self.dock_side, None), (self.dock_console, "Ctrl+J")):
            toggle = dock.toggleViewAction()
            if shortcut:
                toggle.setShortcut(shortcut)
            view.addAction(toggle)
        view.addSeparator()
        view.addAction(self.act_reset_layout)

    def _wire(self):
        self.tabs.text_edited.connect(self.on_text_edited)
        self.tabs.count_changed.connect(self._sync_central)
        self.tabs.currentChanged.connect(lambda index=0: self.findbar.set_editor(self.tabs.current_editor()))
        self.workspace.open_requested.connect(self.open_file)
        self.workspace.new_file_requested.connect(self.new_file)
        self.workspace.new_folder_requested.connect(self.new_folder)
        self.workspace.import_requested.connect(self.import_files)
        self.workspace.rename_requested.connect(self.rename_path)
        self.workspace.delete_requested.connect(self.delete_path)
        self.workspace.set_entry_requested.connect(self.set_entry)
        self.problems.jump_requested.connect(self.open_file)
        self.problems.counts_changed.connect(self._problem_counts)
        self.console.jump_requested.connect(self._jump_from_console)
        self.runner.frame.connect(self.preview.display.set_frame)
        self.runner.output.connect(self.console.append_text)
        self.runner.stats.connect(self.runtime_panel.update_stats)
        self.runner.started.connect(self._on_started)
        self.runner.stopped.connect(self._on_stopped)
        self.preview.display.key_event.connect(self.runner.send_key)

    # ---- layout ------------------------------------------------------------------------------
    def _apply_default_layout(self):
        for dock, area in ((self.dock_workspace, Qt.DockWidgetArea.LeftDockWidgetArea),
                           (self.dock_preview, Qt.DockWidgetArea.RightDockWidgetArea),
                           (self.dock_side, Qt.DockWidgetArea.RightDockWidgetArea),
                           (self.dock_console, Qt.DockWidgetArea.BottomDockWidgetArea)):
            dock.setFloating(False)
            self.addDockWidget(area, dock)
            dock.show()
        self.splitDockWidget(self.dock_preview, self.dock_side, Qt.Orientation.Horizontal)
        self.resizeDocks([self.dock_workspace], [210], Qt.Orientation.Horizontal)
        self.resizeDocks([self.dock_preview, self.dock_side], [430, 320], Qt.Orientation.Horizontal)
        self.resizeDocks([self.dock_console], [170], Qt.Orientation.Vertical)

    def _restore_layout(self):
        self._apply_default_layout()
        geometry, state = self.settings.value("geometry"), self.settings.value("state")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)
            self._saved_layout = True

    def reset_layout(self):
        self._apply_default_layout()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._shown_once:
            self._shown_once = True
            if not self._saved_layout:
                QTimer.singleShot(0, self._apply_default_layout)    # sizes only stick once the window is shown

    # ---- title / state -----------------------------------------------------------------------
    def _update_title(self):
        self.setWindowTitle("%s[*] — %s" % (self.project.name, APP_NAME))
        self.setWindowModified(self.project.dirty)

    def _sync_central(self, count: int):
        self.central.setCurrentWidget(self.editor_area if count else self.welcome)

    def _problem_counts(self, errors: int, warnings: int):
        total = errors + warnings
        self.side_tabs.setTabText(1, "Problems (%d)" % total if total else "Problems")

    def _warn(self, text: str):
        QMessageBox.warning(self, APP_NAME, text)

    # ---- project open / save ---------------------------------------------------------------
    def _confirm_discard(self) -> bool:
        if not self.project.dirty:
            return True
        choice = QMessageBox.question(
            self, APP_NAME, 'Save changes to "%s"?' % self.project.name,
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if choice == QMessageBox.StandardButton.Save:
            return self.save_project()
        return choice == QMessageBox.StandardButton.Discard

    def _load_project(self, project: Project):
        self.runner.stop(quiet=True)
        self._on_stopped("Idle", log=False)
        self.tabs.close_all()
        self.problems.clear_all()
        self.preview.display.clear_frame()
        self.project = project
        self._symbols_stale = True
        self.workspace.refresh(project)
        self.runtime_panel.set_status("Idle", project.entry)
        self.runtime_panel.reset_stats()
        py_files = [f for f in project.files() if f.endswith(".py")]
        if project.is_file(project.entry):
            self.open_file(project.entry)
        elif py_files:
            self.open_file(py_files[0])
        self._diag_pending.update(py_files)
        self._diag_timer.start()
        self._update_title()

    def new_project(self, template: str):
        if self._confirm_discard():
            self._load_project(templates.new_project(template))

    def open_project(self, path):
        if not self._confirm_discard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open project", os.path.expanduser("~"),
                                                  "Cardputer project (*%s)" % EXTENSION)
            if not path:
                return
        try:
            project = Project.load(path)
        except ProjectError as e:
            self._warn(str(e))
            return
        self._load_project(project)
        self.statusBar().showMessage("Opened %s" % path, 4000)

    def save_project(self) -> bool:
        if not self.project.path:
            return self.save_project_as()
        try:
            self.project.save()
        except (ProjectError, OSError) as e:
            self._warn("Couldn't save: %s" % e)
            return False
        self._update_title()
        self.statusBar().showMessage("Saved %s" % self.project.path, 4000)
        return True

    def save_project_as(self) -> bool:
        suggested = self.project.path or os.path.join(os.path.expanduser("~"), self.project.name + EXTENSION)
        path, _ = QFileDialog.getSaveFileName(self, "Save project", suggested, "Cardputer project (*%s)" % EXTENSION)
        if not path:
            return False
        if not path.lower().endswith(EXTENSION):
            path += EXTENSION
        self.project.name = Project.suggest_name(path)
        try:
            self.project.save(path)
        except (ProjectError, OSError) as e:
            self._warn("Couldn't save: %s" % e)
            return False
        self.workspace.refresh(self.project)
        self._update_title()
        self.statusBar().showMessage("Saved %s" % path, 4000)
        return True

    # ---- files and folders in the project ----------------------------------------------------
    def _ask(self, title: str, label: str, text: str = "") -> str:
        value, ok = QInputDialog.getText(self, title, label, text=text)
        return value.strip() if ok else ""

    def _refresh_tree(self, select: str | None = None):
        self._symbols_stale = True
        self.workspace.refresh(self.project)
        if select:
            self.workspace.select_path(select)
        self._update_title()

    def open_file(self, path: str, line: int = 0, col: int = 0):
        try:
            text = self.project.read_text(path)
        except ProjectError as e:
            self.console.append_text("%s\n" % e, "warn")
            self.statusBar().showMessage(str(e), 5000)
            return
        self.tabs.open_path(path, text, line or None, col)
        self.workspace.select_path(path)

    def new_file(self, parent_dir):
        if parent_dir is None:
            parent_dir = self.workspace.current_target_dir()
        name = self._ask("New File", "File name:", "new_file.py")
        if not name:
            return
        path = "%s/%s" % (parent_dir, name) if parent_dir else name
        try:
            if self.project.exists(path):
                self._warn("%s already exists." % path)
                return
            self.project.write_text(path, "")
        except ProjectError as e:
            self._warn(str(e))
            return
        self._refresh_tree(path)
        self.open_file(path)

    def new_folder(self, parent_dir):
        if parent_dir is None:
            parent_dir = self.workspace.current_target_dir()
        name = self._ask("New Folder", "Folder name:")
        if not name:
            return
        path = "%s/%s" % (parent_dir, name) if parent_dir else name
        try:
            self.project.make_dir(path)
        except ProjectError as e:
            self._warn(str(e))
            return
        self._refresh_tree(path)

    def import_files(self, parent_dir):
        if parent_dir is None:
            parent_dir = self.workspace.current_target_dir()
        paths, _ = QFileDialog.getOpenFileNames(self, "Import files into the project", os.path.expanduser("~"))
        last = None
        for src in paths:
            name = os.path.basename(src)
            dest = "%s/%s" % (parent_dir, name) if parent_dir else name
            try:
                if self.project.exists(dest):
                    self._warn("%s already exists; skipped." % dest)
                    continue
                with open(src, "rb") as f:
                    self.project.write_bytes(dest, f.read())
                last = dest
            except (ProjectError, OSError) as e:
                self._warn("Couldn't import %s: %s" % (name, e))
        if last:
            self._refresh_tree(last)

    def rename_path(self, path: str):
        new_name = self._ask("Rename", "New name:", posixpath.basename(path))
        if not new_name or new_name == posixpath.basename(path):
            return
        parent = posixpath.dirname(path)
        new_path = "%s/%s" % (parent, new_name) if parent else new_name
        try:
            self.project.rename(path, new_path)
        except ProjectError as e:
            self._warn(str(e))
            return
        self.tabs.rename_path(path, new_path)
        self.problems.rename_path(path, new_path)
        self._refresh_tree(new_path)

    def delete_path(self, path: str):
        answer = QMessageBox.question(self, "Delete", 'Delete "%s"? This can\'t be undone.' % path,
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        was_entry = path == self.project.entry or self.project.entry.startswith(path + "/")
        try:
            self.project.delete(path)
        except ProjectError as e:
            self._warn(str(e))
            return
        self.tabs.close_under(path)
        self.problems.forget_path(path)
        self._refresh_tree()
        if was_entry:
            self.statusBar().showMessage("The entry file was deleted: set a new one (right-click a .py file).", 8000)

    def set_entry(self, path: str):
        try:
            self.project.set_entry(path)
        except ProjectError as e:
            self._warn(str(e))
            return
        self._refresh_tree(path)
        self.runtime_panel.set_status("Idle", path)

    # ---- editing, diagnostics ----------------------------------------------------------------
    def _edit(self, method: str):
        target = QApplication.focusWidget()
        fn = getattr(target, method, None)
        if not callable(fn):
            target = self.tabs.current_editor()
            fn = getattr(target, method, None)
        if callable(fn):
            fn()

    def _editor_call(self, method: str):
        ed = self.tabs.current_editor()
        if ed is not None:
            getattr(ed, method)()

    def _show_find(self, replace: bool):
        self.findbar.set_editor(self.tabs.current_editor())
        self.findbar.show_find(replace)

    def _symbol_index(self) -> SymbolIndex:
        """Index of the project's functions and classes, rebuilt lazily after edits."""
        if self._symbols_stale:
            files = {p: self.project.read_text(p) for p in self.project.files() if p.endswith(".py")}
            self.symbols = SymbolIndex.build(files, self.api_names, previous=self.symbols)
            self._symbols_stale = False
        return self.symbols

    def _complete_at(self, path: str, text: str, offset: int):
        self._sync_open_text(path, text)
        return completion.complete(text, offset, path, self._symbol_index())

    def _hover_at(self, path: str, text: str, line: int, col: int):
        self._sync_open_text(path, text)
        return hover.hover_html(text, line, col, path, self._symbol_index())

    def _sync_open_text(self, path: str, text: str):
        """The editor text is authoritative; make sure the project (and index) agree with it."""
        try:
            if self.project.is_file(path) and self.project.read_text(path) != text:
                self.project.write_text(path, text)
                self._symbols_stale = True
        except ProjectError:
            pass

    def on_text_edited(self, path: str, text: str):
        self._symbols_stale = True
        try:
            self.project.write_text(path, text)
        except ProjectError as e:
            self.statusBar().showMessage(str(e), 5000)
            return
        self._update_title()
        if path.endswith(".py"):
            self._diag_pending.add(path)
            self._diag_timer.start()

    def _run_diagnostics(self):
        pending, self._diag_pending = self._diag_pending, set()
        for path in sorted(pending):
            if not self.project.is_file(path):
                continue
            try:
                text = self.project.read_text(path)
            except ProjectError:
                continue
            diagnostics = check_source(text, path, self.api_names)
            self.tabs.set_diagnostics(path, diagnostics)
            self.problems.set_diagnostics(path, diagnostics)

    def _jump_from_console(self, path: str, line: int):
        if self.project.is_file(path):
            self.open_file(path, line)

    # ---- running -----------------------------------------------------------------------------
    def run_project(self):
        if not self.project.is_file(self.project.entry):
            self._warn('The entry file "%s" doesn\'t exist. Right-click a .py file in the Workspace and choose '
                       '"Set as Entry Point".' % self.project.entry)
            return
        self.console.clear()
        self.preview.display.clear_frame()
        self.runtime_panel.reset_stats()
        try:
            self.runner.start(self.project)
        except (ProjectError, OSError) as e:
            self._warn("Couldn't start the preview: %s" % e)
            return
        self.preview.display.setFocus()

    def stop_project(self):
        self.runner.stop()

    def _on_started(self):
        self.act_stop.setEnabled(True)
        self.preview.display.set_running(True)
        self.preview.set_status("Running %s" % self.project.entry)
        self.runtime_panel.set_status("Running", self.project.entry)
        self.console.append_text("▶ Running %s\n" % self.project.entry, "info")

    def _on_stopped(self, reason: str, log: bool = True):
        self.act_stop.setEnabled(False)
        self.preview.display.set_running(False)
        self.preview.set_status(reason)
        self.runtime_panel.set_status(reason)
        if log and reason != "Idle":
            self.console.append_text("■ %s\n" % reason, "info")

    def export_firmware(self):
        try:
            firmware.export_firmware(self.project, "")
        except firmware.FirmwareExportNotImplemented:
            QMessageBox.information(self, "Export Firmware", firmware.PLACEHOLDER_MESSAGE)

    def export_api_docs(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export API reference",
                                              os.path.join(os.path.expanduser("~"), "cardputer_api.md"),
                                              "Markdown (*.md)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(api_docs.to_markdown())
        except OSError as e:
            self._warn("Couldn't write %s: %s" % (path, e))
            return
        self.statusBar().showMessage("Exported %s" % path, 4000)

    # ---- closing -----------------------------------------------------------------------------
    def closeEvent(self, event):
        if not self._confirm_discard():
            event.ignore()
            return
        self.runner.stop(quiet=True)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("state", self.saveState())
        event.accept()
