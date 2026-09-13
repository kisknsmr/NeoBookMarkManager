//! AI classification: readiness, cost estimate, the streaming run itself, and
//! applying the resulting moves to the tree.
//!
//! The run used to be one 205-line `async fn` holding chunking, retry/backoff,
//! quota fallback, vocabulary growth and progress reporting at once. It is now
//! a [`ClassifyRun`] that is prepared (and possibly refused) up front, then
//! driven one chunk at a time.

use axum::extract::State;
use axum::response::sse::{Event, Sse};
use axum::routing::post;
use axum::{Json, Router};
use futures_util::stream::Stream;
use nbm_core::ai_classify::{self, AiMove, ClassifyProgress, CostEstimate, FieldSelection};
use nbm_core::ai_client::{
    call_gemini_batch, is_model_unavailable_error, is_quota_error, parse_retry_after_secs,
};
use nbm_core::tree;
use serde::{Deserialize, Serialize};
use tokio::sync::mpsc;

use crate::error::ApiResult;
use crate::settings;
use crate::sse;
use crate::state::AppState;

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/classify/readiness", post(classify_readiness))
        .route("/classify/estimate", post(classify_estimate))
        .route("/classify/ai", post(classify_ai))
        .route("/classify/ai-apply", post(classify_ai_apply))
}

fn default_chunk_size() -> usize { 40 }
fn bool_true() -> bool { true }

/// How many existing folder paths to show the model as reusable vocabulary.
/// Bounded so a large tree cannot crowd the bookmarks out of the prompt.
const KNOWN_FOLDER_LIMIT: usize = 60;

/// Attempts per chunk before it is reported as failed.
const CHUNK_ATTEMPTS: u32 = 3;

/// Never sleep longer than this between attempts, whatever the server asks for.
const MAX_BACKOFF_SECS: f64 = 90.0;

// --- Request bodies --------------------------------------------------------

#[derive(Deserialize)]
struct ClassifyAiBody {
    bookmark_ids: Vec<String>,
    custom_prompt: Option<String>,
    #[serde(default = "default_chunk_size")]
    chunk_size: usize,
    #[serde(default = "settings::default_model")]
    model: String,
    #[serde(default = "bool_true")]
    sanitize_urls: bool,
    /// Which fields to send to the model. Omitted entries default to false,
    /// except an entirely missing object falls back to FieldSelection::default.
    #[serde(default)]
    fields: Option<FieldSelectionBody>,
    /// Use the billing-enabled key instead of the default one. Set only after
    /// the user has agreed to the switch in the quota-exhausted prompt.
    #[serde(default)]
    use_paid_key: bool,
}

#[derive(Deserialize)]
struct FieldSelectionBody {
    #[serde(default = "bool_true")]
    title: bool,
    #[serde(default = "bool_true")]
    url: bool,
    #[serde(default = "bool_true")]
    tags: bool,
    #[serde(default)]
    description: bool,
}

impl From<&FieldSelectionBody> for FieldSelection {
    fn from(b: &FieldSelectionBody) -> Self {
        Self { title: b.title, url: b.url, tags: b.tags, description: b.description }
    }
}

impl ClassifyAiBody {
    fn field_selection(&self) -> FieldSelection {
        self.fields.as_ref().map(Into::into).unwrap_or_default()
    }
}

// --- Shared inputs ---------------------------------------------------------

/// Every folder path in the tree that currently holds at least one bookmark.
/// Capped so a huge tree cannot crowd out the bookmarks in the prompt.
fn collect_folder_names(root: &nbm_core::Node, limit: usize) -> Vec<String> {
    fn walk(node: &nbm_core::Node, prefix: &str, out: &mut Vec<(String, usize)>) {
        for child in &node.children {
            if !child.is_folder() { continue; }
            let path = if prefix.is_empty() {
                child.title.clone()
            } else {
                format!("{prefix}/{}", child.title)
            };
            let count = child.count_bookmarks();
            if count > 0 {
                out.push((path.clone(), count));
            }
            walk(child, &path, out);
        }
    }
    let mut found = Vec::new();
    walk(root, "", &mut found);
    // Busiest folders first: those carry the most useful naming signal.
    found.sort_by_key(|(_, count)| std::cmp::Reverse(*count));
    found.truncate(limit);
    found.into_iter().map(|(path, _)| path).collect()
}

