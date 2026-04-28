"""
PySide6-based main window for NeoBookMarkManager (refactored).
Uses MainWindowCommandsMixin for command implementations, keeping this class focused on wiring.
"""

from __future__ import annotations

from typing import Optional
from pathlib import Path

from PySide6.QtWidgets import QMainWindow

from core.ModelBookmark import Node
from core.ServiceStorage import ConfigManager
from gui.controllers.ctl_main_commands import MainWindowCommandsMixin
from gui.controllers.ControllerTree import TreeController
from gui.ModelAppState import AppState
from gui.ui_components import TopBar, LeftPanel, RightPanel, FolderTree, BookmarkListView, DetailPanel
from services.ServiceSearch import SearchService
from services.ServiceBookmark import BookmarkService
from services.ServiceTags import TagService


class MainWindow(MainWindowCommandsMixin, QMainWindow):
    """Slim main window that wires UI components and state."""

    def __init__(self) -> None:
        super().__init__()

        self.app_state = AppState()
        self.root_node: Optional[Node] = self.app_state.root_node
        self.current_folder: Optional[Node] = self.app_state.current_folder
        self.selected_node: Optional[Node] = None
        self.search_query: str = ""
        self.search_hits = set()
        self.view_mode: str = "list"
        self.dual_tree_mode: bool = False
        self.network_updates_enabled: bool = False
        self.preview_cache = {}

        project_root = Path(__file__).resolve().parent.parent.parent
        self.config_manager = ConfigManager()
        self.search_service = SearchService()
        self.bookmark_service = BookmarkService()
        self.tag_service = TagService(project_root=project_root)

        self.tree_controller = TreeController()

        self.topbar = TopBar(dual_tree_mode=self.dual_tree_mode, view_mode=self.view_mode)
        self.left_panel = LeftPanel(callbacks={
            "get_dual_tree_mode": lambda: self.dual_tree_mode,
            "set_dual_tree_mode": lambda enabled: self._set_dual_tree_mode(bool(enabled)),
            "set_view_mode_list": lambda: self.cmd_set_view_mode("list"),
            "set_view_mode_card": lambda: self.cmd_set_view_mode("card"),
            "on_folder_selected": lambda node, tree: self._on_folder_selected(node, tree),
        })
        self.right_panel = RightPanel(callbacks={})

        self.folder_tree: FolderTree = self.left_panel.folder_tree
        self.folder_tree_left: FolderTree = self.left_panel.folder_tree_left
        self.folder_tree_right: FolderTree = self.left_panel.folder_tree_right
        self.bookmark_list_view: BookmarkListView = self.left_panel.bookmark_view
        self.detail_panel: DetailPanel = self.right_panel.get_detail_panel()

        self._install_main_layout()
        self._post_ui_built()

        try:
            self.topbar.search_triggered.connect(self._on_search_triggered)
            self.topbar.search_text_changed.connect(self._on_search_text_changed)
            self.topbar.toggle_dual_tree.connect(lambda checked: self._set_dual_tree_mode(bool(checked)))
        except Exception:
            pass

        try:
            self.detail_panel.edit_requested.connect(self._on_edit_bookmark)
            self.detail_panel.copy_url_requested.connect(self._open_url)
            self.detail_panel.move_requested.connect(lambda n: setattr(self, "selected_node", n) or self.cmd_move_to_folder())
            self.detail_panel.delete_requested.connect(lambda n: setattr(self, "selected_node", n) or self.cmd_delete())
            self.detail_panel.edit_tags_requested.connect(self._on_edit_tags)
        except Exception:
            pass

        try:
            self.bookmark_list_view.preview_fetch_requested.connect(self._enqueue_preview_fetch)
            self.bookmark_list_view.node_selected.connect(lambda n: setattr(self, "selected_node", n) or self.detail_panel.set_node(n))
        except Exception:
            pass

    def _on_search_triggered(self, text: str) -> None:
        self.search_query = text or ""
        self.search_hits = self.search_service.query(self.search_query)
        self.refresh_tree(select_node=self.current_folder or self.root_node)
        self.refresh_list()

    def _on_search_text_changed(self, text: str) -> None:
        self.search_query = text or ""
        self.search_hits = self.search_service.query(self.search_query)
        self.refresh_list()

    def _on_folder_selected(self, node: Node, source_tree: FolderTree) -> None:
        if node and node.type == "folder":
            self.current_folder = node
            self.tree_ui.sync_selection(node, source_tree)
            self.refresh_list()

    def set_root_node_state(self, root: Node) -> None:
        self.root_node = root
        self.current_folder = root
        self.selected_node = None
        self.search_query = ""
        self.search_hits = set()

    def set_rules_state(self, rules: list, rules_path: Optional[str]) -> None:
        self.rules = rules
        self.rules_path = rules_path

    def set_current_file_state(self, file_path: str) -> None:
        self.current_file = file_path


App = MainWindow
