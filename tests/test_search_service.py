"""
Test SearchService bookmark search logic.
"""

import pytest
from core.ModelBookmark import Node
from services.ServiceSearch import SearchService


class TestSearchService:
    """Tests for SearchService."""

    def test_rebuild_index(self, sample_tree):
        """Test index rebuilding."""
        service = SearchService()
        service.rebuild(sample_tree)
        
        # Should have indexed all bookmarks (5 total: Python, Django, HN, TechNews, + duplicates)
        # Actually 7: Python.org, Django Docs, HN, Tech News, Dup Python1, Dup Python2, Dup Django1
        assert len(service.search_index) >= 5
        
        # Check URL lookup
        assert "https://python.org" in service.url_lookup
        assert len(service.url_lookup["https://python.org"]) >= 1

    def test_query_single_token(self, search_service):
        """Test single token search."""
        hits = search_service.query("python")
        
        assert len(hits) >= 1
        # Should find Python-related bookmarks
        titles = [node.title for node in hits]
        assert any("Python" in title for title in titles)

    def test_query_multiple_tokens(self, search_service):
        """Test multi-token AND search."""
        hits = search_service.query("python org")
        
        # Should find "Python.org"
        assert len(hits) >= 1
        titles = [node.title for node in hits]
        assert any("Python" in title for title in titles)

    def test_query_case_insensitive(self, search_service):
        """Test case-insensitive search."""
        hits1 = search_service.query("PYTHON")
        hits2 = search_service.query("python")
        
        assert len(hits1) == len(hits2)

    def test_query_no_results(self, search_service):
        """Test search with no results."""
        hits = search_service.query("nonexistent_bookmark")
        
        assert len(hits) == 0

    def test_query_empty_string(self, search_service):
        """Test empty query."""
        hits = search_service.query("")
        assert len(hits) == 0
        
        hits = search_service.query("   ")
        assert len(hits) == 0

    def test_find_by_url(self, search_service):
        """Test finding nodes by URL."""
        nodes = search_service.find_by_url("https://python.org")
        
        assert len(nodes) >= 1
        assert nodes[0].url == "https://python.org"

    def test_find_by_url_not_found(self, search_service):
        """Test finding non-existent URL."""
        nodes = search_service.find_by_url("https://nonexistent.invalid")
        
        assert len(nodes) == 0

    def test_search_preserves_tree_structure(self, sample_tree):
        """Verify search doesn't modify tree structure."""
        service = SearchService()
        service.rebuild(sample_tree)
        
        original_count = len(list(self._count_all_nodes(sample_tree)))
        
        # Perform searches
        service.query("python")
        service.query("news")
        service.query("nothing")
        
        final_count = len(list(self._count_all_nodes(sample_tree)))
        assert original_count == final_count

    @staticmethod
    def _count_all_nodes(node):
        """Helper to count all nodes in tree."""
        yield node
        for child in node.children:
            yield from TestSearchService._count_all_nodes(child)
