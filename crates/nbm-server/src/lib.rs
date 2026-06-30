//! In-process HTTP layer used both by the standalone bin and by the Tauri shell.

use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;

use axum::extract::{Path, Query, State};
use axum::http::{HeaderValue, Method, StatusCode};
use axum::routing::{delete, get, patch, post};
use axum::{Json, Router};
use camino::Utf8PathBuf;
use serde::{Deserialize, Serialize};
use tokio::net::TcpListener;
use tokio::sync::RwLock;
use tower_http::cors::CorsLayer;

use axum::response::sse::{Event, Sse};
use futures_util::stream::StreamExt;
use nbm_core::backup::{BackupManager, BackupTargets};
use nbm_core::db::Db;
use nbm_core::model::{Node, NodeKind};
use nbm_core::ai_classify;
use nbm_core::autotag;
use nbm_core::organize;
use nbm_core::storage::{load_bookmarks, save_bookmarks, LoadedBookmarks};
use nbm_core::tree;

#[derive(Clone)]
pub struct AppState {
    pub inner: Arc<AppStateInner>,
}

const UNDO_LIMIT: usize = 50;

pub struct AppStateInner {
    pub root: RwLock<Node>,
    pub current_file: RwLock<Option<Utf8PathBuf>>,
    pub dirty: RwLock<bool>,
    pub db: Option<Arc<Db>>,
    pub backup_mgr: Option<Arc<BackupManager>>,
    pub config_ini_path: Option<PathBuf>,
    pub http_client: reqwest::Client,
    pub undo_stack: RwLock<Vec<Node>>,
    pub redo_stack: RwLock<Vec<Node>>,
    /// True when the opened file matches the fingerprint the DB session metadata
    /// was captured against, so the frontend should ask whether to resume.
    pub resume_available: RwLock<bool>,
}

pub struct AppStateConfig {
    pub current_file: Option<Utf8PathBuf>,
    pub db: Option<Arc<Db>>,
    pub backup_mgr: Option<Arc<BackupManager>>,
    pub config_ini_path: Option<PathBuf>,
    /// Optional proxy URL (e.g. "http://proxy:3128").
    pub proxy_url: Option<String>,
}

impl Default for AppStateConfig {
    fn default() -> Self {
        Self {
            current_file: None,
            db: None,
            backup_mgr: None,
            config_ini_path: None,
            proxy_url: None,
        }
    }
}

impl AppState {
    pub fn new(root: Node, cfg: AppStateConfig) -> Self {
        let http_client = build_http_client(cfg.proxy_url.as_deref());
        Self {
            inner: Arc::new(AppStateInner {
                root: RwLock::new(root),
                current_file: RwLock::new(cfg.current_file),
                dirty: RwLock::new(false),
                db: cfg.db,
                backup_mgr: cfg.backup_mgr,
                config_ini_path: cfg.config_ini_path,
                http_client,
                undo_stack: RwLock::new(Vec::new()),
                redo_stack: RwLock::new(Vec::new()),
                resume_available: RwLock::new(false),
            }),
        }
    }

    pub async fn load_from_file(
        path: &Utf8PathBuf,
        cfg: AppStateConfig,
    ) -> anyhow::Result<Self> {
        let LoadedBookmarks { mut root, content_hash, .. } = load_bookmarks(path.as_std_path())?;
        eprintln!(
            "[session] load_from_file: path={:?} hash={:?} db_configured={}",
            path.as_str(), content_hash, cfg.db.is_some()
        );
        if let Some(db) = cfg.db.as_ref() {
            eprintln!("[session] load_from_file: db_path={:?}", db.path);
        }
        tree::ensure_bookmark_ids(&mut root);
        tree::ensure_node_ids(&mut root);
        // Decide whether the DB session metadata (fetched titles + tags) belongs
        // to this exact file. Same path + same content hash → resumable (kept,
        // frontend confirms). Different file → cleared immediately.
        let resumable = cfg
            .db
            .as_ref()
            .map(|db| reconcile_session_meta(db, path.as_str(), &content_hash))
            .unwrap_or(false);
        let cfg = AppStateConfig {
            current_file: Some(path.clone()),
            ..cfg
        };
        let state = Self::new(root, cfg);
        *state.inner.resume_available.write().await = resumable;
        Ok(state)
    }
}

/// Decide what happens to the DB session metadata (fetched titles + tags) when a
/// bookmark file is opened, by comparing the file's `(path, content_hash)` to
/// the fingerprint stored at the last save.
///
/// - Same path AND same hash → returns `true` (resumable): metadata is kept and
///   the frontend asks the user whether to continue editing.
/// - Otherwise (different file, externally modified, or first run) → clears
///   meta + tags and returns `false`.
///
/// The new fingerprint is NOT written here; that happens on save so it always
/// reflects the on-disk content.
fn reconcile_session_meta(db: &Db, path: &str, content_hash: &str) -> bool {
    let prev = db.get_open_state().ok().flatten();
    let resumable = matches!(
        prev,
        Some((ref p, ref h)) if p == path && h == content_hash
    );
    eprintln!(
        "[session] reconcile: current=({path:?}, {content_hash:?}) prev_open_state={prev:?} resumable={resumable}"
    );
    if !resumable {
        eprintln!("[session] clearing session meta/tags (mismatch or no prior open_state)");
        let _ = db.clear_session_data();
    }
    resumable
}

fn build_http_client(proxy_url: Option<&str>) -> reqwest::Client {
    let mut builder = reqwest::Client::builder()
        .user_agent("Mozilla/5.0 (NeoBookMarkManager)")
        .timeout(std::time::Duration::from_secs(5))
        .danger_accept_invalid_certs(false);
    if let Some(url) = proxy_url {
        if let Ok(proxy) = reqwest::Proxy::all(url) {
            builder = builder.proxy(proxy);
        }
    }
    builder.build().unwrap_or_default()
}

pub fn router(state: AppState) -> Router {
    let cors = CorsLayer::new()
        .allow_origin([
            "tauri://localhost".parse::<HeaderValue>().unwrap(),
            "http://localhost:1430".parse::<HeaderValue>().unwrap(),
            "http://127.0.0.1:1430".parse::<HeaderValue>().unwrap(),
        ])
        .allow_methods([Method::GET, Method::POST, Method::PATCH, Method::DELETE])
        .allow_headers(tower_http::cors::Any);

    Router::new()
        .route("/health", get(health))
        .route("/bookmarks", get(list_bookmarks))
        .route("/tree", get(get_tree))
        .route("/meta/:bookmark_id", get(get_bookmark_meta))
        .route("/edit/node/:id/reorder", post(edit_node_reorder))
        .route("/edit/node/:id/move", post(edit_node_move))
        .route("/search", get(search))
        .route("/tags/:bookmark_id", get(get_tags))
        .route("/tags/update", post(update_tags))
        // Edit
        .route("/edit/undo", post(edit_undo))
        .route("/edit/redo", post(edit_redo))
        .route("/edit/history", get(edit_history))
        .route("/edit/bookmark/bulk-move", post(edit_bookmark_bulk_move))
        .route("/edit/bookmark/add", post(edit_bookmark_add))
        .route("/edit/bookmark/:id", patch(edit_bookmark_patch).delete(edit_bookmark_delete))
        .route("/edit/bookmark/:id/move", post(edit_bookmark_move))
        .route("/edit/bookmark/:id/reorder", post(edit_bookmark_reorder))
        .route("/edit/bookmark/:id/move-up", post(edit_bookmark_move_up))
        .route("/edit/folder/add", post(edit_folder_add))
        .route("/edit/folder/rename", patch(edit_folder_rename))
        .route("/edit/folder", delete(edit_folder_delete))
        .route("/edit/save", post(edit_save))
        // File
        .route("/file/open", post(file_open))
        .route("/session/state", get(session_state))
        .route("/session/resume", post(session_resume))
        // Backup
        .route("/backup/list", get(backup_list))
        .route("/backup/restore", post(backup_restore))
        .route("/backup/undo-latest", post(backup_undo_latest))
        // Autotag
        .route("/autotag/local", post(autotag_local))
        // Network
        .route("/network/fix-titles", post(network_fix_titles))
        .route("/network/fetch-preview", post(network_fetch_preview))
        .route("/network/proxy-check", get(network_proxy_check))
        .route("/network/link-check", post(network_link_check))
        // Config (settings)
        .route("/config/ai-status", get(config_ai_status))
        .route("/config/api-key", post(config_set_api_key))
        .route("/config/ai-pricing", post(config_set_ai_pricing))
        .route("/config/models", get(config_models))
        // Classify
        .route("/classify/estimate", post(classify_estimate))
        .route("/classify/ai", post(classify_ai))
        .route("/classify/ai-apply", post(classify_ai_apply))
        // Organize
        .route("/organize/dedupe", post(organize_dedupe))
        .route("/organize/merge-duplicate-folders", post(organize_merge_dup_folders))
        .route("/organize/domain-stats", get(organize_domain_stats))
        .route("/organize/consolidate-by-domain", post(organize_consolidate_domain))
        .route("/organize/sort-by-domain", post(organize_sort_by_domain))
        .with_state(state)
        .layer(cors)
}

pub async fn bind(host: &str, port: u16) -> std::io::Result<(TcpListener, u16)> {
    let addr: SocketAddr = format!("{host}:{port}").parse().map_err(|e| {
        std::io::Error::new(std::io::ErrorKind::InvalidInput, format!("bad addr: {e}"))
    })?;
    let listener = TcpListener::bind(addr).await?;
    let actual = listener.local_addr()?.port();
    Ok((listener, actual))
}

pub async fn serve(listener: TcpListener, state: AppState) -> anyhow::Result<()> {
    axum::serve(listener, router(state)).await?;
    Ok(())
}

// --- error mapping ---------------------------------------------------------

#[derive(Serialize)]
struct ApiError {
    error: String,
}

fn err(status: StatusCode, msg: impl ToString) -> (StatusCode, Json<ApiError>) {
    (status, Json(ApiError { error: msg.to_string() }))
}

fn map_tree_err(e: tree::TreeError) -> (StatusCode, Json<ApiError>) {
    use tree::TreeError::*;
    match e {
        FolderNotFound(_) | BookmarkNotFound(_) => err(StatusCode::NOT_FOUND, e),
        NotFolder(_) | Invalid(_) => err(StatusCode::BAD_REQUEST, e),
    }
}

// --- Read handlers ---------------------------------------------------------

#[derive(Serialize)]
struct HealthResponse {
    status: &'static str,
    version: &'static str,
}

async fn health() -> Json<HealthResponse> {
    Json(HealthResponse { status: "ok", version: env!("CARGO_PKG_VERSION") })
}

#[derive(Deserialize)]
struct ListQuery {
    file_path: Option<String>,
}

#[derive(Serialize)]
struct ListResponse {
    file_path: Option<String>,
    count: usize,
    items: Vec<FlatBookmark>,
    dirty: bool,
}

#[derive(Serialize)]
struct FlatBookmark {
    bookmark_id: String,
    title: String,
    url: String,
    folder_path: String,
    add_date: String,
    last_modified: String,
    icon: String,
    description: String,
}

async fn list_bookmarks(
    State(state): State<AppState>,
    Query(q): Query<ListQuery>,
) -> Json<ListResponse> {
    let _ = q.file_path;
    let root = state.inner.root.read().await;
    let mut items = Vec::new();
    flatten(&root, "", &mut items);
    let file_path = state
        .inner
        .current_file
        .read()
        .await
        .as_ref()
        .map(|p| p.to_string());
    let dirty = *state.inner.dirty.read().await;
    Json(ListResponse { file_path, count: items.len(), items, dirty })
}

