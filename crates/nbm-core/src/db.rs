//! SQLite tag storage. Mirrors `OriginalPythonCodes/core/DatabaseManager.py`.
//!
//! - `schema_version` table gates compatibility.
//! - One migration so far: `0 -> 1` creates `tags` and `url_tags`.
//! - `save_tags_for_url` replaces tags for `(bookmark_id, source)` and
//!   inserts into the bridge table.

use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::{params, Connection};

pub const CURRENT_VERSION: i64 = 3;

#[derive(Debug, thiserror::Error)]
pub enum DbError {
    #[error("sqlite: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("db version {0} is newer than supported {1}")]
    VersionTooNew(i64, i64),
}

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct TagDetail {
    pub name: String,
    pub source: String,
    pub confidence: Option<f64>,
}

pub struct Db {
    pub path: PathBuf,
}

impl Db {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, DbError> {
        let path = path.into();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let db = Self { path };
        db.ensure_compatible()?;
        db.migrate()?;
        Ok(db)
    }

    fn connect(&self) -> Result<Connection, DbError> {
        let conn = Connection::open(&self.path)?;
        conn.execute("PRAGMA foreign_keys = ON;", [])?;
        Ok(conn)
    }

    fn ensure_compatible(&self) -> Result<(), DbError> {
        let conn = self.connect()?;
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);",
            [],
        )?;
        let ver: Option<i64> = conn
            .query_row("SELECT version FROM schema_version LIMIT 1;", [], |r| r.get(0))
            .ok();
        if ver.is_none() {
            conn.execute("INSERT INTO schema_version(version) VALUES (0);", [])?;
        } else if let Some(v) = ver {
            if v > CURRENT_VERSION {
                return Err(DbError::VersionTooNew(v, CURRENT_VERSION));
            }
        }
        Ok(())
    }

    fn migrate(&self) -> Result<(), DbError> {
        let conn = self.connect()?;
        let mut ver: i64 = conn
            .query_row("SELECT version FROM schema_version LIMIT 1;", [], |r| r.get(0))
            .unwrap_or(0);
        while ver < CURRENT_VERSION {
            match (ver, ver + 1) {
                (0, 1) => migrate_0_to_1(&conn)?,
                (1, 2) => migrate_1_to_2(&conn)?,
                (2, 3) => migrate_2_to_3(&conn)?,
                _ => unreachable!("missing migration {ver}->{}", ver + 1),
            }
            conn.execute("DELETE FROM schema_version;", [])?;
            conn.execute("INSERT INTO schema_version(version) VALUES (?);", params![ver + 1])?;
            ver += 1;
        }
        Ok(())
    }

    pub fn get_tags(&self, bookmark_id: &str) -> Result<Vec<TagDetail>, DbError> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            "SELECT t.name, ut.source, ut.confidence
             FROM url_tags ut
             JOIN tags t ON t.id = ut.tag_id
             WHERE ut.bookmark_id = ?
             ORDER BY t.name",
        )?;
        let rows = stmt.query_map(params![bookmark_id], |r| {
            Ok(TagDetail {
                name: r.get::<_, String>(0)?,
                source: r.get::<_, String>(1)?,
                confidence: r.get::<_, Option<f64>>(2)?,
            })
        })?;
        let mut out = Vec::new();
        for row in rows {
            out.push(row?);
        }
        Ok(out)
    }

    /// Return all tags as a Map<bookmark_id, space-joined tag names> in one query.
    pub fn get_all_tags_map(&self) -> Result<std::collections::HashMap<String, String>, DbError> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            "SELECT ut.bookmark_id, t.name
             FROM url_tags ut
             JOIN tags t ON t.id = ut.tag_id
             ORDER BY ut.bookmark_id, t.name",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?;
        let mut map: std::collections::HashMap<String, Vec<String>> = std::collections::HashMap::new();
        for row in rows {
            let (bid, tag) = row?;
            map.entry(bid).or_default().push(tag);
        }
        Ok(map.into_iter().map(|(k, v)| (k, v.join(" "))).collect())
    }

    /// Save or replace the fetched metadata (title supplement) for a bookmark.
    /// description is stored in the Node tree (HTML); only the fetched title
    /// that should NOT overwrite the user's title goes here.
    pub fn save_meta(
        &self,
        bookmark_id: &str,
        fetched_title: &str,
    ) -> Result<(), DbError> {
        if bookmark_id.is_empty() {
            return Ok(());
        }
        let conn = self.connect()?;
        let now = iso_now();
        conn.execute(
            "INSERT INTO bookmark_meta(bookmark_id, fetched_title, fetched_at)
             VALUES (?, ?, ?)
             ON CONFLICT(bookmark_id) DO UPDATE SET
               fetched_title = excluded.fetched_title,
               fetched_at    = excluded.fetched_at;",
            params![bookmark_id, fetched_title, now],
        )?;
        Ok(())
    }

    /// Get the fetched title for a bookmark, if any.
    pub fn get_meta(&self, bookmark_id: &str) -> Result<Option<String>, DbError> {
        let conn = self.connect()?;
        let result = conn.query_row(
            "SELECT fetched_title FROM bookmark_meta WHERE bookmark_id = ? LIMIT 1;",
            params![bookmark_id],
            |r| r.get::<_, String>(0),
        );
        match result {
            Ok(t) => Ok(Some(t)),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(e) => Err(e.into()),
        }
    }

    /// Get fetched titles for multiple bookmarks at once.
    /// Returns a map of bookmark_id -> fetched_title.
    pub fn get_meta_bulk(
        &self,
        bookmark_ids: &[String],
    ) -> Result<std::collections::HashMap<String, String>, DbError> {
        if bookmark_ids.is_empty() {
            return Ok(std::collections::HashMap::new());
        }
        let conn = self.connect()?;
        let placeholders = bookmark_ids.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!(
            "SELECT bookmark_id, fetched_title FROM bookmark_meta WHERE bookmark_id IN ({placeholders});"
        );
        let mut stmt = conn.prepare(&sql)?;
        let params_vec: Vec<&dyn rusqlite::ToSql> =
            bookmark_ids.iter().map(|s| s as &dyn rusqlite::ToSql).collect();
        let rows = stmt.query_map(params_vec.as_slice(), |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?;
        let mut out = std::collections::HashMap::new();
        for row in rows {
            let (id, title) = row?;
            out.insert(id, title);
        }
        Ok(out)
    }

    /// Clear all fetched metadata. Called on file open so stale data from a
    /// previous session doesn't bleed into AI classification of a new file.
    pub fn clear_all_meta(&self) -> Result<(), DbError> {
        let conn = self.connect()?;
        conn.execute("DELETE FROM bookmark_meta;", [])?;
        Ok(())
    }

    /// Drop all session-scoped data (fetched titles AND tags) in one
    /// transaction. Called when a *different* bookmark file is opened so the
    /// previous file's metadata/tags don't bleed across files.
    pub fn clear_session_data(&self) -> Result<(), DbError> {
        let mut conn = self.connect()?;
        let tx = conn.transaction()?;
        tx.execute("DELETE FROM bookmark_meta;", [])?;
        tx.execute("DELETE FROM url_tags;", [])?;
        tx.commit()?;
        Ok(())
    }

    /// Read the fingerprint of the file the session metadata was last captured
    /// against: `(file_path, content_hash)`. None if never recorded.
    pub fn get_open_state(&self) -> Result<Option<(String, String)>, DbError> {
        let conn = self.connect()?;
        let result = conn.query_row(
            "SELECT file_path, content_hash FROM open_state WHERE id = 1 LIMIT 1;",
            [],
            |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)),
        );
        match result {
            Ok(v) => Ok(Some(v)),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(e) => Err(e.into()),
        }
    }

    /// Record the file path + content hash the current session metadata belongs
    /// to. Called on save so a clean reopen of the same file reattaches meta.
    pub fn set_open_state(&self, file_path: &str, content_hash: &str) -> Result<(), DbError> {
        let conn = self.connect()?;
        let now = iso_now();
        conn.execute(
            "INSERT INTO open_state(id, file_path, content_hash, updated_at)
             VALUES (1, ?, ?, ?)
             ON CONFLICT(id) DO UPDATE SET
               file_path    = excluded.file_path,
               content_hash = excluded.content_hash,
               updated_at   = excluded.updated_at;",
            params![file_path, content_hash, now],
        )?;
        Ok(())
    }

    /// Replace tags for `(bookmark_id, source)` with the supplied set.
    /// Mirrors `DatabaseManager.save_tags_for_url`.
    pub fn save_tags_for_url(
        &self,
        bookmark_id: &str,
        tags: &[String],
        source: &str,
        confidence: Option<f64>,
    ) -> Result<(), DbError> {
        if bookmark_id.is_empty() {
            return Ok(());
        }
        let mut conn = self.connect()?;
        let now = iso_now();
        let cleaned = normalize_tags(tags);

        let tx = conn.transaction()?;
        tx.execute(
            "DELETE FROM url_tags WHERE bookmark_id = ? AND source = ?;",
            params![bookmark_id, source],
        )?;
        for (name, norm) in &cleaned {
            tx.execute(
                "INSERT OR IGNORE INTO tags(name, normalized_name, created_at) VALUES (?, ?, ?);",
                params![name, norm, now],
            )?;
            let tag_id: i64 = tx.query_row(
                "SELECT id FROM tags WHERE normalized_name = ? LIMIT 1;",
                params![norm],
                |r| r.get(0),
            )?;
            tx.execute(
                "INSERT OR IGNORE INTO url_tags(bookmark_id, tag_id, source, confidence, created_at)
                 VALUES (?, ?, ?, ?, ?);",
                params![bookmark_id, tag_id, source, confidence, now],
            )?;
        }
        tx.commit()?;
        Ok(())
    }
}

