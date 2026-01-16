"""
SearchService - Bookmark search logic (independent from UI).

検索インデックス構築とクエリ実行を一元管理。
UI が検索ロジックに依存しない設計。
"""

import re
from typing import Dict, List, Set
from core.model import Node


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
