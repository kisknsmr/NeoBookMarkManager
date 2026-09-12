//! Mutating endpoints: bookmark/folder/node edits, undo/redo, save, open,
//! session and backup.

mod support;

use axum::http::StatusCode;
use serde_json::json;
use support::{app, Fixture};

#[tokio::test]
async fn adding_a_bookmark_shows_up_in_the_listing_and_marks_dirty() {
    let app = app().await;
    let (status, body) = app
        .post(
            "/edit/bookmark/add",
            json!({ "folder_path": "Personal", "title": "New", "url": "https://new.test/" }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    let new_id = body["bookmark_id"].as_str().unwrap().to_string();
    assert!(!new_id.is_empty());

    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["count"], 6);
    assert_eq!(list["dirty"], true, "an edit must mark the tree dirty");
    assert_eq!(app.folder_of("New").await.as_deref(), Some("Personal"));

    // The edit is undoable.
    let (_, hist) = app.get("/edit/history").await;
    assert_eq!(hist["undo_count"], 1);
}

#[tokio::test]
async fn adding_a_bookmark_to_an_unknown_folder_is_404() {
    let app = app().await;
    let (status, body) = app
        .post(
            "/edit/bookmark/add",
            json!({ "folder_path": "Nope", "title": "x", "url": "https://x.test/" }),
        )
        .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert!(body["error"].as_str().is_some_and(|e| !e.is_empty()));
}

#[tokio::test]
async fn patching_a_bookmark_updates_the_supplied_fields_only() {
    let app = app().await;
    let id = app.bookmark_id("A").await;

    let (status, _) = app
        .patch(
            &format!("/edit/bookmark/{id}"),
            json!({ "title": "A renamed", "description": "notes" }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);

    let (_, list) = app.get("/bookmarks").await;
    let item = list["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|b| b["bookmark_id"] == id.as_str())
        .unwrap();
    assert_eq!(item["title"], "A renamed");
    assert_eq!(item["description"], "notes");
    assert_eq!(item["url"], "https://github.com/a", "url was not in the patch");
}

#[tokio::test]
async fn patching_an_unknown_bookmark_is_404() {
    let app = app().await;
    let (status, _) = app
        .patch("/edit/bookmark/does-not-exist", json!({ "title": "x" }))
        .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn deleting_a_bookmark_removes_it() {
    let app = app().await;
    let id = app.bookmark_id("B").await;
    let (status, body) = app.delete(&format!("/edit/bookmark/{id}")).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], true);

    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["count"], 4);
    assert_eq!(app.folder_of("B").await, None);
}

#[tokio::test]
async fn bulk_delete_removes_every_id_under_one_undo() {
    let app = app().await;
    let a = app.bookmark_id("A").await;
    let c = app.bookmark_id("C").await;

    // A stale id in the batch must not abort the rest — the link-check modal
    // sends whatever was on screen when the sweep finished.
    let (status, body) = app
        .post(
            "/edit/bookmark/bulk-delete",
            json!({ "bookmark_ids": [a, "gone", c] }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["deleted"], 2);
    assert_eq!(body["missing"], json!(["gone"]));

    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["count"], 3);
    assert_eq!(app.folder_of("A").await, None);
    assert_eq!(app.folder_of("C").await, None);

    // One snapshot for the whole batch: a single undo brings both back.
    app.post("/edit/undo", json!({})).await;
    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["count"], 5, "one undo restores the whole batch");
}

#[tokio::test]
async fn moving_a_bookmark_changes_its_folder() {
    let app = app().await;
    let id = app.bookmark_id("A").await;
    let (status, _) = app
        .post(
            &format!("/edit/bookmark/{id}/move"),
            json!({ "folder_path": "Work/Nested" }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(app.folder_of("A").await.as_deref(), Some("Work/Nested"));

    // Moving into a folder that does not exist is a 404, not a silent no-op.
    let (status, _) = app
        .post(
            &format!("/edit/bookmark/{id}/move"),
            json!({ "folder_path": "Ghost" }),
        )
        .await;
    assert_eq!(status, StatusCode::NOT_FOUND);

    // ...and the bookmark must survive the rejected move. It used to be
    // detached before the destination was resolved, so a 404 here deleted it.
    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["count"], 5);
    assert_eq!(app.folder_of("A").await.as_deref(), Some("Work/Nested"));
}

#[tokio::test]
async fn a_rejected_node_move_leaves_the_node_in_place() {
    let app = app().await;
    let nested = app.folder_node_id("Work/Nested").await;

    let (status, _) = app
        .post(
            &format!("/edit/node/{nested}/move"),
            json!({ "target_parent_path": "Ghost" }),
        )
        .await;
    assert_eq!(status, StatusCode::NOT_FOUND);

    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["count"], 5, "the whole folder must not be dropped");
    assert_eq!(app.folder_of("C").await.as_deref(), Some("Work/Nested"));
}

