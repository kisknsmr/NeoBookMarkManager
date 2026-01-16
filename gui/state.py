"""
AppState - Unified application state container.

集約された状態を管理し、変更を通知可能な dataclass。
UI と business logic の境界を明確にする。
"""

from dataclasses import dataclass, field
from typing import Optional, Set
from PySide6.QtCore import QObject, Signal

from core.model import Node


class AppStateSignals(QObject):
    """Signals for state changes."""
    state_changed = Signal()
    current_folder_changed = Signal(object)  # Node
    selected_node_changed = Signal(object)   # Optional[Node]
    search_query_changed = Signal(str)
    view_mode_changed = Signal(str)
    dual_tree_mode_changed = Signal(bool)


@dataclass
class AppState:
    """
    統一された UI 状態コンテナ。
    
    Attributes:
        root_node: ルートノード（ブックマーク木構造）
        current_folder: 現在表示中のフォルダ
        selected_node: 選択中のノード
        search_query: 検索クエリ
        search_hits: 検索結果のノード集合
        view_mode: "card" or "list"
        dual_tree_mode: 2画面ツリーモード有効か
        use_proxy: プロキシ使用フラグ
        current_file: 現在開いているファイルパス
        rules: ブックマーク分類ルール
        rules_path: ルールファイルパス
    """
    root_node: Node = field(default_factory=lambda: Node("folder", "Bookmarks"))
    current_folder: Optional[Node] = None
    selected_node: Optional[Node] = None
    search_query: str = ""
    search_hits: Set[Node] = field(default_factory=set)
    view_mode: str = "card"  # "card" | "list"
    dual_tree_mode: bool = False
    use_proxy: bool = False
    current_file: Optional[str] = None
    rules: list = field(default_factory=list)
    rules_path: Optional[str] = None

    # Signals
    _signals: Optional[AppStateSignals] = field(default=None, init=False, repr=False)

    def __post_init__(self):
        """Initialize signals."""
        self._signals = AppStateSignals()
        if self.current_folder is None:
            self.current_folder = self.root_node

    @property
    def signals(self) -> AppStateSignals:
        """Get state signals."""
        if self._signals is None:
            self._signals = AppStateSignals()
        return self._signals

    def set_current_folder(self, folder: Optional[Node]) -> None:
        """Set current folder and emit signal."""
        if folder is not None and folder.type != "folder":
            raise ValueError("Node must be a folder")
        self.current_folder = folder
        self._signals.current_folder_changed.emit(folder)
        self._signals.state_changed.emit()

    def set_selected_node(self, node: Optional[Node]) -> None:
        """Set selected node and emit signal."""
        self.selected_node = node
        self._signals.selected_node_changed.emit(node)
        self._signals.state_changed.emit()

    def set_search_query(self, query: str) -> None:
        """Set search query and emit signal."""
        self.search_query = query.strip()
        self._signals.search_query_changed.emit(self.search_query)
        self._signals.state_changed.emit()

    def set_view_mode(self, mode: str) -> None:
        """Set view mode ('card' or 'list') and emit signal."""
        if mode not in ("card", "list"):
            raise ValueError(f"Invalid view mode: {mode}")
        self.view_mode = mode
        self._signals.view_mode_changed.emit(mode)
        self._signals.state_changed.emit()

    def set_dual_tree_mode(self, enabled: bool) -> None:
        """Set dual tree mode and emit signal."""
        self.dual_tree_mode = enabled
        self._signals.dual_tree_mode_changed.emit(enabled)
        self._signals.state_changed.emit()

    def set_root_node(self, node: Node) -> None:
        """Set root node and reset UI state."""
        if node.type != "folder":
            raise ValueError("Root must be a folder")
        self.root_node = node
        self.current_folder = node
        self.selected_node = None
        self.search_query = ""
        self.search_hits.clear()
        self._signals.state_changed.emit()

    def set_proxy_enabled(self, enabled: bool) -> None:
        """Set proxy enabled flag."""
        self.use_proxy = enabled
        self._signals.state_changed.emit()

    def set_current_file(self, file_path: Optional[str]) -> None:
        """Set current file."""
        self.current_file = file_path
        self._signals.state_changed.emit()

    def set_rules(self, rules: list, rules_path: Optional[str] = None) -> None:
        """Set classification rules."""
        self.rules = rules
        self.rules_path = rules_path
        self._signals.state_changed.emit()

    def clear_search(self) -> None:
        """Clear search results."""
        self.set_search_query("")
        self.search_hits.clear()
