"""
PySide6 GUI Components - Consolidated Layout Module

This module consolidates all GUI layout components previously split across
gui/layout/*.py files into a single module for better maintainability.

Components:
- Basic Components: BookmarkCard, BookmarkRow, FolderTree, SearchBar
- Panels: TopBar, LeftPanel, RightPanel, DetailPanel
- Views: BookmarkListView
- Dialogs: CustomPromptDialog, FolderSelectDialog
"""

from typing import Optional, Callable, Dict, Any, List, Set, Tuple
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QTextEdit,
    QStyle,
    QDialog,
    QListWidget,
    QListWidgetItem,
    QGridLayout,
    QSizePolicy,
    QSplitter,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon, QFont, QPixmap, QCursor

from core.ModelBookmark import Node
from gui.UtilGuiResources import Theme, Typography, Spacing, ColorTokens, create_qfont

# ==================== Favicon Cache ====================

_favicon_cache: Dict[str, Optional[QPixmap]] = {}


def get_favicon_image(icon_data: str, size: int = 16) -> Optional[QPixmap]:
    """ファビコンデータから QPixmap を取得（キャッシュ付き）"""
    if not icon_data:
        return None
    
    try:
        from PIL import Image
        from io import BytesIO
        import base64
        
        cache_key = f"{hash(icon_data)}_{size}"
        if cache_key in _favicon_cache:
            return _favicon_cache[cache_key]
        
        if icon_data.startswith('data:image'):
            header, encoded = icon_data.split(',', 1)
            img_data = base64.b64decode(encoded)
            img = Image.open(BytesIO(img_data))
            img = img.resize((size, size), Image.Resampling.LANCZOS)
            
            # PIL Image から QPixmap に変換
            import io
            with io.BytesIO() as buf:
                img.save(buf, format='PNG')
                buf.seek(0)
                pixmap = QPixmap()
                pixmap.loadFromData(buf.read())
            
            _favicon_cache[cache_key] = pixmap
            return pixmap
    except Exception:
        pass
    
    _favicon_cache[cache_key] = None
    return None


# ==================== Basic Components ====================

class BookmarkCard(QFrame):
    """
    個別ブックマークを表示するカードコンポーネント
    
    シグナル:
    - clicked: カードがクリックされた
    - double_clicked: カードがダブルクリックされた
    """
    
    clicked = Signal()
    double_clicked = Signal()
    
    def __init__(self, node: Node, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.node = node
        self.is_selected = False
        
        # QSSクラス設定
        self.setObjectName("bookmarkCard")
        
        # レイアウト設定
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        
        # ヘッダー（ファビコン + タイトル）
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)
        
        # ファビコン
        favicon = get_favicon_image(node.icon, 20) if node.icon else None
        if favicon:
            icon_label = QLabel()
            icon_label.setPixmap(favicon)
            icon_label.setFixedSize(20, 20)
            header_layout.addWidget(icon_label)
        else:
            icon_label = QLabel("🔗")
            font = QFont(Typography.FONT_FAMILY, 14)
            icon_label.setFont(font)
            header_layout.addWidget(icon_label)
        
        # タイトル
        title_label = QLabel(node.title or "Untitled")
        title_font = QFont(Typography.FONT_FAMILY, 14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setObjectName("cardTitle")
        header_layout.addWidget(title_label, 1)
        
        layout.addLayout(header_layout)
        
        # URL
        if node.url:
            url_label = QLabel(node.url)
            url_font = QFont(Typography.FONT_FAMILY, 11)
            url_label.setFont(url_font)
            url_label.setObjectName("cardUrl")
            url_label.setWordWrap(True)
            url_label.setMaximumHeight(30)
            layout.addWidget(url_label)
        
        # 説明
        if hasattr(node, 'description') and node.description:
            desc_label = QLabel(node.description)
            desc_font = QFont(Typography.FONT_FAMILY, 12)
            desc_label.setFont(desc_font)
            desc_label.setObjectName("cardDescription")
            desc_label.setWordWrap(True)
            desc_label.setMaximumHeight(40)
            layout.addWidget(desc_label)
        
        layout.addStretch()
        self.setMinimumHeight(100)
    
    def mousePressEvent(self, event):
        """マウスクリックイベント"""
        self.clicked.emit()
        self.set_selected(True)
        super().mousePressEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """ダブルクリックイベント"""
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)
    
    def set_selected(self, selected: bool) -> None:
        """選択状態を設定"""
        self.is_selected = selected
        if selected:
            self.setProperty("selected", "true")
        else:
            self.setProperty("selected", "false")
        # スタイル再適用
        self.style().unpolish(self)
        self.style().polish(self)


