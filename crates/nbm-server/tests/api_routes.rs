//! Route inventory.
//!
//! The handlers live in one module per area and each contributes its own
//! `Router`, so a dropped `.route(...)` would not break the build — it would
//! quietly 404 in the UI instead. This test names every endpoint the frontend
//! calls and asserts the router still matches it.
//!
//! An unmatched path in axum answers 404 with an *empty* body, and a wrong
//! method answers 405; every handler's own 404 carries a JSON body. That is
//! what distinguishes "route is gone" from "route said not found".

mod support;

use axum::body::Body;
use axum::http::{Method, Request, StatusCode};
use serde_json::json;
use support::Fixture;
use tower::ServiceExt;

/// Every (method, path) pair the frontend uses, with a body where one is
/// required. Paths with an `:id` segment are exercised with a made-up id.
fn endpoints() -> Vec<(Method, &'static str, Option<serde_json::Value>)> {
    let ids = json!({ "bookmark_ids": [] });
    vec![
        (Method::GET, "/health", None),
        (Method::GET, "/bookmarks", None),
        (Method::GET, "/tree", None),
        (Method::GET, "/search", None),
        (Method::GET, "/meta/some-id", None),
        (Method::GET, "/tags/some-id", None),
        (Method::POST, "/tags/update", Some(json!({ "bookmark_id": "x", "tags": [] }))),
        // Edit
        (Method::POST, "/edit/undo", Some(json!({}))),
        (Method::POST, "/edit/redo", Some(json!({}))),
        (Method::GET, "/edit/history", None),
        (
            Method::POST,
            "/edit/bookmark/add",
            Some(json!({ "folder_path": "Work", "title": "t", "url": "https://t.test/" })),
        ),
        (
            Method::POST,
            "/edit/bookmark/bulk-move",
            Some(json!({ "node_ids": [], "target_parent_path": "Work" })),
        ),
        (Method::PATCH, "/edit/bookmark/some-id", Some(json!({ "title": "t" }))),
        (Method::DELETE, "/edit/bookmark/some-id", None),
        (
            Method::POST,
            "/edit/bookmark/some-id/move",
            Some(json!({ "folder_path": "Work" })),
        ),
        (
            Method::POST,
            "/edit/bookmark/some-id/reorder",
            Some(json!({ "new_index": 0 })),
        ),
        (Method::POST, "/edit/bookmark/some-id/move-up", Some(json!({}))),
        (
            Method::POST,
            "/edit/node/some-id/move",
            Some(json!({ "target_parent_path": "Work" })),
        ),
        (
            Method::POST,
            "/edit/node/some-id/reorder",
            Some(json!({ "new_index": 0 })),
        ),
        (
            Method::POST,
            "/edit/folder/add",
            Some(json!({ "parent_path": "", "title": "New" })),
        ),
        (
            Method::PATCH,
            "/edit/folder/rename",
            Some(json!({ "folder_path": "Work", "new_title": "W" })),
        ),
        (Method::DELETE, "/edit/folder?folder_path=Work", None),
        (Method::POST, "/edit/save", Some(json!({}))),
        // Session
        (Method::POST, "/file/open", Some(json!({ "path": "nope.html" }))),
        (Method::GET, "/session/state", None),
        (Method::POST, "/session/resume", Some(json!({ "keep": true }))),
        // Backup
        (Method::GET, "/backup/list", None),
        (Method::POST, "/backup/restore", Some(json!({ "backup_dir": "x" }))),
        (Method::POST, "/backup/undo-latest", Some(json!({}))),
        // Autotag + network (empty batches, so nothing is fetched)
        (Method::POST, "/autotag/local", Some(ids.clone())),
        (Method::POST, "/network/fix-titles", Some(ids.clone())),
        (Method::POST, "/network/fetch-preview", Some(ids.clone())),
        (Method::POST, "/network/link-check", Some(ids.clone())),
        (Method::GET, "/network/proxy-check", None),
        // Config
        (Method::GET, "/config/ai-status", None),
        (Method::POST, "/config/api-key", Some(json!({ "api_key": "k" }))),
        (Method::POST, "/config/ai-tier", Some(json!({ "free_tier": true }))),
        (
            Method::POST,
            "/config/ai-pricing",
            Some(json!({ "input_cost_per_1m": 1.0, "output_cost_per_1m": 1.0 })),
        ),
        (Method::GET, "/config/models", None),
        // Classify
        (Method::POST, "/classify/readiness", Some(ids.clone())),
        (Method::POST, "/classify/estimate", Some(ids.clone())),
        (Method::POST, "/classify/ai", Some(ids.clone())),
        (Method::POST, "/classify/ai-apply", Some(json!({ "moves": [] }))),
        // Organize
        (Method::POST, "/organize/dedupe", Some(json!({ "folder_path": "Work" }))),
        (
            Method::POST,
            "/organize/merge-duplicate-folders",
            Some(json!({ "parent_path": "" })),
        ),
        (Method::GET, "/organize/domain-stats", None),
        (
            Method::POST,
            "/organize/consolidate-by-domain",
            Some(json!({ "domain": "example.com" })),
        ),
        (
            Method::POST,
            "/organize/sort-by-domain",
            Some(json!({ "folder_path": "Work" })),
        ),
    ]
}