/// The folder vocabulary handed to the model.
async fn known_folders(state: &AppState) -> Vec<String> {
    let root = state.inner.root.read().await;
    collect_folder_names(&root, KNOWN_FOLDER_LIMIT)
}

/// Build the BookmarkItem payload for the given ids (shared by estimate + run).
async fn classify_items(
    state: &AppState,
    bookmark_ids: &[String],
    fields: FieldSelection,
) -> Vec<ai_classify::BookmarkItem> {
    use ai_classify::BookmarkItem;

    let fetched_titles = state
        .inner
        .db
        .as_ref()
        .and_then(|db| db.get_meta_bulk(bookmark_ids).ok())
        .unwrap_or_default();

    let tags_map = if fields.tags {
        state
            .inner
            .db
            .as_ref()
            .and_then(|db| db.get_all_tags_map().ok())
            .unwrap_or_default()
    } else {
        std::collections::HashMap::new()
    };

    let root = state.inner.root.read().await;
    bookmark_ids
        .iter()
        .filter_map(|id| {
            let (path, idx) = tree::locate_bookmark(&root, id)?;
            let folder = tree::find_folder(&root, &path)?;
            let bm = folder.children.get(idx)?;
            let title = if bm.title.is_empty() {
                fetched_titles.get(id).cloned().unwrap_or_default()
            } else {
                bm.title.clone()
            };
            let tags = tags_map
                .get(id)
                .map(|s| s.split(' ').filter(|t| !t.is_empty()).map(str::to_string).collect())
                .unwrap_or_default();
            let description = if fields.description {
                bm.description.clone()
            } else {
                String::new()
            };
            Some(BookmarkItem {
                bookmark_id: id.clone(),
                title,
                url: bm.url.clone(),
                tags,
                description,
            })
        })
        .collect()
}

// --- Readiness -------------------------------------------------------------

#[derive(Deserialize)]
struct ReadinessBody {
    bookmark_ids: Vec<String>,
}

/// How much material the model would actually receive for these bookmarks.
///
/// Titles, descriptions and tags are all populated by other commands, and a run
/// started before those have been fetched gives the model little more than a
/// domain to work with — which is what produces a pile of unclassifiable
/// bookmarks. The UI warns using these counts before anything is sent.
#[derive(Serialize)]
struct ReadinessResp {
    total: usize,
    with_title: usize,
    with_description: usize,
    with_tags: usize,
    /// Bookmarks with no title AND no tags AND no description: for these the
    /// model sees only the domain and URL.
    bare: usize,
}

async fn classify_readiness(
    State(state): State<AppState>,
    Json(body): Json<ReadinessBody>,
) -> Json<ReadinessResp> {
    // Ask for every field so the counts describe what is available, not what
    // the current field selection happens to send.
    let all_fields = FieldSelection { title: true, url: true, tags: true, description: true };
    let items = classify_items(&state, &body.bookmark_ids, all_fields).await;

    let mut resp = ReadinessResp {
        total: items.len(),
        with_title: 0,
        with_description: 0,
        with_tags: 0,
        bare: 0,
    };
    for it in &items {
        let has_title = !it.title.trim().is_empty();
        let has_description = !it.description.trim().is_empty();
        let has_tags = !it.tags.is_empty();
        resp.with_title += usize::from(has_title);
        resp.with_description += usize::from(has_description);
        resp.with_tags += usize::from(has_tags);
        resp.bare += usize::from(!has_title && !has_description && !has_tags);
    }
    Json(resp)
}

// --- Estimate --------------------------------------------------------------

#[derive(Serialize)]
struct EstimateResp {
    /// True only when both an API key and pricing are configured → AI run allowed.
    can_run: bool,
    /// Human-readable reason when can_run is false.
    blocked_reason: Option<String>,
    cost: CostEstimate,
    /// User-declared tier, so the approval gate can say whether the estimated
    /// dollar figure will actually be charged. None = undeclared.
    free_tier: Option<bool>,
    paid_key_set: bool,
}

/// Why an AI run cannot start, or `None` when it can. Both the estimate
/// endpoint and the run itself gate on this, so the wording stays in one place.
fn blocked_reason(state: &AppState, model: &str, key_set: bool, priced: bool) -> Option<String> {
    if !key_set {
        Some("APIキーが未設定です。設定からキーを登録してください。".to_string())
    } else if !priced {
        Some(format!(
            "「{model}」の単価が分かりません。config/models.json に価格を追加するか、config.ini [AI] の input/output_cost_per_1m_tokens を設定してください。"
        ))
    } else {
        let _ = state;
        None
    }
}

