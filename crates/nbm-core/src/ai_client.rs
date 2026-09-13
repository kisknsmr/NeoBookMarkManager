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
    content: GeminiContent,
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

    fn truncate_chars(s: &str, max: usize) -> String {
        s.chars().take(max).collect()
    }

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
        let req_body = serde_json::json!({
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        });

        let resp = match client
            .post(&endpoint)
            .json(&req_body)
            .timeout(std::time::Duration::from_secs(60))
            .send()
            .await
        {
            Ok(r) => r,
            Err(e) => { last_err = e.to_string(); continue; }
        };

        let status = resp.status();
        let status_code = status.as_u16();
        if !status.is_success() {
            // Gemini's error body (e.g. `{"error":{"message":"API key not
            // valid","status":"INVALID_ARGUMENT"}}`) is far more diagnostic
            // than the bare status code — surface it instead of discarding it.
            let body = resp.text().await.unwrap_or_default();
            let detail = extract_gemini_error_message(&body)
                .unwrap_or_else(|| truncate_chars(&body, 300));
            let msg = if detail.is_empty() {
                format!("HTTP {status_code}")
            } else {
                format!("HTTP {status_code}: {detail}")
            };
            // Don't loop back into the JSON-format retry here: that would fire
            // another request immediately, doubling up on whatever rate limit
            // or outage just rejected us. Return so the caller's backoff
            // (which can honor the server's suggested retry delay) applies
            // before anything is sent again.
            return Err(msg);
        }

        let text: String = match resp.text().await {
            Ok(t) => t,
            Err(e) => { last_err = e.to_string(); continue; }
        };

        let raw_text = serde_json::from_str::<GeminiResponse>(&text)
            .ok()
            .and_then(|g| g.candidates.into_iter().next())
            .and_then(|c| c.content.parts.into_iter().next())
            .map(|p| p.text)
            .unwrap_or_else(|| text.clone());

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