fn flatten(node: &Node, prefix: &str, out: &mut Vec<FlatBookmark>) {
    for child in &node.children {
        match child.kind {
            NodeKind::Folder => {
                let next = if prefix.is_empty() {
                    child.title.clone()
                } else {
                    format!("{prefix}/{}", child.title)
                };
                flatten(child, &next, out);
            }
            NodeKind::Bookmark => out.push(FlatBookmark {
                bookmark_id: child.bookmark_id.clone(),
                title: child.title.clone(),
                url: child.url.clone(),
                folder_path: prefix.to_string(),
                add_date: child.add_date.clone(),
                last_modified: child.last_modified.clone(),
                icon: child.icon.clone(),
                description: child.description.clone(),
            }),
        }
    }
}

#[derive(Deserialize)]
struct SearchQuery {
    q: Option<String>,
    limit: Option<usize>,
    file_path: Option<String>,
}

async fn search(
    State(state): State<AppState>,
    Query(q): Query<SearchQuery>,
) -> Json<ListResponse> {
    let _ = q.file_path;
    let needle = q.q.unwrap_or_default().to_lowercase();
    let limit = q.limit.unwrap_or(200);
    let root = state.inner.root.read().await;
    let mut items = Vec::new();
    flatten(&root, "", &mut items);
    if !needle.is_empty() {
        let tokens: Vec<&str> = needle.split_whitespace().collect();
        items.retain(|b| {
            let hay = format!(
                "{} {} {}",
                b.title.to_lowercase(),
                b.url.to_lowercase(),
                b.folder_path.to_lowercase()
            );
            tokens.iter().all(|t| hay.contains(t))
        });
    }
    items.truncate(limit);
    let file_path = state
        .inner
        .current_file
        .read()
        .await
        .as_ref()
        .map(|p| p.to_string());
    let dirty = *state.inner.dirty.read().await;
    Json(ListResponse { file_path, count: items.len(), items, dirty })
}

// --- Tags ------------------------------------------------------------------

#[derive(Serialize)]
struct TagsResponse {
    bookmark_id: String,
    tags: Vec<nbm_core::db::TagDetail>,
}

async fn get_tags(
    State(state): State<AppState>,
    Path(bookmark_id): Path<String>,
) -> Result<Json<TagsResponse>, (StatusCode, Json<ApiError>)> {
    let tags = match &state.inner.db {
        Some(db) => db.get_tags(&bookmark_id).map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?,
        None => Vec::new(),
    };
    Ok(Json(TagsResponse { bookmark_id, tags }))
}

#[derive(Deserialize)]
struct TagsUpdateBody {
    bookmark_id: String,
    tags: Vec<String>,
    #[serde(default = "default_source")]
    source: String,
    confidence: Option<f64>,
}

fn default_source() -> String { "manual".into() }

#[derive(Serialize)]
struct OkResponse { ok: bool }

async fn update_tags(
    State(state): State<AppState>,
    Json(body): Json<TagsUpdateBody>,
) -> Result<Json<OkResponse>, (StatusCode, Json<ApiError>)> {
    let db = state
        .inner
        .db
        .as_ref()
        .ok_or_else(|| err(StatusCode::SERVICE_UNAVAILABLE, "tags db unavailable"))?;
    db.save_tags_for_url(&body.bookmark_id, &body.tags, &body.source, body.confidence)
        .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    Ok(Json(OkResponse { ok: true }))
}

// --- Edit ------------------------------------------------------------------

async fn mark_dirty(state: &AppState) {
    *state.inner.dirty.write().await = true;
}

/// Snapshot the current root onto the undo stack, clear redo stack, mark dirty.
/// Call this BEFORE mutating root.
async fn push_undo(state: &AppState) {
    let snapshot = state.inner.root.read().await.clone();
    let mut stack = state.inner.undo_stack.write().await;
    stack.push(snapshot);
    if stack.len() > UNDO_LIMIT {
        stack.remove(0);
    }
    drop(stack);
    state.inner.redo_stack.write().await.clear();
    *state.inner.dirty.write().await = true;
}

#[derive(Serialize)]
struct UndoRedoResp {
    ok: bool,
    undo_count: usize,
    redo_count: usize,
}

async fn edit_undo(
    State(state): State<AppState>,
) -> Result<Json<UndoRedoResp>, (StatusCode, Json<ApiError>)> {
    let mut undo = state.inner.undo_stack.write().await;
    let snapshot = undo.pop()
        .ok_or_else(|| err(StatusCode::CONFLICT, "undo stack is empty"))?;
    let undo_count = undo.len();
    drop(undo);

    let current = state.inner.root.read().await.clone();
    state.inner.redo_stack.write().await.push(current);
    let redo_count = state.inner.redo_stack.read().await.len();

    *state.inner.root.write().await = snapshot;
    *state.inner.dirty.write().await = true;
    Ok(Json(UndoRedoResp { ok: true, undo_count, redo_count }))
}

async fn edit_redo(
    State(state): State<AppState>,
) -> Result<Json<UndoRedoResp>, (StatusCode, Json<ApiError>)> {
    let mut redo = state.inner.redo_stack.write().await;
    let snapshot = redo.pop()
        .ok_or_else(|| err(StatusCode::CONFLICT, "redo stack is empty"))?;
    let redo_count = redo.len();
    drop(redo);

    let current = state.inner.root.read().await.clone();
    state.inner.undo_stack.write().await.push(current);
    let undo_count = state.inner.undo_stack.read().await.len();

    *state.inner.root.write().await = snapshot;
    *state.inner.dirty.write().await = true;
    Ok(Json(UndoRedoResp { ok: true, undo_count, redo_count }))
}

async fn edit_history(
    State(state): State<AppState>,
) -> Json<UndoRedoResp> {
    let undo_count = state.inner.undo_stack.read().await.len();
    let redo_count = state.inner.redo_stack.read().await.len();
    Json(UndoRedoResp { ok: true, undo_count, redo_count })
}

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
) -> Result<Json<AddBookmarkResp>, (StatusCode, Json<ApiError>)> {
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    let id = tree::add_bookmark(&mut root, &body.folder_path, &body.title, &body.url)
        .map_err(map_tree_err)?;
    Ok(Json(AddBookmarkResp { bookmark_id: id }))
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
) -> Result<Json<OkResponse>, (StatusCode, Json<ApiError>)> {
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    tree::patch_bookmark(
        &mut root,
        &id,
        tree::BookmarkPatch {
            title: body.title,
            url: body.url,
            description: body.description,
        },
    )
    .map_err(map_tree_err)?;
    Ok(Json(OkResponse { ok: true }))
}

async fn edit_bookmark_delete(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Json<OkResponse>, (StatusCode, Json<ApiError>)> {
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    tree::delete_bookmark(&mut root, &id).map_err(map_tree_err)?;
    Ok(Json(OkResponse { ok: true }))
}

#[derive(Deserialize)]
struct MoveBookmarkBody {
    folder_path: String,
}

async fn edit_bookmark_move(
    State(state): State<AppState>,
    Path(id): Path<String>,
    Json(body): Json<MoveBookmarkBody>,
) -> Result<Json<OkResponse>, (StatusCode, Json<ApiError>)> {
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    tree::move_bookmark(&mut root, &id, &body.folder_path).map_err(map_tree_err)?;
    Ok(Json(OkResponse { ok: true }))
}

#[derive(Deserialize)]
struct ReorderBody {
    new_index: usize,
}

async fn edit_bookmark_reorder(
    State(state): State<AppState>,
    Path(id): Path<String>,
    Json(body): Json<ReorderBody>,
) -> Result<Json<OkResponse>, (StatusCode, Json<ApiError>)> {
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    tree::reorder_bookmark(&mut root, &id, body.new_index).map_err(map_tree_err)?;
    Ok(Json(OkResponse { ok: true }))
}

async fn get_tree(State(state): State<AppState>) -> Json<Node> {
    let root = state.inner.root.read().await;
    Json(root.clone())
}

#[derive(Serialize)]
struct BookmarkMetaResp {
    fetched_title: Option<String>,
}

async fn get_bookmark_meta(
    State(state): State<AppState>,
    Path(bookmark_id): Path<String>,
) -> Json<BookmarkMetaResp> {
    let fetched_title = state.inner.db.as_ref()
        .and_then(|db| db.get_meta(&bookmark_id).ok().flatten());
    Json(BookmarkMetaResp { fetched_title })
}

async fn edit_node_reorder(
    State(state): State<AppState>,
    Path(id): Path<String>,
    Json(body): Json<ReorderBody>,
) -> Result<Json<OkResponse>, (StatusCode, Json<ApiError>)> {
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    tree::reorder_node(&mut root, &id, body.new_index).map_err(map_tree_err)?;
    Ok(Json(OkResponse { ok: true }))
}

#[derive(Deserialize)]
struct MoveNodeBody {
    target_parent_path: String,
    new_index: Option<usize>,
}

async fn edit_node_move(
    State(state): State<AppState>,
    Path(id): Path<String>,
    Json(body): Json<MoveNodeBody>,
) -> Result<Json<OkResponse>, (StatusCode, Json<ApiError>)> {
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    tree::move_node(&mut root, &id, &body.target_parent_path, body.new_index)
        .map_err(map_tree_err)?;
    Ok(Json(OkResponse { ok: true }))
}

#[derive(Deserialize)]
struct BulkMoveBody {
    node_ids: Vec<String>,
    target_parent_path: String,
}

async fn edit_bookmark_bulk_move(
    State(state): State<AppState>,
    Json(body): Json<BulkMoveBody>,
) -> Result<Json<OkResponse>, (StatusCode, Json<ApiError>)> {
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    for id in &body.node_ids {
        let _ = tree::move_node(&mut root, id, &body.target_parent_path, None);
    }
    Ok(Json(OkResponse { ok: true }))
}

async fn edit_bookmark_move_up(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Json<OkResponse>, (StatusCode, Json<ApiError>)> {
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    tree::move_bookmark_up(&mut root, &id).map_err(map_tree_err)?;
    Ok(Json(OkResponse { ok: true }))
}

#[derive(Deserialize)]
struct AddFolderBody {
    parent_path: String,
    title: String,
}

#[derive(Serialize)]
struct AddFolderResp {
    folder_path: String,
}

async fn edit_folder_add(
    State(state): State<AppState>,
    Json(body): Json<AddFolderBody>,
) -> Result<Json<AddFolderResp>, (StatusCode, Json<ApiError>)> {
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    let p = tree::add_folder(&mut root, &body.parent_path, &body.title).map_err(map_tree_err)?;
    Ok(Json(AddFolderResp { folder_path: p }))
}

#[derive(Deserialize)]
struct RenameFolderBody {
    folder_path: String,
    new_title: String,
}

#[derive(Serialize)]
struct RenameFolderResp {
    folder_path: String,
}

async fn edit_folder_rename(
    State(state): State<AppState>,
    Json(body): Json<RenameFolderBody>,
) -> Result<Json<RenameFolderResp>, (StatusCode, Json<ApiError>)> {
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    let p = tree::rename_folder(&mut root, &body.folder_path, &body.new_title)
        .map_err(map_tree_err)?;
    Ok(Json(RenameFolderResp { folder_path: p }))
}

#[derive(Deserialize)]
struct DeleteFolderQuery {
    folder_path: String,
}

async fn edit_folder_delete(
    State(state): State<AppState>,
    Query(q): Query<DeleteFolderQuery>,
) -> Result<Json<OkResponse>, (StatusCode, Json<ApiError>)> {
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    tree::delete_folder(&mut root, &q.folder_path).map_err(map_tree_err)?;
    Ok(Json(OkResponse { ok: true }))
}

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
) -> Result<Json<SaveResp>, (StatusCode, Json<ApiError>)> {
    let target: Utf8PathBuf = match body.file_path {
        Some(s) => Utf8PathBuf::from(s),
        None => state
            .inner
            .current_file
            .read()
            .await
            .clone()
            .ok_or_else(|| err(StatusCode::BAD_REQUEST, "no file_path supplied and no current_file"))?,
    };

    // Ensure parent directory exists.
    if let Some(parent) = target.parent() {
        if !parent.as_str().is_empty() {
            std::fs::create_dir_all(parent)
                .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, format!("create dir: {e}")))?;
        }
    }

    // Best-effort backup before overwriting — failures are logged but never
    // block the save. If all 3 backup targets exist, we snapshot; otherwise skip.
    let backup_path = pre_save_backup(&state, &target).await;

    let root = state.inner.root.read().await;
    save_bookmarks(target.as_std_path(), &root, None)
        .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    drop(root);

    // Record the fingerprint of what we just wrote so a clean reopen of this
    // exact file reattaches the session metadata (fetched titles + tags).
    if let Some(db) = state.inner.db.as_ref() {
        if let Ok(html) = std::fs::read_to_string(target.as_std_path()) {
            let hash = nbm_core::storage::hash_content(&html);
            eprintln!("[session] edit_save: set_open_state path={:?} hash={:?}", target.as_str(), hash);
            if let Err(e) = db.set_open_state(target.as_str(), &hash) {
                eprintln!("[session] edit_save: set_open_state FAILED: {e:?}");
            }
        } else {
            eprintln!("[session] edit_save: failed to re-read saved file for hashing: {:?}", target.as_str());
        }
    } else {
        eprintln!("[session] edit_save: no db configured, open_state not recorded");
    }

    *state.inner.dirty.write().await = false;
    *state.inner.current_file.write().await = Some(target.clone());
    Ok(Json(SaveResp {
        saved_to: target.to_string(),
        backup: backup_path.map(|p| p.display().to_string()),
    }))
}

