//! Read-only endpoints: health, listing, search, tree, tags, meta.

mod support;

use axum::http::StatusCode;
use support::{app, Fixture};

#[tokio::test]
async fn health_reports_ok_and_a_version() {
    let app = app().await;
    let (status, body) = app.get("/health").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["status"], "ok");
    assert!(body["version"].as_str().is_some_and(|v| !v.is_empty()));
}

#[tokio::test]
async fn bookmarks_flattens_the_tree_with_folder_paths() {
    let app = app().await;
    let (status, body) = app.get("/bookmarks").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["count"], 5);
    assert_eq!(body["dirty"], false);
    assert_eq!(body["file_path"], serde_json::Value::Null);

    let mut paths: Vec<&str> = body["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|b| b["folder_path"].as_str().unwrap())
        .collect();
    paths.sort_unstable();
    assert_eq!(
        paths,
        ["Personal", "Work", "Work", "Work", "Work/Nested"],
        "nested folders should be reported as slash-joined paths"
    );

    // Every bookmark carries a non-empty id, which is what every edit endpoint
    // is addressed by.
    assert!(body["items"]
        .as_array()
        .unwrap()
        .iter()
        .all(|b| !b["bookmark_id"].as_str().unwrap().is_empty()));
}

#[tokio::test]
async fn bookmarks_reports_current_file_when_one_is_open() {
    let app = Fixture::default().with_current_file().build().await;
    let (_, body) = app.get("/bookmarks").await;
    assert!(body["file_path"]
        .as_str()
        .is_some_and(|p| p.ends_with("bookmarks.html")));
}

#[tokio::test]
async fn search_requires_every_token_to_match() {
    let app = app().await;

    let (status, body) = app.get("/search?q=github").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["count"], 3, "three bookmarks live on github.com");

    // Tokens are ANDed across title + url + folder path.
    let (_, body) = app.get("/search?q=github%20work").await;
    assert_eq!(body["count"], 3);
    let (_, body) = app.get("/search?q=github%20personal").await;
    assert_eq!(body["count"], 0);

    // Case-insensitive, and an empty query returns everything.
    let (_, body) = app.get("/search?q=GITHUB").await;
    assert_eq!(body["count"], 3);
    let (_, body) = app.get("/search").await;
    assert_eq!(body["count"], 5);
}

#[tokio::test]
async fn search_honours_limit() {
    let app = app().await;
    let (_, body) = app.get("/search?q=&limit=2").await;
    assert_eq!(body["count"], 2);
    assert_eq!(body["items"].as_array().unwrap().len(), 2);
}

#[tokio::test]
async fn tree_returns_the_whole_node_hierarchy() {
    let app = app().await;
    let (status, body) = app.get("/tree").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["type"], "folder");
    let children = body["children"].as_array().unwrap();
    assert_eq!(children.len(), 2);
    assert_eq!(children[0]["title"], "Work");
    // Work holds A, B, Dup and the Nested folder.
    assert_eq!(children[0]["children"].as_array().unwrap().len(), 4);
}

#[tokio::test]
async fn tags_are_empty_without_a_db_and_unavailable_for_writes() {
    let app = app().await;
    let id = app.bookmark_id("A").await;

    let (status, body) = app.get(&format!("/tags/{id}")).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["bookmark_id"], id);
    assert_eq!(body["tags"].as_array().unwrap().len(), 0);

    let (status, _) = app
        .post(
            "/tags/update",
            serde_json::json!({ "bookmark_id": id, "tags": ["rust"] }),
        )
        .await;
    assert_eq!(
        status,
        StatusCode::SERVICE_UNAVAILABLE,
        "writing tags without a db must fail loudly, not silently succeed"
    );
}

#[tokio::test]
async fn tags_round_trip_through_the_db() {
    let app = Fixture::default().with_db().build().await;
    let id = app.bookmark_id("A").await;

    let (status, body) = app
        .post(
            "/tags/update",
            serde_json::json!({
                "bookmark_id": id,
                "tags": ["rust", "cli"],
                "source": "manual",
                "confidence": 0.5,
            }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], true);

    let (_, body) = app.get(&format!("/tags/{id}")).await;
    let mut tags: Vec<&str> = body["tags"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t["name"].as_str().unwrap())
        .collect();
    tags.sort_unstable();
    assert_eq!(tags, ["cli", "rust"]);
}

#[tokio::test]
async fn meta_is_null_without_a_db() {
    let app = app().await;
    let id = app.bookmark_id("A").await;
    let (status, body) = app.get(&format!("/meta/{id}")).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["fetched_title"], serde_json::Value::Null);
}
