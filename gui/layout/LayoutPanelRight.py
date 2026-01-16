"""
Right panel management for NeoBookMarkManager.

Consolidated module for all right-side panel components:
- Action sections (File, Edit, Organize, AI Classification)
- Detail panel with bookmark information and actions
"""

from typing import Optional, List, Set, Callable, Dict
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QCursor
from PySide6.QtWidgets import (
    QFrame,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QGridLayout,
    QSizePolicy,
)

from core.ModelBookmark import Node
from gui.UtilGuiResources import Typography


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