async fn pre_save_backup(state: &AppState, target: &Utf8PathBuf) -> Option<PathBuf> {
    let bm = state.inner.backup_mgr.clone()?;
    let db_path = state.inner.db.as_ref()?.path.clone();
    let cfg_path = state.inner.config_ini_path.clone()?;
    let html_path = target.as_std_path().to_path_buf();
    // Skip if any target is missing — backup requires all 3 files to exist.
    if !html_path.exists() || !db_path.exists() || !cfg_path.exists() {
        return None;
    }
    let targets = BackupTargets {
        bookmarks_html: html_path,
        user_data_db: db_path,
        config_ini: cfg_path,
    };
    bm.create_backup(&targets).ok()
}

// --- Backup ----------------------------------------------------------------

// --- File handlers ---------------------------------------------------------

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
) -> Result<Json<FileOpenResp>, (StatusCode, Json<ApiError>)> {
    let path = Utf8PathBuf::from(&body.path);
    if !path.as_std_path().exists() {
        return Err(err(StatusCode::NOT_FOUND, format!("file not found: {}", body.path)));
    }
    let LoadedBookmarks { mut root, content_hash, .. } = load_bookmarks(path.as_std_path())
        .map_err(|e| err(StatusCode::BAD_REQUEST, format!("parse error: {e}")))?;
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
    let count = {
        let mut items = Vec::new();
        flatten(&root, "", &mut items);
        items.len()
    };
    *state.inner.root.write().await = root;
    *state.inner.current_file.write().await = Some(path.clone());
    *state.inner.dirty.write().await = false;
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
) -> Result<Json<SessionResumeResp>, (StatusCode, Json<ApiError>)> {
    if !body.keep {
        if let Some(db) = state.inner.db.as_ref() {
            db.clear_session_data()
                .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        }
    }
    // Either way the prompt is now resolved; don't ask again this session.
    *state.inner.resume_available.write().await = false;
    Ok(Json(SessionResumeResp { kept: body.keep }))
}

// --- Backup handlers -------------------------------------------------------

#[derive(Serialize)]
struct BackupListResp {
    backups: Vec<String>,
}

async fn backup_list(
    State(state): State<AppState>,
) -> Result<Json<BackupListResp>, (StatusCode, Json<ApiError>)> {
    let bm = state
        .inner
        .backup_mgr
        .as_ref()
        .ok_or_else(|| err(StatusCode::SERVICE_UNAVAILABLE, "backup mgr unavailable"))?;
    let dirs = bm
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
) -> Result<Json<OkResponse>, (StatusCode, Json<ApiError>)> {
    let bm = state
        .inner
        .backup_mgr
        .as_ref()
        .ok_or_else(|| err(StatusCode::SERVICE_UNAVAILABLE, "backup mgr unavailable"))?;
    let targets = current_targets(&state).await
        .ok_or_else(|| err(StatusCode::SERVICE_UNAVAILABLE, "targets incomplete"))?;
    bm.restore_backup(std::path::Path::new(&body.backup_dir), &targets)
        .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    reload_after_restore(&state, &targets).await?;
    Ok(Json(OkResponse { ok: true }))
}

async fn backup_undo_latest(
    State(state): State<AppState>,
) -> Result<Json<OkResponse>, (StatusCode, Json<ApiError>)> {
    let bm = state
        .inner
        .backup_mgr
        .as_ref()
        .ok_or_else(|| err(StatusCode::SERVICE_UNAVAILABLE, "backup mgr unavailable"))?;
    let latest = bm
        .list_backups()
        .into_iter()
        .next()
        .ok_or_else(|| err(StatusCode::NOT_FOUND, "no backups"))?;
    let targets = current_targets(&state).await
        .ok_or_else(|| err(StatusCode::SERVICE_UNAVAILABLE, "targets incomplete"))?;
    bm.restore_backup(&latest, &targets)
        .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    reload_after_restore(&state, &targets).await?;
    Ok(Json(OkResponse { ok: true }))
}

async fn current_targets(state: &AppState) -> Option<BackupTargets> {
    let bookmarks = state.inner.current_file.read().await.clone()?;
    let db = state.inner.db.as_ref()?.path.clone();
    let cfg = state.inner.config_ini_path.clone()?;
    Some(BackupTargets {
        bookmarks_html: bookmarks.as_std_path().to_path_buf(),
        user_data_db: db,
        config_ini: cfg,
    })
}

async fn reload_after_restore(
    state: &AppState,
    targets: &BackupTargets,
) -> Result<(), (StatusCode, Json<ApiError>)> {
    let LoadedBookmarks { mut root, content_hash, .. } = load_bookmarks(&targets.bookmarks_html)
        .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
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
    *state.inner.dirty.write().await = false;
    *state.inner.resume_available.write().await = false;
    Ok(())
}

// --- Network handlers (SSE) ------------------------------------------------

#[derive(Deserialize)]
struct NetworkBatchBody {
    /// List of bookmark_ids to process.
    bookmark_ids: Vec<String>,
}

/// Case-insensitive `find`, restricted to ASCII needles, that returns a byte
/// index valid in the *original* (non-lowercased) haystack.
///
/// `str::to_lowercase()` can change the byte length of the string for some
/// Unicode characters (e.g. Turkish dotted İ, Kelvin sign K), so indices
/// found in a lowercased copy are not safe to slice the original string with
/// — they can land out of bounds or mid-character. Since our needles here
/// are always plain ASCII tag/attribute names, we instead scan the original
/// bytes and fold case only on the ASCII range; a match can only occur at a
/// true ASCII byte position, which is always a valid char boundary.
fn find_ascii_ci(haystack: &str, needle: &str) -> Option<usize> {
    let h = haystack.as_bytes();
    let n = needle.as_bytes();
    if n.is_empty() || n.len() > h.len() {
        return None;
    }
    (0..=h.len() - n.len()).find(|&i| {
        h[i..i + n.len()]
            .iter()
            .zip(n)
            .all(|(&a, &b)| a.to_ascii_lowercase() == b.to_ascii_lowercase())
    })
}

fn rfind_ascii_ci(haystack: &str, needle: &str) -> Option<usize> {
    let h = haystack.as_bytes();
    let n = needle.as_bytes();
    if n.is_empty() || n.len() > h.len() {
        return None;
    }
    (0..=h.len() - n.len()).rev().find(|&i| {
        h[i..i + n.len()]
            .iter()
            .zip(n)
            .all(|(&a, &b)| a.to_ascii_lowercase() == b.to_ascii_lowercase())
    })
}

/// Extract `<title>` and `<meta property="og:title">` / `<meta name="description">` from HTML.
/// Quick scan without a full DOM — we stop once we leave `<head>`.
fn extract_meta(html: &str) -> (String, String) {
    let head_end = find_ascii_ci(html, "</head>").unwrap_or(html.len());
    let head = &html[..head_end];

    let og_title = extract_meta_attr(head, "og:title");
    let title_tag = extract_title_tag(head);
    let title = og_title.or(title_tag).unwrap_or_default();

    let og_desc = extract_meta_attr(head, "og:description");
    let meta_desc = extract_meta_name(head, "description");
    let description = og_desc.or(meta_desc).unwrap_or_default();
    (title, description)
}

fn extract_title_tag(html: &str) -> Option<String> {
    let title_start = find_ascii_ci(html, "<title")?;
    let tag_close = html[title_start..].find('>')? + title_start + 1;
    let end = find_ascii_ci(&html[tag_close..], "</title>")?;
    Some(html[tag_close..tag_close + end].trim().to_string())
}

fn extract_meta_attr(html: &str, property: &str) -> Option<String> {
    let prop_str = format!("property=\"{}\"", property);
    let idx = find_ascii_ci(html, &prop_str)?;
    // Backtrack to `<meta` to get the full tag.
    let meta_start = rfind_ascii_ci(&html[..idx], "<meta")?;
    let tag_end = html[idx..].find('>')?;
    let tag = &html[meta_start..idx + tag_end + 1];
    extract_attr(tag, "content")
}

fn extract_meta_name(html: &str, name: &str) -> Option<String> {
    let needle = format!("name=\"{}\"", name);
    let idx = find_ascii_ci(html, &needle)?;
    let meta_start = rfind_ascii_ci(&html[..idx], "<meta")?;
    let tag_end = html[idx..].find('>')?;
    let tag = &html[meta_start..idx + tag_end + 1];
    extract_attr(tag, "content")
}

fn extract_attr(tag: &str, attr: &str) -> Option<String> {
    let search = format!("{}=\"", attr);
    let start = find_ascii_ci(tag, &search)? + search.len();
    let end = tag[start..].find('"')?;
    Some(html_decode(&tag[start..start + end]))
}

fn html_decode(s: &str) -> String {
    s.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&#39;", "'")
        .replace("&apos;", "'")
}

#[cfg(test)]
mod meta_extraction_tests {
    use super::*;