#[tokio::test]
async fn every_endpoint_the_frontend_calls_is_routed() {
    // A fully wired app, so no endpoint answers "not configured" for a missing
    // db/backup manager instead of being exercised.
    let app = Fixture::default()
        .with_db()
        .with_backup()
        .with_current_file()
        .with_config("[AI]\nmodel = gemini-2.5-flash-lite\n")
        .build()
        .await;

    for (method, uri, body) in endpoints() {
        let mut builder = Request::builder().method(method.clone()).uri(uri);
        let request_body = match &body {
            Some(v) => {
                builder = builder.header("content-type", "application/json");
                Body::from(serde_json::to_vec(v).unwrap())
            }
            None => Body::empty(),
        };
        let res = app
            .router
            .clone()
            .oneshot(builder.body(request_body).unwrap())
            .await
            .expect("router response");

        let status = res.status();
        assert_ne!(
            status,
            StatusCode::METHOD_NOT_ALLOWED,
            "{method} {uri} is routed, but not for this method"
        );

        let bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
            .await
            .expect("read body");
        assert!(
            !(status == StatusCode::NOT_FOUND && bytes.is_empty()),
            "{method} {uri} is not routed at all (bare 404 from the router)"
        );
    }
}

#[tokio::test]
async fn an_unknown_path_is_a_bare_404() {
    // Guards the assertion the test above relies on.
    let app = support::app().await;
    let res = app
        .router
        .clone()
        .oneshot(
            Request::builder()
                .uri("/definitely/not/an/endpoint")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::NOT_FOUND);
    let bytes = axum::body::to_bytes(res.into_body(), usize::MAX).await.unwrap();
    assert!(bytes.is_empty(), "an unrouted path must have no body");
}

/// The webview talks to this server over HTTP, so its origin has to survive
/// the CORS layer. On Windows that origin is `http://tauri.localhost`, not the
/// `tauri://localhost` used on macOS and Linux — when only the latter was
/// allowed, the preflight came back without `access-control-allow-origin` and
/// every call in the packaged exe failed as an opaque "Failed to fetch".
#[tokio::test]
async fn cors_allows_every_webview_origin() {
    let app = Fixture::default().build().await;

    for origin in [
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "http://localhost:1430",
    ] {
        let req = Request::builder()
            .method(Method::OPTIONS)
            .uri("/file/open")
            .header("origin", origin)
            .header("access-control-request-method", "POST")
            .header("access-control-request-headers", "content-type")
            .body(Body::empty())
            .expect("build preflight");
        let res = app.router.clone().oneshot(req).await.expect("router response");

        assert_eq!(res.status(), StatusCode::OK, "preflight rejected for {origin}");
        let allowed = res
            .headers()
            .get("access-control-allow-origin")
            .unwrap_or_else(|| panic!("no access-control-allow-origin for {origin}"));
        assert_eq!(allowed, origin, "wrong origin echoed back for {origin}");
    }
}
