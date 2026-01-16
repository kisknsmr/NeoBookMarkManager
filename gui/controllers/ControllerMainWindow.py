"""
PySide6-based main window for NeoBookMarkManager.
Material Design 3 layout with splitter-based 3-column structure.
"""

import os
import queue
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from core.UtilLogger import logger
from core.ModelBookmark import Node
from core.ServiceStorage import ConfigManager, load_bookmarks, save_bookmarks
from core.UtilCoreUtils import LRUCache, is_valid_url
from gui.layout.LayoutBookmarkListView import BookmarkListView
from gui.commands import CommandRegistry
from gui.layout.LayoutComponents import BookmarkCard, BookmarkRow, FolderTree, SearchBar
from gui.layout.LayoutDialogs import CustomPromptDialog, FolderSelectDialog
from gui.layout.LayoutPanelLeft import LeftPanel
from gui.layout.LayoutMainLayout import install_main_layout
from gui.layout.LayoutTopBar import TopBar
from gui.layout.LayoutMenus import MenuBuilder
from gui.presenters.PresenterBookmark import BookmarkPresenter
from gui.UtilGuiResources import Typography, WindowSize
from gui.layout.LayoutPanelRight import RightPanel, DetailPanel
from gui.ModelAppState import AppState
from gui.controllers.ControllerTree import TreeController
from gui.controllers.ControllerSearch import SearchController
from gui.controllers.ControllerSession import SessionController
from gui.controllers.ControllerTreeUi import TreeUIController
from gui.controllers.ControllerUiEvent import UIEventController
from services.legacy.ServiceAiClassifierLegacy import AIBookmarkClassifier, BookmarkNode
from services.ServiceBookmark import BookmarkService
from services.ServiceSearch import SearchService
from services.BusWorker import WorkerBus, WorkerEventHandler
from services.ServiceFeatureFlags import FeatureFlagManager


