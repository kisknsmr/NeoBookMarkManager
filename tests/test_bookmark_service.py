"""
Test BookmarkService bookmark business logic.
"""

import pytest
from core.ModelBookmark import Node
from services.ServiceBookmark import BookmarkService


class TestBookmarkService:
    """Tests for BookmarkService."""

    # ==================== Create ====================
    def test_create_folder(self, bookmark_service):
        """Test creating a new folder."""
        parent = Node("folder", "Root")
        folder = bookmark_service.create_folder(parent, "Tech")
        
        assert folder.type == "folder"
        assert folder.title == "Tech"
        assert folder.parent is parent
        assert folder in parent.children

    def test_create_folder_empty_name(self, bookmark_service):
        """Test creating folder with empty name."""
        parent = Node("folder", "Root")
        folder = bookmark_service.create_folder(parent, "  ")
        
        assert folder.title == "Untitled"

    def test_create_bookmark(self, bookmark_service):
        """Test creating a new bookmark."""
        parent = Node("folder", "Root")
        bookmark = bookmark_service.create_bookmark(parent, "https://example.com", "Example")
        
        assert bookmark.type == "bookmark"
        assert bookmark.title == "Example"
        assert bookmark.url == "https://example.com"
        assert bookmark.parent is parent

    def test_create_bookmark_no_title(self, bookmark_service):
        """Test creating bookmark without title (defaults to URL)."""
        parent = Node("folder", "Root")
        bookmark = bookmark_service.create_bookmark(parent, "https://example.com")
        
        assert bookmark.title == "https://example.com"

    # ==================== Edit ====================
    def test_rename_node(self, bookmark_service):
        """Test renaming a node."""
        node = Node("folder", "Old Name")
        bookmark_service.rename(node, "New Name")
        
        assert node.title == "New Name"

    def test_rename_empty_raises(self, bookmark_service):
        """Test renaming to empty string raises error."""
        node = Node("folder", "Name")
        
        with pytest.raises(ValueError):
            bookmark_service.rename(node, "  ")

    def test_edit_url(self, bookmark_service):
        """Test editing bookmark URL."""
        bookmark = Node("bookmark", "Example", url="https://old.com")
        bookmark_service.edit_url(bookmark, "https://new.com")
        
        assert bookmark.url == "https://new.com"

    def test_edit_url_folder_raises(self, bookmark_service):
        """Test editing folder URL raises error."""
        folder = Node("folder", "Folder")
        
        with pytest.raises(ValueError):
            bookmark_service.edit_url(folder, "https://example.com")

    # ==================== Move & Reorder ====================
    def test_move_to_folder(self, bookmark_service):
        """Test moving bookmark to another folder."""
        root = Node("folder", "Root")
        tech = Node("folder", "Tech")
        news = Node("folder", "News")
        root.append(tech)
        root.append(news)
        
        bookmark = Node("bookmark", "Python", url="https://python.org")
        tech.append(bookmark)
        
        # Move to news
        bookmark_service.move_to_folder(bookmark, news)
        
        assert bookmark.parent is news
        assert bookmark in news.children
        assert bookmark not in tech.children

    def test_move_to_itself_raises(self, bookmark_service):
        """Test moving folder to itself raises error."""
        folder = Node("folder", "Folder")
        
        with pytest.raises(ValueError):
            bookmark_service.move_to_folder(folder, folder)

    def test_move_to_descendant_raises(self, bookmark_service):
        """Test moving folder to its descendant raises error."""
        grandparent = Node("folder", "GrandParent")
        parent = Node("folder", "Parent")
        child = Node("folder", "Child")
        
        grandparent.append(parent)
        parent.append(child)
        
        # Try to move grandparent to child - should raise
        with pytest.raises(ValueError):
            bookmark_service.move_to_folder(grandparent, child)

    def test_move_up(self, bookmark_service):
        """Test moving node up in sibling list."""
        parent = Node("folder", "Parent")
        b1 = Node("bookmark", "B1", url="https://b1.com")
        b2 = Node("bookmark", "B2", url="https://b2.com")
        parent.append(b1)
        parent.append(b2)
        
        bookmark_service.move_up(b2)
        
        assert parent.children[0] is b2
        assert parent.children[1] is b1

    def test_move_up_at_top_raises(self, bookmark_service):
        """Test moving up when already at top raises error."""
        parent = Node("folder", "Parent")
        b1 = Node("bookmark", "B1", url="https://b1.com")
        parent.append(b1)
        
        with pytest.raises(ValueError):
            bookmark_service.move_up(b1)

    # ==================== Delete ====================
    def test_delete_bookmark(self, bookmark_service):
        """Test deleting a bookmark."""
        parent = Node("folder", "Parent")
        bookmark = Node("bookmark", "Example", url="https://example.com")
        parent.append(bookmark)
        
        bookmark_service.delete(bookmark)
        
        assert bookmark not in parent.children
        assert bookmark.parent is None

    def test_delete_root_raises(self, bookmark_service):
        """Test deleting root raises error."""
        root = Node("folder", "Root")
        
        with pytest.raises(ValueError):
            bookmark_service.delete(root)

    # ==================== Organize ====================
    def test_sort_by_title(self, bookmark_service):
        """Test sorting children by title."""
        parent = Node("folder", "Parent")
        parent.append(Node("bookmark", "Zebra", url="https://z.com"))
        parent.append(Node("bookmark", "Apple", url="https://a.com"))
        parent.append(Node("bookmark", "Mango", url="https://m.com"))
        
        bookmark_service.sort_children(parent, key="title")
        
        titles = [child.title for child in parent.children]
        assert titles == ["Apple", "Mango", "Zebra"]

    def test_sort_by_domain(self, bookmark_service):
        """Test sorting children by domain (folders first)."""
        parent = Node("folder", "Parent")
        parent.append(Node("bookmark", "B", url="https://b.example.com/path"))
        parent.append(Node("bookmark", "A", url="https://www.a.example.com/"))
        parent.append(Node("folder", "Z-Folder"))
        parent.append(Node("bookmark", "NoUrl", url=""))

        bookmark_service.sort_children(parent, key="domain")

        # folders first, then by domain
        assert parent.children[0].type == "folder"
        assert parent.children[1].type == "bookmark"
        # www stripped => a.example.com should come before b.example.com
        assert parent.children[1].url.startswith("https://www.a.example.com")
        assert parent.children[2].url.startswith("https://b.example.com")

    def test_delete_duplicates(self, bookmark_service):
        """Test deleting duplicate bookmarks."""
        parent = Node("folder", "Parent")
        parent.append(Node("bookmark", "Python 1", url="https://python.org"))
        parent.append(Node("bookmark", "Python 2", url="https://python.org"))
        parent.append(Node("bookmark", "Unique", url="https://unique.com"))
        
        deleted = bookmark_service.delete_duplicates(parent)
        
        assert deleted == 1
        assert len(parent.children) == 2
        urls = [child.url for child in parent.children]
        assert urls.count("https://python.org") == 1

    def test_remove_duplicates_report(self, bookmark_service):
        """Test duplicate removal returns (count, details) and keeps behavior scope (direct children only)."""
        parent = Node("folder", "Parent")
        parent.append(Node("bookmark", "A", url="https://example.com"))
        parent.append(Node("bookmark", "B", url="https://example.com"))
        parent.append(Node("bookmark", "C", url="https://unique.com"))

        count, details = bookmark_service.remove_duplicates(parent, log_file_path=None)

        assert count == 1
        assert len(details) == 1
        assert "https://example.com" in details[0]

    def test_get_domain_statistics_and_consolidate(self, bookmark_service):
        root = Node("folder", "Root")
        f1 = Node("folder", "F1")
        f2 = Node("folder", "F2")
        root.append(f1)
        root.append(f2)

        b1 = Node("bookmark", "A", url="https://www.example.com/a")
        b2 = Node("bookmark", "B", url="https://example.com/b")
        b3 = Node("bookmark", "C", url="https://other.com/c")
        f1.append(b1)
        f1.append(b3)
        f2.append(b2)

        stats = bookmark_service.get_domain_statistics(root)
        stats_map = dict(stats)
        assert stats_map.get("example.com") == 2
        assert stats_map.get("other.com") == 1

        moved = bookmark_service.consolidate_by_domain(root, "example.com", "Example統合")
        assert moved == 2
        assert root.children[0].type == "folder"
        assert root.children[0].title == "Example統合"
        target = root.children[0]
        assert len([c for c in target.children if c.type == "bookmark"]) == 2
        # 元のフォルダから消えている
        assert b1.parent is target
        assert b2.parent is target

    def test_merge_duplicate_folders(self, bookmark_service):
        """Test merging folders with same name."""
        parent = Node("folder", "Root")
        
        tech1 = Node("folder", "Technology")
        tech1.append(Node("bookmark", "Python", url="https://python.org"))
        parent.append(tech1)
        
        tech2 = Node("folder", "Technology")
        tech2.append(Node("bookmark", "Rust", url="https://rust-lang.org"))
        parent.append(tech2)
        
        assert len(parent.children) == 2
        
        merged = bookmark_service.merge_duplicate_folders(parent)
        
        assert merged == 1
        assert len(parent.children) == 1
        assert len(parent.children[0].children) == 2
