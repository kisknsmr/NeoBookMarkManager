//! Backup listing and restore. Restoring rolls back the HTML, the DB and
//! config.ini together, so the tree has to be reloaded afterwards.

use axum::extract::State;
use axum::routing::{get, post};
use axum::{Json, Router};
use nbm_core::backup::BackupTargets;
use nbm_core::storage::{load_bookmarks, LoadedBookmarks};
use nbm_core::tree;
use serde::{Deserialize, Serialize};

use crate::error::{ApiError, ApiResult};
use crate::routes::OkResponse;
use crate::state::AppState;

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/backup/list", get(backup_list))
        .route("/backup/restore", post(backup_restore))
        .route("/backup/undo-latest", post(backup_undo_latest))
}

/// The backup manager, or the "not configured in this install" error the three
/// handlers below all answer with.
fn manager(state: &AppState) -> Result<&nbm_core::backup::BackupManager, ApiError> {
    state
        .inner
        .backup_mgr
        .as_deref()
        .ok_or_else(|| ApiError::unavailable("backup mgr unavailable"))
}

#[derive(Serialize)]
struct BackupListResp {
    backups: Vec<String>,
}

async fn backup_list(State(state): State<AppState>) -> ApiResult<BackupListResp> {
    let dirs = manager(&state)?
        .list_backups()
        .into_iter()
        .map(|p| p.display().to_string())
        .collect();
    Ok(Json(BackupListResp { backups: dirs }))
}

#[derive(Deserialize)]
struct RestoreBody {
    backup_dir: String,
}

async fn backup_restore(
    State(state): State<AppState>,
    Json(body): Json<RestoreBody>,
) -> ApiResult<OkResponse> {
    restore_from(&state, std::path::Path::new(&body.backup_dir)).await?;
    Ok(OkResponse::ok())
}

async fn backup_undo_latest(State(state): State<AppState>) -> ApiResult<OkResponse> {
    let latest = manager(&state)?
        .list_backups()
        .into_iter()
        .next()
        .ok_or_else(|| ApiError::not_found("no backups"))?;
    restore_from(&state, &latest).await?;
    Ok(OkResponse::ok())
}

/// Roll the three files back to `dir` and reload the tree from what landed on
/// disk. Both restore endpoints do exactly this; they differ only in how they
/// pick the directory.
async fn restore_from(state: &AppState, dir: &std::path::Path) -> Result<(), ApiError> {
    let targets = current_targets(state)
        .await
        .ok_or_else(|| ApiError::unavailable("targets incomplete"))?;
    manager(state)?.restore_backup(dir, &targets)?;
    reload_after_restore(state, &targets).await
}

async fn current_targets(state: &AppState) -> Option<BackupTargets> {
    let bookmarks = state.inner.current_file.read().await.clone()?;
    let db = state.inner.db.as_ref()?.path.clone();
    Some(BackupTargets {
        bookmarks_html: bookmarks.as_std_path().to_path_buf(),
        user_data_db: db,
        config_ini: state.inner.config_ini_path.clone().filter(|p| p.exists()),
    })
}

async fn reload_after_restore(
    state: &AppState,
    targets: &BackupTargets,
) -> Result<(), ApiError> {
    let LoadedBookmarks { mut root, content_hash, .. } =
        load_bookmarks(&targets.bookmarks_html).map_err(ApiError::internal)?;
    tree::ensure_bookmark_ids(&mut root);
    tree::ensure_node_ids(&mut root);
    // The DB (incl. its session metadata + open_state) was just rolled back to
    // this backup, so the restored meta matches the restored HTML. Re-point the
    // fingerprint at the restored content; never clear here.
    if let Some(db) = state.inner.db.as_ref() {
        if let Some(path) = targets.bookmarks_html.to_str() {
            let _ = db.set_open_state(path, &content_hash);
        }
    }
    *state.inner.root.write().await = root;
    state.mark_clean().await;
    *state.inner.resume_available.write().await = false;
    Ok(())
}