async fn classify_estimate(
    State(state): State<AppState>,
    Json(body): Json<ClassifyAiBody>,
) -> Json<EstimateResp> {
    let fields = body.field_selection();
    let items = classify_items(&state, &body.bookmark_ids, fields).await;

    // The vocabulary is part of the prompt, so it has to be part of the estimate.
    let prompt = ai_classify::build_prompt(
        &settings::priority_terms(&state),
        body.custom_prompt.as_deref(),
        &known_folders(&state).await,
    );

    let (in_price, out_price) = settings::ai_pricing_for_model(&state, &body.model);
    let cost = ai_classify::estimate_cost(
        &items,
        prompt.len(),
        body.chunk_size.max(1),
        fields,
        body.sanitize_urls,
        in_price,
        out_price,
    );

    let blocked = blocked_reason(
        &state,
        &body.model,
        settings::api_key(&state).is_some(),
        in_price.is_some() && out_price.is_some(),
    );
    Json(EstimateResp {
        can_run: blocked.is_none(),
        blocked_reason: blocked,
        cost,
        free_tier: settings::free_tier_flag(&state),
        paid_key_set: settings::paid_api_key(&state).is_some(),
    })
}

// --- The streaming run -----------------------------------------------------

/// A `ClassifyProgress` with only the counts and status set. The other five
/// fields are `None` at almost every emit site, so events are written as
/// `ClassifyProgress { chunk_moves: Some(..), ..progress("done", n, n) }`.
fn progress(status: &str, processed: usize, total: usize) -> ClassifyProgress {
    ClassifyProgress {
        processed,
        total,
        status: status.to_string(),
        chunk_moves: None,
        error: None,
        cost_estimate: None,
        failed_ids: None,
    }
}

/// A run that was refused before anything was sent.
fn refusal(message: String) -> ClassifyProgress {
    ClassifyProgress { error: Some(message), ..progress("error", 0, 0) }
}

/// Everything one classification run needs, resolved from the request before
/// the streaming task starts.
struct ClassifyRun {
    client: reqwest::Client,
    api_key: String,
    model: String,
    priority_terms: Vec<String>,
    custom_prompt: Option<String>,
    fields: FieldSelection,
    sanitize_urls: bool,
    chunk_size: usize,
    items: Vec<ai_classify::BookmarkItem>,
    /// Grows as chunks complete, so later chunks reuse the folder names earlier
    /// ones settled on instead of inventing synonyms.
    known_folders: Vec<String>,
    /// Whether this run is on the billing-enabled key, which only changes how
    /// a quota rejection is worded.
    use_paid_key: bool,
    cost: CostEstimate,
    tx: mpsc::Sender<ClassifyProgress>,
}

impl ClassifyRun {
    /// Resolve the request into a runnable run, or the refusal to send back.
    ///
    /// Both gates are pre-flight: without a key there is nothing to call, and
    /// without pricing the cost-approval gate refuses to send anything to
    /// Gemini at all.
    async fn prepare(
        state: &AppState,
        body: ClassifyAiBody,
        tx: mpsc::Sender<ClassifyProgress>,
    ) -> Result<Self, ClassifyProgress> {
        let api_key = if body.use_paid_key {
            settings::paid_api_key(state)
        } else {
            settings::api_key(state)
        };
        let Some(api_key) = api_key else {
            return Err(refusal(if body.use_paid_key {
                "有料枠のAPIキーが未登録です。AI設定で登録してください。".to_string()
            } else {
                "APIキーが未設定です。設定からキーを登録してください。".to_string()
            }));
        };

        let (in_price, out_price) = settings::ai_pricing_for_model(state, &body.model);
        if in_price.is_none() || out_price.is_none() {
            return Err(refusal(format!(
                "「{}」の単価が分からないため実行をブロックしました。config/models.json に価格を追加するか、config.ini [AI] の input/output_cost_per_1m_tokens を設定してください。",
                body.model
            )));
        }

        let fields = body.field_selection();
        let items = classify_items(state, &body.bookmark_ids, fields).await;
        let known_folders = known_folders(state).await;
        let priority_terms = settings::priority_terms(state);
        let chunk_size = body.chunk_size.max(1);

        let cost = ai_classify::estimate_cost(
            &items,
            ai_classify::build_prompt(&priority_terms, body.custom_prompt.as_deref(), &known_folders)
                .len(),
            chunk_size,
            fields,
            body.sanitize_urls,
            in_price,
            out_price,
        );

        Ok(Self {
            client: state.inner.http_client.clone(),
            api_key,
            model: body.model,
            priority_terms,
            custom_prompt: body.custom_prompt,
            fields,
            sanitize_urls: body.sanitize_urls,
            chunk_size,
            items,
            known_folders,
            use_paid_key: body.use_paid_key,
            cost,
            tx,
        })
    }

