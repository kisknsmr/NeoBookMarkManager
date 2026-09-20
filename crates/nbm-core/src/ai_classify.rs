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

/// Canonical catch-all folder name used only in "fresh classification" mode
/// (build_prompt's `fresh: true`) when a bookmark does not fit any theme.
/// The base prompt otherwise forbids this class of name and tells the model
/// to omit unclassifiable bookmarks entirely — fresh mode needs the opposite
/// (every input index must land somewhere), so this override explicitly lifts
/// that restriction for this one designated name.
pub const FRESH_CATCHALL: &str = "その他";

const FRESH_MODE_OVERRIDE: &str = r#"

FRESH CLASSIFICATION MODE (FULL REORGANIZATION) — OVERRIDES ABOVE:
- These bookmarks were selected for a full re-organization from scratch.
  Ignore whatever folder they currently live in — decide placement purely
  from their content (title/url/domain/tags/description), even when that
  content is thin (domain and URL only).
- This OVERRIDES the "only include moves you are confident about; if none,
  return {"moves":[]}" line above. In this mode an empty or partial result is
  WRONG. Every single input index MUST appear in exactly one move — use a
  low confidence value (e.g. 0.3) for a shaky guess instead of leaving it out.
- The "minimum group size 2" rule still applies to ordinary theme groups. But
  bookmarks that do not fit any theme must NOT be omitted — put them in one
  single group named exactly "その他" (reuse this exact name, do not invent
  variants like "Other" or "Misc"). This is the one exception to the "never
  use these names" rule above — it is the designated catch-all for this mode.
"#;

/// `known_folders` carries the folders that already exist in the tree plus
/// every folder produced by earlier chunks of the same run. Without it each
/// chunk names groups from scratch, so a 260-bookmark run split into 7 requests
/// happily invents "Development", "Dev Tools" and "Programming" in parallel.
pub fn build_prompt(
    priority_terms: &[String],
    custom_prompt: Option<&str>,
    known_folders: &[String],
    fresh: bool,
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
               \"Programming\" when \"Development\" is already listed).\n\
             - A listed entry may be a two-level \"Parent/Child\" path. You MAY add a new\n\
               sibling child under an already-listed parent even if that exact child isn't\n\
               listed (e.g. \"Language Learning/Thai\" is listed and you find Spanish\n\
               bookmarks — use \"Language Learning/Spanish\", reusing the \"Language Learning\"\n\
               parent exactly). Still never nest deeper than two levels total.\n"
        ));
    }

    prompt.push_str(SCHEMA_OVERRIDE);
    if fresh {
        prompt.push_str(FRESH_MODE_OVERRIDE);
    }
    if let Some(custom) = custom_prompt {
        prompt = format!("USER OVERRIDE INSTRUCTIONS:\n{custom}\n\n{prompt}");
    }
    prompt
}

// ---------------------------------------------------------------------------
// Stage 1: plan the folder structure for the whole list
// ---------------------------------------------------------------------------
//
// Filing bookmarks in independent chunks means each chunk only sees its own
// slice: a lone price-comparison site in an early chunk has no "Shopping"
// folder to go to yet, so it lands in the catch-all. Deciding the folders once,
// from the complete list, and then filing every chunk against that fixed set
// makes the result independent of where the chunk boundaries fall.

/// Most folders the planning stage may propose.
pub const PLAN_MAX_FOLDERS: usize = 60;

/// Fields for the planning payload: only what says what a bookmark *is*. The
/// full text is not needed to pick folder names, and the whole library goes in
/// one request.
pub fn plan_fields(fields: FieldSelection) -> FieldSelection {
    FieldSelection { title: fields.title, url: false, tags: fields.tags, description: false }
}