class MainWindow(QMainWindow):
    """Main application window (PySide6)."""

    # ==================== Properties (backward compatibility) ====================
    @property
    def root_node(self):
        return self.app_state.root_node

    @property
    def current_file(self):
        return self.app_state.current_file

    @current_file.setter
    def current_file(self, path: Optional[str]):
        self.app_state.set_current_file(path)

    @property
    def rules(self):
        return self.app_state.rules

    @property
    def rules_path(self):
        return self.app_state.rules_path

    @property
    def current_folder(self):
        return self.app_state.current_folder

    @current_folder.setter
    def current_folder(self, node: Optional[Node]):
        self.app_state.set_current_folder(node)

    @property
    def selected_node(self):
        return self.app_state.selected_node

    @selected_node.setter
    def selected_node(self, node: Optional[Node]):
        self.app_state.set_selected_node(node)

    @property
    def search_query(self):
        return self.app_state.search_query

    @property
    def search_hits(self):
        return self.app_state.search_hits

    @property
    def use_proxy(self):
        return self.feature_flags.flags().proxy_enabled

    @property
    def view_mode(self):
        return self.app_state.view_mode

    @view_mode.setter
    def view_mode(self, mode: str):
        self.app_state.set_view_mode(mode)

    @property
    def dual_tree_mode(self):
        return self.app_state.dual_tree_mode

    @dual_tree_mode.setter
    def dual_tree_mode(self, value: bool):
        self.app_state.set_dual_tree_mode(value)

    @property
    def network_updates_enabled(self):
        return self.feature_flags.flags().network_enabled

    @network_updates_enabled.setter
    def network_updates_enabled(self, value: bool):
        self.feature_flags.set_flag("network_enabled", value)

    # ==================== Setter Methods ====================
    def set_root_node_state(self, node: Node):
        """Set root node."""
        self.app_state.set_root_node(node)

    def set_current_file_state(self, path: Optional[str]):
        """Set current file."""
        self.app_state.set_current_file(path)

    def set_rules_state(self, rules: list, path: Optional[str] = None):
        """Set rules."""
        self.app_state.set_rules(rules, path)

    def __init__(self) -> None:
        super().__init__()

        # logging and config
        self.logger = logger
        self._setup_logging()
        self.config_manager = ConfigManager()

        # ==================== Service Layer ====================
        self.app_state = AppState()
        self.bookmark_service = BookmarkService()
        self.search_service = SearchService()
        self.feature_flags = FeatureFlagManager.get()

        # ==================== Legacy UI State (gradual migration) ====================
        self.card_to_node: Dict[Any, Node] = {}
        self.preview_cache = LRUCache(maxsize=50)
        self.ui_queue: "queue.Queue[Any]" = queue.Queue()
        self.max_smart_items = 300
        self.progress_history: List[Any] = []
        self._titlefix_nodes: List[Node] = []

        # ==================== Tree Controller ====================
        self.tree_controller = TreeController()

        # ==================== Presenter ====================
        self.presenter = BookmarkPresenter()

        # ==================== Commands ====================
        self.commands = CommandRegistry(self)

        # ==================== Controllers ====================
        self.session_controller = SessionController(
            window=self,
            config=self.config_manager,
            load_bookmarks=load_bookmarks,
            default_rules=self._default_rules,
        )
        self.search_controller = SearchController(
            window=self,
            app_state=self.app_state,
            search_service=self.search_service,
            debounce_ms=300,
            parent=self,
        )
        self.ui_events = UIEventController(window=self)

        # ==================== Async related (UI state) ====================
        self._smart_dialog = None
        self._smart_cancelled = False
        self._titlefix_dialog = None
        self._titlefix_cancelled = False
        self.fetch_timeout = 10
        self._load_dialog = None
        self._load_cancelled = False

        # ==================== Worker Bus ====================
        self.worker_bus = WorkerBus(ui_queue=self.ui_queue, logger=self.logger, qt_parent=self)
        self.worker_bus.on_event(
            WorkerEventHandler(
                search_service=self.search_service,
                refresh_list=self.refresh_list,
                status_message=self.statusBar().showMessage,
                titlefix_nodes_getter=lambda: self._titlefix_nodes,
                titlefix_nodes_setter=lambda nodes: setattr(self, "_titlefix_nodes", nodes),
            ).handle
        )

        # build UI
        self._setup_ui()
        self._create_menu_bar()
        self._build_ui()

        # start worker polling
        self.worker_bus.start()

    # ---------------------------- UI construction ----------------------------
    def _setup_ui(self) -> None:
        """Basic window setup and stylesheet loading."""
        self.setWindowTitle("Bookmark Studio — Chrome Bookmarks Organizer")
        self.resize(WindowSize.DEFAULT_WIDTH, WindowSize.DEFAULT_HEIGHT)
        self.setMinimumSize(WindowSize.MIN_WIDTH, WindowSize.MIN_HEIGHT)

        style_path = Path(__file__).parent / "style.qss"
        if style_path.exists():
            with open(style_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())

    def _setup_logging(self) -> None:
        """Set up file logging at WARNING level or above."""
        from logging.handlers import RotatingFileHandler
        import logging

        for handler in self.logger.handlers:
            if isinstance(handler, RotatingFileHandler):
                return

        log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        log_path = Path(__file__).resolve().parent.parent / "logs" / "bookmark_editor.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=1024 * 1024,
            backupCount=2,
            encoding="utf-8",
        )
        file_handler.setFormatter(log_formatter)
        file_handler.setLevel(logging.WARNING)
        self.logger.addHandler(file_handler)
        self.logger.setLevel(logging.WARNING)

    def _create_menu_bar(self) -> None:
        """Create application menu bar using MenuBuilder."""
        callbacks = {
            "cmd_open": self.cmd_open,
            "cmd_save": self.cmd_save,
            "cmd_save_as": self.cmd_save_as,
            "cmd_new_folder": self.cmd_new_folder,
            "cmd_new_bookmark": self.cmd_new_bookmark,
            "cmd_rename": self.cmd_rename,
            "cmd_edit_url": self.cmd_edit_url,
            "cmd_move_to_folder": self.cmd_move_to_folder,
            "cmd_move_up": self.cmd_move_up,
            "cmd_delete": self.cmd_delete,
            "set_proxy_flag": lambda checked: self.feature_flags.set_flag("proxy_enabled", checked),
            "cmd_check_proxy": self.cmd_check_proxy,
            "cmd_show_classify_preview": self.cmd_show_classify_preview,
            "cmd_smart_classify": self.cmd_smart_classify,
            "cmd_fix_titles_from_url": self.cmd_fix_titles_from_url,
            "cmd_set_view_mode": self.cmd_set_view_mode,
            "_set_dual_tree_mode": self._set_dual_tree_mode,
        }
        
        builder = MenuBuilder(self)
        builder.build_menus(callbacks)
        
        # Store action references from builder
        self.card_mode_action = builder.card_mode_action
        self.list_mode_action = builder.list_mode_action
        self.dual_tree_action = builder.dual_tree_action

    def _build_ui(self) -> None:
        """Build main layout with TopBar + splitter panels (delegated)."""
        self.topbar = TopBar(dual_tree_mode=self.dual_tree_mode, view_mode=self.view_mode)
        self.topbar.search_text_changed.connect(self.search_controller.on_text_changed)
        self.topbar.search_triggered.connect(self.search_controller.on_triggered)
        self.topbar.toggle_dual_tree.connect(self._set_dual_tree_mode)
        self.topbar.expand_all.connect(self.cmd_expand_all)
        self.topbar.collapse_all.connect(self.cmd_collapse_all)

        # Backward compatibility: allow existing code to update chip/button
        self.mode_chip = self.topbar.mode_chip
        self.dual_tree_button = self.topbar.dual_tree_button

        self.left_panel = self._create_left_panel()
        self.right_panel = self._create_right_panel()

        install_main_layout(window=self, topbar=self.topbar, left_panel=self.left_panel, right_panel=self.right_panel)

        self._post_ui_built()

        self.statusBar().showMessage("Ready")
        self.refresh_counts()

    def _create_left_panel(self) -> QWidget:
        """Create left panel using LeftPanel component."""
        callbacks = {
            "on_folder_selected": self.ui_events.on_folder_selected,
            "on_tree_node_moved": self.ui_events.on_tree_node_moved,
            "set_view_mode_list": lambda: self.cmd_set_view_mode("list"),
            "set_view_mode_card": lambda: self.cmd_set_view_mode("card"),
        }
        
        left_panel = LeftPanel(callbacks=callbacks)
        
        # Store references for backward compatibility
        self.bookmarks_count_label = left_panel.bookmarks_count_label
        self.workspace_count_label = left_panel.workspace_count_label
        self.view_buttons = left_panel.view_buttons
        self.folder_tree = left_panel.folder_tree
        self.folder_tree_left = left_panel.folder_tree_left
        self.folder_tree_right = left_panel.folder_tree_right
        self.tree_scroll = left_panel.tree_scroll
        self.dual_tree_splitter = left_panel.dual_tree_splitter
        self.cards_scroll = left_panel.cards_scroll
        self.left_splitter = left_panel.left_splitter
        
        # Bookmark list view with signals
        self.bookmark_list_view = left_panel.get_bookmark_list_view()
        self.bookmark_list_view.node_selected.connect(self.ui_events.on_bookmark_node_selected)
        self.bookmark_list_view.open_requested.connect(self._open_url)
        self.bookmark_list_view.delete_requested.connect(self.commands.bookmark.delete_node)
        self.bookmark_list_view.preview_fetch_requested.connect(self.commands.network.enqueue_preview_fetch)
        
        return left_panel

    def _create_right_panel(self) -> QWidget:
        """Create right action panel with all sections using RightPanel."""
        callbacks = {
            "file": [
                ("別名保存", self.cmd_save_as),
                ("保存", self.cmd_save),
                ("開く", self.cmd_open),
            ],
            "edit": [
                ("新規フォルダ", self.cmd_new_folder),
                ("新規ブックマーク", self.cmd_new_bookmark),
                ("名前変更", self.cmd_rename),
                ("URL編集", self.cmd_edit_url),
                ("プレビュー取得", self.cmd_fetch_preview),
                ("移動", self.cmd_move_to_folder),
                ("削除", self.cmd_delete),
            ],
            "organize": [
                ("タイトル順", lambda: self._apply_sort("title")),
                ("ドメイン順", lambda: self._apply_sort("domain")),
                ("上へ移動", self.cmd_move_up),
                ("重複削除", self.cmd_delete_duplicates),
                ("フォルダ統合", self.cmd_merge_duplicate_folders),
            ],
            "ai": [
                ("スマート分類", self.cmd_smart_classify),
                ("ルール分類", self.cmd_show_classify_preview),
                ("ルール編集", self.cmd_show_classify_preview),
                ("上限設定", self.cmd_save),
                ("タイトル取得", self.cmd_fix_titles_from_url),
            ],
        }
        
        panel = RightPanel(callbacks=callbacks)
        self.actions_container = panel.actions_container
        self.detail_panel = panel.get_detail_panel()
        
        # Connect detail panel signals
        self.detail_panel.edit_requested.connect(self.ui_events.on_detail_edit)
        self.detail_panel.copy_url_requested.connect(self._copy_to_clipboard)
        self.detail_panel.move_requested.connect(self.ui_events.on_detail_move)
        self.detail_panel.delete_requested.connect(self.ui_events.on_detail_delete)
        
        return panel

    # ------------------------------ window events ----------------------------
    def showEvent(self, event: Any) -> None:
        """Auto-load last bookmarks file on first window show."""
        super().showEvent(event)

        self.session_controller.on_first_show()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._resize_right_pane()

    def _resize_right_pane(self) -> None:
        if not hasattr(self, "right_panel"):
            return
        if not hasattr(self, "actions_container") or not hasattr(self, "detail_panel"):
            return
        available = self.right_panel.height()
        if available <= 0:
            return
        target = max(200, available // 2)
        self.actions_container.setMinimumHeight(target)
        self.detail_panel.setMinimumHeight(target)
    
    def _apply_dual_tree_visibility(self) -> None:
        if hasattr(self, "tree_scroll"):
            self.tree_scroll.setVisible(not self.dual_tree_mode)
        if hasattr(self, "dual_tree_splitter"):
            self.dual_tree_splitter.setVisible(self.dual_tree_mode)

    def _open_url(self, url: str) -> None:
        if not url:
            return
        QDesktopServices.openUrl(QUrl(url))

    def _copy_to_clipboard(self, text: str) -> None:
        """Copy text to clipboard."""
        if not text:
            return
        clipboard = self.app.clipboard() if hasattr(self, 'app') else None
        if clipboard:
            clipboard.setText(text)
            self.statusBar().showMessage("URLをコピーしました", 2000)
        else:
            # Fallback: try to get clipboard from QApplication
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage("URLをコピーしました", 2000)

    def refresh_tree(self, select_node: Optional[Node] = None) -> None:
        """
        Update only the tree display (called when folder structure changes).
        
        Args:
            select_node: Node to select in the tree (default: current_folder)
        """
        if not hasattr(self, "tree_ui"):
            return
        self._apply_dual_tree_visibility()
        self.tree_ui.refresh(select_node=select_node)

    def refresh_list(self) -> None:
        """Update only the bookmark list display."""
        nodes = self.presenter.get_display_nodes(
            current_folder=self.current_folder,
            search_query=self.search_query,
            search_hits=set(self.search_hits or set()),
        )
        self.presenter.refresh_list(
            bookmark_list_view=self.bookmark_list_view,
            detail_panel=self.detail_panel,
            preview_cache=self.preview_cache,
            nodes=nodes,
            view_mode=self.view_mode,
            preview_requester=self.bookmark_list_view.request_preview_fetch,
        )

    def refresh_counts(self) -> None:
        """Update only the bookmark count labels."""
        total = self.presenter.count_bookmarks(self.root_node)
        self.presenter.update_counts(
            bookmarks_count_label=getattr(self, "bookmarks_count_label", None),
            workspace_count_label=getattr(self, "workspace_count_label", None),
            total=total,
        )

    def _after_model_changed(self, select_node: Optional[Node] = None, refresh_parts: str = "all") -> None:
        """
        Unified handler for model changes. Call this INSTEAD of manually calling _build_search_index + _refresh_*.
        
        Args:
            select_node: Node to focus on after refresh (for tree selection)
            refresh_parts: "all" | "trees" | "list"
                - "all": Full rebuild (model structure changed)
                - "trees": Tree structure changed
                - "list": Only list/search results changed
        """
        if refresh_parts in ("all", "trees"):
            self.refresh_tree(select_node=select_node)
        
        if refresh_parts in ("all", "list"):
            self.refresh_list()
        
        self.refresh_counts()

    def _default_rules(self) -> list:
        return []

    # ----------------------------- commands ------------------------------
    def cmd_open(self) -> None:
        self.commands.file.open()

    def cmd_save(self) -> None:
        self.commands.file.save()

    def cmd_save_as(self) -> None:
        self.commands.file.save_as()

    # ----------------------------- command delegation ----------------------------
    def cmd_new_folder(self) -> None:
        """Delegate to bookmark commands."""
        self.commands.bookmark.new_folder()

    def cmd_new_bookmark(self) -> None:
        """Delegate to bookmark commands."""
        self.commands.bookmark.new_bookmark()

    def cmd_rename(self) -> None:
        """Delegate to bookmark commands."""
        self.commands.bookmark.rename()

    def cmd_edit_url(self) -> None:
        """Delegate to bookmark commands."""
        self.commands.bookmark.edit_url()

    def cmd_move_to_folder(self) -> None:
        """Delegate to bookmark commands."""
        self.commands.bookmark.move_to_folder()

    def cmd_move_up(self) -> None:
        """Delegate to bookmark commands."""
        self.commands.bookmark.move_up()

    def cmd_delete(self) -> None:
        """Delegate to bookmark commands."""
        self.commands.bookmark.delete()

    def cmd_expand_all(self) -> None:
        """Expand all folders (placeholder)."""
        QMessageBox.information(self, "Expand", "Expand all folders functionality.")

    def cmd_collapse_all(self) -> None:
        """Collapse all folders (placeholder)."""
        QMessageBox.information(self, "Collapse", "Collapse all folders functionality.")

    def cmd_check_proxy(self) -> None:
        """Delegate to network commands."""
        self.commands.network.check_proxy()

    def _delete_node(self, node: Node) -> None:
        # Backward compatibility shim; prefer BookmarkCommands.delete_node
        self.commands.bookmark.delete_node(node)


    def cmd_show_classify_preview(self) -> None:
        """Delegate to classify commands."""
        self.commands.classify.rule_classify()

    def cmd_smart_classify(self) -> None:
        """Delegate to classify commands."""
        self.commands.classify.ai_classify()

    def cmd_delete_duplicates(self) -> None:
        """Delegate to bookmark commands."""
        self.commands.bookmark.delete_duplicates()

    def cmd_merge_duplicate_folders(self) -> None:
        """Delegate to bookmark commands."""
        removed = self.commands.bookmark.merge_duplicate_folders()
        if removed > 0:
            self.statusBar().showMessage(f"Merged {removed} duplicate folders", 3000)


    def cmd_set_view_mode(self, mode: str) -> None:
        self.commands.view.set_view_mode(mode)

    def _set_dual_tree_mode(self, enabled: bool) -> None:
        self.dual_tree_mode = bool(enabled)
        if hasattr(self, "dual_tree_action"):
            self.dual_tree_action.setChecked(self.dual_tree_mode)
        if hasattr(self, "dual_tree_button"):
            self.dual_tree_button.setChecked(self.dual_tree_mode)
        self.refresh_tree(select_node=self.current_folder or self.root_node)

    def _apply_sort(self, sort_by: str) -> None:
        self.commands.view.sort(sort_by)

    def cmd_fix_titles_from_url(self) -> None:
        """Delegate to network commands."""
        self.commands.network.fix_titles_from_url()

    def cmd_fetch_preview(self) -> None:
        """Delegate to network commands."""
        self.commands.network.fetch_preview()

    def _post_ui_built(self) -> None:
        """Initialize controllers that need widget references."""
        self.tree_ui = TreeUIController(
            tree_controller=self.tree_controller,
            get_root=lambda: self.root_node,
            get_current_folder=lambda: self.current_folder,
            get_search_hits=lambda: self.search_hits,
            get_search_query=lambda: self.search_query,
            get_dual_tree_mode=lambda: self.dual_tree_mode,
            get_trees=self._get_visible_trees,
            get_all_trees=self._get_all_trees,
        )

    def _get_visible_trees(self):
        trees = [self.folder_tree]
        if self.dual_tree_mode:
            trees.extend([self.folder_tree_left, self.folder_tree_right])
        return trees

    def _get_all_trees(self):
        return [self.folder_tree, self.folder_tree_left, self.folder_tree_right]


# Backward compatibility alias
App = MainWindow