    async fn emit(&self, event: ClassifyProgress) {
        let _ = self.tx.send(event).await;
    }

    /// Send one chunk, retrying transient failures. `Err` carries the last
    /// error once the attempts are spent.
    async fn send_chunk(
        &self,
        batch: &[ai_classify::BookmarkItem],
        processed: usize,
    ) -> Result<Vec<AiMove>, String> {
        // Rebuilt per chunk so each request sees the folders the previous
        // chunks settled on. Without this, independent chunks invent
        // "Development", "Dev Tools" and "Programming" for the same idea.
        let prompt = ai_classify::build_prompt(
            &self.priority_terms,
            self.custom_prompt.as_deref(),
            &self.known_folders,
        );
        let total = self.items.len();
        let mut last_err = String::new();

        for attempt in 0..CHUNK_ATTEMPTS {
            match call_gemini_batch(
                &self.client,
                &self.api_key,
                &self.model,
                &prompt,
                batch,
                self.sanitize_urls,
                self.fields,
            )
            .await
            {
                Ok(moves) => return Ok(moves),
                Err(e) => {
                    last_err = e;
                    let Some(wait_secs) = retry_delay(&last_err, attempt) else {
                        break;
                    };
                    let reason = if last_err.contains("429") {
                        format!("レート制限のため {wait_secs:.0} 秒待機して再送します…")
                    } else {
                        format!("一時エラーのため {wait_secs:.0} 秒待機して再送します…")
                    };
                    self.emit(ClassifyProgress {
                        error: Some(reason),
                        ..progress("waiting", processed, total)
                    })
                    .await;
                    tokio::time::sleep(std::time::Duration::from_secs_f64(wait_secs)).await;
                }
            }
        }
        Err(last_err)
    }

    /// Fold newly invented folder names into the vocabulary for later chunks.
    fn learn_folders(&mut self, moves: &[AiMove]) {
        for m in moves {
            if self.known_folders.len() < KNOWN_FOLDER_LIMIT
                && !self.known_folders.iter().any(|f| f == &m.folder)
            {
                self.known_folders.push(m.folder.clone());
            }
        }
    }

    /// Ids of every bookmark from `chunk_index` (1-based) onward, i.e. the work
    /// that will not be attempted.
    fn remaining_ids(&self, chunk_index: usize) -> Vec<String> {
        self.items
            .chunks(self.chunk_size)
            .skip(chunk_index - 1)
            .flatten()
            .map(|b| b.bookmark_id.clone())
            .collect()
    }

