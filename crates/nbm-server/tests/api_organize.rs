//! Organize, classify (non-network parts) and settings endpoints.

mod support;

use axum::http::StatusCode;
use serde_json::json;
use support::{app, Fixture};

const CONFIG_INI: &str = "[API]\napi_key = test-key-123\n\n[AI]\nmodel = gemini-2.5-flash-lite\n";

/// Every bookmark_id in the tree, in listing order.
async fn all_ids(app: &support::TestApp) -> Vec<String> {
    let (_, list) = app.get("/bookmarks").await;
    list["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|b| b["bookmark_id"].as_str().unwrap().to_string())
        .collect()
}

// --- Organize --------------------------------------------------------------

#[tokio::test]
async fn dedupe_removes_bookmarks_sharing_a_url() {
    let app = app().await;
    let (status, body) = app
        .post("/organize/dedupe", json!({ "folder_path": "Work" }))
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], true);
    assert_eq!(body["count"], 1, "Dup shares A's url");

    assert_eq!(app.titles_in("Work").await, ["A", "B"]);
    let (_, hist) = app.get("/edit/history").await;
    assert_eq!(hist["undo_count"], 1, "dedupe must be undoable");
}

#[tokio::test]
async fn dedupe_on_an_unknown_folder_is_a_bad_request() {
    let app = app().await;
    let (status, _) = app
        .post("/organize/dedupe", json!({ "folder_path": "Ghost" }))
        .await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn merging_duplicate_folders_combines_same_named_siblings() {
    let app = app().await;
    // A second root-level "Work" folder, then something inside it.
    app.post("/edit/folder/add", json!({ "parent_path": "", "title": "Work" }))
        .await;
    app.post(
        "/edit/bookmark/add",
        json!({ "folder_path": "Work", "title": "E", "url": "https://e.test/" }),
    )
    .await;

    let (status, body) = app
        .post("/organize/merge-duplicate-folders", json!({ "parent_path": "" }))
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["count"], 1);

    let (_, tree) = app.get("/tree").await;
    let work_folders = tree["children"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c["title"] == "Work")
        .count();
    assert_eq!(work_folders, 1, "the duplicate was folded into the first");
}

#[tokio::test]
async fn domain_statistics_counts_bookmarks_per_host() {
    let app = app().await;
    let (status, body) = app.get("/organize/domain-stats").await;
    assert_eq!(status, StatusCode::OK);

    let stats: Vec<(String, u64)> = body["stats"]
        .as_array()
        .unwrap()
        .iter()
        .map(|s| {
            (
                s["domain"].as_str().unwrap().to_string(),
                s["count"].as_u64().unwrap(),
            )
        })
        .collect();
    let github = stats.iter().find(|(d, _)| d == "github.com").expect("github.com");
    assert_eq!(github.1, 3, "A, B and Dup all live on github.com");
    assert!(stats.iter().any(|(d, c)| d == "example.com" && *c == 1));
    assert!(stats.iter().any(|(d, c)| d == "example.org" && *c == 1));
}

#[tokio::test]
async fn sort_by_domain_orders_bookmarks_and_moves_folders_after() {
    let app = app().await;
    // Shuffle so the sort has something to do.
    let dup = app.bookmark_id("Dup").await;
    app.post(&format!("/edit/bookmark/{dup}/reorder"), json!({ "new_index": 0 }))
        .await;
    assert_eq!(app.titles_in("Work").await, ["Dup", "A", "B"]);

    let (status, body) = app
        .post("/organize/sort-by-domain", json!({ "folder_path": "Work" }))
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["count"], 4, "3 bookmarks + the Nested folder");
    assert_eq!(app.titles_in("Work").await, ["A", "B", "Dup"]);

    let (_, tree) = app.get("/tree").await;
    let work = &tree["children"][0];
    let last = work["children"].as_array().unwrap().last().unwrap();
    assert_eq!(
        last["title"], "Nested",
        "folders must sort after every direct bookmark"
    );
}

