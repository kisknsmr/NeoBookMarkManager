//! Tree mutations on the in-memory `Node` model.
//!
//! Mirrors `OriginalPythonCodes/services/ServiceBookmark.py`. Folders are
//! addressed by their `/`-joined path (e.g. `"ブックマーク バー/Subfolder"`),
//! bookmarks by their `bookmark_id`. Path segments containing `/` are not
//! supported (matches the PySide6 invariant — folders sanitize on creation).

use std::time::{SystemTime, UNIX_EPOCH};

use crate::model::{Node, NodeKind};

#[derive(Debug, thiserror::Error)]
pub enum TreeError {
    #[error("folder not found: {0}")]
    FolderNotFound(String),
    #[error("bookmark not found: {0}")]
    BookmarkNotFound(String),
    #[error("not a folder: {0}")]
    NotFolder(String),
    #[error("invalid: {0}")]
    Invalid(String),
}

/// Find a folder node by its `/`-separated path. Empty path returns the root.
pub fn find_folder<'a>(root: &'a Node, path: &str) -> Option<&'a Node> {
    if path.is_empty() {
        return Some(root);
    }
    let mut cur = root;
    for part in path.split('/') {
        if part.is_empty() {
            continue;
        }
        let next = cur
            .children
            .iter()
            .find(|c| c.is_folder() && c.title == part)?;
        cur = next;
    }
    Some(cur)
}

pub fn find_folder_mut<'a>(root: &'a mut Node, path: &str) -> Option<&'a mut Node> {
    if path.is_empty() {
        return Some(root);
    }
    let mut cur = root;
    for part in path.split('/') {
        if part.is_empty() {
            continue;
        }
        let idx = cur
            .children
            .iter()
            .position(|c| c.is_folder() && c.title == part)?;
        cur = &mut cur.children[idx];
    }
    Some(cur)
}

/// Recursively search the tree for a bookmark with `bookmark_id`. Returns
/// `(parent_path, index_within_parent)` if found.
pub fn locate_bookmark(root: &Node, bookmark_id: &str) -> Option<(String, usize)> {
    fn walk(node: &Node, path: &str, target: &str) -> Option<(String, usize)> {
        for (i, child) in node.children.iter().enumerate() {
            match child.kind {
                NodeKind::Bookmark => {
                    if child.bookmark_id == target {
                        return Some((path.to_string(), i));
                    }
                }
                NodeKind::Folder => {
                    let next = if path.is_empty() {
                        child.title.clone()
                    } else {
                        format!("{path}/{}", child.title)
                    };
                    if let Some(hit) = walk(child, &next, target) {
                        return Some(hit);
                    }
                }
            }
        }
        None
    }
    walk(root, "", bookmark_id)
}

/// Visit every bookmark in the tree.
pub fn iter_bookmarks(node: &Node) -> Vec<&Node> {
    let mut out = Vec::new();
    walk_bookmarks(node, &mut out);
    out
}

fn walk_bookmarks<'a>(node: &'a Node, out: &mut Vec<&'a Node>) {
    for child in &node.children {
        match child.kind {
            NodeKind::Bookmark => out.push(child),
            NodeKind::Folder => walk_bookmarks(child, out),
        }
    }
}

/// Assign UUIDs to bookmarks missing a `bookmark_id`. Returns the count assigned.
/// Mirrors `BookmarkService.ensure_bookmark_ids`.
/// For tests: produce a deterministic pseudo-id from a string seed.
pub fn ensure_bookmark_ids_return(seed: &str) -> String {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    let mut h = DefaultHasher::new();
    seed.hash(&mut h);
    format!("{:016x}{:016x}", h.finish(), h.finish().wrapping_add(1))
}

