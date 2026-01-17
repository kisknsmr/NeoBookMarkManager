"""UI event controller.

Collects user interaction entrypoints and delegates to window refresh/commands.
"""

from typing import Optional

from core.ModelBookmark import Node
from gui.components import FolderTree


class UIEventController:
    def __init__(self, *, window) -> None:
        self.window = window

    def on_folder_selected(self, node: Node, source_tree: Optional[FolderTree] = None) -> None:
        if getattr(self.window, "tree_ui", None) and self.window.tree_ui.is_building:
            return

        if source_tree is not None and getattr(self.window, "tree_ui", None):
            self.window.tree_ui.sync_selection(node, source_tree)

        if node.type == "folder":
            self.window.current_folder = node
            self.window.selected_node = None
            self.window.detail_panel.clear()
            self.window.refresh_list()
            self.window.refresh_counts()
        else:
            self.window.selected_node = node
            if node.parent:
                self.window.current_folder = node.parent
                self.window.refresh_list()
                self.window.refresh_counts()
            self.window.detail_panel.set_node(node)

    def on_bookmark_node_selected(self, node: Node) -> None:
        self.window.app_state.set_selected_node(node)
        self.window.detail_panel.set_node(node)

    def on_detail_edit(self, node: Node) -> None:
        self.window.selected_node = node
        self.window.cmd_rename()

    def on_detail_move(self, node: Node) -> None:
        self.window.selected_node = node
        self.window.cmd_move_to_folder()

    def on_detail_delete(self, node: Node) -> None:
        self.window._delete_node(node)

    def on_tree_node_moved(self, node: Node, old_parent: Node, new_parent: Node, index: int) -> None:
        if not node or not old_parent or not new_parent:
            return
        if node is self.window.root_node:
            return
        if new_parent is node or self._is_descendant_of(new_parent, node):
            self.window.statusBar().showMessage("Cannot move a folder into its descendant", 3000)
            self.window.refresh_tree(select_node=node)
            return

        old_parent.remove_child(node)
        new_parent.insert_child(index, node)

        self.window.refresh_tree(select_node=node)

    def _is_descendant_of(self, node: Node, folder: Node) -> bool:
        cur = node.parent
        while cur:
            if cur is folder:
                return True
            cur = cur.parent
        return False
