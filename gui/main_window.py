"""
PySide6-based main window for NeoBookMarkManager.
Material Design 3 layout with splitter-based 3-column structure.
"""

import os
import queue
import re
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import urlparse

from PySide6.QtCore import QTimer, Qt, QUrl, QSignalBlocker
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QGridLayout,
)

from core.logger import logger
from core.model import Node
from core.storage import ConfigManager, load_bookmarks, save_bookmarks
from core.utils import LRUCache, is_valid_url
from gui.components import BookmarkCard, BookmarkRow, DetailPanel, FolderTree, SearchBar
from gui.dialogs import CustomPromptDialog, FolderSelectDialog
from gui.resources import Typography, WindowSize
from gui.state import AppState
from services.legacy.ai_classifier import AIBookmarkClassifier, BookmarkNode
from services.bookmark import BookmarkService
from services.search import SearchService
from services.events import WorkerEvent, PreviewFetchedEvent, TitleFixDoneEvent, event_from_tuple
from services.workers import fetch_preview, fix_titles


class MainWindow(QMainWindow):
    """Main application window (PySide6)."""

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

        # ==================== Legacy UI State (gradual migration) ====================
        self.card_to_node: Dict[Any, Node] = {}
        self.selected_cards: Set[Any] = set()
        self.preview_cache = LRUCache(maxsize=50)
        self.ui_queue: "queue.Queue[Any]" = queue.Queue()
        self.max_smart_items = 300
        self.progress_history: List[Any] = []
        self._startup_complete = False
        self._building_tree = False

        # ==================== Shortcuts to app state ====================
        # (For backward compatibility during migration)
        @property
        def root_node(self):
            return self.app_state.root_node

        @property
        def current_file(self):
            return self.app_state.current_file

        @property
        def rules(self):
            return self.app_state.rules

        @property
        def rules_path(self):
            return self.app_state.rules_path

        @property
        def current_folder(self):
            return self.app_state.current_folder

        @property
        def selected_node(self):
            return self.app_state.selected_node

        @property
        def search_query(self):
            return self.app_state.search_query

        @property
        def search_hits(self):
            return self.app_state.search_hits

        @property
        def use_proxy(self):
            return self.app_state.use_proxy

        @property
        def view_mode(self):
            return self.app_state.view_mode

        @property
        def dual_tree_mode(self):
            return self.app_state.dual_tree_mode

        # Setters
        def set_root_node_state(self, node: Node):
            self.app_state.set_root_node(node)

        def set_current_file_state(self, path: Optional[str]):
            self.app_state.set_current_file(path)

        def set_rules_state(self, rules: list, path: Optional[str] = None):
            self.app_state.set_rules(rules, path)

        # ==================== Async related ====================
        self._smart_dialog = None
        self._smart_cancelled = False
        self._titlefix_dialog = None
        self._titlefix_cancelled = False
        self.fetch_timeout = 10
        self._load_dialog = None
        self._load_cancelled = False

        # build UI
        self._setup_ui()
        self._create_menu_bar()
        self._build_ui()

        # delayed search index build
        QTimer.singleShot(500, self._build_search_index)

        # start polling
        self._start_polling()

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
        """Create application menu bar."""
        menubar = self.menuBar()

        # File menu
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

        # Edit menu
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

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        proxy_action = QAction("Use Proxy", self, checkable=True)
        proxy_action.setChecked(self.use_proxy)
        proxy_action.triggered.connect(lambda checked: setattr(self, "use_proxy", checked))
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

        # View menu
        view_menu = menubar.addMenu("&View")
        card_mode_action = QAction("&Card Mode", self, checkable=True)
        card_mode_action.setChecked(self.view_mode == "card")
        card_mode_action.triggered.connect(lambda: self.cmd_set_view_mode("card"))
        view_menu.addAction(card_mode_action)

        list_mode_action = QAction("&List Mode", self, checkable=True)
        list_mode_action.setChecked(self.view_mode == "list")
        list_mode_action.triggered.connect(lambda: self.cmd_set_view_mode("list"))
        view_menu.addAction(list_mode_action)

        view_menu.addSeparator()
        dual_tree_action = QAction("Two-Pane Tree Mode", self, checkable=True)
        dual_tree_action.setChecked(self.dual_tree_mode)
        dual_tree_action.triggered.connect(self._set_dual_tree_mode)
        view_menu.addAction(dual_tree_action)

        self.card_mode_action = card_mode_action
        self.list_mode_action = list_mode_action
        self.dual_tree_action = dual_tree_action

    def _build_ui(self) -> None:
        """Build main layout with topbar + splitter panels."""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Top bar
        main_layout.addWidget(self._create_topbar())
        
        # Content area
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        content_layout.addWidget(splitter)

        self.left_panel = self._create_left_panel()
        splitter.addWidget(self.left_panel)

        self.right_panel = self._create_right_panel()
        splitter.addWidget(self.right_panel)

        splitter.setSizes([600, 300])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        
        main_layout.addWidget(content_widget, 1)

        self.statusBar().showMessage("Ready")
        self._update_bookmark_count()

    def _create_topbar(self) -> QFrame:
        """Create top bar with brand, chips, and actions."""
        topbar = QFrame()
        topbar.setObjectName("topbar")
        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(12)
        
        # Brand section
        brand_label = QLabel("📑 Bookmark Studio")
        brand_font = QFont(Typography.FONT_FAMILY, 12)
        brand_font.setBold(True)
        brand_label.setFont(brand_font)
        layout.addWidget(brand_label)
        
        # Chip: version
        chip1 = QLabel("v1.0")
        chip1.setObjectName("chip")
        layout.addWidget(chip1)

        # Search bar
        self.search_bar = SearchBar()
        self.search_bar.search_triggered.connect(self._on_search)
        self.search_bar.search_text_changed.connect(self._on_search)
        layout.addWidget(self.search_bar, 1)
        
        # Spacer
        layout.addStretch()
        
        # Right actions
        dual_btn = QPushButton("2画面モード")
        dual_btn.setCheckable(True)
        dual_btn.setChecked(self.dual_tree_mode)
        dual_btn.setObjectName("chip")
        dual_btn.clicked.connect(lambda checked: self._set_dual_tree_mode(checked))
        layout.addWidget(dual_btn)
        self.dual_tree_button = dual_btn
        
        # View mode chip
        display_text = "Card" if self.view_mode == "card" else "List"
        mode_chip = QLabel(f"表示: {display_text}")
        mode_chip.setObjectName("chip")
        self.mode_chip = mode_chip
        layout.addWidget(mode_chip)
        
        # Expand all button
        expand_btn = QPushButton("すべて展開")
        expand_btn.setObjectName("outlineButton")
        expand_btn.setMaximumHeight(30)
        expand_btn.setMinimumWidth(80)
        expand_btn.clicked.connect(self.cmd_expand_all)
        layout.addWidget(expand_btn)
        
        # Collapse all button
        collapse_btn = QPushButton("すべて縮小")
        collapse_btn.setObjectName("ghostButton")
        collapse_btn.setMaximumHeight(30)
        collapse_btn.setMinimumWidth(80)
        collapse_btn.clicked.connect(self.cmd_collapse_all)
        layout.addWidget(collapse_btn)
        
        return topbar

    def _create_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("leftPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Header with title
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)
        
        header = QLabel("📁 Bookmarks")
        header_font = Typography.get_title_font()
        header.setFont(header_font)
        header.setObjectName("panelHeader")
        header_layout.addWidget(header)

        count_label = QLabel("0")
        count_label.setObjectName("chip")
        header_layout.addWidget(count_label)
        self.bookmarks_count_label = count_label
        
        header_layout.addStretch()
        layout.addWidget(header_widget)

        # Workspace header with view toggle (above main view)
        workspace_header = QWidget()
        workspace_layout = QHBoxLayout(workspace_header)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(12)
        
        workspace_title = QLabel("Bookmarks")
        workspace_title.setObjectName("panelHeader")
        workspace_layout.addWidget(workspace_title)

        workspace_count = QLabel("0")
        workspace_count.setObjectName("chip")
        workspace_layout.addWidget(workspace_count)
        self.workspace_count_label = workspace_count
        
        workspace_layout.addStretch()
        
        list_btn = QPushButton("List")
        list_btn.setObjectName("ghostButton")
        list_btn.setMaximumWidth(60)
        list_btn.setMaximumHeight(30)
        list_btn.clicked.connect(lambda: self.cmd_set_view_mode("list"))
        workspace_layout.addWidget(list_btn)

        card_btn = QPushButton("Card")
        card_btn.setObjectName("tonalButton")
        card_btn.setMaximumWidth(60)
        card_btn.setMaximumHeight(30)
        card_btn.clicked.connect(lambda: self.cmd_set_view_mode("card"))
        workspace_layout.addWidget(card_btn)

        self.view_buttons = {
            "list": list_btn,
            "card": card_btn,
        }
        
        layout.addWidget(workspace_header)

        # Folder tree (tree view)
        self.folder_tree = FolderTree()
        self.folder_tree.item_selected.connect(lambda node: self._on_folder_selected(node, self.folder_tree))
        self.folder_tree.node_moved.connect(self._on_tree_node_moved)

        tree_scroll = QScrollArea()
        tree_scroll.setWidgetResizable(True)
        tree_scroll.setObjectName("treeScroll")
        tree_scroll.setWidget(self.folder_tree)
        tree_scroll.setVisible(False)
        layout.addWidget(tree_scroll, 1)
        self.tree_scroll = tree_scroll

        # Dual tree mode (two panes)
        self.folder_tree_left = FolderTree()
        self.folder_tree_left.item_selected.connect(
            lambda node: self._on_folder_selected(node, self.folder_tree_left)
        )
        self.folder_tree_left.node_moved.connect(self._on_tree_node_moved)

        self.folder_tree_right = FolderTree()
        self.folder_tree_right.item_selected.connect(
            lambda node: self._on_folder_selected(node, self.folder_tree_right)
        )
        self.folder_tree_right.node_moved.connect(self._on_tree_node_moved)

        left_tree_scroll = QScrollArea()
        left_tree_scroll.setWidgetResizable(True)
        left_tree_scroll.setObjectName("treeScrollLeft")
        left_tree_scroll.setWidget(self.folder_tree_left)

        right_tree_scroll = QScrollArea()
        right_tree_scroll.setWidgetResizable(True)
        right_tree_scroll.setObjectName("treeScrollRight")
        right_tree_scroll.setWidget(self.folder_tree_right)

        dual_tree_splitter = QSplitter(Qt.Orientation.Horizontal)
        dual_tree_splitter.addWidget(left_tree_scroll)
        dual_tree_splitter.addWidget(right_tree_scroll)
        dual_tree_splitter.setSizes([400, 400])
        dual_tree_splitter.setStretchFactor(0, 1)
        dual_tree_splitter.setStretchFactor(1, 1)
        dual_tree_splitter.setVisible(False)
        self.dual_tree_splitter = dual_tree_splitter

        # Main view (cards/list)
        self.cards_container = QFrame()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(8, 8, 8, 8)
        self.cards_layout.setSpacing(12)

        cards_scroll = QScrollArea()
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setObjectName("contentScroll")
        cards_scroll.setWidget(self.cards_container)
        self.cards_scroll = cards_scroll

        # Split tree (top) and cards/list (bottom)
        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.setSpacing(0)
        tree_layout.addWidget(tree_scroll)
        tree_layout.addWidget(dual_tree_splitter)

        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(tree_container)
        left_splitter.addWidget(cards_scroll)
        left_splitter.setStretchFactor(0, 1)
        left_splitter.setStretchFactor(1, 1)
        left_splitter.setSizes([350, 350])
        layout.addWidget(left_splitter, 1)
        self.left_splitter = left_splitter

        return panel

    def _create_right_panel(self) -> QWidget:
        """Create right action panel with multiple sections."""
        panel = QFrame()
        panel.setObjectName("rightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("actionScroll")
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(8, 8, 8, 8)
        scroll_layout.setSpacing(8)
        
        actions_container = QFrame()
        actions_layout = QVBoxLayout(actions_container)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        self.actions_container = actions_container

        # File Actions Section
        actions_layout.addWidget(self._create_action_section(
            "📁 ファイル",
            "高",
            [
                ("別名保存", self.cmd_save_as),
                ("保存", self.cmd_save),
                ("開く", self.cmd_open),
            ]
        ))
        
        # Edit Actions Section
        actions_layout.addWidget(self._create_action_section(
            "✏️ 編集",
            "中",
            [
                ("新規フォルダ", self.cmd_new_folder),
                ("新規ブックマーク", self.cmd_new_bookmark),
                ("名前変更", self.cmd_rename),
                ("URL編集", self.cmd_edit_url),
                ("プレビュー取得", self.cmd_fetch_preview),
                ("移動", self.cmd_move_to_folder),
                ("削除", self.cmd_delete),
            ],
            danger_buttons={"削除"}
        ))
        
        # Organize Section
        actions_layout.addWidget(self._create_action_section(
            "🧹 整理",
            "低",
            [
                ("タイトル順", lambda: self._apply_sort("title")),
                ("ドメイン順", lambda: self._apply_sort("domain")),
                ("上へ移動", self.cmd_move_up),
                ("重複削除", self.cmd_delete_duplicates),
                ("フォルダ統合", self.cmd_merge_duplicate_folders),
            ]
        ))
        
        # AI Classification Section
        actions_layout.addWidget(self._create_action_section(
            "✨ AI分類",
            "高",
            [
                ("スマート分類", self.cmd_smart_classify),
                ("ルール分類", self.cmd_show_classify_preview),
                ("ルール編集", self.cmd_show_classify_preview),
                ("上限設定", self.cmd_save),
                ("タイトル取得", self.cmd_fix_titles_from_url),
            ]
        ))

        # Details panel at bottom
        details_panel = self._create_details_panel()
        self.detail_panel = details_panel

        scroll_layout.addWidget(actions_container, stretch=1)
        scroll_layout.addWidget(details_panel, stretch=1)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll, stretch=1)
        
        return panel

    def _create_details_panel(self) -> DetailPanel:
        """Create details panel with actions."""
        details = DetailPanel()
        details.edit_requested.connect(self._on_detail_edit)
        details.copy_url_requested.connect(self._copy_to_clipboard)
        details.move_requested.connect(lambda node: self._on_detail_move(node))
        details.delete_requested.connect(lambda node: self._on_detail_delete(node))
        self.detail_panel = details
        return details


    def _create_action_section(self, title: str, frequency: str, actions: List[tuple], danger_buttons: Optional[Set[str]] = None) -> QFrame:
        """Create an action section with title, frequency, and buttons.
        
        Args:
            title: Section title with emoji
            frequency: Usage frequency: "高", "中", or "低"
            actions: List of (button_text, callback) tuples
            danger_buttons: Set of button texts that should use dangerButton style
        """
        if danger_buttons is None:
            danger_buttons = set()
            
        section = QFrame()
        section.setObjectName("actionSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        
        # Section header with title and frequency
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        
        title_label = QLabel(title)
        title_font = QFont(Typography.FONT_FAMILY, 11)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setObjectName("sectionTitle")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        freq_label = QLabel(f"頻度: {frequency}")
        freq_label.setObjectName("sectionNote")
        header_layout.addWidget(freq_label)
        
        layout.addWidget(header)
        
        # Buttons grid
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        
        for i, (btn_text, callback) in enumerate(actions):
            btn = QPushButton(btn_text)
            btn.setMinimumHeight(30)
            btn.clicked.connect(callback)
            
            # Apply danger style to destructive actions
            if btn_text in danger_buttons:
                btn.setObjectName("dangerButton")
            else:
                btn.setObjectName("actionButton")
            
            row = i // 3
            col = i % 3
            grid.addWidget(btn, row, col)
        
        layout.addLayout(grid)
        return section

    # ------------------------------ window events ----------------------------
    def showEvent(self, event: Any) -> None:
        """Auto-load last bookmarks file on first window show."""
        super().showEvent(event)
        
        # Load last bookmarks file if available
        if not self._startup_complete:
            self._startup_complete = True
            config = ConfigManager()
            last_file = config.get("Session", "last_bookmarks_file", "")
            
            if last_file and os.path.exists(last_file):
                try:
                    QTimer.singleShot(100, lambda: self._auto_load_bookmarks(last_file))
                except Exception as e:
                    self.logger.warning(f"Failed to auto-load bookmarks: {e}")

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
    
    def _auto_load_bookmarks(self, file_path: str) -> None:
        """Auto-load bookmarks without user dialog."""
        try:
            root, rules, rules_path = load_bookmarks(file_path)
            if root is None:
                self.logger.error("Auto-load failed: root node is None")
                return

            if not isinstance(root, Node):
                self.logger.error("Auto-load failed: invalid root node type: %s", type(root))
                return

            self.root_node = root
            self.rules = rules or self._default_rules()
            self.rules_path = rules_path
            self.current_file = file_path
            self.current_folder = self.root_node
            self.selected_node = None
            
            self._after_model_changed(select_node=self.root_node, refresh_parts="all")
            
            self.statusBar().showMessage(f"Loaded: {os.path.basename(file_path)}", 5000)
            self.logger.info(f"Auto-loaded bookmarks: {file_path}")
        except Exception as e:
            self.logger.error(f"Failed to auto-load bookmarks: {e}")

    # ------------------------------ polling ------------------------------
    def _start_polling(self) -> None:
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll_worker_results)
        self.poll_timer.start(200)

    def _poll_worker_results(self) -> None:
        try:
            self._process_ui_queue_once()
        except Exception as exc:  # pragma: no cover
            self.logger.error("Worker polling failed: %s", exc, exc_info=True)

    def _process_ui_queue_once(self) -> None:
        try:
            while not self.ui_queue.empty():
                item = self.ui_queue.get_nowait()
                if callable(item):
                    item()
                    continue
                if isinstance(item, WorkerEvent):
                    self._handle_worker_event_typed(item)
                elif isinstance(item, tuple) and len(item) == 2:
                    # Backward compatibility: convert legacy tuple to typed event
                    kind, payload = item
                    event = event_from_tuple(kind, payload)
                    self._handle_worker_event_typed(event)
        except queue.Empty:
            pass
        except Exception as exc:  # pragma: no cover
            self.logger.error("UI queue processing failed: %s", exc, exc_info=True)

    def _handle_worker_event_typed(self, event: WorkerEvent) -> None:
        """Handle typed worker events."""
        if isinstance(event, PreviewFetchedEvent):
            nodes = self.search_service.find_by_url(event.url)
            for node in nodes:
                if event.title and not node.title:
                    node.title = event.title
                if event.description:
                    node.description = event.description
            self._after_model_changed(refresh_parts="list")

        elif isinstance(event, TitleFixDoneEvent):
            self.statusBar().showMessage("Title fix complete", 4000)
            self._after_model_changed(refresh_parts="list")

        else:
            # Generic progress events
            if hasattr(event, "percentage"):
                pct = event.percentage if isinstance(event.percentage, (int, float)) else 0
                self.statusBar().showMessage(f"{event.__class__.__name__}: {pct:.0f}%")
            elif hasattr(event, "processed") and hasattr(event, "total"):
                self.statusBar().showMessage(f"Progress: {event.processed}/{event.total}")

    def _handle_worker_event(self, kind: str, payload: Any) -> None:
        """Legacy handler for backward compatibility."""
        event = event_from_tuple(kind, payload)
        self._handle_worker_event_typed(event)

    # --------------------------- event handlers ---------------------------
    def _on_folder_selected(self, node: Node, source_tree: Optional[FolderTree] = None) -> None:
        if self._building_tree:
            return
        if source_tree is not None:
            self._sync_tree_selection(node, source_tree)
        if node.type == "folder":
            self.current_folder = node
            self.selected_node = None
            self._refresh_content()
        else:
            self.selected_node = node
            if node.parent:
                self.current_folder = node.parent
                self._refresh_content()
            self.detail_panel.set_node(node)

    def _on_search(self, query: str) -> None:
        self._apply_search(query)
        self._refresh_content()

    def _on_detail_edit(self, node: Node) -> None:
        self.selected_node = node
        self.cmd_rename()

    def _on_detail_move(self, node: Node) -> None:
        self.selected_node = node
        self.cmd_move_to_folder()

    def _on_detail_delete(self, node: Node) -> None:
        self._delete_node(node)

    # ---------------------------- core actions ----------------------------
    def _refresh_content(self) -> None:
        """Monolithic refresh. Call _after_model_changed() instead."""
        if not hasattr(self, "cards_layout") or self.cards_layout is None:
            return
        self._refresh_layout_visibility()
        self._refresh_trees()
        self._refresh_list()
        self._update_bookmark_count()

    def _refresh_layout_visibility(self) -> None:
        """Update layout visibility based on dual_tree_mode."""
        if hasattr(self, "tree_scroll"):
            self.tree_scroll.setVisible(not self.dual_tree_mode)
        if hasattr(self, "dual_tree_splitter"):
            self.dual_tree_splitter.setVisible(self.dual_tree_mode)

    def _refresh_trees(self, select_node: Optional[Node] = None) -> None:
        """Refresh folder trees. Use when folder structure changes."""
        if select_node is None:
            select_node = self.current_folder if self.current_folder else self.root_node
        self._refresh_folder_trees(select_node)

    def _refresh_list(self) -> None:
        """Refresh bookmark cards/rows in the list. Use when current folder or search changes."""
        self._clear_cards()
        nodes = self._get_display_nodes()

        if not nodes:
            placeholder = QLabel("No bookmarks to display.")
            placeholder.setWordWrap(True)
            self.cards_layout.addWidget(placeholder)
            self.detail_panel.clear()
            return

        for node in nodes:
            if self.view_mode == "list":
                widget = BookmarkRow(node)
                widget.delete_requested.connect(lambda n=node: self._delete_node(n))
            else:
                widget = BookmarkCard(node)
                widget.double_clicked.connect(lambda n=node: self._open_url(n.url))

            widget.clicked.connect(lambda n=node, w=widget: self._select_node(n, w))
            self.cards_layout.addWidget(widget)

            if node.url and node.url not in self.preview_cache:
                self.preview_cache[node.url] = True
                self._enqueue_preview_fetch(node)

        self.cards_layout.addStretch()

    def _clear_cards(self) -> None:
        for i in reversed(range(self.cards_layout.count())):
            item = self.cards_layout.takeAt(i)
            if item.widget():
                item.widget().deleteLater()
        self.selected_cards.clear()

    def _select_node(self, node: Node, widget: Any) -> None:
        for w in list(self.selected_cards):
            if hasattr(w, "set_selected"):
                w.set_selected(False)
        self.selected_cards = {widget}
        if hasattr(widget, "set_selected"):
            widget.set_selected(True)
        self.selected_node = node
        self.detail_panel.set_node(node)

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
        # Rebuild search index via service
        self.search_service.rebuild(self.app_state.root_node)
        
        if refresh_parts in ("all", "trees"):
            self._refresh_trees(select_node=select_node)
        
        if refresh_parts in ("all", "list"):
            self._refresh_list()
        
        self._update_bookmark_count()

    def _apply_search(self, query: str) -> None:
        """Execute search via SearchService."""
        self.app_state.set_search_query(query)
        if not query.strip():
            self.app_state.search_hits.clear()
            return
        
        hits = self.search_service.query(query)
        self.app_state.search_hits = hits

    def _get_display_nodes(self) -> List[Node]:
        if not self.current_folder:
            return []

        base_nodes = [ch for ch in self.current_folder.children if ch.type == "bookmark"]
        if not self.search_query:
            return base_nodes

        # show matches inside the current subtree when searching
        filtered: List[Node] = []
        for node in self.search_hits:
            if self._is_descendant_of(node, self.current_folder):
                filtered.append(node)
        return filtered

    def _is_descendant_of(self, node: Node, folder: Node) -> bool:
        cur = node.parent
        while cur:
            if cur is folder:
                return True
            cur = cur.parent
        return False

    def _iter_bookmarks(self, node: Node) -> Iterable[Node]:
        for child in getattr(node, "children", []):
            if child.type == "bookmark":
                yield child
            elif child.type == "folder":
                yield from self._iter_bookmarks(child)

    def _update_bookmark_count(self) -> None:
        if not self.root_node:
            total = 0
        else:
            total = sum(1 for _ in self._iter_bookmarks(self.root_node))

        if hasattr(self, "bookmarks_count_label"):
            self.bookmarks_count_label.setText(f"{total:,}")
        if hasattr(self, "workspace_count_label"):
            self.workspace_count_label.setText(f"{total:,}")

    def _refresh_folder_trees(self, select_node: Optional[Node] = None) -> None:
        self._building_tree = True
        try:
            with QSignalBlocker(self.folder_tree):
                self._populate_folder_tree(self.folder_tree, select_node)
            if self.dual_tree_mode:
                with QSignalBlocker(self.folder_tree_left):
                    self._populate_folder_tree(self.folder_tree_left, select_node)
                with QSignalBlocker(self.folder_tree_right):
                    self._populate_folder_tree(self.folder_tree_right, select_node)
        finally:
            self._building_tree = False

    def _sync_tree_selection(self, node: Node, source_tree: FolderTree) -> None:
        trees = [self.folder_tree, self.folder_tree_left, self.folder_tree_right]
        for tree in trees:
            if tree is source_tree:
                continue
            with QSignalBlocker(tree):
                self._select_tree_item_for_node(node, tree)

    def _populate_folder_tree(self, tree: FolderTree, select_node: Optional[Node] = None) -> None:
        tree.clear()

        filter_active = bool(self.search_query)

        def should_include(node: Node) -> bool:
            if not filter_active:
                return True
            return node in self.search_hits

        def add_folder(node: Node, parent_item=None) -> Optional[Any]:
            # Build children first when filtering to decide whether to keep the folder
            item = tree.add_folder(parent_item, node)
            has_visible_child = False
            for child in node.children:
                if child.type == "folder":
                    child_item = add_folder(child, item)
                    has_visible_child = has_visible_child or (child_item is not None)
                elif child.type == "bookmark":
                    if should_include(child):
                        tree.add_bookmark(item, child)
                        has_visible_child = True

            if filter_active and not should_include(node) and not has_visible_child:
                # Remove empty folder when filtering
                if parent_item is None:
                    # Keep root when filtering so tree stays anchored
                    return item
                if item.parent():
                    item.parent().removeChild(item)
                return None
            return item

        root_item = add_folder(self.root_node, None)
        tree.expandAll()

        # Try to select the current folder/bookmark in tree
        if select_node is not None:
            def walk(item: Any) -> Optional[Any]:
                if item.data(0, Qt.ItemDataRole.UserRole) is select_node:
                    return item
                for i in range(item.childCount()):
                    found = walk(item.child(i))
                    if found:
                        return found
                return None

            target = walk(root_item)
            if target is not None:
                tree.setCurrentItem(target)
        if select_node:
            self._select_tree_item_for_node(select_node, tree)
        else:
            tree.setCurrentItem(root_item)

    def _select_tree_item_for_node(self, target: Node, tree: FolderTree) -> None:
        def walk(item):
            if item.data(0, Qt.ItemDataRole.UserRole) is target:
                tree.setCurrentItem(item)
                return True
            for i in range(item.childCount()):
                if walk(item.child(i)):
                    return True
            return False

        for i in range(tree.topLevelItemCount()):
            if walk(tree.topLevelItem(i)):
                break

    def _on_tree_node_moved(self, node: Node, old_parent: Node, new_parent: Node, index: int) -> None:
        if not node or not old_parent or not new_parent:
            return
        if node is self.root_node:
            return
        if new_parent is node or self._is_descendant_of(new_parent, node):
            self.statusBar().showMessage("Cannot move a folder into its descendant", 3000)
            self._refresh_folder_trees(select_node=node)
            return

        # Use Node API instead of direct manipulation
        old_parent.remove_child(node)
        new_parent.insert_child(index, node)

        self._after_model_changed(select_node=node, refresh_parts="trees")

    def _default_rules(self) -> list:
        return []

    # ----------------------------- commands ------------------------------
    def cmd_open(self) -> None:
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

        self.root_node = root
        self.rules = rules
        self.rules_path = rules_path
        self.current_file = file_path
        self.current_folder = self.root_node
        self._refresh_folder_trees(select_node=self.root_node)
        self._build_search_index()
        self._refresh_content()
        # Remember last file
        self.config_manager.set("Session", "last_bookmarks_file", file_path)
        self.statusBar().showMessage(f"Loaded {file_path}", 4000)

    def cmd_save(self) -> None:
        if not self.current_file:
            self.cmd_save_as()
            return
        try:
            save_bookmarks(self.current_file, self.root_node, self.rules)
            self.statusBar().showMessage(f"Saved to {self.current_file}", 4000)
            # Remember last file
            self.config_manager.set("Session", "last_bookmarks_file", self.current_file)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save:\n{exc}")

    def cmd_save_as(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save As", "", "HTML Files (*.html);;All Files (*)"
        )
        if not file_path:
            return
        self.current_file = file_path
        self.cmd_save()
        # Remember last file
        self.config_manager.set("Session", "last_bookmarks_file", file_path)

    def cmd_new_folder(self) -> None:
        if not self.current_folder or self.current_folder.type != "folder":
            QMessageBox.warning(self, "Warning", "Select a folder first.")
            return
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if not ok or not name.strip():
            return
        new_node = Node("folder", name.strip())
        self.current_folder.append(new_node)
        self._after_model_changed(select_node=new_node, refresh_parts="all")

    def cmd_new_bookmark(self) -> None:
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
        self._after_model_changed(select_node=node, refresh_parts="all")
        self._enqueue_preview_fetch(node)

    def cmd_rename(self) -> None:
        if not self.selected_node:
            QMessageBox.information(self, "Info", "Select an item to rename.")
            return
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=self.selected_node.title)
        if not ok or not name.strip():
            return
        self.selected_node.title = name.strip()
        self._after_model_changed(select_node=self.selected_node if self.selected_node.type == "folder" else None, refresh_parts="all")

    def cmd_edit_url(self) -> None:
        if not self.selected_node or self.selected_node.type != "bookmark":
            QMessageBox.information(self, "Info", "Select a bookmark to edit.")
            return
        url, ok = QInputDialog.getText(self, "Edit URL", "URL:", text=self.selected_node.url)
        if not ok or not url.strip():
            return
        if not is_valid_url(url.strip()):
            QMessageBox.warning(self, "Warning", "Enter a valid URL.")
            return
        self.selected_node.url = url.strip()
        self._after_model_changed(refresh_parts="list")

    def cmd_move_to_folder(self) -> None:
        if not self.selected_node or not self.root_node:
            QMessageBox.information(self, "Info", "Select an item to move.")
            return
        dialog = FolderSelectDialog(self, root_node=self.root_node, exclude_nodes=[self.selected_node])
        if dialog.exec() != dialog.Accepted or not dialog.result:
            return
        target_folder = dialog.result
        if target_folder.type != "folder":
            QMessageBox.warning(self, "Warning", "Target must be a folder.")
            return
        parent = self.selected_node.parent
        if parent:
            parent.remove_child(self.selected_node)
        target_folder.append(self.selected_node)
        self.current_folder = target_folder
        self._after_model_changed(select_node=target_folder, refresh_parts="all")

    def cmd_move_up(self) -> None:
        if not self.selected_node or not self.selected_node.parent:
            return
        parent = self.selected_node.parent
        siblings = parent.children
        idx = siblings.index(self.selected_node)
        if idx <= 0:
            return
        # Use Node API: move to idx-1
        parent.move_child(self.selected_node, idx - 1)
        self._after_model_changed(select_node=self.selected_node, refresh_parts="trees")

    def _delete_node(self, node: Node) -> None:
        if not node.parent:
            QMessageBox.warning(self, "Warning", "Cannot delete root.")
            return
        parent = node.parent
        parent.remove_child(node)
        if self.selected_node is node:
            self.selected_node = None
        self._after_model_changed(select_node=parent, refresh_parts="all")

    def cmd_delete(self) -> None:
        if not self.selected_node:
            QMessageBox.information(self, "Info", "Select an item to delete.")
            return
        self._delete_node(self.selected_node)

    def cmd_expand_all(self) -> None:
        """Expand all folders (placeholder)."""
        QMessageBox.information(self, "Expand", "Expand all folders functionality.")

    def cmd_collapse_all(self) -> None:
        """Collapse all folders (placeholder)."""
        QMessageBox.information(self, "Collapse", "Collapse all folders functionality.")

    def cmd_check_proxy(self) -> None:
        settings = self.config_manager.get_proxy_settings()
        if not settings:
            QMessageBox.information(self, "Proxy", "Proxy is disabled or not configured.")
            return
        summary = settings.get("url", "")
        QMessageBox.information(self, "Proxy", f"Using proxy: {summary}")

    def _build_domain_plan(self) -> Dict[str, List[Node]]:
        plan: Dict[str, List[Node]] = {}
        base = self.current_folder if self.current_folder else self.root_node
        for node in self._iter_bookmarks(base):
            domain = urlparse(node.url or "").netloc or "Unsorted"
            plan.setdefault(domain, []).append(node)
        return plan

    def _build_rules_plan(self) -> Dict[str, List[Node]]:
        plan: Dict[str, List[Node]] = {}
        rules = self.rules or {}
        if not rules:
            return plan

        base = self.current_folder if self.current_folder else self.root_node
        for node in self._iter_bookmarks(base):
            title = (node.title or "").lower()
            url = (node.url or "").lower()
            domain = urlparse(node.url or "").netloc.lower()
            for folder, rule in rules.items():
                domains = [d.lower() for d in rule.get("domains", [])]
                keywords = [k.lower() for k in rule.get("keywords", [])]
                if any(d in domain for d in domains) or any(k in title or k in url for k in keywords):
                    plan.setdefault(folder, []).append(node)
                    break
        return plan

    def cmd_show_classify_preview(self) -> None:
        plan = self._build_rules_plan()
        if not plan:
            QMessageBox.information(self, "Classify", "No rules or matching bookmarks.")
            return
        lines = [f"{folder}: {len(nodes)}" for folder, nodes in plan.items()]
        preview = "\n".join(lines)
        res = QMessageBox.question(self, "Rule-based Classification", preview + "\n\nApply this plan?")
        if res != QMessageBox.StandardButton.Yes:
            return
        base = self.current_folder if self.current_folder else self.root_node
        for folder_name, nodes in plan.items():
            target = self._find_or_create_folder(base, folder_name)
            for node in nodes:
                parent = node.parent
                if parent and node in parent.children:
                    parent.children.remove(node)
                target.append(node)
        self._refresh_folder_trees(select_node=base)
        self._build_search_index()
        self._refresh_content()
        self.statusBar().showMessage("Rule-based classification applied", 4000)

    def cmd_smart_classify(self) -> None:
        base = self.current_folder if self.current_folder else self.root_node
        nodes = list(self._iter_bookmarks(base))
        if not nodes:
            QMessageBox.information(self, "Classify", "No bookmarks to classify.")
            return

        dialog = CustomPromptDialog(self, title="追加指示（任意）", previous_prompts=[])
        if dialog.exec() != dialog.Accepted:
            additional_prompt = None
        else:
            additional_prompt = dialog.result or None

        try:
            classifier = AIBookmarkClassifier(config_path=str(self.config_manager.config_path))
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

        for folder_name, items in result.plan.items():
            target = self._find_or_create_folder(base, folder_name)
            for item in items:
                node = node_map.get(item)
                if not node:
                    continue
                parent = node.parent
                if parent and node in parent.children:
                    parent.children.remove(node)
                target.append(node)

        self._refresh_folder_trees(select_node=base)
        self._build_search_index()
        self._refresh_content()
        self.statusBar().showMessage("AI classification completed", 4000)

    def cmd_delete_duplicates(self) -> None:
        if not self.current_folder:
            return
        seen: set[str] = set()
        removed = 0
        new_children = []
        for child in self.current_folder.children:
            if child.type != "bookmark":
                new_children.append(child)
                continue
            key = (child.url or "").strip().lower()
            if key and key in seen:
                removed += 1
                continue
            seen.add(key)
            new_children.append(child)
        self.current_folder.children = new_children
        self._build_search_index()
        self._refresh_content()
        self._refresh_folder_trees(select_node=self.current_folder)
        self.statusBar().showMessage(f"Removed {removed} duplicate bookmarks", 3000)

    def cmd_merge_duplicate_folders(self) -> None:
        if not self.current_folder:
            return
        folders: Dict[str, Node] = {}
        removed = 0
        new_children = []
        for child in list(self.current_folder.children):
            if child.type != "folder":
                new_children.append(child)
                continue
            key = (child.title or "").strip().lower()
            if key in folders:
                target = folders[key]
                for sub in list(child.children):
                    target.append(sub)
                removed += 1
                continue
            folders[key] = child
            new_children.append(child)
        self.current_folder.children = new_children
        self._build_search_index()
        self._refresh_content()
        self._refresh_folder_trees(select_node=self.current_folder)
        self.statusBar().showMessage(f"Merged {removed} duplicate folders", 3000)

    def _find_or_create_folder(self, parent: Node, name: str) -> Node:
        for child in parent.children:
            if child.type == "folder" and child.title == name:
                return child
        new_folder = Node("folder", name)
        parent.append(new_folder)
        return new_folder

    def cmd_set_view_mode(self, mode: str) -> None:
        """Switch between card and list view modes."""
        if mode not in ("card", "list"):
            return
        
        self.view_mode = mode
        
        # Update checkboxes
        self.card_mode_action.setChecked(mode == "card")
        self.list_mode_action.setChecked(mode == "list")
        
        # Update top bar chip
        if hasattr(self, 'mode_chip'):
            display_text = "Card" if mode == "card" else "List"
            self.mode_chip.setText(f"表示: {display_text}")

        # Update view toggle button styles
        if hasattr(self, "view_buttons"):
            for key, btn in self.view_buttons.items():
                btn.setObjectName("tonalButton" if key == mode else "ghostButton")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()
        
        # Refresh content with new mode
        self._refresh_content()
        self.statusBar().showMessage(f"Switched to {mode.title()} Mode", 2000)

    def _set_dual_tree_mode(self, enabled: bool) -> None:
        self.dual_tree_mode = bool(enabled)
        if hasattr(self, "dual_tree_action"):
            self.dual_tree_action.setChecked(self.dual_tree_mode)
        if hasattr(self, "dual_tree_button"):
            self.dual_tree_button.setChecked(self.dual_tree_mode)
        if self.view_mode == "tree":
            self._refresh_content()

    def _apply_sort(self, sort_by: str) -> None:
        """Sort bookmarks by specified field."""
        if sort_by == "title":
            self.current_folder.children.sort(key=lambda n: n.title or "", reverse=False)
            self.statusBar().showMessage("Sorted by title", 2000)
        elif sort_by == "domain":
            # Sort by domain extracted from URL
            def get_domain(node: Node) -> str:
                if node.url:
                    try:
                        from urllib.parse import urlparse
                        return urlparse(node.url).netloc or node.title or ""
                    except:
                        return node.title or ""
                return node.title or ""
            
            self.current_folder.children.sort(key=get_domain, reverse=False)
            self.statusBar().showMessage("Sorted by domain", 2000)
        
        self._refresh_content()

    def cmd_fix_titles_from_url(self) -> None:
        self._enable_network_updates("タイトル取得")
        nodes = list(self._iter_bookmarks(self.current_folder)) if self.current_folder else []
        if not nodes:
            QMessageBox.information(self, "Info", "No bookmarks to update.")
            return
        proxy_info = self.config_manager.get_proxies_for_requests(use_proxy=self.use_proxy)
        self.statusBar().showMessage("Starting title fix...", 2000)
        self._start_background(fix_titles, nodes, self.ui_queue, proxy_info, self.fetch_timeout, None, None)

    def cmd_fetch_preview(self) -> None:
        """Fetch preview for the selected bookmark (on demand)."""
        if not self.selected_node or self.selected_node.type != "bookmark":
            QMessageBox.information(self, "Info", "プレビュー取得はブックマークを選択してください。")
            return
        self._enable_network_updates("プレビュー取得")
        self._enqueue_preview_fetch(self.selected_node)

    def _enqueue_preview_fetch(self, node: Node) -> None:
        if not self.network_updates_enabled:
            return
        proxy_info = self.config_manager.get_proxies_for_requests(use_proxy=self.use_proxy)
        self._start_background(fetch_preview, node.url, self.ui_queue, proxy_info, self.fetch_timeout)

    def _enable_network_updates(self, reason: str) -> None:
        if not self.network_updates_enabled:
            self.network_updates_enabled = True
            self.statusBar().showMessage(f"ネットワーク更新を有効化: {reason}", 3000)

    def _start_background(self, target, *args) -> None:
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()


# Backward compatibility alias
App = MainWindow

