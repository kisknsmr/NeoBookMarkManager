//! Shared application state: the in-memory tree, the optional DB/backup/config
//! wiring, and the undo bookkeeping every mutating handler goes through.

use std::path::PathBuf;
use std::sync::Arc;

use camino::Utf8PathBuf;
use nbm_core::backup::{BackupError, BackupManager, BackupTargets};
use nbm_core::db::Db;
use nbm_core::fetch::build_http_client;
use nbm_core::model::Node;
use nbm_core::storage::{load_bookmarks, LoadedBookmarks};
use nbm_core::tree;
use tokio::sync::RwLock;

#[derive(Clone)]
pub struct AppState {
    pub inner: Arc<AppStateInner>,
}

const UNDO_LIMIT: usize = 50;

pub struct AppStateInner {
    pub root: RwLock<Node>,
    pub current_file: RwLock<Option<Utf8PathBuf>>,
    pub dirty: RwLock<bool>,
    pub db: Option<Arc<Db>>,
    pub backup_mgr: Option<Arc<BackupManager>>,
    pub config_ini_path: Option<PathBuf>,
    pub http_client: reqwest::Client,
    pub undo_stack: RwLock<Vec<Node>>,
    pub redo_stack: RwLock<Vec<Node>>,
    /// True when the opened file matches the fingerprint the DB session metadata
    /// was captured against, so the frontend should ask whether to resume.
    pub resume_available: RwLock<bool>,
}

#[derive(Default)]
pub struct AppStateConfig {
    pub current_file: Option<Utf8PathBuf>,
    pub db: Option<Arc<Db>>,
    pub backup_mgr: Option<Arc<BackupManager>>,
    pub config_ini_path: Option<PathBuf>,
    /// Optional proxy URL (e.g. "http://proxy:3128").
    pub proxy_url: Option<String>,
}


impl AppState {
    pub fn new(root: Node, cfg: AppStateConfig) -> Self {
        let http_client = build_http_client(cfg.proxy_url.as_deref());
        Self {
            inner: Arc::new(AppStateInner {
                root: RwLock::new(root),
                current_file: RwLock::new(cfg.current_file),
                dirty: RwLock::new(false),
                db: cfg.db,
                backup_mgr: cfg.backup_mgr,
                config_ini_path: cfg.config_ini_path,
                http_client,
                undo_stack: RwLock::new(Vec::new()),
                redo_stack: RwLock::new(Vec::new()),
                resume_available: RwLock::new(false),
            }),
        }
    }

    pub async fn load_from_file(
        path: &Utf8PathBuf,
        cfg: AppStateConfig,
    ) -> anyhow::Result<Self> {
        let LoadedBookmarks { mut root, content_hash, .. } = load_bookmarks(path.as_std_path())?;
        eprintln!(
            "[session] load_from_file: path={:?} hash={:?} db_configured={}",
            path.as_str(), content_hash, cfg.db.is_some()
        );
        if let Some(db) = cfg.db.as_ref() {
            eprintln!("[session] load_from_file: db_path={:?}", db.path);
        }
        tree::ensure_bookmark_ids(&mut root);
        tree::ensure_node_ids(&mut root);
        // Decide whether the DB session metadata (fetched titles + tags) belongs
        // to this exact file. Same path + same content hash → resumable (kept,
        // frontend confirms). Different file → cleared immediately.
        let resumable = cfg
            .db
            .as_ref()
            .map(|db| reconcile_session_meta(db, path.as_str(), &content_hash))
            .unwrap_or(false);
        let cfg = AppStateConfig {
            current_file: Some(path.clone()),
            ..cfg
        };
        let state = Self::new(root, cfg);
        *state.inner.resume_available.write().await = resumable;
        Ok(state)
    }

    /// Mark the in-memory tree as diverged from the file on disk.
    pub async fn mark_dirty(&self) {
        *self.inner.dirty.write().await = true;
    }

    /// Mark the in-memory tree as matching the file on disk. Call after a
    /// successful save, open, or backup restore.
    pub async fn mark_clean(&self) {
        *self.inner.dirty.write().await = false;
    }

    /// Safety gate for destructive batches (AI apply, bulk tidy, save): snapshot
    /// bookmarks HTML + DB + config into a new backup generation first.
    ///
    /// `Ok(None)` means there was genuinely nothing to protect: no backup
    /// manager configured (tests), or the bookmarks file has never been written
    /// to disk. Anything else — a database that should be there and is not, a
    /// copy that fails — is an `Err`, and the caller must abort rather than
    /// carry on unprotected. This used to return `Ok(None)` for those too, so a
    /// missing `config.ini` silently disabled the safety net for every batch.
    pub fn backup_before(&self, html: &std::path::Path) -> Result<Option<PathBuf>, BackupError> {
        let Some(bm) = self.inner.backup_mgr.as_ref() else { return Ok(None) };
        if !html.exists() {
            return Ok(None);
        }
        let Some(db) = self.inner.db.as_ref() else {
            return Err(BackupError::MissingTarget(
                "user_data.db（データベースを開けていないため、バックアップを作成できません）".into(),
            ));
        };
        if !db.path.exists() {
            return Err(BackupError::MissingTarget(db.path.display().to_string()));
        }
        let targets = BackupTargets {
            bookmarks_html: html.to_path_buf(),
            user_data_db: db.path.clone(),
            // Optional on purpose: an install with no config.ini still gets the
            // bookmarks file and the database protected.
            config_ini: self.inner.config_ini_path.clone().filter(|p| p.exists()),
        };
        bm.create_backup(&targets).map(Some)
    }