    /// `İ` (Turkish dotted capital I, U+0130) lowercases to a 2-character,
    /// 3-byte sequence ("i̇"), one byte longer than the 2-byte original.
    /// A naive `html.to_lowercase().find(...)` index used to slice the
    /// original `html` would therefore land out of bounds / off a char
    /// boundary once enough of these appear before the target tag.
    #[test]
    fn extract_meta_handles_byte_length_changing_lowercase() {
        let html = format!(
            "<html><head><title>İstanbul</title>\
             <meta property=\"og:title\" content=\"İstanbul Guide\">\
             <meta name=\"description\" content=\"İ İ İ İ İ İ İ İ İ İ travel tips\">\
             </head><body></body></html>"
        );
        let (title, description) = extract_meta(&html);
        assert_eq!(title, "İstanbul Guide");
        assert_eq!(description, "İ İ İ İ İ İ İ İ İ İ travel tips");
    }

    #[test]
    fn extract_meta_falls_back_to_title_tag() {
        let html = "<html><head><title>Plain Title</title></head><body></body></html>";
        let (title, _description) = extract_meta(html);
        assert_eq!(title, "Plain Title");
    }

    #[test]
    fn extract_meta_no_head_close_tag_does_not_panic() {
        let html = "<html><head><title>No closing head tag</title>";
        let (title, _description) = extract_meta(html);
        assert_eq!(title, "No closing head tag");
    }
}

/// SSE event payload sent for each processed bookmark.
#[derive(Serialize, Clone)]
struct NetworkProgress {
    bookmark_id: String,
    processed: usize,
    total: usize,
    status: String, // "ok" | "error" | "done"
    #[serde(skip_serializing_if = "Option::is_none")]
    bookmark_title: Option<String>, // 処理中のブックマーク名（プログレス表示用）
    #[serde(skip_serializing_if = "Option::is_none")]
    new_title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    description: Option<String>,
}

async fn network_fix_titles(
    State(state): State<AppState>,
    Json(body): Json<NetworkBatchBody>,
) -> Sse<impl futures_util::Stream<Item = Result<Event, std::convert::Infallible>>> {
    let (tx, rx) = tokio::sync::mpsc::channel::<NetworkProgress>(32);
    let client = state.inner.http_client.clone();

    // Collect (id, url, title) to fetch.
    let urls: Vec<(String, String, String)> = {
        let root = state.inner.root.read().await;
        body.bookmark_ids
            .iter()
            .filter_map(|id| {
                let (path, idx) = nbm_core::tree::locate_bookmark(&root, id)?;
                let folder = nbm_core::tree::find_folder(&root, &path)?;
                let bm = folder.children.get(idx)?;
                Some((id.clone(), bm.url.clone(), bm.title.clone()))
            })
            .collect()
    };
    // `total` reflects the work actually queued, not the requested id count —
    // ids that fail to resolve in the tree are silently dropped from `urls`,
    // and the "done" event must match the processed count for the progress
    // bar to reach 100% correctly instead of jumping early.
    let total = urls.len();

    let db = state.inner.db.clone();
    let concurrency = load_fetch_concurrency(&state);
    eprintln!(
        "[fix-titles] requested={} resolved={} concurrency={}",
        body.bookmark_ids.len(),
        urls.len(),
        concurrency
    );
    if urls.len() != body.bookmark_ids.len() {
        let resolved_ids: std::collections::HashSet<&String> = urls.iter().map(|(id, _, _)| id).collect();
        let missing: Vec<&String> = body.bookmark_ids.iter().filter(|id| !resolved_ids.contains(id)).collect();
        eprintln!("[fix-titles] {} ids could not be located in tree: {:?}", missing.len(), missing);
    }
    tokio::spawn(async move {
        use futures_util::StreamExt as _;
        // Shared progress counter — completion order is non-deterministic when parallel.
        let processed = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));

        futures_util::stream::iter(urls)
            .map(|(id, url, title)| {
                let client = client.clone();
                let db = db.clone();
                let tx = tx.clone();
                let processed = processed.clone();
                async move {
                    let (new_title, description, status) = match fetch_url_meta(&client, &url).await {
                        Ok((t, d)) => (Some(t), Some(d), "ok".to_string()),
                        Err(e) => (None, None, format!("error: {e}")),
                    };

                    // fetched_title → DB のみ保存（HTML/Node ツリーには書かない）
                    if status == "ok" {
                        if let (Some(ref t), Some(ref db)) = (&new_title, &db) {
                            if !t.is_empty() {
                                let _ = db.save_meta(&id, t);
                            }
                        }
                    }

                    let n = processed.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1;
                    let _ = tx.send(NetworkProgress {
                        bookmark_id: id,
                        processed: n,
                        total,
                        status,
                        bookmark_title: Some(if title.is_empty() { url.clone() } else { title }),
                        new_title,
                        description,
                    }).await;
                }
            })
            .buffer_unordered(concurrency)
            .collect::<()>()
            .await;

        let _ = tx.send(NetworkProgress {
            bookmark_id: String::new(),
            processed: total,
            total,
            status: "done".to_string(),
            bookmark_title: None,
            new_title: None,
            description: None,
        }).await;
    });

    let stream = tokio_stream::wrappers::ReceiverStream::new(rx).map(|p| {
        let data = serde_json::to_string(&p).unwrap_or_default();
        Ok::<Event, std::convert::Infallible>(Event::default().data(data))
    });
    Sse::new(stream).keep_alive(axum::response::sse::KeepAlive::default())
}

async fn network_fetch_preview(
    State(state): State<AppState>,
    Json(body): Json<NetworkBatchBody>,
) -> Sse<impl futures_util::Stream<Item = Result<Event, std::convert::Infallible>>> {
    let (tx, rx) = tokio::sync::mpsc::channel::<NetworkProgress>(32);
    let client = state.inner.http_client.clone();

    let urls: Vec<(String, String, String)> = {
        let root = state.inner.root.read().await;
        body.bookmark_ids
            .iter()
            .filter_map(|id| {
                let (path, idx) = nbm_core::tree::locate_bookmark(&root, id)?;
                let folder = nbm_core::tree::find_folder(&root, &path)?;
                let bm = folder.children.get(idx)?;
                Some((id.clone(), bm.url.clone(), bm.title.clone()))
            })
            .collect()
    };
    // See network_fix_titles: total must match urls.len(), not the requested
    // id count, so the "done" event aligns with the actual processed count.
    let total = urls.len();

    let db = state.inner.db.clone();
    tokio::spawn(async move {
        for (i, (id, url, bm_title)) in urls.iter().enumerate() {
            let result = fetch_url_meta(&client, url).await;
            let (title, description, status) = match result {
                Ok((t, d)) => (Some(t), Some(d), "ok".to_string()),
                Err(e) => (None, None, format!("error: {e}")),
            };

            if status == "ok" {
                // description → Node tree (bookmarks.html に保存)
                if let Some(ref desc) = description {
                    let mut root = state.inner.root.write().await;
                    if let Some((path, idx)) = nbm_core::tree::locate_bookmark(&root, id) {
                        if let Some(folder) = nbm_core::tree::find_folder_mut(&mut root, &path) {
                            if let Some(bm) = folder.children.get_mut(idx) {
                                bm.description = desc.clone();
                            }
                        }
                    }
                    *state.inner.dirty.write().await = true;
                }
                // fetched_title → bookmark_meta DB (揮発性、HTML には書かない)
                if let (Some(ref t), Some(ref db)) = (&title, &db) {
                    if !t.is_empty() {
                        let _ = db.save_meta(id, t);
                    }
                }
            }

            let _ = tx.send(NetworkProgress {
                bookmark_id: id.clone(),
                processed: i + 1,
                total,
                status,
                bookmark_title: Some(if bm_title.is_empty() { url.clone() } else { bm_title.clone() }),
                new_title: title,
                description,
            }).await;
        }
        let _ = tx.send(NetworkProgress {
            bookmark_id: String::new(),
            processed: total, total,
            status: "done".to_string(),
            bookmark_title: None, new_title: None, description: None,
        }).await;
    });

    let stream = tokio_stream::wrappers::ReceiverStream::new(rx).map(|p| {
        Ok::<Event, std::convert::Infallible>(
            Event::default().data(serde_json::to_string(&p).unwrap_or_default()),
        )
    });
    Sse::new(stream).keep_alive(axum::response::sse::KeepAlive::default())
}

async fn fetch_url_meta(client: &reqwest::Client, url: &str) -> Result<(String, String), String> {
    let mut last_err = String::new();
    for attempt in 0..3u32 {
        match client.get(url).send().await {
            Ok(resp) => {
                let status = resp.status().as_u16();
                if status == 404 {
                    return Err("404 Not Found".into());
                }
                if !resp.status().is_success() {
                    last_err = format!("HTTP {status}");
                    if attempt < 2 {
                        tokio::time::sleep(std::time::Duration::from_millis(500 * (1 << attempt))).await;
                    }
                    continue;
                }
                // Content-Type ヘッダの charset を取得
                let ct_charset = resp.headers()
                    .get(reqwest::header::CONTENT_TYPE)
                    .and_then(|v| v.to_str().ok())
                    .and_then(|s| {
                        let lower = s.to_lowercase();
                        let pos = lower.find("charset=")?;
                        Some(lower[pos + 8..].trim_matches('"').trim().to_string())
                    });

                let bytes = resp.bytes().await.map_err(|e| e.to_string())?;

                // HTML の <meta charset> / <meta http-equiv content-type> を確認
                // まず UTF-8 としてデコードして charset 宣言を探す
                let sniff = String::from_utf8_lossy(&bytes[..bytes.len().min(2048)]).to_lowercase();
                let html_charset = extract_html_charset(&sniff);
                let charset = ct_charset.or(html_charset).unwrap_or_else(|| "utf-8".into());

                let text = decode_bytes(&bytes, &charset);
                let (title, desc) = extract_meta(&text);
                return Ok((title, desc));
            }
            Err(e) => {
                last_err = e.to_string();
                if attempt < 2 {
                    tokio::time::sleep(std::time::Duration::from_millis(500 * (1 << attempt))).await;
                }
            }
        }
    }
    Err(last_err)
}

/// HTML の先頭付近から charset 宣言を抽出する。
fn extract_html_charset(sniff: &str) -> Option<String> {
    // <meta charset="utf-8">
    if let Some(pos) = sniff.find("charset=\"") {
        let rest = &sniff[pos + 9..];
        let end = rest.find('"')?;
        return Some(rest[..end].trim().to_string());
    }
    // <meta charset='utf-8'>
    if let Some(pos) = sniff.find("charset='") {
        let rest = &sniff[pos + 9..];
        let end = rest.find('\'')?;
        return Some(rest[..end].trim().to_string());
    }
    // <meta http-equiv="content-type" content="text/html; charset=shift_jis">
    if let Some(pos) = sniff.find("charset=") {
        let rest = &sniff[pos + 8..].trim_start_matches('"');
        let end = rest.find(|c: char| c == '"' || c == '\'' || c == ';' || c == '>')?;
        return Some(rest[..end].trim().to_string());
    }
    None
}

/// バイト列を指定 charset でデコードする。
/// Shift_JIS / EUC-JP は encoding_rs で変換し、それ以外は UTF-8 ロスレスフォールバック。
fn decode_bytes(bytes: &[u8], charset: &str) -> String {
    let label = charset.to_lowercase();
    let label = label.trim();
    // encoding_rs が対応している名前に正規化
    let enc = encoding_rs::Encoding::for_label(label.as_bytes());
    if let Some(enc) = enc {
        let (text, _, _) = enc.decode(bytes);
        return text.into_owned();
    }
    String::from_utf8_lossy(bytes).into_owned()
}

// --- Link check (SSE) -------------------------------------------------------