fn migrate_2_to_3(conn: &Connection) -> Result<(), DbError> {
    // Single-row table (id pinned to 1) holding the fingerprint of the file the
    // session metadata was last captured against.
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS open_state (
           id           INTEGER PRIMARY KEY CHECK (id = 1),
           file_path    TEXT NOT NULL,
           content_hash TEXT NOT NULL,
           updated_at   TEXT NOT NULL
         );",
    )?;
    Ok(())
}

fn migrate_1_to_2(conn: &Connection) -> Result<(), DbError> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS bookmark_meta (
           bookmark_id   TEXT PRIMARY KEY NOT NULL,
           fetched_title TEXT NOT NULL DEFAULT '',
           fetched_at    TEXT NOT NULL
         );",
    )?;
    Ok(())
}

fn migrate_0_to_1(conn: &Connection) -> Result<(), DbError> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS tags (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           name TEXT NOT NULL,
           normalized_name TEXT NOT NULL,
           created_at TEXT NOT NULL
         );
         CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_normalized_name ON tags(normalized_name);
         CREATE TABLE IF NOT EXISTS url_tags (
           bookmark_id TEXT NOT NULL,
           tag_id INTEGER NOT NULL,
           source TEXT NOT NULL,
           confidence REAL,
           created_at TEXT NOT NULL,
           PRIMARY KEY (bookmark_id, tag_id),
           FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
         );
         CREATE INDEX IF NOT EXISTS idx_url_tags_bookmark_id ON url_tags(bookmark_id);
         CREATE INDEX IF NOT EXISTS idx_url_tags_tag_id ON url_tags(tag_id);",
    )?;
    Ok(())
}

