//! Bookmark organization utilities.
//!
//! Mirrors `OriginalPythonCodes/services/ServiceBookmark.py` organize section:
//! dedupe, merge-duplicate-folders, consolidate-by-domain, domain-statistics.

use std::collections::{HashMap, HashSet};

use crate::model::{Node, NodeKind};
use crate::tree::{find_folder, find_folder_mut};

#[derive(Debug, thiserror::Error)]
pub enum OrganizeError {
    #[error("folder not found: {0}")]
    FolderNotFound(String),
    #[error("invalid: {0}")]
    Invalid(String),
}

// --- Domain helpers --------------------------------------------------------

pub fn normalize_domain(url: &str) -> String {
    if url.is_empty() {
        return String::new();
    }
    // Minimal URL parse — we don't pull url::Url in nbm-core.
    let after_scheme = url
        .strip_prefix("https://")
        .or_else(|| url.strip_prefix("http://"))
        .unwrap_or(url);
    let netloc = after_scheme.split('/').next().unwrap_or("").to_lowercase();
    // Strip port.
    let netloc = netloc.split(':').next().unwrap_or("").to_string();
    // Strip www.
    let netloc = netloc.strip_prefix("www.").unwrap_or(&netloc).to_string();
    netloc
}

// --- Domain statistics -----------------------------------------------------

/// Returns `(domain, count)` pairs sorted by frequency descending.
/// Mirrors `BookmarkService.get_domain_statistics`.
pub fn domain_statistics(root: &Node) -> Vec<(String, usize)> {
    let mut map: HashMap<String, usize> = HashMap::new();
    walk_bookmarks(root, &mut |bm| {
        let d = normalize_domain(&bm.url);
        if !d.is_empty() {
            *map.entry(d).or_insert(0) += 1;
        }
    });
    let mut vec: Vec<_> = map.into_iter().collect();
    vec.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    vec
}

// --- Deduplicate bookmarks (same folder, same URL) -------------------------

/// Remove duplicate bookmarks inside `folder_path` (exact URL match, keep first).
/// URLs in `exclude_urls` are never treated as duplicates (always kept as-is).
pub fn dedupe_folder(
    root: &mut Node,
    folder_path: &str,
    exclude_urls: &HashSet<String>,
) -> Result<usize, OrganizeError> {
    let folder = find_folder_mut(root, folder_path)
        .ok_or_else(|| OrganizeError::FolderNotFound(folder_path.to_string()))?;
    let mut seen: HashSet<String> = HashSet::new();
    let before = folder.children.len();
    folder.children.retain(|c| match c.kind {
        NodeKind::Bookmark => {
            let url = c.url.clone();
            if url.is_empty() || exclude_urls.contains(&url) {
                true // always keep blanks and excluded URLs
            } else {
                seen.insert(url)
            }
        }
        NodeKind::Folder => true,
    });
    Ok(before - folder.children.len())
}

// --- Merge duplicate folders (same name, same parent) ----------------------

/// Merge same-name sub-folders into the first occurrence (case-insensitive).
/// Mirrors `BookmarkService.merge_duplicate_folders`.
pub fn merge_duplicate_folders(root: &mut Node, parent_path: &str) -> Result<usize, OrganizeError> {
    let parent = find_folder_mut(root, parent_path)
        .ok_or_else(|| OrganizeError::FolderNotFound(parent_path.to_string()))?;
    let mut folder_map: HashMap<String, usize> = HashMap::new(); // title.lower -> index in children
    let mut to_merge: Vec<(usize, usize)> = Vec::new(); // (dup_idx, target_idx)
    for (i, child) in parent.children.iter().enumerate() {
        if !child.is_folder() {
            continue;
        }
        let key = child.title.to_lowercase();
        match folder_map.get(&key) {
            Some(&target_idx) => to_merge.push((i, target_idx)),
            None => { folder_map.insert(key, i); }
        }
    }
    // Process in reverse order so indices stay stable.
    to_merge.sort_by_key(|&(dup_idx, _)| std::cmp::Reverse(dup_idx));
    let count = to_merge.len();
    for (dup_idx, target_idx) in to_merge {
        let dup_children: Vec<Node> = std::mem::take(&mut parent.children[dup_idx].children);
        parent.children.remove(dup_idx);
        // target_idx is now off by (dup_idx was before target), but since dup_idx > target_idx
        // (we process smallest to largest dup in reverse), the target stays stable.
        let target = &mut parent.children[target_idx];
        target.children.extend(dup_children);
    }
    Ok(count)
}

