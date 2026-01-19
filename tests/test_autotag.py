from pathlib import Path


def test_autotag_tier1_saves_rule_tags(tmp_path):
    from core.DatabaseManager import DatabaseManager
    from core.ModelBookmark import Node
    from services.ServiceAutoTag import AutoTagService
    from services.ServiceTags import TagService

    project_root = Path(tmp_path)
    (project_root / "bookmarks.html").write_text("<!DOCTYPE html><html></html>", encoding="utf-8")
    (project_root / "config.ini").write_text("", encoding="utf-8")

    dbm = DatabaseManager(project_root=project_root)
    dbm.ensure_compatible()
    dbm.migrate_if_needed(bookmarks_html=project_root / "bookmarks.html", config_ini=project_root / "config.ini", keep_generations=5)

    n = Node("bookmark", title="Repo", url="https://github.com/example/repo", bookmark_id="bid1")
    svc = AutoTagService(project_root=project_root)
    r = svc.auto_tag(nodes=[n], allow_network=False, proxy_info=None)
    assert r.tagged == 1
    assert r.save_failed == 0
    assert r.missing_id == 0

    tags = TagService(project_root=project_root).get_tags("bid1")
    assert "Dev" in tags


def test_autotag_tier2_tokenize_and_cleanup(tmp_path, monkeypatch):
    from core.DatabaseManager import DatabaseManager
    from core.ModelBookmark import Node
    from services.ServiceAutoTag import AutoTagService
    from services.ServiceTags import TagService

    project_root = Path(tmp_path)
    (project_root / "bookmarks.html").write_text("<!DOCTYPE html><html></html>", encoding="utf-8")
    (project_root / "config.ini").write_text("", encoding="utf-8")

    dbm = DatabaseManager(project_root=project_root)
    dbm.ensure_compatible()
    dbm.migrate_if_needed(bookmarks_html=project_root / "bookmarks.html", config_ini=project_root / "config.ini", keep_generations=5)

    # fake HTTP response (no network)
    calls = {}

    class _Resp:
        status_code = 200
        text = """
        <html><head>
          <title>AI・機械学習 入門｜公式サイト</title>
          <meta name="keywords" content="Python, AI・機械学習, 公式, まとめ"/>
          <meta property="article:tag" content="データサイエンス"/>
        </head><body></body></html>
        """

    def fake_get(url, timeout=None, headers=None, proxies=None, auth=None):
        calls["timeout"] = timeout
        calls["ua"] = (headers or {}).get("User-Agent")
        return _Resp()

    import services.ServiceAutoTag as mod
    monkeypatch.setattr(mod.requests, "get", fake_get)

    n = Node("bookmark", title="X", url="https://example.com/article", bookmark_id="bid2")
    svc = AutoTagService(project_root=project_root)
    r = svc.auto_tag(nodes=[n], allow_network=True, proxy_info=None)
    assert r.tagged == 1
    assert calls["timeout"] == 3
    assert calls["ua"] == "NeoBookmarkManager/1.0"

    tags = TagService(project_root=project_root).get_tags("bid2")
    # punctuation removed, stopwords removed, Japanese tokens kept
    assert "Python" in tags
    assert "AI" in tags
    assert "機械学習" in tags
    assert "データサイエンス" in tags
    assert "公式" not in tags