/// Assign a deterministic id to every bookmark missing a `bookmark_id`, derived
/// from its folder path + URL + an occurrence index for duplicate URLs in the
/// same folder. Nodes that already carry a `BOOKMARK_ID` (e.g. files we saved
/// before) keep it untouched. Determinism lets DB metadata/tags reattach after
/// reopening a browser-exported file that has no BOOKMARK_ID attributes.
pub fn ensure_bookmark_ids(node: &mut Node) -> usize {
    use std::collections::HashMap;
    let mut count = 0;
    // (folder_path, url) -> how many times we've already seen this pair.
    let mut seen: HashMap<(String, String), usize> = HashMap::new();
    fn walk(
        n: &mut Node,
        path: &str,
        seen: &mut HashMap<(String, String), usize>,
        count: &mut usize,
    ) {
        for c in n.children.iter_mut() {
            match c.kind {
                NodeKind::Bookmark => {
                    if c.bookmark_id.is_empty() {
                        let key = (path.to_string(), c.url.clone());
                        let nth = seen.entry(key).or_insert(0);
                        let seed = format!("{path}\u{0}{}\u{0}{nth}", c.url);
                        c.bookmark_id = ensure_bookmark_ids_return(&seed);
                        *nth += 1;
                        *count += 1;
                    }
                }
                NodeKind::Folder => {
                    let child_path = if path.is_empty() {
                        c.title.clone()
                    } else {
                        format!("{path}/{}", c.title)
                    };
                    walk(c, &child_path, seen, count);
                }
            }
        }
    }
    walk(node, "", &mut seen, &mut count);
    count
}

/// Ensure every node (folder + bookmark) has a stable `node_id`. For bookmarks
/// the existing `bookmark_id` is reused so external references stay valid.
pub fn ensure_node_ids(node: &mut Node) -> usize {
    let mut count = 0;
    fn walk(n: &mut Node, count: &mut usize) {
        for c in n.children.iter_mut() {
            if c.node_id.is_empty() {
                c.node_id = if !c.bookmark_id.is_empty() {
                    c.bookmark_id.clone()
                } else {
                    new_uuid_hex()
                };
                *count += 1;
            }
            if c.is_folder() {
                walk(c, count);
            }
        }
    }
    if node.node_id.is_empty() {
        node.node_id = "root".into();
    }
    walk(node, &mut count);
    count
}

/// Find a node by its `node_id`. Returns `(parent_path, index_within_parent)`.
/// The parent_path is the textual `/`-joined folder path of the parent.
pub fn locate_node(root: &Node, node_id: &str) -> Option<(String, usize)> {
    fn walk(node: &Node, path: &str, target: &str) -> Option<(String, usize)> {
        for (i, child) in node.children.iter().enumerate() {
            if child.node_id == target {
                return Some((path.to_string(), i));
            }
            if child.is_folder() {
                let next = if path.is_empty() {
                    child.title.clone()
                } else {
                    format!("{path}/{}", child.title)
                };
                if let Some(hit) = walk(child, &next, target) {
                    return Some(hit);
                }
            }
        }
        None
    }
    walk(root, "", node_id)
}

fn new_uuid_hex() -> String {
    // Lightweight v4-ish UUID. Mixes the high-resolution clock with a process
    // counter and an xorshift state so the bytes look genuinely random instead
    // of showing trailing zeros from a low counter.
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0) as u128;
    let counter = COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let mut hi = (nanos as u64) ^ counter.wrapping_mul(0x9E37_79B9_7F4A_7C15);
    let mut lo = ((nanos >> 64) as u64) ^ counter.rotate_left(31);
    hi = xorshift(hi);
    lo = xorshift(lo.wrapping_add(0xA5A5_A5A5_A5A5_A5A5));

    let mut bytes = [0u8; 16];
    bytes[..8].copy_from_slice(&hi.to_le_bytes());
    bytes[8..16].copy_from_slice(&lo.to_le_bytes());
    bytes[6] = (bytes[6] & 0x0f) | 0x40; // v4
    bytes[8] = (bytes[8] & 0x3f) | 0x80; // RFC 4122 variant
    let mut hex = String::with_capacity(32);
    for b in bytes {
        hex.push_str(&format!("{:02x}", b));
    }
    hex
}

fn xorshift(mut x: u64) -> u64 {
    if x == 0 {
        x = 0xDEAD_BEEF_CAFE_F00D;
    }
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    x
}

static COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);

fn now_unix_secs() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs().to_string())
        .unwrap_or_else(|_| String::new())
}

// --- Mutations -------------------------------------------------------------

pub fn add_bookmark(
    root: &mut Node,
    folder_path: &str,
    title: &str,
    url: &str,
) -> Result<String, TreeError> {
    let parent = find_folder_mut(root, folder_path)
        .ok_or_else(|| TreeError::FolderNotFound(folder_path.to_string()))?;
    if !parent.is_folder() {
        return Err(TreeError::NotFolder(folder_path.to_string()));
    }
    if url.trim().is_empty() {
        return Err(TreeError::Invalid("url is empty".into()));
    }
    let mut bm = Node::new_bookmark(
        if title.trim().is_empty() {
            url.trim()
        } else {
            title.trim()
        },
        url.trim(),
    );
    bm.bookmark_id = new_uuid_hex();
    bm.node_id = bm.bookmark_id.clone();
    bm.add_date = now_unix_secs();
    let id = bm.bookmark_id.clone();
    parent.children.push(bm);
    Ok(id)
}

