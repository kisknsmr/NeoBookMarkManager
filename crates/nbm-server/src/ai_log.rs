//! Plain-text log of AI classification runs.
//!
//! `/classify/ai` used to leave no trace beyond the SSE stream the browser
//! tab happened to be open for — a run that came back with zero moves left
//! nothing to look at afterward to tell "the model genuinely proposed
//! nothing" apart from "a bug ate the results". This appends a
//! human-readable record of every run (params, per-chunk outcome, final move
//! count) to `<config dir>/../logs/ai_classify.log` so it survives after the
//! fact. Logging is best-effort: a failure here must never fail the run.

use std::io::Write;
use std::path::{Path, PathBuf};

/// Where the log file lives, derived from the app's `config.ini` location
/// (`<root>/config/config.ini` → `<root>/logs/ai_classify.log`) so it sits
/// next to the portable app's `data/`/`config/`/`backups/` folders without
/// needing a separate config knob.
pub fn dir_from_config_path(config_ini_path: Option<&Path>) -> Option<PathBuf> {
    let root = config_ini_path?.parent()?.parent()?;
    Some(root.join("logs"))
}

/// Append one block of text to the log file, creating the directory/file as
/// needed. Swallows every error (logging must never break a classify run) but
/// prints a diagnostic to stderr so a permissions problem isn't invisible.
pub fn append(log_dir: Option<&Path>, block: &str) {
    let Some(dir) = log_dir else { return };
    if let Err(e) = std::fs::create_dir_all(dir) {
        eprintln!("[ai_log] create_dir_all({}) failed: {e}", dir.display());
        return;
    }
    let path = dir.join("ai_classify.log");
    let mut text = block.to_string();
    if !text.ends_with('\n') {
        text.push('\n');
    }
    match std::fs::OpenOptions::new().create(true).append(true).open(&path) {
        Ok(mut f) => {
            let _ = f.write_all(text.as_bytes());
        }
        Err(e) => eprintln!("[ai_log] open({}) failed: {e}", path.display()),
    }
}

/// Epoch-seconds timestamp string — matches `nbm_core::db`'s `iso_now`, kept
/// dependency-free rather than pulling in a datetime crate for one log line.
pub fn timestamp() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("{secs}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dir_is_the_config_root_sibling() {
        let cfg = Path::new("/portable/config/config.ini");
        assert_eq!(
            dir_from_config_path(Some(cfg)),
            Some(PathBuf::from("/portable/logs"))
        );
    }

    #[test]
    fn no_config_path_means_no_log() {
        assert_eq!(dir_from_config_path(None), None);
    }

    #[test]
    fn append_creates_the_file_and_keeps_earlier_lines() {
        let mut dir = std::env::temp_dir();
        dir.push(format!("nbm-ai-log-test-{}", timestamp()));
        append(Some(&dir), "first");
        append(Some(&dir), "second");
        let contents = std::fs::read_to_string(dir.join("ai_classify.log")).unwrap();
        assert_eq!(contents, "first\nsecond\n");
        std::fs::remove_dir_all(&dir).ok();
    }
}
