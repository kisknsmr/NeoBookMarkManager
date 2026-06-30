//! High-level wrappers over Netscape parse/serialize plus the rules sidecar.
//!
//! Mirrors `OriginalPythonCodes/core/ServiceStorage.py::load_bookmarks` /
//! `save_bookmarks`. The sidecar is `{bookmarks_path_stem}.bookmark_rules.json`.

use std::path::{Path, PathBuf};

use serde_json::Value;

use crate::model::Node;
use crate::netscape;

#[derive(Debug, thiserror::Error)]
pub enum StorageError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("parse: {0}")]
    Parse(#[from] netscape::NetscapeError),
    #[error("rules json: {0}")]
    Json(#[from] serde_json::Error),
}

pub struct LoadedBookmarks {
    pub root: Node,
    pub rules: Value,
    pub rules_path: Option<PathBuf>,
    /// Stable fingerprint of the raw HTML bytes, used to decide whether a
    /// reopened file is the same content the DB metadata was captured against.
    pub content_hash: String,
}

/// Fingerprint the raw bookmark HTML. Not cryptographic — only used to detect
/// "same file, untouched since we last closed it" so session metadata can be
/// safely reattached.
pub fn hash_content(html: &str) -> String {
    use std::hash::{Hash, Hasher};
    let mut h = std::collections::hash_map::DefaultHasher::new();
    html.hash(&mut h);
    format!("{:016x}", h.finish())
}

pub fn load_bookmarks(path: impl AsRef<Path>) -> Result<LoadedBookmarks, StorageError> {
    let path = path.as_ref();
    let html = std::fs::read_to_string(path)?;
    let content_hash = hash_content(&html);
    let root = netscape::parse(&html)?;

    let sidecar = sidecar_path(path);
    let (rules, rules_path) = if sidecar.exists() {
        match std::fs::read_to_string(&sidecar)
            .ok()
            .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        {
            Some(v) => (v, Some(sidecar)),
            None => (Value::Object(Default::default()), None),
        }
    } else {
        (Value::Object(Default::default()), None)
    };

    Ok(LoadedBookmarks {
        root,
        rules,
        rules_path,
        content_hash,
    })
}

pub fn save_bookmarks(
    path: impl AsRef<Path>,
    root: &Node,
    rules: Option<&Value>,
) -> Result<Option<PathBuf>, StorageError> {
    let path = path.as_ref();
    let html = netscape::serialize(root);
    std::fs::write(path, html)?;

    if let Some(rules) = rules {
        let sidecar = sidecar_path(path);
        let json = serde_json::to_string_pretty(rules)?;
        std::fs::write(&sidecar, json)?;
        Ok(Some(sidecar))
    } else {
        Ok(None)
    }
}

fn sidecar_path(bookmarks_path: &Path) -> PathBuf {
    let mut s = bookmarks_path.to_path_buf();
    s.set_extension("bookmark_rules.json");
    s
}
