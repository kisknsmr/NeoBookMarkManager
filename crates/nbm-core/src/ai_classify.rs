//! AI bookmark classification using Gemini REST API.
//!
//! Mirrors `OriginalPythonCodes/services/ServiceAiClassifier.py`:
//! - Chunk processing (default 40 items per request)
//! - JSON schema validation with one retry on parse failure
//! - Exponential backoff for 429/5xx (max 3 attempts)
//! - URL sanitization: drop query string before sending to Gemini
//! - Minimum group size ≥ 2 for NEW folders; a singleton filed into a folder
//!   that already exists is kept, and any other singleton is dropped rather
//!   than swept into an unrelated folder
//! - Unclassifiable bookmarks get no move at all (no catch-all folder)
//! - Destinations are relative paths; the review UI decides where new folders
//!   are created (default: inside the folder the run was scoped to)

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
    /// Destination folder as a `/`-separated path relative to the tree root.
    /// May name an existing folder (a merge) or a new one; the review UI
    /// prefixes new folders with the run's base folder before applying.
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
    /// Bookmark ids belonging to a chunk that failed outright, so the UI can
    /// offer to re-run just those instead of silently losing them.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub failed_ids: Option<Vec<String>>,
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

/// Max chars kept per field when building the payload.
const TITLE_MAX: usize = 150;
const DESC_MAX: usize = 300;

/// Truncate to at most `max` chars on a UTF-8 boundary (avoids panics on
/// multibyte text like Japanese).
fn truncate_chars(s: &str, max: usize) -> String {
    s.chars().take(max).collect()
}

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
// Payload construction
// ---------------------------------------------------------------------------

/// Build the JSON object for one bookmark, exactly as it is sent to the model.
///
/// Both the request builder and the cost estimator go through this function so
/// the estimate can never drift from what is actually transmitted. (It used to
/// approximate every item as `title + url + 40` regardless of the field
/// selection, so turning on `description` changed the real cost but not the
/// number shown in the approval gate.)
pub fn build_item_json(
    b: &BookmarkItem,
    index: usize,
    fields: FieldSelection,
    sanitize_urls: bool,
) -> serde_json::Value {
    let mut obj = serde_json::Map::new();
    // index and domain are always sent: cheap, and the highest-signal fields.
    obj.insert("index".into(), serde_json::json!(index));
    obj.insert("domain".into(), serde_json::json!(extract_domain(&b.url)));
    if fields.title {
        obj.insert("title".into(), serde_json::json!(truncate_chars(&b.title, TITLE_MAX)));
    }
    if fields.url {
        let url = if sanitize_urls { sanitize_url(&b.url) } else { b.url.clone() };
        obj.insert("url".into(), serde_json::json!(url));
    }
    if fields.tags && !b.tags.is_empty() {
        obj.insert("tags".into(), serde_json::json!(b.tags));
    }
    if fields.description && !b.description.is_empty() {
        obj.insert("description".into(), serde_json::json!(truncate_chars(&b.description, DESC_MAX)));
    }
    serde_json::Value::Object(obj)
}

/// Serialize one chunk's payload — the `{"bookmarks":[...]}` blob appended
/// after the prompt text.
pub fn build_batch_payload(
    batch: &[BookmarkItem],
    fields: FieldSelection,
    sanitize_urls: bool,
) -> String {
    let items: Vec<serde_json::Value> = batch
        .iter()
        .enumerate()
        .map(|(i, b)| build_item_json(b, i, fields, sanitize_urls))
        .collect();
    serde_json::json!({ "bookmarks": items }).to_string()
}

// ---------------------------------------------------------------------------
// Cost estimation
// ---------------------------------------------------------------------------