pub fn build_plan_prompt(
    priority_terms: &[String],
    custom_prompt: Option<&str>,
    existing_folders: &[String],
) -> String {
    let terms = priority_terms
        .iter()
        .map(|t| format!("\"{t}\""))
        .collect::<Vec<_>>()
        .join(", ");
    let mut prompt = format!(
        "You are an expert Librarian. Below is the COMPLETE list of bookmarks that will be \
organized. Do NOT file them. Design only the FOLDER STRUCTURE that would organize this whole list.\n\
\n\
INPUT: {{\"bookmarks\": [...]}}; each has `index` and `domain` and MAY have `title` and `tags`.\n\
Judge a site by its domain and title, not by the wording of one page.\n\
\n\
RULES:\n\
- Every folder must be able to hold at least 2 of these bookmarks.\n\
- Make sure every recurring kind of site has a home, so that a lone bookmark of that kind can still \
be filed into it later. Example: price-comparison and shopping sites belong in one shopping folder, \
not in a catch-all.\n\
- Specific over general (\"Cloud Infrastructure\" over \"Tech\"), concise names (\"Python\", not \
\"Python Resources\").\n\
- Up to two levels: a single name or \"Parent/Child\". Use a parent only when it has two or more \
sizeable children. Never nest deeper.\n\
- NEVER use these names: \"Misc\", \"Others\", \"Other\", \"Links\", \"Work\", \"General\", \
\"Ungrouped\", \"Unsorted\", \"Uncategorized\", \"未分類\", \"その他\".\n\
- Priority terms, if any bookmark matches one, MUST be folders (exact spelling, case-sensitive): [{terms}]\n\
- At most {PLAN_MAX_FOLDERS} folders.\n"
    );
    if !existing_folders.is_empty() {
        let list = existing_folders.iter().map(|f| format!("- {f}")).collect::<Vec<_>>().join("\n");
        prompt.push_str(&format!(
            "\nFOLDERS THAT ALREADY EXIST (reuse them exactly as written instead of inventing near-duplicates; \
you may add new ones):\n{list}\n"
        ));
    }
    prompt.push_str("\nOUTPUT VALID JSON ONLY, no code fences: {\"folders\": [\"Name\", \"Parent/Child\"]}");
    if let Some(custom) = custom_prompt {
        prompt = format!("USER OVERRIDE INSTRUCTIONS:\n{custom}\n\n{prompt}");
    }
    prompt
}

/// Clean the model's folder plan: sanitize paths, drop catch-all names and
/// duplicates (including spelling variants), cap the count.
pub fn clean_plan(folders: Vec<String>) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    let mut out = Vec::new();
    for raw in folders {
        let f = cap_depth(&sanitize_folder_path(&raw));
        if f.is_empty() || is_unsorted_sentinel(&f) {
            continue;
        }
        if seen.insert(folder_key(&f)) {
            out.push(f);
        }
        if out.len() >= PLAN_MAX_FOLDERS {
            break;
        }
    }
    out
}

