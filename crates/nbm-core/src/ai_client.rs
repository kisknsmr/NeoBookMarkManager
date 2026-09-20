//! Gemini REST client for bookmark classification.
//!
//! The prompt/payload/cost side lives in [`crate::ai_classify`]; this module is
//! only the transport plus the response shapes, so the estimator and the caller
//! agree on exactly what gets sent.

use serde::Deserialize;

use crate::ai_classify;

#[derive(serde::Deserialize)]
struct GeminiResponse {
    candidates: Vec<GeminiCandidate>,
}

#[derive(serde::Deserialize)]
struct GeminiCandidate {
    #[serde(default)]
    content: Option<GeminiContent>,
    /// "STOP" on a complete answer. "MAX_TOKENS" means the JSON was cut off
    /// mid-way, which used to surface only as an unexplained parse failure.
    #[serde(rename = "finishReason", default)]
    finish_reason: Option<String>,
}

#[derive(serde::Deserialize)]
struct GeminiContent {
    parts: Vec<GeminiPart>,
}

#[derive(serde::Deserialize)]
struct GeminiPart {
    text: String,
}

#[derive(serde::Deserialize)]
struct MovesResponse {
    moves: Vec<RawMove>,
}

#[derive(serde::Deserialize)]
struct RawMove {
    index: usize,
    folder: String,
    confidence: f64,
    reason: String,
}

pub fn extract_gemini_json(text: &str) -> Option<String> {
    let t = text.trim();
    let start = t.find('{')?;
    let end = t.rfind('}')?;
    if end > start { Some(t[start..=end].to_string()) } else { None }
}

/// Pull the human-readable `error.message` out of a Gemini API error body,
/// e.g. `{"error":{"code":400,"message":"API key not valid.","status":"INVALID_ARGUMENT"}}`.
pub fn extract_gemini_error_message(body: &str) -> Option<String> {
    #[derive(Deserialize)]
    struct ErrBody { error: ErrDetail }
    #[derive(Deserialize)]
    struct ErrDetail { message: Option<String>, status: Option<String> }
    let parsed: ErrBody = serde_json::from_str(body).ok()?;
    match (parsed.error.status, parsed.error.message) {
        (Some(s), Some(m)) => Some(format!("{s}: {m}")),
        (None, Some(m)) => Some(m),
        (Some(s), None) => Some(s),
        (None, None) => None,
    }
}

/// Gemini 429 (RESOURCE_EXHAUSTED) messages end with e.g. "Please retry in
/// 23.556131354s." — parse that out so we can wait the suggested amount
/// instead of guessing with a short fixed backoff that just gets rejected
/// again.
pub fn parse_retry_after_secs(msg: &str) -> Option<f64> {
    let lower = msg.to_lowercase();
    let idx = lower.find("retry in ")?;
    let rest = &msg[idx + "retry in ".len()..];
    let end = rest.find('s')?;
    rest[..end].trim().parse::<f64>().ok()
}

/// Why a request failed, and whether the caller should try again straight away.
enum PostErr {
    /// An HTTP-level rejection (quota, bad key, retired model…). Retrying at
    /// once would only double up on whatever refused us, so this goes back to
    /// the caller's backoff instead.
    Fatal(String),
    /// A transport hiccup or an unreadable body: worth another immediate go.
    Soft(String),
}

/// POST one prompt to `generateContent` and return the model's raw text.
async fn post_generate(
    client: &reqwest::Client,
    endpoint: &str,
    prompt_text: &str,
    timeout_secs: u64,
) -> Result<String, PostErr> {
    let req_body = serde_json::json!({
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    });

    let resp = client
        .post(endpoint)
        .json(&req_body)
        .timeout(std::time::Duration::from_secs(timeout_secs))
        .send()
        .await
        .map_err(|e| PostErr::Soft(e.to_string()))?;

    let status = resp.status();
    let status_code = status.as_u16();
    if !status.is_success() {
        // Gemini's error body (e.g. `{"error":{"message":"API key not
        // valid","status":"INVALID_ARGUMENT"}}`) is far more diagnostic than the
        // bare status code — surface it instead of discarding it.
        let body = resp.text().await.unwrap_or_default();
        let detail = extract_gemini_error_message(&body)
            .unwrap_or_else(|| body.chars().take(300).collect());
        return Err(PostErr::Fatal(if detail.is_empty() {
            format!("HTTP {status_code}")
        } else {
            format!("HTTP {status_code}: {detail}")
        }));
    }

    let text = resp.text().await.map_err(|e| PostErr::Soft(e.to_string()))?;
    let Some(candidate) = serde_json::from_str::<GeminiResponse>(&text)
        .ok()
        .and_then(|g| g.candidates.into_iter().next())
    else {
        // Not the shape we know — hand the body on and let the JSON step report.
        return Ok(text);
    };
    if let Some(reason) = candidate.finish_reason.as_deref() {
        if let Some(msg) = unfinished_reason(reason) {
            return Err(PostErr::Fatal(msg));
        }
    }
    Ok(candidate
        .content
        .and_then(|c| c.parts.into_iter().next())
        .map(|p| p.text)
        .unwrap_or(text))
}