pub fn add_folder(
    root: &mut Node,
    parent_path: &str,
    title: &str,
) -> Result<String, TreeError> {
    let parent = find_folder_mut(root, parent_path)
        .ok_or_else(|| TreeError::FolderNotFound(parent_path.to_string()))?;
    let title = title.trim();
    if title.is_empty() {
        return Err(TreeError::Invalid("title is empty".into()));
    }
    if title.contains('/') {
        return Err(TreeError::Invalid("folder title may not contain '/'".into()));
    }
    let mut folder = Node::new_folder(title);
    folder.node_id = new_uuid_hex();
    parent.children.push(folder);
    Ok(if parent_path.is_empty() {
        title.to_string()
    } else {
        format!("{parent_path}/{title}")
    })
}

pub fn rename_folder(
    root: &mut Node,
    folder_path: &str,
    new_title: &str,
) -> Result<String, TreeError> {
    let new_title = new_title.trim();
    if new_title.is_empty() || new_title.contains('/') {
        return Err(TreeError::Invalid("invalid new title".into()));
    }
    if folder_path.is_empty() {
        return Err(TreeError::Invalid("cannot rename root".into()));
    }
    let folder = find_folder_mut(root, folder_path)
        .ok_or_else(|| TreeError::FolderNotFound(folder_path.to_string()))?;
    folder.title = new_title.to_string();
    let new_path = match folder_path.rsplit_once('/') {
        Some((parent, _)) => format!("{parent}/{new_title}"),
        None => new_title.to_string(),
    };
    Ok(new_path)
}

pub fn delete_folder(root: &mut Node, folder_path: &str) -> Result<(), TreeError> {
    if folder_path.is_empty() {
        return Err(TreeError::Invalid("cannot delete root".into()));
    }
    let (parent_path, name) = match folder_path.rsplit_once('/') {
        Some((p, n)) => (p.to_string(), n.to_string()),
        None => (String::new(), folder_path.to_string()),
    };
    let parent = find_folder_mut(root, &parent_path)
        .ok_or_else(|| TreeError::FolderNotFound(parent_path.clone()))?;
    let pos = parent
        .children
        .iter()
        .position(|c| c.is_folder() && c.title == name)
        .ok_or_else(|| TreeError::FolderNotFound(folder_path.to_string()))?;
    parent.children.remove(pos);
    Ok(())
}

pub fn delete_bookmark(root: &mut Node, bookmark_id: &str) -> Result<(), TreeError> {
    let (parent_path, idx) = locate_bookmark(root, bookmark_id)
        .ok_or_else(|| TreeError::BookmarkNotFound(bookmark_id.to_string()))?;
    let parent = find_folder_mut(root, &parent_path)
        .ok_or_else(|| TreeError::FolderNotFound(parent_path.clone()))?;
    parent.children.remove(idx);
    Ok(())
}

#[derive(Default, Clone)]
pub struct BookmarkPatch {
    pub title: Option<String>,
    pub url: Option<String>,
    pub description: Option<String>,
}

pub fn patch_bookmark(
    root: &mut Node,
    bookmark_id: &str,
    patch: BookmarkPatch,
) -> Result<(), TreeError> {
    let (parent_path, idx) = locate_bookmark(root, bookmark_id)
        .ok_or_else(|| TreeError::BookmarkNotFound(bookmark_id.to_string()))?;
    let parent = find_folder_mut(root, &parent_path)
        .ok_or_else(|| TreeError::FolderNotFound(parent_path.clone()))?;
    let bm = &mut parent.children[idx];
    if let Some(title) = patch.title {
        bm.title = title.trim().to_string();
    }
    if let Some(url) = patch.url {
        if url.trim().is_empty() {
            return Err(TreeError::Invalid("url is empty".into()));
        }
        bm.url = url.trim().to_string();
    }
    if let Some(desc) = patch.description {
        bm.description = desc;
    }
    bm.last_modified = now_unix_secs();
    Ok(())
}

