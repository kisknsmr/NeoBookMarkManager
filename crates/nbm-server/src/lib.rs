//! In-process HTTP layer used both by the standalone bin and by the Tauri shell.
//!
//! Layout:
//! - [`state`] — the shared tree plus undo/dirty bookkeeping
//! - [`error`] — the one error type every handler returns
//! - [`settings`] — values read out of `config.ini`
//! - [`sse`] — shared plumbing for the progress-streaming commands
//! - [`routes`] — the handlers, one module per area, each exposing its own
//!   `Router`, which [`router`] merges

use std::net::SocketAddr;

use axum::http::{HeaderValue, Method};
use axum::Router;
use tokio::net::TcpListener;
use tower_http::cors::CorsLayer;

pub mod ai_log;
pub mod error;
pub mod routes;
pub mod settings;
pub mod sse;
pub mod state;

pub use state::{resume_file, AppState, AppStateConfig, AppStateInner};

pub fn router(state: AppState) -> Router {
    // The webview's origin depends on the platform, and missing the right one
    // fails every single request as an opaque "Failed to fetch" in the UI.
    let cors = CorsLayer::new()
        .allow_origin([
            // macOS / Linux: the custom protocol is a real scheme.
            "tauri://localhost".parse::<HeaderValue>().unwrap(),
            // Windows / Android: WebView2 cannot register a custom scheme, so
            // Tauri serves the app from `http://tauri.localhost` instead
            // (`https://` when a window sets `useHttpsScheme`). Both are listed
            // because the origin changes with that flag, not with the platform.
            "http://tauri.localhost".parse::<HeaderValue>().unwrap(),
            "https://tauri.localhost".parse::<HeaderValue>().unwrap(),
            // `tauri dev` with an external dev server.
            "http://localhost:1430".parse::<HeaderValue>().unwrap(),
            "http://127.0.0.1:1430".parse::<HeaderValue>().unwrap(),
        ])
        .allow_methods([Method::GET, Method::POST, Method::PATCH, Method::DELETE])
        .allow_headers(tower_http::cors::Any);

    routes::all().with_state(state).layer(cors)
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