/// Explain a `finishReason` that means the answer is not usable, or `None` when
/// the model finished normally.
///
/// Retrying an identical request would be cut off at exactly the same place, so
/// these are reported rather than retried — the caller hands the ids back and
/// the UI offers to re-run just those.
pub fn unfinished_reason(reason: &str) -> Option<String> {
    match reason {
        "STOP" | "" => None,
        "MAX_TOKENS" => Some(
            "応答が長すぎて途中で切れました（finishReason=MAX_TOKENS）。\
             AI設定で「1回のリクエストに含める件数」を減らして再実行してください。"
                .to_string(),
        ),
        "SAFETY" | "PROHIBITED_CONTENT" | "BLOCKLIST" | "SPII" => Some(format!(
            "送信内容がGemini側の安全フィルタでブロックされました（finishReason={reason}）。"
        )),
        other => Some(format!("モデルが応答を完了できませんでした（finishReason={other}）。")),
    }
}

#[derive(serde::Deserialize)]
struct FoldersResponse {
    folders: Vec<String>,
}

/// Ask the model for the folder structure of the *whole* list, before any
/// bookmark is filed. The answer is only folder names, so it stays small no
/// matter how many bookmarks go in.
pub async fn call_gemini_folders(
    client: &reqwest::Client,
    api_key: &str,
    model: &str,
    prompt: &str,
    items: &[ai_classify::BookmarkItem],
    sanitize_urls: bool,
    fields: ai_classify::FieldSelection,
) -> Result<Vec<String>, String> {
    let data_json = ai_classify::build_batch_payload(items, fields, sanitize_urls);
    let full_prompt = format!("{prompt}\n\n{data_json}");
    let endpoint = format!(
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    );

    let mut last_err = String::from("no response");
    for _ in 0..2u8 {
        // A whole-library payload is large, so allow more time than a chunk.
        let raw_text = match post_generate(client, &endpoint, &full_prompt, 180).await {
            Ok(t) => t,
            Err(PostErr::Fatal(m)) => return Err(m),
            Err(PostErr::Soft(m)) => { last_err = m; continue; }
        };
        let Some(json_str) = extract_gemini_json(&raw_text) else {
            last_err = "no JSON in response".into();
            continue;
        };
        let parsed = serde_json::from_str::<FoldersResponse>(&json_str)
            .map(|r| r.folders)
            .or_else(|_| serde_json::from_str::<Vec<String>>(&json_str));
        match parsed {
            Ok(folders) => return Ok(folders),
            Err(e) => last_err = format!("JSON parse: {e}"),
        }
    }
    Err(last_err)
}

pub async fn call_gemini_batch(
    client: &reqwest::Client,
    api_key: &str,
    model: &str,
    prompt: &str,
    batch: &[ai_classify::BookmarkItem],
    sanitize_urls: bool,
    fields: ai_classify::FieldSelection,
) -> Result<Vec<ai_classify::AiMove>, String> {
    use ai_classify::AiMove;

    // Payload construction lives in nbm-core so the cost estimator measures
    // exactly what gets transmitted here.
    let data_json = ai_classify::build_batch_payload(batch, fields, sanitize_urls);
    let full_prompt = format!("{prompt}\n\n{data_json}");
    let endpoint = format!(
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    );

    let mut last_err = String::from("no response");
    for json_retry in 0..3u8 {
        let prompt_text = if json_retry == 0 {
            full_prompt.clone()
        } else {
            format!(
                "{full_prompt}\n\nYour previous output did not match the required schema. \
                 The top-level JSON object MUST have a \"moves\" key whose value is an array, \
                 e.g. {{\"moves\":[{{\"index\":0,\"folder\":\"FolderName\",\"confidence\":0.9,\"reason\":\"...\"}}]}}. \
                 Output ONLY that JSON object, nothing else."
            )
        };
        let raw_text = match post_generate(client, &endpoint, &prompt_text, 60).await {
            Ok(t) => t,
            Err(PostErr::Fatal(m)) => return Err(m),
            Err(PostErr::Soft(m)) => { last_err = m; continue; }
        };

        let json_str = match extract_gemini_json(&raw_text) {
            Some(s) => s,
            None => { last_err = "no JSON in response".into(); continue; }
        };

        // The model is instructed to return {"moves":[...]}, but occasionally
        // drops the wrapper and returns the bare array instead. Accept both
        // shapes rather than failing the whole chunk over a missing key.
        let raw_moves: Result<Vec<RawMove>, serde_json::Error> =
            serde_json::from_str::<MovesResponse>(&json_str)
                .map(|m| m.moves)
                .or_else(|_| serde_json::from_str::<Vec<RawMove>>(&json_str));

        match raw_moves {
            Ok(moves) => {
                let moves = moves.into_iter().filter_map(|m| {
                    if m.index >= batch.len() { return None; }
                    // Keep `/` as a path separator: the vocabulary hands the
                    // model full paths of existing folders to reuse, and
                    // flattening them here turned every reuse into a new
                    // top-level folder named "Parent_Child".
                    let folder = ai_classify::sanitize_folder_path(&m.folder);
                    if folder.is_empty() { return None; }
                    Some(AiMove {
                        bookmark_id: batch[m.index].bookmark_id.clone(),
                        folder,
                        confidence: m.confidence.clamp(0.0, 1.0),
                        reason: m.reason,
                    })
                }).collect();
                return Ok(moves);
            }
            Err(e) => { last_err = format!("JSON parse: {e}"); continue; }
        }
    }
    Err(last_err)
}

