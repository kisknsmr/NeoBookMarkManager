"""
PySide6 GUI Components - Main UI Components Module

This module contains the main UI components for the NeoBookMarkManager application.
Dialogs have been moved to ui_dialogs.py for better organization.

Components:
- Basic Components: BookmarkCard, BookmarkRow, FolderTree, SearchBar
- Panels: TopBar, LeftPanel, RightPanel, DetailPanel
- Views: BookmarkListView
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
    QGridLayout,
    QSizePolicy,
    QSplitter,
    QLayout,
    QCheckBox,
)
from PySide6.QtCore import Qt, Signal, QSize, QPoint
from PySide6.QtGui import QIcon, QFont, QPixmap, QCursor, QPainter, QFontMetrics

from core.ModelBookmark import Node
from core.FontManager import FontManager
from gui.UtilGuiResources import Theme, Typography, Spacing, ColorTokens, create_qfont, ASSETS_DIR

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
        
        # サイズの固定（崩壊防止の要）
        self.setFixedSize(180, 120)
        
        # レイアウト設定
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        
        # ヘッダー（ファビコン + タイトル）
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        
        # ファビコン
        favicon = get_favicon_image(node.icon, 18) if node.icon else None
        icon_label = QLabel()
        if favicon:
            icon_label.setPixmap(favicon)
        else:
            icon_label.setText("🔗")
            icon_label.setFont(FontManager.get_ui_font(12))
        header_layout.addWidget(icon_label)
        
        # タイトル
        title_label = QLabel(node.title or "Untitled")
        title_label.setFont(FontManager.get_heading_font(11))
        title_label.setObjectName("cardTitle")
        title_label.setWordWrap(True)
        header_layout.addWidget(title_label, 1)
        
        layout.addLayout(header_layout)
        
        # URL
        if node.url:
            url_label = QLabel(node.url)
            url_label.setFont(FontManager.get_body_font(9))
            url_label.setObjectName("cardUrl")
            url_label.setStyleSheet(f"color: {ColorTokens.TEXT_SECONDARY};")
            url_label.setMaximumHeight(35)
            url_label.setWordWrap(True)
            layout.addWidget(url_label)
        
        layout.addStretch()
    
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
        self.setProperty("selected", "true" if selected else "false")
        # スタイル再適用
        self.style().unpolish(self)
        self.style().polish(self)


class BookmarkRow(QFrame):
    """
    ブックマークの行表示（リスト用）
    タイトルとURLを2段で表示し、横幅いっぱいに広がります。
    
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
        
        # サイズ固定（URLを表示するため少し高く設定）
        self.setFixedHeight(50)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 5, 12, 5)
        layout.setSpacing(12)
        
        # 1. ファビコン
        favicon = get_favicon_image(node.icon, 16) if node.icon else None
        icon_label = QLabel()
        if favicon:
            icon_label.setPixmap(favicon)
        else:
            icon_label.setText("🔗")
        icon_label.setFixedSize(16, 16)
        layout.addWidget(icon_label)
        
        # 2. テキストエリア（タイトルとURLを垂直に配置）
        text_container = QVBoxLayout()
        text_container.setSpacing(2)
        text_container.setContentsMargins(0, 0, 0, 0)
        
        # タイトル (太字、省略あり)
        title_label = QLabel()
        title_font = FontManager.get_heading_font(12)
        title_label.setFont(title_font)
        title_label.setObjectName("rowTitle")
        
        # タイトルが長い場合に「...」で省略
        metrics = QFontMetrics(title_font)
        elided_title = metrics.elidedText(node.title or "Untitled", Qt.TextElideMode.ElideRight, 400)
        title_label.setText(elided_title)
        title_label.setToolTip(node.title or "Untitled")  # ツールチップに完全なタイトルを表示
        text_container.addWidget(title_label)
        
        # URL (薄い色、小さいフォント)
        if node.url:
            url_label = QLabel()
            url_font = FontManager.get_body_font(10)
            url_label.setFont(url_font)
            url_label.setObjectName("rowUrl")
            url_label.setStyleSheet(f"color: {ColorTokens.TEXT_SECONDARY};")
            
            # URLが長い場合に「...」で省略
            url_metrics = QFontMetrics(url_font)
            elided_url = url_metrics.elidedText(node.url, Qt.TextElideMode.ElideRight, 500)
            url_label.setText(elided_url)
            url_label.setToolTip(node.url)  # ツールチップに完全なURLを表示
            text_container.addWidget(url_label)
        
        layout.addLayout(text_container, 1)  # stretch=1 で余白を埋める
        
        # 3. 削除ボタン
        delete_btn = QPushButton("削除")
        delete_btn.setObjectName("textButton")
        delete_btn.setFixedWidth(50)
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.clicked.connect(self.delete_requested.emit)
        layout.addWidget(delete_btn)
    
    def mousePressEvent(self, event):
        """マウスクリックイベント"""
        self.clicked.emit()
        self.set_selected(True)
        super().mousePressEvent(event)
    
    def set_selected(self, selected: bool) -> None:
        """選択状態を設定"""
        self.is_selected = selected
        self.setProperty("selected", "true" if selected else "false")
        # スタイル再適用
        self.style().unpolish(self)
        self.style().polish(self)