// --- Sort by domain --------------------------------------------------------

/// Sort the direct bookmark children of `folder_path` by domain, then by title.
/// Sub-folders are kept in place (moved to the front, preserving their relative order).
pub fn sort_by_domain(root: &mut Node, folder_path: &str) -> Result<usize, OrganizeError> {
    let folder = find_folder_mut(root, folder_path)
        .ok_or_else(|| OrganizeError::FolderNotFound(folder_path.to_string()))?;
    let before: Vec<_> = std::mem::take(&mut folder.children);
    let count = before.len();
    let (mut folders, mut bookmarks): (Vec<_>, Vec<_>) =
        before.into_iter().partition(|n| n.is_folder());
    bookmarks.sort_by(|a, b| {
        let da = normalize_domain(&a.url);
        let db = normalize_domain(&b.url);
        da.cmp(&db).then(a.title.to_lowercase().cmp(&b.title.to_lowercase()))
    });
    folders.append(&mut bookmarks);
    folder.children = folders;
    Ok(count)
}

// --- Consolidate by domain -------------------------------------------------

/// Consolidate bookmarks/folders matching `domain` into `target_folder_name`.
///
/// Rules (applied recursively inside `scope_path`):
/// - A direct-child **folder** whose every bookmark (recursively) belongs to
///   `domain` → move the whole folder into `target_folder_name` and remove the
///   original.
/// - A direct-child **folder** that is mixed (some domain, some not) → recurse
///   into it and lift only the pure-domain sub-folders / lone bookmarks.
/// - A direct-child **bookmark** matching `domain` → move into `target_folder_name`.
/// - Empty folders left behind are removed.
///
/// `scope_path`:
///   - `None` / `Some("")` → operate from root
///   - `Some(p)` → operate inside folder `p`; target folder is created inside `p`
///
/// `keyword`: when `Some(kw)`, only bookmarks whose title contains `kw`
/// (case-insensitive) are matched. Folders are still moved whole only when
/// *all* their bookmarks pass both the domain and keyword filters.
pub fn consolidate_by_domain(
    root: &mut Node,
    domain: &str,
    target_folder_name: &str,
    scope_path: Option<&str>,
    keyword: Option<&str>,
    // Space-joined tag names per bookmark_id from the DB (pass empty map if unavailable).
    tags_map: &std::collections::HashMap<String, String>,
    // Folder names (case-insensitive) to leave untouched — used by callers that
    // issue several consolidation passes in a row (e.g. one per keyword rule,
    // then a catch-all) so the catch-all doesn't re-absorb folders a previous
    // pass already created/populated for this same domain.
    exclude_names: &[String],
) -> Result<usize, OrganizeError> {
    let domain_norm = {
        let d = domain.trim().to_lowercase();
        d.strip_prefix("www.").map(|s| s.to_string()).unwrap_or(d)
    };
    let kw_lower = keyword.map(|k| k.trim().to_lowercase()).filter(|k| !k.is_empty());
    if domain_norm.is_empty() || target_folder_name.trim().is_empty() {
        return Err(OrganizeError::Invalid("domain and target_folder_name are required".into()));
    }
    let exclude_lower: HashSet<String> = exclude_names.iter().map(|s| s.trim().to_lowercase()).collect();

    let target_parent_path = match scope_path {
        Some(sp) if !sp.is_empty() => sp.to_string(),
        _ => String::new(),
    };

    // Validate scope exists.
    if !target_parent_path.is_empty() && find_folder(root, &target_parent_path).is_none() {
        return Err(OrganizeError::FolderNotFound(target_parent_path.clone()));
    }

    let target_name_lower = target_folder_name.to_lowercase();
    let target_full_path = if target_parent_path.is_empty() {
        target_folder_name.to_string()
    } else {
        format!("{}/{}", target_parent_path, target_folder_name)
    };

    // Collect items to pull into the target folder.
    // Each entry is either:
    //   Ok(node_id)  → move this entire child node of the scope into target
    //   Err(bm_id)   → move this bookmark (nested) into target
    //
    // The analysis only needs to read the scope, so it borrows it immutably.
    // This used to clone the entire subtree "so we can analyse it without
    // borrow conflicts" — there was no conflict to avoid, because what comes
    // back is a list of owned ids that borrows nothing.
    let mut items_to_move: Vec<Result<String, String>> = Vec::new();
    {
        let scope = find_folder(root, &target_parent_path)
            .ok_or_else(|| OrganizeError::FolderNotFound(target_parent_path.clone()))?;
        collect_domain_items(
            scope,
            &domain_norm,
            &target_name_lower,
            kw_lower.as_deref(),
            tags_map,
            &exclude_lower,
            &mut items_to_move,
        );
    }

    if items_to_move.is_empty() {
        return Ok(0);
    }

    // Ensure target folder exists inside the scope parent.
    {
        let parent = find_folder_mut(root, &target_parent_path)
            .ok_or_else(|| OrganizeError::FolderNotFound(target_parent_path.clone()))?;
        if !parent.children.iter().any(|c| c.is_folder() && c.title.to_lowercase() == target_name_lower) {
            parent.children.insert(0, Node::new_folder(target_folder_name));
        }
    }

    let mut moved = 0;

    for item in items_to_move {
        // Each move is detach-then-attach. Both halves resolve their own path,
        // and `attach_to_named_child` hands the node back rather than dropping
        // it if the target disappeared, so a failed attach cannot lose data.
        let (node, weight) = match item {
            // An entire child node of the scope, addressed by node_id.
            Ok(node_id) => {
                match detach_child_by_node_id(root, &target_parent_path, &node_id) {
                    Some(child) => {
                        let bm_count = count_bookmarks(&child);
                        (child, bm_count)
                    }
                    None => continue,
                }
            }
            // A single bookmark, addressed by bookmark_id.
            Err(bm_id) => {
                let Some((src_path, idx)) = crate::tree::locate_bookmark(root, &bm_id) else {
                    continue;
                };
                // Skip if already inside the target folder.
                if src_path.to_lowercase() == target_full_path.to_lowercase() {
                    continue;
                }
                match detach_child_at(root, &src_path, idx) {
                    Some(bm_node) => (bm_node, 1),
                    None => continue,
                }
            }
        };

        match attach_to_named_child(root, &target_parent_path, &target_name_lower, node) {
            Ok(()) => moved += weight,
            // The target folder was created above and nothing removes it, so
            // this is unreachable in practice; putting the node back where it
            // came from is still better than dropping it on the floor.
            Err(orphan) => {
                if let Some(parent) = find_folder_mut(root, &target_parent_path) {
                    parent.children.push(*orphan);
                }
            }
        }
    }

    // Remove empty folders left inside the scope (but not the target folder itself).
    if let Some(scope) = find_folder_mut(root, &target_parent_path) {
        remove_empty_folders(scope, &target_name_lower);
    }

    Ok(moved)
}

