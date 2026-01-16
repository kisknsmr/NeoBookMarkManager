"""
Bookmark list view component for displaying bookmarks as cards or rows.
Handles item display, selection, and signals for main window.
"""

from typing import Any, List, Optional, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.ModelBookmark import Node
from gui.layout.LayoutComponents import BookmarkCard, BookmarkRow


class BookmarkListView(QFrame):
    """Widget for displaying bookmarks as cards or list rows."""

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
