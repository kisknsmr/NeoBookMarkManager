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

use crate::ai_log;
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
    /// "選んだブックマークだけを見て、フォルダ構成を一から作り直す" mode:
    /// the existing tree's folder vocabulary is withheld from the prompt and
    /// unclassifiable/undersized groups are redirected to a catch-all instead
    /// of being dropped. False keeps today's "既存フォルダを優先して使う"
    /// behavior.
    #[serde(default)]
    fresh: bool,
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
    let vocab = if body.fresh { Vec::new() } else { known_folders(&state).await };
    let prompt = ai_classify::build_prompt(
        &settings::priority_terms(&state),
        body.custom_prompt.as_deref(),
        &vocab,
        body.fresh,
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
    /// "選んだブックマークだけを見て、フォルダ構成を一から作り直す" mode —
    /// see the field doc on `ClassifyAiBody::fresh`.
    fresh: bool,
    /// Whether this run is on the billing-enabled key, which only changes how
    /// a quota rejection is worded.
    use_paid_key: bool,
    cost: CostEstimate,
    tx: mpsc::Sender<ClassifyProgress>,
    /// Where to append this run's plain-text log, or `None` when no
    /// `config.ini` path is configured (e.g. in tests).
    log_dir: Option<std::path::PathBuf>,
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
        // Fresh mode ("選んだブックマークだけを見て、フォルダ構成を一から
        // 作り直す") withholds the existing tree's vocabulary entirely, so the
        // model never sees a "reuse this exactly" instruction for it.
        let known_folders = if body.fresh { Vec::new() } else { known_folders(state).await };
        let priority_terms = settings::priority_terms(state);
        let chunk_size = body.chunk_size.max(1);
        let fresh = body.fresh;

        let cost = ai_classify::estimate_cost(
            &items,
            ai_classify::build_prompt(&priority_terms, body.custom_prompt.as_deref(), &known_folders, fresh)
                .len(),
            chunk_size,
            fields,
            body.sanitize_urls,
            in_price,
            out_price,
        );

        let log_dir = ai_log::dir_from_config_path(state.inner.config_ini_path.as_deref());
        ai_log::append(log_dir.as_deref(), &format!(
            "==== {} classify run start ==== model={} fresh={} items={} chunk_size={} chunks={} \
             fields(title={} url={} tags={} description={}) known_folders={}",
            ai_log::timestamp(), body.model, fresh, items.len(), chunk_size, cost.chunks,
            fields.title, fields.url, fields.tags, fields.description, known_folders.len(),
        ));

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
            fresh,
            use_paid_key: body.use_paid_key,
            cost,
            log_dir,
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
            self.fresh,
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
            let outcome = self.send_chunk(batch, processed).await;
            ai_log::append(self.log_dir.as_deref(), &match &outcome {
                Ok(moves) => format!(
                    "[{}] chunk {}/{} ({} items): ok, moves={}",
                    ai_log::timestamp(), chunk_index, batches.len(), batch.len(), moves.len()
                ),
                Err(e) => format!(
                    "[{}] chunk {}/{} ({} items): error: {e}",
                    ai_log::timestamp(), chunk_index, batches.len(), batch.len()
                ),
            });
            match outcome {
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

        // Order matters: handle the "could not classify" markers first so they
        // cannot become the largest group, then merge spelling variants so the
        // min-group rule counts merged folders rather than variants.
        let raw_move_count = all_moves.len();
        let final_moves = if self.fresh {
            // Full reorganization: nothing gets dropped, undersized/unsorted
            // moves are redirected to the catch-all instead.
            ai_classify::enforce_min_group_size_or_catchall(
                ai_classify::canonicalize_folder_names(ai_classify::redirect_unsorted_sentinels(all_moves)),
                &existing_folders,
            )
        } else {
            ai_classify::enforce_min_group_size(
                ai_classify::canonicalize_folder_names(ai_classify::drop_unsorted_sentinels(all_moves)),
                &existing_folders,
            )
        };
        let catchall_count = final_moves.iter().filter(|m| m.folder == ai_classify::FRESH_CATCHALL).count();
        ai_log::append(self.log_dir.as_deref(), &format!(
            "==== {} classify run end ==== raw_moves={} final_moves={} catchall={} (dropped_by_postprocess={})",
            ai_log::timestamp(), raw_move_count, final_moves.len(), catchall_count,
            raw_move_count.saturating_sub(final_moves.len()),
        ));
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
    /// Folders that were the explicit scope of this classification run (e.g.
    /// the one folder the user pointed "一から作り直す" at). Only meaningful
    /// together with `prune_empty_source`.
    ///
    /// A scope folder that still has bookmarks left in it after the moves —
    /// because the AI didn't propose anything for them, or the user left them
    /// unchecked in the review list — has those leftovers swept into one
    /// timestamped "<timestamp> Archive" folder at the root before the scope
    /// folder is deleted. Without this, "run AI classify on this folder"
    /// only ever added new folders next to the untouched original, which
    /// reads as an addition rather than the reorganization it was meant to
    /// be. Folders NOT listed here keep the old, conservative behavior:
    /// pruned only when they end up genuinely empty on their own — a folder
    /// that merely donated one bookmark as a side effect must never have its
    /// unrelated remaining contents swept away.
    #[serde(default)]
    archive_scope_paths: Vec<String>,
}

#[derive(Serialize)]
struct ClassifyApplyResp {
    ok: bool,
    applied: usize,
    skipped: usize,
    /// Number of now-empty source folders removed (0 when toggle off).
    pruned: usize,
    /// Bookmarks swept into the timestamped Archive folder (0 unless a scope
    /// folder in `archive_scope_paths` still had leftovers).
    archived: usize,
}

async fn classify_ai_apply(
    State(state): State<AppState>,
    Json(body): Json<ClassifyApplyBody>,
) -> ApiResult<ClassifyApplyResp> {
    // This is the largest bulk mutation in the app — hundreds of bookmarks in
    // one call — so it goes through the same undo snapshot as every other edit.
    if body.moves.is_empty() {
        return Ok(Json(ClassifyApplyResp { ok: true, applied: 0, skipped: 0, pruned: 0, archived: 0 }));
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

            let (pruned, archived) = if body.prune_empty_source {
                // Never prune a folder we just filled: with merging enabled a
                // source folder can also be a destination.
                let prunable: std::collections::HashSet<String> =
                    sources.difference(&targets).cloned().collect();

                let scope: std::collections::HashSet<&String> =
                    body.archive_scope_paths.iter().collect();
                let mut archived = 0usize;
                let mut archive_folder: Option<String> = None;
                for path in prunable.iter().filter(|p| scope.contains(p)) {
                    let Some(folder) = tree::find_folder(root, path) else { continue };
                    let mut leftover_ids = Vec::new();
                    collect_bookmark_ids_recursive(folder, &mut leftover_ids);
                    if leftover_ids.is_empty() {
                        continue;
                    }
                    let archive_path = archive_folder
                        .get_or_insert_with(|| {
                            let name = format!("{} Archive", archive_timestamp());
                            find_or_create_folder(root, &name);
                            name
                        })
                        .clone();
                    for id in &leftover_ids {
                        if tree::move_bookmark(root, id, &archive_path).is_ok() {
                            archived += 1;
                        }
                    }
                }

                (prune_empty_source_folders(root, &prunable), archived)
            } else {
                (0, 0)
            };

            ClassifyApplyResp { ok: true, applied, skipped, pruned, archived }
        })
        .await;

    Ok(Json(resp))
}

