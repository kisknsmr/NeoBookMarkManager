import io
import html
from html.parser import HTMLParser

# Netscape Bookmark HTML Format
BOOKMARK_HTML_HEADER = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
"""
BOOKMARK_HTML_FOOTER = """</DL><p>
"""


class Node:
    # NOTE: `qt_pixmap_cache` is used by the GUI layer to cache decoded favicons per node.
    # It intentionally lives here to allow "store QPixmap on Node" without __dict__ (Node uses __slots__).
    __slots__ = (
        "type",
        "title",
        "url",
        "add_date",
        "last_modified",
        "icon",
        "description",
        "bookmark_id",
        "children",
        "parent",
        "qt_pixmap_cache",
    )

    def __init__(
        self,
        type_,
        title="",
        url="",
        add_date="",
        last_modified="",
        icon="",
        description="",
        bookmark_id="",
    ):
        self.type = type_
        self.title = title
        self.url = url
        self.add_date = add_date
        self.last_modified = last_modified
        self.icon = icon  # ファビコンURLまたはbase64データ
        self.description = description
        self.bookmark_id = bookmark_id or ""
        self.children = []
        self.parent = None
        self.qt_pixmap_cache = {}

    def append(self, child):
        child.parent = self
        self.children.append(child)

    def remove_child(self, child) -> bool:
        """Remove child safely. Returns True if removed, False if not found."""
        if child in self.children:
            self.children.remove(child)
            if child.parent is self:
                child.parent = None
            return True
        return False

    def insert_child(self, index: int, child):
        """Insert child at index. Clamps index to valid range."""
        if child.parent is not self and child in (getattr(child.parent, 'children', []) or []):
            child.parent.remove_child(child)
        
        child.parent = self
        if index < 0 or index > len(self.children):
            self.children.append(child)
        else:
            self.children.insert(index, child)

    def move_child(self, child, index: int) -> None:
        """Move child to new index within same parent."""
        if child.parent is not self:
            raise ValueError("Child must be in this node's children")
        
        if child in self.children:
            self.children.remove(child)
            if index < 0 or index > len(self.children):
                self.children.append(child)
            else:
                self.children.insert(index, child)

    def __repr__(self):
        return f"Node(type='{self.type}', title='{self.title}')"


class NetscapeBookmarkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("folder", "Bookmarks")
        self.stack = [self.root]
        self._pending_link = None
        self._pending_folder = None
        self._capture_text_for = None
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        tag = tag.lower()
        if tag == "h3":
            self._pending_folder = Node("folder", title="", add_date=attr.get("add_date", ""),
                                        last_modified=attr.get("last_modified", ""), icon="")
            self._capture_text_for = "folder";
            self._buffer = []
        elif tag == "a":
            # ICON属性を読み込む（data:image形式またはURL）
            icon_data = attr.get("icon", "")
            bookmark_id = attr.get("bookmark_id", "") or attr.get("data-bookmark-id", "") or ""
            self._pending_link = Node("bookmark", title="", url=attr.get("href", ""), 
                                     add_date=attr.get("add_date", ""),
                                     last_modified=attr.get("last_modified", ""), icon=icon_data, bookmark_id=bookmark_id)
            self._capture_text_for = "link";
            self._buffer = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("h3", "a"):
            text = "".join(self._buffer).strip()
            self._buffer = []
            if self._capture_text_for == "folder" and self._pending_folder:
                self._pending_folder.title = text or "Untitled"
                self.stack[-1].append(self._pending_folder)
                self.stack.append(self._pending_folder)
                self._pending_folder = None
            elif self._capture_text_for == "link" and self._pending_link:
                self._pending_link.title = text
                self.stack[-1].append(self._pending_link)
                self._pending_link = None
            self._capture_text_for = None
        elif tag == "dl":
            if len(self.stack) > 1: self.stack.pop()

    def handle_data(self, data):
        if self._capture_text_for in ("folder", "link"): self._buffer.append(data)


def export_netscape_html(root: Node) -> str:
    out = io.StringIO()
    out.write(BOOKMARK_HTML_HEADER)

    def esc(s: str) -> str:
        return html.escape(s or "", quote=True)

    def write_folder(node: Node, indent: int = 1) -> None:
        ind = "    " * indent
        out.write(
            f'{ind}<DT><H3 ADD_DATE="{esc(node.add_date)}" LAST_MODIFIED="{esc(node.last_modified)}">{esc(node.title)}</H3>\n')
        out.write(f"{ind}<DL><p>\n")
        for ch in node.children:
            if ch.type == "folder":
                write_folder(ch, indent + 1)
            else:
                icon_attr = f' ICON="{esc(ch.icon)}"' if ch.icon else ""
                bid_attr = f' BOOKMARK_ID="{esc(getattr(ch, "bookmark_id", "") or "")}"' if getattr(ch, "bookmark_id", "") else ""
                out.write(
                    f'{ind}    <DT><A HREF="{esc(ch.url)}" ADD_DATE="{esc(ch.add_date)}" LAST_MODIFIED="{esc(ch.last_modified)}"{icon_attr}{bid_attr}>{esc(ch.title)}</A>\n')
        out.write(f"{ind}</DL><p>\n")

    for ch in root.children:
        if ch.type == "folder":
            write_folder(ch, 1)
        else:
            icon_attr = f' ICON="{esc(ch.icon)}"' if ch.icon else ""
            bid_attr = f' BOOKMARK_ID="{esc(getattr(ch, "bookmark_id", "") or "")}"' if getattr(ch, "bookmark_id", "") else ""
            out.write(
                f'    <DT><A HREF="{esc(ch.url)}" ADD_DATE="{esc(ch.add_date)}" LAST_MODIFIED="{esc(ch.last_modified)}"{icon_attr}{bid_attr}>{esc(ch.title)}</A>\n')
    out.write(BOOKMARK_HTML_FOOTER)
    return out.getvalue()
