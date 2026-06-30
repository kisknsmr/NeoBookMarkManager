#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! Tauri shell. On startup we:
//! 1. Locate the portable data root next to the exe (or use repo dirs in dev).
//! 2. Bind a tokio TcpListener on 127.0.0.1:0 — OS picks a free port.
//! 3. Spawn the axum server on a dedicated tokio runtime.
//! 4. Inject `window.__NBM_API_BASE__` into the webview before index.html loads.

use std::net::TcpListener as StdTcpListener;
use std::path::PathBuf;
use std::sync::Arc;

use camino::Utf8PathBuf;
use nbm_core::backup::BackupManager;
use nbm_core::db::Db;
use nbm_core::model::Node;
use nbm_server::{AppState, AppStateConfig};

struct Resolved {
    bookmarks: Option<Utf8PathBuf>,
    db_path: PathBuf,
    config_ini: PathBuf,
    backup_root: PathBuf,
}

fn resolve_paths() -> Resolved {
    // Portable layout: prefer directory next to the exe that has data/ or config/.
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(PathBuf::from));

    if let Some(root) = exe_dir.as_ref().filter(|p| {
        p.join("data").exists() || p.join("config").exists()
    }) {
        let resolved = Resolved {
            bookmarks: None, // filled after bootstrap
            db_path: root.join("data").join("user_data.db"),
            config_ini: root.join("config").join("config.ini"),
            backup_root: root.clone(),
        };
        bootstrap_portable(root);
        let bookmarks = root.join("data").join("bookmarks.html");
        return Resolved {
            bookmarks: Utf8PathBuf::from_path_buf(bookmarks.clone())
                .ok()
                .filter(|_| bookmarks.exists()),
            ..resolved
        };
    }

    // First-run exe: bootstrap portable layout next to the exe.
    if let Some(root) = exe_dir.as_ref() {
        if !root.join("data").exists() || !root.join("config").exists() {
            bootstrap_portable(root);
            let bookmarks = root.join("data").join("bookmarks.html");
            return Resolved {
                bookmarks: Utf8PathBuf::from_path_buf(bookmarks.clone())
                    .ok()
                    .filter(|_| bookmarks.exists()),
                db_path: root.join("data").join("user_data.db"),
                config_ini: root.join("config").join("config.ini"),
                backup_root: root.clone(),
            };
        }
    }

    // Dev fallback: use the repo working dir.
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let sample = cwd.join("samples").join("bookmarks_2026_01_10.html");
    Resolved {
        bookmarks: Utf8PathBuf::from_path_buf(sample.clone()).ok().filter(|_| sample.exists()),
        db_path: cwd.join("user_data.db"),
        config_ini: cwd.join("config").join("config.ini"),
        backup_root: cwd,
    }
}

/// Create the portable directory layout on first run.
fn bootstrap_portable(root: &PathBuf) {
    let data_dir = root.join("data");
    let config_dir = root.join("config");
    let backup_dir = root.join("backups");

    for dir in [&data_dir, &config_dir, &backup_dir] {
        if let Err(e) = std::fs::create_dir_all(dir) {
            tracing::warn!(error=%e, path=%dir.display(), "bootstrap: failed to create dir");
        }
    }

    // Minimal bookmarks.html on first run.
    let bm = data_dir.join("bookmarks.html");
    if !bm.exists() {
        let content = "<!DOCTYPE NETSCAPE-Bookmark-file-1>\n\
            <!-- This is an automatically generated file. -->\n\
            <META HTTP-EQUIV=\"Content-Type\" CONTENT=\"text/html; charset=UTF-8\">\n\
            <TITLE>Bookmarks</TITLE>\n\
            <H1>Bookmarks</H1>\n\
            <DL><p>\n\
            </DL><p>\n";
        if let Err(e) = std::fs::write(&bm, content) {
            tracing::warn!(error=%e, "bootstrap: failed to write bookmarks.html");
        } else {
            tracing::info!("bootstrap: created {}", bm.display());
        }
    }

    // Minimal config.ini on first run.
    let ini = config_dir.join("config.ini");
    if !ini.exists() {
        let content = "[API]\n# api_key = YOUR_GEMINI_KEY_HERE\n\n[Proxy]\n# url = http://proxy:3128\n\n[Classifier]\n# priority_terms = Python, Rust, DevOps\n";
        if let Err(e) = std::fs::write(&ini, content) {
            tracing::warn!(error=%e, "bootstrap: failed to write config.ini");
        } else {
            tracing::info!("bootstrap: created {}", ini.display());
        }
    }
}

fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let std_listener = StdTcpListener::bind("127.0.0.1:0")
        .expect("failed to bind 127.0.0.1:0 — is the loopback interface up?");
    std_listener.set_nonblocking(true).expect("set_nonblocking");
    let port = std_listener.local_addr().expect("local_addr").port();
    tracing::info!(port, "bound axum listener");

    let api_base = format!("http://127.0.0.1:{port}");
    let init_script = format!("window.__NBM_API_BASE__ = '{}';", api_base);

    let resolved = resolve_paths();
    let db = Db::open(&resolved.db_path).ok().map(Arc::new);
    let backup_mgr = Some(Arc::new(BackupManager::new(&resolved.backup_root, 30)));

    // Read proxy URL from config.ini if present.
    let proxy_url = match nbm_core::ConfigManager::load(&resolved.config_ini) {
        Ok(cm) => cm.get("Proxy", "url"),
        Err(_) => None,
    };

    let state_cfg = AppStateConfig {
        current_file: resolved.bookmarks.clone(),
        db,
        backup_mgr,
        config_ini_path: Some(resolved.config_ini.clone()),
        proxy_url,
    };

    let server_runtime = Arc::new(
        tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("tokio runtime"),
    );

    let state = match resolved.bookmarks.as_ref() {
        Some(p) if p.as_std_path().exists() => server_runtime
            .block_on(AppState::load_from_file(p, state_cfg))
            .unwrap_or_else(|e| {
                tracing::error!(error=%e, path=%p, "failed to load bookmarks; starting empty");
                let cfg = AppStateConfig {
                    current_file: resolved.bookmarks.clone(),
                    db: None,
                    backup_mgr: None,
                    config_ini_path: None,
                    proxy_url: None,
                };
                AppState::new(Node::new_root(), cfg)
            }),
        _ => {
            tracing::warn!("no bookmarks.html found; starting empty");
            AppState::new(Node::new_root(), state_cfg)
        }
    };

    {
        let rt = server_runtime.clone();
        let state = state.clone();
        std::thread::Builder::new()
            .name("nbm-server".into())
            .spawn(move || {
                rt.block_on(async move {
                    let listener = tokio::net::TcpListener::from_std(std_listener)
                        .expect("from_std");
                    if let Err(e) = nbm_server::serve(listener, state).await {
                        tracing::error!(error=%e, "axum server exited");
                    }
                });
            })
            .expect("spawn server thread");
    }

    // Window is defined statically in tauri.conf.json so that
    // dragDropEnabled:false actually takes effect on Windows
    // (tauri-apps/tauri#13761: the Rust .drag_and_drop(false) builder API
    // is silently ignored, only the JSON config path works).
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .append_invoke_initialization_script(init_script)
        .run(tauri::generate_context!())
        .expect("error while running tauri application");

    drop(server_runtime);
}