/// A quota/rate-limit rejection that survived the retry loop. Retrying the same
/// key further will not help (a daily cap won't clear within the run), so this
/// is the point at which switching to the paid key is worth offering.
pub fn is_quota_error(msg: &str) -> bool {
    msg.contains("429")
        || msg.contains("RESOURCE_EXHAUSTED")
        || msg.to_lowercase().contains("quota")
}

/// A model id Gemini no longer serves for this call — retired, renamed, or
/// never valid to begin with. Google periodically changes its Gemini lineup,
/// so whatever model config.ini names today can stop resolving with no
/// warning.
///
/// Distinct from a transient failure: every remaining chunk in the run would
/// hit the exact same 404, so the caller stops the whole run here instead of
/// working through the batch one identical failure at a time.
pub fn is_model_unavailable_error(msg: &str) -> bool {
    msg.contains("404")
        || msg.contains("NOT_FOUND")
        || msg.to_lowercase().contains("is not found for api")
        || msg.to_lowercase().contains("not supported for generatecontent")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_cut_off_answer_is_reported_instead_of_parsed() {
        assert!(unfinished_reason("STOP").is_none());
        assert!(unfinished_reason("").is_none());
        let msg = unfinished_reason("MAX_TOKENS").unwrap();
        assert!(msg.contains("件数"), "{msg}");
        assert!(unfinished_reason("SAFETY").unwrap().contains("ブロック"));
        assert!(unfinished_reason("WHATEVER").unwrap().contains("WHATEVER"));
    }

    #[test]
    fn quota_errors_are_recognised() {
        assert!(is_quota_error("HTTP 429: rate limited"));
        assert!(is_quota_error("RESOURCE_EXHAUSTED: too many requests"));
        assert!(is_quota_error("You exceeded your current Quota"));
    }

    #[test]
    fn model_unavailable_errors_are_recognised() {
        // The exact message Gemini returns for a retired/renamed model id.
        assert!(is_model_unavailable_error(
            "HTTP 404: models/gemini-1.0-pro is not found for API version              v1beta, or is not supported for generateContent."
        ));
        assert!(is_model_unavailable_error("NOT_FOUND"));
        // A quota rejection must not be misread as a dead model — they take
        // different recovery paths (wait/switch key vs. pick another model).
        assert!(!is_model_unavailable_error("HTTP 429: rate limited"));
        assert!(!is_model_unavailable_error("HTTP 400: API key not valid"));
    }

    #[test]
    fn non_quota_errors_are_not_treated_as_quota() {
        assert!(!is_quota_error("HTTP 400: API key not valid"));
        assert!(!is_quota_error("JSON parse: expected value"));
        assert!(!is_quota_error("HTTP 503: service unavailable"));
    }

    #[test]
    fn retry_after_is_parsed_from_the_server_message() {
        assert_eq!(
            parse_retry_after_secs("RESOURCE_EXHAUSTED. Please retry in 23.556131354s."),
            Some(23.556131354)
        );
        assert_eq!(parse_retry_after_secs("no suggestion here"), None);
    }

    #[test]
    fn the_error_message_is_lifted_out_of_the_api_body() {
        let body = r#"{"error":{"code":400,"message":"API key not valid.","status":"INVALID_ARGUMENT"}}"#;
        assert_eq!(
            extract_gemini_error_message(body).as_deref(),
            Some("INVALID_ARGUMENT: API key not valid.")
        );
        assert_eq!(extract_gemini_error_message("not json"), None);
    }

    #[test]
    fn json_is_extracted_from_a_chatty_response() {
        assert_eq!(
            extract_gemini_json("Sure! {\"moves\":[]} hope that helps").as_deref(),
            Some("{\"moves\":[]}")
        );
        assert_eq!(extract_gemini_json("no braces at all"), None);
    }
}
