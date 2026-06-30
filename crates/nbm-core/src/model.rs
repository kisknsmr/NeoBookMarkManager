use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum NodeKind {
    Folder,
    Bookmark,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Node {
    #[serde(rename = "type")]
    pub kind: NodeKind,
    #[serde(default)]
    pub title: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub url: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub add_date: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub last_modified: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub icon: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub description: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub bookmark_id: String,
    /// Stable identifier for *every* node (folder or bookmark). For bookmarks
    /// this duplicates `bookmark_id` so existing API surface keeps working;
    /// for folders this is the only handle the frontend uses to reorder/move
    /// them, since folder paths shift as siblings are renamed.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub node_id: String,
    #[serde(default)]
    pub children: Vec<Node>,
}

impl Node {
    pub fn new_root() -> Self {
        Self {
            kind: NodeKind::Folder,
            title: "Bookmarks".into(),
            url: String::new(),
            add_date: String::new(),
            last_modified: String::new(),
            icon: String::new(),
            description: String::new(),
            bookmark_id: String::new(),
            node_id: String::new(),
            children: Vec::new(),
        }
    }

    pub fn new_folder(title: impl Into<String>) -> Self {
        Self {
            kind: NodeKind::Folder,
            title: title.into(),
            ..Self::new_root()
        }
    }

    pub fn new_bookmark(title: impl Into<String>, url: impl Into<String>) -> Self {
        let mut n = Self::new_root();
        n.kind = NodeKind::Bookmark;
        n.title = title.into();
        n.url = url.into();
        n
    }

    pub fn is_folder(&self) -> bool {
        matches!(self.kind, NodeKind::Folder)
    }

    /// Walk all descendants depth-first, including self.
    pub fn walk(&self) -> impl Iterator<Item = &Node> {
        let mut stack = vec![self];
        std::iter::from_fn(move || {
            let n = stack.pop()?;
            for child in n.children.iter().rev() {
                stack.push(child);
            }
            Some(n)
        })
    }

    pub fn count_bookmarks(&self) -> usize {
        self.walk().filter(|n| !n.is_folder()).count()
    }
}
