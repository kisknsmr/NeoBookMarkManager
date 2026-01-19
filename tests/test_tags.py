from pathlib import Path


def test_bookmark_id_roundtrip_parser_exporter(tmp_path):
    from core.ModelBookmark import Node, export_netscape_html, NetscapeBookmarkParser
    from services.ServiceBookmark import BookmarkService

    root = Node("folder", "Bookmarks")
    bm = Node("bookmark", title="Example", url="https://example.com")
    root.append(bm)

    svc = BookmarkService()
    assert svc.ensure_bookmark_ids(root) == 1
    assert bm.bookmark_id

    html = export_netscape_html(root)
    assert "BOOKMARK_ID" in html

    p = NetscapeBookmarkParser()
    p.feed(html)
    parsed_root = p.root
    parsed_bm = next(ch for ch in parsed_root.children if ch.type == "bookmark")
    assert parsed_bm.bookmark_id == bm.bookmark_id


def test_tag_service_set_get(tmp_path):
    from core.DatabaseManager import DatabaseManager
    from services.ServiceTags import TagService

    project_root = Path(tmp_path)
    # required targets for migration backup
    bookmarks_html = project_root / "bookmarks.html"
    config_ini = project_root / "config.ini"
    bookmarks_html.write_text("<!DOCTYPE html><html></html>", encoding="utf-8")
    config_ini.write_text("", encoding="utf-8")

    dbm = DatabaseManager(project_root=project_root)
    dbm.ensure_compatible()
    dbm.migrate_if_needed(bookmarks_html=bookmarks_html, config_ini=config_ini, keep_generations=5)

    tags = TagService(project_root=project_root)
    bid = "abc123"
    tags.set_tags(bid, ["Python", " python ", "AI"])
    assert tags.get_tags(bid) == ["AI", "Python"]

    details = tags.get_tag_details(bid)
    # manual source
    assert any(d.name == "Python" and d.source == "manual" for d in details)