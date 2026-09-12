//! Shared harness for the HTTP-level tests.
//!
//! Every test drives the real `router()` through `tower::ServiceExt::oneshot`,
//! so the assertions cover extractors, status codes and JSON shapes exactly as
//! the frontend sees them — the layer that had no coverage before.

// Each test binary pulls in this module and uses a different subset of it.
#![allow(dead_code)]

use std::sync::Arc;

use axum::body::Body;
use axum::http::{Method, Request, StatusCode};
use axum::Router;
use camino::Utf8PathBuf;
use nbm_core::backup::BackupManager;
use nbm_core::db::Db;
use nbm_core::model::Node;
use nbm_core::tree;
use nbm_server::{AppState, AppStateConfig};
use serde_json::Value;
use tempfile::TempDir;
use tower::ServiceExt;

/// A server under test plus the temp directory its files live in.
pub struct TestApp {
    pub state: AppState,
    pub router: Router,
    pub dir: TempDir,
}

/// What the app should be wired up with. Defaults to the bare minimum (tree
/// only) so each test opts into the parts it actually exercises.
#[derive(Default)]
pub struct Fixture {
    pub with_db: bool,
    pub with_backup: bool,
    /// config.ini body to write, if any.
    pub config_ini: Option<&'static str>,
    /// Write the tree to this file and set it as `current_file`.
    pub with_current_file: bool,
}

impl Fixture {
    pub fn with_db(mut self) -> Self {
        self.with_db = true;
        self
    }
    pub fn with_backup(mut self) -> Self {
        self.with_backup = true;
        self
    }
    pub fn with_config(mut self, ini: &'static str) -> Self {
        self.config_ini = Some(ini);
        self
    }
    pub fn with_current_file(mut self) -> Self {
        self.with_current_file = true;
        self
    }

    pub async fn build(self) -> TestApp {
        let dir = tempfile::tempdir().expect("tempdir");
        let mut cfg = AppStateConfig::default();

        if self.with_db {
            let db = Db::open(dir.path().join("user_data.db")).expect("open db");
            cfg.db = Some(Arc::new(db));
        }
        if self.with_backup {
            cfg.backup_mgr = Some(Arc::new(BackupManager::new(dir.path(), 3)));
        }
        if let Some(ini) = self.config_ini {
            let path = dir.path().join("config.ini");
            std::fs::write(&path, ini).expect("write config.ini");
            cfg.config_ini_path = Some(path);
        }
        if self.with_current_file {
            let path = dir.path().join("bookmarks.html");
            nbm_core::storage::save_bookmarks(&path, &sample_tree(), None).expect("save");
            cfg.current_file =
                Some(Utf8PathBuf::from_path_buf(path).expect("utf8 path"));
        }

        let state = AppState::new(sample_tree(), cfg);
        let router = nbm_server::router(state.clone());
        TestApp { state, router, dir }
    }
}

pub async fn app() -> TestApp {
    Fixture::default().build().await
}

/// ```text
/// (root)
/// ├── Work
/// │   ├── A     https://github.com/a
/// │   ├── B     https://github.com/b
/// │   ├── Dup   https://github.com/a   (duplicate URL of A)
/// │   └── Nested
/// │       └── C https://example.com/c
/// └── Personal
///     └── D     https://example.org/d
/// ```
/// 5 bookmarks, 3 folders, one duplicate URL and one duplicate folder name is
/// added by `sample_tree_with_dup_folder`.
pub fn sample_tree() -> Node {
    let bm = |title: &str, url: &str| Node::new_bookmark(title, url);

    let mut nested = Node::new_folder("Nested");
    nested.children.push(bm("C", "https://example.com/c"));

    let mut work = Node::new_folder("Work");
    work.children.push(bm("A", "https://github.com/a"));
    work.children.push(bm("B", "https://github.com/b"));
    work.children.push(bm("Dup", "https://github.com/a"));
    work.children.push(nested);

    let mut personal = Node::new_folder("Personal");
    personal.children.push(bm("D", "https://example.org/d"));

    let mut root = Node::new_root();
    root.children.push(work);
    root.children.push(personal);
    tree::ensure_bookmark_ids(&mut root);
    tree::ensure_node_ids(&mut root);
    root
}

impl TestApp {
    async fn request(&self, method: Method, uri: &str, body: Option<Value>) -> (StatusCode, Value) {
        let mut builder = Request::builder().method(method).uri(uri);
        let body = match body {
            Some(v) => {
                builder = builder.header("content-type", "application/json");
                Body::from(serde_json::to_vec(&v).expect("serialize body"))
            }
            None => Body::empty(),
        };
        let req = builder.body(body).expect("build request");
        let res = self
            .router
            .clone()
            .oneshot(req)
            .await
            .expect("router response");
        let status = res.status();
        let bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
            .await
            .expect("read body");
        // Handlers that return no body (or a non-JSON one) still need a value
        // to hand back; Null keeps the call sites uniform.
        let json = if bytes.is_empty() {
            Value::Null
        } else {
            serde_json::from_slice(&bytes).unwrap_or(Value::Null)
        };
        (status, json)
    }

    pub async fn get(&self, uri: &str) -> (StatusCode, Value) {
        self.request(Method::GET, uri, None).await
    }

    pub async fn post(&self, uri: &str, body: Value) -> (StatusCode, Value) {
        self.request(Method::POST, uri, Some(body)).await
    }

    pub async fn patch(&self, uri: &str, body: Value) -> (StatusCode, Value) {
        self.request(Method::PATCH, uri, Some(body)).await
    }

    pub async fn delete(&self, uri: &str) -> (StatusCode, Value) {
        self.request(Method::DELETE, uri, None).await
    }

    /// `bookmark_id` of the bookmark titled `title`, via the public listing.
    pub async fn bookmark_id(&self, title: &str) -> String {
        let (_, list) = self.get("/bookmarks").await;
        list["items"]
            .as_array()
            .expect("items array")
            .iter()
            .find(|b| b["title"] == title)
            .unwrap_or_else(|| panic!("no bookmark titled {title}"))["bookmark_id"]
            .as_str()
            .expect("bookmark_id")
            .to_string()
    }

    /// `node_id` of the folder at `path` (e.g. "Work/Nested").
    pub async fn folder_node_id(&self, path: &str) -> String {
        let root = self.state.inner.root.read().await;
        tree::find_folder(&root, path)
            .unwrap_or_else(|| panic!("no folder at {path}"))
            .node_id
            .clone()
    }

    /// Folder path of the bookmark titled `title`, or None when it is gone.
    pub async fn folder_of(&self, title: &str) -> Option<String> {
        let (_, list) = self.get("/bookmarks").await;
        list["items"].as_array()?.iter().find_map(|b| {
            (b["title"] == title).then(|| b["folder_path"].as_str().unwrap_or("").to_string())
        })
    }

    pub async fn titles_in(&self, folder_path: &str) -> Vec<String> {
        let (_, list) = self.get("/bookmarks").await;
        list["items"]
            .as_array()
            .expect("items array")
            .iter()
            .filter(|b| b["folder_path"] == folder_path)
            .map(|b| b["title"].as_str().unwrap_or_default().to_string())
            .collect()
    }
}