    /// [`AppState::backup_before`] for the file currently open.
    pub async fn backup_before_batch(&self) -> Result<Option<PathBuf>, BackupError> {
        let current = self.inner.current_file.read().await.clone();
        match current {
            Some(f) => self.backup_before(f.as_std_path()),
            None => Ok(None),
        }
    }

    pub async fn is_dirty(&self) -> bool {
        *self.inner.dirty.read().await
    }

    /// Apply a fallible mutation to the tree with undo bookkeeping.
    ///
    /// This replaces the `push_undo(); let mut root = …write().await;` pair that
    /// opened seventeen handlers, and fixes three things that pairing got wrong:
    ///
    /// - the snapshot is committed only when `f` succeeds, so a rejected edit no
    ///   longer leaves a phantom entry on the undo stack;
    /// - a failed `f` is rolled back, so a mutation that gives up half way
    ///   cannot leave the tree in a partial state;
    /// - the write lock is held across the snapshot and the mutation, closing
    ///   the window where two concurrent edits each snapshotted the other's
    ///   half-applied tree.
    ///
    /// The tree is cloned once per call, exactly as before.
    pub async fn edit<T, E>(&self, f: impl FnOnce(&mut Node) -> Result<T, E>) -> Result<T, E> {
        let mut root = self.inner.root.write().await;
        let snapshot = root.clone();
        match f(&mut root) {
            Ok(value) => {
                drop(root);
                self.commit_undo(snapshot).await;
                Ok(value)
            }
            Err(e) => {
                *root = snapshot;
                Err(e)
            }
        }
    }

    /// [`AppState::edit`] for bulk mutations that report per-item skips instead
    /// of failing as a whole.
    pub async fn edit_infallible<T>(&self, f: impl FnOnce(&mut Node) -> T) -> T {
        let mut root = self.inner.root.write().await;
        let snapshot = root.clone();
        let value = f(&mut root);
        drop(root);
        self.commit_undo(snapshot).await;
        value
    }

    /// Move the newest snapshot from `src` into the tree and push the outgoing
    /// tree onto `dst`. Undo and redo are this same operation with the two
    /// stacks swapped. Returns `(src_len, dst_len)` after the swap.
    ///
    /// The outgoing tree is moved rather than cloned, so a history step now
    /// costs no allocation of its own.
    async fn restore(
        &self,
        src: &RwLock<Vec<Node>>,
        dst: &RwLock<Vec<Node>>,
    ) -> Option<(usize, usize)> {
        let mut src_stack = src.write().await;
        let snapshot = src_stack.pop()?;
        let src_len = src_stack.len();
        drop(src_stack);

        let mut root = self.inner.root.write().await;
        let outgoing = std::mem::replace(&mut *root, snapshot);
        drop(root);

        let mut dst_stack = dst.write().await;
        dst_stack.push(outgoing);
        let dst_len = dst_stack.len();
        drop(dst_stack);

        self.mark_dirty().await;
        Some((src_len, dst_len))
    }

    /// Step back one edit. `Some((undo_count, redo_count))`, or `None` when
    /// there is nothing left to undo.
    pub async fn undo(&self) -> Option<(usize, usize)> {
        self.restore(&self.inner.undo_stack, &self.inner.redo_stack).await
    }

    /// Step forward one edit. `Some((undo_count, redo_count))`, or `None` when
    /// the redo branch is empty.
    pub async fn redo(&self) -> Option<(usize, usize)> {
        let (redo_count, undo_count) = self
            .restore(&self.inner.redo_stack, &self.inner.undo_stack)
            .await?;
        Some((undo_count, redo_count))
    }

    /// `(undo_count, redo_count)` without changing anything.
    pub async fn history(&self) -> (usize, usize) {
        let undo_count = self.inner.undo_stack.read().await.len();
        let redo_count = self.inner.redo_stack.read().await.len();
        (undo_count, redo_count)
    }

    /// Push a pre-mutation snapshot onto the undo stack, invalidate the redo
    /// branch and mark the tree dirty.
    async fn commit_undo(&self, snapshot: Node) {
        let mut stack = self.inner.undo_stack.write().await;
        stack.push(snapshot);
        if stack.len() > UNDO_LIMIT {
            stack.remove(0);
        }
        drop(stack);
        self.inner.redo_stack.write().await.clear();
        self.mark_dirty().await;
    }
}

/// A bookmark as the batch commands need it: what to fetch, and what to show
/// while fetching it.
#[derive(Clone, Debug)]
pub struct BookmarkRef {
    pub id: String,
    pub url: String,
    pub title: String,
    pub description: String,
}

