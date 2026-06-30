//! Netscape Bookmark HTML 1.0 parser / serializer.
//!
//! Mirrors the behavior of `OriginalPythonCodes/core/ModelBookmark.py`:
//! - `<H3 ADD_DATE LAST_MODIFIED>folder name</H3>` opens a folder.
//! - `<DL>` / `</DL>` push/pop the folder stack.
//! - `<A HREF ADD_DATE LAST_MODIFIED ICON BOOKMARK_ID>title</A>` creates a bookmark.

use html5ever::tendril::StrTendril;
use html5ever::tokenizer::{
    BufferQueue, Tag, TagKind, Token, TokenSink, TokenSinkResult, Tokenizer, TokenizerOpts,
};

use crate::model::{Node, NodeKind};

const HEADER: &str = "<!DOCTYPE NETSCAPE-Bookmark-file-1>\n\
<META HTTP-EQUIV=\"Content-Type\" CONTENT=\"text/html; charset=UTF-8\">\n\
<TITLE>Bookmarks</TITLE>\n\
<H1>Bookmarks</H1>\n\
<DL><p>\n";
const FOOTER: &str = "</DL><p>\n";

#[derive(Debug, thiserror::Error)]
pub enum NetscapeError {
    #[error("tokenizer error: {0}")]
    Tokenizer(String),
}

/// Each frame on the stack is a folder under construction.
struct Frame {
    node: Node,
}

struct Sink {
    /// Stack of folders being built. Bottom is the synthetic root.
    stack: Vec<Frame>,
    pending_folder: Option<Node>,
    pending_link: Option<Node>,
    capture: Capture,
    buffer: String,
}

#[derive(Copy, Clone, PartialEq, Eq)]
enum Capture {
    None,
    Folder,
    Link,
    /// Capturing the text of a <DD> description that follows a bookmark <A>.
    Dd,
}

impl Sink {
    fn new() -> Self {
        Self {
            stack: vec![Frame {
                node: Node::new_root(),
            }],
            pending_folder: None,
            pending_link: None,
            capture: Capture::None,
            buffer: String::new(),
        }
    }

    /// Push a bookmark that was held open to absorb a trailing <DD> description.
    /// `dd_text` is the description captured since </A> (empty if none).
    fn flush_pending_link(&mut self, dd_text: &str) {
        if let Some(mut link) = self.pending_link.take() {
            let d = dd_text.trim();
            if !d.is_empty() {
                link.description = d.to_string();
            }
            self.stack.last_mut().unwrap().node.children.push(link);
        }
    }

    fn finish(mut self) -> Node {
        // A bookmark held open for a possible <DD> at EOF still needs flushing.
        if self.pending_link.is_some() {
            let dd = std::mem::take(&mut self.buffer);
            self.flush_pending_link(&dd);
        }
        // Collapse any unclosed folders back into their parents.
        while self.stack.len() > 1 {
            let child = self.stack.pop().unwrap().node;
            self.stack.last_mut().unwrap().node.children.push(child);
        }
        self.stack.pop().unwrap().node
    }
}

fn attr<'a>(tag: &'a Tag, name: &str) -> Option<&'a str> {
    tag.attrs
        .iter()
        .find(|a| a.name.local.eq_str_ignore_ascii_case(name))
        .map(|a| a.value.as_ref())
}

impl TokenSink for Sink {
    type Handle = ();