#[derive(Serialize, Clone)]
struct LinkCheckProgress {
    bookmark_id: String,
    processed: usize,
    total: usize,
    /// "ok" | "skip" | "dead" | "timeout" | "done"
    result: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    bookmark_title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    detail: Option<String>,
}

/// Load exclude_patterns from [LinkCheck] dedupe_exclude_patterns in config.ini.
/// Entries are glob-style prefixes/substrings matched against the URL.
fn load_linkcheck_excludes(state: &AppState) -> Vec<String> {
    state.inner.config_ini_path.as_ref()
        .and_then(|p| nbm_core::ConfigManager::load(p).ok())
        .and_then(|cfg| cfg.get("LinkCheck", "exclude_patterns"))
        .map(|v| v.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect())
        .unwrap_or_else(|| vec![
            "file://".into(),
            "javascript:".into(),
            "about:".into(),
        ])
}

/// Parallelism for title/description fetches. Reads [Network].concurrency,
/// falls back to [LinkCheck].concurrency, then 5. Clamped to 1..=20.
fn load_fetch_concurrency(state: &AppState) -> usize {
    let n = state.inner.config_ini_path.as_ref()
        .and_then(|p| nbm_core::ConfigManager::load(p).ok())
        .and_then(|cfg| {
            cfg.get("Network", "concurrency")
                .or_else(|| cfg.get("LinkCheck", "concurrency"))
                .and_then(|v| v.trim().parse::<usize>().ok())
        })
        .unwrap_or(5);
    n.clamp(1, 20)
}

fn url_is_excluded(url: &str, excludes: &[String]) -> bool {
    let lower = url.to_lowercase();
    excludes.iter().any(|pat| {
        let p = pat.to_lowercase();
        // Wildcard prefix: "192.168.*" → match start
        if let Some(prefix) = p.strip_suffix(".*") {
            lower.contains(prefix.trim_start_matches("http://").trim_start_matches("https://"))
        } else {
            lower.contains(p.as_str())
        }
    })
}

async fn check_url(client: &reqwest::Client, url: &str, timeout_secs: u64)
    -> (&'static str, String)
{
    let timeout = std::time::Duration::from_secs(timeout_secs);
    // Try HEAD first (lightweight), fall back to GET on method-not-allowed.
    let result = client
        .head(url)
        .timeout(timeout)
        .send()
        .await;
    let status = match result {
        Err(e) if e.is_timeout() => return ("timeout", "タイムアウト".into()),
        Err(e) => {
            // Connection refused / DNS failure → dead
            return ("dead", e.to_string());
        }
        Ok(r) => r.status().as_u16(),
    };
    if status == 405 || status == 501 {
        // Server doesn't support HEAD — retry with GET (no body read)
        let g = client.get(url).timeout(timeout).send().await;
        match g {
            Err(e) if e.is_timeout() => return ("timeout", "タイムアウト".into()),
            Err(e) => return ("dead", e.to_string()),
            Ok(r) => {
                let s = r.status().as_u16();
                if s < 400 { ("ok", format!("HTTP {s}")) }
                else { ("dead", format!("HTTP {s}")) }
            }
        }
    } else if status < 400 {
        ("ok", format!("HTTP {status}"))
    } else {
        ("dead", format!("HTTP {status}"))
    }
}

async fn network_link_check(
    State(state): State<AppState>,
    Json(body): Json<NetworkBatchBody>,
) -> Sse<impl futures_util::Stream<Item = Result<Event, std::convert::Infallible>>> {
    let (tx, rx) = tokio::sync::mpsc::channel::<LinkCheckProgress>(64);
    let client = state.inner.http_client.clone();
    let excludes = load_linkcheck_excludes(&state);

    // Read timeout / concurrency from config
    let (timeout_secs, concurrency) = state.inner.config_ini_path.as_ref()
        .and_then(|p| nbm_core::ConfigManager::load(p).ok())
        .map(|cfg| {
            let t = cfg.get("LinkCheck", "timeout_secs")
                .and_then(|v| v.parse().ok()).unwrap_or(5u64);
            let c = cfg.get("LinkCheck", "concurrency")
                .and_then(|v| v.parse().ok()).unwrap_or(5usize);
            (t, c)
        })
        .unwrap_or((10, 5));

    let items: Vec<(String, String, String)> = {
        let root = state.inner.root.read().await;
        body.bookmark_ids.iter()
            .filter_map(|id| {
                let (path, idx) = nbm_core::tree::locate_bookmark(&root, id)?;
                let folder = nbm_core::tree::find_folder(&root, &path)?;
                let bm = folder.children.get(idx)?;
                Some((id.clone(), bm.url.clone(), bm.title.clone()))
            })
            .collect()
    };
    let total = items.len();

    tokio::spawn(async move {
        use futures_util::StreamExt as _;
        let processed = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));

        futures_util::stream::iter(items)
            .map(|(id, url, title)| {
                let client = client.clone();
                let excludes = excludes.clone();
                let tx = tx.clone();
                let processed = processed.clone();
                async move {
                    let (result, detail) = if url.is_empty() {
                        ("skip", "URL なし".to_string())
                    } else if url_is_excluded(&url, &excludes) {
                        ("skip", "除外パターン".to_string())
                    } else {
                        check_url(&client, &url, timeout_secs).await
                    };
                    let n = processed.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1;
                    let _ = tx.send(LinkCheckProgress {
                        bookmark_id: id,
                        processed: n,
                        total,
                        result: result.to_string(),
                        bookmark_title: Some(if title.is_empty() { url.clone() } else { title }),
                        url: Some(url),
                        detail: Some(detail),
                    }).await;
                }
            })
            .buffer_unordered(concurrency)
            .collect::<()>()
            .await;

        let _ = tx.send(LinkCheckProgress {
            bookmark_id: String::new(),
            processed: total,
            total,
            result: "done".to_string(),
            bookmark_title: None,
            url: None,
            detail: None,
        }).await;
    });

    let stream = tokio_stream::wrappers::ReceiverStream::new(rx).map(|p| {
        let data = serde_json::to_string(&p).unwrap_or_default();
        Ok::<Event, std::convert::Infallible>(Event::default().data(data))
    });
    Sse::new(stream).keep_alive(axum::response::sse::KeepAlive::default())
}

#[derive(Serialize)]
struct ProxyCheckResp {
    configured: bool,
    url: Option<String>,
    reachable: bool,
    message: String,
}

async fn network_proxy_check(State(state): State<AppState>) -> Json<ProxyCheckResp> {
    // Read proxy config.
    let proxy_url = state.inner.config_ini_path.as_ref().and_then(|p| {
        nbm_core::ConfigManager::load(p).ok()?.get("Proxy", "url")
    });
    let Some(url) = proxy_url else {
        return Json(ProxyCheckResp {
            configured: false,
            url: None,
            reachable: false,
            message: "プロキシ設定なし".into(),
        });
    };
    // Quick connectivity check.
    let reachable = state
        .inner
        .http_client
        .get("https://www.google.com")
        .timeout(std::time::Duration::from_secs(5))
        .send()
        .await
        .map(|r| r.status().is_success() || r.status().as_u16() < 500)
        .unwrap_or(false);
    Json(ProxyCheckResp {
        configured: true,
        url: Some(url),
        reachable,
        message: if reachable { "接続 OK".into() } else { "接続失敗".into() },
    })
}

// --- Organize handlers -----------------------------------------------------

/// Read [Organize] dedupe_exclude_urls from config.ini.
/// Value is a comma-separated list of URLs to never treat as duplicates.
fn load_dedupe_exclude_urls(state: &AppState) -> std::collections::HashSet<String> {
    state.inner.config_ini_path.as_ref()
        .and_then(|p| nbm_core::ConfigManager::load(p).ok())
        .and_then(|cfg| cfg.get("Organize", "dedupe_exclude_urls"))
        .map(|v| v.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect())
        .unwrap_or_default()
}

#[derive(Deserialize)]
struct DedupeBody {
    folder_path: String,
}

#[derive(Serialize)]
struct OrganizeResp {
    ok: bool,
    count: usize,
}

async fn organize_dedupe(
    State(state): State<AppState>,
    Json(body): Json<DedupeBody>,
) -> Result<Json<OrganizeResp>, (StatusCode, Json<ApiError>)> {
    let exclude = load_dedupe_exclude_urls(&state);
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    let count = organize::dedupe_folder(&mut root, &body.folder_path, &exclude)
        .map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
    Ok(Json(OrganizeResp { ok: true, count }))
}

#[derive(Deserialize)]
struct MergeDupFoldersBody {
    parent_path: String,
}

async fn organize_merge_dup_folders(
    State(state): State<AppState>,
    Json(body): Json<MergeDupFoldersBody>,
) -> Result<Json<OrganizeResp>, (StatusCode, Json<ApiError>)> {
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    let count = organize::merge_duplicate_folders(&mut root, &body.parent_path)
        .map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
    Ok(Json(OrganizeResp { ok: true, count }))
}

#[derive(Serialize)]
struct DomainStatsResp {
    stats: Vec<DomainStat>,
}

#[derive(Serialize)]
struct DomainStat {
    domain: String,
    count: usize,
}

async fn organize_domain_stats(State(state): State<AppState>) -> Json<DomainStatsResp> {
    let root = state.inner.root.read().await;
    let stats = organize::domain_statistics(&root)
        .into_iter()
        .map(|(domain, count)| DomainStat { domain, count })
        .collect();
    Json(DomainStatsResp { stats })
}

#[derive(Deserialize)]
struct ConsolidateDomainBody {
    domain: String,
    target_folder: Option<String>,
    /// If set, only bookmarks inside this folder path are considered.
    scope_path: Option<String>,
    /// If set, only bookmarks whose title contains this keyword (case-insensitive) are matched.
    keyword: Option<String>,
    /// Folder names to leave untouched — used when issuing several consolidation
    /// passes in a row (one per keyword rule, then a catch-all) so a later pass
    /// doesn't re-absorb folders an earlier pass already created for this domain.
    #[serde(default)]
    exclude_target_names: Vec<String>,
}

async fn organize_consolidate_domain(
    State(state): State<AppState>,
    Json(body): Json<ConsolidateDomainBody>,
) -> Result<Json<OrganizeResp>, (StatusCode, Json<ApiError>)> {
    let folder_name = body.target_folder.unwrap_or_else(|| body.domain.clone());
    let scope = body.scope_path.as_deref();
    let keyword = body.keyword.as_deref().map(|k| k.trim().to_lowercase());
    let tags_map = match &state.inner.db {
        Some(db) => db.get_all_tags_map().unwrap_or_default(),
        None => std::collections::HashMap::new(),
    };
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    let count = organize::consolidate_by_domain(
        &mut root,
        &body.domain,
        &folder_name,
        scope,
        keyword.as_deref(),
        &tags_map,
        &body.exclude_target_names,
    )
        .map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
    Ok(Json(OrganizeResp { ok: true, count }))
}

#[derive(Deserialize)]
struct SortByDomainBody {
    folder_path: String,
}

async fn organize_sort_by_domain(
    State(state): State<AppState>,
    Json(body): Json<SortByDomainBody>,
) -> Result<Json<OrganizeResp>, (StatusCode, Json<ApiError>)> {
    push_undo(&state).await;
    let mut root = state.inner.root.write().await;
    let count = organize::sort_by_domain(&mut root, &body.folder_path)
        .map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
    Ok(Json(OrganizeResp { ok: true, count }))
}

// --- Autotag handler (SSE) -------------------------------------------------

