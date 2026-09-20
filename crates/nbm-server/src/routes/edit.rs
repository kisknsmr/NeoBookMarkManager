//! Every endpoint that mutates the tree, plus save-to-disk.
//!
//! All the tree mutations go through [`AppState::edit`], which owns the undo
//! snapshot, the dirty flag and the write lock. That leaves each handler as
//! just its own request shape plus the one `tree::` call it is about.


use axum::extract::{Path, Query, State};
use axum::routing::{delete, get, patch, post};
use axum::{Json, Router};
use camino::Utf8PathBuf;
use nbm_core::storage::save_bookmarks;
use nbm_core::tree;
use serde::{Deserialize, Serialize};

use crate::error::{ApiError, ApiResult};
use crate::routes::OkResponse;
use crate::state::AppState;

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/edit/undo", post(edit_undo))
        .route("/edit/redo", post(edit_redo))
        .route("/edit/history", get(edit_history))
        .route("/edit/bookmark/add", post(edit_bookmark_add))
        .route("/edit/bookmark/bulk-move", post(edit_bookmark_bulk_move))
        .route("/edit/bookmark/bulk-delete", post(edit_bookmark_bulk_delete))
        .route(
            "/edit/bookmark/:id",
            patch(edit_bookmark_patch).delete(edit_bookmark_delete),
        )
        .route("/edit/bookmark/:id/move", post(edit_bookmark_move))
        .route("/edit/bookmark/:id/reorder", post(edit_bookmark_reorder))
        .route("/edit/bookmark/:id/move-up", post(edit_bookmark_move_up))
        .route("/edit/node/:id/move", post(edit_node_move))
        .route("/edit/node/:id/reorder", post(edit_node_reorder))
        .route("/edit/folder/add", post(edit_folder_add))
        .route("/edit/folder/rename", patch(edit_folder_rename))
        .route("/edit/folder", delete(edit_folder_delete))
        .route("/edit/save", post(edit_save))
}

// --- Undo / redo -----------------------------------------------------------

#[derive(Serialize)]
struct UndoRedoResp {
    ok: bool,
    undo_count: usize,
    redo_count: usize,
}

impl UndoRedoResp {
    fn new((undo_count, redo_count): (usize, usize)) -> Json<Self> {
        Json(Self { ok: true, undo_count, redo_count })
    }
}

async fn edit_undo(State(state): State<AppState>) -> ApiResult<UndoRedoResp> {
    let counts = state
        .undo()
        .await
        .ok_or_else(|| ApiError::conflict("undo stack is empty"))?;
    Ok(UndoRedoResp::new(counts))
}

async fn edit_redo(State(state): State<AppState>) -> ApiResult<UndoRedoResp> {
    let counts = state
        .redo()
        .await
        .ok_or_else(|| ApiError::conflict("redo stack is empty"))?;
    Ok(UndoRedoResp::new(counts))
}

async fn edit_history(State(state): State<AppState>) -> Json<UndoRedoResp> {
    UndoRedoResp::new(state.history().await)
}

// --- Bookmarks -------------------------------------------------------------

#[derive(Deserialize)]
struct AddBookmarkBody {
    folder_path: String,
    title: String,
    url: String,
}

#[derive(Serialize)]
struct AddBookmarkResp {
    bookmark_id: String,
}

async fn edit_bookmark_add(
    State(state): State<AppState>,
    Json(body): Json<AddBookmarkBody>,
) -> ApiResult<AddBookmarkResp> {
    let bookmark_id = state
        .edit(|root| tree::add_bookmark(root, &body.folder_path, &body.title, &body.url))
        .await?;
    Ok(Json(AddBookmarkResp { bookmark_id }))
}

#[derive(Deserialize)]
struct PatchBookmarkBody {
    title: Option<String>,
    url: Option<String>,
    description: Option<String>,
}

async fn edit_bookmark_patch(
    State(state): State<AppState>,
    Path(id): Path<String>,
    Json(body): Json<PatchBookmarkBody>,
) -> ApiResult<OkResponse> {
    let patch = tree::BookmarkPatch {
        title: body.title,
        url: body.url,
        description: body.description,
    };
    state
        .edit(|root| tree::patch_bookmark(root, &id, patch))
        .await?;
    Ok(OkResponse::ok())
}