    fn process_token(&mut self, token: Token, _line: u64) -> TokenSinkResult<()> {
        match token {
            Token::TagToken(tag) => {
                let name = tag.name.as_ref().to_ascii_lowercase();
                match (tag.kind, name.as_str()) {
                    (TagKind::StartTag, "h3") => {
                        // A new folder ends any pending bookmark's <DD> window.
                        if self.pending_link.is_some() {
                            let dd = std::mem::take(&mut self.buffer);
                            self.flush_pending_link(&dd);
                        }
                        let mut n = Node::new_folder("");
                        n.add_date = attr(&tag, "add_date").unwrap_or("").to_string();
                        n.last_modified = attr(&tag, "last_modified").unwrap_or("").to_string();
                        self.pending_folder = Some(n);
                        self.capture = Capture::Folder;
                        self.buffer.clear();
                    }
                    (TagKind::StartTag, "a") => {
                        // A new bookmark ends the previous one's <DD> window.
                        if self.pending_link.is_some() {
                            let dd = std::mem::take(&mut self.buffer);
                            self.flush_pending_link(&dd);
                        }
                        let mut n = Node::new_bookmark("", attr(&tag, "href").unwrap_or(""));
                        n.add_date = attr(&tag, "add_date").unwrap_or("").to_string();
                        n.last_modified = attr(&tag, "last_modified").unwrap_or("").to_string();
                        n.icon = attr(&tag, "icon").unwrap_or("").to_string();
                        n.bookmark_id = attr(&tag, "bookmark_id")
                            .or_else(|| attr(&tag, "data-bookmark-id"))
                            .unwrap_or("")
                            .to_string();
                        self.pending_link = Some(n);
                        self.capture = Capture::Link;
                        self.buffer.clear();
                    }
                    (TagKind::EndTag, "h3") => {
                        let text = self.buffer.trim().to_string();
                        self.buffer.clear();
                        if let Some(mut folder) = self.pending_folder.take() {
                            folder.title = if text.is_empty() {
                                "Untitled".into()
                            } else {
                                text
                            };
                            // The folder becomes the new top of the stack; its eventual
                            // children will be appended here, then the whole frame gets
                            // moved into the parent's children when </DL> fires.
                            self.stack.push(Frame { node: folder });
                        }
                        self.capture = Capture::None;
                    }
                    (TagKind::EndTag, "a") => {
                        let text = self.buffer.trim().to_string();
                        self.buffer.clear();
                        // Keep the link pending so a following <DD> can attach a
                        // description. It is flushed on the next DT/DD/H3/</DL> or EOF.
                        if let Some(link) = self.pending_link.as_mut() {
                            link.title = text;
                        }
                        // Enter Dd mode to capture any <DD> text that follows.
                        self.capture = Capture::Dd;
                    }
                    (TagKind::StartTag, "dd") => {
                        // <DD> has no end tag; its text runs until the next element.
                        // Start fresh capture for the description body.
                        self.buffer.clear();
                        if self.pending_link.is_some() {
                            self.capture = Capture::Dd;
                        }
                    }
                    (TagKind::EndTag, "dl") => {
                        // Closing a folder ends any pending bookmark's <DD> window.
                        if self.pending_link.is_some() {
                            let dd = std::mem::take(&mut self.buffer);
                            self.flush_pending_link(&dd);
                        }
                        // The first <DL> after <H1> wraps the root, so we only pop when
                        // there's an actual nested folder to close.
                        if self.stack.len() > 1 {
                            let finished = self.stack.pop().unwrap().node;
                            self.stack
                                .last_mut()
                                .unwrap()
                                .node
                                .children
                                .push(finished);
                        }
                    }
                    _ => {}
                }
            }
            Token::CharacterTokens(text) => {
                if matches!(self.capture, Capture::Folder | Capture::Link | Capture::Dd) {
                    self.buffer.push_str(&text);
                }
            }
            _ => {}
        }
        TokenSinkResult::Continue
    }
}

pub fn parse(input: &str) -> Result<Node, NetscapeError> {
    let sink = Sink::new();
    let mut tok = Tokenizer::new(sink, TokenizerOpts::default());
    let mut input_buffer = BufferQueue::default();
    input_buffer.push_back(StrTendril::from(input));
    let _ = tok.feed(&mut input_buffer);
    tok.end();
    Ok(tok.sink.finish())
}

