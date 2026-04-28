"""
DatabaseManager

SQLite DB schema versioning & migration gate.

Spec: AI機能実装計画.md
- schema_version table (Must)
- sequential migrations (Must)
- db_version > CURRENT_VERSION => refuse to run (Must)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from core.util_core import normalize_tag

from core.UtilBackupManager import BackupManager, BackupTargets, BackupError


class DatabaseVersionError(RuntimeError):
    pass


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabasePaths:
    db_path: Path


class DatabaseManager:
    CURRENT_VERSION = 1

    def __init__(self, *, project_root: Path, db_filename: str = "user_data.db") -> None:
        self.project_root = Path(project_root)
        self.paths = DatabasePaths(db_path=self.project_root / db_filename)

    def connect(self) -> sqlite3.Connection:
        self.paths.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.paths.db_path))
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def ensure_compatible(self) -> None:
        """
        Ensure schema_version exists and DB is not newer than CURRENT_VERSION.
        Creates DB if missing.

        Note: マイグレーション自体は、3点セットバックアップを作れるタイミング
        （bookmarks.html が確定した後）に実行する。
        """
        with self.connect() as conn:
            self._ensure_schema_version_table(conn)
            ver = self._get_db_version(conn)
            if ver is None:
                # 0 = empty/initial (migrations will create tables)
                self._set_db_version(conn, 0)
                ver = 0
            if ver > self.CURRENT_VERSION:
                raise DatabaseVersionError(
                    f"DB version {ver} is newer than app supports ({self.CURRENT_VERSION}). Please update the app."
                )

    def migrate_if_needed(
        self,
        *,
        bookmarks_html: Path,
        config_ini: Path,
        keep_generations: int = 30,
    ) -> None:
        """
        Run sequential migrations with safety:
        - Start only after creating 3-target backup (Must)
        - On migration failure, restore user_data.db from the backup and abort (Must)
        """
        bookmarks_html = Path(bookmarks_html)
        config_ini = Path(config_ini)

        with self.connect() as conn:
            self._ensure_schema_version_table(conn)
            ver = self._get_db_version(conn)
            if ver is None:
                self._set_db_version(conn, 0)
                ver = 0
            if ver > self.CURRENT_VERSION:
                raise DatabaseVersionError(
                    f"DB version {ver} is newer than app supports ({self.CURRENT_VERSION}). Please update the app."
                )
            if ver == self.CURRENT_VERSION:
                return

        # Must: backup before migration
        project_root = self.project_root
        bm = BackupManager(project_root=project_root, keep_generations=keep_generations)
        targets = BackupTargets(
            bookmarks_html=bookmarks_html,
            user_data_db=self.paths.db_path,
            config_ini=config_ini,
        )
        try:
            backup_dir = bm.create_backup(targets)
        except BackupError as exc:
            raise MigrationError(f"Backup failed; cannot migrate: {exc}") from exc

        try:
            with self.connect() as conn:
                self._migrate_sequential(conn)
        except Exception as exc:
            # Must: restore DB from backup and abort
            try:
                bm.restore_backup(backup_dir=backup_dir, targets=targets)
            except Exception as restore_exc:
                raise MigrationError(f"Migration failed AND restore failed: {restore_exc}") from exc
            raise MigrationError(f"Migration failed; DB restored from backup: {exc}") from exc

    def _migrate_sequential(self, conn: sqlite3.Connection) -> None:
        ver = self._get_db_version(conn)
        if ver is None:
            self._set_db_version(conn, 0)
            ver = 0

        # Apply migrations: 0 -> 1
        while ver < self.CURRENT_VERSION:
            next_ver = ver + 1
            if ver == 0 and next_ver == 1:
                self._migration_0_to_1(conn)
            else:
                raise MigrationError(f"No migration path: {ver} -> {next_ver}")
            self._set_db_version(conn, next_ver)
            ver = next_ver

    def _migration_0_to_1(self, conn: sqlite3.Connection) -> None:
        """
        Initial schema for tags (Phase 1 safety spec section 3).
        Note: bookmark_id based linkage is prepared; actual ID assignment is handled elsewhere.
        """
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tags (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              normalized_name TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_normalized_name ON tags(normalized_name);")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS url_tags (
              bookmark_id TEXT NOT NULL,
              tag_id INTEGER NOT NULL,
              source TEXT NOT NULL,
              confidence REAL,
              created_at TEXT NOT NULL,
              PRIMARY KEY (bookmark_id, tag_id),
              FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_url_tags_bookmark_id ON url_tags(bookmark_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_url_tags_tag_id ON url_tags(tag_id);")
        conn.commit()

    # ----------------------------- Tags (local) ------------------------------
    def _ensure_tags_schema(self, conn: sqlite3.Connection) -> None:
        """tags/url_tags の存在を保証（migrate未実行でも壊れないよう安全側）。"""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tags (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              normalized_name TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_normalized_name ON tags(normalized_name);")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS url_tags (
              bookmark_id TEXT NOT NULL,
              tag_id INTEGER NOT NULL,
              source TEXT NOT NULL,
              confidence REAL,
              created_at TEXT NOT NULL,
              PRIMARY KEY (bookmark_id, tag_id),
              FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_url_tags_bookmark_id ON url_tags(bookmark_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_url_tags_tag_id ON url_tags(tag_id);")

    def save_tags_for_url(
        self,
        *,
        bookmark_id: str,
        tags: List[str],
        source: str = "rule",
        confidence: Optional[float] = None,
    ) -> None:
        """
        Spec: ServiceAutoTag はこのAPI経由で保存すること。
        ここでは url_tags のキーは bookmark_id である（URL文字列主キーは禁止）。
        """
        if not bookmark_id:
            raise ValueError("bookmark_id is required")

        # normalize & unique
        cleaned = []
        seen = set()
        for t in tags or []:
            name = (t or "").strip()
            if not name:
                continue
            norm = normalize_tag(name)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            cleaned.append((name, norm))

        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            self._ensure_tags_schema(conn)
            conn.execute("BEGIN;")
            conn.execute("DELETE FROM url_tags WHERE bookmark_id = ? AND source = ?;", (bookmark_id, source))
            tag_ids = []
            for name, norm in cleaned:
                conn.execute(
                    "INSERT OR IGNORE INTO tags(name, normalized_name, created_at) VALUES (?, ?, ?);",
                    (name, norm, now),
                )
                row = conn.execute("SELECT id FROM tags WHERE normalized_name = ? LIMIT 1;", (norm,)).fetchone()
                if row:
                    tag_ids.append(int(row[0]))

            for tid in tag_ids:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO url_tags(bookmark_id, tag_id, source, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (bookmark_id, tid, source, confidence, now),
                )
            conn.commit()

    def _ensure_schema_version_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
              version INTEGER NOT NULL
            );
            """
        )

    def _get_db_version(self, conn: sqlite3.Connection) -> Optional[int]:
        cur = conn.execute("SELECT version FROM schema_version LIMIT 1;")
        row = cur.fetchone()
        return int(row[0]) if row else None

    def _set_db_version(self, conn: sqlite3.Connection, version: int) -> None:
        conn.execute("DELETE FROM schema_version;")
        conn.execute("INSERT INTO schema_version(version) VALUES (?);", (int(version),))
        conn.commit()

