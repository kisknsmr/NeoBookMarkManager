"""
PySide6 GUI Components - Material Design 3 Compliance

Simplified component architecture:
- BookmarkCard: Individual bookmark card display
- FolderTree: Folder tree view with drag-and-drop
- SearchBar: Search input with signals
- DetailPanel: Bookmark details display
"""

from typing import Optional, Callable, Dict, Any
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
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon, QFont, QPixmap, QCursor

from core.model import Node
from gui.resources import Theme, Typography, Spacing

# Favicon cache for performance
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
