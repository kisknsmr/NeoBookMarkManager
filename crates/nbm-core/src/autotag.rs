//! Rule/heuristic based auto-tagging.
//!
//! Strategy:
//!   1. Combine URL, title, description, and fetched_title into one text blob.
//!   2. Detect language by character type (CJK → Japanese/Chinese, else English).
//!   3. Tokenize by splitting on whitespace and punctuation (CJK: per-character).
//!   4. Filter tokens through a stopword list and minimum-length check.
//!   5. Apply the domain/keyword rule overlay on top.
//!   6. Return deduplicated tag list, capped at MAX_TAGS.

use std::collections::{HashMap, HashSet};

use once_cell::sync::Lazy;

const MAX_TAGS: usize = 20;
const MIN_TOKEN_LEN: usize = 2; // chars

// ---------------------------------------------------------------------------
// Static rule tables (domain / keyword overlays)
// ---------------------------------------------------------------------------

static DOMAIN_TAGS: Lazy<HashMap<&'static str, &'static [&'static str]>> = Lazy::new(|| {
    let mut m: HashMap<&str, &[&str]> = HashMap::new();
    m.insert("github.com",         &["Dev"]);
    m.insert("gitlab.com",         &["Dev"]);
    m.insert("bitbucket.org",      &["Dev"]);
    m.insert("stackoverflow.com",  &["Dev", "QA"]);
    m.insert("youtube.com",        &["Video"]);
    m.insert("youtu.be",           &["Video"]);
    m.insert("docs.google.com",    &["Docs"]);
    m.insert("drive.google.com",   &["Docs"]);
    m.insert("qiita.com",          &["Dev"]);
    m.insert("zenn.dev",           &["Dev"]);
    m.insert("medium.com",         &["Blog"]);
    m.insert("note.com",           &["Blog"]);
    m.insert("news.ycombinator.com", &["News"]);
    m.insert("reddit.com",         &["Community"]);
    m.insert("twitter.com",        &["Social"]);
    m.insert("x.com",              &["Social"]);
    m.insert("amazon.co.jp",       &["Shopping"]);
    m.insert("amazon.com",         &["Shopping"]);
    m.insert("support.google.com", &["Support"]);
    m.insert("arxiv.org",          &["Paper"]);
    m.insert("scholar.google.com", &["Paper"]);
    m
});

static KEYWORD_RULES: &[(&str, &str)] = &[
    ("login",   "Login"),
    ("signin",  "Login"),
    ("sign-in", "Login"),
    ("signup",  "Signup"),
    ("register","Signup"),
    (".pdf",    "PDF"),
    ("/pdf",    "PDF"),
    (".ppt",    "Slides"),
    (".pptx",   "Slides"),
    (".xls",    "Excel"),
    (".xlsx",   "Excel"),
    (".zip",    "Download"),
    (".tar",    "Download"),
    (".gz",     "Download"),
    ("/api",    "API"),
    ("docs",    "Docs"),
    ("blog",    "Blog"),
    ("news",    "News"),
    ("wiki",    "Wiki"),
    ("pricing", "Pricing"),
    ("support", "Support"),
    ("tutorial","Tutorial"),
];

static STOPWORDS_EN: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    [
        "the","and","or","of","to","in","for","with","on","at","by","from","a","an",
        "is","are","was","were","be","been","being","have","has","had","do","does","did",
        "will","would","could","should","may","might","shall","can",
        "this","that","these","those","it","its","we","our","you","your","he","she","they",
        "home","index","top","page","site","web","www","http","https","com","net","org",
        "new","about","more","all","get","see","use","used","using","make","made",
    ]
    .iter().copied().collect()
});

static STOPWORDS_JP: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    [
        "の","に","は","を","た","が","で","て","と","し","れ","さ","ある","いる","も",
        "する","から","な","こと","として","い","や","れる","など","なっ","ない","この",
        "ため","その","あっ","よう","また","もの","という","あり","まで","られ","なる",
        "へ","か","だ","これ","とき","に","は","が","を","も","で","や","など",
        "公式","ホーム","トップ","ページ","サイト","記事","一覧","まとめ","検索","無料",
        "について","における","おける","ください","お知らせ","情報","サービス",
    ]
    .iter().copied().collect()
});

static STOPWORDS_ZH: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    [
        "的","了","和","是","在","我","有","这","你","他","她","它","们","个","上",
        "为","以","从","到","被","与","及","或","但","也","都","就","而","对","于",
        "中","该","其","此","等","也","又","都","则",
    ]
    .iter().copied().collect()
});

// ---------------------------------------------------------------------------
// Input struct
// ---------------------------------------------------------------------------

/// All textual information available for a bookmark.
pub struct BookmarkText<'a> {
    pub url: &'a str,
    pub title: &'a str,
    pub description: &'a str,
    pub fetched_title: Option<&'a str>,
}