pub fn estimate_cost(
    items: &[BookmarkItem],
    prompt_len: usize,
    chunk_size: usize,
    fields: FieldSelection,
    sanitize_urls: bool,
    in_price_per_1m: Option<f64>,
    out_price_per_1m: Option<f64>,
) -> CostEstimate {
    let tok = |n: usize| n.div_ceil(4).max(1);
    let chunk = chunk_size.max(1);
    let chunks = items.len().div_ceil(chunk);
    // The full prompt is re-sent with every chunk, so it counts `chunks` times.
    // Counting it once under-reported multi-chunk runs by a wide margin.
    let prompt_tokens = tok(prompt_len) * chunks.max(1);
    let data_tokens: usize = items
        .chunks(chunk)
        .map(|batch| tok(build_batch_payload(batch, fields, sanitize_urls).len()))
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

/// `known_folders` carries the folders that already exist in the tree plus
/// every folder produced by earlier chunks of the same run. Without it each
/// chunk names groups from scratch, so a 260-bookmark run split into 7 requests
/// happily invents "Development", "Dev Tools" and "Programming" in parallel.
pub fn build_prompt(
    priority_terms: &[String],
    custom_prompt: Option<&str>,
    known_folders: &[String],
) -> String {
    let terms_str = priority_terms
        .iter()
        .map(|t| format!("\"{t}\""))
        .collect::<Vec<_>>()
        .join(", ");
    let mut prompt = PROMPT_TEMPLATE
        .replace("{priority_terms_placeholder}", &terms_str);

    if !known_folders.is_empty() {
        let list = known_folders
            .iter()
            .map(|f| format!("- {f}"))
            .collect::<Vec<_>>()
            .join("\n");
        prompt.push_str(&format!(
            "\n\n**EXISTING FOLDER VOCABULARY (REUSE BEFORE INVENTING):**\n\
             These folders already exist in the user's tree, or were created by an\n\
             earlier batch of this same classification run. Entries may be\n\
             `/`-separated paths — reuse the full path when you reuse one:\n\
             {list}\n\
             - If a bookmark fits one of these, you MUST reuse the entry EXACTLY as written.\n\
             - Invent a new folder name only when none of the above is a reasonable fit.\n\
             - NEVER create a near-duplicate of a listed entry (e.g. \"Dev Tools\" or\n\
               \"Programming\" when \"Development\" is already listed).\n"
        ));
    }

    prompt.push_str(SCHEMA_OVERRIDE);
    if let Some(custom) = custom_prompt {
        prompt = format!("USER OVERRIDE INSTRUCTIONS:\n{custom}\n\n{prompt}");
    }
    prompt
}

// ---------------------------------------------------------------------------
// Folder-name canonicalization
// ---------------------------------------------------------------------------

/// Normalized key used to detect folder names that differ only in casing,
/// spacing or separators.
fn folder_key(s: &str) -> String {
    s.chars()
        .filter(|c| c.is_alphanumeric())
        .flat_map(|c| c.to_lowercase())
        .collect()
}

/// Collapse folder names that are the same word in different clothing —
/// "Dev Tools" / "dev-tools" / "DevTools" all become one folder.
///
/// Chunks are classified independently, so spelling drifts between requests
/// even when the model picks the same concept. The vocabulary passed through
/// [`build_prompt`] handles the semantic case; this handles the typographic
/// one. The most frequently used spelling wins (ties go to the shorter name).
pub fn canonicalize_folder_names(mut moves: Vec<AiMove>) -> Vec<AiMove> {
    if moves.is_empty() { return moves; }

    let mut variants: HashMap<String, HashMap<String, usize>> = HashMap::new();
    for m in &moves {
        *variants
            .entry(folder_key(&m.folder))
            .or_default()
            .entry(m.folder.clone())
            .or_insert(0) += 1;
    }

    let canonical: HashMap<String, String> = variants
        .into_iter()
        .filter_map(|(key, spellings)| {
            spellings
                .into_iter()
                .max_by(|a, b| a.1.cmp(&b.1).then_with(|| b.0.len().cmp(&a.0.len())))
                .map(|(name, _)| (key, name))
        })
        .collect();

    for m in &mut moves {
        if let Some(name) = canonical.get(&folder_key(&m.folder)) {
            m.folder = name.clone();
        }
    }
    moves
}

// ---------------------------------------------------------------------------
// Minimum group size enforcement (mirrors Python logic)
// ---------------------------------------------------------------------------

/// Normalize a model-provided destination into a safe relative folder path.
///
/// `/` is kept as a real separator: the prompt hands the model the full paths
/// of existing folders and asks it to reuse them, so "ブックマーク バー/ゲーム"
/// has to survive as two levels. It previously ran through
/// `folder.replace('/', "_")`, which collapsed every reused path into a single
/// junk folder at the top level — silently defeating the whole reuse feature.
///
/// Empty, `.` and `..` segments are dropped so a stray leading slash or `../`
/// cannot escape the tree, and characters that are illegal in folder titles are
/// replaced per segment.
pub fn sanitize_folder_path(raw: &str) -> String {
    raw.split('/')
        .map(str::trim)
        .filter(|seg| !seg.is_empty() && *seg != "." && *seg != "..")
        .map(|seg| seg.replace(['\\', ':', '*', '?', '"', '<', '>', '|'], "_"))
        .collect::<Vec<_>>()
        .join("/")
}

/// Folder names that mean "I could not classify this", plus the junk names the
/// prompt tells the model to avoid.
fn is_unsorted_sentinel(folder: &str) -> bool {
    let leaf = folder.rsplit('/').next().unwrap_or(folder);
    matches!(
        folder_key(leaf).as_str(),
        "" | "ungrouped" | "unsorted" | "uncategorized" | "unclassified"
            | "misc" | "miscellaneous" | "other" | "others" | "none" | "na"
            | "general" | "links" | "未分類" | "その他" | "分類不能"
    )
}

/// Drop moves whose destination is a "could not classify" marker.
///
/// The prompt asks the model to leave unclassifiable bookmarks as "ungrouped",
/// but nothing downstream treated that as a sentinel — it flowed through as an
/// ordinary folder name, so a run would end up proposing a large `ungrouped`
/// folder. A bookmark the model could not place should simply get no
/// suggestion.
pub fn drop_unsorted_sentinels(moves: Vec<AiMove>) -> Vec<AiMove> {
    moves.into_iter().filter(|m| !is_unsorted_sentinel(&m.folder)).collect()
}

/// Apply the "a new folder needs at least 2 bookmarks" rule.
///
/// `existing_folders` are folders that already exist in the user's tree; a
/// single bookmark filed into one of those is fine — the folder is not new.
///
/// Moves that fail the rule are **dropped**, not redirected. The previous
/// behaviour reassigned every singleton to whichever folder happened to be
/// largest, which silently filed bookmarks into unrelated folders — and when
/// the largest group was `ungrouped`, it swept the singletons in there too.
pub fn enforce_min_group_size(moves: Vec<AiMove>, existing_folders: &[String]) -> Vec<AiMove> {
    if moves.is_empty() { return moves; }

    let existing: std::collections::HashSet<String> =
        existing_folders.iter().map(|f| folder_key(f)).collect();

    let mut counts: HashMap<String, usize> = HashMap::new();
    for m in &moves { *counts.entry(m.folder.clone()).or_insert(0) += 1; }

    moves
        .into_iter()
        .filter(|m| counts[&m.folder] >= 2 || existing.contains(&folder_key(&m.folder)))
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
    /// A lone bookmark in a brand-new folder gets no suggestion — it must NOT
    /// be swept into whichever folder happens to be biggest.
    fn min_group_drops_singleton_in_new_folder() {
        let moves = vec![
            AiMove { bookmark_id: "a".into(), folder: "Big".into(), confidence: 0.9, reason: "x".into() },
            AiMove { bookmark_id: "b".into(), folder: "Big".into(), confidence: 0.9, reason: "x".into() },
            AiMove { bookmark_id: "c".into(), folder: "Small".into(), confidence: 0.9, reason: "x".into() },
        ];
        let result = enforce_min_group_size(moves, &[]);
        assert_eq!(result.len(), 2, "{result:?}");
        assert!(result.iter().all(|m| m.folder == "Big"), "{result:?}");
        assert!(!result.iter().any(|m| m.bookmark_id == "c"), "singleton must be dropped");
    }

    #[test]
    fn min_group_drops_all_singletons() {
        let moves = vec![
            AiMove { bookmark_id: "a".into(), folder: "X".into(), confidence: 0.9, reason: "x".into() },
            AiMove { bookmark_id: "b".into(), folder: "Y".into(), confidence: 0.9, reason: "x".into() },
        ];
        assert!(enforce_min_group_size(moves, &[]).is_empty());
    }

    #[test]
    /// Filing one bookmark into a folder that already exists is not "creating a
    /// folder for one item", so the rule must not drop it.
    fn min_group_keeps_singleton_for_existing_folder() {
        let moves = vec![
            AiMove { bookmark_id: "a".into(), folder: "Development".into(), confidence: 0.9, reason: "x".into() },
        ];
        let existing = vec!["Development".to_string()];
        let result = enforce_min_group_size(moves, &existing);
        assert_eq!(result.len(), 1, "{result:?}");
    }

    #[test]
    fn sanitize_keeps_nested_paths() {
        // The whole point: a reused existing path must stay nested.
        assert_eq!(sanitize_folder_path("Development/Rust"), "Development/Rust");
        assert_eq!(sanitize_folder_path("ブックマーク バー/ゲームカタログ"), "ブックマーク バー/ゲームカタログ");
    }

    #[test]
    fn sanitize_strips_traversal_and_empty_segments() {
        assert_eq!(sanitize_folder_path("/Development//Rust/"), "Development/Rust");
        assert_eq!(sanitize_folder_path("../../etc"), "etc");
        assert_eq!(sanitize_folder_path("./Dev"), "Dev");
        assert_eq!(sanitize_folder_path("   "), "");
        assert_eq!(sanitize_folder_path("/"), "");
    }

    #[test]
    fn sanitize_replaces_illegal_characters_per_segment() {
        assert_eq!(sanitize_folder_path("A:B/C*D"), "A_B/C_D");
        assert_eq!(sanitize_folder_path("we<b>/q?"), "we_b_/q_");
    }

    #[test]
    fn unsorted_sentinels_are_dropped() {
        let moves = vec![
            mv("a", "ungrouped"),
            mv("b", "Ungrouped"),
            mv("c", "_AI/unsorted"),
            mv("d", "Misc"),
            mv("e", "その他"),
            mv("f", "Development"),
        ];
        let result = drop_unsorted_sentinels(moves);
        assert_eq!(result.len(), 1, "{result:?}");
        assert_eq!(result[0].folder, "Development");
    }

    #[test]
    fn real_folder_names_survive_sentinel_filter() {
        let moves = vec![mv("a", "Other Tools"), mv("b", "General Aviation"), mv("c", "Linkedin")];
        assert_eq!(drop_unsorted_sentinels(moves).len(), 3);
    }

    fn sample_items(n: usize) -> Vec<BookmarkItem> {
        (0..n)
            .map(|i| BookmarkItem {
                bookmark_id: i.to_string(),
                title: "Test".into(),
                url: "https://example.com".into(),
                tags: vec!["rust".into(), "docs".into()],
                description: "A fairly long description that costs real tokens.".into(),
            })
            .collect()
    }

    #[test]
    fn cost_estimate_sanity() {
        let items = sample_items(100);
        let est = estimate_cost(&items, 500, 40, FieldSelection::default(), true, None, None);
        assert_eq!(est.chunks, 3);
        assert!(est.input_tokens_est > 0);
    }

    #[test]
    fn cost_estimate_grows_with_description() {
        let items = sample_items(100);
        let lean = FieldSelection { title: true, url: true, tags: true, description: false };
        let rich = FieldSelection { description: true, ..lean };
        let a = estimate_cost(&items, 500, 40, lean, true, None, None);
        let b = estimate_cost(&items, 500, 40, rich, true, None, None);
        assert!(
            b.input_tokens_est > a.input_tokens_est,
            "description must raise the estimate: {} vs {}",
            a.input_tokens_est, b.input_tokens_est
        );
    }

    #[test]
    fn cost_estimate_counts_prompt_per_chunk() {
        let items = sample_items(100);
        let f = FieldSelection::default();
        let one_chunk = estimate_cost(&items, 4000, 100, f, true, None, None);
        let three_chunks = estimate_cost(&items, 4000, 40, f, true, None, None);
        assert_eq!(three_chunks.chunks, 3);
        assert!(
            three_chunks.input_tokens_est > one_chunk.input_tokens_est,
            "the prompt is re-sent per chunk and must be counted per chunk"
        );
    }

    #[test]
    fn item_json_omits_unselected_fields() {
        let item = &sample_items(1)[0];
        let fields = FieldSelection { title: true, url: false, tags: false, description: false };
        let v = build_item_json(item, 0, fields, true);
        assert!(v.get("title").is_some());
        assert!(v.get("url").is_none());
        assert!(v.get("tags").is_none());
        assert!(v.get("description").is_none());
        // index and domain are always present.
        assert_eq!(v["domain"], "example.com");
        assert_eq!(v["index"], 0);
    }

    #[test]
    fn prompt_lists_known_folders() {
        let p = build_prompt(&[], None, &["Development".into(), "Machine Learning".into()]);
        assert!(p.contains("- Development"));
        assert!(p.contains("- Machine Learning"));
        assert!(p.contains("EXISTING FOLDER VOCABULARY"));
    }

    #[test]
    fn prompt_without_known_folders_has_no_vocabulary_section() {
        let p = build_prompt(&[], None, &[]);
        assert!(!p.contains("EXISTING FOLDER VOCABULARY"));
    }

    fn mv(id: &str, folder: &str) -> AiMove {
        AiMove { bookmark_id: id.into(), folder: folder.into(), confidence: 0.9, reason: "x".into() }
    }

    #[test]
    fn canonicalize_merges_spelling_variants() {
        let moves = vec![
            mv("a", "Dev Tools"),
            mv("b", "dev-tools"),
            mv("c", "Dev Tools"),
            mv("d", "DevTools"),
        ];
        let out = canonicalize_folder_names(moves);
        assert!(out.iter().all(|m| m.folder == "Dev Tools"), "{out:?}");
    }

    #[test]
    fn canonicalize_keeps_distinct_concepts_apart() {
        let moves = vec![mv("a", "Development"), mv("b", "Dev Tools")];
        let out = canonicalize_folder_names(moves);
        let names: std::collections::HashSet<_> = out.iter().map(|m| m.folder.clone()).collect();
        assert_eq!(names.len(), 2, "{out:?}");
    }

    #[test]
    fn canonicalize_tie_breaks_to_shorter_name() {
        let moves = vec![mv("a", "AI"), mv("b", "A. I.")];
        let out = canonicalize_folder_names(moves);
        assert!(out.iter().all(|m| m.folder == "AI"), "{out:?}");
    }
}