#[tokio::test]
async fn consolidating_a_domain_gathers_matching_bookmarks() {
    let app = app().await;
    let (status, body) = app
        .post(
            "/organize/consolidate-by-domain",
            json!({ "domain": "github.com", "target_folder": "GH" }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["count"], 3);

    for title in ["A", "B", "Dup"] {
        assert_eq!(
            app.folder_of(title).await.as_deref(),
            Some("GH"),
            "{title} should have moved into GH"
        );
    }
    // Untouched bookmarks stay put.
    assert_eq!(app.folder_of("C").await.as_deref(), Some("Work/Nested"));
    assert_eq!(app.folder_of("D").await.as_deref(), Some("Personal"));
}

#[tokio::test]
async fn consolidating_honours_a_keyword_filter() {
    let app = app().await;
    let (status, body) = app
        .post(
            "/organize/consolidate-by-domain",
            json!({ "domain": "github.com", "target_folder": "GH", "keyword": "dup" }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["count"], 1);
    assert_eq!(app.folder_of("Dup").await.as_deref(), Some("GH"));
    assert_eq!(app.folder_of("A").await.as_deref(), Some("Work"));
}

// --- Classify (no network) -------------------------------------------------

#[tokio::test]
async fn readiness_reports_what_the_model_would_receive() {
    let app = app().await;
    let ids = all_ids(&app).await;

    let (status, body) = app
        .post("/classify/readiness", json!({ "bookmark_ids": ids }))
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["total"], 5);
    assert_eq!(body["with_title"], 5);
    assert_eq!(body["with_description"], 0);
    assert_eq!(body["with_tags"], 0);
    assert_eq!(body["bare"], 0, "titles are present, so nothing is bare");
}

#[tokio::test]
async fn a_blank_title_falls_back_to_the_url() {
    let app = app().await;
    let (_, added) = app
        .post(
            "/edit/bookmark/add",
            json!({ "folder_path": "Work", "title": "  ", "url": "https://bare.test/" }),
        )
        .await;
    let id = added["bookmark_id"].as_str().unwrap().to_string();

    // add_bookmark substitutes the url for a blank title, so the model always
    // gets at least that much to work with — nothing is left truly bare.
    let (_, body) = app
        .post("/classify/readiness", json!({ "bookmark_ids": [id] }))
        .await;
    assert_eq!(body["total"], 1);
    assert_eq!(body["with_title"], 1);
    assert_eq!(body["bare"], 0);

    let (_, list) = app.get("/bookmarks").await;
    let added = list["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|b| b["bookmark_id"] == id.as_str())
        .unwrap();
    assert_eq!(added["title"], "https://bare.test/");
}

#[tokio::test]
async fn readiness_counts_bookmarks_with_no_signal_as_bare() {
    let app = app().await;
    // Ask about an id that is not in the tree at all: it contributes nothing.
    let (_, body) = app
        .post("/classify/readiness", json!({ "bookmark_ids": ["ghost"] }))
        .await;
    assert_eq!(body["total"], 0);
    assert_eq!(body["bare"], 0);
}

#[tokio::test]
async fn estimate_reports_a_cost_and_a_consistent_gate() {
    let app = Fixture::default().with_config(CONFIG_INI).build().await;
    let ids = all_ids(&app).await;

    let (status, body) = app
        .post(
            "/classify/estimate",
            json!({ "bookmark_ids": ids, "model": "gemini-2.5-flash-lite", "chunk_size": 2 }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);

    let cost = &body["cost"];
    assert_eq!(cost["items"], 5);
    assert_eq!(cost["chunks"], 3, "5 items in chunks of 2");
    assert!(cost["input_tokens_est"].as_u64().unwrap() > 0);
    assert!(cost["input_cost_usd"].as_f64().is_some(), "priced from the catalog");

    // can_run is exactly the absence of a blocking reason.
    assert_eq!(body["can_run"], body["blocked_reason"].is_null());
    assert_eq!(body["can_run"], true, "config.ini supplies key + catalog pricing");
}

#[tokio::test]
async fn estimate_blocks_when_the_model_has_no_known_price() {
    let app = Fixture::default().with_config(CONFIG_INI).build().await;
    let ids = all_ids(&app).await;

    let (status, body) = app
        .post(
            "/classify/estimate",
            json!({ "bookmark_ids": ids, "model": "no-such-model-9000" }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["can_run"], false);
    assert!(body["blocked_reason"]
        .as_str()
        .unwrap()
        .contains("no-such-model-9000"));
}

#[tokio::test]
async fn applying_ai_moves_creates_the_target_folders() {
    let app = app().await;
    let a = app.bookmark_id("A").await;
    let d = app.bookmark_id("D").await;

    let (status, body) = app
        .post(
            "/classify/ai-apply",
            json!({
                "moves": [
                    { "bookmark_id": a, "folder_path": "Archive/GitHub" },
                    { "bookmark_id": d, "folder_path": "Archive/GitHub" },
                    { "bookmark_id": "ghost-id", "folder_path": "Archive/GitHub" },
                    { "bookmark_id": a, "folder_path": "  " },
                ]
            }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["applied"], 2);
    assert_eq!(body["skipped"], 2, "unknown id and blank destination");
    assert_eq!(body["pruned"], 0);

    assert_eq!(app.folder_of("A").await.as_deref(), Some("Archive/GitHub"));
    assert_eq!(app.folder_of("D").await.as_deref(), Some("Archive/GitHub"));

    // Nested destinations are created once, not per move.
    let (_, tree) = app.get("/tree").await;
    let archives = tree["children"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c["title"] == "Archive")
        .count();
    assert_eq!(archives, 1);

    let (_, hist) = app.get("/edit/history").await;
    assert_eq!(hist["undo_count"], 1, "a bulk apply must be undoable");
}

#[tokio::test]
async fn applying_no_moves_changes_nothing() {
    let app = app().await;
    let (status, body) = app
        .post("/classify/ai-apply", json!({ "moves": [] }))
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["applied"], 0);
    assert_eq!(body["skipped"], 0);

    let (_, list) = app.get("/bookmarks").await;
    assert_eq!(list["dirty"], false, "an empty apply must not dirty the file");
    let (_, hist) = app.get("/edit/history").await;
    assert_eq!(hist["undo_count"], 0, "and must not push an undo entry");
}

#[tokio::test]
async fn applying_moves_can_prune_emptied_source_folders() {
    let app = app().await;
    let c = app.bookmark_id("C").await;

    let (status, body) = app
        .post(
            "/classify/ai-apply",
            json!({
                "moves": [{ "bookmark_id": c, "folder_path": "Personal" }],
                "prune_empty_source": true,
            }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["applied"], 1);
    assert_eq!(body["pruned"], 1, "Work/Nested is now empty");

    let (_, tree) = app.get("/tree").await;
    let work = &tree["children"][0];
    assert!(
        !work["children"]
            .as_array()
            .unwrap()
            .iter()
            .any(|c| c["title"] == "Nested"),
        "the emptied source folder is gone"
    );
}

// --- Settings --------------------------------------------------------------

#[tokio::test]
async fn ai_status_reports_the_configured_key_and_catalog_pricing() {
    let app = Fixture::default().with_config(CONFIG_INI).build().await;
    let (status, body) = app.get("/config/ai-status").await;
    assert_eq!(status, StatusCode::OK);

    assert_eq!(body["api_key_set"], true);
    assert_eq!(body["model"], "gemini-2.5-flash-lite");
    assert_eq!(body["pricing_set"], true);
    assert_eq!(body["pricing_source"], "catalog");
    assert!(body["input_cost_per_1m"].as_f64().unwrap() > 0.0);
    assert!(body["config_path"]
        .as_str()
        .is_some_and(|p| p.ends_with("config.ini")));
    // The key itself must never be echoed back.
    assert!(!serde_json::to_string(&body).unwrap().contains("test-key-123"));
}

#[tokio::test]
async fn ai_status_without_a_config_file_reports_nothing_configured() {
    let app = app().await;
    let (status, body) = app.get("/config/ai-status").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["config_path"], serde_json::Value::Null);
    assert_eq!(body["paid_key_set"], false);
    assert_eq!(body["free_tier"], serde_json::Value::Null);
}

#[tokio::test]
async fn setting_the_api_key_persists_it_to_config_ini() {
    let app = Fixture::default().with_config("[AI]\nmodel = gemini-2.5-flash\n").build().await;

    let (_, body) = app.get("/config/ai-status").await;
    let had_key_from_env = body["api_key_set"].as_bool().unwrap();

    let (status, body) = app
        .post("/config/api-key", json!({ "api_key": "  written-key  " }))
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], true);

    let ini = std::fs::read_to_string(app.dir.path().join("config.ini")).unwrap();
    assert!(ini.contains("written-key"), "trimmed key is stored");

    let (_, body) = app.get("/config/ai-status").await;
    assert_eq!(body["api_key_set"], true);
    if !had_key_from_env {
        assert_eq!(body["api_key_source"], "config");
    }

    // The paid key goes to its own option.
    let (_, body) = app
        .post("/config/api-key", json!({ "api_key": "paid-key", "paid": true }))
        .await;
    assert_eq!(body["ok"], true);
    let (_, body) = app.get("/config/ai-status").await;
    assert_eq!(body["paid_key_set"], true);
}

#[tokio::test]
async fn an_empty_api_key_is_rejected() {
    let app = Fixture::default().with_config(CONFIG_INI).build().await;
    let (status, body) = app.post("/config/api-key", json!({ "api_key": "   " })).await;
    assert_eq!(status, StatusCode::OK, "the handler reports failure in the body");
    assert_eq!(body["ok"], false);
    assert!(body["message"].as_str().unwrap().contains("空"));
}

#[tokio::test]
async fn setting_the_api_key_without_a_config_path_fails_cleanly() {
    let app = app().await;
    let (status, body) = app.post("/config/api-key", json!({ "api_key": "k" })).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], false);
    assert!(body["message"].as_str().unwrap().contains("config.ini"));
}