// ---------------------------------------------------------------------------
// Language detection
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq)]
enum Lang {
    Japanese,
    Chinese,
    English,
}

fn detect_lang(text: &str) -> Lang {
    let mut jp = 0usize;
    let mut zh_only = 0usize;
    let mut total = 0usize;
    for c in text.chars() {
        let cp = c as u32;
        // Hiragana / Katakana → definitely Japanese
        if (0x3040..=0x30FF).contains(&cp) || (0xFF65..=0xFF9F).contains(&cp) {
            jp += 1;
        }
        // CJK Unified ideographs
        if (0x4E00..=0x9FFF).contains(&cp) {
            zh_only += 1;
        }
        if !c.is_ascii_whitespace() {
            total += 1;
        }
    }
    if total == 0 { return Lang::English; }
    if jp > 0 { return Lang::Japanese; }
    // If more than 20% of chars are CJK and no kana → Chinese
    if zh_only * 5 > total { return Lang::Chinese; }
    Lang::English
}

// ---------------------------------------------------------------------------
// Tokenization
// ---------------------------------------------------------------------------

/// Character class for Japanese/Chinese segmentation.
#[derive(PartialEq, Clone, Copy)]
enum CharClass {
    Kanji,    // CJK ideographs
    Katakana, // カタカナ（外来語）
    Hiragana, // ひらがな（助詞・活用 → ノイズ源）
    Other,    // ASCII・記号・空白など → 区切り
}

fn classify_char(ch: char) -> CharClass {
    let cp = ch as u32;
    if (0x3040..=0x309F).contains(&cp) {
        CharClass::Hiragana
    } else if (0x30A0..=0x30FF).contains(&cp) || (0xFF65..=0xFF9F).contains(&cp) {
        CharClass::Katakana
    } else if (0x4E00..=0x9FFF).contains(&cp)
        || (0x3400..=0x4DBF).contains(&cp)
        || (0xF900..=0xFAFF).contains(&cp)
        || (0x20000..=0x2A6DF).contains(&cp)
    {
        CharClass::Kanji
    } else {
        CharClass::Other
    }
}

/// CJK segmentation by character-class boundaries.
///
/// Japanese tends to alternate 漢字語 + ひらがな助詞 + カタカナ外来語, so cutting
/// at every change of character class recovers word-like chunks without a
/// dictionary. We keep kanji and katakana runs as whole tokens (the common case
/// where a script boundary == a word boundary) and drop hiragana runs, which are
/// almost always grammatical glue. This avoids the n-gram garbage
/// ("議事"/"事録" from 議事録) the previous bigram approach produced.
fn tokenize_cjk(text: &str, stopwords: &HashSet<&'static str>) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let mut run: Vec<char> = Vec::new();
    let mut run_class = CharClass::Other;

    let flush = |class: CharClass, run: &mut Vec<char>, out: &mut Vec<String>| {
        if run.len() >= MIN_TOKEN_LEN {
            match class {
                // Whole kanji / katakana run is the candidate word.
                CharClass::Kanji | CharClass::Katakana => {
                    let s: String = run.iter().collect();
                    if !stopwords.contains(s.as_str()) {
                        out.push(s);
                    }
                    // For long kanji runs (≥4) a single chunk may be a compound
                    // of two words; add a light bigram fallback to keep recall.
                    if class == CharClass::Kanji && run.len() >= 4 {
                        for w in run.windows(2) {
                            let s: String = w.iter().collect();
                            if !stopwords.contains(s.as_str()) {
                                out.push(s);
                            }
                        }
                    }
                }
                // Hiragana / other: drop (grammatical glue or delimiters).
                _ => {}
            }
        }
        run.clear();
    };

    for ch in text.chars() {
        let class = classify_char(ch);
        if class != run_class {
            flush(run_class, &mut run, &mut out);
            run_class = class;
        }
        if class != CharClass::Other {
            run.push(ch);
        }
    }
    flush(run_class, &mut run, &mut out);
    out
}

fn tokenize_japanese(text: &str) -> Vec<String> {
    tokenize_cjk(text, &STOPWORDS_JP)
}

fn tokenize_chinese(text: &str) -> Vec<String> {
    tokenize_cjk(text, &STOPWORDS_ZH)
}

fn tokenize_english(text: &str) -> Vec<String> {
    text.split(|c: char| c.is_ascii_whitespace() || ".,;:!?\"'()[]{}<>|/\\-_".contains(c))
        .filter(|t| !t.is_empty())
        .map(|t| t.trim_matches(|c: char| !c.is_alphanumeric()).to_string())
        .filter(|t| {
            t.len() >= MIN_TOKEN_LEN
                && !STOPWORDS_EN.contains(t.to_lowercase().as_str())
                && !t.chars().all(|c| c.is_ascii_digit())
        })
        .collect()
}

fn tokenize_text(text: &str) -> Vec<String> {
    match detect_lang(text) {
        Lang::Japanese => tokenize_japanese(text),
        Lang::Chinese  => tokenize_chinese(text),
        Lang::English  => tokenize_english(text),
    }
}