pub fn serialize(root: &Node) -> String {
    let mut out = String::with_capacity(4096);
    out.push_str(HEADER);
    for child in &root.children {
        write_node(&mut out, child, 1);
    }
    out.push_str(FOOTER);
    out
}

fn write_node(out: &mut String, node: &Node, indent: usize) {
    let ind = "    ".repeat(indent);
    match node.kind {
        NodeKind::Folder => {
            out.push_str(&format!(
                "{ind}<DT><H3 ADD_DATE=\"{}\" LAST_MODIFIED=\"{}\">{}</H3>\n",
                escape(&node.add_date),
                escape(&node.last_modified),
                escape(&node.title),
            ));
            out.push_str(&format!("{ind}<DL><p>\n"));
            for child in &node.children {
                write_node(out, child, indent + 1);
            }
            out.push_str(&format!("{ind}</DL><p>\n"));
        }
        NodeKind::Bookmark => {
            let icon_attr = if node.icon.is_empty() {
                String::new()
            } else {
                format!(" ICON=\"{}\"", escape(&node.icon))
            };
            let bid_attr = if node.bookmark_id.is_empty() {
                String::new()
            } else {
                format!(" BOOKMARK_ID=\"{}\"", escape(&node.bookmark_id))
            };
            out.push_str(&format!(
                "{ind}<DT><A HREF=\"{}\" ADD_DATE=\"{}\" LAST_MODIFIED=\"{}\"{}{}>{}</A>\n",
                escape(&node.url),
                escape(&node.add_date),
                escape(&node.last_modified),
                icon_attr,
                bid_attr,
                escape(&node.title),
            ));
            // Description persists as a Netscape <DD> line (standard, browser-compatible).
            if !node.description.is_empty() {
                out.push_str(&format!("{ind}<DD>{}\n", escape(&node.description)));
            }
        }
    }
}

fn escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#x27;"),
            _ => out.push(c),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::Node;

    fn find_bm<'a>(node: &'a Node, title: &str) -> Option<&'a Node> {
        if !node.is_folder() && node.title == title {
            return Some(node);
        }
        for c in &node.children {
            if let Some(found) = find_bm(c, title) {
                return Some(found);
            }
        }
        None
    }

    #[test]
    fn description_round_trips_via_dd() {
        let mut root = Node::new_root();
        let mut folder = Node::new_folder("Work");
        let mut bm = Node::new_bookmark("Rust", "https://rust-lang.org/");
        bm.description = "Systems language & safe concurrency".into();
        folder.children.push(bm);
        // A second bookmark with no description must not absorb the previous DD.
        folder.children.push(Node::new_bookmark("Bare", "https://example.com/"));
        root.children.push(folder);

        let html = serialize(&root);
        assert!(html.contains("<DD>Systems language &amp; safe concurrency"), "{html}");

        let parsed = parse(&html).unwrap();
        let rust = find_bm(&parsed, "Rust").expect("Rust bookmark");
        assert_eq!(rust.description, "Systems language & safe concurrency");
        let bare = find_bm(&parsed, "Bare").expect("Bare bookmark");
        assert_eq!(bare.description, "", "description must not leak to the next bookmark");
    }

    #[test]
    fn empty_description_emits_no_dd() {
        let mut root = Node::new_root();
        root.children.push(Node::new_bookmark("X", "https://x.test/"));
        let html = serialize(&root);
        assert!(!html.contains("<DD>"), "{html}");
    }

    #[test]
    fn title_and_url_still_round_trip() {
        let mut root = Node::new_root();
        let mut bm = Node::new_bookmark("My Title", "https://t.test/path");
        bm.description = "desc".into();
        root.children.push(bm);
        let parsed = parse(&serialize(&root)).unwrap();
        let got = find_bm(&parsed, "My Title").unwrap();
        assert_eq!(got.url, "https://t.test/path");
        assert_eq!(got.description, "desc");
    }
}