class BookmarkRow(QFrame):
    """
    ブックマークの行表示（リスト用）
    
    シグナル:
    - clicked: 行がクリックされた
    - delete_requested: 削除が要求された
    """
    
    clicked = Signal()
    delete_requested = Signal()
    
    def __init__(self, node: Node, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.node = node
        self.is_selected = False
        
        # QSSクラス設定
        self.setObjectName("bookmarkRow")
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)
        
        # ファビコン
        favicon = get_favicon_image(node.icon, 16) if node.icon else None
        if favicon:
            icon_label = QLabel()
            icon_label.setPixmap(favicon)
            icon_label.setFixedSize(16, 16)
            layout.addWidget(icon_label)
        else:
            icon_label = QLabel("🔗")
            layout.addWidget(icon_label)
        
        # タイトルとURL
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(2)
        
        title_label = QLabel(node.title or "Untitled")
        title_font = QFont(Typography.FONT_FAMILY, 13)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setObjectName("rowTitle")
        content_layout.addWidget(title_label)
        
        if node.url:
            url_label = QLabel(node.url)
            url_font = QFont(Typography.FONT_FAMILY, 11)
            url_label.setFont(url_font)
            url_label.setObjectName("rowUrl")
            url_label.setMaximumWidth(400)
            content_layout.addWidget(url_label)
        
        layout.addLayout(content_layout, 1)
        
        # 削除ボタン
        delete_btn = QPushButton("削除")
        delete_btn.clicked.connect(self.delete_requested.emit)
        delete_btn.setMaximumWidth(60)
        delete_btn.setObjectName("textButton")
        layout.addWidget(delete_btn)
        
        self.setMinimumHeight(60)
    
    def mousePressEvent(self, event):
        """マウスクリックイベント"""
        self.clicked.emit()
        self.set_selected(True)
        super().mousePressEvent(event)
    
    def set_selected(self, selected: bool) -> None:
        """選択状態を設定"""
        self.is_selected = selected
        if selected:
            self.setProperty("selected", "true")
        else:
            self.setProperty("selected", "false")
        # スタイル再適用
        self.style().unpolish(self)
        self.style().polish(self)