    async fn execute(mut self) {
        let total = self.items.len();
        self.emit(ClassifyProgress {
            cost_estimate: Some(self.cost.clone()),
            ..progress("start", 0, total)
        })
        .await;

        // The folders that existed before this run. `known_folders` grows with
        // AI-invented names as chunks complete, so the min-group rule needs the
        // original set to tell "filed into an existing folder" from "created a
        // new folder for one bookmark".
        let existing_folders = self.known_folders.clone();
        let batches: Vec<Vec<ai_classify::BookmarkItem>> =
            self.items.chunks(self.chunk_size).map(<[_]>::to_vec).collect();

        let mut all_moves: Vec<AiMove> = Vec::new();
        let mut processed = 0usize;

        for (i, batch) in batches.iter().enumerate() {
            let chunk_index = i + 1;
            match self.send_chunk(batch, processed).await {
                Ok(moves) => {
                    processed += batch.len();
                    self.learn_folders(&moves);
                    all_moves.extend(moves.iter().cloned());
                    self.emit(ClassifyProgress {
                        chunk_moves: Some(moves),
                        ..progress("progress", processed, total)
                    })
                    .await;
                }
                // A quota rejection that outlived the backoff means this key is
                // done for now. Burning through the remaining chunks would just
                // collect the same error, so stop and hand every unprocessed id
                // back — the UI offers to continue on the paid key.
                Err(e) if is_quota_error(&e) => {
                    let remaining = self.remaining_ids(chunk_index);
                    let tier = if self.use_paid_key {
                        "有料枠のレート制限"
                    } else {
                        "無料枠のレート制限"
                    };
                    self.emit(ClassifyProgress {
                        error: Some(format!(
                            "{tier}の上限に達しました（残り {} 件は未処理）: {e}",
                            remaining.len()
                        )),
                        failed_ids: Some(remaining),
                        ..progress("quota_exhausted", processed, total)
                    })
                    .await;
                    break;
                }
                // Gemini periodically retires or renames model ids, so
                // config.ini can point at a model that has simply stopped
                // resolving. Every remaining chunk would hit the identical
                // 404, so stop here instead of repeating the same failure
                // across the whole batch — the UI points at AI settings
                // rather than offering a same-model retry that cannot work.
                Err(e) if is_model_unavailable_error(&e) => {
                    let remaining = self.remaining_ids(chunk_index);
                    self.emit(ClassifyProgress {
                        error: Some(format!(
                            "モデル「{}」は利用できません（Gemini側で廃止・変更された可能性があります）。\
                             AI設定で別のモデルに切り替えてください（残り {} 件は未処理）: {e}",
                            self.model,
                            remaining.len()
                        )),
                        failed_ids: Some(remaining),
                        ..progress("model_unavailable", processed, total)
                    })
                    .await;
                    break;
                }
                Err(e) => {
                    processed += batch.len();
                    // Hand back the ids so the UI can re-run just this chunk
                    // instead of silently dropping 40 bookmarks.
                    self.emit(ClassifyProgress {
                        error: Some(e),
                        failed_ids: Some(batch.iter().map(|b| b.bookmark_id.clone()).collect()),
                        ..progress("chunk_error", processed, total)
                    })
                    .await;
                }
            }
        }

        // Order matters: drop the "could not classify" markers first so they
        // cannot become the largest group, then merge spelling variants so the
        // min-group rule counts merged folders rather than variants.
        let final_moves = ai_classify::enforce_min_group_size(
            ai_classify::canonicalize_folder_names(ai_classify::drop_unsorted_sentinels(all_moves)),
            &existing_folders,
        );
        self.emit(ClassifyProgress {
            chunk_moves: Some(final_moves),
            ..progress("done", total, total)
        })
        .await;
    }
}

/// How long to wait before retrying, or `None` when this error is not worth
/// another attempt.
///
/// Gemini states the wait explicitly on a quota error (e.g. "Please retry in
/// 23.5s"); a short fixed backoff just gets rejected again immediately, which
/// is what produced runs of repeated 429s.
fn retry_delay(error: &str, attempt: u32) -> Option<f64> {
    let retryable = ["429", "500", "502", "503", "504"]
        .iter()
        .any(|code| error.contains(code));
    if !retryable || attempt + 1 >= CHUNK_ATTEMPTS {
        return None;
    }
    let secs = parse_retry_after_secs(error)
        .map(|s| s + 1.0) // small safety margin
        .unwrap_or(1.5 * (1u64 << attempt) as f64)
        .min(MAX_BACKOFF_SECS);
    Some(secs)
}

async fn classify_ai(
    State(state): State<AppState>,
    Json(body): Json<ClassifyAiBody>,
) -> Sse<impl Stream<Item = Result<Event, std::convert::Infallible>>> {
    let (tx, rx) = sse::channel();
    match ClassifyRun::prepare(&state, body, tx.clone()).await {
        Ok(run) => {
            tokio::spawn(run.execute());
        }
        Err(refused) => {
            tokio::spawn(async move {
                let _ = tx.send(refused).await;
            });
        }
    }
    sse::progress_stream(rx)
}

// --- Applying the moves ----------------------------------------------------

#[derive(Deserialize)]
struct ApplyMoveItem {
    bookmark_id: String,
    folder_path: String,
}

#[derive(Deserialize)]
struct ClassifyApplyBody {
    moves: Vec<ApplyMoveItem>,
    /// When true, delete source folders left empty by the moves (UI toggle).
    #[serde(default)]
    prune_empty_source: bool,
}

#[derive(Serialize)]
struct ClassifyApplyResp {
    ok: bool,
    applied: usize,
    skipped: usize,
    /// Number of now-empty source folders removed (0 when toggle off).
    pruned: usize,
}