/// Tokens the planning request adds on top of the per-chunk requests.
pub fn estimate_plan_input_tokens(
    items: &[BookmarkItem],
    prompt_len: usize,
    fields: FieldSelection,
    sanitize_urls: bool,
) -> usize {
    let tok = |n: usize| n.div_ceil(4).max(1);
    tok(prompt_len) + tok(build_batch_payload(items, plan_fields(fields), sanitize_urls).len())
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

/// Fresh-mode counterpart of [`drop_unsorted_sentinels`]: a "could not
/// classify" marker is redirected to [`FRESH_CATCHALL`] instead of dropped, so
/// the bookmark still ends up somewhere rather than being silently left in
/// its original location.
pub fn redirect_unsorted_sentinels(mut moves: Vec<AiMove>) -> Vec<AiMove> {
    for m in &mut moves {
        if is_unsorted_sentinel(&m.folder) {
            m.folder = FRESH_CATCHALL.to_string();
        }
    }
    moves
}

/// Deepest folder path the AI may create, counted from where it starts
/// building (so "Guitar/Gear" is 2). The prompt asks for this; nothing made the
/// model obey it.
pub const MAX_NEW_FOLDER_DEPTH: usize = 2;

/// Keep only the first [`MAX_NEW_FOLDER_DEPTH`] segments of a path.
fn cap_depth(folder: &str) -> String {
    folder
        .split('/')
        .take(MAX_NEW_FOLDER_DEPTH)
        .collect::<Vec<_>>()
        .join("/")
}

/// Enforce the two-level limit on folders the AI invented. A folder that already
/// exists in the tree is left alone — reusing a deep folder someone built is not
/// the model nesting too far. Anything deeper is filed at its second level
/// instead ("Guitar/Gear/Amps" → "Guitar/Gear").
pub fn cap_folder_depth(mut moves: Vec<AiMove>, existing_folders: &[String]) -> Vec<AiMove> {
    let existing: std::collections::HashSet<String> =
        existing_folders.iter().map(|f| folder_key(f)).collect();
    for m in &mut moves {
        if m.folder.split('/').count() > MAX_NEW_FOLDER_DEPTH
            && !existing.contains(&folder_key(&m.folder))
        {
            m.folder = cap_depth(&m.folder);
        }
    }
    moves
}

/// Fold a lone bookmark into its parent folder when the siblings add up.
///
/// The model is told to prefer specific folders and may nest two levels, so it
/// tends to answer with "Guitar/Jazz", "Guitar/Karaoke", "Guitar/Blogs"… one
/// bookmark each. Judged folder by folder every one of those is a singleton and
/// gets thrown out, even though together they are an obvious "Guitar" group.
/// Counting by path instead: a singleton whose parent holds two or more
/// bookmarks (its own included) is filed into the parent.
fn roll_up_small_folders(
    mut moves: Vec<AiMove>,
    existing: &std::collections::HashSet<String>,
) -> Vec<AiMove> {
    let mut direct: HashMap<String, usize> = HashMap::new();
    let mut subtree: HashMap<String, usize> = HashMap::new();
    for m in &moves {
        *direct.entry(m.folder.clone()).or_insert(0) += 1;
        let mut path = m.folder.as_str();
        loop {
            *subtree.entry(path.to_string()).or_insert(0) += 1;
            match path.rfind('/') {
                Some(i) => path = &path[..i],
                None => break,
            }
        }
    }
    for m in &mut moves {
        if m.folder == FRESH_CATCHALL
            || direct[&m.folder] >= 2
            || existing.contains(&folder_key(&m.folder))
        {
            continue;
        }
        if let Some(i) = m.folder.rfind('/') {
            let parent = m.folder[..i].to_string();
            if !is_unsorted_sentinel(&parent) && subtree[&parent] >= 2 {
                m.folder = parent;
            }
        }
    }
    moves
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
    let moves = roll_up_small_folders(moves, &existing);

    let mut counts: HashMap<String, usize> = HashMap::new();
    for m in &moves { *counts.entry(m.folder.clone()).or_insert(0) += 1; }

    moves
        .into_iter()
        .filter(|m| counts[&m.folder] >= 2 || existing.contains(&folder_key(&m.folder)))
        .collect()
}

/// Fresh-mode counterpart of [`enforce_min_group_size`]: a move that fails the
/// rule is redirected to [`FRESH_CATCHALL`] instead of dropped, so a full
/// reorganization never silently loses a bookmark. [`FRESH_CATCHALL`] itself
/// is exempt from the size check — it is allowed to be the whole point of a
/// small remainder group.
pub fn enforce_min_group_size_or_catchall(moves: Vec<AiMove>, existing_folders: &[String]) -> Vec<AiMove> {
    if moves.is_empty() { return moves; }

    let existing: std::collections::HashSet<String> =
        existing_folders.iter().map(|f| folder_key(f)).collect();
    let moves = roll_up_small_folders(moves, &existing);

    let mut counts: HashMap<String, usize> = HashMap::new();
    for m in &moves { *counts.entry(m.folder.clone()).or_insert(0) += 1; }

    moves
        .into_iter()
        .map(|mut m| {
            if m.folder != FRESH_CATCHALL
                && counts[&m.folder] < 2
                && !existing.contains(&folder_key(&m.folder))
            {
                m.folder = FRESH_CATCHALL.to_string();
            }
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
    fn lone_children_of_one_parent_are_filed_into_the_parent() {
        // The shape from a real run: every guitar site got its own sub-folder.
        let moves = vec![
            mv("a", "Guitar/Jazz"),
            mv("b", "Guitar/Karaoke"),
            mv("c", "Guitar/Blogs"),
            mv("d", "Shopping"),
            mv("e", "Shopping"),
            mv("f", "Lonely"),
        ];
        let out = enforce_min_group_size_or_catchall(moves, &[]);
        let folder = |id: &str| out.iter().find(|m| m.bookmark_id == id).unwrap().folder.clone();
        for id in ["a", "b", "c"] {
            assert_eq!(folder(id), "Guitar", "{out:?}");
        }
        assert_eq!(folder("d"), "Shopping");
        assert_eq!(folder("f"), FRESH_CATCHALL, "a genuine loner still goes to the catch-all");

        // Outside fresh mode the same rescue applies instead of dropping them.
        let kept = enforce_min_group_size(
            vec![mv("a", "Guitar/Jazz"), mv("b", "Guitar/Karaoke"), mv("f", "Lonely")],
            &[],
        );
        assert_eq!(kept.len(), 2, "{kept:?}");
        assert!(kept.iter().all(|m| m.folder == "Guitar"), "{kept:?}");
    }

    #[test]
    fn folders_the_ai_invents_never_go_past_two_levels() {
        let moves = vec![
            mv("a", "Guitar/Gear/Amps"),
            mv("b", "Guitar/Gear"),
            mv("c", "Music/Old/Deep/Folder"),   // exists in the tree: left alone
            mv("d", "Shopping"),
        ];
        let out = cap_folder_depth(moves, &["Music/Old/Deep/Folder".into()]);
        let folder = |id: &str| out.iter().find(|m| m.bookmark_id == id).unwrap().folder.clone();
        assert_eq!(folder("a"), "Guitar/Gear");
        assert_eq!(folder("b"), "Guitar/Gear");
        assert_eq!(folder("c"), "Music/Old/Deep/Folder");
        assert_eq!(folder("d"), "Shopping");
    }

    #[test]
    fn the_folder_plan_is_capped_at_two_levels_too() {
        assert_eq!(clean_plan(vec!["A/B/C/D".into()]), vec!["A/B".to_string()]);
    }

    #[test]
    fn a_lone_child_of_an_otherwise_empty_parent_is_not_rescued() {
        let out = enforce_min_group_size_or_catchall(vec![mv("a", "Guitar/Jazz")], &[]);
        assert_eq!(out[0].folder, FRESH_CATCHALL);
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
    fn clean_plan_drops_catchalls_duplicates_and_caps() {
        let plan = clean_plan(vec![
            "Shopping".into(),
            "shopping".into(),          // spelling variant of the above
            "その他".into(),             // catch-all is never a planned folder
            "Misc".into(),
            "Language Learning/Thai".into(),
            "".into(),
        ]);
        assert_eq!(plan, vec!["Shopping".to_string(), "Language Learning/Thai".to_string()]);

        let many: Vec<String> = (0..200).map(|i| format!("Folder{i}")).collect();
        assert_eq!(clean_plan(many).len(), PLAN_MAX_FOLDERS);
    }

    #[test]
    fn plan_prompt_states_the_rules_and_reuses_existing_folders() {
        let p = build_plan_prompt(&["Python".into()], None, &["Development".into()]);
        assert!(p.contains("COMPLETE list"));
        assert!(p.contains("\"Python\""));
        assert!(p.contains("- Development"));
        assert!(p.contains("{\"folders\""));
        let none = build_plan_prompt(&[], Some("focus on work"), &[]);
        assert!(none.starts_with("USER OVERRIDE INSTRUCTIONS:
focus on work"));
        assert!(!none.contains("ALREADY EXIST"));
    }

    #[test]
    fn plan_payload_leaves_out_url_and_description() {
        let f = plan_fields(FieldSelection { title: true, url: true, tags: true, description: true });
        assert!(f.title && f.tags && !f.url && !f.description);
    }

    #[test]
    fn prompt_lists_known_folders() {
        let p = build_prompt(&[], None, &["Development".into(), "Machine Learning".into()], false);
        assert!(p.contains("- Development"));
        assert!(p.contains("- Machine Learning"));
        assert!(p.contains("EXISTING FOLDER VOCABULARY"));
    }

    #[test]
    fn prompt_without_known_folders_has_no_vocabulary_section() {
        let p = build_prompt(&[], None, &[], false);
        assert!(!p.contains("EXISTING FOLDER VOCABULARY"));
    }

    #[test]
    fn fresh_mode_adds_override_and_default_omits_it() {
        let normal = build_prompt(&[], None, &[], false);
        assert!(!normal.contains("FRESH CLASSIFICATION MODE"));

        let fresh = build_prompt(&[], None, &[], true);
        assert!(fresh.contains("FRESH CLASSIFICATION MODE"));
        assert!(fresh.contains(FRESH_CATCHALL));
    }

    #[test]
    fn redirect_sentinels_keeps_bookmark_but_renames_folder() {
        let moves = vec![
            mv("a", "ungrouped"),
            mv("b", "_AI/unsorted"),
            mv("c", "Development"),
        ];
        let result = redirect_unsorted_sentinels(moves);
        assert_eq!(result.len(), 3, "no bookmark should be dropped: {result:?}");
        assert_eq!(result[0].folder, FRESH_CATCHALL);
        assert_eq!(result[1].folder, FRESH_CATCHALL);
        assert_eq!(result[2].folder, "Development");
    }

    #[test]
    fn min_group_or_catchall_redirects_instead_of_dropping() {
        let moves = vec![
            mv("a", "Big"),
            mv("b", "Big"),
            mv("c", "Small"),
        ];
        let result = enforce_min_group_size_or_catchall(moves, &[]);
        assert_eq!(result.len(), 3, "no bookmark should be dropped: {result:?}");
        assert!(result.iter().any(|m| m.bookmark_id == "c" && m.folder == FRESH_CATCHALL));
    }

    #[test]
    fn min_group_or_catchall_exempts_catchall_from_size_rule() {
        let moves = vec![mv("a", FRESH_CATCHALL)];
        let result = enforce_min_group_size_or_catchall(moves, &[]);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].folder, FRESH_CATCHALL);
    }

    #[test]
    fn min_group_or_catchall_keeps_singleton_for_existing_folder() {
        let moves = vec![mv("a", "Development")];
        let existing = vec!["Development".to_string()];
        let result = enforce_min_group_size_or_catchall(moves, &existing);
        assert_eq!(result[0].folder, "Development");
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