class FolderTree(QTreeWidget):
    """
    フォルダツリービュー
    
    シグナル:
    - item_selected: フォルダアイテムが選択された
    - item_double_clicked: フォルダアイテムがダブルクリックされた
    """
    
    item_selected = Signal(Node)
    item_double_clicked = Signal(Node)
    node_moved = Signal(object, object, object, int)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        # QSSクラス設定
        self.setObjectName("folderTree")
        
        # ツリー設定
        self.setHeaderHidden(True)
        self.setAnimated(True)
        self.setUniformRowHeights(True)
        self.setColumnCount(1)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._dragged_node = None
        self._dragged_old_parent = None
        
        # シグナル接続
        self.itemSelectionChanged.connect(self._on_item_selected)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
    
    def add_folder(self, parent_item: Optional[QTreeWidgetItem], node: Node) -> QTreeWidgetItem:
        """フォルダアイテムを追加"""
        item = QTreeWidgetItem(parent_item or self)
        item.setText(0, node.title or "Folder")
        item.setData(0, Qt.ItemDataRole.UserRole, node)
        if node.parent is None:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
        else:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
        
        # アイコン設定（Qtのアイコンを使用）
        if hasattr(QStyle.StandardPixmap, 'SP_DirIcon'):
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
            item.setIcon(0, icon)
        
        return item

    def add_bookmark(self, parent_item: Optional[QTreeWidgetItem], node: Node) -> QTreeWidgetItem:
        """ブックマークアイテムを追加"""
        item = QTreeWidgetItem(parent_item or self)
        item.setText(0, node.title or node.url or "Bookmark")
        item.setData(0, Qt.ItemDataRole.UserRole, node)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)

        pixmap = get_favicon_image(node.icon) if getattr(node, "icon", "") else None
        if pixmap:
            item.setIcon(0, QIcon(pixmap))
        elif hasattr(QStyle.StandardPixmap, 'SP_FileIcon'):
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
            item.setIcon(0, icon)

        return item
    
    def _on_item_selected(self):
        """アイテム選択イベント"""
        selected_items = self.selectedItems()
        if selected_items:
            node = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
            if node:
                self.item_selected.emit(node)
    
    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """アイテムダブルクリックイベント"""
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if node:
            self.item_double_clicked.emit(node)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if not item:
            return
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if not node or getattr(node, "parent", None) is None:
            return
        self._dragged_node = node
        self._dragged_old_parent = node.parent
        super().startDrag(supported_actions)

    def dropEvent(self, event):
        source = event.source()
        if isinstance(source, FolderTree) and source is not self:
            dragged_item = source.currentItem()
            dragged_node = dragged_item.data(0, Qt.ItemDataRole.UserRole) if dragged_item else None
            if not dragged_node or getattr(dragged_node, "parent", None) is None:
                event.ignore()
                return

            target_item = self.itemAt(event.position().toPoint())
            if target_item and target_item.data(0, Qt.ItemDataRole.UserRole):
                target_node = target_item.data(0, Qt.ItemDataRole.UserRole)
                if getattr(target_node, "type", "") == "folder":
                    new_parent_node = target_node
                    parent_item = target_item
                else:
                    parent_item = target_item.parent() or self.topLevelItem(0)
                    new_parent_node = parent_item.data(0, Qt.ItemDataRole.UserRole) if parent_item else None
                index = parent_item.indexOfChild(target_item) if parent_item else 0
            else:
                parent_item = self.topLevelItem(0)
                new_parent_node = parent_item.data(0, Qt.ItemDataRole.UserRole) if parent_item else None
                index = parent_item.childCount() if parent_item else 0

            if new_parent_node:
                self.node_moved.emit(dragged_node, dragged_node.parent, new_parent_node, index)
                event.acceptProposedAction()
            else:
                event.ignore()
            return

        if not self._dragged_node:
            super().dropEvent(event)
            return

        dragged_node = self._dragged_node
        old_parent = self._dragged_old_parent
        self._dragged_node = None
        self._dragged_old_parent = None

        super().dropEvent(event)

        dragged_item = self._find_item_by_node(dragged_node)
        if not dragged_item:
            return

        parent_item = dragged_item.parent()
        if parent_item is None:
            parent_item = self.topLevelItem(0)
        if parent_item is None:
            return

        new_parent_node = parent_item.data(0, Qt.ItemDataRole.UserRole)
        if not new_parent_node:
            return
        if getattr(new_parent_node, "type", "") != "folder":
            new_parent_node = getattr(new_parent_node, "parent", None)
            if not new_parent_node:
                return

        index = self._get_item_index(dragged_item)
        self.node_moved.emit(dragged_node, old_parent, new_parent_node, index)

    def _get_item_index(self, item: QTreeWidgetItem) -> int:
        parent = item.parent()
        if parent is None:
            parent = self.invisibleRootItem()
        for i in range(parent.childCount()):
            if parent.child(i) is item:
                return i
        return parent.childCount()

    def _find_item_by_node(self, node: Node) -> Optional[QTreeWidgetItem]:
        def walk(item: QTreeWidgetItem) -> Optional[QTreeWidgetItem]:
            if item.data(0, Qt.ItemDataRole.UserRole) is node:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found:
                    return found
            return None

        for i in range(self.topLevelItemCount()):
            found = walk(self.topLevelItem(i))
            if found:
                return found
        return None