#[derive(Deserialize)]
struct AutotagBody {
    bookmark_ids: Vec<String>,
    // allow_network kept for API compatibility but ignored (Tier2 removed)
    #[serde(default)]
    allow_network: bool,
}

#[derive(Serialize, Clone)]
struct AutotagProgress {
    bookmark_id: String,
    processed: usize,
    total: usize,
    status: String,
    tags: Vec<String>,
}

async fn autotag_local(
    State(state): State<AppState>,
    Json(body): Json<AutotagBody>,
) -> Sse<impl futures_util::Stream<Item = Result<Event, std::convert::Infallible>>> {
    let (tx, rx) = tokio::sync::mpsc::channel::<AutotagProgress>(32);

    // Collect (id, url, title, description) from tree
    let items: Vec<(String, String, String, String)> = {
        let root = state.inner.root.read().await;
        body.bookmark_ids
            .iter()
            .filter_map(|id| {
                let (path, idx) = nbm_core::tree::locate_bookmark(&root, id)?;
                let folder = nbm_core::tree::find_folder(&root, &path)?;
                let bm = folder.children.get(idx)?;
                Some((id.clone(), bm.url.clone(), bm.title.clone(), bm.description.clone()))
            })
            .collect()
    };
    // total = items.len(): ids that fail to resolve in the tree are dropped
    // from `items`, so the "done" event must match the actual processed count.
    let total = items.len();

    // Bulk-fetch fetched_titles from DB
    let fetched_titles = state.inner.db.as_ref()
        .and_then(|db| db.get_meta_bulk(&body.bookmark_ids).ok())
        .unwrap_or_default();

    let db = state.inner.db.clone();

    tokio::spawn(async move {
        for (i, (id, url, title, description)) in items.iter().enumerate() {
            let fetched = fetched_titles.get(id).map(String::as_str);
            let bm_text = autotag::BookmarkText {
                url,
                title,
                description,
                fetched_title: fetched,
            };
            let tags = autotag::generate_tags(&bm_text);
            if let Some(ref db) = db {
                let _ = db.save_tags_for_url(id, &tags, "rule", None);
            }
            let _ = tx.send(AutotagProgress {
                bookmark_id: id.clone(),
                processed: i + 1,
                total,
                status: "ok".into(),
                tags,
            }).await;
        }
        let _ = tx.send(AutotagProgress {
            bookmark_id: String::new(),
            processed: total,
            total,
            status: "done".into(),
            tags: Vec::new(),
        }).await;
    });

    let stream = tokio_stream::wrappers::ReceiverStream::new(rx).map(|p| {
        Ok::<Event, std::convert::Infallible>(
            Event::default().data(serde_json::to_string(&p).unwrap_or_default()),
        )
    });
    Sse::new(stream).keep_alive(axum::response::sse::KeepAlive::default())
}

// --- Classify helpers ------------------------------------------------------ //

#[derive(serde::Deserialize)]
struct GeminiResponse {
    candidates: Vec<GeminiCandidate>,
}

#[derive(serde::Deserialize)]
struct GeminiCandidate {
    content: GeminiContent,
}

#[derive(serde::Deserialize)]
struct GeminiContent {
    parts: Vec<GeminiPart>,
}

#[derive(serde::Deserialize)]
struct GeminiPart {
    text: String,
}

#[derive(serde::Deserialize)]
struct MovesResponse {
    moves: Vec<RawMove>,
}

#[derive(serde::Deserialize)]
struct RawMove {
    index: usize,
    folder: String,
    confidence: f64,
    reason: String,
}

fn extract_gemini_json(text: &str) -> Option<String> {
    let t = text.trim();
    let start = t.find('{')?;
    let end = t.rfind('}')?;
    if end > start { Some(t[start..=end].to_string()) } else { None }
}

/// Pull the human-readable `error.message` out of a Gemini API error body,
/// e.g. `{"error":{"code":400,"message":"API key not valid.","status":"INVALID_ARGUMENT"}}`.
fn extract_gemini_error_message(body: &str) -> Option<String> {
    #[derive(Deserialize)]
    struct ErrBody { error: ErrDetail }
    #[derive(Deserialize)]
    struct ErrDetail { message: Option<String>, status: Option<String> }
    let parsed: ErrBody = serde_json::from_str(body).ok()?;
    match (parsed.error.status, parsed.error.message) {
        (Some(s), Some(m)) => Some(format!("{s}: {m}")),
        (None, Some(m)) => Some(m),
        (Some(s), None) => Some(s),
        (None, None) => None,
    }
}

/// Gemini 429 (RESOURCE_EXHAUSTED) messages end with e.g. "Please retry in
/// 23.556131354s." — parse that out so we can wait the suggested amount
/// instead of guessing with a short fixed backoff that just gets rejected
/// again.
fn parse_retry_after_secs(msg: &str) -> Option<f64> {
    let lower = msg.to_lowercase();
    let idx = lower.find("retry in ")?;
    let rest = &msg[idx + "retry in ".len()..];
    let end = rest.find('s')?;
    rest[..end].trim().parse::<f64>().ok()
}

async fn call_gemini_batch(
    client: &reqwest::Client,
    api_key: &str,
    model: &str,
    prompt: &str,
    batch: &[ai_classify::BookmarkItem],
    sanitize_urls: bool,
    fields: ai_classify::FieldSelection,
) -> Result<Vec<ai_classify::AiMove>, String> {
    use ai_classify::AiMove;

    // Truncate to at most `max` chars on a UTF-8 boundary (avoids panics on
    // multibyte text like Japanese).
    fn truncate_chars(s: &str, max: usize) -> String {
        s.chars().take(max).collect()
    }

    let items: Vec<serde_json::Value> = batch
        .iter()
        .enumerate()
        .map(|(i, b)| {
            // domain is always derived (cheap, high-signal).
            let domain = {
                let after = b.url.strip_prefix("https://")
                    .or_else(|| b.url.strip_prefix("http://"))
                    .unwrap_or(&b.url);
                let netloc = after.split('/').next().unwrap_or("").to_lowercase();
                let netloc = netloc.split(':').next().unwrap_or("").to_string();
                netloc.strip_prefix("www.").map(str::to_string).unwrap_or(netloc)
            };
            let mut obj = serde_json::Map::new();
            obj.insert("index".into(), serde_json::json!(i));
            obj.insert("domain".into(), serde_json::json!(domain));
            if fields.title {
                obj.insert("title".into(), serde_json::json!(truncate_chars(&b.title, 150)));
            }
            if fields.url {
                let url_san = if sanitize_urls {
                    b.url.split_once('?').map(|(p, _)| p.to_string())
                        .unwrap_or_else(|| b.url.clone())
                } else {
                    b.url.clone()
                };
                obj.insert("url".into(), serde_json::json!(url_san));
            }
            if fields.tags && !b.tags.is_empty() {
                obj.insert("tags".into(), serde_json::json!(b.tags));
            }
            if fields.description && !b.description.is_empty() {
                obj.insert("description".into(),
                    serde_json::json!(truncate_chars(&b.description, 300)));
            }
            serde_json::Value::Object(obj)
        })
        .collect();

    let data_json = serde_json::to_string(&serde_json::json!({"bookmarks": items}))
        .map_err(|e| e.to_string())?;
    let full_prompt = format!("{prompt}\n\n{data_json}");
    let endpoint = format!(
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    );

    let mut last_err = String::from("no response");
    for json_retry in 0..3u8 {
        let prompt_text = if json_retry == 0 {
            full_prompt.clone()
        } else {
            format!(
                "{full_prompt}\n\nYour previous output did not match the required schema. \
                 The top-level JSON object MUST have a \"moves\" key whose value is an array, \
                 e.g. {{\"moves\":[{{\"index\":0,\"folder\":\"FolderName\",\"confidence\":0.9,\"reason\":\"...\"}}]}}. \
                 Output ONLY that JSON object, nothing else."
            )
        };
        let req_body = serde_json::json!({
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        });

        let resp = match client
            .post(&endpoint)
            .json(&req_body)
            .timeout(std::time::Duration::from_secs(60))
            .send()
            .await
        {
            Ok(r) => r,
            Err(e) => { last_err = e.to_string(); continue; }
        };

        let status = resp.status();
        let status_code = status.as_u16();
        if !status.is_success() {
            // Gemini's error body (e.g. `{"error":{"message":"API key not
            // valid","status":"INVALID_ARGUMENT"}}`) is far more diagnostic
            // than the bare status code — surface it instead of discarding it.
            let body = resp.text().await.unwrap_or_default();
            let detail = extract_gemini_error_message(&body)
                .unwrap_or_else(|| truncate_chars(&body, 300));
            let msg = if detail.is_empty() {
                format!("HTTP {status_code}")
            } else {
                format!("HTTP {status_code}: {detail}")
            };
            // Don't loop back into the JSON-format retry here: that would fire
            // another request immediately, doubling up on whatever rate limit
            // or outage just rejected us. Return so the caller's backoff
            // (which can honor the server's suggested retry delay) applies
            // before anything is sent again.
            return Err(msg);
        }

        let text: String = match resp.text().await {
            Ok(t) => t,
            Err(e) => { last_err = e.to_string(); continue; }
        };

        let raw_text = serde_json::from_str::<GeminiResponse>(&text)
            .ok()
            .and_then(|g| g.candidates.into_iter().next())
            .and_then(|c| c.content.parts.into_iter().next())
            .map(|p| p.text)
            .unwrap_or_else(|| text.clone());

        let json_str = match extract_gemini_json(&raw_text) {
            Some(s) => s,
            None => { last_err = "no JSON in response".into(); continue; }
        };

        // The model is instructed to return {"moves":[...]}, but occasionally
        // drops the wrapper and returns the bare array instead. Accept both
        // shapes rather than failing the whole chunk over a missing key.
        let raw_moves: Result<Vec<RawMove>, serde_json::Error> =
            serde_json::from_str::<MovesResponse>(&json_str)
                .map(|m| m.moves)
                .or_else(|_| serde_json::from_str::<Vec<RawMove>>(&json_str));

        match raw_moves {
            Ok(moves) => {
                let moves = moves.into_iter().filter_map(|m| {
                    if m.index >= batch.len() { return None; }
                    let folder = m.folder.trim().replace('/', "_");
                    if folder.is_empty() { return None; }
                    Some(AiMove {
                        bookmark_id: batch[m.index].bookmark_id.clone(),
                        folder,
                        confidence: m.confidence.clamp(0.0, 1.0),
                        reason: m.reason,
                    })
                }).collect();
                return Ok(moves);
            }
            Err(e) => { last_err = format!("JSON parse: {e}"); continue; }
        }
    }
    Err(last_err)
}

// --- Classify handlers ----------------------------------------------------- //

#[derive(Deserialize)]
struct ClassifyAiBody {
    bookmark_ids: Vec<String>,
    custom_prompt: Option<String>,
    #[serde(default = "default_chunk_size")]
    chunk_size: usize,
    #[serde(default = "default_model")]
    model: String,
    #[serde(default = "bool_true")]
    sanitize_urls: bool,
    /// Which fields to send to the model. Omitted entries default to false,
    /// except an entirely missing object falls back to FieldSelection::default.
    #[serde(default)]
    fields: Option<FieldSelectionBody>,
}

#[derive(Deserialize)]
struct FieldSelectionBody {
    #[serde(default = "bool_true")]
    title: bool,
    #[serde(default = "bool_true")]
    url: bool,
    #[serde(default = "bool_true")]
    tags: bool,
    #[serde(default)]
    description: bool,
}