#[tokio::test]
async fn bulk_move_to_a_missing_folder_keeps_every_node() {
    let app = app().await;
    let a = app.bookmark_id("A").await;
    let b = app.bookmark_id("B").await;

    // bulk-move ignores per-node errors, so a bad destination has to be
    // harmless rather than quietly destructive.
    let (status, _) = app
        .post(
            "/edit/bookmark/bulk-move",
            json!({ "node_ids": [a, b], "target_parent_path": "Ghost" }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);

    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["count"], 5);
    assert_eq!(app.titles_in("Work").await, ["A", "B", "Dup"]);
}

#[tokio::test]
async fn reordering_a_bookmark_changes_sibling_order() {
    let app = app().await;
    assert_eq!(app.titles_in("Work").await, ["A", "B", "Dup"]);

    let id = app.bookmark_id("Dup").await;
    let (status, _) = app
        .post(&format!("/edit/bookmark/{id}/reorder"), json!({ "new_index": 0 }))
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(app.titles_in("Work").await, ["Dup", "A", "B"]);
}

#[tokio::test]
async fn move_up_swaps_with_the_previous_sibling_and_refuses_at_the_top() {
    let app = app().await;
    let b = app.bookmark_id("B").await;
    let (status, _) = app.post(&format!("/edit/bookmark/{b}/move-up"), json!({})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(app.titles_in("Work").await, ["B", "A", "Dup"]);

    // B is now first — moving it up again is a bad request.
    let (status, _) = app.post(&format!("/edit/bookmark/{b}/move-up"), json!({})).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn folders_can_be_added_renamed_and_deleted() {
    let app = app().await;

    let (status, body) = app
        .post("/edit/folder/add", json!({ "parent_path": "Personal", "title": "Sub" }))
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["folder_path"], "Personal/Sub");

    let (status, body) = app
        .patch(
            "/edit/folder/rename",
            json!({ "folder_path": "Personal/Sub", "new_title": "Renamed" }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["folder_path"], "Personal/Renamed");

    let (status, _) = app.delete("/edit/folder?folder_path=Personal/Renamed").await;
    assert_eq!(status, StatusCode::OK);

    // Deleting a folder takes its bookmarks with it.
    let (status, _) = app.delete("/edit/folder?folder_path=Work/Nested").await;
    assert_eq!(status, StatusCode::OK);
    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["count"], 4);

    let (status, _) = app.delete("/edit/folder?folder_path=Ghost").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn nodes_can_be_moved_and_reordered_by_node_id() {
    let app = app().await;
    let nested = app.folder_node_id("Work/Nested").await;

    let (status, _) = app
        .post(
            &format!("/edit/node/{nested}/move"),
            json!({ "target_parent_path": "Personal" }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(app.folder_of("C").await.as_deref(), Some("Personal/Nested"));

    let (status, _) = app
        .post(&format!("/edit/node/{nested}/reorder"), json!({ "new_index": 0 }))
        .await;
    assert_eq!(status, StatusCode::OK);
    // Personal now holds [Nested, D]; the listing walks folders first.
    assert_eq!(app.folder_of("C").await.as_deref(), Some("Personal/Nested"));
}

#[tokio::test]
async fn moving_a_folder_into_itself_is_rejected() {
    let app = app().await;
    let work = app.folder_node_id("Work").await;
    let (status, body) = app
        .post(
            &format!("/edit/node/{work}/move"),
            json!({ "target_parent_path": "Work/Nested" }),
        )
        .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert!(body["error"].as_str().unwrap().contains("descendant"));
}

#[tokio::test]
async fn bulk_move_relocates_every_listed_node() {
    let app = app().await;
    let a = app.bookmark_id("A").await;
    let b = app.bookmark_id("B").await;

    let (status, _) = app
        .post(
            "/edit/bookmark/bulk-move",
            json!({ "node_ids": [a, b], "target_parent_path": "Personal" }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(app.folder_of("A").await.as_deref(), Some("Personal"));
    assert_eq!(app.folder_of("B").await.as_deref(), Some("Personal"));
    assert_eq!(app.titles_in("Work").await, ["Dup"]);
}

#[tokio::test]
async fn undo_restores_the_previous_tree_and_redo_reapplies_it() {
    let app = app().await;
    let id = app.bookmark_id("A").await;
    app.delete(&format!("/edit/bookmark/{id}")).await;
    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["count"], 4);

    let (status, body) = app.post("/edit/undo", json!({})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["undo_count"], 0);
    assert_eq!(body["redo_count"], 1);
    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["count"], 5, "undo brings the deleted bookmark back");

    let (status, body) = app.post("/edit/redo", json!({})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["undo_count"], 1);
    assert_eq!(body["redo_count"], 0);
    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["count"], 4, "redo re-applies the delete");
}

#[tokio::test]
async fn undo_and_redo_on_an_empty_stack_are_conflicts() {
    let app = app().await;
    let (status, _) = app.post("/edit/undo", json!({})).await;
    assert_eq!(status, StatusCode::CONFLICT);
    let (status, _) = app.post("/edit/redo", json!({})).await;
    assert_eq!(status, StatusCode::CONFLICT);

    let (status, body) = app.get("/edit/history").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["undo_count"], 0);
    assert_eq!(body["redo_count"], 0);
}

#[tokio::test]
async fn a_rejected_edit_leaves_no_history_entry_and_no_dirty_flag() {
    let app = app().await;

    // Four different rejections, none of which changed anything.
    let (status, _) = app
        .post(
            "/edit/bookmark/add",
            json!({ "folder_path": "Ghost", "title": "x", "url": "https://x.test/" }),
        )
        .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, _) = app
        .patch("/edit/bookmark/nope", json!({ "title": "x" }))
        .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, _) = app.delete("/edit/folder?folder_path=Ghost").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let (status, _) = app
        .post("/edit/folder/add", json!({ "parent_path": "", "title": "  " }))
        .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);

    let (_, hist) = app.get("/edit/history").await;
    assert_eq!(
        hist["undo_count"], 0,
        "a failed edit must not push an undo entry; undo would otherwise be a no-op step"
    );
    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(
        list["dirty"], false,
        "nothing changed, so the file is not dirty"
    );
    assert_eq!(list["count"], 5);
}