class SearchBar(QFrame):
    """
    検索バーコンポーネント
    
    シグナル:
    - search_text_changed: 検索テキストが変更された
    - search_triggered: 検索が実行された（Enterキー押下）
    """
    
    search_text_changed = Signal(str)
    search_triggered = Signal(str)
    
    def __init__(self, placeholder: str = "検索...", parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        # QSSクラス設定
        self.setObjectName("searchBar")
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # 検索アイコン
        icon_label = QLabel("🔍")
        icon_font = QFont(Typography.FONT_FAMILY, 14)
        icon_label.setFont(icon_font)
        layout.addWidget(icon_label)
        
        # 入力フィールド
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(placeholder)
        input_font = QFont(Typography.FONT_FAMILY, 13)
        self.search_input.setFont(input_font)
        self.search_input.setObjectName("searchInput")
        layout.addWidget(self.search_input, 1)
        
        # クリアボタン
        clear_btn = QPushButton("クリア")
        clear_btn.clicked.connect(self._clear_search)
        clear_btn.setMaximumWidth(70)
        clear_btn.setObjectName("textButton")
        layout.addWidget(clear_btn)
        
        # シグナル接続
        self.search_input.textChanged.connect(self.search_text_changed.emit)
        self.search_input.returnPressed.connect(self._on_search_triggered)
        
        self._update_height()
    
    def showEvent(self, event):
        """ウィジェットが表示される際に高さを更新"""
        super().showEvent(event)
        self._update_height()
    
    def _update_height(self):
        if self.parent():
            parent_height = self.parent().height()
            if parent_height > 0:
                target_height = 30
                self.setMaximumHeight(target_height)
                self.setMinimumHeight(target_height)
    
    def _on_search_triggered(self):
        """検索トリガー"""
        self.search_triggered.emit(self.search_input.text())
    
    def _clear_search(self):
        """検索をクリア"""
        self.search_input.clear()
    
    def get_search_text(self) -> str:
        """検索テキストを取得"""
        return self.search_input.text()
    
    def set_search_text(self, text: str) -> None:
        """検索テキストを設定"""
        self.search_input.setText(text)


# ==================== Views ====================

class BookmarkListView(QFrame):
    """
    Bookmark list view component for displaying bookmarks as cards or rows.
    Handles item display, selection, and signals for main window.
    """

    # Signals
    node_selected = Signal(Node)  # Emitted when a bookmark is selected
    open_requested = Signal(str)  # Emitted when bookmark should be opened (URL)
    delete_requested = Signal(Node)  # Emitted when bookmark deletion is requested
    preview_fetch_requested = Signal(Node)  # Emitted when preview should be fetched

    def __init__(self):
        super().__init__()
        self.setObjectName("bookmarkListView")

        # UI
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(12)

        # State
        self.selected_cards: Set[Any] = set()
        self.view_mode: str = "card"  # "card" or "list"
        self._widgets: List[QWidget] = []
        self._last_nodes: List[Node] = []  # Cache for optimization

    def set_items(self, nodes: List[Node], view_mode: str = "card") -> None:
        """
        Set bookmarks to display.

        Args:
            nodes: List of bookmark nodes to display
            view_mode: Display mode ("card" or "list")
        """
        # Optimization: skip if items are identical (same nodes in same order)
        if self.view_mode == view_mode and self._last_nodes == nodes:
            return
        
        self._last_nodes = list(nodes)  # Cache for next comparison
        self.view_mode = view_mode
        self.clear()

        if not nodes:
            self._set_placeholder()
            return

        for node in nodes:
            if self.view_mode == "list":
                widget = BookmarkRow(node)
                widget.delete_requested.connect(lambda n=node: self._on_delete_requested(n))
            else:
                widget = BookmarkCard(node)
                widget.double_clicked.connect(lambda n=node: self._on_open_requested(n.url))

            widget.clicked.connect(lambda n=node, w=widget: self._on_node_selected(n, w))
            self.layout.addWidget(widget)
            self._widgets.append(widget)

        self.layout.addStretch()

    def select_node(self, node: Node) -> None:
        """
        Select a node programmatically.

        Args:
            node: Node to select
        """
        for widget in self._widgets:
            if hasattr(widget, "node") and widget.node is node:
                self._on_node_selected(node, widget)
                break

    def clear(self) -> None:
        """Clear all items from the list."""
        for i in reversed(range(self.layout.count())):
            item = self.layout.takeAt(i)
            if item.widget():
                item.widget().deleteLater()
        self.selected_cards.clear()
        self._widgets.clear()

    def _set_placeholder(self) -> None:
        """Display placeholder when no items."""
        placeholder = QLabel("No bookmarks to display.")
        placeholder.setWordWrap(True)
        placeholder.setObjectName("placeholder")
        self.layout.addWidget(placeholder)

    def _on_node_selected(self, node: Node, widget: Any) -> None:
        """Handle node selection."""
        # Deselect previous selections
        for w in list(self.selected_cards):
            if hasattr(w, "set_selected"):
                w.set_selected(False)

        # Select new widget
        self.selected_cards = {widget}
        if hasattr(widget, "set_selected"):
            widget.set_selected(True)

        # Emit signal
        self.node_selected.emit(node)

    def _on_open_requested(self, url: str) -> None:
        """Handle open URL request."""
        self.open_requested.emit(url)

    def _on_delete_requested(self, node: Node) -> None:
        """Handle delete request."""
        self.delete_requested.emit(node)

    def request_preview_fetch(self, node: Node) -> None:
        """Request preview fetch for a node."""
        self.preview_fetch_requested.emit(node)


# ==================== Panels ====================

class TopBar(QFrame):
    """Top bar with brand, search, and quick actions."""

    search_text_changed = Signal(str)
    search_triggered = Signal(str)
    toggle_dual_tree = Signal(bool)
    expand_all = Signal()
    collapse_all = Signal()

    def __init__(self, *, dual_tree_mode: bool = False, view_mode: str = "card", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("topbar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(12)

        brand_label = QLabel("📑 Bookmark Studio")
        brand_font = QFont(Typography.FONT_FAMILY, 12)
        brand_font.setBold(True)
        brand_label.setFont(brand_font)
        layout.addWidget(brand_label)

        chip1 = QLabel("v1.0")
        chip1.setObjectName("chip")
        layout.addWidget(chip1)

        self.search_bar = SearchBar(parent=self)
        self.search_bar.search_triggered.connect(self.search_triggered)
        self.search_bar.search_text_changed.connect(self.search_text_changed)
        layout.addWidget(self.search_bar, 1)

        layout.addStretch()

        dual_btn = QPushButton("2画面モード")
        dual_btn.setCheckable(True)
        dual_btn.setChecked(bool(dual_tree_mode))
        dual_btn.setObjectName("chip")
        dual_btn.clicked.connect(self.toggle_dual_tree)
        layout.addWidget(dual_btn)
        self.dual_tree_button = dual_btn

        mode_chip = QLabel("")
        mode_chip.setObjectName("chip")
        self.mode_chip = mode_chip
        self.set_view_mode(view_mode)
        layout.addWidget(mode_chip)

        expand_btn = QPushButton("すべて展開")
        expand_btn.setObjectName("outlineButton")
        expand_btn.setMaximumHeight(30)
        expand_btn.setMinimumWidth(80)
        expand_btn.clicked.connect(self.expand_all)
        layout.addWidget(expand_btn)

        collapse_btn = QPushButton("すべて縮小")
        collapse_btn.setObjectName("ghostButton")
        collapse_btn.setMaximumHeight(30)
        collapse_btn.setMinimumWidth(80)
        collapse_btn.clicked.connect(self.collapse_all)
        layout.addWidget(collapse_btn)

    def set_dual_tree_checked(self, checked: bool) -> None:
        self.dual_tree_button.setChecked(bool(checked))

    def set_view_mode(self, mode: str) -> None:
        display_text = "Card" if mode == "card" else "List"
        self.mode_chip.setText(f"表示: {display_text}")
    
    def resizeEvent(self, event):
        """TopBarのサイズ変更時にSearchBarの高さを更新"""
        super().resizeEvent(event)
        if hasattr(self, 'search_bar'):
            self.search_bar._update_height()


class LeftPanel(QFrame):
    """
    Left panel component for bookmark tree and list display.
    Manages folder tree (single/dual mode) and bookmark cards/rows.
    """

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


class ActionSection(QFrame):
    """
    Action section component with title, frequency label, and button grid.
    
    Displays a group of related actions organized in a 3-column grid.
    """
    
    def __init__(self, 
                 title: str, 
                 frequency: str, 
                 actions: List[tuple],
                 danger_buttons: Optional[Set[str]] = None,
                 parent: Optional[QWidget] = None):
        """
        Initialize action section.
        
        Args:
            title: Section title with emoji (e.g., "📁 ファイル")
            frequency: Usage frequency: "高", "中", or "低"
            actions: List of (button_text, callback) tuples
            danger_buttons: Set of button texts that should use dangerButton style
            parent: Parent widget
        """
        super().__init__(parent)
        self.setObjectName("actionSection")
        
        if danger_buttons is None:
            danger_buttons = set()
        
        layout = QVBoxLayout(self)
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
        
        # Buttons grid (3 columns)
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        
        for i, (btn_text, callback) in enumerate(actions):
            btn = QPushButton(btn_text)
            btn.setMinimumHeight(30)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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


class RightPanel(QFrame):
    """
    Right panel containing action sections and detail panel.
    
    Manages all right-side UI components in a single consolidated module.
    Includes:
    - File actions (Save, Open, etc.)
    - Edit actions (New, Rename, Delete, etc.)
    - Organize actions (Sort, Merge, etc.)
    - AI Classification actions
    - Detail panel for selected bookmark
    """
    
    def __init__(self, callbacks: Optional[Dict[str, Dict[str, Callable]]] = None, parent: Optional[QWidget] = None):
        """
        Initialize right panel with all sections.
        
        Args:
            callbacks: Dictionary of callback functions for action sections
                      Keys: "file", "edit", "organize", "ai"
                      Values: Dict/List mapping button text to callback functions
            parent: Parent widget
        """
        super().__init__(parent)
        self.setObjectName("rightPanel")
        self.callbacks = callbacks or {}
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Create scrollable area for action sections
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("actionScroll")
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(8, 8, 8, 8)
        scroll_layout.setSpacing(8)
        
        self.actions_container = QFrame()
        actions_layout = QVBoxLayout(self.actions_container)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        
        # Store references to action sections for dynamic updates
        self.file_section = None
        self.edit_section = None
        self.organize_section = None
        self.ai_section = None
        
        # Detail panel
        self.detail_panel = DetailPanel()
        
        # Initialize sections if callbacks are provided
        if callbacks:
            self._initialize_sections()
        
        scroll_layout.addWidget(self.actions_container, stretch=1)
        scroll_layout.addWidget(self.detail_panel, stretch=1)
        scroll_layout.addStretch()
        
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll, stretch=1)
    
    def _initialize_sections(self) -> None:
        """Initialize all action sections with callbacks."""
        file_callbacks = self.callbacks.get("file", {})
        if file_callbacks:
            self.add_action_section(
                "file",
                "📁 ファイル",
                "高",
                file_callbacks,
            )
        
        edit_callbacks = self.callbacks.get("edit", {})
        if edit_callbacks:
            self.add_action_section(
                "edit",
                "✏️ 編集",
                "中",
                edit_callbacks,
                danger_buttons={"削除"}
            )
        
        organize_callbacks = self.callbacks.get("organize", {})
        if organize_callbacks:
            self.add_action_section(
                "organize",
                "🧹 整理",
                "低",
                organize_callbacks,
            )
        
        ai_callbacks = self.callbacks.get("ai", {})
        if ai_callbacks:
            self.add_action_section(
                "ai",
                "✨ AI分類",
                "高",
                ai_callbacks,
            )
    
    def add_action_section(self,
                          section_id: str,
                          title: str,
                          frequency: str,
                          actions: List[tuple],
                          danger_buttons: Optional[Set[str]] = None) -> ActionSection:
        """
        Add an action section to the panel.
        
        Args:
            section_id: Unique identifier for the section (e.g., "file", "edit", "organize", "ai")
            title: Section title with emoji
            frequency: Usage frequency: "高", "中", or "低"
            actions: List of (button_text, callback) tuples
            danger_buttons: Set of button texts that should use dangerButton style
            
        Returns:
            The created ActionSection widget
        """
        section = ActionSection(title, frequency, actions, danger_buttons)
        
        # Store reference by section_id
        if section_id == "file":
            self.file_section = section
        elif section_id == "edit":
            self.edit_section = section
        elif section_id == "organize":
            self.organize_section = section
        elif section_id == "ai":
            self.ai_section = section
        
        # Add to container
        layout = self.actions_container.layout()
        if layout:
            layout.addWidget(section)
        
        return section
    
    def get_detail_panel(self) -> 'DetailPanel':
        """Get the detail panel for bookmark display."""
        return self.detail_panel


class DetailPanel(QScrollArea):
    """
    ブックマーク詳細パネル
    
    ブックマークの詳細情報を表示・編集するパネル
    
    シグナル:
    - edit_requested: 編集が要求された
    - copy_url_requested: URLコピーが要求された
    - move_requested: 移動が要求された
    - delete_requested: 削除が要求された
    """
    
    edit_requested = Signal(Node)
    copy_url_requested = Signal(str)
    move_requested = Signal(Node)
    delete_requested = Signal(Node)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self.current_node: Optional[Node] = None
        
        # QSSクラス設定
        self.setObjectName("detailPanel")
        self.setWidgetResizable(True)
        
        # コンテンツウィジェット
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(16, 16, 16, 16)
        self.content_layout.setSpacing(12)
        
        self.setWidget(self.content_widget)
    
    def set_node(self, node: Node) -> None:
        """ノードを設定して詳細を表示"""
        self.current_node = node
        
        # 既存ウィジェットをクリア
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # タイトル
        title_label = QLabel("タイトル:")
        title_font = QFont(Typography.FONT_FAMILY, 13)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setObjectName("sectionLabel")
        self.content_layout.addWidget(title_label)
        
        title_value = QLabel(node.title or "Untitled")
        value_font = QFont(Typography.FONT_FAMILY, 13)
        title_value.setFont(value_font)
        title_value.setObjectName("valueLabel")
        title_value.setWordWrap(True)
        self.content_layout.addWidget(title_value)
        
        # URL
        if node.url:
            url_label = QLabel("URL:")
            url_font = QFont(Typography.FONT_FAMILY, 13)
            url_font.setBold(True)
            url_label.setFont(url_font)
            url_label.setObjectName("sectionLabel")
            self.content_layout.addWidget(url_label)
            
            url_value = QLabel(node.url)
            url_value_font = QFont(Typography.FONT_FAMILY, 11)
            url_value.setFont(url_value_font)
            url_value.setObjectName("valueLabel")
            url_value.setWordWrap(True)
            url_value.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.content_layout.addWidget(url_value)
        
        # 説明
        if hasattr(node, 'description') and node.description:
            desc_label = QLabel("説明:")
            desc_font = QFont(Typography.FONT_FAMILY, 13)
            desc_font.setBold(True)
            desc_label.setFont(desc_font)
            desc_label.setObjectName("sectionLabel")
            self.content_layout.addWidget(desc_label)
            
            desc_value = QLabel(node.description)
            desc_value_font = QFont(Typography.FONT_FAMILY, 12)
            desc_value.setFont(desc_value_font)
            desc_value.setObjectName("valueLabel")
            desc_value.setWordWrap(True)
            self.content_layout.addWidget(desc_value)
        
        # 操作ボタンセクション
        self.content_layout.addSpacing(12)
        actions_label = QLabel("操作:")
        actions_font = QFont(Typography.FONT_FAMILY, 13)
        actions_font.setBold(True)
        actions_label.setFont(actions_font)
        actions_label.setObjectName("sectionLabel")
        self.content_layout.addWidget(actions_label)
        
        # ボタンレイアウト
        button_layout = QVBoxLayout()
        button_layout.setSpacing(6)
        
        # 編集ボタン
        edit_btn = QPushButton("✎ 編集")
        edit_btn.setObjectName("actionButton")
        edit_btn.setMinimumHeight(32)
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(node))
        button_layout.addWidget(edit_btn)
        
        # URLコピーボタン
        if node.url:
            copy_btn = QPushButton("📋 URLをコピー")
            copy_btn.setObjectName("actionButton")
            copy_btn.setMinimumHeight(32)
            copy_btn.clicked.connect(lambda: self.copy_url_requested.emit(node.url))
            button_layout.addWidget(copy_btn)
        
        # 移動ボタン
        move_btn = QPushButton("➜ 移動")
        move_btn.setObjectName("actionButton")
        move_btn.setMinimumHeight(32)
        move_btn.clicked.connect(lambda: self.move_requested.emit(node))
        button_layout.addWidget(move_btn)
        
        # 削除ボタン
        delete_btn = QPushButton("🗑 削除")
        delete_btn.setObjectName("dangerButton")
        delete_btn.setMinimumHeight(32)
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(node))
        button_layout.addWidget(delete_btn)
        
        self.content_layout.addLayout(button_layout)
        
        self.content_layout.addStretch()
    
    def clear(self) -> None:
        """詳細パネルをクリア"""
        self.current_node = None
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.content_layout.addStretch()