/// Detach the direct child of `parent_path` whose `node_id` matches.
fn detach_child_by_node_id(root: &mut Node, parent_path: &str, node_id: &str) -> Option<Node> {
    let parent = find_folder_mut(root, parent_path)?;
    let pos = parent.children.iter().position(|c| c.node_id == node_id)?;
    Some(parent.children.remove(pos))
}

/// Detach the child at `idx` under `parent_path`.
fn detach_child_at(root: &mut Node, parent_path: &str, idx: usize) -> Option<Node> {
    let parent = find_folder_mut(root, parent_path)?;
    (idx < parent.children.len()).then(|| parent.children.remove(idx))
}

/// Append `node` to the folder named `name_lower` (compared case-insensitively)
/// directly under `parent_path`. Creates nothing; if that folder is not there,
/// `node` comes back untouched so the caller can decide what to do with it.
/// (Boxed on the way back only because a whole subtree is a large `Err`.)
fn attach_to_named_child(
    root: &mut Node,
    parent_path: &str,
    name_lower: &str,
    node: Node,
) -> Result<(), Box<Node>> {
    let Some(parent) = find_folder_mut(root, parent_path) else {
        return Err(Box::new(node));
    };
    let target = parent
        .children
        .iter_mut()
        .find(|c| c.is_folder() && c.title.to_lowercase() == name_lower);
    match target {
        Some(folder) => {
            folder.children.push(node);
            Ok(())
        }
        None => Err(Box::new(node)),
    }
}