/// Every bookmark id under `node`, recursing into sub-folders. Used to sweep
/// a to-be-deleted scope folder's leftovers into the Archive folder before
/// pruning it.
fn collect_bookmark_ids_recursive(node: &nbm_core::Node, out: &mut Vec<String>) {
    for child in &node.children {
        if child.is_folder() {
            collect_bookmark_ids_recursive(child, out);
        } else {
            out.push(child.bookmark_id.clone());
        }
    }
}

/// UTC "YYYYMMDD HHMMSS" for the Archive folder name. Hand-rolled (no chrono
/// dependency) to match `nbm_core::db`'s epoch-seconds-only convention
/// elsewhere in this codebase, just formatted as a calendar date instead of
/// a raw integer.
fn archive_timestamp() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0) as i64;
    format_timestamp(secs)
}

fn format_timestamp(epoch_secs: i64) -> String {
    let days = epoch_secs.div_euclid(86400);
    let time_of_day = epoch_secs.rem_euclid(86400);
    let (y, m, d) = civil_from_days(days);
    let hh = time_of_day / 3600;
    let mm = (time_of_day % 3600) / 60;
    let ss = time_of_day % 60;
    format!("{y:04}{m:02}{d:02} {hh:02}{mm:02}{ss:02}")
}

/// Howard Hinnant's `civil_from_days`: days since 1970-01-01 (UTC) -> (year,
/// month, day). http://howardhinnant.github.io/date_algorithms.html
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 }.div_euclid(146097);
    let doe = (z - era * 146097) as u64; // [0, 146096]
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365; // [0, 399]
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32; // [1, 12]
    let y = if m <= 2 { y + 1 } else { y };
    (y, m, d)
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

    #[test]
    fn civil_from_days_matches_known_dates() {
        assert_eq!(civil_from_days(0), (1970, 1, 1));
        // 1700000000s (a widely-cited reference epoch value) is 2023-11-14 UTC.
        assert_eq!(civil_from_days(1_700_000_000 / 86400), (2023, 11, 14));
        assert_eq!(civil_from_days(365), (1971, 1, 1));
    }

    #[test]
    fn format_timestamp_renders_date_and_time() {
        // 1700000000 = 2023-11-14 22:13:20 UTC.
        assert_eq!(format_timestamp(1_700_000_000), "20231114 221320");
    }

    #[test]
    fn collect_bookmark_ids_recurses_into_subfolders() {
        let mut root = Node::new_root();
        let mut folder = Node::new_folder("Scope");
        folder.children.push(Node::new_bookmark("a", "https://a.test/"));
        let mut sub = Node::new_folder("Sub");
        sub.children.push(Node::new_bookmark("b", "https://b.test/"));
        folder.children.push(sub);
        root.children.push(folder);

        let scope = tree::find_folder(&root, "Scope").unwrap();
        let mut ids = Vec::new();
        collect_bookmark_ids_recursive(scope, &mut ids);
        assert_eq!(ids.len(), 2, "{ids:?}");
    }

    #[test]
    fn apply_archives_leftovers_from_the_declared_scope_only() {
        let mut root = Node::new_root();
        // Scope folder: one bookmark gets a move, one is left behind
        // (unchecked / no AI suggestion) — it must be archived, not left in
        // place or silently dropped.
        let mut scope = Node::new_folder("Untidy");
        scope.children.push({
            let mut b = Node::new_bookmark("moved", "https://moved.test/");
            b.bookmark_id = "moved".into();
            b
        });
        scope.children.push({
            let mut b = Node::new_bookmark("left-behind", "https://left.test/");
            b.bookmark_id = "left".into();
            b
        });
        root.children.push(scope);
        // Unrelated donor folder: only coincidentally loses one bookmark to
        // this same apply call. Its other bookmark must NOT be swept away —
        // it was never part of this run's scope.
        let mut donor = Node::new_folder("Donor");
        donor.children.push({
            let mut b = Node::new_bookmark("donated", "https://donated.test/");
            b.bookmark_id = "donated".into();
            b
        });
        donor.children.push({
            let mut b = Node::new_bookmark("unrelated", "https://unrelated.test/");
            b.bookmark_id = "unrelated".into();
            b
        });
        root.children.push(donor);

        let body = ClassifyApplyBody {
            moves: vec![
                ApplyMoveItem { bookmark_id: "moved".into(), folder_path: "Topic".into() },
                ApplyMoveItem { bookmark_id: "donated".into(), folder_path: "Topic".into() },
            ],
            prune_empty_source: true,
            archive_scope_paths: vec!["Untidy".into()],
        };

        let mut applied = 0usize;
        let mut sources: HashSet<String> = HashSet::new();
        let mut targets: HashSet<String> = HashSet::new();
        for mv in &body.moves {
            let target = sanitize_destination(&mv.folder_path).unwrap();
            if let Some((src, _)) = tree::locate_bookmark(&root, &mv.bookmark_id) {
                sources.insert(src);
            }
            find_or_create_folder(&mut root, &target);
            tree::move_bookmark(&mut root, &mv.bookmark_id, &target).unwrap();
            applied += 1;
            targets.insert(target);
        }
        assert_eq!(applied, 2);

        let prunable: HashSet<String> = sources.difference(&targets).cloned().collect();
        let scope: HashSet<&String> = body.archive_scope_paths.iter().collect();
        let mut archived = 0usize;
        let mut archive_folder: Option<String> = None;
        for path in prunable.iter().filter(|p| scope.contains(p)) {
            let folder = tree::find_folder(&root, path).unwrap();
            let mut leftover_ids = Vec::new();
            collect_bookmark_ids_recursive(folder, &mut leftover_ids);
            if leftover_ids.is_empty() {
                continue;
            }
            let archive_path = archive_folder
                .get_or_insert_with(|| {
                    let name = format!("{} Archive", archive_timestamp());
                    find_or_create_folder(&mut root, &name);
                    name
                })
                .clone();
            for id in &leftover_ids {
                if tree::move_bookmark(&mut root, id, &archive_path).is_ok() {
                    archived += 1;
                }
            }
        }
        let pruned = prune_empty_source_folders(&mut root, &prunable);

        assert_eq!(archived, 1, "only the scoped folder's leftover must be archived");
        assert_eq!(pruned, 1, "the now-empty scope folder must be removed");
        assert_eq!(count_children_named(&root, "Untidy"), 0, "scope folder must be gone");
        assert_eq!(
            count_children_named(&root, "Donor"), 1,
            "an incidental donor folder must survive with its unrelated bookmark intact"
        );
        let donor = tree::find_folder(&root, "Donor").unwrap();
        assert_eq!(donor.count_bookmarks(), 1, "unrelated donor bookmark must not be swept away");
        assert!(
            tree::locate_bookmark(&root, "left").is_some(),
            "the leftover bookmark must still exist somewhere (archived, not deleted)"
        );
        let (archive_path, _) = tree::locate_bookmark(&root, "left").unwrap();
        assert!(archive_path.ends_with("Archive"), "got {archive_path:?}");
    }
}
