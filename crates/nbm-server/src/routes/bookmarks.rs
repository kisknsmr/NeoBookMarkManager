//! Read-only views of the tree plus the tag endpoints.

use axum::extract::{Path, Query, State};
use axum::routing::{get, post};
use axum::{Json, Router};
use nbm_core::model::{Node, NodeKind};
use serde::{Deserialize, Serialize};

use crate::error::{ApiError, ApiResult};
use crate::routes::OkResponse;
use crate::state::AppState;

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/health", get(health))
        .route("/bookmarks", get(list_bookmarks))
        .route("/tree", get(get_tree))
        .route("/search", get(search))
        .route("/meta/:bookmark_id", get(get_bookmark_meta))
        .route("/tags/:bookmark_id", get(get_tags))
        .route("/tags/update", post(update_tags))
}

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

impl ListResponse {
    /// Wrap a set of bookmarks with the open file and the dirty flag, which the
    /// frontend reads off every listing response.
    async fn build(state: &AppState, items: Vec<FlatBookmark>) -> Self {
        let file_path = state
            .inner
            .current_file
            .read()
            .await
            .as_ref()
            .map(|p| p.to_string());
        Self { file_path, count: items.len(), items, dirty: state.is_dirty().await }
    }
}

async fn list_bookmarks(
    State(state): State<AppState>,
    Query(q): Query<ListQuery>,
) -> Json<ListResponse> {
    let _ = q.file_path;
    let items = {
        let root = state.inner.root.read().await;
        let mut items = Vec::new();
        flatten(&root, "", &mut items);
        items
    };
    Json(ListResponse::build(&state, items).await)
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
    let mut items = {
        let root = state.inner.root.read().await;
        let mut items = Vec::new();
        flatten(&root, "", &mut items);
        items
    };
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
    Json(ListResponse::build(&state, items).await)
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
) -> ApiResult<TagsResponse> {
    let tags = match &state.inner.db {
        Some(db) => db.get_tags(&bookmark_id)?,
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

async fn update_tags(
    State(state): State<AppState>,
    Json(body): Json<TagsUpdateBody>,
) -> ApiResult<OkResponse> {
    let db = state
        .inner
        .db
        .as_ref()
        .ok_or_else(|| ApiError::unavailable("tags db unavailable"))?;
    db.save_tags_for_url(&body.bookmark_id, &body.tags, &body.source, body.confidence)?;
    Ok(OkResponse::ok())
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
