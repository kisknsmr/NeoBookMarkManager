//! The AI settings screen: API keys, tier declaration, pricing and the model
//! catalog. These write back into config.ini.

use axum::extract::State;
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::{Deserialize, Serialize};

use crate::settings::{self, default_model, DEFAULT_MODELS_JSON};
use crate::state::AppState;

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/config/ai-status", get(config_ai_status))
        .route("/config/api-key", post(config_set_api_key))
        .route("/config/ai-tier", post(config_set_ai_tier))
        .route("/config/ai-pricing", post(config_set_ai_pricing))
        .route("/config/models", get(config_models))
}

#[derive(Serialize)]
struct AiStatusResp {
    /// Whether a usable API key is configured (never returns the key itself).
    api_key_set: bool,
    /// Where the key came from: "env" | "config" | "none".
    api_key_source: String,
    /// Whether both input & output prices resolve (> 0) — required to run AI.
    pricing_set: bool,
    /// Where the effective price came from: "catalog" | "config" | "none".
    pricing_source: String,
    /// The price that would actually be used for `model`.
    input_cost_per_1m: Option<f64>,
    output_cost_per_1m: Option<f64>,
    /// The config.ini fallback values, shown so the settings form can edit them.
    config_input_cost_per_1m: Option<f64>,
    config_output_cost_per_1m: Option<f64>,
    model: String,
    /// User-declared tier of the primary key. None = undeclared: the UI then
    /// states neither "課金されます" nor "無料です" rather than guessing.
    free_tier: Option<bool>,
    /// Whether a billing-enabled fallback key is registered.
    paid_key_set: bool,
    /// Which config.ini is actually in use. Surfaced because a portable install
    /// reads the config/ next to the exe, not the one in the repo — a mismatch
    /// that silently looks like "APIキー未設定".
    config_path: Option<String>,
}

async fn config_ai_status(State(state): State<AppState>) -> Json<AiStatusResp> {
    let env_key = std::env::var("GENAI_API_KEY").ok()
        .or_else(|| std::env::var("GOOGLE_API_KEY").ok())
        .filter(|s| !s.trim().is_empty());
    let cfg = state.inner.config_ini_path.as_ref()
        .and_then(|p| nbm_core::ConfigManager::load(p).ok());
    let cfg_key = cfg.as_ref()
        .and_then(|c| c.get("API", "api_key"))
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty() && !s.starts_with('<'));

    let (source, set) = if env_key.is_some() {
        ("env".to_string(), true)
    } else if cfg_key.is_some() {
        ("config".to_string(), true)
    } else {
        ("none".to_string(), false)
    };

    let model = cfg.as_ref()
        .and_then(|c| c.get("AI", "model"))
        .unwrap_or_else(default_model);
    // Report the price that would actually be used for this model, not just
    // whatever config.ini happens to hold.
    let (in_price, out_price, pricing_source) = settings::resolve_ai_pricing(&state, &model);
    let (cfg_in, cfg_out) = settings::config_ai_pricing(&state);

    Json(AiStatusResp {
        api_key_set: set,
        api_key_source: source,
        pricing_set: in_price.is_some() && out_price.is_some(),
        pricing_source: pricing_source.to_string(),
        input_cost_per_1m: in_price,
        output_cost_per_1m: out_price,
        config_input_cost_per_1m: cfg_in,
        config_output_cost_per_1m: cfg_out,
        model,
        free_tier: settings::free_tier_flag(&state),
        paid_key_set: settings::paid_api_key(&state).is_some(),
        config_path: state.inner.config_ini_path.as_ref().map(|p| p.display().to_string()),
    })
}

#[derive(Deserialize)]
struct SetApiKeyBody {
    api_key: String,
    /// Save into `[API] paid_api_key` (the billing-enabled fallback) instead of
    /// the default `api_key`.
    #[serde(default)]
    paid: bool,
}

/// The settings screen shows `message` verbatim, so failures come back as
/// `ok: false` with an explanation rather than as an HTTP error.
#[derive(Serialize)]
struct SetApiKeyResp {
    ok: bool,
    message: String,
}

impl SetApiKeyResp {
    fn saved(message: impl Into<String>) -> Self {
        Self { ok: true, message: message.into() }
    }
    fn failed(message: impl Into<String>) -> Self {
        Self { ok: false, message: message.into() }
    }
}

/// Open config.ini for writing, or the message explaining why we cannot.
///
/// The three settings writers below all start this way.
fn writable_config(state: &AppState) -> Result<nbm_core::ConfigManager, SetApiKeyResp> {
    let Some(path) = state.inner.config_ini_path.clone() else {
        return Err(SetApiKeyResp::failed("config.ini マパス未設定"));
    };
    nbm_core::ConfigManager::load(&path)
        .map_err(|e| SetApiKeyResp::failed(format!("config 読込失敗: {e}")))
}

