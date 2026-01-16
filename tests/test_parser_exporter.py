"""
Test core model parsing and exporting (Netscape bookmark format).
"""

import pytest
from core.model import Node, NetscapeBookmarkParser, export_netscape_html


class TestNetscapeParser:
    """Tests for HTML bookmark parser."""

    def test_parse_empty_bookmarks(self):
        """Parse minimal valid bookmark HTML."""
        html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
        <META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
        <TITLE>Bookmarks</TITLE>
        <H1>Bookmarks</H1>
        <DL><p>
        </DL><p>
        """
        parser = NetscapeBookmarkParser()
        parser.feed(html)
        
        assert parser.root is not None
        assert parser.root.type == "folder"
        assert parser.root.title == "Bookmarks"
        assert len(parser.root.children) == 0

    def test_parse_flat_bookmarks(self):
        """Parse flat bookmark structure."""
        html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
        <DL><p>
            <DT><A HREF="https://example.com" ADD_DATE="1672531200">Example</A>
            <DT><A HREF="https://google.com">Google</A>
        </DL><p>
        """
        parser = NetscapeBookmarkParser()
        parser.feed(html)
        
        assert len(parser.root.children) == 2
        assert parser.root.children[0].type == "bookmark"
        assert parser.root.children[0].title == "Example"
        assert parser.root.children[0].url == "https://example.com"
        assert parser.root.children[1].title == "Google"

    def test_parse_nested_folders(self):
        """Parse nested folder structure."""
        html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
        <DL><p>
            <DT><H3 ADD_DATE="1672531200">Tech</H3>
            <DL><p>
                <DT><A HREF="https://python.org">Python</A>
                <DT><A HREF="https://rust-lang.org">Rust</A>
            </DL><p>
            <DT><H3>News</H3>
            <DL><p>
                <DT><A HREF="https://news.ycombinator.com">HN</A>
            </DL><p>
        </DL><p>
        """
        parser = NetscapeBookmarkParser()
        parser.feed(html)
        
        assert len(parser.root.children) == 2
        assert parser.root.children[0].type == "folder"
        assert parser.root.children[0].title == "Tech"
        assert len(parser.root.children[0].children) == 2
        assert parser.root.children[1].title == "News"

    def test_parse_with_icons(self):
        """Parse bookmarks with icon data."""
        html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
        <DL><p>
            <DT><A HREF="https://example.com" ICON="data:image/x-icon;base64,...">Example</A>
        </DL><p>
        """
        parser = NetscapeBookmarkParser()
        parser.feed(html)
        
        node = parser.root.children[0]
        assert node.icon == "data:image/x-icon;base64,..."


class TestNetscapeExporter:
    """Tests for HTML bookmark exporter."""

    def test_export_empty_tree(self):
        """Export empty tree."""
        root = Node("folder", "Bookmarks")
        html = export_netscape_html(root)
        
        assert "<!DOCTYPE NETSCAPE-Bookmark-file-1>" in html
        assert "Bookmarks" in html
        assert "</DL>" in html

    def test_export_flat_bookmarks(self):
        """Export flat bookmark structure."""
        root = Node("folder", "Bookmarks")
        b1 = Node("bookmark", "Example", url="https://example.com")
        b2 = Node("bookmark", "Google", url="https://google.com")
        root.append(b1)
        root.append(b2)
        
        html = export_netscape_html(root)
        
        assert "Example" in html
        assert "https://example.com" in html
        assert "Google" in html
        assert "https://google.com" in html

    def test_export_nested_folders(self):
        """Export nested folder structure."""
        root = Node("folder", "Bookmarks")
        
        tech = Node("folder", "Tech")
        tech.append(Node("bookmark", "Python", url="https://python.org"))
        tech.append(Node("bookmark", "Rust", url="https://rust-lang.org"))
        root.append(tech)
        
        news = Node("folder", "News")
        news.append(Node("bookmark", "HN", url="https://news.ycombinator.com"))
        root.append(news)
        
        html = export_netscape_html(root)
        
        assert "Tech" in html
        assert "News" in html
        assert "Python" in html
        assert "HN" in html

    def test_export_roundtrip(self):
        """Test export then parse (roundtrip)."""
        root = Node("folder", "Bookmarks")
        tech = Node("folder", "Technology")
        tech.append(Node("bookmark", "Python.org", url="https://python.org"))
        root.append(tech)
        
        # Export
        html = export_netscape_html(root)
        
        # Parse
        parser = NetscapeBookmarkParser()
        parser.feed(html)
        
        # Verify structure preserved
        assert len(parser.root.children) == 1
        assert parser.root.children[0].title == "Technology"
        assert len(parser.root.children[0].children) == 1
        assert parser.root.children[0].children[0].title == "Python.org"

    def test_export_special_characters(self):
        """Export bookmarks with special characters."""
        root = Node("folder", "Test")
        root.append(Node("bookmark", "Example & Special <chars>", url="https://example.com?q=1&r=2"))
        
        html = export_netscape_html(root)
        
        # Special chars should be escaped
        assert "&amp;" in html
        assert "&lt;" in html or "example" in html.lower()