impl From<&FieldSelectionBody> for ai_classify::FieldSelection {
    fn from(b: &FieldSelectionBody) -> Self {
        Self { title: b.title, url: b.url, tags: b.tags, description: b.description }
    }
}

fn default_chunk_size() -> usize { 40 }
fn default_model() -> String { "gemini-2.5-flash-lite".to_string() }
fn bool_true() -> bool { true }

/// Load (input, output) USD price per 1M tokens from config.ini [AI].
/// Returns `Some(price)` only when the value parses to a number > 0.
fn load_ai_pricing(state: &AppState) -> (Option<f64>, Option<f64>) {
    let cfg = state.inner.config_ini_path.as_ref()
        .and_then(|p| nbm_core::ConfigManager::load(p).ok());
    let read = |key: &str| cfg.as_ref()
        .and_then(|c| c.get("AI", key))
        .and_then(|s| s.trim().parse::<f64>().ok())
        .filter(|&v| v > 0.0);
    (read("input_cost_per_1m_tokens"), read("output_cost_per_1m_tokens"))
}

/// Resolve the Gemini API key (env vars take precedence, then config.ini [API].api_key).
/// A placeholder/empty value counts as "not set".
fn resolve_api_key(state: &AppState) -> Option<String> {
    state.inner.config_ini_path.as_ref()
        .and_then(|p| nbm_core::ConfigManager::load(p).ok())
        .and_then(|c| c.get_api_key())
        .or_else(|| std::env::var("GENAI_API_KEY").ok())
        .or_else(|| std::env::var("GOOGLE_API_KEY").ok())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty() && !s.starts_with('<'))
}

/// Build the BookmarkItem payload for the given ids (shared by estimate + run).
async fn build_classify_items(
    state: &AppState,
    bookmark_ids: &[String],
    fields: ai_classify::FieldSelection,
) -> Vec<ai_classify::BookmarkItem> {
    use ai_classify::BookmarkItem;

    let fetched_titles = state.inner.db.as_ref()
        .and_then(|db| db.get_meta_bulk(bookmark_ids).ok())
        .unwrap_or_default();

    let tags_map = if fields.tags {
        state.inner.db.as_ref()
            .and_then(|db| db.get_all_tags_map().ok())
            .unwrap_or_default()
    } else {
        std::collections::HashMap::new()
    };

    let root = state.inner.root.read().await;
    bookmark_ids.iter().filter_map(|id| {
        let (path, idx) = nbm_core::tree::locate_bookmark(&root, id)?;
        let folder = nbm_core::tree::find_folder(&root, &path)?;
        let bm = folder.children.get(idx)?;
        let title = if bm.title.is_empty() {
            fetched_titles.get(id).cloned().unwrap_or_default()
        } else {
            bm.title.clone()
        };
        let tags = tags_map.get(id)
            .map(|s| s.split(' ').filter(|t| !t.is_empty()).map(str::to_string).collect())
            .unwrap_or_default();
        let description = if fields.description { bm.description.clone() } else { String::new() };
        Some(BookmarkItem { bookmark_id: id.clone(), title, url: bm.url.clone(), tags, description })
    }).collect()
}

// --- Config (settings) handlers --------------------------------------------- //

#[derive(Serialize)]
struct AiStatusResp {
    /// Whether a usable API key is configured (never returns the key itself).
    api_key_set: bool,
    /// Where the key came from: "env" | "config" | "none".
    api_key_source: String,
    /// Whether both input & output prices are set (> 0) — required to run AI.
    pricing_set: bool,
    input_cost_per_1m: Option<f64>,
    output_cost_per_1m: Option<f64>,
    model: String,
}

async fn config_ai_status(State(state): State<AppState>) -> Json<AiStatusResp> {
    let env_key = std::env::var("GENAI_API_KEY").ok()
        .or_else(|| std::env::var("GOOGLE_API_KEY").ok())
        .filter(|s| !s.trim().is_empty());
    let cfg = state.inner.config_ini_path.as_ref()
        .and_then(|p| nbm_core::ConfigManager::load(p).ok());
    let cfg_key = cfg.as_ref()
        .and_then(|c| c.get("API", "api_key"))
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty() && !s.starts_with('<'));

    let (source, set) = if env_key.is_some() {
        ("env".to_string(), true)
    } else if cfg_key.is_some() {
        ("config".to_string(), true)
    } else {
        ("none".to_string(), false)
    };

    let (in_price, out_price) = load_ai_pricing(&state);
    let model = cfg.as_ref()
        .and_then(|c| c.get("AI", "model"))
        .unwrap_or_else(default_model);

    Json(AiStatusResp {
        api_key_set: set,
        api_key_source: source,
        pricing_set: in_price.is_some() && out_price.is_some(),
        input_cost_per_1m: in_price,
        output_cost_per_1m: out_price,
        model,
    })
}

#[derive(Deserialize)]
struct SetApiKeyBody {
    api_key: String,
}

#[derive(Serialize)]
struct SetApiKeyResp {
    ok: bool,
    message: String,
}

async fn config_set_api_key(
    State(state): State<AppState>,
    Json(body): Json<SetApiKeyBody>,
) -> Json<SetApiKeyResp> {
    let key = body.api_key.trim();
    if key.is_empty() {
        return Json(SetApiKeyResp { ok: false, message: "APIキーが空です".into() });
    }
    let Some(path) = state.inner.config_ini_path.clone() else {
        return Json(SetApiKeyResp { ok: false, message: "config.ini のパスが未設定です".into() });
    };
    let mut cfg = match nbm_core::ConfigManager::load(&path) {
        Ok(c) => c,
        Err(e) => return Json(SetApiKeyResp { ok: false, message: format!("config 読込失敗: {e}") }),
    };
    match cfg.set("API", "api_key", key) {
        Ok(()) => Json(SetApiKeyResp { ok: true, message: "APIキーを保存しました".into() }),
        Err(e) => Json(SetApiKeyResp { ok: false, message: format!("保存失敗: {e}") }),
    }
}

#[derive(Deserialize)]
struct SetAiPricingBody {
    /// Model id (config.ini [AI].model). Omitted/empty leaves the current model untouched.
    model: Option<String>,
    input_cost_per_1m: f64,
    output_cost_per_1m: f64,
}

/// Save model + USD/1M-token pricing (config.ini [AI]) from the AI settings UI,
/// so users don't have to hand-edit config.ini to clear the cost-approval gate.
async fn config_set_ai_pricing(
    State(state): State<AppState>,
    Json(body): Json<SetAiPricingBody>,
) -> Json<SetApiKeyResp> {
    if !(body.input_cost_per_1m > 0.0) || !(body.output_cost_per_1m > 0.0) {
        return Json(SetApiKeyResp { ok: false, message: "単価は0より大きい値を入力してください".into() });
    }
    let Some(path) = state.inner.config_ini_path.clone() else {
        return Json(SetApiKeyResp { ok: false, message: "config.ini のパスが未設定です".into() });
    };
    let mut cfg = match nbm_core::ConfigManager::load(&path) {
        Ok(c) => c,
        Err(e) => return Json(SetApiKeyResp { ok: false, message: format!("config 読込失敗: {e}") }),
    };
    if let Some(model) = body.model.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        if let Err(e) = cfg.set("AI", "model", model) {
            return Json(SetApiKeyResp { ok: false, message: format!("保存失敗: {e}") });
        }
    }
    if let Err(e) = cfg.set("AI", "input_cost_per_1m_tokens", &body.input_cost_per_1m.to_string()) {
        return Json(SetApiKeyResp { ok: false, message: format!("保存失敗: {e}") });
    }
    match cfg.set("AI", "output_cost_per_1m_tokens", &body.output_cost_per_1m.to_string()) {
        Ok(()) => Json(SetApiKeyResp { ok: true, message: "コスト単価を保存しました".into() }),
        Err(e) => Json(SetApiKeyResp { ok: false, message: format!("保存失敗: {e}") }),
    }
}

#[derive(Serialize)]
struct ModelsResp {
    /// The currently selected model id (config.ini [AI].model).
    current: String,
    /// Raw models.json content passed through verbatim, or null if unavailable.
    catalog: Option<serde_json::Value>,
    /// Set when models.json could not be read/parsed (UI falls back gracefully).
    error: Option<String>,
}

/// Return the model price catalog (config/models.json) for display in the UI.
/// The file lives next to config.ini; falls back to ./config/models.json.
async fn config_models(State(state): State<AppState>) -> Json<ModelsResp> {
    let cfg = state.inner.config_ini_path.as_ref()
        .and_then(|p| nbm_core::ConfigManager::load(p).ok());
    let current = cfg.as_ref()
        .and_then(|c| c.get("AI", "model"))
        .unwrap_or_else(default_model);

    // Resolve models.json: prefer the directory of config.ini.
    let candidate = state.inner.config_ini_path.as_ref()
        .and_then(|p| p.parent())
        .map(|dir| dir.join("models.json"))
        .filter(|p| p.exists())
        .unwrap_or_else(|| PathBuf::from("config/models.json"));

    match std::fs::read_to_string(&candidate) {
        Ok(text) => match serde_json::from_str::<serde_json::Value>(&text) {
            Ok(v) => Json(ModelsResp { current, catalog: Some(v), error: None }),
            Err(e) => Json(ModelsResp { current, catalog: None, error: Some(format!("models.json パース失敗: {e}")) }),
        },
        Err(e) => Json(ModelsResp { current, catalog: None, error: Some(format!("models.json 読込失敗: {e}")) }),
    }
}

#[derive(Serialize)]
struct EstimateResp {
    /// True only when both an API key and pricing are configured → AI run allowed.
    can_run: bool,
    /// Human-readable reason when can_run is false.
    blocked_reason: Option<String>,
    cost: ai_classify::CostEstimate,
}

async fn classify_estimate(
    State(state): State<AppState>,
    Json(body): Json<ClassifyAiBody>,
) -> Json<EstimateResp> {
    use ai_classify::{build_prompt, estimate_cost};

    let fields: ai_classify::FieldSelection = body.fields.as_ref().map(Into::into).unwrap_or_default();
    let items = build_classify_items(&state, &body.bookmark_ids, fields).await;

    let cfg = state.inner.config_ini_path.as_ref()
        .and_then(|p| nbm_core::ConfigManager::load(p).ok());
    let priority_terms = cfg.as_ref().map(|c| c.get_priority_terms()).unwrap_or_default();
    let prompt = build_prompt(&priority_terms, body.custom_prompt.as_deref());

    let (in_price, out_price) = load_ai_pricing(&state);
    let cost = estimate_cost(&items, prompt.len(), body.chunk_size.max(1), in_price, out_price);

    let key_set = resolve_api_key(&state).is_some();
    let pricing_set = in_price.is_some() && out_price.is_some();
    let blocked_reason = if !key_set {
        Some("APIキーが未設定です。設定からキーを登録してください。".into())
    } else if !pricing_set {
        Some("コスト単価が未設定です。config.ini [AI] の input/output_cost_per_1m_tokens を設定してください。".into())
    } else {
        None
    };

    Json(EstimateResp { can_run: blocked_reason.is_none(), blocked_reason, cost })
}