pub fn move_bookmark(
    root: &mut Node,
    bookmark_id: &str,
    target_folder: &str,
) -> Result<(), TreeError> {
    let (parent_path, idx) = locate_bookmark(root, bookmark_id)
        .ok_or_else(|| TreeError::BookmarkNotFound(bookmark_id.to_string()))?;
    if parent_path == target_folder {
        return Ok(());
    }
    let bm = {
        let parent = find_folder_mut(root, &parent_path)
            .ok_or_else(|| TreeError::FolderNotFound(parent_path.clone()))?;
        parent.children.remove(idx)
    };
    let target = find_folder_mut(root, target_folder)
        .ok_or_else(|| TreeError::FolderNotFound(target_folder.to_string()))?;
    target.children.push(bm);
    Ok(())
}

pub fn reorder_bookmark(
    root: &mut Node,
    bookmark_id: &str,
    new_index: usize,
) -> Result<(), TreeError> {
    let (parent_path, idx) = locate_bookmark(root, bookmark_id)
        .ok_or_else(|| TreeError::BookmarkNotFound(bookmark_id.to_string()))?;
    let parent = find_folder_mut(root, &parent_path)
        .ok_or_else(|| TreeError::FolderNotFound(parent_path.clone()))?;
    let len = parent.children.len();
    if len == 0 {
        return Ok(());
    }
    let target = new_index.min(len - 1);
    let item = parent.children.remove(idx);
    parent.children.insert(target, item);
    Ok(())
}

/// Move any node (folder or bookmark) to a new index within the *same* parent,
/// or into a different parent folder. `target_parent_path` empty == root.
/// `new_index` past the end clamps to append.
pub fn move_node(
    root: &mut Node,
    node_id: &str,
    target_parent_path: &str,
    new_index: Option<usize>,
) -> Result<(), TreeError> {
    let (parent_path, idx) = locate_node(root, node_id)
        .ok_or_else(|| TreeError::BookmarkNotFound(node_id.to_string()))?;

    // Reject moving a folder into itself or its own descendant.
    let moving_folder_path = {
        let parent = find_folder(root, &parent_path)
            .ok_or_else(|| TreeError::FolderNotFound(parent_path.clone()))?;
        let n = &parent.children[idx];
        if n.is_folder() {
            Some(if parent_path.is_empty() {
                n.title.clone()
            } else {
                format!("{parent_path}/{}", n.title)
            })
        } else {
            None
        }
    };
    if let Some(src) = &moving_folder_path {
        if target_parent_path == src
            || target_parent_path.starts_with(&format!("{src}/"))
        {
            return Err(TreeError::Invalid(
                "cannot move a folder into itself or its descendant".into(),
            ));
        }
    }

    // Detach
    let item = {
        let parent = find_folder_mut(root, &parent_path)
            .ok_or_else(|| TreeError::FolderNotFound(parent_path.clone()))?;
        parent.children.remove(idx)
    };

    // Re-attach
    let target = find_folder_mut(root, target_parent_path)
        .ok_or_else(|| TreeError::FolderNotFound(target_parent_path.to_string()))?;
    let len = target.children.len();
    let pos = new_index.unwrap_or(len).min(len);
    target.children.insert(pos, item);
    Ok(())
}

/// Reorder a node within its current parent. Equivalent to
/// `move_node(root, id, <same_parent>, Some(new_index))`.
pub fn reorder_node(
    root: &mut Node,
    node_id: &str,
    new_index: usize,
) -> Result<(), TreeError> {
    let (parent_path, _) = locate_node(root, node_id)
        .ok_or_else(|| TreeError::BookmarkNotFound(node_id.to_string()))?;
    move_node(root, node_id, &parent_path, Some(new_index))
}

