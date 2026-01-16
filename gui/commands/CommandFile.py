"""File-related commands (open/save/save-as)."""

from PySide6.QtWidgets import QFileDialog, QMessageBox

from core.ServiceStorage import load_bookmarks, save_bookmarks


class FileCommands:
    """Commands for opening/saving bookmark files."""

    def __init__(self, window):
        self.window = window

    def open(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self.window, "Open HTML", "", "HTML Files (*.html);;All Files (*)"
        )
        if not file_path:
            return

        try:
            root, rules, rules_path = load_bookmarks(file_path)
        except Exception as exc:
            QMessageBox.critical(self.window, "Error", f"Failed to open file:\n{exc}")
            return

        self.window.set_root_node_state(root)
        self.window.set_rules_state(rules, rules_path)
        self.window.set_current_file_state(file_path)
        self.window.current_folder = root
        self.window.selected_node = None

        # search index build is done only on open
        self.window.search_service.rebuild(root)
        self.window.refresh_tree(select_node=root)
        self.window.refresh_list()
        self.window.refresh_counts()

        # Remember last file
        self.window.config_manager.set("Session", "last_bookmarks_file", file_path)
        self.window.statusBar().showMessage(f"Loaded {file_path}", 4000)

    def save(self) -> None:
        if not self.window.current_file:
            self.save_as()
            return

        try:
            save_bookmarks(self.window.current_file, self.window.root_node, self.window.rules)
            self.window.statusBar().showMessage(f"Saved to {self.window.current_file}", 4000)
            self.window.config_manager.set(
                "Session", "last_bookmarks_file", self.window.current_file
            )
        except Exception as exc:
            QMessageBox.critical(self.window, "Error", f"Failed to save:\n{exc}")

    def save_as(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self.window, "Save As", "", "HTML Files (*.html);;All Files (*)"
        )
        if not file_path:
            return

        self.window.current_file = file_path
        self.save()
        self.window.config_manager.set("Session", "last_bookmarks_file", file_path)
