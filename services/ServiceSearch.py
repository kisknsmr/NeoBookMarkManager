"""
SearchService - Bookmark search logic (independent from UI).

検索インデックス構築とクエリ実行を一元管理。
UI が検索ロジックに依存しない設計。
"""

import re
from typing import Dict, List, Set
from core.ModelBookmark import Node


class SearchService:
    """
    Bookmark search engine.
    
    Handles:
    - Index building: search_index, url_lookup
    - Query execution: text search with AND semantics
    """

    def __init__(self):
        """Initialize search service."""
        self.search_index: Dict[Node, str] = {}
        self.url_lookup: Dict[str, List[Node]] = {}

    def rebuild(self, root: Node) -> None:
        """
        Rebuild search index from root node tree.
        
        Args:
            root: Root bookmark node
        """
        self.search_index.clear()
        self.url_lookup.clear()

        for node in self._iter_bookmarks(root):
            # Index: title + url (lowercased for search)
            text = f"{node.title} {node.url}".lower()
            self.search_index[node] = text

            # URL lookup: fast node lookup by URL
            if node.url:
                self.url_lookup.setdefault(node.url, []).append(node)

    def query(self, text: str) -> Set[Node]:
        """
        Execute search query (AND semantics: all tokens must match).
        
        Args:
            text: Search query (space-separated tokens)
            
        Returns:
            Set of matching nodes
        """
        text = text.strip()
        if not text:
            return set()

        # Split by whitespace and filter empty tokens
        tokens = [t for t in re.split(r"\s+", text.lower()) if t]
        if not tokens:
            return set()

        # AND semantics: all tokens must be present
        hits: Set[Node] = set()
        for node, indexed_text in self.search_index.items():
            if all(tok in indexed_text for tok in tokens):
                hits.add(node)

        return hits

    def find_by_url(self, url: str) -> List[Node]:
        """
        Find all nodes with given URL.
        
        Args:
            url: URL to search for
            
        Returns:
            List of nodes with this URL
        """
        return self.url_lookup.get(url, [])

    def add_node(self, node: Node) -> None:
        """
        Add a new bookmark node to the search index.
        
        Call this when a new bookmark is created (instead of rebuild).
        
        Args:
            node: Bookmark node to add
        """
        if node.type != "bookmark":
            return
        
        # Add to search index
        text = f"{node.title} {node.url}".lower()
        self.search_index[node] = text
        
        # Add to URL lookup
        if node.url:
            self.url_lookup.setdefault(node.url, []).append(node)

    def update_node(self, node: Node) -> None:
        """
        Update an existing bookmark node in the search index.
        
        Call this when a bookmark's title or URL changes (rename/edit_url).
        
        Args:
            node: Bookmark node to update
        """
        if node.type != "bookmark":
            return
        
        # Remove old URL lookup entry if URL changed
        old_text = self.search_index.get(node, "")
        old_url = None
        for url, nodes in list(self.url_lookup.items()):
            if node in nodes:
                old_url = url
                break
        
        # Update search index with new title/URL
        text = f"{node.title} {node.url}".lower()
        self.search_index[node] = text
        
        # Update URL lookup if URL changed
        if old_url and old_url != node.url:
            self.url_lookup[old_url].remove(node)
            if not self.url_lookup[old_url]:
                del self.url_lookup[old_url]
            
            if node.url:
                self.url_lookup.setdefault(node.url, []).append(node)

    def remove_node(self, node: Node) -> None:
        """
        Remove a bookmark node from the search index.
        
        Call this when a bookmark is deleted.
        
        Args:
            node: Bookmark node to remove
        """
        if node.type != "bookmark":
            return
        
        # Remove from search index
        if node in self.search_index:
            del self.search_index[node]
        
        # Remove from URL lookup
        if node.url and node.url in self.url_lookup:
            if node in self.url_lookup[node.url]:
                self.url_lookup[node.url].remove(node)
                if not self.url_lookup[node.url]:
                    del self.url_lookup[node.url]

    def _iter_bookmarks(self, node: Node) -> List[Node]:
        """
        Recursively iterate all bookmark nodes in subtree.
        
        Args:
            node: Start node
            
        Returns:
            List of all bookmark nodes
        """
        bookmarks = []
        for child in node.children:
            if child.type == "bookmark":
                bookmarks.append(child)
            else:
                bookmarks.extend(self._iter_bookmarks(child))
        return bookmarks
