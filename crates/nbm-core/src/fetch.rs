//! Outbound HTTP used by the bookmark maintenance commands: fetching page
//! metadata and checking whether a link is still alive.

use crate::html_meta::{decode_bytes, extract_html_charset, extract_meta};

pub fn build_http_client(proxy_url: Option<&str>) -> reqwest::Client {
    let mut builder = reqwest::Client::builder()
        .user_agent("Mozilla/5.0 (NeoBookMarkManager)")
        .timeout(std::time::Duration::from_secs(5))
        .danger_accept_invalid_certs(false);
    if let Some(url) = proxy_url {
        if let Ok(proxy) = reqwest::Proxy::all(url) {
            builder = builder.proxy(proxy);
        }
    }
    builder.build().unwrap_or_default()
}

pub async fn fetch_url_meta(client: &reqwest::Client, url: &str) -> Result<(String, String), String> {
    let mut last_err = String::new();
    for attempt in 0..3u32 {
        match client.get(url).send().await {
            Ok(resp) => {
                let status = resp.status().as_u16();
                if status == 404 {
                    return Err("404 Not Found".into());
                }
                if !resp.status().is_success() {
                    last_err = format!("HTTP {status}");
                    if attempt < 2 {
                        tokio::time::sleep(std::time::Duration::from_millis(500 * (1 << attempt))).await;
                    }
                    continue;
                }
                // Content-Type ヘッダの charset を取得
                let ct_charset = resp.headers()
                    .get(reqwest::header::CONTENT_TYPE)
                    .and_then(|v| v.to_str().ok())
                    .and_then(|s| {
                        let lower = s.to_lowercase();
                        let pos = lower.find("charset=")?;
                        Some(lower[pos + 8..].trim_matches('"').trim().to_string())
                    });

                let bytes = resp.bytes().await.map_err(|e| e.to_string())?;

                // HTML の <meta charset> / <meta http-equiv content-type> を確認
                // まず UTF-8 としてデコードして charset 宣言を探す
                let sniff = String::from_utf8_lossy(&bytes[..bytes.len().min(2048)]).to_lowercase();
                let html_charset = extract_html_charset(&sniff);
                let charset = ct_charset.or(html_charset).unwrap_or_else(|| "utf-8".into());

                let text = decode_bytes(&bytes, &charset);
                let (title, desc) = extract_meta(&text);
                return Ok((title, desc));
            }
            Err(e) => {
                last_err = e.to_string();
                if attempt < 2 {
                    tokio::time::sleep(std::time::Duration::from_millis(500 * (1 << attempt))).await;
                }
            }
        }
    }
    Err(last_err)
}

pub async fn check_url(client: &reqwest::Client, url: &str, timeout_secs: u64)
    -> (&'static str, String)
{
    let timeout = std::time::Duration::from_secs(timeout_secs);
    // Try HEAD first (lightweight), fall back to GET on method-not-allowed.
    let result = client
        .head(url)
        .timeout(timeout)
        .send()
        .await;
    let status = match result {
        Err(e) if e.is_timeout() => return ("timeout", "タイムアウト".into()),
        Err(e) => {
            // Connection refused / DNS failure → dead
            return ("dead", e.to_string());
        }
        Ok(r) => r.status().as_u16(),
    };
    if status == 405 || status == 501 {
        // Server doesn't support HEAD — retry with GET (no body read)
        let g = client.get(url).timeout(timeout).send().await;
        match g {
            Err(e) if e.is_timeout() => ("timeout", "タイムアウト".into()),
            Err(e) => ("dead", e.to_string()),
            Ok(r) => {
                let s = r.status().as_u16();
                if s < 400 { ("ok", format!("HTTP {s}")) }
                else { ("dead", format!("HTTP {s}")) }
            }
        }
    } else if status < 400 {
        ("ok", format!("HTTP {status}"))
    } else {
        ("dead", format!("HTTP {status}"))
    }
}