#[tokio::test]
async fn undo_after_a_rejected_edit_still_reverts_the_last_real_edit() {
    let app = app().await;
    let id = app.bookmark_id("A").await;

    // One real edit, then a rejected one.
    app.patch(&format!("/edit/bookmark/{id}"), json!({ "title": "renamed" }))
        .await;
    app.post(
        "/edit/bookmark/add",
        json!({ "folder_path": "Ghost", "title": "x", "url": "https://x.test/" }),
    )
    .await;

    // A single undo must reach past the failure to the rename.
    let (status, body) = app.post("/edit/undo", json!({})).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["undo_count"], 0);
    assert_eq!(app.folder_of("A").await.as_deref(), Some("Work"));
    assert_eq!(app.folder_of("renamed").await, None);
}

#[tokio::test]
async fn a_new_edit_clears_the_redo_stack() {
    let app = app().await;
    let id = app.bookmark_id("A").await;
    app.delete(&format!("/edit/bookmark/{id}")).await;
    app.post("/edit/undo", json!({})).await;
    let (_, hist) = app.get("/edit/history").await;
    assert_eq!(hist["redo_count"], 1);

    app.post(
        "/edit/bookmark/add",
        json!({ "folder_path": "Work", "title": "Z", "url": "https://z.test/" }),
    )
    .await;
    let (_, hist) = app.get("/edit/history").await;
    assert_eq!(hist["redo_count"], 0, "a fresh edit invalidates the redo branch");
}