// ---------------------------------------------------------------------------
// Domain helpers
// ---------------------------------------------------------------------------

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
// Main entry point
// ---------------------------------------------------------------------------

/// Generate tags for a bookmark from all available text fields.
pub fn generate_tags(bm: &BookmarkText<'_>) -> Vec<String> {
    let mut tags: Vec<String> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();

    let push = |tags: &mut Vec<String>, seen: &mut HashSet<String>, s: String| {
        let s = s.trim().to_string();
        if s.is_empty() || s.chars().count() > 40 { return; }
        if seen.insert(s.to_lowercase()) {
            tags.push(s);
        }
    };

    // 1. Domain / keyword rule overlay (always applied)
    let domain = extract_domain(bm.url);
    if let Some(dt) = DOMAIN_TAGS.get(domain.as_str()) {
        for &t in dt.iter() { push(&mut tags, &mut seen, t.to_string()); }
    }
    let url_l = bm.url.to_lowercase();
    for &(key, tag) in KEYWORD_RULES {
        if url_l.contains(key) { push(&mut tags, &mut seen, tag.to_string()); }
    }

    // 2. Morphological analysis of title fields
    let title_text = [
        bm.title,
        bm.fetched_title.unwrap_or(""),
    ].join(" ");

    if !title_text.trim().is_empty() {
        for tok in tokenize_text(title_text.trim()).into_iter().take(12) {
            push(&mut tags, &mut seen, tok);
        }
    }

    // 3. Description field
    if !bm.description.is_empty() {
        for tok in tokenize_text(bm.description).into_iter().take(10) {
            push(&mut tags, &mut seen, tok);
        }
    }

    // 4. URL path tokens as last resort (English only, low priority)
    if tags.len() < 5 {
        let path = bm.url.split('?').next().unwrap_or(bm.url);
        for tok in tokenize_english(path).into_iter().take(6) {
            push(&mut tags, &mut seen, tok);
        }
    }

    tags.truncate(MAX_TAGS);
    tags
}

// ---------------------------------------------------------------------------
// Legacy shim — kept so nbm-server compiles without changes
// ---------------------------------------------------------------------------

/// Tier-1 tags (URL only). Kept for backward compatibility.
pub fn tier1_tags(url: &str) -> Vec<String> {
    generate_tags(&BookmarkText { url, title: "", description: "", fetched_title: None })
}

/// Tier-2 scraping is removed. Returns empty vec.
pub fn tier2_scrape_tags_blocking(_url: &str) -> Vec<String> {
    Vec::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn jp_segments_on_script_boundary() {
        // 「機械学習をクラウドで構築」→ 漢字語・カタカナ語が取れ、
        // ひらがな助詞（を/で）は捨てられる。
        let toks = tokenize_japanese("機械学習をクラウドで構築");
        assert!(toks.iter().any(|t| t == "機械学習"), "{toks:?}");
        assert!(toks.iter().any(|t| t == "クラウド"), "{toks:?}");
        assert!(toks.iter().any(|t| t == "構築"), "{toks:?}");
        assert!(!toks.iter().any(|t| t == "を" || t == "で"), "{toks:?}");
    }

    #[test]
    fn jp_short_kanji_word_is_single_token() {
        // 「議事録」は3字漢字 → 丸ごと1語。長さ4未満なのでbigram補助は出ない。
        let toks = tokenize_japanese("議事録");
        assert!(toks.contains(&"議事録".to_string()), "{toks:?}");
        assert!(!toks.contains(&"議事".to_string()), "{toks:?}");
        assert!(!toks.contains(&"事録".to_string()), "{toks:?}");
    }

    #[test]
    fn jp_katakana_kept_whole() {
        let toks = tokenize_japanese("プロジェクト管理ツール");
        assert!(toks.iter().any(|t| t == "プロジェクト"), "{toks:?}");
        assert!(toks.iter().any(|t| t == "ツール"), "{toks:?}");
        assert!(toks.iter().any(|t| t == "管理"), "{toks:?}");
    }

    #[test]
    fn en_tokenizes_words() {
        let toks = tokenize_english("Machine Learning on AWS Cloud");
        assert!(toks.contains(&"Machine".to_string()), "{toks:?}");
        assert!(toks.contains(&"Learning".to_string()), "{toks:?}");
        assert!(toks.contains(&"AWS".to_string()), "{toks:?}");
    }

    #[test]
    fn generate_uses_all_fields() {
        let bm = BookmarkText {
            url: "https://example.com/docs",
            title: "プロジェクト計画",
            description: "クラウド基盤の設計メモ",
            fetched_title: None,
        };
        let tags = generate_tags(&bm);
        assert!(tags.iter().any(|t| t == "プロジェクト"), "{tags:?}");
        assert!(tags.iter().any(|t| t == "クラウド"), "{tags:?}");
    }
}
