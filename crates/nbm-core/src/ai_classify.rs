//! AI bookmark classification using Gemini REST API.
//!
//! Mirrors `OriginalPythonCodes/services/ServiceAiClassifier.py`:
//! - Chunk processing (default 40 items per request)
//! - JSON schema validation with one retry on parse failure
//! - Exponential backoff for 429/5xx (max 3 attempts)
//! - URL sanitization: drop query string before sending to Gemini
//! - Minimum group size ≥ 2 (singletons → largest group or "Unsorted")
//! - Results placed under `/_AI/` folder prefix

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

// Note: call_gemini_batch lives in nbm-server (needs async reqwest + json feature).

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct BookmarkItem {
    pub bookmark_id: String,
    pub title: String,
    pub url: String,
    /// Rule-generated tags (may be empty). Sent to the model only when the
    /// caller includes "tags" in the field selection.
    #[serde(default)]
    pub tags: Vec<String>,
    /// Bookmark description (may be empty). Sent only when "description" is
    /// selected — it is the most token-heavy field.
    #[serde(default)]
    pub description: String,
}

/// Which textual fields to include in the payload sent to the model.
/// Lets the user trade tokens for accuracy from the UI.
#[derive(Debug, Clone, Copy)]
pub struct FieldSelection {
    pub title: bool,
    pub url: bool,
    pub tags: bool,
    pub description: bool,
}

impl Default for FieldSelection {
    fn default() -> Self {
        // Token-lean default matching the "tags-centric" design.
        Self { title: true, url: true, tags: true, description: false }
    }
}

/// A single AI-suggested move.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AiMove {
    pub bookmark_id: String,
    /// Folder name (relative, without `/_AI/` prefix — server adds it).
    pub folder: String,
    pub confidence: f64,
    pub reason: String,
}

/// Progress event sent over SSE.
#[derive(Debug, Clone, Serialize)]
pub struct ClassifyProgress {
    pub processed: usize,
    pub total: usize,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub chunk_moves: Option<Vec<AiMove>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    /// Estimated cost info (only on first event).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cost_estimate: Option<CostEstimate>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CostEstimate {
    pub items: usize,
    pub chunks: usize,
    pub input_tokens_est: usize,
    pub output_tokens_low: usize,
    pub output_tokens_high: usize,
    /// USD estimate (None if pricing not configured)
    pub input_cost_usd: Option<f64>,
    pub output_cost_usd_low: Option<f64>,
    pub output_cost_usd_high: Option<f64>,
}

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

#[allow(dead_code)]
fn sanitize_url(url: &str) -> String {
    if let Some(rest) = url.split_once('?') {
        // Keep scheme + authority + path, drop query+fragment.
        let base = rest.0;
        if let Some(frag) = base.split_once('#') { return frag.0.to_string(); }
        return base.to_string();
    }
    if let Some(frag) = url.split_once('#') { return frag.0.to_string(); }
    url.to_string()
}

#[allow(dead_code)]
fn extract_domain(url: &str) -> String {
    let after = url
        .strip_prefix("https://")
        .or_else(|| url.strip_prefix("http://"))
        .unwrap_or(url);
    let netloc = after.split('/').next().unwrap_or("").to_lowercase();
    let netloc = netloc.split(':').next().unwrap_or("").to_string();
    netloc.strip_prefix("www.").map(str::to_string).unwrap_or(netloc)
}

// ---------------------------------------------------------------------------
// Cost estimation
// ---------------------------------------------------------------------------

pub fn estimate_cost(
    items: &[BookmarkItem],
    prompt_len: usize,
    chunk_size: usize,
    in_price_per_1m: Option<f64>,
    out_price_per_1m: Option<f64>,
) -> CostEstimate {
    let tok = |n: usize| n.div_ceil(4).max(1);
    let prompt_tokens = tok(prompt_len);
    let chunks = items.len().div_ceil(chunk_size.max(1));
    let data_tokens: usize = items
        .chunks(chunk_size.max(1))
        .map(|batch| batch.iter().map(|b| tok(b.title.len() + b.url.len() + 40)).sum::<usize>())
        .sum();
    let input_tokens_est = prompt_tokens + data_tokens;
    let n = items.len();
    let out_low = 40 * n;
    let out_high = 120 * n;

    let (input_cost_usd, output_cost_usd_low, output_cost_usd_high) =
        match (in_price_per_1m, out_price_per_1m) {
            (Some(ip), Some(op)) if ip > 0.0 && op > 0.0 => (
                Some(input_tokens_est as f64 / 1_000_000.0 * ip),
                Some(out_low as f64 / 1_000_000.0 * op),
                Some(out_high as f64 / 1_000_000.0 * op),
            ),
            _ => (None, None, None),
        };

    CostEstimate {
        items: n,
        chunks,
        input_tokens_est,
        output_tokens_low: out_low,
        output_tokens_high: out_high,
        input_cost_usd,
        output_cost_usd_low,
        output_cost_usd_high,
    }
}

