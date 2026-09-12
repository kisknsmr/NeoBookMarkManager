//! Rule-based (offline) tag generation, streamed over SSE.

use axum::extract::State;
use axum::response::sse::{Event, Sse};
use axum::routing::post;
use axum::{Json, Router};
use futures_util::stream::Stream;
use nbm_core::autotag;
use serde::{Deserialize, Serialize};

use crate::sse;
use crate::state::AppState;

pub fn routes() -> Router<AppState> {
    Router::new().route("/autotag/local", post(autotag_local))
}

#[derive(Deserialize)]
struct AutotagBody {
    // Older clients also send `allow_network`; serde drops unknown fields, so
    // the field is gone from the struct without breaking those requests
    // (Tier2 scraping was removed and the flag had no effect).
    bookmark_ids: Vec<String>,
}

#[derive(Serialize, Clone)]
struct AutotagProgress {
    bookmark_id: String,
    processed: usize,
    total: usize,
    status: String,
    tags: Vec<String>,
}

/// Tag every requested bookmark from its own text. No network is involved, so
/// this runs sequentially — there is nothing to overlap.
async fn autotag_local(
    State(state): State<AppState>,
    Json(body): Json<AutotagBody>,
) -> Sse<impl Stream<Item = Result<Event, std::convert::Infallible>>> {
    let (tx, rx) = sse::channel();
    let items = state.resolve_bookmarks(&body.bookmark_ids).await;
    let total = items.len();

    // Bulk-fetch fetched_titles from the DB rather than querying per bookmark.
    let fetched_titles = state
        .inner
        .db
        .as_ref()
        .and_then(|db| db.get_meta_bulk(&body.bookmark_ids).ok())
        .unwrap_or_default();
    let db = state.inner.db.clone();

    tokio::spawn(async move {
        for (i, bm) in items.iter().enumerate() {
            let tags = autotag::generate_tags(&autotag::BookmarkText {
                url: &bm.url,
                title: &bm.title,
                description: &bm.description,
                fetched_title: fetched_titles.get(&bm.id).map(String::as_str),
            });
            if let Some(db) = &db {
                let _ = db.save_tags_for_url(&bm.id, &tags, "rule", None);
            }
            let _ = tx
                .send(AutotagProgress {
                    bookmark_id: bm.id.clone(),
                    processed: i + 1,
                    total,
                    status: "ok".into(),
                    tags,
                })
                .await;
        }
        let _ = tx
            .send(AutotagProgress {
                bookmark_id: String::new(),
                processed: total,
                total,
                status: "done".into(),
                tags: Vec::new(),
            })
            .await;
    });

    sse::progress_stream(rx)
}
