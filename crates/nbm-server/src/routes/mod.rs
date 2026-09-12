//! HTTP handlers, one module per area.
//!
//! Each module owns its own routes, request/response bodies and helpers, and
//! exposes a `Router<AppState>` through `routes()`. Adding an endpoint means
//! touching one module instead of a 3,000-line file, and the URL layout is
//! readable from [`all`] alone.

use axum::Router;
use serde::Serialize;

use crate::state::AppState;

/// `{"ok": true}` — the reply from every endpoint whose only outcome is
/// success or an error.
#[derive(Serialize)]
pub(crate) struct OkResponse {
    pub ok: bool,
}

impl OkResponse {
    pub fn ok() -> axum::Json<Self> {
        axum::Json(Self { ok: true })
    }
}

pub mod autotag;
pub mod backup;
pub mod bookmarks;
pub mod classify;
pub mod config;
pub mod edit;
pub mod network;
pub mod organize;
pub mod session;

/// The complete API, before state and CORS are attached.
pub fn all() -> Router<AppState> {
    Router::new()
        .merge(bookmarks::routes())
        .merge(edit::routes())
        .merge(session::routes())
        .merge(backup::routes())
        .merge(autotag::routes())
        .merge(network::routes())
        .merge(config::routes())
        .merge(classify::routes())
        .merge(organize::routes())
}
