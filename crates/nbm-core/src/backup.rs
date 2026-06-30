//! Generational backup with pre-restore safety snapshots.
//!
//! Mirrors `OriginalPythonCodes/core/UtilBackupManager.py`. Each generation is
//! `backups/YYYYMMDD_HHMMSS/` containing the three target files atomically
//! moved from a temp dir. Before a restore, we dump the current state into
//! `backups/_pre_restore_safety/YYYYMMDD_HHMMSS/`.

use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug, thiserror::Error)]
pub enum BackupError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("missing target: {0}")]
    MissingTarget(String),
    #[error("incomplete backup: {0}")]
    Incomplete(String),
}

#[derive(Debug, Clone)]
pub struct BackupTargets {
    pub bookmarks_html: PathBuf,
    pub user_data_db: PathBuf,
    pub config_ini: PathBuf,
}

impl BackupTargets {
    fn paths(&self) -> [&Path; 3] {
        [
            self.bookmarks_html.as_path(),
            self.user_data_db.as_path(),
            self.config_ini.as_path(),
        ]
    }
}

#[derive(Clone)]
pub struct BackupManager {
    pub backups_dir: PathBuf,
    pub keep_generations: usize,
}

impl BackupManager {
    pub fn new(project_root: impl AsRef<Path>, keep_generations: usize) -> Self {
        Self {
            backups_dir: project_root.as_ref().join("backups"),
            keep_generations,
        }
    }

    /// All non-safety generation directories, newest first.
    pub fn list_backups(&self) -> Vec<PathBuf> {
        if !self.backups_dir.exists() {
            return Vec::new();
        }
        let mut dirs: Vec<PathBuf> = match fs::read_dir(&self.backups_dir) {
            Ok(rd) => rd
                .filter_map(|r| r.ok())
                .map(|e| e.path())
                .filter(|p| p.is_dir() && p.file_name().map(|n| n != "_pre_restore_safety").unwrap_or(false))
                .collect(),
            Err(_) => return Vec::new(),
        };
        dirs.sort_by(|a, b| b.file_name().cmp(&a.file_name()));
        dirs
    }

    pub fn create_backup(&self, t: &BackupTargets) -> Result<PathBuf, BackupError> {
        validate_exists(t)?;
        fs::create_dir_all(&self.backups_dir)?;
        let stamp = timestamp_dirname();
        let final_dir = self.backups_dir.join(&stamp);
        let tmp_dir = self.backups_dir.join(format!("._tmp_{stamp}"));
        if tmp_dir.exists() {
            fs::remove_dir_all(&tmp_dir).ok();
        }
        fs::create_dir_all(&tmp_dir)?;

        let result = (|| -> Result<(), BackupError> {
            for src in t.paths() {
                let name = src.file_name().ok_or_else(|| {
                    BackupError::MissingTarget(src.display().to_string())
                })?;
                fs::copy(src, tmp_dir.join(name))?;
            }
            fs::rename(&tmp_dir, &final_dir)?;
            Ok(())
        })();
        if let Err(e) = result {
            fs::remove_dir_all(&tmp_dir).ok();
            return Err(e);
        }

        self.cleanup_generations()?;
        Ok(final_dir)
    }

    pub fn restore_backup(
        &self,
        backup_dir: &Path,
        t: &BackupTargets,
    ) -> Result<(), BackupError> {
        if !backup_dir.is_dir() {
            return Err(BackupError::Incomplete(backup_dir.display().to_string()));
        }
        for name in t.paths().iter().filter_map(|p| p.file_name()) {
            if !backup_dir.join(name).exists() {
                return Err(BackupError::Incomplete(format!(
                    "{}/{}",
                    backup_dir.display(),
                    Path::new(name).display()
                )));
            }
        }

        // Pre-restore safety snapshot — only if all targets currently exist.
        validate_exists(t)?;
        let safety = self
            .backups_dir
            .join("_pre_restore_safety")
            .join(timestamp_dirname());
        fs::create_dir_all(&safety)?;
        for src in t.paths() {
            let name = src.file_name().unwrap();
            fs::copy(src, safety.join(name))?;
        }

        // Now copy backup over targets.
        for dst in t.paths() {
            let name = dst.file_name().unwrap();
            fs::copy(backup_dir.join(name), dst)?;
        }
        Ok(())
    }

    fn cleanup_generations(&self) -> Result<(), BackupError> {
        if self.keep_generations == 0 {
            return Ok(());
        }
        let dirs = self.list_backups();
        if dirs.len() <= self.keep_generations {
            return Ok(());
        }
        for old in &dirs[self.keep_generations..] {
            fs::remove_dir_all(old)?;
        }
        Ok(())
    }
}

fn validate_exists(t: &BackupTargets) -> Result<(), BackupError> {
    for p in t.paths() {
        if !p.exists() {
            return Err(BackupError::MissingTarget(p.display().to_string()));
        }
    }
    Ok(())
}

fn timestamp_dirname() -> String {
    // YYYYMMDD_HHMMSS in UTC. We don't pull chrono in just for this.
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let (y, mo, d, h, mi, s) = unix_to_ymdhms(secs);
    format!("{y:04}{mo:02}{d:02}_{h:02}{mi:02}{s:02}")
}

fn unix_to_ymdhms(secs: u64) -> (u32, u32, u32, u32, u32, u32) {
    // Simple UTC conversion good enough for filename stamps.
    let days = secs / 86_400;
    let s = secs % 86_400;
    let h = (s / 3600) as u32;
    let mi = ((s % 3600) / 60) as u32;
    let sec = (s % 60) as u32;
    let (y, mo, d) = days_to_ymd(days as i64);
    (y, mo, d, h, mi, sec)
}

fn days_to_ymd(mut days: i64) -> (u32, u32, u32) {
    // Epoch is 1970-01-01.
    let mut year: i32 = 1970;
    loop {
        let dy = if is_leap(year) { 366 } else { 365 };
        if days < dy {
            break;
        }
        days -= dy;
        year += 1;
    }
    let mdays = [31, if is_leap(year) { 29 } else { 28 }, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    let mut month = 1u32;
    for &dm in &mdays {
        if days < dm {
            break;
        }
        days -= dm;
        month += 1;
    }
    (year as u32, month, (days as u32) + 1)
}

fn is_leap(y: i32) -> bool {
    (y % 4 == 0 && y % 100 != 0) || y % 400 == 0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_dates_round_trip() {
        // 2024-01-01 00:00:00 UTC = 1704067200
        let (y, mo, d, h, mi, s) = unix_to_ymdhms(1704067200);
        assert_eq!((y, mo, d, h, mi, s), (2024, 1, 1, 0, 0, 0));
        let (y, mo, d, _, _, _) = unix_to_ymdhms(1709251200); // 2024-03-01
        assert_eq!((y, mo, d), (2024, 3, 1));
    }
}
