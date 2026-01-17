"""
BookmarkService - Centralized bookmark business logic.

木構造操作、追加・編集・削除・移動・整理などを一元管理。
MainWindow はダイアログ取得と UI 更新のみに専念。
"""

from typing import Optional, List, Set, Tuple
from datetime import datetime
import time
from urllib.parse import urlparse
from pathlib import Path
import datetime

from core.ModelBookmark import Node
from core.UtilLogger import logger


class BookmarkService:
    """
    Business logic for bookmark operations.
    
    Responsibilities:
    - Add/remove/edit bookmarks and folders
    - Move/reorder bookmarks
    - Organize: deduplication, merge, sort
    - Maintains tree invariants
    """

    def __init__(self):
        """Initialize bookmark service."""
        pass

    # ==================== Create ====================
    def create_folder(self, parent: Node, title: str) -> Node:
        """
        Create new folder under parent.
        
        Args:
            parent: Parent folder node
            title: Folder title
            
        Returns:
            New folder node
            
        Raises:
            ValueError: If parent is not a folder
        """
        if parent.type != "folder":
            raise ValueError("Parent must be a folder")

        folder = Node("folder", title=title.strip() or "Untitled")
        parent.append(folder)
        return folder

    def find_or_create_folder(self, parent: Node, name: str) -> Node:
        """Find or create a folder with the given name under parent."""
        for child in parent.children:
            if child.type == "folder" and child.title == name:
                return child
        return self.create_folder(parent, name)

    def create_bookmark(self, parent: Node, url: str, title: Optional[str] = None) -> Node:
        """
        Create new bookmark under parent.
        
        Args:
            parent: Parent folder node
            url: Bookmark URL
            title: Bookmark title (optional, defaults to URL)
            
        Returns:
            New bookmark node
            
        Raises:
            ValueError: If parent is not a folder or URL is invalid
        """
        if parent.type != "folder":
            raise ValueError("Parent must be a folder")

        bookmark = Node(
            "bookmark",
            title=title.strip() if title else url,
            url=url.strip(),
            add_date=str(int(time.time()))
        )
        parent.append(bookmark)
        return bookmark

    # ==================== Edit ====================
    def rename(self, node: Node, new_title: str) -> None:
        """Rename node."""
        if not new_title.strip():
            raise ValueError("Title cannot be empty")
        node.title = new_title.strip()

    def edit_url(self, node: Node, new_url: str) -> None:
        """Edit bookmark URL."""
        if node.type != "bookmark":
            raise ValueError("Only bookmarks have URLs")
        if not new_url.strip():
            raise ValueError("URL cannot be empty")
        node.url = new_url.strip()

    def edit_description(self, node: Node, description: str) -> None:
        """Edit node description."""
        node.description = description.strip()

    def update_node(self, node: Node, *, title: str, url: str) -> bool:
        """タイトルとURLをまとめて更新する（bookmark編集用）。"""
        try:
            if not node:
                return False
            if title is not None:
                node.title = title.strip()
            if node.type == "bookmark" and url is not None:
                node.url = url.strip()
            logger.info(f"Updated node: {node}")
            return True
        except Exception as exc:
            logger.error(f"Update Error: {exc}")
            return False

    # ==================== Move & Reorder ====================
    def move_to_folder(self, node: Node, target_parent: Node, index: Optional[int] = None) -> None:
        """
        Move node to target folder at given index.
        
        Args:
            node: Node to move
            target_parent: Target folder
            index: Position in target (None = append)
            
        Raises:
            ValueError: If move creates cycle or invalid operation
        """
        if node is target_parent:
            raise ValueError("Cannot move node into itself")

        # Check if target_parent is descendant of node (which would create cycle)
        if self._is_descendant_of(node, target_parent):
            raise ValueError("Cannot move node into its descendant")

        if node.type == "folder" and node in (getattr(target_parent, 'children', []) or []):
            raise ValueError("Node already in target parent")

        # Remove from old parent
        old_parent = node.parent
        if old_parent:
            old_parent.remove_child(node)

        # Add to new parent
        if index is None:
            target_parent.append(node)
        else:
            target_parent.insert_child(index, node)

        logger.info(f"Moved {node.type} '{node.title}' to {target_parent.title}")

    def reorder(self, parent: Node, indices: List[int]) -> None:
        """
        Reorder children by given indices.
        
        Args:
            parent: Parent node
            indices: New order of child indices
        """
        if len(indices) != len(parent.children):
            raise ValueError("Index count mismatch")

        new_children = [parent.children[i] for i in indices]
        parent.children = new_children

    def move_up(self, node: Node) -> None:
        """Move node up in sibling list."""
        parent = node.parent
        if not parent:
            raise ValueError("Root node cannot be moved")

        idx = parent.children.index(node)
        if idx <= 0:
            raise ValueError("Already at top")

        parent.move_child(node, idx - 1)

    def move_down(self, node: Node) -> None:
        """Move node down in sibling list."""
        parent = node.parent
        if not parent:
            raise ValueError("Root node cannot be moved")

        idx = parent.children.index(node)
        if idx >= len(parent.children) - 1:
            raise ValueError("Already at bottom")

        parent.move_child(node, idx + 1)

    # ==================== Read helpers ====================
    def iter_bookmarks(self, node: Node) -> List[Node]:
        """Public wrapper to list bookmarks in subtree."""
        return self._iter_bookmarks(node)

    # ==================== Delete ====================
    def delete(self, node: Node) -> None:
        """
        Delete node.
        
        Args:
            node: Node to delete
            
        Raises:
            ValueError: If node is root
        """
        if not node.parent:
            raise ValueError("Cannot delete root node")

        node.parent.remove_child(node)
        logger.info(f"Deleted {node.type} '{node.title}'")

    # ==================== Organize ====================
    def sort_bookmarks(self, criteria: str, parent_node: Node | None = None) -> bool:
        """
        指定されたノード直下の子要素のみをソートする。
        - parent_node が None の場合は何もしない（Controller側で current_folder を渡す想定）
        """
        target = parent_node
        if not target or not getattr(target, "children", None):
            return False
        try:
            self.sort_children(target, key=criteria)
            return True
        except Exception as exc:
            logger.error(f"Sort Error ({criteria}): {exc}")
            return False

    def sort_children(self, parent: Node, key: str = "title", reverse: bool = False) -> None:
        """
        Sort parent's children.
        
        Args:
            parent: Parent node
            key: "title" | "url" | "domain" | "type"
            reverse: Reverse order?
        """
        if key == "title":
            # Folders first, then by title
            parent.children.sort(key=lambda n: (n.type != "folder", (n.title or "").lower()), reverse=reverse)
        elif key == "url":
            parent.children.sort(key=lambda n: (n.url or "").lower(), reverse=reverse)
        elif key == "domain":
            def domain_key(n: Node) -> tuple:
                if n.type == "folder":
                    return (0, (n.title or "").lower())
                raw = (n.url or "")
                try:
                    netloc = (urlparse(raw).netloc or "").lower()
                except Exception:
                    netloc = ""
                if netloc.startswith("www."):
                    netloc = netloc[4:]
                # 空URL/解析不能は最後に寄せる（テスト期待＆使い勝手）
                empty = 1 if not netloc else 0
                return (1, empty, netloc, (n.title or "").lower())

            parent.children.sort(key=domain_key, reverse=reverse)
        elif key == "type":
            # Folders first, then bookmarks
            parent.children.sort(key=lambda n: (n.type != "folder", n.title.lower()), reverse=reverse)
        else:
            raise ValueError(f"Unknown sort key: {key}")

        logger.info(f"Sorted {parent.title} by {key}")

    def delete_duplicates(self, parent: Node) -> int:
        """
        Delete duplicate bookmarks in folder (same URL).
        
        Args:
            parent: Folder to clean
            
        Returns:
            Number of deleted nodes
        """
        seen_urls: Set[str] = set()
        to_delete: List[Node] = []

        for child in parent.children:
            if child.type == "bookmark":
                if child.url in seen_urls:
                    to_delete.append(child)
                else:
                    seen_urls.add(child.url)

        for node in to_delete:
            parent.remove_child(node)

        logger.info(f"Deleted {len(to_delete)} duplicate bookmarks in {parent.title}")
        return len(to_delete)

    def remove_duplicates(self, parent: Node, *, log_file_path: str | Path | None = None) -> tuple[int, list[str]]:
        """
        重複を削除し、(削除件数, 削除した情報のリスト) を返す。
        - 対象は parent 直下のみ（既存挙動に合わせる）
        - log_file_path が指定されていれば logs に追記する
        """
        if not parent or not getattr(parent, "children", None):
            return (0, [])

        seen_urls: set[str] = set()
        to_delete: List[Node] = []
        removed_info: List[str] = []

        for child in list(parent.children):
            if child.type != "bookmark":
                continue
            url = child.url or ""
            if not url:
                continue
            if url in seen_urls:
                to_delete.append(child)
                removed_info.append(f"{child.title} ({url})")
            else:
                seen_urls.add(url)

        for node in to_delete:
            parent.remove_child(node)

        removed_count = len(to_delete)
        logger.info(f"Removed {removed_count} duplicate bookmarks in {getattr(parent, 'title', '')}")

        if removed_count and log_file_path:
            try:
                path = Path(log_file_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as f:
                    f.write(f"\n--- {datetime.datetime.now().isoformat(timespec='seconds')} ---\n")
                    for line in removed_info:
                        f.write(f"Removed: {line}\n")
            except Exception as exc:
                logger.error(f"Failed to write cleanup log: {exc}")

        return (removed_count, removed_info)

    def merge_duplicate_folders(self, parent: Node) -> int:
        """
        Merge folders with same name (recursively).
        
        Args:
            parent: Folder to clean
            
        Returns:
            Number of merged folders
        """
        merged_count = 0
        folder_map: dict = {}

        for child in list(parent.children):
            if child.type == "folder":
                key = child.title.lower()
                if key in folder_map:
                    # Merge: move all children to first folder
                    target = folder_map[key]
                    for grandchild in list(child.children):
                        target.append(grandchild)
                    parent.remove_child(child)
                    merged_count += 1
                else:
                    folder_map[key] = child

        logger.info(f"Merged {merged_count} duplicate folders in {parent.title}")
        return merged_count

    def apply_rules(self, root: Node, rules: List[dict]) -> Tuple[int, int]:
        """
        Apply classification rules to bookmarks.
        
        Args:
            root: Root node
            rules: List of {"pattern": regex, "target_folder": path} rules
            
        Returns:
            (bookmarks_processed, bookmarks_moved)
        """
        if not rules:
            return (0, 0)

        moved = 0
        for node in self._iter_bookmarks(root):
            for rule in rules:
                pattern = rule.get("pattern", "")
                target_path = rule.get("target_folder", "")

                # Simple pattern matching: if pattern in title/url
                if pattern.lower() in (node.title + node.url).lower():
                    target = self._find_folder_by_path(root, target_path)
                    if target:
                        self.move_to_folder(node, target)
                        moved += 1
                        break

        return (len(list(self._iter_bookmarks(root))), moved)

    # ==================== Utilities ====================
    def _is_descendant_of(self, ancestor: Node, node: Node) -> bool:
        """Check if node is descendant of ancestor."""
        # Walk up from node to see if we reach ancestor
        current = node.parent
        while current is not None:
            if current is ancestor:
                return True
            current = current.parent
        return False

    def _iter_bookmarks(self, node: Node) -> List[Node]:
        """Iterate all bookmarks in subtree."""
        bookmarks = []
        for child in node.children:
            if child.type == "bookmark":
                bookmarks.append(child)
            else:
                bookmarks.extend(self._iter_bookmarks(child))
        return bookmarks

    def _find_folder_by_path(self, root: Node, path: str) -> Optional[Node]:
        """
        Find folder by path (e.g., "News/Tech").
        
        Args:
            root: Root node
            path: Folder path
            
        Returns:
            Folder node or None
        """
        if not path or path == "/":
            return root

        parts = [p for p in path.split("/") if p]
        current = root

        for part in parts:
            found = False
            for child in current.children:
                if child.type == "folder" and child.title == part:
                    current = child
                    found = True
                    break
            if not found:
                return None

        return current