#[tokio::test]
async fn the_free_tier_flag_round_trips() {
    let app = Fixture::default().with_config(CONFIG_INI).build().await;

    let (status, body) = app.post("/config/ai-tier", json!({ "free_tier": true })).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], true);
    let (_, body) = app.get("/config/ai-status").await;
    assert_eq!(body["free_tier"], true);

    app.post("/config/ai-tier", json!({ "free_tier": false })).await;
    let (_, body) = app.get("/config/ai-status").await;
    assert_eq!(body["free_tier"], false);
}

#[tokio::test]
async fn pricing_is_saved_and_non_positive_values_are_rejected() {
    let app = Fixture::default().with_config(CONFIG_INI).build().await;

    let (status, body) = app
        .post(
            "/config/ai-pricing",
            json!({ "model": "custom-model", "input_cost_per_1m": 1.5, "output_cost_per_1m": 3.0 }),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], true);

    let (_, body) = app.get("/config/ai-status").await;
    assert_eq!(body["model"], "custom-model");
    assert_eq!(body["config_input_cost_per_1m"], 1.5);
    assert_eq!(body["config_output_cost_per_1m"], 3.0);
    assert_eq!(
        body["pricing_source"], "config",
        "custom-model is not in the catalog, so config.ini supplies the price"
    );

    for bad in [json!(0.0), json!(-1.0)] {
        let (_, body) = app
            .post(
                "/config/ai-pricing",
                json!({ "input_cost_per_1m": bad, "output_cost_per_1m": 1.0 }),
            )
            .await;
        assert_eq!(body["ok"], false, "{bad} must be rejected");
        assert!(body["message"].as_str().unwrap().contains("0より大きい"));
    }
}