fn collect_domain_items(
    parent: &Node,
    domain: &str,
    target_name_lower: &str,
    keyword: Option<&str>,
    tags_map: &std::collections::HashMap<String, String>,
    exclude_names: &HashSet<String>,
    out: &mut Vec<Result<String, String>>,
) {
    for child in &parent.children {
        match child.kind {
            NodeKind::Bookmark => {
                let extra = tags_map.get(&child.bookmark_id).map(|s| s.as_str());
                if bm_matches(child, domain, keyword, extra) && !child.bookmark_id.is_empty() {
                    out.push(Err(child.bookmark_id.clone()));
                }
            }
            NodeKind::Folder => {
                let title_lower = child.title.to_lowercase();
                if title_lower == target_name_lower || exclude_names.contains(&title_lower) {
                    continue;
                }
                if folder_all_match(child, domain, keyword, tags_map) {
                    out.push(Ok(child.node_id.clone()));
                } else {
                    collect_domain_items(child, domain, target_name_lower, keyword, tags_map, exclude_names, out);
                }
            }
        }
    }
}

/// Returns true when a bookmark matches domain AND keyword (if set).
/// Searched fields: title, description, URL, and `extra` (caller passes
/// space-joined tag names from the DB so we stay DB-free in this crate).
fn bm_matches(bm: &Node, domain: &str, keyword: Option<&str>, extra_tags: Option<&str>) -> bool {
    if normalize_domain(&bm.url) != domain {
        return false;
    }
    if let Some(kw) = keyword {
        bm.title.to_lowercase().contains(kw)
            || bm.description.to_lowercase().contains(kw)
            || bm.url.to_lowercase().contains(kw)
            || extra_tags.is_some_and(|t| t.to_lowercase().contains(kw))
    } else {
        true
    }
}

fn folder_all_match(
    node: &Node,
    domain: &str,
    keyword: Option<&str>,
    tags_map: &std::collections::HashMap<String, String>,
) -> bool {
    let mut total = 0usize;
    let mut matching = 0usize;
    walk_bookmarks(node, &mut |bm| {
        total += 1;
        let extra = tags_map.get(&bm.bookmark_id).map(|s| s.as_str());
        if bm_matches(bm, domain, keyword, extra) {
            matching += 1;
        }
    });
    total > 0 && total == matching
}

/// Remove folders (recursively) that contain no bookmarks,
/// skipping the folder named `skip_lower`.
fn remove_empty_folders(parent: &mut Node, skip_lower: &str) {
    // First recurse into children.
    for child in parent.children.iter_mut() {
        if child.is_folder() && child.title.to_lowercase() != skip_lower {
            remove_empty_folders(child, skip_lower);
        }
    }
    // Then drop empty folders at this level (never drop the target).
    parent.children.retain(|c| {
        if c.is_folder() && c.title.to_lowercase() != skip_lower {
            count_bookmarks(c) > 0
        } else {
            true
        }
    });
}

fn count_bookmarks(node: &Node) -> usize {
    let mut n = 0;
    walk_bookmarks(node, &mut |_| n += 1);
    n
}

// --- Internal helpers ------------------------------------------------------

// Path lookup lives in `tree` (see the import at the top of the file); this
// module used to carry its own byte-identical copy of `find_folder_mut`.

