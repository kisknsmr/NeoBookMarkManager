import sys
import os
import pytest

# Ensure the project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.model import Node
from services.search import SearchService
from services.bookmark import BookmarkService


@pytest.fixture
def sample_tree():
    """Create a sample bookmark tree for testing."""
    root = Node("folder", "Bookmarks")
    
    # Tech folder
    tech = Node("folder", "Technology")
    python_site = Node("bookmark", "Python.org", url="https://python.org")
    django_docs = Node("bookmark", "Django Docs", url="https://docs.djangoproject.com")
    tech.append(python_site)
    tech.append(django_docs)
    root.append(tech)
    
    # News folder
    news = Node("folder", "News")
    hn = Node("bookmark", "Hacker News", url="https://news.ycombinator.com")
    tech_news = Node("bookmark", "Tech News", url="https://technewstoday.com")
    news.append(hn)
    news.append(tech_news)
    root.append(news)
    
    # Duplicates folder (for testing deduplication)
    dupes = Node("folder", "Duplicates")
    dup1 = Node("bookmark", "Python 1", url="https://python.org")
    dup2 = Node("bookmark", "Python 2", url="https://python.org")
    dup3 = Node("bookmark", "Django 1", url="https://docs.djangoproject.com")
    dupes.append(dup1)
    dupes.append(dup2)
    dupes.append(dup3)
    root.append(dupes)
    
    return root


@pytest.fixture
def search_service(sample_tree):
    """Create SearchService with sample tree."""
    service = SearchService()
    service.rebuild(sample_tree)
    return service


@pytest.fixture
def bookmark_service():
    """Create BookmarkService instance."""
    return BookmarkService()


@pytest.fixture
def mock_bookmarks_file(tmp_path):
    """Creates a temporary dummy bookmarks HTML file."""
    f = tmp_path / "test_bookmarks.html"
    f.write_text("""<!DOCTYPE NETSCAPE-Bookmark-file-1>
    <HTML>
    <META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
    <TITLE>Bookmarks</TITLE>
    <H1>Bookmarks Menu</H1>
    <DL><p>
        <DT><A HREF="https://example.com" ADD_DATE="1672531200">Example</A>
        <DT><H3 ADD_DATE="1672531200">Folder</H3>
        <DL><p>
            <DT><A HREF="https://sub.example.com">SubItem</A>
        </DL><p>
    </DL><p>
    """, encoding="utf-8")
    return str(f)

@pytest.fixture
def mock_config_ini(tmp_path):
    """Creates a temporary config.ini."""
    f = tmp_path / "config.ini"
    f.write_text("[API]\napi_key=DEFAULT_TEST_KEY\n[Classifier]\npriority_terms=tech,AI\n", encoding="utf-8")
    return str(f)
