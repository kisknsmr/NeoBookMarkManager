//! Standalone server bin. `cargo run -p nbm-server -- <bookmarks.html>`.

use std::env;
use std::sync::Arc;

use camino::Utf8PathBuf;
use nbm_core::backup::BackupManager;
use nbm_core::db::Db;
use nbm_core::model::Node;
use nbm_server::{AppState, AppStateConfig};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let bookmarks_path = env::args().nth(1).map(Utf8PathBuf::from);
    let project_root = std::env::current_dir()?;
    let db_path = project_root.join("user_data.db");
    let cfg_path = project_root.join("config").join("config.ini");

    let db = Db::open(&db_path).ok().map(Arc::new);
    let backup_mgr = Some(Arc::new(BackupManager::new(&project_root, 30)));

    let state_cfg = AppStateConfig {
        current_file: bookmarks_path.clone(),
        db,
        backup_mgr,
        config_ini_path: Some(cfg_path),
        proxy_url: None,
    };

    let state = match bookmarks_path {
        Some(ref p) if p.exists() => AppState::load_from_file(p, state_cfg).await?,
        _ => AppState::new(Node::new_root(), state_cfg),
    };

    let host = env::var("NBM_API_HOST").unwrap_or_else(|_| "127.0.0.1".into());
    let port: u16 = env::var("NBM_API_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);

    let (listener, actual_port) = nbm_server::bind(&host, port).await?;
    println!("[nbm-server] listening on http://{host}:{actual_port}");
    nbm_server::serve(listener, state).await?;
    Ok(())
}
