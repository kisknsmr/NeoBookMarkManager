"""
UtilBackupManager

AI/一括整理など「破壊的変更」の直前に必ずバックアップを作成し、
復元（Undo / 世代選択）も提供するためのユーティリティ。

Spec: AI機能実装計画.md (Backup & Restore)
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupTargets:
    bookmarks_html: Path
    user_data_db: Path
    config_ini: Path


class BackupManager:
    def __init__(self, *, project_root: Path, keep_generations: int = 30) -> None:
        self.project_root = Path(project_root)
        self.backups_dir = self.project_root / "backups"
        self.keep_generations = int(keep_generations)

    def _ts_dirname(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _validate_targets(self, targets: BackupTargets) -> None:
        missing = [p for p in (targets.bookmarks_html, targets.user_data_db, targets.config_ini) if not p.exists()]
        if missing:
            raise BackupError(f"Backup target missing: {', '.join(str(p) for p in missing)}")

    def list_backups(self) -> list[Path]:
        if not self.backups_dir.exists():
            return []
        dirs = [p for p in self.backups_dir.iterdir() if p.is_dir() and p.name != "_pre_restore_safety"]
        return sorted(dirs, key=lambda p: p.name, reverse=True)

    def create_backup(self, targets: BackupTargets) -> Path:
        """
        Create backups/YYYYMMDD_HHMMSS/ and copy the 3 target files into it.
        MUST: If backup creation fails, caller must abort the destructive operation.
        """
        self._validate_targets(targets)

        self.backups_dir.mkdir(parents=True, exist_ok=True)
        backup_dir = self.backups_dir / self._ts_dirname()
        tmp_dir = self.backups_dir / f"._tmp_{backup_dir.name}"

        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=False)

        try:
            shutil.copy2(targets.bookmarks_html, tmp_dir / targets.bookmarks_html.name)
            shutil.copy2(targets.user_data_db, tmp_dir / targets.user_data_db.name)
            shutil.copy2(targets.config_ini, tmp_dir / targets.config_ini.name)
            tmp_dir.rename(backup_dir)
        except Exception as exc:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise BackupError(f"Failed to create backup: {exc}") from exc

        # Cleanup old generations (keep latest N). Spec: failure is an error.
        self._cleanup_generations()
        return backup_dir

    def _cleanup_generations(self) -> None:
        if self.keep_generations <= 0:
            return
        dirs = self.list_backups()
        if len(dirs) <= self.keep_generations:
            return
        to_delete = dirs[self.keep_generations :]
        errors: list[str] = []
        for d in to_delete:
            try:
                shutil.rmtree(d)
            except Exception as exc:
                errors.append(f"{d}: {exc}")
        if errors:
            raise BackupError("Failed to cleanup old backups:\n" + "\n".join(errors))

    def restore_backup(self, *, backup_dir: Path, targets: BackupTargets) -> None:
        """
        Restore the 3 target files from backup_dir.
        Spec:
        1) Move current targets into backups/_pre_restore_safety/YYYYMMDD_HHMMSS/
        2) Copy selected backup -> destination paths
        """
        backup_dir = Path(backup_dir)
        if not backup_dir.exists() or not backup_dir.is_dir():
            raise BackupError(f"Backup directory not found: {backup_dir}")

        # Validate backup contains required files
        src_html = backup_dir / targets.bookmarks_html.name
        src_db = backup_dir / targets.user_data_db.name
        src_ini = backup_dir / targets.config_ini.name
        missing = [p for p in (src_html, src_db, src_ini) if not p.exists()]
        if missing:
            raise BackupError(f"Backup is incomplete: {', '.join(str(p) for p in missing)}")

        # Pre-restore safety snapshot
        safety_root = self.backups_dir / "_pre_restore_safety" / self._ts_dirname()
        safety_root.mkdir(parents=True, exist_ok=False)
        try:
            # It's OK if destination paths don't exist (first run), but spec wants 3 files;
            # if missing, treat as error for restoration safety.
            self._validate_targets(targets)
            shutil.copy2(targets.bookmarks_html, safety_root / targets.bookmarks_html.name)
            shutil.copy2(targets.user_data_db, safety_root / targets.user_data_db.name)
            shutil.copy2(targets.config_ini, safety_root / targets.config_ini.name)
        except Exception as exc:
            raise BackupError(f"Failed to create pre-restore safety snapshot: {exc}") from exc

        # Restore
        try:
            shutil.copy2(src_html, targets.bookmarks_html)
            shutil.copy2(src_db, targets.user_data_db)
            shutil.copy2(src_ini, targets.config_ini)
        except Exception as exc:
            raise BackupError(f"Failed to restore backup: {exc}") from exc