async fn classify_ai_apply(
    State(state): State<AppState>,
    Json(body): Json<ClassifyApplyBody>,
) -> ApiResult<ClassifyApplyResp> {
    // This is the largest bulk mutation in the app — hundreds of bookmarks in
    // one call — so it goes through the same undo snapshot as every other edit.
    if body.moves.is_empty() {
        return Ok(Json(ClassifyApplyResp { ok: true, applied: 0, skipped: 0, pruned: 0 }));
    }

    let resp = state
        .edit_infallible(|root| {
            let mut applied = 0usize;
            let mut skipped = 0usize;
            let mut sources: std::collections::HashSet<String> = std::collections::HashSet::new();
            let mut targets: std::collections::HashSet<String> = std::collections::HashSet::new();

            for mv in &body.moves {
                let Some(target) = sanitize_destination(&mv.folder_path) else {
                    skipped += 1;
                    continue;
                };
                // Record the bookmark's current folder before moving it.
                if body.prune_empty_source {
                    if let Some((src, _)) = tree::locate_bookmark(root, &mv.bookmark_id) {
                        sources.insert(src);
                    }
                }
                find_or_create_folder(root, &target);
                match tree::move_bookmark(root, &mv.bookmark_id, &target) {
                    Ok(()) => {
                        applied += 1;
                        targets.insert(target);
                    }
                    Err(_) => skipped += 1,
                }
            }

            let pruned = if body.prune_empty_source {
                // Never prune a folder we just filled: with merging enabled a
                // source folder can also be a destination.
                let prunable: std::collections::HashSet<String> =
                    sources.difference(&targets).cloned().collect();
                prune_empty_source_folders(root, &prunable)
            } else {
                0
            };

            ClassifyApplyResp { ok: true, applied, skipped, pruned }
        })
        .await;

    Ok(Json(resp))
}

/// Normalise a destination path from the review UI, or `None` when it names no
/// folder at all.
///
/// The destination is whatever the UI asked for. It used to be rewritten into
/// `/_AI/...` unconditionally, which made merging into an existing folder
/// impossible — you always got a parallel `_AI` tree. Whitespace is trimmed as
/// well as slashes: a blank-but-not-empty destination ("  ") used to reach
/// `add_folder`, which rejected it, and then `move_bookmark`, which deleted the
/// bookmark instead of moving it.
fn sanitize_destination(raw: &str) -> Option<String> {
    let target = raw
        .trim()
        .trim_start_matches('/')
        .trim_end_matches('/')
        .trim();
    (!target.is_empty()).then(|| target.to_string())
}

/// Delete every folder in `source_paths` that is now empty (no bookmarks,
/// recursively). Skips the root. Returns the count removed. Deepest paths are
/// processed first so emptying a child can cascade up.
///
/// The caller is responsible for excluding folders that were also move
/// destinations — since destinations are no longer forced under `_AI`, a
/// source folder can legitimately be a target too.
fn prune_empty_source_folders(
    root: &mut nbm_core::Node,
    source_paths: &std::collections::HashSet<String>,
) -> usize {
    let mut paths: Vec<&String> = source_paths.iter().filter(|p| !p.is_empty()).collect();
    // Longest path first → delete children before parents.
    paths.sort_by_key(|p| std::cmp::Reverse(p.split('/').count()));
    let mut pruned = 0;
    for p in paths {
        let is_empty = tree::find_folder(root, p)
            .map(|f| f.count_bookmarks() == 0)
            .unwrap_or(false);
        if is_empty && tree::delete_folder(root, p).is_ok() {
            pruned += 1;
        }
    }
    pruned
}