async fn classify_ai(
    State(state): State<AppState>,
    Json(body): Json<ClassifyAiBody>,
) -> Sse<impl futures_util::Stream<Item = Result<Event, std::convert::Infallible>>> {
    use ai_classify::{build_prompt, enforce_min_group_size, estimate_cost, ClassifyProgress};

    let (tx, rx) = tokio::sync::mpsc::channel::<ClassifyProgress>(64);
    let client = state.inner.http_client.clone();

    let api_key = resolve_api_key(&state);

    let config_mgr = state.inner.config_ini_path.as_ref()
        .and_then(|p| nbm_core::ConfigManager::load(p).ok());
    let priority_terms = config_mgr.as_ref().map(|c| c.get_priority_terms()).unwrap_or_default();
    // Pricing doubles as the cost-approval gate: missing/zero → refuse to run.
    let (in_price, out_price) = load_ai_pricing(&state);

    // Field selection (token vs accuracy). Defaults to the tags-centric set.
    let fields: ai_classify::FieldSelection = body.fields.as_ref()
        .map(Into::into)
        .unwrap_or_default();

    let items = build_classify_items(&state, &body.bookmark_ids, fields).await;

    let chunk_size = body.chunk_size.max(1);
    let model = body.model.clone();
    let custom_prompt = body.custom_prompt.clone();
    let sanitize_urls = body.sanitize_urls;

    tokio::spawn(async move {
        let Some(key) = api_key else {
            let _ = tx.send(ClassifyProgress {
                processed: 0, total: 0, status: "error".into(),
                chunk_moves: None,
                error: Some("APIキーが未設定です。設定からキーを登録してください。".into()),
                cost_estimate: None,
            }).await;
            return;
        };

        // Cost-approval gate: refuse to send anything to Gemini until pricing is configured.
        if in_price.is_none() || out_price.is_none() {
            let _ = tx.send(ClassifyProgress {
                processed: 0, total: 0, status: "error".into(),
                chunk_moves: None,
                error: Some("コスト単価が未設定のため実行をブロックしました。config.ini [AI] の input/output_cost_per_1m_tokens を設定してください。".into()),
                cost_estimate: None,
            }).await;
            return;
        }

        let prompt = build_prompt(&priority_terms, custom_prompt.as_deref());
        let cost = estimate_cost(&items, prompt.len(), chunk_size, in_price, out_price);
        let total = items.len();

        let _ = tx.send(ClassifyProgress {
            processed: 0, total, status: "start".into(),
            chunk_moves: None, error: None, cost_estimate: Some(cost),
        }).await;

        let mut all_moves: Vec<ai_classify::AiMove> = Vec::new();
        let mut processed = 0;

        for batch in items.chunks(chunk_size) {
            let mut last_err = String::new();
            let mut success = false;
            for attempt in 0..3u32 {
                match call_gemini_batch(&client, &key, &model, &prompt, batch, sanitize_urls, fields).await {
                    Ok(moves) => {
                        processed += batch.len();
                        all_moves.extend(moves.clone());
                        let _ = tx.send(ClassifyProgress {
                            processed, total, status: "progress".into(),
                            chunk_moves: Some(moves), error: None, cost_estimate: None,
                        }).await;
                        success = true;
                        break;
                    }
                    Err(e) => {
                        last_err = e.clone();
                        let is_rate_limited = e.contains("429");
                        let retryable = is_rate_limited || e.contains("500")
                            || e.contains("502") || e.contains("503") || e.contains("504");
                        if retryable && attempt < 2 {
                            // Gemini tells us exactly how long to wait on a quota
                            // error (e.g. "Please retry in 23.5s") — a short fixed
                            // backoff just gets rejected again immediately, which
                            // is what was causing repeated 429s here.
                            let wait_secs = parse_retry_after_secs(&e)
                                .map(|s| s + 1.0) // small safety margin
                                .unwrap_or(1.5 * (1u64 << attempt) as f64)
                                .min(90.0);
                            let _ = tx.send(ClassifyProgress {
                                processed, total, status: "waiting".into(),
                                chunk_moves: None,
                                error: Some(if is_rate_limited {
                                    format!("レート制限のため {wait_secs:.0} 秒待機して再送します…")
                                } else {
                                    format!("一時エラーのため {wait_secs:.0} 秒待機して再送します…")
                                }),
                                cost_estimate: None,
                            }).await;
                            tokio::time::sleep(std::time::Duration::from_secs_f64(wait_secs)).await;
                            continue;
                        }
                        break;
                    }
                }
            }
            if !success {
                processed += batch.len();
                let _ = tx.send(ClassifyProgress {
                    processed, total, status: "chunk_error".into(),
                    chunk_moves: None, error: Some(last_err), cost_estimate: None,
                }).await;
            }
        }

        let final_moves = enforce_min_group_size(all_moves);
        let _ = tx.send(ClassifyProgress {
            processed: total, total, status: "done".into(),
            chunk_moves: Some(final_moves), error: None, cost_estimate: None,
        }).await;
    });

    let stream = tokio_stream::wrappers::ReceiverStream::new(rx).map(|p| {
        Ok::<Event, std::convert::Infallible>(
            Event::default().data(serde_json::to_string(&p).unwrap_or_default()),
        )
    });
    Sse::new(stream).keep_alive(axum::response::sse::KeepAlive::default())
}

#[derive(Deserialize)]
struct ApplyMoveItem {
    bookmark_id: String,
    folder_path: String,
}

#[derive(Deserialize)]
struct ClassifyApplyBody {
    moves: Vec<ApplyMoveItem>,
    /// When true, delete source folders left empty by the moves (UI toggle).
    #[serde(default)]
    prune_empty_source: bool,
}

#[derive(Serialize)]
struct ClassifyApplyResp {
    ok: bool,
    applied: usize,
    skipped: usize,
    /// Number of now-empty source folders removed (0 when toggle off).
    #[serde(default)]
    pruned: usize,
}

async fn classify_ai_apply(
    State(state): State<AppState>,
    Json(body): Json<ClassifyApplyBody>,
) -> Result<Json<ClassifyApplyResp>, (StatusCode, Json<ApiError>)> {
    let mut root = state.inner.root.write().await;
    let mut applied = 0usize;
    let mut skipped = 0usize;
    let mut sources: std::collections::HashSet<String> = std::collections::HashSet::new();

    for mv in &body.moves {
        let target = if mv.folder_path.starts_with("/_AI/") {
            mv.folder_path.clone()
        } else {
            format!("/_AI/{}", mv.folder_path.trim_start_matches('/'))
        };
        // Record the bookmark's current folder before moving it.
        if body.prune_empty_source {
            if let Some((src, _)) = tree::locate_bookmark(&root, &mv.bookmark_id) {
                sources.insert(src);
            }
        }
        ai_find_or_create_folder(&mut root, &target);
        match tree::move_bookmark(&mut root, &mv.bookmark_id, &target) {
            Ok(_) => applied += 1,
            Err(_) => skipped += 1,
        }
    }

    let pruned = if body.prune_empty_source {
        prune_empty_source_folders(&mut root, &sources)
    } else { 0 };

    drop(root);
    if applied > 0 || pruned > 0 { mark_dirty(&state).await; }
    Ok(Json(ClassifyApplyResp { ok: true, applied, skipped, pruned }))
}

/// Delete every folder in `source_paths` that is now empty (no bookmarks,
/// recursively). Skips the root and anything under the `_AI` subtree so we
/// never delete the AI classification target. Returns the count removed.
/// Deepest paths are processed first so emptying a child can cascade up.
fn prune_empty_source_folders(root: &mut nbm_core::Node, source_paths: &std::collections::HashSet<String>) -> usize {
    let mut paths: Vec<&String> = source_paths.iter()
        .filter(|p| !p.is_empty())
        .filter(|p| *p != "_AI" && !p.starts_with("_AI/"))
        .collect();
    // Longest path first → delete children before parents.
    paths.sort_by(|a, b| b.split('/').count().cmp(&a.split('/').count()));
    let mut pruned = 0;
    for p in paths {
        let is_empty = tree::find_folder(root, p)
            .map(|f| f.count_bookmarks() == 0)
            .unwrap_or(false);
        if is_empty && tree::delete_folder(root, p).is_ok() {
            pruned += 1;
        }
    }
    pruned
}

/// Ensure every folder along `path` exists, creating only the missing levels.
/// Previously this blindly called `add_folder` for each level, which has no
/// dedupe and so produced a fresh duplicate folder on every call (e.g. dozens
/// of empty `_AI` folders when applying a batch of AI moves).
fn ai_find_or_create_folder(root: &mut nbm_core::Node, path: &str) {
    let parts: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
    let mut current = String::new();
    for part in parts {
        let parent = current.clone();
        let candidate = if parent.is_empty() { part.to_string() } else { format!("{parent}/{part}") };
        // Only create the level if a folder with this exact path doesn't exist.
        if tree::find_folder(root, &candidate).is_none() {
            let _ = tree::add_folder(root, &parent, part);
        }
        current = candidate;
    }
}

#[cfg(test)]
mod folder_tests {
    use super::*;
    use nbm_core::Node;

    fn count_children_named(root: &Node, name: &str) -> usize {
        root.children.iter().filter(|c| c.is_folder() && c.title == name).count()
    }

    #[test]
    fn repeated_calls_do_not_duplicate_folders() {
        let mut root = Node::new_root();
        // Simulate applying many AI moves that all target /_AI/<cat>.
        for _ in 0..50 {
            ai_find_or_create_folder(&mut root, "/_AI/Dev");
        }
        ai_find_or_create_folder(&mut root, "/_AI/News");
        // Exactly one _AI folder, regardless of how many moves landed in it.
        assert_eq!(count_children_named(&root, "_AI"), 1, "duplicate _AI folders created");
        let ai = tree::find_folder(&root, "_AI").unwrap();
        assert_eq!(count_children_named(ai, "Dev"), 1);
        assert_eq!(count_children_named(ai, "News"), 1);
    }

    #[test]
    fn creates_missing_nested_levels_only() {
        let mut root = Node::new_root();
        ai_find_or_create_folder(&mut root, "/_AI/A/B");
        ai_find_or_create_folder(&mut root, "/_AI/A/C");
        assert_eq!(count_children_named(&root, "_AI"), 1);
        let a = tree::find_folder(&root, "_AI/A").unwrap();
        assert_eq!(count_children_named(a, "B"), 1);
        assert_eq!(count_children_named(a, "C"), 1);
    }

    #[test]
    fn prune_removes_emptied_sources_but_keeps_nonempty_and_ai() {
        use std::collections::HashSet;
        let mut root = Node::new_root();
        // Old/ has one bookmark that we'll "move out" → becomes empty.
        let mut old = Node::new_folder("Old");
        old.children.push(Node::new_bookmark("x", "https://x.test/"));
        root.children.push(old);
        // Keep/ keeps a bookmark → must survive.
        let mut keep = Node::new_folder("Keep");
        keep.children.push(Node::new_bookmark("y", "https://y.test/"));
        root.children.push(keep);
        // _AI/ target is empty but must never be pruned.
        root.children.push(Node::new_folder("_AI"));

        // Simulate the move-out: empty Old.
        tree::find_folder_mut(&mut root, "Old").unwrap().children.clear();

        let sources: HashSet<String> =
            ["Old".to_string(), "Keep".to_string(), "_AI".to_string()].into_iter().collect();
        let pruned = prune_empty_source_folders(&mut root, &sources);

        assert_eq!(pruned, 1, "only Old should be pruned");
        assert_eq!(count_children_named(&root, "Old"), 0, "empty source removed");
        assert_eq!(count_children_named(&root, "Keep"), 1, "non-empty source kept");
        assert_eq!(count_children_named(&root, "_AI"), 1, "_AI never pruned");
    }
}
