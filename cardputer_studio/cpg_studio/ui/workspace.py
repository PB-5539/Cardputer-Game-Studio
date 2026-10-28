"""Left panel: the project as a directory tree. All real changes are requested via signals and
carried out by the main window, which keeps the project, open tabs and tree in sync."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QTreeWidget, QTreeWidgetItem

from ..core.project import Project
from . import theme

PATH_ROLE = Qt.ItemDataRole.UserRole
KIND_ROLE = Qt.ItemDataRole.UserRole + 1


class WorkspaceTree(QTreeWidget):
    open_requested = Signal(str)
    new_file_requested = Signal(str)          # parent directory ('' = project root)
    new_folder_requested = Signal(str)
    import_requested = Signal(str)
    rename_requested = Signal(str)
    delete_requested = Signal(str)
    set_entry_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.itemActivated.connect(self._activated)
        style = QApplication.style()
        self._dir_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        self._file_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    # ---- building the tree ---------------------------------------------------------------
    def refresh(self, project: Project) -> None:
        expanded = self._expanded_paths()
        self.clear()
        root = QTreeWidgetItem([project.name.upper()])
        root.setData(0, PATH_ROLE, "")
        root.setData(0, KIND_ROLE, "root")
        font = QFont(root.font(0))
        font.setBold(True)
        root.setFont(0, font)
        self.addTopLevelItem(root)
        self._add_children(project, root, "", expanded)
        root.setExpanded(True)

    def _add_children(self, project: Project, parent: QTreeWidgetItem, directory: str, expanded: set) -> None:
        dirs, files = project.children(directory)
        for name in dirs:
            path = f"{directory}/{name}" if directory else name
            item = QTreeWidgetItem(parent, [name])
            item.setIcon(0, self._dir_icon)
            item.setData(0, PATH_ROLE, path)
            item.setData(0, KIND_ROLE, "dir")
            self._add_children(project, item, path, expanded)
            item.setExpanded(path in expanded or not expanded)
        for name in files:
            path = f"{directory}/{name}" if directory else name
            is_entry = path == project.entry
            item = QTreeWidgetItem(parent, [name + ("   ▶ entry" if is_entry else "")])
            item.setIcon(0, self._file_icon)
            item.setData(0, PATH_ROLE, path)
            item.setData(0, KIND_ROLE, "file")
            if is_entry:
                item.setForeground(0, QBrush(QColor(theme.ACCENT)))

    def _expanded_paths(self) -> set:
        out = set()

        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                if child.data(0, KIND_ROLE) == "dir":
                    if child.isExpanded():
                        out.add(child.data(0, PATH_ROLE))
                    walk(child)

        for i in range(self.topLevelItemCount()):
            walk(self.topLevelItem(i))
        return out

    def select_path(self, path: str) -> None:
        def walk(item):
            if item.data(0, PATH_ROLE) == path:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found:
                    return found
            return None

        for i in range(self.topLevelItemCount()):
            item = walk(self.topLevelItem(i))
            if item:
                self.setCurrentItem(item)
                return

    # ---- interaction ---------------------------------------------------------------------
    def _activated(self, item, _column):
        if item.data(0, KIND_ROLE) == "file":
            self.open_requested.emit(item.data(0, PATH_ROLE))

    def _target_dir(self, item) -> str:
        """Directory a 'New File' should go into for a click on `item`."""
        if item is None:
            return ""
        kind, path = item.data(0, KIND_ROLE), item.data(0, PATH_ROLE)
        if kind in ("root", "dir"):
            return path
        return path.rsplit("/", 1)[0] if "/" in path else ""

    def _context_menu(self, pos):
        item = self.itemAt(pos)
        kind = item.data(0, KIND_ROLE) if item else "root"
        path = item.data(0, PATH_ROLE) if item else ""
        target = self._target_dir(item)
        menu = QMenu(self)
        menu.addAction("New File…", lambda: self.new_file_requested.emit(target))
        menu.addAction("New Folder…", lambda: self.new_folder_requested.emit(target))
        menu.addAction("Import File…", lambda: self.import_requested.emit(target))
        if kind in ("file", "dir"):
            menu.addSeparator()
            menu.addAction("Rename…", lambda: self.rename_requested.emit(path))
            menu.addAction("Delete", lambda: self.delete_requested.emit(path))
        if kind == "file" and path.endswith(".py"):
            menu.addSeparator()
            menu.addAction("Set as Entry Point", lambda: self.set_entry_requested.emit(path))
        menu.exec(self.viewport().mapToGlobal(pos))

    def keyPressEvent(self, event):
        item = self.currentItem()
        if item and item.data(0, KIND_ROLE) in ("file", "dir"):
            if event.key() == Qt.Key.Key_F2:
                self.rename_requested.emit(item.data(0, PATH_ROLE))
                return
            if event.key() == Qt.Key.Key_Delete:
                self.delete_requested.emit(item.data(0, PATH_ROLE))
                return
        super().keyPressEvent(event)

    def current_target_dir(self) -> str:
        return self._target_dir(self.currentItem())
