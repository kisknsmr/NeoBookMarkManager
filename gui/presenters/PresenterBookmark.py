"""Bookmark presenter.

Moves list rendering + count computation out of MainWindow.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Set

from core.ModelBookmark import Node


class BookmarkPresenter:
    def get_display_nodes(
        self,
        *,
        current_folder: Optional[Node],
        search_query: str,
        search_hits: Set[Node],
    ) -> List[Node]:
        if not current_folder:
            return []

        base_nodes = [ch for ch in current_folder.children if ch.type == "bookmark"]
        if not search_query:
            return base_nodes

        filtered: List[Node] = []
        for node in search_hits:
            if self.is_descendant_of(node, current_folder):
                filtered.append(node)
        return filtered

    def is_descendant_of(self, node: Node, folder: Node) -> bool:
        cur = node.parent
        while cur:
            if cur is folder:
                return True
            cur = cur.parent
        return False

    def iter_bookmarks(self, node: Node) -> Iterable[Node]:
        for child in getattr(node, "children", []) or []:
            if child.type == "bookmark":
                yield child
            elif child.type == "folder":
                yield from self.iter_bookmarks(child)

    def count_bookmarks(self, root_node: Optional[Node]) -> int:
        if not root_node:
            return 0
        return sum(1 for _ in self.iter_bookmarks(root_node))

    def refresh_list(
        self,
        *,
        bookmark_list_view,
        detail_panel,
        preview_cache,
        nodes: List[Node],
        view_mode: str,
        preview_requester,
    ) -> None:
        bookmark_list_view.set_items(nodes, view_mode=view_mode)

        for node in nodes:
            if node.url and node.url not in preview_cache:
                preview_cache[node.url] = True
                preview_requester(node)

        if not nodes:
            detail_panel.clear()

    def update_counts(self, *, bookmarks_count_label, workspace_count_label, total: int) -> None:
        if bookmarks_count_label is not None:
            bookmarks_count_label.setText(f"{total:,}")
        if workspace_count_label is not None:
            workspace_count_label.setText(f"{total:,}")