impl BookmarkRef {
    /// Label for progress display. Untitled bookmarks fall back to their URL,
    /// which is more useful than an empty row.
    pub fn display_title(&self) -> String {
        if self.title.is_empty() {
            self.url.clone()
        } else {
            self.title.clone()
        }
    }
}

impl AppState {
    /// Resolve `ids` against the tree, in the order given, dropping any that
    /// are no longer there.
    ///
    /// Progress must be reported against the returned length rather than the
    /// requested one: ids that fail to resolve are never processed, and a
    /// `total` that counts them leaves the progress bar stuck short of 100%.
    pub async fn resolve_bookmarks(&self, ids: &[String]) -> Vec<BookmarkRef> {
        let root = self.inner.root.read().await;
        ids.iter()
            .filter_map(|id| {
                let (path, idx) = tree::locate_bookmark(&root, id)?;
                let folder = tree::find_folder(&root, &path)?;
                let bm = folder.children.get(idx)?;
                Some(BookmarkRef {
                    id: id.clone(),
                    url: bm.url.clone(),
                    title: bm.title.clone(),
                    description: bm.description.clone(),
                })
            })
            .collect()
    }

    /// Write a fetched description onto one bookmark and mark the file dirty.
    ///
    /// Deliberately no undo snapshot: this runs once per bookmark inside a
    /// streaming command, and cloning the whole tree per item would be
    /// pathological. The command as a whole is undone by reverting the file.
    pub async fn set_bookmark_description(&self, id: &str, description: &str) {
        {
            let mut root = self.inner.root.write().await;
            if let Some((path, idx)) = tree::locate_bookmark(&root, id) {
                if let Some(folder) = tree::find_folder_mut(&mut root, &path) {
                    if let Some(bm) = folder.children.get_mut(idx) {
                        bm.description = description.to_string();
                    }
                }
            }
        }
        self.mark_dirty().await;
    }
}

/// Decide what happens to the DB session metadata (fetched titles + tags) when a
/// bookmark file is opened, by comparing the file's `(path, content_hash)` to
/// the fingerprint stored at the last reconcile (open OR save).
///
/// - Same path AND same hash → returns `true` (resumable): metadata is kept.
/// - Otherwise (different file, externally modified, or first run) → clears
///   meta + tags and returns `false`.
///
/// The fingerprint is then (re)written to `(path, content_hash)` either way,
/// so a later reopen of this same, still-unmodified file recognizes it as the
/// same session. Earlier this was only written on explicit save, which meant
/// fetched titles/descriptions/tags — none of which require a save to exist —
/// were silently wiped on every relaunch unless the user had saved with that
/// exact content first. Bookmark-level edits still only change the hash once
/// actually saved, so external changes and genuinely different files are
/// still detected exactly as before.
pub(crate) fn reconcile_session_meta(db: &Db, path: &str, content_hash: &str) -> bool {
    let prev = db.get_open_state().ok().flatten();
    let resumable = matches!(
        prev,
        Some((ref p, ref h)) if p == path && h == content_hash
    );
    eprintln!(
        "[session] reconcile: current=({path:?}, {content_hash:?}) prev_open_state={prev:?} resumable={resumable}"
    );
    if !resumable {
        eprintln!("[session] clearing session meta/tags (mismatch or no prior open_state)");
        let _ = db.clear_session_data();
    }
    let _ = db.set_open_state(path, content_hash);
    resumable
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn tempfile_path() -> PathBuf {
        let mut p = std::env::temp_dir();
        let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        p.push(format!("nbm-state-test-{stamp}.db"));
        p
    }

    #[test]
    fn reopening_the_same_unmodified_file_keeps_session_meta_without_a_save() {
        let db = Db::open(tempfile_path()).unwrap();

        // First-ever open: nothing to resume from yet, but this establishes
        // the baseline fingerprint for next time.
        assert!(!reconcile_session_meta(&db, "C:/bm.html", "hash-a"));

        // Enrichment during this session (fetched title, auto-tag) is DB-only
        // and never touches the file, so the on-disk hash stays "hash-a" even
        // without an explicit save.
        db.save_tags_for_url("b1", &["Dev".into()], "auto", None).unwrap();
        assert_eq!(db.get_tags("b1").unwrap().len(), 1);

        // Relaunching the app and reopening the exact same, still-unsaved
        // file must recognize it as the same session and keep the tags —
        // this used to wipe them because only `edit_save` recorded the
        // fingerprint.
        assert!(reconcile_session_meta(&db, "C:/bm.html", "hash-a"));
        assert_eq!(
            db.get_tags("b1").unwrap().len(),
            1,
            "tags must survive a relaunch without a save"
        );

        // A genuinely different file (or externally modified content) must
        // still clear, exactly as before.
        assert!(!reconcile_session_meta(&db, "C:/bm.html", "hash-b"));
        assert_eq!(db.get_tags("b1").unwrap().len(), 0);

        std::fs::remove_file(&db.path).ok();
    }
}
