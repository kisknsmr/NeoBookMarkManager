"""Tree UI controller.

Bridges MainWindow UI widgets and TreeController (tree generation logic).
"""

from typing import Optional, Set

from core.ModelBookmark import Node
from gui.components import FolderTree


class TreeUIController:
    def __init__(
        self,
        *,
        tree_controller,
        get_root,
        get_current_folder,
        get_search_hits,
        get_search_query,
        get_dual_tree_mode,
        get_trees,
        get_all_trees,
    ) -> None:
        self.tree_controller = tree_controller
        self._get_root = get_root
        self._get_current_folder = get_current_folder
        self._get_search_hits = get_search_hits
        self._get_search_query = get_search_query
        self._get_dual_tree_mode = get_dual_tree_mode
        self._get_trees = get_trees
        self._get_all_trees = get_all_trees

        self._building = False

    @property
    def is_building(self) -> bool:
        return self._building

    def refresh(self, select_node: Optional[Node] = None) -> None:
        trees = self._get_trees()
        root = self._get_root()
        if not trees or not root:
            return

        if select_node is None:
            select_node = self._get_current_folder() or root

        self._building = True
        try:
            hits: Set[Node] = set(self._get_search_hits() or set())
            query = self._get_search_query() or ""
            self.tree_controller.rebuild_all(
                trees=trees,
                root=root,
                select_node=select_node,
                filter_hits=hits,
                filter_active=bool(query.strip()),
                dual_tree_mode=bool(self._get_dual_tree_mode()),
            )
        finally:
            self._building = False

    def sync_selection(self, node: Node, source_tree: FolderTree) -> None:
        trees = self._get_all_trees()
        self.tree_controller.sync_selection(trees, node, source_tree)
