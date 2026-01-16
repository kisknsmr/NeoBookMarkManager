"""
Left panel component for bookmark tree and list display.
Manages folder tree (single/dual mode) and bookmark cards/rows.
"""

from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from gui.layout.LayoutBookmarkListView import BookmarkListView
from gui.layout.LayoutComponents import FolderTree
from gui.UtilGuiResources import Typography


class LeftPanel(QFrame):
    """Left panel containing folder tree and bookmark display."""

    def __init__(
        self,
        callbacks: Optional[Dict[str, Callable]] = None,
    ):
        super().__init__()
        self.callbacks = callbacks or {}
        self.setObjectName("leftPanel")

        # UI components
        self.bookmarks_count_label: Optional[QLabel] = None
        self.workspace_count_label: Optional[QLabel] = None
        self.view_buttons: Dict[str, QPushButton] = {}

        # Trees
        self.folder_tree = FolderTree()
        self.folder_tree_left = FolderTree()
        self.folder_tree_right = FolderTree()
        self.tree_scroll: Optional[QScrollArea] = None
        self.dual_tree_splitter: Optional[QSplitter] = None

        # Cards/List display using BookmarkListView
        self.bookmark_list_view = BookmarkListView()
        self.cards_scroll: Optional[QScrollArea] = None

        # Splitters
        self.left_splitter: Optional[QSplitter] = None

        self._init_ui()

    def _init_ui(self) -> None:
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Header with title and count
        layout.addWidget(self._create_header())

        # Workspace header with view toggle
        layout.addWidget(self._create_workspace_header())

        # Folder trees and cards splitter
        layout.addWidget(self._create_content_area(), 1)

    def _create_header(self) -> QWidget:
        """Create top header with title and bookmark count."""
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
        return header_widget

    def _create_workspace_header(self) -> QWidget:
        """Create workspace header with view mode toggle buttons."""
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

        # List view button
        list_btn = QPushButton("List")
        list_btn.setObjectName("ghostButton")
        list_btn.setMaximumWidth(60)
        list_btn.setMaximumHeight(30)
        if "set_view_mode_list" in self.callbacks:
            list_btn.clicked.connect(self.callbacks["set_view_mode_list"])
        workspace_layout.addWidget(list_btn)
        self.view_buttons["list"] = list_btn

        # Card view button
        card_btn = QPushButton("Card")
        card_btn.setObjectName("tonalButton")
        card_btn.setMaximumWidth(60)
        card_btn.setMaximumHeight(30)
        if "set_view_mode_card" in self.callbacks:
            card_btn.clicked.connect(self.callbacks["set_view_mode_card"])
        workspace_layout.addWidget(card_btn)
        self.view_buttons["card"] = card_btn

        return workspace_header

    def _create_content_area(self) -> QWidget:
        """Create the main content area (trees + cards)."""
        # Single folder tree (standard mode)
        self.folder_tree = FolderTree()
        if "on_folder_selected" in self.callbacks:
            self.folder_tree.item_selected.connect(
                lambda node: self.callbacks["on_folder_selected"](node, self.folder_tree)
            )
        if "on_tree_node_moved" in self.callbacks:
            self.folder_tree.node_moved.connect(self.callbacks["on_tree_node_moved"])

        tree_scroll = QScrollArea()
        tree_scroll.setWidgetResizable(True)
        tree_scroll.setObjectName("treeScroll")
        tree_scroll.setWidget(self.folder_tree)
        tree_scroll.setVisible(False)
        self.tree_scroll = tree_scroll

        # Dual tree mode (left and right panes)
        self.folder_tree_left = FolderTree()
        if "on_folder_selected" in self.callbacks:
            self.folder_tree_left.item_selected.connect(
                lambda node: self.callbacks["on_folder_selected"](node, self.folder_tree_left)
            )
        if "on_tree_node_moved" in self.callbacks:
            self.folder_tree_left.node_moved.connect(self.callbacks["on_tree_node_moved"])

        self.folder_tree_right = FolderTree()
        if "on_folder_selected" in self.callbacks:
            self.folder_tree_right.item_selected.connect(
                lambda node: self.callbacks["on_folder_selected"](node, self.folder_tree_right)
            )
        if "on_tree_node_moved" in self.callbacks:
            self.folder_tree_right.node_moved.connect(self.callbacks["on_tree_node_moved"])

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

        # Bookmark list display area
        cards_scroll = QScrollArea()
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setObjectName("contentScroll")
        cards_scroll.setWidget(self.bookmark_list_view)
        self.cards_scroll = cards_scroll

        # Combine tree and cards into tree_container
        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.setSpacing(0)
        tree_layout.addWidget(tree_scroll)
        tree_layout.addWidget(dual_tree_splitter)

        # Main vertical splitter (trees on top, cards on bottom)
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(tree_container)
        left_splitter.addWidget(cards_scroll)
        left_splitter.setStretchFactor(0, 1)
        left_splitter.setStretchFactor(1, 1)
        left_splitter.setSizes([350, 350])
        self.left_splitter = left_splitter

        return left_splitter

    def get_bookmark_list_view(self) -> BookmarkListView:
        """Get the bookmark list view widget."""
        return self.bookmark_list_view

    def update_view_button_style(self, mode: str) -> None:
        """Update view mode button styles."""
        for key, btn in self.view_buttons.items():
            btn.setObjectName("tonalButton" if key == mode else "ghostButton")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()
