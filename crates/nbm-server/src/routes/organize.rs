//! Bulk tidying: dedupe, folder merging and domain-based grouping.

use axum::extract::State;
use axum::routing::{get, post};
use axum::{Json, Router};
use nbm_core::organize;
use serde::{Deserialize, Serialize};

use crate::error::ApiResult;
use crate::settings;
use crate::state::AppState;

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/organize/dedupe", post(organize_dedupe))
        .route(
            "/organize/merge-duplicate-folders",
            post(organize_merge_dup_folders),
        )
        .route("/organize/domain-stats", get(organize_domain_stats))
        .route(
            "/organize/consolidate-by-domain",
            post(organize_consolidate_domain),
        )
        .route("/organize/sort-by-domain", post(organize_sort_by_domain))
}

#[derive(Serialize)]
struct OrganizeResp {
    ok: bool,
    count: usize,
}

impl OrganizeResp {
    fn new(count: usize) -> Json<Self> {
        Json(Self { ok: true, count })
    }
}

#[derive(Deserialize)]
struct DedupeBody {
    folder_path: String,
}

async fn organize_dedupe(
    State(state): State<AppState>,
    Json(body): Json<DedupeBody>,
) -> ApiResult<OrganizeResp> {
    let exclude = settings::dedupe_exclude_urls(&state);
    let count = state
        .edit(|root| organize::dedupe_folder(root, &body.folder_path, &exclude))
        .await?;
    Ok(OrganizeResp::new(count))
}

#[derive(Deserialize)]
struct MergeDupFoldersBody {
    parent_path: String,
}

async fn organize_merge_dup_folders(
    State(state): State<AppState>,
    Json(body): Json<MergeDupFoldersBody>,
) -> ApiResult<OrganizeResp> {
    let count = state
        .edit(|root| organize::merge_duplicate_folders(root, &body.parent_path))
        .await?;
    Ok(OrganizeResp::new(count))
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
) -> ApiResult<OrganizeResp> {
    let folder_name = body.target_folder.unwrap_or_else(|| body.domain.clone());
    let scope = body.scope_path.as_deref();
    let keyword = body.keyword.as_deref().map(|k| k.trim().to_lowercase());
    let tags_map = match &state.inner.db {
        Some(db) => db.get_all_tags_map().unwrap_or_default(),
        None => std::collections::HashMap::new(),
    };
    let count = state
        .edit(|root| {
            organize::consolidate_by_domain(
                root,
                &body.domain,
                &folder_name,
                scope,
                keyword.as_deref(),
                &tags_map,
                &body.exclude_target_names,
            )
        })
        .await?;
    Ok(OrganizeResp::new(count))
}

#[derive(Deserialize)]
struct SortByDomainBody {
    folder_path: String,
}

async fn organize_sort_by_domain(
    State(state): State<AppState>,
    Json(body): Json<SortByDomainBody>,
) -> ApiResult<OrganizeResp> {
    let count = state
        .edit(|root| organize::sort_by_domain(root, &body.folder_path))
        .await?;
    Ok(OrganizeResp::new(count))
}
