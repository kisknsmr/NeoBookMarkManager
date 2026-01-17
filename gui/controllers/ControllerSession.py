"""Session controller.

Moves auto-load (showEvent) responsibilities out of MainWindow.
"""

import os
from typing import Callable, Optional

from PySide6.QtCore import QTimer

from core.ModelBookmark import Node


class SessionController:
    def __init__(
        self,
        *,
        window,
        config,
        load_bookmarks: Callable,
        default_rules: Callable[[], list],
    ) -> None:
        self.window = window
        self.config = config
        self._load_bookmarks = load_bookmarks
        self._default_rules = default_rules
        self._startup_complete = False

    def on_first_show(self) -> None:
        if self._startup_complete:
            return
        self._startup_complete = True

        last_file = self.config.get("Session", "last_bookmarks_file", "")
        if last_file and os.path.exists(last_file):
            QTimer.singleShot(100, lambda: self.auto_load_bookmarks(last_file))
        else:
            # HTMLファイルが存在しない場合でも拡大縮小ボタンを表示
            if hasattr(self.window, 'left_panel') and hasattr(self.window.left_panel, 'tree_controls'):
                self.window.left_panel.tree_controls.setVisible(True)
            # 2画面モードボタンも表示（ロードが無い場合はここで解禁）
            if hasattr(self.window, "left_panel") and hasattr(self.window.left_panel, "dual_tree_button"):
                try:
                    self.window.left_panel.dual_tree_button.setVisible(True)
                except Exception:
                    pass

    def auto_load_bookmarks(self, file_path: str) -> None:
        try:
            root, rules, rules_path = self._load_bookmarks(file_path)
            if root is None or not isinstance(root, Node):
                self.window.logger.error("Auto-load failed: invalid root node")
                return

            self.window.set_root_node_state(root)
            self.window.set_rules_state(rules or self._default_rules(), rules_path)
            self.window.set_current_file_state(file_path)
            self.window.current_folder = root
            self.window.selected_node = None

            # search index build is done only on load
            self.window.search_service.rebuild(root)

            self.window.refresh_tree(select_node=root)
            self.window.refresh_list()
            self.window.refresh_counts()
            
            # HTML読み込み完了後に拡大縮小ボタンを表示
            if hasattr(self.window, 'left_panel') and hasattr(self.window.left_panel, 'tree_controls'):
                self.window.left_panel.tree_controls.setVisible(True)
            # HTML読み込み完了後に2画面モードボタンを表示
            if hasattr(self.window, "left_panel") and hasattr(self.window.left_panel, "dual_tree_button"):
                try:
                    self.window.left_panel.dual_tree_button.setVisible(True)
                except Exception:
                    pass

            self.window.statusBar().showMessage(f"Loaded: {os.path.basename(file_path)}", 5000)
            self.window.logger.info(f"Auto-loaded bookmarks: {file_path}")
        except Exception as exc:
            self.window.logger.error(f"Failed to auto-load bookmarks: {exc}")
            # エラーが発生した場合でも拡大縮小ボタンを表示
            if hasattr(self.window, 'left_panel') and hasattr(self.window.left_panel, 'tree_controls'):
                self.window.left_panel.tree_controls.setVisible(True)
            # エラー時でも2画面モードボタンを表示
            if hasattr(self.window, "left_panel") and hasattr(self.window.left_panel, "dual_tree_button"):
                try:
                    self.window.left_panel.dual_tree_button.setVisible(True)
                except Exception:
                    pass