#[tokio::test]
async fn save_writes_the_file_clears_dirty_and_round_trips() {
    let app = app().await;
    let target = app.dir.path().join("saved.html");

    app.post(
        "/edit/bookmark/add",
        json!({ "folder_path": "Work", "title": "Saved", "url": "https://saved.test/" }),
    )
    .await;
    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["dirty"], true);

    let (status, body) = app
        .post("/edit/save", json!({ "file_path": target.display().to_string() }))
        .await;
    assert_eq!(status, StatusCode::OK);
    assert!(body["saved_to"].as_str().unwrap().ends_with("saved.html"));
    assert!(target.exists());

    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["dirty"], false, "a successful save is no longer dirty");

    // The written file parses back to the same bookmark set.
    let reloaded = nbm_core::storage::load_bookmarks(&target).expect("reload");
    assert_eq!(reloaded.root.count_bookmarks(), 6);
    assert!(reloaded
        .root
        .walk()
        .any(|n| n.title == "Saved" && n.url == "https://saved.test/"));
}

#[tokio::test]
async fn save_without_a_target_or_current_file_is_a_bad_request() {
    let app = app().await;
    let (status, body) = app.post("/edit/save", json!({})).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert!(body["error"].as_str().unwrap().contains("no file_path"));
}

#[tokio::test]
async fn save_falls_back_to_the_current_file() {
    let app = Fixture::default().with_current_file().build().await;
    let (status, body) = app.post("/edit/save", json!({})).await;
    assert_eq!(status, StatusCode::OK);
    assert!(body["saved_to"].as_str().unwrap().ends_with("bookmarks.html"));
}

#[tokio::test]
async fn opening_a_missing_file_is_404() {
    let app = app().await;
    let (status, body) = app
        .post("/file/open", json!({ "path": "no/such/file.html" }))
        .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert!(body["error"].as_str().unwrap().contains("file not found"));
}

#[tokio::test]
async fn opening_a_file_replaces_the_tree_and_clears_dirty() {
    let app = app().await;

    // A one-bookmark file to open.
    let other = app.dir.path().join("other.html");
    let mut root = nbm_core::Node::new_root();
    let mut folder = nbm_core::Node::new_folder("Only");
    folder
        .children
        .push(nbm_core::Node::new_bookmark("Solo", "https://solo.test/"));
    root.children.push(folder);
    nbm_core::storage::save_bookmarks(&other, &root, None).expect("write other.html");

    let id = app.bookmark_id("A").await;
    app.delete(&format!("/edit/bookmark/{id}")).await;

    let (status, body) = app
        .post("/file/open", json!({ "path": other.display().to_string() }))
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["count"], 1);
    assert_eq!(body["resume_available"], false, "no db configured");

    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["count"], 1);
    assert_eq!(list["dirty"], false);
    assert_eq!(app.folder_of("Solo").await.as_deref(), Some("Only"));
}

#[tokio::test]
async fn session_state_reports_the_open_file_and_resume_is_resolvable() {
    let app = Fixture::default().with_current_file().build().await;

    let (status, body) = app.get("/session/state").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["resume_available"], false);
    assert!(body["file"].as_str().is_some_and(|f| f.ends_with("bookmarks.html")));

    let (status, body) = app.post("/session/resume", json!({ "keep": true })).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["kept"], true);

    let (_, body) = app.get("/session/state").await;
    assert_eq!(
        body["resume_available"], false,
        "the prompt is resolved once answered"
    );
}

#[tokio::test]
async fn backup_endpoints_report_unavailable_without_a_manager() {
    let app = app().await;
    let (status, body) = app.get("/backup/list").await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert!(body["error"].as_str().unwrap().contains("backup mgr"));

    let (status, _) = app
        .post("/backup/restore", json!({ "backup_dir": "whatever" }))
        .await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);

    let (status, _) = app.post("/backup/undo-latest", json!({})).await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
}

#[tokio::test]
async fn backup_list_is_empty_before_anything_is_backed_up() {
    let app = Fixture::default().with_backup().build().await;
    let (status, body) = app.get("/backup/list").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["backups"].as_array().unwrap().len(), 0);

    // Nothing to roll back to yet.
    let (status, body) = app.post("/backup/undo-latest", json!({})).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert!(body["error"].as_str().unwrap().contains("no backups"));
}