fn normalize_tag(name: &str) -> String {
    // Mirrors core/util_core.py::normalize_tag — lowercase + trim, no other
    // canonicalization (PySide6 uses casefold; ascii lowercase is good enough
    // for the small tag corpus this app produces).
    name.trim().to_lowercase()
}

fn normalize_tags(input: &[String]) -> Vec<(String, String)> {
    let mut seen = std::collections::HashSet::<String>::new();
    let mut out = Vec::new();
    for t in input {
        let name = t.trim();
        if name.is_empty() {
            continue;
        }
        let norm = normalize_tag(name);
        if norm.is_empty() || !seen.insert(norm.clone()) {
            continue;
        }
        out.push((name.to_string(), norm));
    }
    out
}

fn iso_now() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    // ISO-ish; just enough for the column. We avoid pulling chrono.
    format!("{}", secs)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn migrate_and_round_trip() {
        let tmp = tempfile_path();
        let db = Db::open(&tmp).unwrap();
        db.save_tags_for_url("b1", &["Dev".into(), "Tools".into()], "manual", None)
            .unwrap();
        let tags = db.get_tags("b1").unwrap();
        assert_eq!(tags.len(), 2);
        assert!(tags.iter().any(|t| t.name == "Dev"));
        // Replacing for same source removes prior entries.
        db.save_tags_for_url("b1", &["Solo".into()], "manual", None)
            .unwrap();
        let tags = db.get_tags("b1").unwrap();
        assert_eq!(tags.len(), 1);
        assert_eq!(tags[0].name, "Solo");
        std::fs::remove_file(&tmp).ok();
    }

    #[test]
    fn open_state_round_trips() {
        let tmp = tempfile_path();
        let db = Db::open(&tmp).unwrap();
        assert_eq!(db.get_open_state().unwrap(), None);
        db.set_open_state("C:/bm.html", "deadbeef").unwrap();
        assert_eq!(
            db.get_open_state().unwrap(),
            Some(("C:/bm.html".into(), "deadbeef".into()))
        );
        // Single-row: a second set overwrites, never appends.
        db.set_open_state("C:/other.html", "cafef00d").unwrap();
        assert_eq!(
            db.get_open_state().unwrap(),
            Some(("C:/other.html".into(), "cafef00d".into()))
        );
        std::fs::remove_file(&tmp).ok();
    }

    #[test]
    fn clear_session_data_wipes_meta_and_tags() {
        let tmp = tempfile_path();
        let db = Db::open(&tmp).unwrap();
        db.save_meta("b1", "Fetched Title").unwrap();
        db.save_tags_for_url("b1", &["Dev".into()], "manual", None).unwrap();
        assert!(db.get_meta("b1").unwrap().is_some());
        assert_eq!(db.get_tags("b1").unwrap().len(), 1);

        db.clear_session_data().unwrap();
        assert!(db.get_meta("b1").unwrap().is_none());
        assert_eq!(db.get_tags("b1").unwrap().len(), 0);
        std::fs::remove_file(&tmp).ok();
    }

    #[test]
    fn dedup_normalizes_case() {
        let pairs = normalize_tags(&["Dev".into(), "DEV".into(), "dev".into()]);
        assert_eq!(pairs.len(), 1);
    }

    fn tempfile_path() -> PathBuf {
        let mut p = std::env::temp_dir();
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        p.push(format!("nbm-test-{stamp}.db"));
        p
    }
}
