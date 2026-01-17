"""
Tree controller for managing folder tree operations.
Handles tree population, filtering, selection, and synchronization.
"""

from typing import Any, Optional, Set

from PySide6.QtCore import Qt, QSignalBlocker

from core.ModelBookmark import Node
from gui.components import FolderTree


class TreeController:
    """Controller for managing FolderTree operations."""

    def __init__(self):
        pass

    def rebuild(
        self,
        tree: FolderTree,
        root: Node,
        select_node: Optional[Node] = None,
        filter_hits: Optional[Set[Node]] = None,
        filter_active: bool = False,
    ) -> None:
        """
        Rebuild the entire tree with optional filtering and selection.

        Args:
            tree: FolderTree widget to populate
            root: Root node of the bookmark tree
            select_node: Node to select after rebuild
            filter_hits: Set of nodes matching search filter
            filter_active: Whether filtering is active
        """
        tree.clear()
        filter_hits = filter_hits or set()

        def should_include(node: Node) -> bool:
            """Check if node should be included based on filter."""
            if not filter_active:
                return True
            return node in filter_hits

        def add_folder(node: Node, parent_item=None) -> Optional[Any]:
            """Recursively add folder and children to tree."""
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

            # Remove empty folders when filtering
            if filter_active and not should_include(node) and not has_visible_child:
                if parent_item is None:
                    # Keep root when filtering so tree stays anchored
                    return item
                if item.parent():
                    item.parent().removeChild(item)
                return None

            return item

        # Build tree from root
        root_item = add_folder(root, None)
        tree.expandAll()

        # Select specified node if provided
        if select_node is not None:
            self.select_node(tree, select_node, root_item)
        else:
            tree.setCurrentItem(root_item)

    def select_node(
        self,
        tree: FolderTree,
        target: Node,
        root_item: Optional[Any] = None,
    ) -> None:
        """
        Select a specific node in the tree.

        Args:
            tree: FolderTree widget
            target: Node to select
            root_item: Root tree item (if known), for optimization
        """
        def walk(item):
            """Recursively search for target node."""
            if item.data(0, Qt.ItemDataRole.UserRole) is target:
                tree.setCurrentItem(item)
                return True
            for i in range(item.childCount()):
                if walk(item.child(i)):
                    return True
            return False

        # If root_item is provided, start from there
        if root_item is not None:
            walk(root_item)
            return

        # Otherwise search from all top-level items
        for i in range(tree.topLevelItemCount()):
            if walk(tree.topLevelItem(i)):
                break

    def sync_selection(
        self,
        trees: list,
        node: Node,
        source_tree: FolderTree,
    ) -> None:
        """
        Synchronize selection across multiple trees.

        Args:
            trees: List of FolderTree widgets to synchronize
            node: Node to select in other trees
            source_tree: The tree that initiated the selection (skip this)
        """
        for tree in trees:
            if tree is source_tree:
                continue
            with QSignalBlocker(tree):
                self.select_node(tree, node)

    def rebuild_all(
        self,
        trees: list,
        root: Node,
        select_node: Optional[Node] = None,
        filter_hits: Optional[Set[Node]] = None,
        filter_active: bool = False,
        dual_tree_mode: bool = False,
    ) -> None:
        """
        Rebuild all trees (single or dual mode).

        Args:
            trees: List of FolderTree widgets (single tree or left/right/main)
            root: Root node of the bookmark tree
            select_node: Node to select after rebuild
            filter_hits: Set of nodes matching search filter
            filter_active: Whether filtering is active
            dual_tree_mode: Whether to use dual tree mode
        """
        if not trees:
            return

        # Rebuild primary tree
        primary_tree = trees[0]
        with QSignalBlocker(primary_tree):
            self.rebuild(
                primary_tree,
                root,
                select_node=select_node,
                filter_hits=filter_hits,
                filter_active=filter_active,
            )

        # Rebuild dual trees if present
        if dual_tree_mode and len(trees) >= 2:
            for tree in trees[1:]:
                with QSignalBlocker(tree):
                    self.rebuild(
                        tree,
                        root,
                        select_node=select_node,
                        filter_hits=filter_hits,
                        filter_active=filter_active,
                    )
