"""Session and search controllers consolidated (ctl_ prefix)."""

from __future__ import annotations

import os
from typing import Callable

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
            if hasattr(self.window, "left_panel") and hasattr(self.window.left_panel, "tree_controls"):
                self.window.left_panel.tree_controls.setVisible(True)

    def auto_load_bookmarks(self, file_path: str) -> None:
        try:
            from pathlib import Path
            from core.DatabaseManager import DatabaseManager
            project_root = Path(__file__).resolve().parent.parent.parent
            config_path = Path(getattr(self.config, "config_path", project_root / "config" / "config.ini"))
            DatabaseManager(project_root=project_root).migrate_if_needed(
                bookmarks_html=Path(file_path),
                config_ini=config_path,
                keep_generations=30,
            )
            root, rules, rules_path = self._load_bookmarks(file_path)
            if root is None or not isinstance(root, Node):
                self.window.logger.error("Auto-load failed: invalid root node")
                return
            try:
                self.window.bookmark_service.ensure_bookmark_ids(root)
            except Exception:
                pass
            self.window.set_root_node_state(root)
            self.window.set_rules_state(rules or self._default_rules(), rules_path)
            self.window.set_current_file_state(file_path)
            self.window.current_folder = root
            self.window.selected_node = None
            self.window.search_service.rebuild(root)
            self.window.refresh_tree(select_node=root)
            self.window.refresh_list()
            self.window.refresh_counts()
            if hasattr(self.window, "left_panel") and hasattr(self.window.left_panel, "tree_controls"):
                self.window.left_panel.tree_controls.setVisible(True)
            if hasattr(self.window, "left_panel") and hasattr(self.window.left_panel, "dual_tree_button"):
                try:
                    self.window.left_panel.dual_tree_button.setVisible(True)
                except Exception:
                    pass
            self.window.statusBar().showMessage(f"Loaded: {os.path.basename(file_path)}", 5000)
            self.window.logger.info(f"Auto-loaded bookmarks: {file_path}")
        except Exception as exc:
            self.window.logger.error(f"Failed to auto-load bookmarks: {exc}")
            if hasattr(self.window, "left_panel") and hasattr(self.window.left_panel, "tree_controls"):
                self.window.left_panel.tree_controls.setVisible(True)


class SearchController:
    def __init__(
        self,
        *,
        window,
        app_state,
        search_service,
        debounce_ms: int = 200,
        parent=None,
    ) -> None:
        from PySide6.QtCore import QTimer as _QTimer

        self.window = window
        self.app_state = app_state
        self.search_service = search_service
        self.debounce_ms = int(debounce_ms)
        self._pending_query = ""
        self._query_timer = _QTimer(parent or window)
        self._query_timer.setSingleShot(True)
        self._query_timer.timeout.connect(self.apply_pending)
        self._tree_timer = _QTimer(parent or window)
        self._tree_timer.setSingleShot(True)
        self._tree_timer.timeout.connect(self.refresh_tree_if_needed)

    def on_text_changed(self, query: str) -> None:
        self._pending_query = query
        self._query_timer.stop()
        delay_ms = 80 if not query.strip() else self.debounce_ms
        self._query_timer.start(max(0, int(delay_ms)))

    def on_triggered(self, query: str) -> None:
        self._query_timer.stop()
        self._pending_query = query
        self.apply_query(query)
        self.window.refresh_list()
        self.window.refresh_counts()
        self.window.refresh_tree(select_node=self.window.current_folder or self.window.root_node)

    def apply_pending(self) -> None:
        query = self._pending_query
        self.apply_query(query)
        self.window.refresh_list()
        self.window.refresh_counts()
        delay_ms = 80 if not query.strip() else self.debounce_ms
        self.schedule_tree_refresh(delay_ms=delay_ms)

    def schedule_tree_refresh(self, *, delay_ms: int = 200) -> None:
        self._tree_timer.stop()
        self._tree_timer.start(max(0, int(delay_ms)))

    def refresh_tree_if_needed(self) -> None:
        self.window.refresh_tree(select_node=self.window.current_folder or self.window.root_node)

    def apply_query(self, query: str) -> None:
        self.app_state.set_search_query(query)
        if not query.strip():
            self.app_state.search_hits.clear()
            return
        hits = self.search_service.query(query)
        self.app_state.search_hits = hits