"""
ServiceTags - local tag management using user_data.db.

Stores manual tags in:
- tags(id, name, normalized_name, created_at)
- url_tags(bookmark_id, tag_id, source, confidence, created_at)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.UtilLogger import logger
from core.UtilSafety import normalize_tag


@dataclass(frozen=True)
class TagRecord:
    name: str
    normalized_name: str


@dataclass(frozen=True)
class TagDetail:
    name: str
    source: str
    confidence: Optional[float] = None


class TagService:
    def __init__(self, *, project_root: Path, db_filename: str = "user_data.db") -> None:
        self.project_root = Path(project_root)
        self.db_path = self.project_root / db_filename

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def get_tags(self, bookmark_id: str) -> List[str]:
        if not bookmark_id:
            return []
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT t.name
                FROM url_tags ut
                JOIN tags t ON t.id = ut.tag_id
                WHERE ut.bookmark_id = ?
                ORDER BY t.normalized_name ASC;
                """,
                (bookmark_id,),
            )
            return [r[0] for r in cur.fetchall()]

    def get_tag_details(self, bookmark_id: str) -> List[TagDetail]:
        """タグ名＋source（manual/rule/ai 等）＋confidence を返す。"""
        if not bookmark_id:
            return []
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT t.name, ut.source, ut.confidence
                FROM url_tags ut
                JOIN tags t ON t.id = ut.tag_id
                WHERE ut.bookmark_id = ?
                ORDER BY ut.source ASC, t.normalized_name ASC;
                """,
                (bookmark_id,),
            )
            out: List[TagDetail] = []
            for name, source, conf in cur.fetchall():
                out.append(TagDetail(name=name, source=source or "", confidence=conf))
            return out

    def set_tags(self, bookmark_id: str, tags: List[str], *, source: str = "manual") -> None:
        """
        Replace tags for bookmark_id for the given source.
        """
        if not bookmark_id:
            raise ValueError("bookmark_id is required")

        # normalize & unique
        cleaned: List[TagRecord] = []
        seen = set()
        for t in tags or []:
            name = (t or "").strip()
            if not name:
                continue
            norm = normalize_tag(name)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            cleaned.append(TagRecord(name=name, normalized_name=norm))

        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute("BEGIN;")
            # remove existing tags for this source
            conn.execute("DELETE FROM url_tags WHERE bookmark_id = ? AND source = ?;", (bookmark_id, source))

            # ensure tags exist
            tag_ids: List[int] = []
            for rec in cleaned:
                conn.execute(
                    "INSERT OR IGNORE INTO tags(name, normalized_name, created_at) VALUES (?, ?, ?);",
                    (rec.name, rec.normalized_name, now),
                )
                cur = conn.execute("SELECT id, name FROM tags WHERE normalized_name = ? LIMIT 1;", (rec.normalized_name,))
                row = cur.fetchone()
                if not row:
                    continue
                tag_ids.append(int(row[0]))

            # link
            for tid in tag_ids:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO url_tags(bookmark_id, tag_id, source, confidence, created_at)
                    VALUES (?, ?, ?, NULL, ?);
                    """,
                    (bookmark_id, tid, source, now),
                )
            conn.commit()

        logger.info(f"Set {len(cleaned)} tag(s) for bookmark_id={bookmark_id}")

