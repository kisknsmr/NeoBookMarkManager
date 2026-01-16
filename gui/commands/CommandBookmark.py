"""
Bookmark management commands.
Handles creation, renaming, moving, editing bookmarks/folders.
"""

from PySide6.QtWidgets import QInputDialog, QMessageBox

from core.ModelBookmark import Node
from core.UtilCoreUtils import is_valid_url
from gui.layout.LayoutDialogs import FolderSelectDialog


class BookmarkCommands:
    """Commands for bookmark and folder management."""

    def __init__(self, window):
        """
        Initialize with main window reference.
        
        Args:
            window: MainWindow instance
        """
        self.window = window

    def new_folder(self) -> None:
        """Create new folder with user input."""
        if not self.window.current_folder or self.window.current_folder.type != "folder":
            QMessageBox.warning(self.window, "Warning", "Select a folder first.")
            return
        
        name, ok = QInputDialog.getText(self.window, "New Folder", "Folder name:")
        if not ok or not name.strip():
            return
        
        new_node = Node("folder", name.strip())
        self.window.current_folder.append(new_node)
        
        # Folders don't need search index update, just refresh tree and counts
        self.window.refresh_tree(select_node=new_node)
        self.window.refresh_counts()

    def new_bookmark(self) -> None:
        """Create new bookmark with user input."""
        if not self.window.current_folder or self.window.current_folder.type != "folder":
            QMessageBox.warning(self.window, "Warning", "Select a folder first.")
            return
        
        url, ok = QInputDialog.getText(self.window, "New Bookmark", "URL:")
        if not ok or not url.strip():
            return
        
        if not is_valid_url(url.strip()):
            QMessageBox.warning(self.window, "Warning", "Enter a valid URL (http/https).")
            return
        
        title, _ = QInputDialog.getText(self.window, "New Bookmark", "Title (optional):")
        node = Node("bookmark", title=title.strip() or url.strip(), url=url.strip())
        self.window.current_folder.append(node)
        
        # Add to search index and refresh
        self.window.search_service.add_node(node)
        self.window.refresh_list()
        self.window.refresh_counts()

        self.window.commands.network.enqueue_preview_fetch(node)

    def rename(self) -> None:
        """Rename selected bookmark or folder."""
        if not self.window.selected_node:
            QMessageBox.information(self.window, "Info", "Select an item to rename.")
            return
        
        name, ok = QInputDialog.getText(
            self.window,
            "Rename",
            "New name:",
            text=self.window.selected_node.title
        )
        if not ok or not name.strip():
            return
        
        self.window.selected_node.title = name.strip()
        
        # Update search index and refresh
        self.window.search_service.update_node(self.window.selected_node)
        self.window.refresh_list()
        self.window.refresh_counts()
        
        # If renaming folder, update tree
        if self.window.selected_node.type == "folder":
            self.window.refresh_tree(select_node=self.window.selected_node)

    def edit_url(self) -> None:
        """Edit URL of selected bookmark."""
        if not self.window.selected_node or self.window.selected_node.type != "bookmark":
            QMessageBox.information(self.window, "Info", "Select a bookmark to edit.")
            return
        
        url, ok = QInputDialog.getText(
            self.window,
            "Edit URL",
            "URL:",
            text=self.window.selected_node.url
        )
        if not ok or not url.strip():
            return
        
        if not is_valid_url(url.strip()):
            QMessageBox.warning(self.window, "Warning", "Enter a valid URL.")
            return
        
        self.window.selected_node.url = url.strip()
        
        # Update search index and refresh list only
        self.window.search_service.update_node(self.window.selected_node)
        self.window.refresh_list()
        self.window.refresh_counts()

    def move_to_folder(self) -> None:
        """Move selected bookmark/folder to target folder."""
        if not self.window.selected_node or not self.window.root_node:
            QMessageBox.information(self.window, "Info", "Select an item to move.")
            return
        
        dialog = FolderSelectDialog(
            self.window,
            root_node=self.window.root_node,
            exclude_nodes=[self.window.selected_node]
        )
        if dialog.exec() != dialog.Accepted or not dialog.result:
            return
        
        target_folder = dialog.result
        if target_folder.type != "folder":
            QMessageBox.warning(self.window, "Warning", "Target must be a folder.")
            return
        
        parent = self.window.selected_node.parent
        if parent:
            parent.remove_child(self.window.selected_node)
        target_folder.append(self.window.selected_node)
        self.window.current_folder = target_folder
        
        # Move doesn't change search index (title/url unchanged), just refresh tree and list
        self.window.refresh_tree(select_node=target_folder)
        self.window.refresh_list()
        self.window.refresh_counts()

    def move_up(self) -> None:
        """Move selected item up in siblings."""
        if not self.window.selected_node or not self.window.selected_node.parent:
            return
        
        parent = self.window.selected_node.parent
        siblings = parent.children
        idx = siblings.index(self.window.selected_node)
        if idx <= 0:
            return
        
        parent.move_child(self.window.selected_node, idx - 1)
        
        # Move doesn't change search, just refresh tree
        self.window.refresh_tree(select_node=self.window.selected_node)

    def delete(self) -> None:
        """Delete selected bookmark/folder."""
        if not self.window.selected_node:
            QMessageBox.information(self.window, "Info", "Select an item to delete.")
            return

        self.delete_node(self.window.selected_node)

    def delete_node(self, node: Node) -> None:
        """Delete a bookmark or folder node (use-case)."""
        if not node or not node.parent:
            return

        res = QMessageBox.question(
            self.window,
            "Delete",
            f"Delete '{node.title}'?",
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        parent = node.parent

        # Update search index (bookmarks only)
        if node.type == "bookmark":
            self.window.search_service.remove_node(node)
        elif node.type == "folder":
            # Remove all bookmarks in subtree from search index
            for bm in self._iter_bookmarks(node):
                self.window.search_service.remove_node(bm)

        parent.remove_child(node)

        self.window.refresh_tree(select_node=parent)
        self.window.refresh_list()
        self.window.refresh_counts()
        self.window.statusBar().showMessage(f"Deleted: {node.title}", 2000)

    def _iter_bookmarks(self, node: Node):
        for child in getattr(node, "children", []) or []:
            if child.type == "bookmark":
                yield child
            elif child.type == "folder":
                yield from self._iter_bookmarks(child)

    def delete_duplicates(self) -> None:
        """Delete duplicate bookmarks in current folder."""
        if not self.window.current_folder:
            return
        
        removed = self.window.bookmark_service.delete_duplicates(self.window.current_folder)
        
        # Rebuild search since multiple nodes were deleted
        self.window.search_service.rebuild(self.window.root_node)
        self.window.refresh_list()
        self.window.refresh_tree(select_node=self.window.current_folder)
        self.window.refresh_counts()
        self.window.statusBar().showMessage(f"Removed {removed} duplicate bookmarks", 3000)

    def merge_duplicate_folders(self) -> int:
        """Merge duplicate folders in current folder."""
        if not self.window.current_folder:
            return 0
        
        removed = self.window.bookmark_service.merge_duplicate_folders(self.window.current_folder)
        
        # Rebuild search since structure changed
        self.window.search_service.rebuild(self.window.root_node)
        self.window.refresh_tree(select_node=self.window.current_folder)
        self.window.refresh_list()
        self.window.refresh_counts()
        self.window.statusBar().showMessage(f"Merged {removed} duplicate folders", 3000)
        return removed

    def sort_by_title(self) -> None:
        """Sort bookmarks in current folder by title."""
        if not self.window.current_folder:
            return
        
        self.window.bookmark_service.sort_children(self.window.current_folder, "title")
        
        # Sort doesn't change search, just refresh tree and list
        self.window.refresh_tree(select_node=self.window.current_folder)
        self.window.refresh_list()
        self.window.statusBar().showMessage("Sorted by title", 2000)

    def sort_by_domain(self) -> None:
        """Sort bookmarks in current folder by domain."""
        if not self.window.current_folder:
            return
        
        self.window.bookmark_service.sort_children(self.window.current_folder, "url")
        
        # Sort doesn't change search, just refresh tree and list
        self.window.refresh_tree(select_node=self.window.current_folder)
        self.window.refresh_list()
        self.window.statusBar().showMessage("Sorted by domain", 2000)
