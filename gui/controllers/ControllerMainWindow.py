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
from PySide6.QtGui import QDesktopServices, QFont, QAction, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QWidget,
    QFileDialog,
    QInputDialog,
)

from core.UtilLogger import logger
from core.ModelBookmark import Node
from core.ServiceStorage import ConfigManager, load_bookmarks, save_bookmarks
from core.UtilCoreUtils import LRUCache, is_valid_url
from gui.components import (
    BookmarkListView,
    BookmarkCard,
    BookmarkRow,
    FolderTree,
    SearchBar,
    CustomPromptDialog,
    FolderSelectDialog,
    LeftPanel,
    TopBar,
    RightPanel,
    DetailPanel,
)
from services.WorkerNetwork import fetch_preview, fix_titles
from services.legacy.ServiceAiClassifierLegacy import AIBookmarkClassifier, BookmarkNode
from services.ServicePlans import build_rules_plan
from gui.UtilGuiResources import Typography, WindowSize
from gui.ModelAppState import AppState
from gui.controllers.ControllerTree import TreeController
from gui.controllers.ControllerSearch import SearchController
from gui.controllers.ControllerSession import SessionController
from gui.controllers.ControllerTreeUi import TreeUIController
from gui.controllers.ControllerUiEvent import UIEventController
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

        # ==================== Commands ====================

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
            debounce_ms=200,
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
        # Use project root logs/ directory (not gui/logs/)
        project_root = Path(__file__).resolve().parent.parent.parent
        log_path = project_root / "logs" / "bookmark_editor.log"
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
        """Create application menu bar."""
        self._create_file_menu()
        self._create_edit_menu()
        self._create_tools_menu()
        self._create_view_menu()
    
    def _create_file_menu(self) -> None:
        """Create File menu."""
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        
        open_action = QAction("&Open HTML...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.cmd_open)
        file_menu.addAction(open_action)

        save_action = QAction("&Save", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.cmd_save)
        file_menu.addAction(save_action)

        save_as_action = QAction("Save &As...", self)
        save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_as_action.triggered.connect(self.cmd_save_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
    
    def _create_edit_menu(self) -> None:
        """Create Edit menu."""
        menubar = self.menuBar()
        edit_menu = menubar.addMenu("&Edit")
        
        new_folder_action = QAction("New &Folder", self)
        new_folder_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        new_folder_action.triggered.connect(self.cmd_new_folder)
        edit_menu.addAction(new_folder_action)

        new_bookmark_action = QAction("New &Bookmark", self)
        new_bookmark_action.setShortcut(QKeySequence.StandardKey.New)
        new_bookmark_action.triggered.connect(self.cmd_new_bookmark)
        edit_menu.addAction(new_bookmark_action)

        rename_action = QAction("&Rename", self)
        rename_action.setShortcut(QKeySequence("F2"))
        rename_action.triggered.connect(self.cmd_rename)
        edit_menu.addAction(rename_action)

        edit_url_action = QAction("Edit &URL", self)
        edit_url_action.triggered.connect(self.cmd_edit_url)
        edit_menu.addAction(edit_url_action)

        edit_menu.addSeparator()

        move_action = QAction("&Move to Folder...", self)
        move_action.triggered.connect(self.cmd_move_to_folder)
        edit_menu.addAction(move_action)

        move_up_action = QAction("Move &Up", self)
        move_up_action.setShortcut(QKeySequence("Ctrl+Up"))
        move_up_action.triggered.connect(self.cmd_move_up)
        edit_menu.addAction(move_up_action)

        delete_action = QAction("&Delete", self)
        delete_action.setShortcut(QKeySequence.StandardKey.Delete)
        delete_action.triggered.connect(self.cmd_delete)
        edit_menu.addAction(delete_action)
    
    def _create_tools_menu(self) -> None:
        """Create Tools menu."""
        menubar = self.menuBar()
        tools_menu = menubar.addMenu("&Tools")
        
        proxy_action = QAction("Use Proxy", self, checkable=True)
        proxy_action.setChecked(self.use_proxy)
        proxy_action.triggered.connect(
            lambda checked: self.feature_flags.set_flag("proxy_enabled", checked)
        )
        tools_menu.addAction(proxy_action)

        test_proxy_action = QAction("Test Proxy Connection", self)
        test_proxy_action.triggered.connect(self.cmd_check_proxy)
        tools_menu.addAction(test_proxy_action)

        tools_menu.addSeparator()

        classify_action = QAction("Rule-based Classification...", self)
        classify_action.triggered.connect(self.cmd_show_classify_preview)
        tools_menu.addAction(classify_action)

        smart_classify_action = QAction("AI Smart Classification...", self)
        smart_classify_action.triggered.connect(self.cmd_smart_classify)
        tools_menu.addAction(smart_classify_action)

        tools_menu.addSeparator()

        fix_titles_action = QAction("Fix Titles from URL", self)
        fix_titles_action.triggered.connect(self.cmd_fix_titles_from_url)
        tools_menu.addAction(fix_titles_action)
    
    def _create_view_menu(self) -> None:
        """Create View menu."""
        menubar = self.menuBar()
        view_menu = menubar.addMenu("&View")
        
        self.card_mode_action = QAction("&Card Mode", self, checkable=True)
        self.card_mode_action.setChecked(self.view_mode == "card")
        self.card_mode_action.triggered.connect(
            lambda: self.cmd_set_view_mode("card")
        )
        view_menu.addAction(self.card_mode_action)

        self.list_mode_action = QAction("&List Mode", self, checkable=True)
        self.list_mode_action.setChecked(self.view_mode == "list")
        self.list_mode_action.triggered.connect(
            lambda: self.cmd_set_view_mode("list")
        )
        view_menu.addAction(self.list_mode_action)

        view_menu.addSeparator()
        
        self.dual_tree_action = QAction("Two-Pane Tree Mode", self, checkable=True)
        self.dual_tree_action.setChecked(self.dual_tree_mode)
        self.dual_tree_action.triggered.connect(self._set_dual_tree_mode)
        view_menu.addAction(self.dual_tree_action)

    def _build_ui(self) -> None:
        """Build main layout with TopBar + splitter panels (delegated)."""
        self.topbar = TopBar(dual_tree_mode=self.dual_tree_mode, view_mode=self.view_mode)
        self.topbar.search_text_changed.connect(self.search_controller.on_text_changed)
        self.topbar.search_triggered.connect(self.search_controller.on_triggered)
        self.topbar.toggle_dual_tree.connect(self._set_dual_tree_mode)

        # Backward compatibility: allow existing code to update chip/button
        self.mode_chip = self.topbar.mode_chip
        # dual_tree_buttonはLeftPanel側のツリーヘッダーに移設するため、あとで差し替える
        self.dual_tree_button = self.topbar.dual_tree_button
        try:
            self.topbar.dual_tree_button.setVisible(False)
        except Exception:
            pass

        self.left_panel = self._create_left_panel()
        self.right_panel = self._create_right_panel()

        # 2画面モードボタンはツリーヘッダー側を正とする（メニュー操作時の同期対象もこちら）
        if hasattr(self.left_panel, "dual_tree_button") and self.left_panel.dual_tree_button is not None:
            self.dual_tree_button = self.left_panel.dual_tree_button
            try:
                self.dual_tree_button.setChecked(bool(self.dual_tree_mode))
            except Exception:
                pass

        self._install_main_layout()

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
            "set_dual_tree_mode": self._set_dual_tree_mode,
            "get_dual_tree_mode": lambda: self.dual_tree_mode,
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
        self.bookmark_list_view.delete_requested.connect(self._delete_node)
        self.bookmark_list_view.preview_fetch_requested.connect(self._enqueue_preview_fetch)
        
        # Connect expand/collapse signals
        left_panel.expand_all.connect(self.cmd_expand_all)
        left_panel.collapse_all.connect(self.cmd_collapse_all)
        left_panel.expand_current.connect(self.cmd_expand_current)
        left_panel.collapse_current.connect(self.cmd_collapse_current)
        
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
        # ツリー再構築後に展開状態を復元
        self._restore_tree_expansion_state()

    def refresh_list(self) -> None:
        """Update only the bookmark list display."""
        nodes = self._get_display_nodes(
            current_folder=self.current_folder,
            search_query=self.search_query,
            search_hits=set(self.search_hits or set()),
        )
        self._refresh_list_internal(
            bookmark_list_view=self.bookmark_list_view,
            detail_panel=self.detail_panel,
            preview_cache=self.preview_cache,
            nodes=nodes,
            view_mode=self.view_mode,
            preview_requester=self.bookmark_list_view.request_preview_fetch,
        )

    def refresh_counts(self) -> None:
        """Update only the bookmark count labels."""
        total = self._count_bookmarks(self.root_node)
        self._update_counts(
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

    # ----------------------------- File Commands ------------------------------
    def cmd_open(self) -> None:
        """Open bookmark HTML file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open HTML", "", "HTML Files (*.html);;All Files (*)"
        )
        if not file_path:
            return

        try:
            root, rules, rules_path = load_bookmarks(file_path)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to open file:\n{exc}")
            return

        self.set_root_node_state(root)
        self.set_rules_state(rules, rules_path)
        self.set_current_file_state(file_path)
        self.current_folder = root
        self.selected_node = None

        # search index build is done only on open
        self.search_service.rebuild(root)
        self.refresh_tree(select_node=root)
        self.refresh_list()
        self.refresh_counts()
        
        # HTML読み込み完了後に拡大縮小ボタンを表示
        if hasattr(self, 'left_panel') and hasattr(self.left_panel, 'tree_controls'):
            self.left_panel.tree_controls.setVisible(True)

        # Remember last file
        self.config_manager.set("Session", "last_bookmarks_file", file_path)
        self.statusBar().showMessage(f"Loaded {file_path}", 4000)

    def cmd_save(self) -> None:
        """Save bookmark HTML file."""
        if not self.current_file:
            self.cmd_save_as()
            return

        try:
            save_bookmarks(self.current_file, self.root_node, self.rules)
            self.statusBar().showMessage(f"Saved to {self.current_file}", 4000)
            self.config_manager.set(
                "Session", "last_bookmarks_file", self.current_file
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save:\n{exc}")

    def cmd_save_as(self) -> None:
        """Save bookmark HTML file with new name."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save As", "", "HTML Files (*.html);;All Files (*)"
        )
        if not file_path:
            return

        self.current_file = file_path
        self.cmd_save()
        self.config_manager.set("Session", "last_bookmarks_file", file_path)

    # ----------------------------- Bookmark Commands ------------------------------
    def cmd_new_folder(self) -> None:
        """Create new folder with user input."""
        if not self.current_folder or self.current_folder.type != "folder":
            QMessageBox.warning(self, "Warning", "Select a folder first.")
            return
        
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if not ok or not name.strip():
            return
        
        new_node = Node("folder", name.strip())
        self.current_folder.append(new_node)
        
        # Folders don't need search index update, just refresh tree and counts
        self.refresh_tree(select_node=new_node)
        self.refresh_counts()

    def cmd_new_bookmark(self) -> None:
        """Create new bookmark with user input."""
        if not self.current_folder or self.current_folder.type != "folder":
            QMessageBox.warning(self, "Warning", "Select a folder first.")
            return
        
        url, ok = QInputDialog.getText(self, "New Bookmark", "URL:")
        if not ok or not url.strip():
            return
        
        if not is_valid_url(url.strip()):
            QMessageBox.warning(self, "Warning", "Enter a valid URL (http/https).")
            return
        
        title, _ = QInputDialog.getText(self, "New Bookmark", "Title (optional):")
        node = Node("bookmark", title=title.strip() or url.strip(), url=url.strip())
        self.current_folder.append(node)
        
        # Add to search index and refresh
        self.search_service.add_node(node)
        self.refresh_list()
        self.refresh_counts()

        self._enqueue_preview_fetch(node)

    def cmd_rename(self) -> None:
        """Rename selected bookmark or folder."""
        if not self.selected_node:
            QMessageBox.information(self, "Info", "Select an item to rename.")
            return
        
        name, ok = QInputDialog.getText(
            self,
            "Rename",
            "New name:",
            text=self.selected_node.title
        )
        if not ok or not name.strip():
            return
        
        self.selected_node.title = name.strip()
        
        # Update search index and refresh
        self.search_service.update_node(self.selected_node)
        self.refresh_list()
        self.refresh_counts()
        
        # If renaming folder, update tree
        if self.selected_node.type == "folder":
            self.refresh_tree(select_node=self.selected_node)

    def cmd_edit_url(self) -> None:
        """Edit URL of selected bookmark."""
        if not self.selected_node or self.selected_node.type != "bookmark":
            QMessageBox.information(self, "Info", "Select a bookmark to edit.")
            return
        
        url, ok = QInputDialog.getText(
            self,
            "Edit URL",
            "URL:",
            text=self.selected_node.url
        )
        if not ok or not url.strip():
            return
        
        if not is_valid_url(url.strip()):
            QMessageBox.warning(self, "Warning", "Enter a valid URL.")
            return
        
        self.selected_node.url = url.strip()
        
        # Update search index and refresh list only
        self.search_service.update_node(self.selected_node)
        self.refresh_list()
        self.refresh_counts()

    def cmd_move_to_folder(self) -> None:
        """Move selected bookmark/folder to target folder."""
        if not self.selected_node or not self.root_node:
            QMessageBox.information(self, "Info", "Select an item to move.")
            return
        
        dialog = FolderSelectDialog(
            self,
            root_node=self.root_node,
            exclude_nodes=[self.selected_node]
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.result:
            return
        
        target_folder = dialog.result
        if target_folder.type != "folder":
            QMessageBox.warning(self, "Warning", "Target must be a folder.")
            return

        # Serviceに集約（木構造の不変条件をService側で担保）
        try:
            self.bookmark_service.move(self.selected_node, target_folder)
        except Exception as exc:
            QMessageBox.warning(self, "Warning", f"Move failed: {exc}")
            return

        self.current_folder = target_folder
        
        # Move doesn't change search index (title/url unchanged), just refresh tree and list
        self.refresh_tree(select_node=target_folder)
        self.refresh_list()
        self.refresh_counts()

    def cmd_move_up(self) -> None:
        """Move selected item up in siblings."""
        if not self.selected_node or not self.selected_node.parent:
            return

        try:
            self.bookmark_service.move_up(self.selected_node)
        except Exception:
            return

        # 並び替えはリスト表示にも影響するため両方更新
        self.refresh_tree(select_node=self.selected_node)
        self.refresh_list()

    def cmd_delete(self) -> None:
        """Delete selected bookmark/folder."""
        if not self.selected_node:
            QMessageBox.information(self, "Info", "Select an item to delete.")
            return

        self._delete_node(self.selected_node)

    def _delete_node(self, node: Node) -> None:
        """Delete a bookmark or folder node."""
        if not node or not node.parent:
            return

        res = QMessageBox.question(
            self,
            "Delete",
            f"Delete '{node.title}'?",
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        parent = node.parent

        # Update search index (bookmarks only)
        if node.type == "bookmark":
            self.search_service.remove_node(node)
        elif node.type == "folder":
            # Remove all bookmarks in subtree from search index
            for bm in self._iter_bookmarks(node):
                self.search_service.remove_node(bm)

        parent.remove_child(node)

        self.refresh_tree(select_node=parent)
        self.refresh_list()
        self.refresh_counts()
        self.statusBar().showMessage(f"Deleted: {node.title}", 2000)

    def _iter_bookmarks(self, node: Node):
        """Iterate over all bookmarks in a node subtree."""
        for child in getattr(node, "children", []) or []:
            if child.type == "bookmark":
                yield child
            elif child.type == "folder":
                yield from self._iter_bookmarks(child)

    def cmd_delete_duplicates(self) -> None:
        """Delete duplicate bookmarks in current folder."""
        if not self.current_folder:
            return
        
        removed = self.bookmark_service.delete_duplicates(self.current_folder)
        
        # Rebuild search since multiple nodes were deleted
        self.search_service.rebuild(self.root_node)
        self.refresh_list()
        self.refresh_tree(select_node=self.current_folder)
        self.refresh_counts()
        self.statusBar().showMessage(f"Removed {removed} duplicate bookmarks", 3000)

    def cmd_merge_duplicate_folders(self) -> None:
        """Merge duplicate folders in current folder."""
        if not self.current_folder:
            return
        
        removed = self.bookmark_service.merge_duplicate_folders(self.current_folder)
        
        # Rebuild search since structure changed
        self.search_service.rebuild(self.root_node)
        self.refresh_tree(select_node=self.current_folder)
        self.refresh_list()
        self.refresh_counts()
        self.statusBar().showMessage(f"Merged {removed} duplicate folders", 3000)

    def cmd_expand_all(self) -> None:
        """Expand all folders in the tree view(s) and save the state."""
        trees_to_update = []
        if self.app_state.dual_tree_mode:
            if hasattr(self, 'folder_tree_left') and self.folder_tree_left:
                trees_to_update.append(self.folder_tree_left)
            if hasattr(self, 'folder_tree_right') and self.folder_tree_right:
                trees_to_update.append(self.folder_tree_right)
        else:
            if hasattr(self, 'folder_tree') and self.folder_tree:
                trees_to_update.append(self.folder_tree)
        
        # すべてのツリーを展開
        for tree in trees_to_update:
            tree.expandAll()
        
        # 展開状態を保存（最初のツリーの状態を使用）
        if trees_to_update:
            self._save_tree_expansion_state(trees_to_update[0])

    def cmd_collapse_all(self) -> None:
        """Collapse all folders in the tree view(s) and save the state."""
        trees_to_update = []
        if self.app_state.dual_tree_mode:
            if hasattr(self, 'folder_tree_left') and self.folder_tree_left:
                trees_to_update.append(self.folder_tree_left)
            if hasattr(self, 'folder_tree_right') and self.folder_tree_right:
                trees_to_update.append(self.folder_tree_right)
        else:
            if hasattr(self, 'folder_tree') and self.folder_tree:
                trees_to_update.append(self.folder_tree)
        
        # すべてのツリーを縮小
        for tree in trees_to_update:
            tree.collapseAll()
        
        # 展開状態を保存（最初のツリーの状態を使用）
        if trees_to_update:
            self._save_tree_expansion_state(trees_to_update[0])

    def cmd_expand_current(self) -> None:
        """Expand the currently selected folder in the tree view(s)."""
        current_folder = self.current_folder
        if not current_folder or current_folder.type != "folder":
            return
        
        # 現在のツリーを取得（2画面モードの場合は適切なツリーを選択）
        trees_to_update = []
        if self.app_state.dual_tree_mode:
            # 2画面モードの場合、左右両方のツリーを更新
            if hasattr(self, 'folder_tree_left') and self.folder_tree_left:
                trees_to_update.append(self.folder_tree_left)
            if hasattr(self, 'folder_tree_right') and self.folder_tree_right:
                trees_to_update.append(self.folder_tree_right)
        else:
            # 通常モードの場合、単一のツリーを更新
            if hasattr(self, 'folder_tree') and self.folder_tree:
                trees_to_update.append(self.folder_tree)
        
        # 各ツリーで現在のフォルダに対応するアイテムを展開
        for tree in trees_to_update:
            item = self._find_tree_item_by_node(tree, current_folder)
            if item:
                tree.expandItem(item)

    def cmd_collapse_current(self) -> None:
        """Collapse the currently selected folder in the tree view(s)."""
        current_folder = self.current_folder
        if not current_folder or current_folder.type != "folder":
            return
        
        # 現在のツリーを取得（2画面モードの場合は適切なツリーを選択）
        trees_to_update = []
        if self.app_state.dual_tree_mode:
            # 2画面モードの場合、左右両方のツリーを更新
            if hasattr(self, 'folder_tree_left') and self.folder_tree_left:
                trees_to_update.append(self.folder_tree_left)
            if hasattr(self, 'folder_tree_right') and self.folder_tree_right:
                trees_to_update.append(self.folder_tree_right)
        else:
            # 通常モードの場合、単一のツリーを更新
            if hasattr(self, 'folder_tree') and self.folder_tree:
                trees_to_update.append(self.folder_tree)
        
        # 各ツリーで現在のフォルダに対応するアイテムを縮小
        for tree in trees_to_update:
            item = self._find_tree_item_by_node(tree, current_folder)
            if item:
                tree.collapseItem(item)

    def _find_tree_item_by_node(self, tree: FolderTree, node: Node) -> Optional[Any]:
        """Find QTreeWidgetItem by Node in the tree."""
        from PySide6.QtWidgets import QTreeWidgetItem
        
        def walk(item: QTreeWidgetItem) -> Optional[QTreeWidgetItem]:
            item_node = item.data(0, Qt.ItemDataRole.UserRole)
            if item_node is node:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found:
                    return found
            return None
        
        for i in range(tree.topLevelItemCount()):
            found = walk(tree.topLevelItem(i))
            if found:
                return found
        return None

    def _get_folder_path(self, node: Node) -> str:
        """Get folder path from root to node (e.g., 'Root/Folder1/SubFolder')."""
        path_parts = []
        current = node
        while current and current.parent:
            path_parts.insert(0, current.title or "Untitled")
            current = current.parent
        # ルートは含めない
        return "/".join(path_parts) if path_parts else ""

    def _save_tree_expansion_state(self, tree: FolderTree) -> None:
        """Save tree expansion state to config.ini."""
        from PySide6.QtWidgets import QTreeWidgetItem
        import json
        
        expanded_paths = []
        
        def collect_expanded(item: QTreeWidgetItem):
            node = item.data(0, Qt.ItemDataRole.UserRole)
            if node and node.type == "folder" and item.isExpanded():
                path = self._get_folder_path(node)
                if path:  # ルートは保存しない
                    expanded_paths.append(path)
            for i in range(item.childCount()):
                collect_expanded(item.child(i))
        
        for i in range(tree.topLevelItemCount()):
            collect_expanded(tree.topLevelItem(i))
        
        # config.iniに保存
        expanded_json = json.dumps(expanded_paths, ensure_ascii=False)
        self.config_manager.set("Session", "tree_expanded_paths", expanded_json)
        self.logger.debug(f"Saved tree expansion state: {len(expanded_paths)} folders")

    def _restore_tree_expansion_state(self) -> None:
        """Restore tree expansion state from config.ini."""
        import json
        
        # 展開状態を読み込む
        expanded_json = self.config_manager.get("Session", "tree_expanded_paths", "")
        if not expanded_json:
            return
        
        try:
            expanded_paths = json.loads(expanded_json)
        except (json.JSONDecodeError, TypeError):
            self.logger.warning("Failed to parse tree expansion state")
            return
        
        if not expanded_paths:
            return
        
        # 復元対象のツリーを取得
        trees_to_restore = []
        if self.app_state.dual_tree_mode:
            if hasattr(self, 'folder_tree_left') and self.folder_tree_left:
                trees_to_restore.append(self.folder_tree_left)
            if hasattr(self, 'folder_tree_right') and self.folder_tree_right:
                trees_to_restore.append(self.folder_tree_right)
        else:
            if hasattr(self, 'folder_tree') and self.folder_tree:
                trees_to_restore.append(self.folder_tree)
        
        # 各ツリーで展開状態を復元
        for tree in trees_to_restore:
            self._apply_expansion_state_to_tree(tree, expanded_paths)

    def _apply_expansion_state_to_tree(self, tree: FolderTree, expanded_paths: List[str]) -> None:
        """Apply expansion state to a tree widget."""
        from PySide6.QtWidgets import QTreeWidgetItem
        
        # パスからNodeへのマッピングを作成
        path_to_node = {}
        def build_path_map(node: Node, current_path: str = ""):
            if node.type == "folder":
                if current_path:
                    path_to_node[current_path] = node
                for child in node.children:
                    if child.type == "folder":
                        child_path = f"{current_path}/{child.title or 'Untitled'}" if current_path else (child.title or "Untitled")
                        build_path_map(child, child_path)
        
        build_path_map(self.root_node)
        
        # 展開すべきパスのセットを作成
        expanded_set = set(expanded_paths)
        
        # ツリー内のアイテムを走査して展開
        def expand_items(item: QTreeWidgetItem):
            node = item.data(0, Qt.ItemDataRole.UserRole)
            if node and node.type == "folder":
                path = self._get_folder_path(node)
                if path in expanded_set:
                    tree.expandItem(item)
            for i in range(item.childCount()):
                expand_items(item.child(i))
        
        for i in range(tree.topLevelItemCount()):
            expand_items(tree.topLevelItem(i))

    # ----------------------------- Classification Commands ------------------------------
    def cmd_show_classify_preview(self) -> None:
        """Classify bookmarks using predefined rules."""
        base = self.current_folder if self.current_folder else self.root_node
        plan = build_rules_plan(base, self.rules or {})
        if not plan:
            QMessageBox.information(self, "Classify", "No rules or matching bookmarks.")
            return
        
        lines = [f"{folder}: {len(nodes)}" for folder, nodes in plan.items()]
        preview = "\n".join(lines)
        res = QMessageBox.question(
            self,
            "Rule-based Classification",
            preview + "\n\nApply this plan?"
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        
        for folder_name, nodes in plan.items():
            target = self.bookmark_service.find_or_create_folder(base, folder_name)
            for node in nodes:
                try:
                    self.bookmark_service.move_to_folder(node, target)
                except ValueError as e:
                    self.logger.warning(f"Failed to move {node.title}: {e}")
        
        # Structure changed, rebuild search and refresh
        self.search_service.rebuild(self.root_node)
        self.refresh_tree(select_node=base)
        self.refresh_list()
        self.refresh_counts()
        self.statusBar().showMessage("Rule-based classification applied", 4000)

    def cmd_smart_classify(self) -> None:
        """Classify bookmarks using AI."""
        base = self.current_folder if self.current_folder else self.root_node
        nodes = list(self.bookmark_service.iter_bookmarks(base))
        if not nodes:
            QMessageBox.information(self, "Classify", "No bookmarks to classify.")
            return

        # Get additional prompt from user
        dialog = CustomPromptDialog(self, title="追加指示（任意）", previous_prompts=[])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            additional_prompt = None
        else:
            additional_prompt = dialog.result or None

        try:
            classifier = AIBookmarkClassifier(
                config_path=str(self.config_manager.config_path)
            )
            priority_terms = self.config_manager.get_priority_terms()
            node_map: Dict[BookmarkNode, Node] = {}
            items: List[BookmarkNode] = []
            
            for node in nodes:
                bn = BookmarkNode(title=node.title or "", url=node.url or "")
                items.append(bn)
                node_map[bn] = node
            
            result = classifier.classify_bookmarks(
                items,
                priority_terms=priority_terms,
                max_items=self.max_smart_items,
                additional_prompt=additional_prompt,
            )
        except Exception as exc:
            QMessageBox.critical(self, "AI Classify", f"AI分類に失敗しました:\n{exc}")
            return

        if not result.plan:
            QMessageBox.information(self, "AI Classify", "分類結果が空でした。")
            return

        # Apply classification
        for folder_name, items in result.plan.items():
            target = self.bookmark_service.find_or_create_folder(base, folder_name)
            for item in items:
                node = node_map.get(item)
                if not node:
                    continue
                try:
                    self.bookmark_service.move_to_folder(node, target)
                except ValueError as e:
                    self.logger.warning(f"Failed to move {node.title}: {e}")

        # Structure changed, rebuild search and refresh
        self.search_service.rebuild(self.root_node)
        self.refresh_tree(select_node=base)
        self.refresh_list()
        self.refresh_counts()
        self.statusBar().showMessage("AI classification completed", 4000)

    # ----------------------------- Network Commands ------------------------------
    def cmd_check_proxy(self) -> None:
        """Check proxy settings."""
        settings = self.config_manager.get_proxy_settings()
        if not settings:
            QMessageBox.information(
                self,
                "Proxy",
                "Proxy is disabled or not configured."
            )
            return
        
        summary = settings.get("url", "")
        QMessageBox.information(self, "Proxy", f"Using proxy: {summary}")

    def cmd_fix_titles_from_url(self) -> None:
        """Fix bookmark titles by fetching from URLs."""
        self._enable_network_updates("タイトル取得")
        
        nodes = list(self.bookmark_service.iter_bookmarks(self.current_folder)) \
            if self.current_folder else []
        if not nodes:
            QMessageBox.information(self, "Info", "No bookmarks to update.")
            return

        # keep for search index update on completion
        self._titlefix_nodes = nodes
        
        proxy_info = self.config_manager.get_proxies_for_requests(
            use_proxy=self.use_proxy
        )
        self.statusBar().showMessage("Starting title fix...", 2000)
        self.worker_bus.submit(
            fix_titles,
            nodes,
            self.worker_bus.ui_queue,
            proxy_info,
            self.fetch_timeout,
            None,
            None
        )

    def cmd_fetch_preview(self) -> None:
        """Fetch preview for selected bookmark (on demand)."""
        if not self.selected_node or \
           self.selected_node.type != "bookmark":
            QMessageBox.information(
                self,
                "Info",
                "プレビュー取得はブックマークを選択してください。"
            )
            return
        
        self._enable_network_updates("プレビュー取得")
        self._enqueue_preview_fetch(self.selected_node)

    def _enable_network_updates(self, reason: str) -> None:
        """Enable network updates if disabled."""
        if not self.network_updates_enabled:
            self.network_updates_enabled = True
            self.statusBar().showMessage(f"ネットワーク更新を有効化: {reason}", 3000)

    def _enqueue_preview_fetch(self, node) -> None:
        """Enqueue preview fetch for a bookmark node."""
        if not node or not getattr(node, "url", None):
            return
        if not self.network_updates_enabled:
            return

        proxy_info = self.config_manager.get_proxies_for_requests(use_proxy=self.use_proxy)
        self.worker_bus.submit(
            fetch_preview,
            node.url,
            self.worker_bus.ui_queue,
            proxy_info,
            self.fetch_timeout,
        )

    # ----------------------------- View Commands ------------------------------
    def cmd_set_view_mode(self, mode: str) -> None:
        """Set view mode (card or list)."""
        if mode not in ("card", "list"):
            return

        self.view_mode = mode

        # Update checkboxes
        if hasattr(self, "card_mode_action"):
            self.card_mode_action.setChecked(mode == "card")
        if hasattr(self, "list_mode_action"):
            self.list_mode_action.setChecked(mode == "list")

        # Update top bar chip
        if hasattr(self, "topbar") and self.topbar is not None:
            self.topbar.set_view_mode(mode)
        elif hasattr(self, "mode_chip"):
            display_text = "Card" if mode == "card" else "List"
            self.mode_chip.setText(f"表示: {display_text}")

        # Update view toggle button styles
        if hasattr(self, "view_buttons"):
            for key, btn in self.view_buttons.items():
                btn.setObjectName("tonalButton" if key == mode else "ghostButton")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()

        # Refresh only list/counts (tree doesn't depend on view_mode)
        self.refresh_list()
        self.refresh_counts()
        self.statusBar().showMessage(f"Switched to {mode.title()} Mode", 2000)

    def _set_dual_tree_mode(self, enabled: bool) -> None:
        """Set dual tree mode (two-pane view)."""
        self.dual_tree_mode = bool(enabled)
        if hasattr(self, "dual_tree_action"):
            self.dual_tree_action.setChecked(self.dual_tree_mode)
        if hasattr(self, "dual_tree_button"):
            self.dual_tree_button.setChecked(self.dual_tree_mode)
            # ラベルは「現在の状態」ではなく「次の切り替え先」を表示
            # 2画面ON中は「1画面」、2画面OFF中は「2画面」
            try:
                self.dual_tree_button.setText("1画面" if self.dual_tree_mode else "2画面")
            except Exception:
                pass
        self.refresh_tree(select_node=self.current_folder or self.root_node)

    def _apply_sort(self, sort_by: str) -> None:
        """Apply sorting to current folder."""
        if not self.current_folder:
            return

        if sort_by == "title":
            self.bookmark_service.sort_children(self.current_folder, "title")
            self.statusBar().showMessage("Sorted by title", 2000)
        elif sort_by == "domain":
            self.bookmark_service.sort_children(self.current_folder, "domain")
            self.statusBar().showMessage("Sorted by domain", 2000)
        else:
            return

        self.refresh_tree(select_node=self.current_folder)
        self.refresh_list()

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

    def _install_main_layout(self) -> None:
        """Install the main layout (topbar + left/right splitter) into this QMainWindow."""
        from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget
        from PySide6.QtCore import Qt
        
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self.topbar)

        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        content_layout.addWidget(splitter)

        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.right_panel)

        splitter.setSizes([600, 300])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(content_widget, 1)

    def _get_display_nodes(
        self,
        *,
        current_folder: Optional[Node],
        search_query: str,
        search_hits: Set[Node],
    ) -> List[Node]:
        """Get nodes to display in the bookmark list view."""
        if not current_folder:
            return []

        base_nodes = [ch for ch in current_folder.children if ch.type == "bookmark"]
        if not search_query:
            return base_nodes

        filtered: List[Node] = []
        for node in search_hits:
            if self._is_descendant_of(node, current_folder):
                filtered.append(node)
        return filtered

    def _is_descendant_of(self, node: Node, folder: Node) -> bool:
        """Check if node is a descendant of folder."""
        cur = node.parent
        while cur:
            if cur is folder:
                return True
            cur = cur.parent
        return False

    def _iter_bookmarks(self, node: Node) -> Iterable[Node]:
        """Iterate over all bookmarks in the subtree."""
        for child in getattr(node, "children", []) or []:
            if child.type == "bookmark":
                yield child
            elif child.type == "folder":
                yield from self._iter_bookmarks(child)

    def _count_bookmarks(self, root_node: Optional[Node]) -> int:
        """Count total bookmarks in the tree."""
        if not root_node:
            return 0
        return sum(1 for _ in self._iter_bookmarks(root_node))

    def _refresh_list_internal(
        self,
        *,
        bookmark_list_view,
        detail_panel,
        preview_cache,
        nodes: List[Node],
        view_mode: str,
        preview_requester,
    ) -> None:
        """Internal method to refresh the bookmark list view."""
        bookmark_list_view.set_items(nodes, view_mode=view_mode)

        for node in nodes:
            if node.url and node.url not in preview_cache:
                preview_cache[node.url] = True
                preview_requester(node)

        if not nodes:
            detail_panel.clear()

    def _update_counts(self, *, bookmarks_count_label, workspace_count_label, total: int) -> None:
        """Update bookmark count labels."""
        if bookmarks_count_label is not None:
            bookmarks_count_label.setText(f"{total:,}")
        if workspace_count_label is not None:
            workspace_count_label.setText(f"{total:,}")


# Backward compatibility alias
App = MainWindow