async fn edit_bookmark_delete(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> ApiResult<OkResponse> {
    state.edit(|root| tree::delete_bookmark(root, &id)).await?;
    Ok(OkResponse::ok())
}

#[derive(Deserialize)]
struct BulkDeleteBody {
    bookmark_ids: Vec<String>,
}

#[derive(Serialize)]
struct BulkDeleteResp {
    ok: bool,
    /// How many of the requested ids were actually removed.
    deleted: usize,
    /// Ids that were no longer in the tree. Reported rather than swallowed so
    /// the caller can tell "nothing matched" from "nothing was asked".
    missing: Vec<String>,
}

/// Delete a batch of bookmarks under a single undo snapshot.
///
/// Deleting the link-check results one id at a time through
/// `DELETE /edit/bookmark/:id` would push one undo entry per bookmark, so
/// putting back a 40-link sweep would take 40 undos. Ids that have already
/// gone are tolerated, matching `bulk-move`: the frontend sends whatever the
/// user selected, and one stale id must not abort the rest.
async fn edit_bookmark_bulk_delete(
    State(state): State<AppState>,
    Json(body): Json<BulkDeleteBody>,
) -> ApiResult<BulkDeleteResp> {
    let (deleted, missing) = state
        .edit_infallible(|root| {
            let mut deleted = 0usize;
            let mut missing = Vec::new();
            for id in &body.bookmark_ids {
                match tree::delete_bookmark(root, id) {
                    Ok(()) => deleted += 1,
                    Err(_) => missing.push(id.clone()),
                }
            }
            (deleted, missing)
        })
        .await;
    Ok(Json(BulkDeleteResp { ok: true, deleted, missing }))
}

#[derive(Deserialize)]
struct MoveBookmarkBody {
    folder_path: String,
}

async fn edit_bookmark_move(
    State(state): State<AppState>,
    Path(id): Path<String>,
    Json(body): Json<MoveBookmarkBody>,
) -> ApiResult<OkResponse> {
    state
        .edit(|root| tree::move_bookmark(root, &id, &body.folder_path))
        .await?;
    Ok(OkResponse::ok())
}

#[derive(Deserialize)]
struct ReorderBody {
    new_index: usize,
}

async fn edit_bookmark_reorder(
    State(state): State<AppState>,
    Path(id): Path<String>,
    Json(body): Json<ReorderBody>,
) -> ApiResult<OkResponse> {
    state
        .edit(|root| tree::reorder_bookmark(root, &id, body.new_index))
        .await?;
    Ok(OkResponse::ok())
}

async fn edit_bookmark_move_up(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> ApiResult<OkResponse> {
    state.edit(|root| tree::move_bookmark_up(root, &id)).await?;
    Ok(OkResponse::ok())
}

// --- Nodes (folders and bookmarks alike, addressed by node_id) -------------

#[derive(Deserialize)]
struct MoveNodeBody {
    target_parent_path: String,
    new_index: Option<usize>,
}

async fn edit_node_move(
    State(state): State<AppState>,
    Path(id): Path<String>,
    Json(body): Json<MoveNodeBody>,
) -> ApiResult<OkResponse> {
    state
        .edit(|root| tree::move_node(root, &id, &body.target_parent_path, body.new_index))
        .await?;
    Ok(OkResponse::ok())
}

async fn edit_node_reorder(
    State(state): State<AppState>,
    Path(id): Path<String>,
    Json(body): Json<ReorderBody>,
) -> ApiResult<OkResponse> {
    state
        .edit(|root| tree::reorder_node(root, &id, body.new_index))
        .await?;
    Ok(OkResponse::ok())
}

#[derive(Deserialize)]
struct BulkMoveBody {
    node_ids: Vec<String>,
    target_parent_path: String,
}

async fn edit_bookmark_bulk_move(
    State(state): State<AppState>,
    Json(body): Json<BulkMoveBody>,
) -> ApiResult<OkResponse> {
    // Per-node failures are deliberately tolerated: the frontend sends whatever
    // the user selected, and a stale id in the batch must not abort the rest.
    state
        .edit_infallible(|root| {
            for id in &body.node_ids {
                let _ = tree::move_node(root, id, &body.target_parent_path, None);
            }
        })
        .await;
    Ok(OkResponse::ok())
}

// --- Folders ---------------------------------------------------------------

#[derive(Deserialize)]
struct AddFolderBody {
    parent_path: String,
    title: String,
}

#[derive(Serialize)]
struct FolderPathResp {
    folder_path: String,
}

async fn edit_folder_add(
    State(state): State<AppState>,
    Json(body): Json<AddFolderBody>,
) -> ApiResult<FolderPathResp> {
    let folder_path = state
        .edit(|root| tree::add_folder(root, &body.parent_path, &body.title))
        .await?;
    Ok(Json(FolderPathResp { folder_path }))
}

#[derive(Deserialize)]
struct RenameFolderBody {
    folder_path: String,
    new_title: String,
}

async fn edit_folder_rename(
    State(state): State<AppState>,
    Json(body): Json<RenameFolderBody>,
) -> ApiResult<FolderPathResp> {
    let folder_path = state
        .edit(|root| tree::rename_folder(root, &body.folder_path, &body.new_title))
        .await?;
    Ok(Json(FolderPathResp { folder_path }))
}

#[derive(Deserialize)]
struct DeleteFolderQuery {
    folder_path: String,
}

async fn edit_folder_delete(
    State(state): State<AppState>,
    Query(q): Query<DeleteFolderQuery>,
) -> ApiResult<OkResponse> {
    state
        .edit(|root| tree::delete_folder(root, &q.folder_path))
        .await?;
    Ok(OkResponse::ok())
}

// --- Save ------------------------------------------------------------------

#[derive(Deserialize, Default)]
struct SaveBody {
    file_path: Option<String>,
}

#[derive(Serialize)]
struct SaveResp {
    saved_to: String,
    backup: Option<String>,
}

async fn edit_save(
    State(state): State<AppState>,
    Json(body): Json<SaveBody>,
) -> ApiResult<SaveResp> {
    let target: Utf8PathBuf = match body.file_path {
        Some(s) => Utf8PathBuf::from(s),
        None => state
            .inner
            .current_file
            .read()
            .await
            .clone()
            .ok_or_else(|| ApiError::bad_request("no file_path supplied and no current_file"))?,
    };

    // Ensure parent directory exists.
    if let Some(parent) = target.parent() {
        if !parent.as_str().is_empty() {
            std::fs::create_dir_all(parent)
                .map_err(|e| ApiError::internal(format!("create dir: {e}")))?;
        }
    }

    // Snapshot before overwriting. If the backup itself fails we stop: saving
    // over the only copy without a safety net is what the backup is there for.
    let backup_path = state.backup_before(target.as_std_path())?;

    {
        let root = state.inner.root.read().await;
        save_bookmarks(target.as_std_path(), &root, None).map_err(ApiError::internal)?;
    }

    record_save_fingerprint(&state, &target);

    state.mark_clean().await;
    *state.inner.current_file.write().await = Some(target.clone());
    Ok(Json(SaveResp {
        saved_to: target.to_string(),
        backup: backup_path.map(|p| p.display().to_string()),
    }))
}

/// Record the fingerprint of what was just written, so a clean reopen of this
/// exact file reattaches the session metadata (fetched titles + tags).
fn record_save_fingerprint(state: &AppState, target: &Utf8PathBuf) {
    let Some(db) = state.inner.db.as_ref() else {
        eprintln!("[session] edit_save: no db configured, open_state not recorded");
        return;
    };
    let Ok(html) = std::fs::read_to_string(target.as_std_path()) else {
        eprintln!(
            "[session] edit_save: failed to re-read saved file for hashing: {:?}",
            target.as_str()
        );
        return;
    };
    let hash = nbm_core::storage::hash_content(&html);
    eprintln!(
        "[session] edit_save: set_open_state path={:?} hash={:?}",
        target.as_str(),
        hash
    );
    if let Err(e) = db.set_open_state(target.as_str(), &hash) {
        eprintln!("[session] edit_save: set_open_state FAILED: {e:?}");
    }
}