/// Ensure every folder along `path` exists, creating only the missing levels.
/// Previously this blindly called `add_folder` for each level, which has no
/// dedupe and so produced a fresh duplicate folder on every call (e.g. dozens
/// of empty `_AI` folders when applying a batch of AI moves).
fn find_or_create_folder(root: &mut nbm_core::Node, path: &str) {
    let parts: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
    let mut current = String::new();
    for part in parts {
        let parent = current.clone();
        let candidate = if parent.is_empty() {
            part.to_string()
        } else {
            format!("{parent}/{part}")
        };
        // Only create the level if a folder with this exact path doesn't exist.
        if tree::find_folder(root, &candidate).is_none() {
            let _ = tree::add_folder(root, &parent, part);
        }
        current = candidate;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use nbm_core::Node;
    use std::collections::HashSet;

    fn count_children_named(root: &Node, name: &str) -> usize {
        root.children.iter().filter(|c| c.is_folder() && c.title == name).count()
    }

    #[test]
    fn repeated_calls_do_not_duplicate_folders() {
        let mut root = Node::new_root();
        // Simulate applying many AI moves that all target the same folder.
        for _ in 0..50 {
            find_or_create_folder(&mut root, "/_AI/Dev");
        }
        find_or_create_folder(&mut root, "/_AI/News");
        assert_eq!(count_children_named(&root, "_AI"), 1, "duplicate _AI folders created");
        let ai = tree::find_folder(&root, "_AI").unwrap();
        assert_eq!(count_children_named(ai, "Dev"), 1);
        assert_eq!(count_children_named(ai, "News"), 1);
    }

    #[test]
    fn creates_missing_nested_levels_only() {
        let mut root = Node::new_root();
        find_or_create_folder(&mut root, "/_AI/A/B");
        find_or_create_folder(&mut root, "/_AI/A/C");
        assert_eq!(count_children_named(&root, "_AI"), 1);
        let a = tree::find_folder(&root, "_AI/A").unwrap();
        assert_eq!(count_children_named(a, "B"), 1);
        assert_eq!(count_children_named(a, "C"), 1);
    }

    #[test]
    fn prune_removes_emptied_sources_but_keeps_nonempty() {
        let mut root = Node::new_root();
        // Old/ had its only bookmark moved out → now empty.
        root.children.push(Node::new_folder("Old"));
        // Keep/ still holds one → must survive.
        let mut keep = Node::new_folder("Keep");
        keep.children.push(Node::new_bookmark("y", "https://y.test/"));
        root.children.push(keep);

        let sources: HashSet<String> =
            ["Old".to_string(), "Keep".to_string()].into_iter().collect();
        assert_eq!(prune_empty_source_folders(&mut root, &sources), 1);
        assert_eq!(count_children_named(&root, "Old"), 0, "empty source removed");
        assert_eq!(count_children_named(&root, "Keep"), 1, "non-empty source kept");
    }

    #[test]
    fn prune_only_touches_paths_the_caller_listed() {
        let mut root = Node::new_root();
        root.children.push(Node::new_folder("Listed"));
        root.children.push(Node::new_folder("Unlisted"));

        let sources: HashSet<String> = ["Listed".to_string()].into_iter().collect();
        assert_eq!(prune_empty_source_folders(&mut root, &sources), 1);
        assert_eq!(count_children_named(&root, "Listed"), 0);
        assert_eq!(
            count_children_named(&root, "Unlisted"),
            1,
            "an empty folder that was not a move source must be left alone"
        );
    }

    #[test]
    fn a_blank_destination_names_no_folder() {
        assert_eq!(sanitize_destination("Archive/GitHub").as_deref(), Some("Archive/GitHub"));
        assert_eq!(sanitize_destination("/Archive/").as_deref(), Some("Archive"));
        assert_eq!(sanitize_destination("  /Archive/  ").as_deref(), Some("Archive"));
        assert_eq!(sanitize_destination(""), None);
        assert_eq!(sanitize_destination("   "), None, "whitespace is not a folder name");
        assert_eq!(sanitize_destination("/"), None);
    }

    #[test]
    fn retryable_errors_back_off_and_others_do_not() {
        // Server-side and rate-limit failures are worth another attempt.
        assert!(retry_delay("HTTP 429: quota", 0).is_some());
        assert!(retry_delay("HTTP 503", 0).is_some());
        // A bad key never becomes good by waiting.
        assert!(retry_delay("HTTP 400: API key not valid", 0).is_none());
        // The last attempt does not sleep before giving up.
        assert!(retry_delay("HTTP 429", CHUNK_ATTEMPTS - 1).is_none());
        // The server's own suggestion wins, plus a safety margin, capped.
        let secs = retry_delay("429 RESOURCE_EXHAUSTED. Please retry in 23.5s.", 0).unwrap();
        assert!((secs - 24.5).abs() < 0.01, "got {secs}");
        let capped = retry_delay("429. Please retry in 900.0s.", 0).unwrap();
        assert_eq!(capped, MAX_BACKOFF_SECS);
    }
}
