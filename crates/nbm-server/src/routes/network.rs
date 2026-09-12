//! Outbound-network commands, all streamed back over SSE: fetching titles and
//! descriptions, and checking links for rot.

use axum::extract::State;
use axum::response::sse::{Event, Sse};
use axum::routing::{get, post};
use axum::{Json, Router};
use futures_util::stream::Stream;
use nbm_core::fetch::{check_url, fetch_url_meta};
use serde::{Deserialize, Serialize};

use crate::settings;
use crate::sse::{self, Reporter};
use crate::state::{AppState, BookmarkRef};

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/network/fix-titles", post(network_fix_titles))
        .route("/network/fetch-preview", post(network_fetch_preview))
        .route("/network/link-check", post(network_link_check))
        .route("/network/proxy-check", get(network_proxy_check))
}

#[derive(Deserialize)]
struct NetworkBatchBody {
    /// List of bookmark_ids to process.
    bookmark_ids: Vec<String>,
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

impl NetworkProgress {
    fn done(total: usize) -> Self {
        Self {
            bookmark_id: String::new(),
            processed: total,
            total,
            status: "done".to_string(),
            bookmark_title: None,
            new_title: None,
            description: None,
        }
    }
}

/// What a metadata fetch does with what it finds. Both endpoints fetch exactly
/// the same thing; they differ only in whether the description is persisted
/// into the tree.
#[derive(Clone, Copy)]
enum Persist {
    /// Fetched title goes to the DB only; the tree is left untouched.
    TitleInDbOnly,
    /// The description is also written onto the bookmark, so it lands in
    /// bookmarks.html on the next save.
    DescriptionIntoTree,
}

async fn network_fix_titles(
    State(state): State<AppState>,
    Json(body): Json<NetworkBatchBody>,
) -> Sse<impl Stream<Item = Result<Event, std::convert::Infallible>>> {
    fetch_metadata(state, body.bookmark_ids, Persist::TitleInDbOnly).await
}

async fn network_fetch_preview(
    State(state): State<AppState>,
    Json(body): Json<NetworkBatchBody>,
) -> Sse<impl Stream<Item = Result<Event, std::convert::Infallible>>> {
    fetch_metadata(state, body.bookmark_ids, Persist::DescriptionIntoTree).await
}

/// Fetch title + description for each bookmark, streaming one event per item.
///
/// `fix-titles` and `fetch-preview` used to be two near-identical copies of
/// this, and had drifted: one honoured `[Network] concurrency` while the other
/// fetched strictly one page at a time regardless of the setting. They now
/// share the loop, so the setting applies to both.
async fn fetch_metadata(
    state: AppState,
    requested_ids: Vec<String>,
    persist: Persist,
) -> Sse<impl Stream<Item = Result<Event, std::convert::Infallible>>> {
    let (tx, rx) = sse::channel();
    let items = state.resolve_bookmarks(&requested_ids).await;
    let concurrency = settings::fetch_concurrency(&state);
    report_unresolved(&requested_ids, &items, concurrency);

    let client = state.inner.http_client.clone();
    sse::spawn_workers(
        items,
        concurrency,
        tx,
        move |bm: BookmarkRef, reporter: Reporter<NetworkProgress>| {
            let client = client.clone();
            let state = state.clone();
            async move {
                let (new_title, description, status) = match fetch_url_meta(&client, &bm.url).await {
                    Ok((title, desc)) => (Some(title), Some(desc), "ok".to_string()),
                    Err(e) => (None, None, format!("error: {e}")),
                };

                if status == "ok" {
                    if let (Persist::DescriptionIntoTree, Some(desc)) = (persist, &description) {
                        state.set_bookmark_description(&bm.id, desc).await;
                    }
                    // fetched_title は DB のみ（揮発性、HTML には書かない）
                    if let (Some(title), Some(db)) = (&new_title, &state.inner.db) {
                        if !title.is_empty() {
                            let _ = db.save_meta(&bm.id, title);
                        }
                    }
                }

                reporter
                    .send(|processed, total| NetworkProgress {
                        bookmark_id: bm.id.clone(),
                        processed,
                        total,
                        status,
                        bookmark_title: Some(bm.display_title()),
                        new_title,
                        description,
                    })
                    .await;
            }
        },
        NetworkProgress::done,
    );

    sse::progress_stream(rx)
}

/// Log the ids that no longer exist in the tree. They are dropped silently from
/// the batch, which is otherwise invisible when the count comes back short.
fn report_unresolved(requested: &[String], resolved: &[BookmarkRef], concurrency: usize) {
    eprintln!(
        "[network] requested={} resolved={} concurrency={}",
        requested.len(),
        resolved.len(),
        concurrency
    );
    if requested.len() == resolved.len() {
        return;
    }
    let found: std::collections::HashSet<&str> = resolved.iter().map(|b| b.id.as_str()).collect();
    let missing: Vec<&String> = requested
        .iter()
        .filter(|id| !found.contains(id.as_str()))
        .collect();
    eprintln!(
        "[network] {} ids could not be located in tree: {:?}",
        missing.len(),
        missing
    );
}

// --- Link check ------------------------------------------------------------

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

impl LinkCheckProgress {
    fn done(total: usize) -> Self {
        Self {
            bookmark_id: String::new(),
            processed: total,
            total,
            result: "done".to_string(),
            bookmark_title: None,
            url: None,
            detail: None,
        }
    }
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

async fn network_link_check(
    State(state): State<AppState>,
    Json(body): Json<NetworkBatchBody>,
) -> Sse<impl Stream<Item = Result<Event, std::convert::Infallible>>> {
    let (tx, rx) = sse::channel();
    let items = state.resolve_bookmarks(&body.bookmark_ids).await;
    let excludes = settings::linkcheck_excludes(&state);
    let (timeout_secs, concurrency) = settings::linkcheck_limits(&state);
    let client = state.inner.http_client.clone();

    sse::spawn_workers(
        items,
        concurrency,
        tx,
        move |bm: BookmarkRef, reporter: Reporter<LinkCheckProgress>| {
            let client = client.clone();
            let excludes = excludes.clone();
            async move {
                let (result, detail) = if bm.url.is_empty() {
                    ("skip", "URL なし".to_string())
                } else if url_is_excluded(&bm.url, &excludes) {
                    ("skip", "除外パターン".to_string())
                } else {
                    check_url(&client, &bm.url, timeout_secs).await
                };
                reporter
                    .send(|processed, total| LinkCheckProgress {
                        bookmark_id: bm.id.clone(),
                        processed,
                        total,
                        result: result.to_string(),
                        bookmark_title: Some(bm.display_title()),
                        url: Some(bm.url),
                        detail: Some(detail),
                    })
                    .await;
            }
        },
        LinkCheckProgress::done,
    );

    sse::progress_stream(rx)
}

// --- Proxy -----------------------------------------------------------------

#[derive(Serialize)]
struct ProxyCheckResp {
    configured: bool,
    url: Option<String>,
    reachable: bool,
    message: String,
}

async fn network_proxy_check(State(state): State<AppState>) -> Json<ProxyCheckResp> {
    let Some(url) = settings::proxy_url(&state) else {
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