# ==================== Dialogs ====================

class CustomPromptDialog(QDialog):
    """
    プロンプト入力ダイアログ
    以前のプロンプト履歴表示 + 新規プロンプト入力
    """
    
    def __init__(self, parent=None, title="指示入力", previous_prompts=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setGeometry(100, 100, 500, 400)
        self.previous_prompts = previous_prompts or []
        self.result = None
        
        self._build_ui()
    
    def _build_ui(self):
        """UIを構築"""
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 以前のプロンプト履歴
        if self.previous_prompts:
            history_label = QLabel("現在の指示:")
            history_label.setFont(create_qfont(size=12, bold=True))
            history_label.setStyleSheet(f"color: {ColorTokens.TEXT_SECONDARY};")
            layout.addWidget(history_label)
            
            history_text = QTextEdit()
            history_text.setReadOnly(True)
            history_text.setFont(create_qfont(size=11))
            history_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {ColorTokens.SURFACE_2};
                    color: {ColorTokens.TEXT_PRIMARY};
                    border: 1px solid {ColorTokens.BORDER_DEFAULT};
                    border-radius: 4px;
                    padding: 5px;
                }}
            """)
            
            display_str = "\n".join([f"• {p}" for p in self.previous_prompts])
            history_text.setPlainText(display_str)
            history_text.setMaximumHeight(100)
            layout.addWidget(history_text)
        
        # 新規プロンプト入力
        prompt_label = QLabel("追加の指示を入力:")
        prompt_label.setFont(create_qfont(size=12, bold=True))
        prompt_label.setStyleSheet(f"color: {ColorTokens.TEXT_PRIMARY};")
        layout.addWidget(prompt_label)
        
        self.text_input = QTextEdit()
        self.text_input.setFont(create_qfont(size=11))
        self.text_input.setStyleSheet(f"""
            QTextEdit {{
                background-color: {ColorTokens.SURFACE_2};
                color: {ColorTokens.TEXT_PRIMARY};
                border: 1px solid {ColorTokens.BORDER_DEFAULT};
                border-radius: 4px;
                padding: 8px;
            }}
            QTextEdit:focus {{
                border: 2px solid {ColorTokens.BORDER_FOCUSED};
                padding: 7px;
            }}
        """)
        layout.addWidget(self.text_input)
        
        # ボタンレイアウト
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._accept)
        ok_btn.setObjectName("primaryButton")
        ok_btn.setMaximumWidth(100)
        btn_layout.addWidget(ok_btn)
        
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self._reject)
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.setMaximumWidth(100)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
    
    def _accept(self):
        """OKが押されたとき"""
        self.result = self.text_input.toPlainText().strip()
        self.accept()
    
    def _reject(self):
        """キャンセルが押されたとき"""
        self.result = None
        self.reject()


class FolderSelectDialog(QDialog):
    """
    フォルダ選択ダイアログ
    ツリー構造内のフォルダを選択
    """
    
    def __init__(self, parent=None, root_node: Node = None, exclude_nodes: Optional[List[Node]] = None):
        super().__init__(parent)
        self.setWindowTitle("フォルダを選択")
        self.setGeometry(100, 100, 500, 400)
        
        self.result = None
        self.root_node = root_node
        self.exclude_nodes = set(exclude_nodes) if exclude_nodes else set()
        
        # フォルダリストを構築
        self.folder_list: List[Tuple[str, Node]] = []
        if root_node:
            self._build_folder_list(root_node, [])
        
        self._build_ui()
        
        # 最初のフォルダを選択
        if self.folder_list:
            self.folder_widget.setCurrentRow(0)
    
    def _build_folder_list(self, node: Node, path: List[str]):
        """フォルダリストを再帰的に構築"""
        if node in self.exclude_nodes:
            return
        
        if node.type == "folder":
            # パス文字列を作成
            if path:
                path_str = " / ".join([p for p in path[1:] if p] + [node.title or "Untitled"])
            else:
                path_str = node.title or "Bookmarks"
            
            self.folder_list.append((path_str, node))
            
            # 子フォルダを再帰的に追加
            for child in getattr(node, 'children', []):
                self._build_folder_list(child, path + [node.title or ""])
    
    def _build_ui(self):
        """UIを構築"""
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 説明ラベル
        label = QLabel("移動先のフォルダを選択してください:")
        label.setFont(create_qfont(size=12, bold=True))
        label.setStyleSheet(f"color: {ColorTokens.TEXT_PRIMARY};")
        layout.addWidget(label)
        
        # フォルダリスト
        self.folder_widget = QListWidget()
        self.folder_widget.setFont(create_qfont(size=11))
        self.folder_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {ColorTokens.SURFACE_1};
                color: {ColorTokens.TEXT_PRIMARY};
                border: 1px solid {ColorTokens.BORDER_DEFAULT};
                border-radius: 4px;
            }}
            QListWidget::item:selected {{
                background-color: {ColorTokens.PRIMARY};
                color: white;
            }}
            QListWidget::item:hover {{
                background-color: {ColorTokens.HOVER_OVERLAY};
            }}
        """)
        
        for path_str, node in self.folder_list:
            item = QListWidgetItem(path_str)
            item.setData(Qt.UserRole, node)
            self.folder_widget.addItem(item)
        
        layout.addWidget(self.folder_widget)
        
        # ボタンレイアウト
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._accept)
        ok_btn.setObjectName("primaryButton")
        ok_btn.setMaximumWidth(100)
        btn_layout.addWidget(ok_btn)
        
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self._reject)
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.setMaximumWidth(100)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
    
    def _accept(self):
        """OKが押されたとき"""
        current_item = self.folder_widget.currentItem()
        if current_item:
            self.result = current_item.data(Qt.UserRole)
        self.accept()
    
    def _reject(self):
        """キャンセルが押されたとき"""
        self.result = None
        self.reject()