#[tokio::test]
async fn models_returns_the_embedded_catalog_when_no_file_is_on_disk() {
    let app = Fixture::default().with_config(CONFIG_INI).build().await;
    let (status, body) = app.get("/config/models").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["current"], "gemini-2.5-flash-lite");
    assert_eq!(body["error"], serde_json::Value::Null);
    assert_eq!(body["from_file"], false);
    assert!(body["catalog"]["models"]
        .as_array()
        .unwrap()
        .iter()
        .any(|m| m["id"] == "gemini-2.5-flash-lite"));
}

#[tokio::test]
async fn models_prefers_a_models_json_next_to_config_ini() {
    let app = Fixture::default().with_config(CONFIG_INI).build().await;
    std::fs::write(
        app.dir.path().join("models.json"),
        r#"{"models":[{"id":"local-only","input_per_1m":1.0,"output_per_1m":2.0}]}"#,
    )
    .unwrap();

    let (_, body) = app.get("/config/models").await;
    assert_eq!(body["from_file"], true);
    assert_eq!(body["catalog"]["models"][0]["id"], "local-only");
}

#[tokio::test]
async fn a_broken_models_json_falls_back_to_the_embedded_catalog() {
    let app = Fixture::default().with_config(CONFIG_INI).build().await;
    std::fs::write(app.dir.path().join("models.json"), "{ not json").unwrap();

    let (status, body) = app.get("/config/models").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["from_file"], false);
    assert!(body["error"].as_str().unwrap().contains("models.json"));
    assert!(body["catalog"]["models"].as_array().unwrap().len() > 1);
}

#[tokio::test]
async fn proxy_check_reports_no_configuration_without_a_config_file() {
    let app = app().await;
    let (status, body) = app.get("/network/proxy-check").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["configured"], false);
    assert_eq!(body["reachable"], false);
    assert_eq!(body["url"], serde_json::Value::Null);
}