pub fn move_bookmark_up(root: &mut Node, bookmark_id: &str) -> Result<(), TreeError> {
    let (parent_path, idx) = locate_bookmark(root, bookmark_id)
        .ok_or_else(|| TreeError::BookmarkNotFound(bookmark_id.to_string()))?;
    if idx == 0 {
        return Err(TreeError::Invalid("already at top".into()));
    }
    let parent = find_folder_mut(root, &parent_path)
        .ok_or_else(|| TreeError::FolderNotFound(parent_path.clone()))?;
    parent.children.swap(idx, idx - 1);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> Node {
        let mut root = Node::new_root();
        let mut bar = Node::new_folder("Bar");
        bar.children.push({
            let mut b = Node::new_bookmark("first", "https://a.example/");
            b.bookmark_id = "id-a".into();
            b
        });
        bar.children.push({
            let mut b = Node::new_bookmark("second", "https://b.example/");
            b.bookmark_id = "id-b".into();
            b
        });
        let mut sub = Node::new_folder("Sub");
        sub.children.push({
            let mut b = Node::new_bookmark("nested", "https://c.example/");
            b.bookmark_id = "id-c".into();
            b
        });
        bar.children.push(sub);
        root.children.push(bar);
        root
    }

    fn raw_export() -> Node {
        // Mimics a browser export: no BOOKMARK_ID attributes anywhere.
        let mut root = Node::new_root();
        let mut work = Node::new_folder("Work");
        work.children.push(Node::new_bookmark("Rust", "https://rust-lang.org/"));
        work.children.push(Node::new_bookmark("Docs", "https://doc.rust-lang.org/"));
        // Duplicate URL in the same folder must still get distinct ids.
        work.children.push(Node::new_bookmark("Rust again", "https://rust-lang.org/"));
        root.children.push(work);
        root
    }

    #[test]
    fn ensure_ids_are_deterministic_across_reopens() {
        let mut a = raw_export();
        let mut b = raw_export();
        ensure_bookmark_ids(&mut a);
        ensure_bookmark_ids(&mut b);
        let ids_a: Vec<_> = a.children[0].children.iter().map(|c| c.bookmark_id.clone()).collect();
        let ids_b: Vec<_> = b.children[0].children.iter().map(|c| c.bookmark_id.clone()).collect();
        assert_eq!(ids_a, ids_b, "same file must yield identical ids on reopen");
    }

    #[test]
    fn ensure_ids_distinguish_duplicate_urls() {
        let mut root = raw_export();
        ensure_bookmark_ids(&mut root);
        let work = &root.children[0];
        let first = &work.children[0].bookmark_id; // Rust
        let dup = &work.children[2].bookmark_id;   // Rust again, same URL
        assert!(!first.is_empty() && !dup.is_empty());
        assert_ne!(first, dup, "duplicate URLs in a folder must get distinct ids");
    }

    #[test]
    fn ensure_ids_preserve_existing() {
        // Nodes that already carry an id (e.g. files we saved before) are untouched.
        let mut root = sample();
        ensure_bookmark_ids(&mut root);
        assert_eq!(locate_bookmark(&root, "id-a"), Some(("Bar".into(), 0)));
        assert_eq!(locate_bookmark(&root, "id-c"), Some(("Bar/Sub".into(), 0)));
    }

    #[test]
    fn locate_finds_nested() {
        let root = sample();
        assert_eq!(locate_bookmark(&root, "id-c"), Some(("Bar/Sub".into(), 0)));
        assert_eq!(locate_bookmark(&root, "missing"), None);
    }

    #[test]
    fn add_and_delete_bookmark() {
        let mut root = sample();
        let id = add_bookmark(&mut root, "Bar", "new", "https://new.example/").unwrap();
        assert!(locate_bookmark(&root, &id).is_some());
        delete_bookmark(&mut root, &id).unwrap();
        assert!(locate_bookmark(&root, &id).is_none());
    }

    #[test]
    fn move_bookmark_between_folders() {
        let mut root = sample();
        move_bookmark(&mut root, "id-a", "Bar/Sub").unwrap();
        assert_eq!(locate_bookmark(&root, "id-a"), Some(("Bar/Sub".into(), 1)));
    }

    #[test]
    fn rename_folder_updates_path() {
        let mut root = sample();
        let new_path = rename_folder(&mut root, "Bar", "Renamed").unwrap();
        assert_eq!(new_path, "Renamed");
        assert!(find_folder(&root, "Renamed").is_some());
        assert_eq!(locate_bookmark(&root, "id-c"), Some(("Renamed/Sub".into(), 0)));
    }

    #[test]
    fn ensure_ids_assigns_only_missing() {
        let mut root = sample();
        // Add one without id.
        root.children[0].children.push(Node::new_bookmark("x", "https://x/"));
        let n = ensure_bookmark_ids(&mut root);
        assert_eq!(n, 1);
        // Re-running is a no-op.
        assert_eq!(ensure_bookmark_ids(&mut root), 0);
    }

    #[test]
    fn move_up_reorders() {
        let mut root = sample();
        move_bookmark_up(&mut root, "id-b").unwrap();
        // id-b should now be at index 0 in Bar.
        let bar = find_folder(&root, "Bar").unwrap();
        assert_eq!(bar.children[0].bookmark_id, "id-b");
        assert_eq!(bar.children[1].bookmark_id, "id-a");
    }
}
