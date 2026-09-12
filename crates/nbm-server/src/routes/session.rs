//! Opening a bookmark file and resolving the "resume previous session?" prompt.

use axum::extract::State;
use axum::routing::{get, post};
use axum::{Json, Router};
use camino::Utf8PathBuf;
use nbm_core::storage::{load_bookmarks, LoadedBookmarks};
use nbm_core::tree;
use serde::{Deserialize, Serialize};

use crate::error::{ApiError, ApiResult};
use crate::state::{reconcile_session_meta, AppState};

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/file/open", post(file_open))
        .route("/session/state", get(session_state))
        .route("/session/resume", post(session_resume))
}

#[derive(Deserialize)]
struct FileOpenBody {
    path: String,
}

#[derive(Serialize)]
struct FileOpenResp {
    path: String,
    count: usize,
    resume_available: bool,
}

async fn file_open(
    State(state): State<AppState>,
    Json(body): Json<FileOpenBody>,
) -> ApiResult<FileOpenResp> {
    let path = Utf8PathBuf::from(&body.path);
    if !path.as_std_path().exists() {
        return Err(ApiError::not_found(format!("file not found: {}", body.path)));
    }
    let LoadedBookmarks { mut root, content_hash, .. } = load_bookmarks(path.as_std_path())
        .map_err(|e| ApiError::bad_request(format!("parse error: {e}")))?;
    tree::ensure_bookmark_ids(&mut root);
    tree::ensure_node_ids(&mut root);
    // Same reconciliation as startup: keep DB meta only if this is the same file
    // (path + hash) it was captured against; otherwise clear it.
    let resumable = state
        .inner
        .db
        .as_ref()
        .map(|db| reconcile_session_meta(db, path.as_str(), &content_hash))
        .unwrap_or(false);
    let count = root.count_bookmarks();
    *state.inner.root.write().await = root;
    *state.inner.current_file.write().await = Some(path.clone());
    state.mark_clean().await;
    *state.inner.resume_available.write().await = resumable;
    Ok(Json(FileOpenResp { path: path.to_string(), count, resume_available: resumable }))
}

// --- Session handlers ------------------------------------------------------

#[derive(Serialize)]
struct SessionStateResp {
    /// True when the opened file matches the fingerprint the DB session
    /// metadata was captured against — the frontend should ask the user
    /// whether to resume (keep) or start fresh (clear).
    resume_available: bool,
    file: Option<String>,
}

async fn session_state(State(state): State<AppState>) -> Json<SessionStateResp> {
    let resume_available = *state.inner.resume_available.read().await;
    let file = state.inner.current_file.read().await.as_ref().map(|p| p.to_string());
    Json(SessionStateResp { resume_available, file })
}

#[derive(Deserialize)]
struct SessionResumeBody {
    /// false → discard the previous session's fetched titles + tags.
    keep: bool,
}

#[derive(Serialize)]
struct SessionResumeResp {
    kept: bool,
}

async fn session_resume(
    State(state): State<AppState>,
    Json(body): Json<SessionResumeBody>,
) -> ApiResult<SessionResumeResp> {
    if !body.keep {
        if let Some(db) = state.inner.db.as_ref() {
            db.clear_session_data()
                .map_err(ApiError::internal)?;
        }
    }
    // Either way the prompt is now resolved; don't ask again this session.
    *state.inner.resume_available.write().await = false;
    Ok(Json(SessionResumeResp { kept: body.keep }))
}