// ---------------------------------------------------------------------------
// Build prompt
// ---------------------------------------------------------------------------

const PROMPT_TEMPLATE: &str = include_str!("../../../config/prompt.txt");

const SCHEMA_OVERRIDE: &str = r#"

CRITICAL OUTPUT RULES (SAFETY OVERRIDE):
- Output VALID JSON ONLY. No code fences, no extra text.
- Return exactly this schema:
{"moves":[{"index":0,"folder":"FolderName","confidence":0.92,"reason":"short reason"}]}
- confidence: 0.0 to 1.0
- reason: short and specific
- Only include moves you are confident about; if none, return {"moves":[]}.
"#;

pub fn build_prompt(priority_terms: &[String], custom_prompt: Option<&str>) -> String {
    let terms_str = priority_terms
        .iter()
        .map(|t| format!("\"{t}\""))
        .collect::<Vec<_>>()
        .join(", ");
    let mut prompt = PROMPT_TEMPLATE
        .replace("{priority_terms_placeholder}", &terms_str);
    prompt.push_str(SCHEMA_OVERRIDE);
    if let Some(custom) = custom_prompt {
        prompt = format!("USER OVERRIDE INSTRUCTIONS:\n{custom}\n\n{prompt}");
    }
    prompt
}

// ---------------------------------------------------------------------------
// Minimum group size enforcement (mirrors Python logic)
// ---------------------------------------------------------------------------

pub fn enforce_min_group_size(moves: Vec<AiMove>) -> Vec<AiMove> {
    if moves.is_empty() { return moves; }

    let mut counts: HashMap<String, usize> = HashMap::new();
    for m in &moves { *counts.entry(m.folder.clone()).or_insert(0) += 1; }

    let large: Vec<_> = counts.iter().filter(|(_, &c)| c >= 2).map(|(f, _)| f.clone()).collect();
    let small: std::collections::HashSet<_> = counts.iter().filter(|(_, &c)| c < 2).map(|(f, _)| f.clone()).collect();

    if small.is_empty() { return moves; }

    let target = if large.is_empty() {
        "Unsorted".to_string()
    } else {
        large.into_iter().max_by_key(|f| counts[f]).unwrap()
    };

    moves
        .into_iter()
        .map(|mut m| {
            if small.contains(&m.folder) { m.folder = target.clone(); }
            m
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sanitize_drops_query() {
        assert_eq!(sanitize_url("https://example.com/path?q=1&r=2"), "https://example.com/path");
    }

    #[test]
    fn sanitize_drops_fragment() {
        assert_eq!(sanitize_url("https://example.com/path#section"), "https://example.com/path");
    }

    #[test]
    fn sanitize_clean_url() {
        assert_eq!(sanitize_url("https://example.com/path"), "https://example.com/path");
    }

    #[test]
    fn min_group_singleton_to_largest() {
        let moves = vec![
            AiMove { bookmark_id: "a".into(), folder: "Big".into(), confidence: 0.9, reason: "x".into() },
            AiMove { bookmark_id: "b".into(), folder: "Big".into(), confidence: 0.9, reason: "x".into() },
            AiMove { bookmark_id: "c".into(), folder: "Small".into(), confidence: 0.9, reason: "x".into() },
        ];
        let result = enforce_min_group_size(moves);
        assert!(result.iter().all(|m| m.folder == "Big"), "{result:?}");
    }

    #[test]
    fn min_group_all_singletons_to_unsorted() {
        let moves = vec![
            AiMove { bookmark_id: "a".into(), folder: "X".into(), confidence: 0.9, reason: "x".into() },
            AiMove { bookmark_id: "b".into(), folder: "Y".into(), confidence: 0.9, reason: "x".into() },
        ];
        let result = enforce_min_group_size(moves);
        assert!(result.iter().all(|m| m.folder == "Unsorted"), "{result:?}");
    }

    #[test]
    fn cost_estimate_sanity() {
        let items: Vec<BookmarkItem> = (0..100)
            .map(|i| BookmarkItem {
                bookmark_id: i.to_string(),
                title: "Test".into(),
                url: "https://example.com".into(),
                ..Default::default()
            })
            .collect();
        let est = estimate_cost(&items, 500, 40, None, None);
        assert_eq!(est.chunks, 3);
        assert!(est.input_tokens_est > 0);
    }
}
