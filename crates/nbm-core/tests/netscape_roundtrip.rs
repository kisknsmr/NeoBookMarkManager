use nbm_core::netscape;

const SAMPLE_HTML: &str = r#"<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="1601981276" LAST_MODIFIED="1768030434">ブックマーク バー</H3>
    <DL><p>
        <DT><A HREF="https://example.com/" ADD_DATE="1721438824" LAST_MODIFIED="" BOOKMARK_ID="abc">Example</A>
        <DT><H3 ADD_DATE="1602032015" LAST_MODIFIED="">Subfolder</H3>
        <DL><p>
            <DT><A HREF="https://nested.test/" ADD_DATE="1602032016" LAST_MODIFIED="">Nested</A>
        </DL><p>
    </DL><p>
    <DT><A HREF="https://root-level.test/" ADD_DATE="1602032020" LAST_MODIFIED="">Root level</A>
</DL><p>
"#;

#[test]
fn parse_and_count() {
    let root = netscape::parse(SAMPLE_HTML).unwrap();
    assert_eq!(root.children.len(), 2, "root should have folder + bookmark");
    let bar = &root.children[0];
    assert!(bar.is_folder());
    assert_eq!(bar.title, "ブックマーク バー");
    assert_eq!(bar.children.len(), 2);
    let sub = &bar.children[1];
    assert!(sub.is_folder());
    assert_eq!(sub.title, "Subfolder");
    assert_eq!(sub.children.len(), 1);
    assert_eq!(sub.children[0].url, "https://nested.test/");
    assert_eq!(root.count_bookmarks(), 3);
}

#[test]
fn roundtrip_preserves_shape() {
    let root1 = netscape::parse(SAMPLE_HTML).unwrap();
    let html2 = netscape::serialize(&root1);
    let root2 = netscape::parse(&html2).unwrap();
    assert_eq!(root1.count_bookmarks(), root2.count_bookmarks());
    assert_eq!(root1.children.len(), root2.children.len());
    assert_eq!(root1.children[0].title, root2.children[0].title);
}

#[test]
fn real_sample_loads() {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../samples/bookmarks_2026_01_10.html");
    let html = std::fs::read_to_string(&path).expect("sample exists");
    let root = netscape::parse(&html).unwrap();
    assert!(root.count_bookmarks() > 0, "sample should contain bookmarks");
}
