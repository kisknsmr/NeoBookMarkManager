//! Everything read out of `config.ini` (and the model price catalog).
//!
//! Collected in one module because these are all "look up a value the user may
//! or may not have configured, fall back to something sane" — the handlers just
//! consume the result.

use std::path::PathBuf;

use nbm_core::ConfigManager;

use crate::state::AppState;

/// Parse config.ini, if this install has one. A missing or unreadable file is
/// not an error here: every reader below falls back to a default.
fn config(state: &AppState) -> Option<ConfigManager> {
    let path = state.inner.config_ini_path.as_ref()?;
    ConfigManager::load(path).ok()
}

/// Read one `[section] option` from config.ini.
fn value(state: &AppState, section: &str, option: &str) -> Option<String> {
    config(state)?.get(section, option)
}

/// Split a comma-separated config value into trimmed, non-empty entries.
fn csv_entries(raw: &str) -> Vec<String> {
    raw.split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

/// The shipped model id, used when config.ini names none.
pub fn default_model() -> String { "gemini-2.5-flash-lite".to_string() }

/// Classifier hint terms the user configured ([Classifier] priority_terms).
pub fn priority_terms(state: &AppState) -> Vec<String> {
    config(state).map(|c| c.get_priority_terms()).unwrap_or_default()
}

/// The model the user picked ([AI] model), or the shipped default.
pub fn selected_model(state: &AppState) -> String {
    value(state, "AI", "model").unwrap_or_else(default_model)
}

/// Load exclude_patterns from [LinkCheck] dedupe_exclude_patterns in config.ini.
/// Entries are glob-style prefixes/substrings matched against the URL.
pub fn linkcheck_excludes(state: &AppState) -> Vec<String> {
    value(state, "LinkCheck", "exclude_patterns")
        .map(|v| csv_entries(&v))
        .unwrap_or_else(|| vec![
            "file://".into(),
            "javascript:".into(),
            "about:".into(),
        ])
}

/// Parallelism for title/description fetches. Reads [Network].concurrency,
/// falls back to [LinkCheck].concurrency, then 5. Clamped to 1..=20.
pub fn fetch_concurrency(state: &AppState) -> usize {
    let n = config(state)
        .and_then(|cfg| {
            cfg.get("Network", "concurrency")
                .or_else(|| cfg.get("LinkCheck", "concurrency"))
                .and_then(|v| v.trim().parse::<usize>().ok())
        })
        .unwrap_or(5);
    n.clamp(1, 20)
}

/// Timeout (seconds) and parallelism for the link checker, from [LinkCheck].
///
/// Note the asymmetric fallback, preserved from the original: with a config
/// file present but the keys absent the defaults are (5, 5), while with no
/// config file at all they are (10, 5).
pub fn linkcheck_limits(state: &AppState) -> (u64, usize) {
    config(state)
        .map(|cfg| {
            let timeout = cfg
                .get("LinkCheck", "timeout_secs")
                .and_then(|v| v.parse().ok())
                .unwrap_or(5u64);
            let concurrency = cfg
                .get("LinkCheck", "concurrency")
                .and_then(|v| v.parse().ok())
                .unwrap_or(5usize);
            (timeout, concurrency)
        })
        .unwrap_or((10, 5))
}

/// The configured proxy URL, if any ([Proxy] url).
pub fn proxy_url(state: &AppState) -> Option<String> {
    value(state, "Proxy", "url")
}

/// Read [Organize] dedupe_exclude_urls from config.ini.
/// Value is a comma-separated list of URLs to never treat as duplicates.
pub fn dedupe_exclude_urls(state: &AppState) -> std::collections::HashSet<String> {
    value(state, "Organize", "dedupe_exclude_urls")
        .map(|v| csv_entries(&v).into_iter().collect())
        .unwrap_or_default()
}

/// Load (input, output) USD price per 1M tokens from config.ini [AI].
/// Returns `Some(price)` only when the value parses to a number > 0.
pub fn config_ai_pricing(state: &AppState) -> (Option<f64>, Option<f64>) {
    let cfg = config(state);
    let read = |key: &str| cfg.as_ref()
        .and_then(|c| c.get("AI", key))
        .and_then(|s| s.trim().parse::<f64>().ok())
        .filter(|&v| v > 0.0);
    (read("input_cost_per_1m_tokens"), read("output_cost_per_1m_tokens"))
}

/// The shipped price table, compiled in so it is available even when no
/// models.json exists on disk (e.g. a portable install whose config/ directory
/// was bootstrapped without one). The on-disk file, when present, overrides it.
pub const DEFAULT_MODELS_JSON: &str = include_str!("../../../config/models.json");

/// models.json text plus whether it came from disk. Falling back to the
/// embedded copy keeps the cost gate working regardless of install layout —
/// previously a missing file meant "単価不明" and every AI run was blocked.
pub fn models_json_text(state: &AppState) -> (String, bool) {
    match std::fs::read_to_string(models_json_path(state)) {
        Ok(text) => (text, true),
        Err(_) => (DEFAULT_MODELS_JSON.to_string(), false),
    }
}

/// Resolve models.json, preferring the directory that holds config.ini.
fn models_json_path(state: &AppState) -> PathBuf {
    state.inner.config_ini_path.as_ref()
        .and_then(|p| p.parent())
        .map(|dir| dir.join("models.json"))
        .filter(|p| p.exists())
        .unwrap_or_else(|| PathBuf::from("config/models.json"))
}

/// Per-1M-token pricing for `model`, taken from models.json.
///
/// The catalog already carries a price for every model, so the estimate now
/// follows whichever model the user picked instead of a single pair of numbers
/// in config.ini that had no connection to the model actually being called.
/// config.ini remains the fallback for models missing from the catalog.
pub fn ai_pricing_for_model(state: &AppState, model: &str) -> (Option<f64>, Option<f64>) {
    let (i, o, _) = resolve_ai_pricing(state, model);
    (i, o)
}

/// Same as [`load_ai_pricing_for_model`] but also reports where the numbers
/// came from: "catalog" (models.json), "config" (config.ini) or "none".
/// The settings screen needs the source so it can stop claiming that an empty
/// config.ini blocks AI — it no longer does when the catalog has a price.
pub fn resolve_ai_pricing(state: &AppState, model: &str) -> (Option<f64>, Option<f64>, &'static str) {
    let from_catalog = serde_json::from_str::<serde_json::Value>(&models_json_text(state).0)
        .ok()
        .and_then(|v| {
            let entry = v.get("models")?
                .as_array()?
                .iter()
                .find(|m| m.get("id").and_then(|i| i.as_str()) == Some(model))?
                .clone();
            let inp = entry.get("input_per_1m")?.as_f64()?;
            let out = entry.get("output_per_1m")?.as_f64()?;
            (inp > 0.0 && out > 0.0).then_some((inp, out))
        });

    match from_catalog {
        Some((i, o)) => (Some(i), Some(o), "catalog"),
        None => match config_ai_pricing(state) {
            (Some(i), Some(o)) => (Some(i), Some(o), "config"),
            _ => (None, None, "none"),
        },
    }
}

/// Resolve the Gemini API key (env vars take precedence, then config.ini [API].api_key).
/// A placeholder/empty value counts as "not set".
pub fn api_key(state: &AppState) -> Option<String> {
    config(state)
        .and_then(|c| c.get_api_key())
        .or_else(|| std::env::var("GENAI_API_KEY").ok())
        .or_else(|| std::env::var("GOOGLE_API_KEY").ok())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty() && !s.starts_with('<'))
}

/// The key for a billing-enabled project, used only after the user agrees to
/// fall back to it.
///
/// A Gemini project is either on the free tier or has billing linked — the tier
/// is not something a single request can choose. So "try free first, then ask
/// about paid" means holding two keys from two projects.
pub fn paid_api_key(state: &AppState) -> Option<String> {
    value(state, "API", "paid_api_key")
        .or_else(|| std::env::var("GENAI_PAID_API_KEY").ok())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty() && !s.starts_with('<'))
}

/// Whether the user declared the primary key to be on the free tier.
/// `None` means undeclared — the UI then avoids asserting either way rather
/// than guessing, since being wrong is misleading in both directions.
pub fn free_tier_flag(state: &AppState) -> Option<bool> {
    value(state, "AI", "free_tier")
        .map(|s| s.trim().to_lowercase())
        .and_then(|s| match s.as_str() {
            "true" | "1" | "yes" => Some(true),
            "false" | "0" | "no" => Some(false),
            _ => None,
        })
}
