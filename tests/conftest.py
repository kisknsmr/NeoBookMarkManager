import sys
import os
import pytest

# Ensure the project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

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