# ==================== Tree & View Components ====================

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
        
        # 展開/縮小アイコンの読み込み
        self._load_expand_icons()
        
        # シグナル接続
        self.itemSelectionChanged.connect(self._on_item_selected)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.itemExpanded.connect(self._on_item_expanded)
        self.itemCollapsed.connect(self._on_item_collapsed)
    
    def _load_expand_icons(self):
        """展開/縮小アイコンを読み込む"""
        icons_dir = ASSETS_DIR / "icons"
        chevron_right_path = icons_dir / "chevron-right.svg"
        chevron_down_path = icons_dir / "chevron-down.svg"
        
        # アイコンが存在する場合は読み込む
        if chevron_right_path.exists() and chevron_down_path.exists():
            self.icon_collapsed = QIcon(str(chevron_right_path))
            self.icon_expanded = QIcon(str(chevron_down_path))
            # アイコンのサイズを設定（18x18ピクセル、少し大きくして視認性向上）
            self.expand_icon_size = 18
        else:
            # フォールバック: アイコンなし
            self.icon_collapsed = None
            self.icon_expanded = None
            self.expand_icon_size = 16
    
    def _create_combined_icon(self, folder_icon: QIcon, expand_icon: QIcon, size: int = 24) -> QIcon:
        """フォルダアイコンと展開/縮小アイコンを合成"""
        # メインアイコン（フォルダ）のPixmapを取得
        folder_pixmap = folder_icon.pixmap(size, size)
        
        # 展開/縮小アイコンのPixmapを取得（小さめのサイズ）
        expand_size = self.expand_icon_size if hasattr(self, 'expand_icon_size') else 16
        expand_pixmap = expand_icon.pixmap(expand_size, expand_size)
        
        # 合成用のPixmapを作成
        combined_pixmap = QPixmap(size, size)
        combined_pixmap.fill(Qt.GlobalColor.transparent)
        
        # ペインターで描画
        painter = QPainter(combined_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        
        # フォルダアイコンを描画
        painter.drawPixmap(0, 0, folder_pixmap)
        
        # 展開/縮小アイコンを右下に描画（オーバーレイ）
        offset_x = size - expand_size - 2
        offset_y = size - expand_size - 2
        painter.drawPixmap(offset_x, offset_y, expand_pixmap)
        
        painter.end()
        
        return QIcon(combined_pixmap)
    
    def add_folder(self, parent_item: Optional[QTreeWidgetItem], node: Node) -> QTreeWidgetItem:
        """フォルダアイテムを追加"""
        item = QTreeWidgetItem(parent_item or self)
        item.setText(0, node.title or "Folder")
        item.setData(0, Qt.ItemDataRole.UserRole, node)
        if node.parent is None:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
        else:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
        
        # フォルダアイコンを取得
        if hasattr(QStyle.StandardPixmap, 'SP_DirIcon'):
            folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        else:
            folder_icon = None
        
        # すべてのフォルダに対して展開/縮小アイコンと合成
        if folder_icon:
            if hasattr(self, 'icon_collapsed') and self.icon_collapsed:
                # SVGアイコンとフォルダアイコンを合成（初期状態は縮小）
                combined_icon = self._create_combined_icon(folder_icon, self.icon_collapsed)
                item.setIcon(0, combined_icon)
            else:
                # フォールバック: フォルダアイコンのみ
                item.setIcon(0, folder_icon)
            # 展開/縮小状態を更新（初期状態は縮小）
            self._update_folder_icon(item, expanded=False)
        
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
    
    def _on_item_expanded(self, item: QTreeWidgetItem):
        """アイテム展開イベント - アイコンを更新"""
        self._update_folder_icon(item, expanded=True)
    
    def _on_item_collapsed(self, item: QTreeWidgetItem):
        """アイテム縮小イベント - アイコンを更新"""
        self._update_folder_icon(item, expanded=False)
    
    def _update_folder_icon(self, item: QTreeWidgetItem, expanded: bool):
        """フォルダアイコンの展開/縮小状態を更新（SVGアイコンとフォルダアイコンを合成）"""
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if not node or node.type != "folder":
            return
        
        folder_title = node.title or "Folder"
        item.setText(0, folder_title)  # テキストはアイコンなし
        
        # フォルダアイコンを取得
        if hasattr(QStyle.StandardPixmap, 'SP_DirIcon'):
            folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        else:
            return
        
        # SVGアイコンが読み込まれている場合は合成
        if hasattr(self, 'icon_expanded') and self.icon_expanded and self.icon_collapsed:
            if expanded:
                # 展開状態: 下向きのアイコンと合成
                combined_icon = self._create_combined_icon(folder_icon, self.icon_expanded)
            else:
                # 縮小状態: 右向きのアイコンと合成
                combined_icon = self._create_combined_icon(folder_icon, self.icon_collapsed)
            item.setIcon(0, combined_icon)
        else:
            # フォールバック: フォルダアイコンのみ
            item.setIcon(0, folder_icon)

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
        icon_label.setFont(FontManager.get_ui_font(14))
        layout.addWidget(icon_label)
        
        # 入力フィールド
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(placeholder)
        self.search_input.setFont(FontManager.get_body_font(13))
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

class BookmarkView(QFrame):
    """
    ブックマークの表示を管理するメインコンテナ。
    ウィジェットを完全に再利用し、レイアウトのみを切り替える超軽量版。
    """
    node_selected = Signal(Node)
    open_requested = Signal(str)
    delete_requested = Signal(Node)
    preview_fetch_requested = Signal(Node)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("bookmarkView")
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.container = QWidget()
        self.main_layout.addWidget(self.container)
        
        self.selected_widgets: Set[Any] = set()
        self.view_mode: str = "card"
        self._nodes: List[Node] = []
        self._widgets: List[QWidget] = []  # ウィジェットプール
        self._last_width = 0

    def set_items(self, nodes: List[Node], view_mode: str = "card") -> None:
        """データをセットし、描画を更新する"""
        from PySide6.QtWidgets import QApplication
        
        # モード変更の検知
        mode_changed = self.view_mode != view_mode
        self.view_mode = view_mode
        self._nodes = list(nodes)

        # 1. モードが変わる場合は、レイアウトエンジンのみをリセット
        # ※ウィジェット本体は捨てない
        if mode_changed:
            self._reset_layout_only()
        
        if len(nodes) > 50:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        self._refresh_ui_optimized()
        
        if len(nodes) > 50:
            QApplication.restoreOverrideCursor()

    def _reset_layout_only(self) -> None:
        """
        レイアウト（枠組み）だけを破棄し、ウィジェットはプールに回収する。
        - sip 依存を排除（PySide6環境でsipが無い）
        - setParent(None) はトップレベル化の原因になるため使わない
        """
        old_layout = self.container.layout()
        if old_layout:
            self._clear_layout_keep_widgets(old_layout)
            # 重要: deleteLater() だけだと、この直後も container.layout() が旧レイアウトを返すことがある。
            # 即座にコンテナからレイアウトを外すため、ダミーウィジェットへ付け替える。
            dummy = QWidget()
            try:
                dummy.setLayout(old_layout)
            except Exception:
                # 付け替えに失敗しても、deleteLaterだけはしておく
                pass
            dummy.deleteLater()
            old_layout.deleteLater()
        self.selected_widgets.clear()

    def _clear_layout_keep_widgets(self, layout: QLayout) -> None:
        """レイアウトからアイテムを外し、ウィジェットは hide() で回収する（deleteしない）"""
        while layout.count():
            item = layout.takeAt(0)
            if not item:
                continue
            w = item.widget()
            if w is not None:
                # placeholderは積み上がるので破棄
                if getattr(w, "objectName", lambda: "")() == "placeholder":
                    w.deleteLater()
                else:
                    w.hide()
                continue
            sub = item.layout()
            if sub is not None:
                self._clear_layout_keep_widgets(sub)
                try:
                    sub.setParent(None)
                except Exception:
                    pass
                sub.deleteLater()

    def _refresh_ui_optimized(self) -> None:
        """既存ウィジェットの並び替えのみを行う高速ロジック"""
        layout = self.container.layout()
        want_grid = self.view_mode == "card"
        # モードに対してレイアウト型が違う場合は作り直す（古いlayoutが残るケース対策）
        if layout and want_grid and not isinstance(layout, QGridLayout):
            self._reset_layout_only()
            layout = None
        if layout and (not want_grid) and not isinstance(layout, QVBoxLayout):
            self._reset_layout_only()
            layout = None
        
        # 適切なレイアウトがなければ作成
        if not layout:
            if self.view_mode == "card":
                layout = QGridLayout(self.container)
                layout.setSpacing(15)
                layout.setContentsMargins(10, 10, 10, 10)
            else:
                layout = QVBoxLayout(self.container)
                layout.setSpacing(4)
                layout.setContentsMargins(5, 5, 5, 5)
        else:
            # 現行レイアウトをクリア（ウィジェットは回収して再利用）
            self._clear_layout_keep_widgets(layout)

        if not self._nodes:
            self._set_placeholder()
            return

        target_class = BookmarkCard if self.view_mode == "card" else BookmarkRow
        column_count = max(1, (self.width() - 20) // 195) if self.view_mode == "card" else 1

        # 2. プールの整理（クラスが違うウィジェットを入れ替える）
        for i in range(len(self._nodes)):
            if i < len(self._widgets):
                if not isinstance(self._widgets[i], target_class):
                    old_w = self._widgets[i]
                    old_w.deleteLater()
                    new_w = target_class(self._nodes[i], parent=self.container)
                    self._connect_view_widget_signals(new_w)
                    self._widgets[i] = new_w
            else:
                # 不足分を新規作成
                new_w = target_class(self._nodes[i], parent=self.container)
                self._connect_view_widget_signals(new_w)
                self._widgets.append(new_w)

        # 3. データの更新とレイアウトへの追加
        for i, node in enumerate(self._nodes):
            widget = self._widgets[i]
            widget.node = node
            widget.setParent(self.container)

            if self.view_mode == "card":
                layout.addWidget(widget, i // column_count, i % column_count)
            else:
                layout.addWidget(widget)
            
            widget.show()

        # 4. 余ったウィジェットを隠す
        for k in range(len(self._nodes), len(self._widgets)):
            self._widgets[k].hide()

        # ストレッチ（余白調整）
        if self.view_mode == "card":
            if isinstance(layout, QGridLayout):
                layout.setRowStretch(layout.rowCount(), 1)
                layout.setColumnStretch(column_count, 1)
        else:
            if isinstance(layout, QVBoxLayout):
                layout.addStretch()

    def _connect_view_widget_signals(self, widget: QWidget) -> None:
        """BookmarkCard/BookmarkRow のシグナルを生成時に一度だけ接続する（disconnectしない）"""
        if hasattr(widget, "clicked"):
            widget.clicked.connect(lambda w=widget: self._on_node_selected(getattr(w, "node", None), w))
        if isinstance(widget, BookmarkCard):
            widget.double_clicked.connect(
                lambda w=widget: self.open_requested.emit(getattr(getattr(w, "node", None), "url", "") or "")
            )
        if isinstance(widget, BookmarkRow):
            widget.delete_requested.connect(
                lambda w=widget: self.delete_requested.emit(getattr(w, "node", None))
                if getattr(w, "node", None)
                else None
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.view_mode == "card" and self._nodes:
            if abs(self.width() - self._last_width) > 20:
                self._last_width = self.width()
                self._refresh_ui_optimized()

    def clear_all(self):
        """完全リセットが必要な場合のみ呼ぶ"""
        self._reset_layout_only()
        for w in self._widgets:
            w.deleteLater()
        self._widgets.clear()
        self._nodes.clear()

    def _set_placeholder(self) -> None:
        layout = self.container.layout()
        placeholder = QLabel("表示するブックマークがありません。")
        placeholder.setObjectName("placeholder")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(placeholder, 0, Qt.AlignmentFlag.AlignCenter)

    def _on_node_selected(self, node: Node, widget: Any) -> None:
        for w in self.selected_widgets:
            if hasattr(w, "set_selected"): w.set_selected(False)
        self.selected_widgets = {widget}
        if hasattr(widget, "set_selected"): widget.set_selected(True)
        self.node_selected.emit(node)

    def select_node(self, node: Node) -> None:
        """ノードをプログラム的に選択"""
        for widget in self._widgets:
            if hasattr(widget, "node") and widget.node is node:
                self._on_node_selected(node, widget)
                break
    
    def request_preview_fetch(self, node: Node) -> None:
        """プレビュー取得を要求"""
        self.preview_fetch_requested.emit(node)


# Backward compatibility:
# ControllerMainWindow (and older code) imports `BookmarkListView`.
# Keep it as an alias to the current lightweight `BookmarkView` without changing visuals.
class BookmarkListView(BookmarkView):
    pass


# ==================== Panels ====================

class TopBar(QFrame):
    """Top bar with brand, search, and quick actions."""

    search_text_changed = Signal(str)
    search_triggered = Signal(str)
    toggle_dual_tree = Signal(bool)

    def __init__(self, *, dual_tree_mode: bool = False, view_mode: str = "card", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("topbar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(12)

        brand_label = QLabel("📑 Bookmark Studio")
        brand_label.setFont(FontManager.get_heading_font(12))
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
    フォルダツリーとブックマーク表示エリアを統合したパネル
    """
    expand_all = Signal()
    collapse_all = Signal()
    expand_current = Signal()
    collapse_current = Signal()
    toggle_dual_tree = Signal(bool)

    def __init__(self, callbacks: Optional[Dict[str, Callable]] = None):
        super().__init__()
        self.callbacks = callbacks or {}
        self.setObjectName("leftPanel")

        # インスタンス作成
        self.folder_tree = FolderTree()
        self.folder_tree_left = FolderTree()
        self.folder_tree_right = FolderTree()
        
        # 名前を更新: BookmarkListView -> BookmarkView
        self.bookmark_view = BookmarkView() 
        
        self.tree_scroll: Optional[QScrollArea] = None
        self.dual_tree_splitter: Optional[QSplitter] = None
        self.cards_scroll: Optional[QScrollArea] = None
        self.left_splitter: Optional[QSplitter] = None
        self.tree_controls: Optional[QWidget] = None
        self.bookmarks_count_label: Optional[QLabel] = None
        self.workspace_count_label: Optional[QLabel] = None
        self.workspace_title_label: Optional[QLabel] = None
        self.view_buttons: Dict[str, QPushButton] = {}

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._create_header())
        layout.addWidget(self._create_content_area(), 1)

    def _create_header(self) -> QWidget:
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        header = QLabel("📁 Bookmarks")
        header.setFont(Typography.get_title_font())
        header_layout.addWidget(header)

        self.bookmarks_count_label = QLabel("0")
        self.bookmarks_count_label.setObjectName("chip")
        header_layout.addWidget(self.bookmarks_count_label)
        header_layout.addStretch()
        return header_widget

    def _create_bookmarks_header(self) -> QWidget:
        """下側（リスト/カード表示エリア）のヘッダー：List/Card切替をここに置く"""
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("Workspace")
        title.setObjectName("panelHeader")
        self.workspace_title_label = title
        layout.addWidget(title)

        self.workspace_count_label = QLabel("0")
        self.workspace_count_label.setObjectName("chip")
        layout.addWidget(self.workspace_count_label)

        layout.addStretch()

        for mode in ["list", "card"]:
            btn = QPushButton(mode.capitalize())
            btn.setObjectName("ghostButton" if mode == "list" else "tonalButton")
            btn.setMaximumWidth(60)
            if f"set_view_mode_{mode}" in self.callbacks:
                btn.clicked.connect(self.callbacks[f"set_view_mode_{mode}"])
            layout.addWidget(btn)
            self.view_buttons[mode] = btn

        return header

    def _create_tree_header(self) -> QWidget:
        """ツリービューのヘッダー：2画面モードボタンをここに置く"""
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("Tree")
        title.setObjectName("panelHeader")
        layout.addWidget(title)
        layout.addStretch()

        dual_btn = QPushButton("2画面")
        dual_btn.setCheckable(True)
        if "get_dual_tree_mode" in self.callbacks:
            try:
                dual_btn.setChecked(bool(self.callbacks["get_dual_tree_mode"]()))
            except Exception:
                dual_btn.setChecked(False)
        dual_btn.setObjectName("ghostButton")
        # HTML読み込み完了まで非表示
        dual_btn.setVisible(False)
        dual_btn.toggled.connect(self.toggle_dual_tree.emit)
        if "set_dual_tree_mode" in self.callbacks:
            dual_btn.toggled.connect(self.callbacks["set_dual_tree_mode"])
        self.dual_tree_button = dual_btn
        layout.addWidget(dual_btn)

        return header

    def _create_content_area(self) -> QWidget:
        """コンテンツエリアの生成（ツリーとブックマーク表示の分割エリア）"""
        
        # ツリー操作ボタン
        tree_controls = QWidget()
        self.tree_controls = tree_controls
        tree_controls.setVisible(False)
        tree_controls_layout = QHBoxLayout(tree_controls)
        tree_controls_layout.setContentsMargins(0, 0, 0, 0)
        tree_controls_layout.setSpacing(8)
        
        expand_all_btn = QPushButton("すべて展開")
        expand_all_btn.setObjectName("outlineButton")
        expand_all_btn.setMinimumWidth(80)
        expand_all_btn.clicked.connect(self.expand_all.emit)
        tree_controls_layout.addWidget(expand_all_btn)
        
        collapse_all_btn = QPushButton("すべて縮小")
        collapse_all_btn.setObjectName("ghostButton")
        collapse_all_btn.setMinimumWidth(80)
        collapse_all_btn.clicked.connect(self.collapse_all.emit)
        tree_controls_layout.addWidget(collapse_all_btn)
        
        tree_controls_layout.addSpacing(12)
        
        expand_current_btn = QPushButton("展開")
        expand_current_btn.setObjectName("outlineButton")
        expand_current_btn.setMinimumWidth(60)
        expand_current_btn.clicked.connect(self.expand_current.emit)
        tree_controls_layout.addWidget(expand_current_btn)

        collapse_current_btn = QPushButton("縮小")
        collapse_current_btn.setObjectName("ghostButton")
        collapse_current_btn.setMinimumWidth(60)
        collapse_current_btn.clicked.connect(self.collapse_current.emit)
        tree_controls_layout.addWidget(collapse_current_btn)
        
        tree_controls_layout.addStretch()
        
        # フォルダツリーの設定
        if "on_folder_selected" in self.callbacks:
            self.folder_tree.item_selected.connect(
                lambda node: self.callbacks["on_folder_selected"](node, self.folder_tree)
            )
        if "on_tree_node_moved" in self.callbacks:
            self.folder_tree.node_moved.connect(self.callbacks["on_tree_node_moved"])
        
        # 2画面モード用のツリー
        if "on_folder_selected" in self.callbacks:
            self.folder_tree_left.item_selected.connect(
                lambda node: self.callbacks["on_folder_selected"](node, self.folder_tree_left)
            )
            self.folder_tree_right.item_selected.connect(
                lambda node: self.callbacks["on_folder_selected"](node, self.folder_tree_right)
            )
        if "on_tree_node_moved" in self.callbacks:
            self.folder_tree_left.node_moved.connect(self.callbacks["on_tree_node_moved"])
            self.folder_tree_right.node_moved.connect(self.callbacks["on_tree_node_moved"])
        
        # ツリースクロールエリア
        tree_scroll = QScrollArea()
        tree_scroll.setWidgetResizable(True)
        tree_scroll.setObjectName("treeScroll")
        tree_scroll.setWidget(self.folder_tree)
        tree_scroll.setVisible(False)
        self.tree_scroll = tree_scroll
        
        # 2画面モード用のスプリッター
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

        # ブックマーク表示エリア
        cards_scroll = QScrollArea()
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setObjectName("contentScroll")
        cards_scroll.setWidget(self.bookmark_view)
        self.cards_scroll = cards_scroll

        # ツリーコンテナ
        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.setSpacing(8)
        tree_layout.addWidget(self._create_tree_header())
        tree_layout.addWidget(tree_controls)
        # ツリー領域が縦方向に最大まで広がるようにする（余白削減）
        tree_layout.addWidget(tree_scroll, 1)
        tree_layout.addWidget(dual_tree_splitter, 1)

        # 下側（ブックマーク表示）コンテナ：ヘッダー + スクロール
        bookmarks_container = QWidget()
        bookmarks_layout = QVBoxLayout(bookmarks_container)
        bookmarks_layout.setContentsMargins(0, 0, 0, 0)
        bookmarks_layout.setSpacing(8)
        bookmarks_layout.addWidget(self._create_bookmarks_header())
        bookmarks_layout.addWidget(cards_scroll, 1)

        # メインスプリッター（上下分割）
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(tree_container)
        left_splitter.addWidget(bookmarks_container)
        # ツリー(0)を優先して縮みすぎを防ぐ
        left_splitter.setStretchFactor(0, 3)
        left_splitter.setStretchFactor(1, 2)
        left_splitter.setCollapsible(0, False)
        left_splitter.setSizes([350, 350])
        self.left_splitter = left_splitter

        return left_splitter

    def get_bookmark_view(self) -> 'BookmarkView':
        """ブックマーク表示コンポーネントを返す"""
        return self.bookmark_view
    
    def get_bookmark_list_view(self) -> 'BookmarkView':
        """ブックマークリストビューを取得（後方互換性のため）"""
        return self.bookmark_view

    def update_view_button_style(self, mode: str) -> None:
        for key, btn in self.view_buttons.items():
            btn.setObjectName("tonalButton" if key == mode else "ghostButton")
            btn.style().unpolish(btn)
            btn.style().polish(btn)


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
        title_label.setFont(FontManager.get_heading_font(11))
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
        
        scroll_layout.addWidget(self.actions_container, 0) # 高さを中身に合わせる
        scroll_layout.addWidget(self.detail_panel, 0)      # 詳細も可変（スクロールで担保）
        scroll_layout.addStretch(1)                        # 余った空白を一番下に追いやる
        
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll, stretch=1)
    
    def _initialize_sections(self) -> None:
        """アクションセクションの初期化（不要な重複ボタンを削除）"""
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
            # 「名前変更」「URL編集」「移動」をここから除外（DetailPanelに専念）
            excluded = {"名前変更", "URL編集", "移動"}
            filtered_edit = edit_callbacks
            # ControllerMainWindowからは List[tuple] が来る。dict形式にも一応対応する。
            if isinstance(edit_callbacks, dict):
                filtered_edit = [(k, v) for k, v in edit_callbacks.items() if k not in excluded]
            elif isinstance(edit_callbacks, list):
                filtered_edit = [t for t in edit_callbacks if t and t[0] not in excluded]
            if filtered_edit:
                self.add_action_section(
                    "edit",
                    "✏️ 編集",
                    "中",
                    filtered_edit,
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
    edit_tags_requested = Signal(Node)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        
        self.current_node: Optional[Node] = None
        self._tag_provider: Optional[Callable[[Node], List[str]]] = None
        self._tag_detail_provider: Optional[Callable[[Node], List[Tuple[str, str, Any]]]] = None
        
        # QSSクラス設定
        self.setObjectName("detailPanel")
        self.setWidgetResizable(True)
        
        # コンテンツウィジェット
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(16, 16, 16, 16)
        self.content_layout.setSpacing(12)
        
        self.setWidget(self.content_widget)

    def set_tag_provider(self, provider: Optional[Callable[[Node], List[str]]]) -> None:
        """Tag表示用のプロバイダを設定（DBアクセスはController側に寄せる）。"""
        self._tag_provider = provider

    def set_tag_detail_provider(self, provider: Optional[Callable[[Node], List[Tuple[str, str, Any]]]]) -> None:
        """タグ詳細（name, source, confidence）表示用のプロバイダ。"""
        self._tag_detail_provider = provider
    
    def clear_layout(self, layout: QLayout) -> None:
        """レイアウトを再帰的にクリア"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())
                # QLayoutはQObjectを継承しているのでdeleteLaterが使える
                item.layout().deleteLater()
    
    def set_node(self, node: Node) -> None:
        """ノードを設定して詳細を表示"""
        self.current_node = node
        self.clear_layout(self.content_layout)
        
        # タイトル
        title_label = QLabel("タイトル:")
        title_label.setFont(FontManager.get_heading_font(13))
        title_label.setObjectName("sectionLabel")
        self.content_layout.addWidget(title_label)
        
        title_value = QLabel(node.title or "Untitled")
        title_value.setFont(FontManager.get_body_font(13))
        title_value.setObjectName("valueLabel")
        title_value.setWordWrap(True)
        self.content_layout.addWidget(title_value)
        
        # URL
        if node.url:
            url_label = QLabel("URL:")
            url_label.setFont(FontManager.get_heading_font(13))
            url_label.setObjectName("sectionLabel")
            self.content_layout.addWidget(url_label)
            
            # RichText形式でリンクとして表示
            url_value = QLabel(f'<a href="{node.url}">{node.url}</a>')
            url_value.setFont(FontManager.get_body_font(11))
            url_value.setObjectName("valueLabel")
            url_value.setWordWrap(True)
            url_value.setTextFormat(Qt.TextFormat.RichText)
            url_value.setOpenExternalLinks(False)
            url_value.linkActivated.connect(lambda: self.copy_url_requested.emit(self.current_node.url))
            self.content_layout.addWidget(url_value)
        
        # 説明
        if hasattr(node, 'description') and node.description:
            desc_label = QLabel("説明:")
            desc_label.setFont(FontManager.get_heading_font(13))
            desc_label.setObjectName("sectionLabel")
            self.content_layout.addWidget(desc_label)
            
            desc_value = QLabel(node.description)
            desc_value.setFont(FontManager.get_body_font(12))
            desc_value.setObjectName("valueLabel")
            desc_value.setWordWrap(True)
            self.content_layout.addWidget(desc_value)

        # タグ（ブックマークのみ）
        if getattr(node, "type", "") == "bookmark":
            tags_label = QLabel("タグ:")
            tags_label.setFont(FontManager.get_heading_font(13))
            tags_label.setObjectName("sectionLabel")
            self.content_layout.addWidget(tags_label)

            tags = []
            tag_details: List[Tuple[str, str, Any]] = []
            try:
                if self._tag_detail_provider:
                    tag_details = self._tag_detail_provider(node) or []
                if self._tag_provider:
                    tags = self._tag_provider(node) or []
            except Exception:
                tags = []
                tag_details = []

            if tag_details:
                # 表示例: Dev [rule], Python [manual]
                parts = []
                for name, source, conf in tag_details:
                    s = (source or "").strip() or "unknown"
                    if conf is None or conf == "":
                        parts.append(f"{name} [{s}]")
                    else:
                        try:
                            parts.append(f"{name} [{s} {float(conf):.2f}]")
                        except Exception:
                            parts.append(f"{name} [{s}]")
                tags_text = ", ".join(parts)
            else:
                tags_text = ", ".join(tags) if tags else "(なし)"

            tags_value = QLabel(tags_text)
            tags_value.setFont(FontManager.get_body_font(12))
            tags_value.setObjectName("valueLabel")
            tags_value.setWordWrap(True)
            self.content_layout.addWidget(tags_value)
        
        # 操作ボタンセクション
        self.content_layout.addSpacing(12)
        actions_label = QLabel("操作:")
        actions_label.setFont(FontManager.get_heading_font(13))
        actions_label.setObjectName("sectionLabel")
        self.content_layout.addWidget(actions_label)
        
        # ボタンレイアウト
        button_layout = QVBoxLayout()
        button_layout.setSpacing(6)
        
        # 編集ボタン（current_nodeを参照）
        edit_btn = QPushButton("✎ 編集")
        edit_btn.setObjectName("actionButton")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.current_node))
        button_layout.addWidget(edit_btn)

        # タグ編集（ブックマークのみ）
        if getattr(node, "type", "") == "bookmark":
            tags_btn = QPushButton("🏷 タグ編集")
            tags_btn.setObjectName("actionButton")
            tags_btn.clicked.connect(lambda: self.edit_tags_requested.emit(self.current_node))
            button_layout.addWidget(tags_btn)
        
        # URLコピーボタン
        if node.url:
            copy_btn = QPushButton("📋 URLをコピー")
            copy_btn.setObjectName("actionButton")
            copy_btn.clicked.connect(lambda: self.copy_url_requested.emit(self.current_node.url))
            button_layout.addWidget(copy_btn)
        
        # 移動ボタン
        move_btn = QPushButton("➜ 移動")
        move_btn.setObjectName("actionButton")
        move_btn.clicked.connect(lambda: self.move_requested.emit(self.current_node))
        button_layout.addWidget(move_btn)
        
        # 削除ボタン
        delete_btn = QPushButton("🗑 削除")
        delete_btn.setObjectName("dangerButton")
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.current_node))
        button_layout.addWidget(delete_btn)
        
        self.content_layout.addLayout(button_layout)
        self.content_layout.addStretch()
    
    def clear(self) -> None:
        """詳細パネルをクリア"""
        self.current_node = None
        self.clear_layout(self.content_layout)
        self.content_layout.addStretch()