fn walk_bookmarks<'a>(node: &'a Node, f: &mut impl FnMut(&'a Node)) {
    for child in &node.children {
        match child.kind {
            NodeKind::Bookmark => f(child),
            NodeKind::Folder => walk_bookmarks(child, f),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::Node;

    fn sample() -> Node {
        let mut root = Node::new_root();
        let mut f1 = Node::new_folder("Work");
        let bm = |title: &str, url: &str| {
            let mut b = Node::new_bookmark(title, url);
            b.bookmark_id = crate::tree::ensure_bookmark_ids_return(title);
            b
        };
        f1.children.push(bm("A", "https://github.com/a"));
        f1.children.push(bm("B", "https://github.com/b"));
        f1.children.push(bm("Dup", "https://github.com/a")); // duplicate URL
        root.children.push(f1);
        let mut f2 = Node::new_folder("Personal");
        f2.children.push(bm("C", "https://example.com/"));
        root.children.push(f2);
        // Duplicate folder names.
        root.children.push(Node::new_folder("Work"));
        root
    }

    #[test]
    fn dedupe_removes_exact_url_dups() {
        let mut root = sample();
        let removed = dedupe_folder(&mut root, "Work", &HashSet::new()).unwrap();
        assert_eq!(removed, 1);
        assert_eq!(root.children[0].children.len(), 2);
    }

    #[test]
    fn merge_dup_folders_combines() {
        let mut root = sample();
        let merged = merge_duplicate_folders(&mut root, "").unwrap();
        assert_eq!(merged, 1);
        assert!(root.children.iter().filter(|c| c.title == "Work").count() == 1);
    }

    #[test]
    fn domain_stats_counts() {
        let root = sample();
        let stats = domain_statistics(&root);
        let github = stats.iter().find(|(d, _)| d == "github.com").map(|(_, c)| *c);
        assert_eq!(github, Some(3)); // A, B, Dup all github.com
    }

    #[test]
    fn consolidate_moves_matching_bookmarks() {
        let mut root = sample();
        crate::tree::ensure_bookmark_ids(&mut root);
        crate::tree::ensure_node_ids(&mut root);
        // Work/ has A, B, Dup (all github.com) → whole Work folder moves into GitHub/
        let moved = consolidate_by_domain(&mut root, "github.com", "GitHub", None, None, &Default::default(), &[]).unwrap();
        assert!(moved >= 3);
        let gh = root.children.iter().find(|c| c.title == "GitHub").unwrap();
        let bm_count = count_bookmarks(gh);
        assert_eq!(bm_count, 3);
    }

    #[test]
    fn consolidate_scoped_to_folder() {
        let mut root = sample();
        crate::tree::ensure_bookmark_ids(&mut root);
        crate::tree::ensure_node_ids(&mut root);
        // Scope to Work/: target folder created inside Work/, not at root.
        let moved = consolidate_by_domain(&mut root, "github.com", "GitHub", Some("Work"), None, &Default::default(), &[]).unwrap();
        assert!(moved >= 3);
        assert!(root.children.iter().all(|c| c.title != "GitHub"), "GitHub folder must not be at root");
        let work = root.children.iter().find(|c| c.title == "Work").unwrap();
        let gh = work.children.iter().find(|c| c.title == "GitHub").unwrap();
        assert_eq!(count_bookmarks(gh), 3);
    }

    #[test]
    fn consolidate_pure_subfolder_moved_whole() {
        // Work/
        //   tools/          ← all github.com
        //     gh-cli
        //     gh-docs
        //   readme          ← github.com (lone bm)
        // Expected: GitHub/ contains tools/ + readme; Work/ is empty → removed.
        let mut root = Node::new_root();
        crate::tree::ensure_node_ids(&mut root);
        let mut work = Node::new_folder("Work");
        let mut tools = Node::new_folder("tools");
        tools.children.push(Node::new_bookmark("gh-cli", "https://github.com/cli/cli"));
        tools.children.push(Node::new_bookmark("gh-docs", "https://github.com/github/docs"));
        work.children.push(tools);
        work.children.push(Node::new_bookmark("readme", "https://github.com/readme"));
        root.children.push(work);
        crate::tree::ensure_bookmark_ids(&mut root);
        crate::tree::ensure_node_ids(&mut root);

        let moved = consolidate_by_domain(&mut root, "github.com", "GitHub", None, None, &Default::default(), &[]).unwrap();
        assert_eq!(moved, 3);

        let gh = root.children.iter().find(|c| c.title == "GitHub").unwrap();
        // Work/ was all-github.com → moved whole into GitHub/
        assert!(gh.children.iter().any(|c| c.is_folder() && c.title == "Work"));
        assert_eq!(count_bookmarks(gh), 3);
        // Original Work/ should be gone at root level.
        assert_eq!(root.children.iter().filter(|c| c.title == "Work").count(), 0);
    }

    #[test]
    fn consolidate_mixed_folder_keeps_non_domain() {
        // Work/
        //   tools/
        //     gh-cli         ← github.com
        //     curl-doc       ← curl.se
        // Expected: gh-cli moves to GitHub/, curl-doc stays in tools/, tools/ stays in Work/
        let mut root = Node::new_root();
        let mut work = Node::new_folder("Work");
        let mut tools = Node::new_folder("tools");
        tools.children.push(Node::new_bookmark("gh-cli", "https://github.com/cli/cli"));
        tools.children.push(Node::new_bookmark("curl-doc", "https://curl.se/docs"));
        work.children.push(tools);
        root.children.push(work);
        crate::tree::ensure_bookmark_ids(&mut root);
        crate::tree::ensure_node_ids(&mut root);

        let moved = consolidate_by_domain(&mut root, "github.com", "GitHub", None, None, &Default::default(), &[]).unwrap();
        assert_eq!(moved, 1);

        let gh = root.children.iter().find(|c| c.title == "GitHub").unwrap();
        assert_eq!(count_bookmarks(gh), 1);

        let work = root.children.iter().find(|c| c.title == "Work").unwrap();
        let tools = work.children.iter().find(|c| c.title == "tools").unwrap();
        assert_eq!(count_bookmarks(tools), 1); // curl-doc remains
    }

    #[test]
    fn consolidate_catchall_does_not_reabsorb_prior_rule_folders() {
        // Domain×Keyword wizard flow: one pass per keyword rule, then a
        // catch-all pass (keyword=None) targeting the domain name itself.
        // The catch-all must not re-absorb the "Python" folder the first
        // pass just created, even though every bookmark inside it also
        // matches the domain (since keyword=None matches unconditionally).
        let mut root = Node::new_root();
        root.children.push(Node::new_bookmark("py lib", "https://github.com/py/lib"));
        root.children.push(Node::new_bookmark("other repo", "https://github.com/other/repo"));
        crate::tree::ensure_bookmark_ids(&mut root);
        crate::tree::ensure_node_ids(&mut root);

        // Pass 1: keyword "py" → folder "Python".
        let moved1 = consolidate_by_domain(
            &mut root, "github.com", "Python", None, Some("py"), &Default::default(), &[],
        ).unwrap();
        assert_eq!(moved1, 1);

        // Pass 2: catch-all → folder "github.com", excluding "Python".
        let moved2 = consolidate_by_domain(
            &mut root, "github.com", "github.com", None, None, &Default::default(),
            &["Python".to_string()],
        ).unwrap();
        assert_eq!(moved2, 1, "only the unmatched bookmark should move");

        let python = root.children.iter().find(|c| c.title == "Python").unwrap();
        assert_eq!(count_bookmarks(python), 1);
        assert!(!python.children.iter().any(|c| c.is_folder()), "Python/ must not contain a nested github.com/ folder");

        let domain_folder = root.children.iter().find(|c| c.title == "github.com").unwrap();
        assert_eq!(count_bookmarks(domain_folder), 1);
        assert!(domain_folder.children.iter().all(|c| !c.is_folder()), "github.com/ must not have swallowed Python/");
    }

    #[test]
    fn sort_by_domain_orders_bookmarks() {
        let mut root = Node::new_root();
        let mut folder = Node::new_folder("Mixed");
        let bm = |title: &str, url: &str| {
            let mut b = Node::new_bookmark(title, url);
            b.bookmark_id = crate::tree::ensure_bookmark_ids_return(title);
            b
        };
        folder.children.push(bm("Z", "https://z.example.com/"));
        folder.children.push(bm("A", "https://a.example.com/"));
        folder.children.push(bm("M", "https://m.example.com/"));
        root.children.push(folder);
        sort_by_domain(&mut root, "Mixed").unwrap();
        let titles: Vec<_> = root.children[0].children.iter().map(|c| c.title.as_str()).collect();
        assert_eq!(titles, ["A", "M", "Z"]);
    }
}