async fn config_set_api_key(
    State(state): State<AppState>,
    Json(body): Json<SetApiKeyBody>,
) -> Json<SetApiKeyResp> {
    let key = body.api_key.trim();
    if key.is_empty() {
        return Json(SetApiKeyResp::failed("APIキーが空です"));
    }
    let mut cfg = match writable_config(&state) {
        Ok(cfg) => cfg,
        Err(resp) => return Json(resp),
    };
    let option = if body.paid { "paid_api_key" } else { "api_key" };
    let label = if body.paid { "有料枠のAPIキー" } else { "APIキー" };
    match cfg.set("API", option, key) {
        Ok(()) => Json(SetApiKeyResp::saved(format!("{label}を保存しました"))),
        Err(e) => Json(SetApiKeyResp::failed(format!("保存失敗: {e}"))),
    }
}

#[derive(Deserialize)]
struct SetAiTierBody {
    free_tier: bool,
}

/// Record whether the primary key is on the free tier. Purely a user
/// declaration — the API exposes no way to ask which tier a key belongs to.
async fn config_set_ai_tier(
    State(state): State<AppState>,
    Json(body): Json<SetAiTierBody>,
) -> Json<SetApiKeyResp> {
    let mut cfg = match writable_config(&state) {
        Ok(cfg) => cfg,
        Err(resp) => return Json(resp),
    };
    match cfg.set("AI", "free_tier", if body.free_tier { "true" } else { "false" }) {
        Ok(()) => Json(SetApiKeyResp::saved(if body.free_tier {
            "無料枠として記録しました"
        } else {
            "有料枠として記録しました"
        })),
        Err(e) => Json(SetApiKeyResp::failed(format!("保存失敗: {e}"))),
    }
}

#[derive(Deserialize)]
struct SetAiPricingBody {
    /// Model id (config.ini [AI].model). Omitted/empty leaves the current model untouched.
    model: Option<String>,
    input_cost_per_1m: f64,
    output_cost_per_1m: f64,
}

/// Save model + USD/1M-token pricing (config.ini [AI]) from the AI settings UI,
/// so users don't have to hand-edit config.ini to clear the cost-approval gate.
async fn config_set_ai_pricing(
    State(state): State<AppState>,
    Json(body): Json<SetAiPricingBody>,
) -> Json<SetApiKeyResp> {
    // NaN and infinity must be rejected as well as zero/negative, so this tests
    // for a usable price rather than negating a comparison (NaN fails both).
    let is_usable_price = |v: f64| v.is_finite() && v > 0.0;
    if !is_usable_price(body.input_cost_per_1m) || !is_usable_price(body.output_cost_per_1m) {
        return Json(SetApiKeyResp::failed("単価は0より大きい値を入力してください"));
    }
    let mut cfg = match writable_config(&state) {
        Ok(cfg) => cfg,
        Err(resp) => return Json(resp),
    };
    if let Some(model) = body.model.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        if let Err(e) = cfg.set("AI", "model", model) {
            return Json(SetApiKeyResp::failed(format!("保存失敗: {e}")));
        }
    }
    if let Err(e) = cfg.set("AI", "input_cost_per_1m_tokens", &body.input_cost_per_1m.to_string()) {
        return Json(SetApiKeyResp::failed(format!("保存失敗: {e}")));
    }
    match cfg.set("AI", "output_cost_per_1m_tokens", &body.output_cost_per_1m.to_string()) {
        Ok(()) => Json(SetApiKeyResp::saved("コスト単価を保存しました")),
        Err(e) => Json(SetApiKeyResp::failed(format!("保存失敗: {e}"))),
    }
}

#[derive(Serialize)]
struct ModelsResp {
    /// The currently selected model id (config.ini [AI].model).
    current: String,
    /// Raw models.json content passed through verbatim, or null if unavailable.
    catalog: Option<serde_json::Value>,
    /// Set when models.json could not be read/parsed (UI falls back gracefully).
    error: Option<String>,
    /// True when the catalog came from a models.json on disk; false when it is
    /// the copy embedded in the binary.
    from_file: bool,
}

/// Return the model price catalog (config/models.json) for display in the UI.
/// The file lives next to config.ini; falls back to ./config/models.json.
async fn config_models(State(state): State<AppState>) -> Json<ModelsResp> {
    let current = settings::selected_model(&state);
    let (text, from_file) = settings::models_json_text(&state);
    match serde_json::from_str::<serde_json::Value>(&text) {
        Ok(v) => Json(ModelsResp { current, catalog: Some(v), error: None, from_file }),
        Err(e) => {
            // A broken on-disk file should not take the price table down with
            // it — fall back to the embedded copy and say so.
            match serde_json::from_str::<serde_json::Value>(DEFAULT_MODELS_JSON) {
                Ok(v) => Json(ModelsResp {
                    current, catalog: Some(v), from_file: false,
                    error: Some(format!("models.json のパースに失敗したため、内蔵の価格表を使用しています: {e}")),
                }),
                Err(_) => Json(ModelsResp {
                    current, catalog: None, from_file: false,
                    error: Some(format!("models.json パース失敗: {e}")),
                }),
            }
        }
    }
}
