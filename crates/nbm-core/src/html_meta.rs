//! Minimal HTML `<head>` scanning: title/description extraction and charset
//! sniffing.
//!
//! Lives here rather than in the HTTP layer because deriving a bookmark's title
//! and description from a page is domain work — the server only transports the
//! result. No DOM is built: the scan stops at `</head>`, which is all the
//! metadata we need and orders of magnitude cheaper than a full parse.

/// Case-insensitive `find`, restricted to ASCII needles, that returns a byte
/// index valid in the *original* (non-lowercased) haystack.
///
/// `str::to_lowercase()` can change the byte length of the string for some
/// Unicode characters (e.g. Turkish dotted İ, Kelvin sign K), so indices
/// found in a lowercased copy are not safe to slice the original string with
/// — they can land out of bounds or mid-character. Since our needles here
/// are always plain ASCII tag/attribute names, we instead scan the original
/// bytes and fold case only on the ASCII range; a match can only occur at a
/// true ASCII byte position, which is always a valid char boundary.
fn find_ascii_ci(haystack: &str, needle: &str) -> Option<usize> {
    let h = haystack.as_bytes();
    let n = needle.as_bytes();
    if n.is_empty() || n.len() > h.len() {
        return None;
    }
    (0..=h.len() - n.len()).find(|&i| {
        h[i..i + n.len()]
            .iter()
            .zip(n)
            .all(|(&a, &b)| a.eq_ignore_ascii_case(&b))
    })
}

fn rfind_ascii_ci(haystack: &str, needle: &str) -> Option<usize> {
    let h = haystack.as_bytes();
    let n = needle.as_bytes();
    if n.is_empty() || n.len() > h.len() {
        return None;
    }
    (0..=h.len() - n.len()).rev().find(|&i| {
        h[i..i + n.len()]
            .iter()
            .zip(n)
            .all(|(&a, &b)| a.eq_ignore_ascii_case(&b))
    })
}

/// Extract `<title>` and `<meta property="og:title">` / `<meta name="description">` from HTML.
/// Quick scan without a full DOM — we stop once we leave `<head>`.
pub fn extract_meta(html: &str) -> (String, String) {
    let head_end = find_ascii_ci(html, "</head>").unwrap_or(html.len());
    let head = &html[..head_end];

    let og_title = extract_meta_attr(head, "og:title");
    let title_tag = extract_title_tag(head);
    let title = og_title.or(title_tag).unwrap_or_default();

    let og_desc = extract_meta_attr(head, "og:description");
    let meta_desc = extract_meta_name(head, "description");
    let description = og_desc.or(meta_desc).unwrap_or_default();
    (title, description)
}

fn extract_title_tag(html: &str) -> Option<String> {
    let title_start = find_ascii_ci(html, "<title")?;
    let tag_close = html[title_start..].find('>')? + title_start + 1;
    let end = find_ascii_ci(&html[tag_close..], "</title>")?;
    Some(html[tag_close..tag_close + end].trim().to_string())
}

fn extract_meta_attr(html: &str, property: &str) -> Option<String> {
    let prop_str = format!("property=\"{}\"", property);
    let idx = find_ascii_ci(html, &prop_str)?;
    // Backtrack to `<meta` to get the full tag.
    let meta_start = rfind_ascii_ci(&html[..idx], "<meta")?;
    let tag_end = html[idx..].find('>')?;
    let tag = &html[meta_start..idx + tag_end + 1];
    extract_attr(tag, "content")
}

fn extract_meta_name(html: &str, name: &str) -> Option<String> {
    let needle = format!("name=\"{}\"", name);
    let idx = find_ascii_ci(html, &needle)?;
    let meta_start = rfind_ascii_ci(&html[..idx], "<meta")?;
    let tag_end = html[idx..].find('>')?;
    let tag = &html[meta_start..idx + tag_end + 1];
    extract_attr(tag, "content")
}

fn extract_attr(tag: &str, attr: &str) -> Option<String> {
    let search = format!("{}=\"", attr);
    let start = find_ascii_ci(tag, &search)? + search.len();
    let end = tag[start..].find('"')?;
    Some(html_decode(&tag[start..start + end]))
}

fn html_decode(s: &str) -> String {
    s.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&#39;", "'")
        .replace("&apos;", "'")
}


/// HTML の先頭付近から charset 宣言を抽出する。
pub fn extract_html_charset(sniff: &str) -> Option<String> {
    // <meta charset="utf-8">
    if let Some(pos) = sniff.find("charset=\"") {
        let rest = &sniff[pos + 9..];
        let end = rest.find('"')?;
        return Some(rest[..end].trim().to_string());
    }
    // <meta charset='utf-8'>
    if let Some(pos) = sniff.find("charset='") {
        let rest = &sniff[pos + 9..];
        let end = rest.find('\'')?;
        return Some(rest[..end].trim().to_string());
    }
    // <meta http-equiv="content-type" content="text/html; charset=shift_jis">
    if let Some(pos) = sniff.find("charset=") {
        let rest = &sniff[pos + 8..].trim_start_matches('"');
        let end = rest.find(['"', '\'', ';', '>'])?;
        return Some(rest[..end].trim().to_string());
    }
    None
}

/// バイト列を指定 charset でデコードする。
/// Shift_JIS / EUC-JP は encoding_rs で変換し、それ以外は UTF-8 ロスレスフォールバック。
pub fn decode_bytes(bytes: &[u8], charset: &str) -> String {
    let label = charset.to_lowercase();
    let label = label.trim();
    // encoding_rs が対応している名前に正規化
    let enc = encoding_rs::Encoding::for_label(label.as_bytes());
    if let Some(enc) = enc {
        let (text, _, _) = enc.decode(bytes);
        return text.into_owned();
    }
    String::from_utf8_lossy(bytes).into_owned()
}

#[cfg(test)]
mod meta_extraction_tests {
    use super::*;

    /// `İ` (Turkish dotted capital I, U+0130) lowercases to a 2-character,
    /// 3-byte sequence ("i̇"), one byte longer than the 2-byte original.
    /// A naive `html.to_lowercase().find(...)` index used to slice the
    /// original `html` would therefore land out of bounds / off a char
    /// boundary once enough of these appear before the target tag.
    #[test]
    fn extract_meta_handles_byte_length_changing_lowercase() {
        let html = "<html><head><title>İstanbul</title>\
             <meta property=\"og:title\" content=\"İstanbul Guide\">\
             <meta name=\"description\" content=\"İ İ İ İ İ İ İ İ İ İ travel tips\">\
             </head><body></body></html>".to_string();
        let (title, description) = extract_meta(&html);
        assert_eq!(title, "İstanbul Guide");
        assert_eq!(description, "İ İ İ İ İ İ İ İ İ İ travel tips");
    }

    #[test]
    fn extract_meta_falls_back_to_title_tag() {
        let html = "<html><head><title>Plain Title</title></head><body></body></html>";
        let (title, _description) = extract_meta(html);
        assert_eq!(title, "Plain Title");
    }

    #[test]
    fn extract_meta_no_head_close_tag_does_not_panic() {
        let html = "<html><head><title>No closing head tag</title>";
        let (title, _description) = extract_meta(html);
        assert_eq!(title, "No closing head tag");
    }
}
