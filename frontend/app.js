// NeoBookMarkManager — frontend (Phase 3 build).
//
// Phase 3 wires mutation commands to the Rust API:
//   add/edit/delete bookmark+folder, save, tags, move-up, reorder, backup.
// D&D and 2-pane tree-to-tree moves come in Phase 4.

const API_BASE_STORAGE_KEY = "nbm_api_base";
const SPLIT_STORAGE_KEY = "nbm_split_state";
const VIEW_STORAGE_KEY = "nbm_view_mode";
const DUAL_STORAGE_KEY = "nbm_dual_pane";
const TREE_OPEN_STORAGE_KEY = "nbm_tree_open";

function loadApiBase() {
  if (window.__NBM_API_BASE__) return window.__NBM_API_BASE__.replace(/\/+$/, "");
  try {
    const stored = localStorage.getItem(API_BASE_STORAGE_KEY);
    if (stored) return stored.replace(/\/+$/, "");
  } catch (_) {}
  return "";
}
const API_BASE = loadApiBase();

// --- DOM refs --------------------------------------------------------------

const $ = (id) => document.getElementById(id);
const statusChip = $("statusChip");
const toastEl = $("toast");
const searchInput = $("searchInput");
const treeContainerA = $("treeContainerA");
const treeContainerB = $("treeContainerB");
const listContainer = $("listContainer");
const treeCountEl = $("treeCount");
const listCountEl = $("listCount");
const viewChip = $("viewChip");
const viewListBtn = $("viewListBtn");
const viewCardBtn = $("viewCardBtn");
const dualPaneBtn = $("dualPaneBtn");
const detailEmpty = $("detailEmpty");
const detailCard = $("detailCard");
const detailTitle = $("detailTitle");
const detailFetchedTitle = $("detailFetchedTitle");
const detailUrl = $("detailUrl");
const detailMeta = $("detailMeta");
const detailTags = $("detailTags");
const detailDescription = $("detailDescription");
const treeNodeTpl = $("treeNodeTemplate");
const treeBmTpl   = $("treeBmTemplate");
const listRowTpl = $("listRowTemplate");
const listCardTpl = $("listCardTemplate");

// --- State -----------------------------------------------------------------

const state = {
  bookmarks: [],          // flat array from /bookmarks
  treeRoot: null,         // hierarchical view derived from folder_path
  selectedFolder: null,   // folder path string for Tree A
  selectedFolderB: null,  // folder path string for Tree B (2-pane mode)
  selectedBookmark: null, // bookmark item (flat record) — last clicked
  selectedBookmarks: new Set(), // Set<bookmark_id> for multi-select
  selectedBookmarkMap: new Map(), // Map<bookmark_id, bm record>
  lastClickedBmId: null,  // for Shift-range anchor
  openFolders: new Set(), // folder paths currently expanded (shared A+B)
  openFoldersB: new Set(), // open state for Tree B (independent)
  searchQuery: "",
};

// --- Toast / status --------------------------------------------------------

let toastTimer = null;
function toast(msg, kind) {
  toastEl.textContent = msg;
  toastEl.className = "toast " + (kind === "error" ? "error" : "");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.add("hidden"), 2400);
}

function setStatus(text) {
  statusChip.textContent = text;
}

// --- API client ------------------------------------------------------------

async function api(path, opts = {}) {
  const url = API_BASE + path;
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// --- Tree building from server /tree --------------------------------------
//
// Server returns the canonical Node tree where folders and bookmarks are
// siblings inside a single ordered `children` array. We preserve that order
// verbatim so the user can reorder folders and bookmarks against each other.
// Each node has `type` ("folder"|"bookmark"), `node_id`, `title`, and folders
// have nested `children`; bookmarks have `url`/`bookmark_id` etc.

function annotateTree(root) {
  // Walk the server tree and attach a computed `path` (folder path string)
  // to every folder for quick lookup. Root path is "".
  const visit = (node, path) => {
    node.path = path;
    if (node.type === "folder") {
      for (const c of node.children || []) {
        const childPath = c.type === "folder"
          ? (path ? `${path}/${c.title}` : c.title)
          : path;
        visit(c, childPath);
      }
    }
  };
  visit(root, "");
  return root;
}

function countBookmarks(node) {
  if (node.type === "bookmark") return 1;
  let n = 0;
  for (const c of node.children || []) n += countBookmarks(c);
  return n;
}

function findFolderByPath(root, path) {
  if (!path) return root;
  const parts = path.split("/").filter(Boolean);
  let cur = root;
  for (const p of parts) {
    const next = (cur.children || []).find((c) => c.type === "folder" && c.title === p);
    if (!next) return null;
    cur = next;
  }
  return cur;
}

function findNodeById(root, nodeId) {
  if (root.node_id === nodeId) return root;
  for (const c of root.children || []) {
    if (c.node_id === nodeId) return c;
    if (c.type === "folder") {
      const hit = findNodeById(c, nodeId);
      if (hit) return hit;
    }
  }
  return null;
}

// Flatten all bookmarks for the workspace list view.
function flattenBookmarks(node, path, out) {
  for (const c of node.children || []) {
    if (c.type === "bookmark") {
      out.push({
        bookmark_id: c.bookmark_id,
        node_id: c.node_id,
        title: c.title,
        url: c.url,
        folder_path: path,
        add_date: c.add_date,
        last_modified: c.last_modified,
        icon: c.icon,
        description: c.description,
      });
    } else if (c.type === "folder") {
      const next = path ? `${path}/${c.title}` : c.title;
      flattenBookmarks(c, next, out);
    }
  }
}

// --- Tree rendering --------------------------------------------------------

function renderTree(container, root, pane = "A") {
  container.innerHTML = "";
  const ul = document.createElement("ul");
  for (const child of root.children || []) {
    child.parentPath = "";
    if (child.type === "folder") {
      ul.appendChild(renderTreeNode(child, pane));
    } else {
      ul.appendChild(renderTreeBm(child, pane));
    }
  }
  container.appendChild(ul);
}

function renderTreeNode(node, pane = "A") {
  const isB = pane === "B";
  const openSet = isB ? state.openFoldersB : state.openFolders;
  const selectedPath = isB ? state.selectedFolderB : state.selectedFolder;

  const frag = treeNodeTpl.content.cloneNode(true);
  const li = frag.querySelector(".tree-node");
  const row = frag.querySelector(".tree-row");
  const toggle = frag.querySelector(".tree-toggle");
  const folderIcon = frag.querySelector(".tree-folder-icon");
  const label = frag.querySelector(".tree-label");
  const count = frag.querySelector(".tree-count");
  const childUl = frag.querySelector(".tree-children");

  label.textContent = node.title;
  count.textContent = countBookmarks(node).toLocaleString();

  const open = openSet.has(node.path);
  childUl.classList.toggle("hidden", !open);
  toggle.textContent = open ? "▾" : "▸";
  folderIcon.textContent = open ? "📂" : "📁";

  row.dataset.path = node.path;
  row.dataset.pane = pane;
  if (selectedPath === node.path) row.classList.add("selected");

  toggle.addEventListener("click", (ev) => {
    ev.stopPropagation();
    if (openSet.has(node.path)) openSet.delete(node.path);
    else openSet.add(node.path);
    persistOpenFolders();
    renderAllTrees();
  });

  // フォルダアイコンクリックでも開閉
  folderIcon.addEventListener("click", (ev) => {
    ev.stopPropagation();
    if (openSet.has(node.path)) openSet.delete(node.path);
    else openSet.add(node.path);
    persistOpenFolders();
    renderAllTrees();
  });

  row.addEventListener("click", () => {
    if (isB) {
      state.selectedFolderB = node.path;
    } else {
      state.selectedFolder = node.path;
    }
    persistOpenFolders();
    renderAllTrees();
    // In dual mode, clicking Tree B does not change the workspace list
    if (!isB) renderList();
  });

  attachFolderContextMenu(row, node);

  // --- Folder row as a draggable + drop target -----------------------------
  // The folder is itself a Node (with node_id). Dragging it reorders the
  // folder among its siblings (which can be other folders OR bookmarks);
  // dropping onto it moves the dragged item INTO the folder as a child.
  row.draggable = true;
  row.dataset.nodeId = node.node_id;
  row.addEventListener("dragstart", (e) => {
    e.stopPropagation();
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("application/nbm-node", node.node_id);
    window._nbmDragNodeId = node.node_id;
    row.classList.add("dragging");
  });
  row.addEventListener("dragend", () => {
    row.classList.remove("dragging");
    row.classList.remove("drag-over", "drag-over-top", "drag-over-bottom");
    window._nbmDragNodeId = null;
  });

  row.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    // Three drop zones: top third = insert before, bottom third = insert after,
    // middle = drop INTO the folder. This is the standard tree DnD UX.
    const rect = row.getBoundingClientRect();
    const y = e.clientY - rect.top;
    row.classList.remove("drag-over", "drag-over-top", "drag-over-bottom");
    if (y < rect.height * 0.25) row.classList.add("drag-over-top");
    else if (y > rect.height * 0.75) row.classList.add("drag-over-bottom");
    else row.classList.add("drag-over");
  });
  row.addEventListener("dragleave", () => {
    row.classList.remove("drag-over", "drag-over-top", "drag-over-bottom");
  });
  row.addEventListener("drop", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    const zone = row.classList.contains("drag-over-top") ? "before"
              : row.classList.contains("drag-over-bottom") ? "after"
              : "into";
    row.classList.remove("drag-over", "drag-over-top", "drag-over-bottom");

    const srcId = e.dataTransfer.getData("application/nbm-node") ||
                  e.dataTransfer.getData("application/nbm-bookmark") ||
                  e.dataTransfer.getData("text/plain") ||
                  window._nbmDragNodeId ||
                  window._nbmDragId;
    if (!srcId || srcId === node.node_id) return;
    await dropOntoNode(srcId, node, zone);
  });

  // Render children in their server-given order (folders + bookmarks mixed).
  for (const c of node.children || []) {
    c.parentPath = node.path;
    if (c.type === "folder") {
      childUl.appendChild(renderTreeNode(c, pane));
    } else {
      childUl.appendChild(renderTreeBm(c, pane));
    }
  }
  return frag;
}

// Common "drop SRC onto DST" handler used by both tree-row and tree-bm.
// `zone` is "before" | "after" | "into" (into is folder-only).
// When multiple bookmarks are selected and srcId is one of them,
// all selected items are moved together via bulk-move.
async function dropOntoNode(srcId, dstNode, zone) {
  // Locate destination's parent and index inside that parent's children.
  const dstParentPath = dstNode.parentPath ?? "";
  const dstParent = findFolderByPath(state.treeRoot, dstParentPath);
  if (!dstParent) return toast("移動先が見つかりません", "error");

  let targetParentPath, newIndex;
  if (zone === "into" && dstNode.type === "folder") {
    targetParentPath = dstNode.path;
    newIndex = (dstNode.children || []).length;
  } else {
    targetParentPath = dstParentPath;
    const dstIdx = dstParent.children.findIndex((c) => c.node_id === dstNode.node_id);
    if (dstIdx < 0) return;
    newIndex = zone === "after" ? dstIdx + 1 : dstIdx;
    const srcIdx = dstParent.children.findIndex((c) => c.node_id === srcId);
    if (srcIdx >= 0 && srcIdx < newIndex) newIndex -= 1;
  }

  // If srcId is part of a multi-selection, bulk-move all selected items.
  const multiIds = [...state.selectedBookmarks].map((bmId) => {
    const bm = state.selectedBookmarkMap.get(bmId);
    return bm?.node_id || bmId;
  });
  const isMulti = state.selectedBookmarks.size > 1 && multiIds.includes(srcId);

  try {
    if (isMulti) {
      await api("/edit/bookmark/bulk-move", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_ids: multiIds, target_parent_path: targetParentPath }),
      });
      toast(`${multiIds.length} 件を移動しました`);
    } else {
      await api(`/edit/node/${encodeURIComponent(srcId)}/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_parent_path: targetParentPath, new_index: newIndex }),
      });
    }
    await reload();
  } catch (err) {
    toast(`移動失敗: ${err.message}`, "error");
  }
}

function renderTreeBm(node, pane) {
  // `node` is a server Node of type=bookmark. `node.parentPath` is set by
  // the caller (renderTreeNode/renderTree).
  const frag = treeBmTpl.content.cloneNode(true);
  const li = frag.querySelector(".tree-bm");
  const fav = frag.querySelector(".tree-bm-fav");
  const label = frag.querySelector(".tree-bm-label");

  fav.src = node.icon || faviconUrl(node.url);
  label.textContent = node.title || "(no title)";
  li.dataset.bmId = node.bookmark_id;
  li.dataset.nodeId = node.node_id;
  li.title = node.url;

  if (state.selectedBookmark && state.selectedBookmark.bookmark_id === node.bookmark_id) {
    li.classList.add("selected");
  }

  li.addEventListener("click", (e) => {
    const bm = {
      bookmark_id: node.bookmark_id,
      node_id: node.node_id,
      title: node.title,
      url: node.url,
      folder_path: node.parentPath || "",
      add_date: node.add_date,
      last_modified: node.last_modified,
      icon: node.icon,
      description: node.description,
    };
    if (e.ctrlKey || e.metaKey) {
      toggleBookmarkSelection(bm);
    } else if (e.shiftKey) {
      rangeSelectBookmark(bm);
    } else {
      if (state.selectedBookmark?.bookmark_id === node.bookmark_id && state.selectedBookmarks.size <= 1) {
        clearSelection();
        return;
      }
      if (pane !== "B") state.selectedFolder = node.parentPath || "";
      selectBookmark(bm);
    }
  });

  attachBookmarkContextMenu(li, node);

  li.draggable = true;
  li.addEventListener("dragstart", (e) => {
    e.stopPropagation();
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", node.node_id);
    e.dataTransfer.setData("application/nbm-node", node.node_id);
    e.dataTransfer.setData("application/nbm-bookmark", node.bookmark_id);
    window._nbmDragNodeId = node.node_id;
    window._nbmDragId = node.bookmark_id;
    li.classList.add("dragging");
  });
  li.addEventListener("dragend", () => {
    li.classList.remove("dragging", "drag-over-top", "drag-over-bottom");
    window._nbmDragNodeId = null;
    window._nbmDragId = null;
  });
  li.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const rect = li.getBoundingClientRect();
    const mid = rect.top + rect.height / 2;
    li.classList.toggle("drag-over-top",    e.clientY < mid);
    li.classList.toggle("drag-over-bottom", e.clientY >= mid);
  });
  li.addEventListener("dragleave", () => {
    li.classList.remove("drag-over-top", "drag-over-bottom");
  });
  li.addEventListener("drop", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    const dropBottom = li.classList.contains("drag-over-bottom");
    li.classList.remove("drag-over-top", "drag-over-bottom");
    const srcId = e.dataTransfer.getData("application/nbm-node") ||
                  e.dataTransfer.getData("application/nbm-bookmark") ||
                  e.dataTransfer.getData("text/plain") ||
                  window._nbmDragNodeId ||
                  window._nbmDragId;
    if (!srcId || srcId === node.node_id) return;
    await dropOntoNode(srcId, node, dropBottom ? "after" : "before");
  });

  return frag;
}

function renderAllTrees() {
  if (!state.treeRoot) return;
  renderTree(treeContainerA, state.treeRoot, "A");
  if (document.body.dataset.dual === "true") {
    renderTree(treeContainerB, state.treeRoot, "B");
  }
  treeCountEl.textContent = countBookmarks(state.treeRoot).toLocaleString();
}

// --- List rendering --------------------------------------------------------

function visibleBookmarks() {
  if (!state.treeRoot) return [];
  // Search query overrides folder selection — matches PySide6 SearchBar behaviour.
  if (state.searchQuery) {
    const tokens = state.searchQuery.toLowerCase().split(/\s+/).filter(Boolean);
    return state.bookmarks.filter((b) => {
      const hay = `${b.title} ${b.url} ${b.folder_path}`.toLowerCase();
      return tokens.every((t) => hay.includes(t));
    });
  }
  if (state.selectedFolder == null) {
    return state.bookmarks;
  }
  const node = findFolderByPath(state.treeRoot, state.selectedFolder);
  if (!node) return [];
  const out = [];
  flattenBookmarks(node, state.selectedFolder || "", out);
  return out;
}

// favicon: sessionStorage でホスト単位にキャッシュ
// プライバシーモード時は Google s2 を呼ばずローカルの汎用アイコンを返す
const FAVICON_PRIVACY_KEY = "nbm_favicon_privacy";
let _faviconPrivacy = localStorage.getItem(FAVICON_PRIVACY_KEY) === "1";

function faviconUrl(url) {
  if (_faviconPrivacy) return "";   // プライバシーモード: favicon 非表示
  try {
    const host = new URL(url).hostname;
    if (!host) return "";
    const cacheKey = "fav:" + host;
    const cached = sessionStorage.getItem(cacheKey);
    if (cached) return cached;
    const result = `https://www.google.com/s2/favicons?domain=${host}&sz=32`;
    try { sessionStorage.setItem(cacheKey, result); } catch (_) {}
    return result;
  } catch (_) {
    return "";
  }
}

function setFaviconPrivacy(on) {
  _faviconPrivacy = on;
  try { localStorage.setItem(FAVICON_PRIVACY_KEY, on ? "1" : "0"); } catch (_) {}
}

function renderList() {
  const items = visibleBookmarks();
  listContainer.innerHTML = "";
  listCountEl.textContent = items.length.toLocaleString();
  for (const bm of items) {
    listContainer.appendChild(renderListRow(bm));
    listContainer.appendChild(renderListCard(bm));
  }
  // Update Organize / Enrich scope indicators
  const f = state.selectedFolder;
  const scopeText = f ? `（${f}）` : "（全体）";
  for (const id of ["organizeScope", "enrichScope"]) {
    const el = document.getElementById(id);
    if (el) el.textContent = scopeText;
  }
}

function attachBmDragDrop(el, bm) {
  el.draggable = true;
  el.addEventListener("dragstart", (e) => {
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", bm.node_id || bm.bookmark_id);
    e.dataTransfer.setData("application/nbm-node", bm.node_id || bm.bookmark_id);
    e.dataTransfer.setData("application/nbm-bookmark", bm.bookmark_id);
    window._nbmDragNodeId = bm.node_id || bm.bookmark_id;
    window._nbmDragId = bm.bookmark_id;
    el.classList.add("dragging");
  });
  el.addEventListener("dragend", () => {
    el.classList.remove("dragging");
    window._nbmDragNodeId = null;
    window._nbmDragId = null;
  });
  el.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const rect = el.getBoundingClientRect();
    el.classList.toggle("drag-over-top",    e.clientY < rect.top + rect.height / 2);
    el.classList.toggle("drag-over-bottom", e.clientY >= rect.top + rect.height / 2);
  });
  el.addEventListener("dragleave", () => el.classList.remove("drag-over-top", "drag-over-bottom"));
  el.addEventListener("drop", (e) => handleBmDrop(e, bm, el));
}

function renderListRow(bm) {
  const frag = listRowTpl.content.cloneNode(true);
  const li = frag.querySelector(".bm-row");
  const fav = frag.querySelector(".bm-favicon");
  const title = frag.querySelector(".bm-title");
  const urlEl = frag.querySelector(".bm-url");
  fav.src = bm.icon || faviconUrl(bm.url);
  const needle = state.searchQuery || "";
  title.innerHTML = highlightMatch(bm.title || "(no title)", needle);
  urlEl.innerHTML = highlightMatch(bm.url, needle);
  li.dataset.bmId = bm.bookmark_id;
  li.dataset.folderPath = bm.folder_path;
  if (state.selectedBookmark && state.selectedBookmark.bookmark_id === bm.bookmark_id) {
    li.classList.add("selected");
  }
  li.addEventListener("click", (e) => {
    if (e.ctrlKey || e.metaKey) {
      toggleBookmarkSelection(bm);
    } else if (e.shiftKey) {
      rangeSelectBookmark(bm);
    } else {
      if (state.selectedBookmark?.bookmark_id === bm.bookmark_id && state.selectedBookmarks.size <= 1) clearSelection();
      else selectBookmark(bm);
    }
  });
  attachBmDragDrop(li, bm);
  return frag;
}

function renderListCard(bm) {
  const frag = listCardTpl.content.cloneNode(true);
  const li = frag.querySelector(".bm-card");
  const fav = frag.querySelector(".bm-card-favicon");
  const title = frag.querySelector(".bm-card-title");
  const urlEl = frag.querySelector(".bm-card-url");
  fav.src = bm.icon || faviconUrl(bm.url);
  title.textContent = bm.title || "(no title)";
  urlEl.textContent = bm.url;
  li.dataset.bmId = bm.bookmark_id;
  if (state.selectedBookmark && state.selectedBookmark.bookmark_id === bm.bookmark_id) {
    li.classList.add("selected");
  }
  li.addEventListener("click", (e) => {
    if (e.ctrlKey || e.metaKey) {
      toggleBookmarkSelection(bm);
    } else if (e.shiftKey) {
      rangeSelectBookmark(bm);
    } else {
      if (state.selectedBookmark?.bookmark_id === bm.bookmark_id && state.selectedBookmarks.size <= 1) clearSelection();
      else selectBookmark(bm);
    }
  });
  attachBmDragDrop(li, bm);
  return frag;
}

// List/card row drop handler — translate the drop into a node move so it
// shares the same reorder semantics as the tree.
async function handleBmDrop(e, dstBm, el) {
  e.preventDefault();
  const dropBottom = el.classList.contains("drag-over-bottom");
  el.classList.remove("drag-over-top", "drag-over-bottom");
  const srcId = e.dataTransfer.getData("application/nbm-node") ||
                e.dataTransfer.getData("application/nbm-bookmark") ||
                e.dataTransfer.getData("text/plain") ||
                window._nbmDragNodeId ||
                window._nbmDragId;
  if (!srcId) return;
  // Find the destination's actual Node in the tree (we need node_id + parentPath).
  const dstNode = findNodeById(state.treeRoot, dstBm.node_id || dstBm.bookmark_id);
  if (!dstNode) return;
  // findNodeById doesn't set parentPath; recompute from folder_path.
  dstNode.parentPath = dstBm.folder_path || "";
  if (srcId === dstNode.node_id) return;
  await dropOntoNode(srcId, dstNode, dropBottom ? "after" : "before");
}

// Single-select (no modifier). Clears multi-selection.
function selectBookmark(bm) {
  state.selectedBookmark = bm;
  state.selectedBookmarks.clear();
  state.selectedBookmarkMap.clear();
  if (bm) {
    state.selectedBookmarks.add(bm.bookmark_id);
    state.selectedBookmarkMap.set(bm.bookmark_id, bm);
    state.lastClickedBmId = bm.bookmark_id;
  } else {
    state.lastClickedBmId = null;
  }
  syncSelectionUI();
  renderDetail();
}

// Ctrl+Click: toggle one item without clearing others.
function toggleBookmarkSelection(bm) {
  if (state.selectedBookmarks.has(bm.bookmark_id)) {
    state.selectedBookmarks.delete(bm.bookmark_id);
    state.selectedBookmarkMap.delete(bm.bookmark_id);
    // Update primary selection to another item or null
    state.selectedBookmark = state.selectedBookmarks.size > 0
      ? state.selectedBookmarkMap.values().next().value
      : null;
  } else {
    state.selectedBookmarks.add(bm.bookmark_id);
    state.selectedBookmarkMap.set(bm.bookmark_id, bm);
    state.selectedBookmark = bm;
  }
  state.lastClickedBmId = bm.bookmark_id;
  syncSelectionUI();
  renderDetail();
}

// Shift+Click: select range from lastClickedBmId to bm in the visible list.
function rangeSelectBookmark(bm) {
  const visible = visibleBookmarks();
  const ids = visible.map((b) => b.bookmark_id);
  const anchorIdx = ids.indexOf(state.lastClickedBmId);
  const targetIdx = ids.indexOf(bm.bookmark_id);
  if (anchorIdx === -1 || targetIdx === -1) {
    selectBookmark(bm);
    return;
  }
  const lo = Math.min(anchorIdx, targetIdx);
  const hi = Math.max(anchorIdx, targetIdx);
  // Keep existing selection outside the range; add everything in [lo, hi].
  for (let i = lo; i <= hi; i++) {
    const b = visible[i];
    state.selectedBookmarks.add(b.bookmark_id);
    state.selectedBookmarkMap.set(b.bookmark_id, b);
  }
  state.selectedBookmark = bm;
  syncSelectionUI();
  renderDetail();
}

function clearSelection() {
  selectBookmark(null);
}

// Apply .selected / .multi-selected CSS classes to all rendered rows.
function syncSelectionUI() {
  const single = state.selectedBookmark?.bookmark_id;
  const multi  = state.selectedBookmarks;

  for (const el of listContainer.children) {
    const id = el.dataset?.bmId;
    el.classList.toggle("selected",       id === single && multi.size <= 1);
    el.classList.toggle("multi-selected", multi.size > 1 && multi.has(id));
  }
  for (const el of document.querySelectorAll(".tree-bm")) {
    const id = el.dataset?.bmId;
    el.classList.toggle("selected",       id === single && multi.size <= 1);
    el.classList.toggle("multi-selected", multi.size > 1 && multi.has(id));
  }
}

// --- Detail ----------------------------------------------------------------

function renderDetail() {
  const bm = state.selectedBookmark;
  if (!bm) {
    detailEmpty.classList.remove("hidden");
    detailCard.classList.add("hidden");
    return;
  }
  detailEmpty.classList.add("hidden");
  detailCard.classList.remove("hidden");

  detailTitle.value = bm.title || "";
  detailFetchedTitle.textContent = "";
  detailFetchedTitle.classList.add("hidden");

  detailUrl.value = bm.url || "";
  const meta = [];
  if (bm.folder_path) meta.push(`📂 ${bm.folder_path}`);
  if (bm.add_date) meta.push(`追加: ${formatTimestamp(bm.add_date)}`);
  if (bm.last_modified) meta.push(`更新: ${formatTimestamp(bm.last_modified)}`);
  detailMeta.textContent = meta.join("  ·  ");
  detailDescription.value = bm.description || "";

  loadTagsFor(bm.bookmark_id).catch(() => {
    detailTags.textContent = "(取得失敗)";
  });

  // DB の fetched_title を非同期で取得して専用行に表示
  if (bm.bookmark_id) {
    api(`/meta/${encodeURIComponent(bm.bookmark_id)}`)
      .then((data) => {
        if (state.selectedBookmark?.bookmark_id !== bm.bookmark_id) return;
        if (data.fetched_title) {
          detailFetchedTitle.textContent = data.fetched_title;
          detailFetchedTitle.classList.remove("hidden");
        } else {
          detailFetchedTitle.classList.add("hidden");
        }
      })
      .catch(() => {});
  }
}

// Save changed fields when focus leaves or Enter is pressed (single-line only).
// Called once at boot; event listeners persist across bookmark selections.
function setupDetailInlineEdit() {
  async function saveDetail() {
    const bm = state.selectedBookmark;
    if (!bm) return;
    const newTitle = detailTitle.value.trim();
    const newUrl   = detailUrl.value.trim();
    const newDesc  = detailDescription.value;
    // Skip if nothing changed
    if (newTitle === (bm.title || "") && newUrl === (bm.url || "") && newDesc === (bm.description || "")) return;
    try {
      await api(`/edit/bookmark/${encodeURIComponent(bm.bookmark_id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: newTitle, url: newUrl, description: newDesc }),
      });
      bm.title = newTitle;
      bm.url   = newUrl;
      bm.description = newDesc;
      await reload();
      toast("更新しました");
    } catch (e) {
      toast(`更新失敗: ${e.message}`, "error");
    }
  }

  // blur = focus-out → save
  detailTitle.addEventListener("blur", saveDetail);
  detailUrl.addEventListener("blur", saveDetail);
  detailDescription.addEventListener("blur", saveDetail);

  // Enter on single-line fields → blur to trigger save
  detailTitle.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); detailTitle.blur(); } });
  detailUrl.addEventListener("keydown",   (e) => { if (e.key === "Enter") { e.preventDefault(); detailUrl.blur(); } });
  // Escape → revert
  function revert(el, getter) {
    el.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { el.value = getter(); el.blur(); }
    });
  }
  revert(detailTitle,       () => state.selectedBookmark?.title || "");
  revert(detailUrl,         () => state.selectedBookmark?.url   || "");
  revert(detailDescription, () => state.selectedBookmark?.description || "");
}

function formatTimestamp(unixStr) {
  const n = parseInt(unixStr, 10);
  if (!Number.isFinite(n) || n <= 0) return unixStr;
  return new Date(n * 1000).toISOString().slice(0, 19).replace("T", " ");
}

const TAG_SOURCE_COLORS = {
  rule:   "#7C9EFF",  // accent blue
  manual: "#5BCEA8",  // teal
  ai:     "#a78fd6",  // muted purple
  scrape: "#c4956a",  // muted amber
};

async function loadTagsFor(id) {
  if (!id) { renderTagChips([]); return; }
  try {
    const data = await api(`/tags/${encodeURIComponent(id)}`);
    renderTagChips(data.tags || []);
  } catch (_) {
    detailTags.innerHTML = '<span style="color:#f38ba8">(取得失敗)</span>';
  }
}

function renderTagChips(tags) {
  if (!tags.length) { detailTags.innerHTML = '<span style="color:#585b70">(なし)</span>'; return; }
  detailTags.innerHTML = tags.map((t) => {
    const color = TAG_SOURCE_COLORS[t.source] || "#cdd6f4";
    const conf = t.confidence ? ` ${Math.round(t.confidence * 100)}%` : "";
    return `<span class="tag-chip" style="background:${color}22;border:1px solid ${color};color:${color}" title="${t.source}${conf}">${escHtml(t.name)}</span>`;
  }).join(" ");
}

// --- Search highlight ------------------------------------------------------

function highlightMatch(text, query) {
  if (!query) return escHtml(text);
  const tokens = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!tokens.length) return escHtml(text);
  // Build one regex from all tokens.
  const pattern = tokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  const re = new RegExp(`(${pattern})`, "gi");
  return text.replace(re, (m) => `<mark class="search-hl">${escHtml(m)}</mark>`);
}

// --- Search ----------------------------------------------------------------

let searchDebounce = null;
searchInput.addEventListener("input", () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => {
    state.searchQuery = searchInput.value.trim();
    renderList();
  }, 120);
});
$("searchClearBtn").addEventListener("click", () => {
  searchInput.value = "";
  state.searchQuery = "";
  renderList();
});

// --- View toggle / dual-pane / tree expand-all -----------------------------

function setViewMode(mode) {
  document.body.dataset.view = mode;
  viewChip.textContent = `表示: ${mode === "card" ? "Card" : "List"}`;
  viewListBtn.setAttribute("aria-pressed", mode === "list");
  viewCardBtn.setAttribute("aria-pressed", mode === "card");
  try { localStorage.setItem(VIEW_STORAGE_KEY, mode); } catch (_) {}
}
viewListBtn.addEventListener("click", () => setViewMode("list"));
viewCardBtn.addEventListener("click", () => setViewMode("card"));

function setDualPane(on) {
  document.body.dataset.dual = on ? "true" : "false";
  dualPaneBtn.setAttribute("aria-pressed", on);
  $("treeALabel").textContent = on ? "Tree A" : "Tree";
  try { localStorage.setItem(DUAL_STORAGE_KEY, on ? "1" : "0"); } catch (_) {}
  renderAllTrees();
}
dualPaneBtn.addEventListener("click", () => {
  setDualPane(document.body.dataset.dual !== "true");
});

const faviconPrivacyBtn = $("faviconPrivacyBtn");
faviconPrivacyBtn.setAttribute("aria-pressed", _faviconPrivacy);
faviconPrivacyBtn.addEventListener("click", () => {
  setFaviconPrivacy(!_faviconPrivacy);
  faviconPrivacyBtn.setAttribute("aria-pressed", _faviconPrivacy);
  renderList(); // favicon 表示を即時更新
});

$("treeExpandAllBtn").addEventListener("click", () => {
  if (!state.treeRoot) return;
  const visit = (n) => {
    if (n.type !== "folder") return;
    if (n.path) state.openFolders.add(n.path);
    (n.children || []).forEach(visit);
  };
  (state.treeRoot.children || []).forEach(visit);
  persistOpenFolders();
  renderAllTrees();
});
$("treeCollapseAllBtn").addEventListener("click", () => {
  state.openFolders.clear();
  persistOpenFolders();
  renderAllTrees();
});

// Tree B controls (shown only in dual-pane mode)
document.addEventListener("click", (e) => {
  if (e.target.id === "treeBExpandAllBtn") {
    if (!state.treeRoot) return;
    const visit = (n) => {
      if (n.type !== "folder") return;
      if (n.path) state.openFoldersB.add(n.path);
      (n.children || []).forEach(visit);
    };
    (state.treeRoot.children || []).forEach(visit);
    persistOpenFolders();
    renderAllTrees();
  } else if (e.target.id === "treeBCollapseAllBtn") {
    state.openFoldersB.clear();
    persistOpenFolders();
    renderAllTrees();
  }
});

function persistOpenFolders() {
  try {
    localStorage.setItem(TREE_OPEN_STORAGE_KEY, JSON.stringify([...state.openFolders]));
    localStorage.setItem(TREE_OPEN_STORAGE_KEY + "_B", JSON.stringify([...state.openFoldersB]));
  } catch (_) {}
}

// --- Splitter drag (flex-basis resize) -------------------------------------

function initSplitters() {
  document.querySelectorAll(".splitter-h, .splitter-v").forEach((sp) => {
    sp.addEventListener("pointerdown", (e) => {
      sp.setPointerCapture(e.pointerId);
      const target = sp.dataset.target;
      const isH = sp.classList.contains("splitter-h"); // horizontal = resizes left/right siblings

      // Identify the two flex siblings around this splitter
      const prev = sp.previousElementSibling;
      const next = sp.nextElementSibling;
      if (!prev || !next) return;

      const startPos = isH ? e.clientX : e.clientY;
      const startPrev = isH ? prev.getBoundingClientRect().width : prev.getBoundingClientRect().height;
      const startNext = isH ? next.getBoundingClientRect().width : next.getBoundingClientRect().height;

      const onMove = (ev) => {
        const delta = (isH ? ev.clientX : ev.clientY) - startPos;
        const newPrev = startPrev + delta;
        const newNext = startNext - delta;
        if (newPrev > 80 && newNext > 80) {
          prev.style.flex = `0 0 ${newPrev}px`;
          next.style.flex = `0 0 ${newNext}px`;
        }
      };
      const onUp = () => {
        sp.releasePointerCapture(e.pointerId);
        sp.removeEventListener("pointermove", onMove);
        sp.removeEventListener("pointerup", onUp);
        saveSplit();
      };
      sp.addEventListener("pointermove", onMove);
      sp.addEventListener("pointerup", onUp);
    });
  });
}

function saveSplit() {
  try {
    const colLeft   = document.querySelector(".col-left");
    const paneUpper = document.querySelector(".pane-upper");
    const paneTreeA = document.querySelector("#paneTreeA");
    const paneTreB  = document.querySelector("#paneTreB");
    const actions   = document.querySelector(".pane-actions");
    localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify({
      colLeft:   colLeft?.style.flex   || "",
      actions:   actions?.style.flex   || "",
      paneUpper: paneUpper?.style.flex || "",
      paneList:  document.querySelector(".pane-list")?.style.flex || "",
      paneTreeA: paneTreeA?.style.flex || "",
      paneTreB:  paneTreB?.style.flex  || "",
    }));
  } catch (_) {}
}

function restoreSplit() {
  try {
    const raw = localStorage.getItem(SPLIT_STORAGE_KEY);
    if (!raw) return;
    const v = JSON.parse(raw);
    const set = (sel, val) => { if (val) { const el = document.querySelector(sel); if (el) el.style.flex = val; } };
    set(".col-left",   v.colLeft);
    set(".pane-actions", v.actions);
    set(".pane-upper", v.paneUpper);
    set(".pane-list",  v.paneList);
    set("#paneTreeA",  v.paneTreeA);
    set("#paneTreB",   v.paneTreB);
  } catch (_) {}
}

initSplitters();

// リスト・ツリーの余白クリックで選択解除
// e.target が直接コンテナ（ul/div）の場合だけ解除（子要素クリックは各自のハンドラで処理）
listContainer.addEventListener("click", (e) => {
  if (e.target === listContainer) clearSelection();
});
treeContainerA.addEventListener("click", (e) => {
  if (e.target === treeContainerA || e.target.tagName === "UL") clearSelection();
});
treeContainerB.addEventListener("click", (e) => {
  if (e.target === treeContainerB || e.target.tagName === "UL") clearSelection();
});

// --- Reload helper ----------------------------------------------------------

/// 開いたファイルが前回保存時と同一（パス＋内容ハッシュ一致）のとき、
/// 前回取得したタイトル・タグを引き継ぐか確認する。NO ならサーバ側で破棄。
/// resumeAvailable=false のときは何もしない（別ファイル＝サーバが既に破棄済み）。
async function maybePromptResume(resumeAvailable, fileName) {
  if (!resumeAvailable) return;
  const name = fileName ? `「${fileName.split(/[\\/]/).pop()}」` : "このファイル";
  const keep = await confirmDialog(
    `${name} の前回の続きを編集しますか?\n\n` +
    `「引き継ぐ」: 前回取得したタイトル・タグを引き継ぎます。\n` +
    `「破棄」: 取得済みのタイトル・タグを破棄して新規に始めます。`,
    { okLabel: "引き継ぐ", cancelLabel: "破棄" }
  );
  try {
    await api("/session/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keep }),
    });
  } catch (e) {
    toast(`セッション復元に失敗: ${e.message}`, "error");
  }
}

// window.confirm() はTauriのWebViewでは動作しない（常に未表示でfalse扱い）ため、
// 自前のモーダルダイアログで代替する。
function confirmDialog(message, { okLabel = "OK", cancelLabel = "キャンセル" } = {}) {
  return new Promise((resolve) => {
    const div = document.createElement("div");
    div.style.cssText =
      "position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:10000;display:flex;align-items:center;justify-content:center";
    div.innerHTML = `
      <div style="background:#1e1e2e;border-radius:12px;padding:24px;min-width:360px;max-width:520px;display:flex;flex-direction:column;gap:16px">
        <div style="color:#cdd6f4;white-space:pre-wrap;line-height:1.6">${message.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</div>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button id="confirm-dialog-cancel" style="padding:8px 16px;border-radius:6px;border:1px solid #585b70;background:transparent;color:#cdd6f4;cursor:pointer">${cancelLabel}</button>
          <button id="confirm-dialog-ok" style="padding:8px 16px;border-radius:6px;border:none;background:#89b4fa;color:#1e1e2e;cursor:pointer;font-weight:600">${okLabel}</button>
        </div>
      </div>`;
    document.body.appendChild(div);
    const cleanup = (result) => {
      div.remove();
      resolve(result);
    };
    div.querySelector("#confirm-dialog-ok").addEventListener("click", () => cleanup(true));
    div.querySelector("#confirm-dialog-cancel").addEventListener("click", () => cleanup(false));
  });
}

async function reload() {
  try {
    // /tree gives us the canonical Node tree with folder/bookmark order intact.
    // /bookmarks is still useful for the search/list view (flat, with folder_path).
    const [treeData, listData] = await Promise.all([
      api("/tree"),
      api("/bookmarks"),
    ]);
    state.treeRoot = annotateTree(treeData);
    state.bookmarks = listData.items || [];
    // 選択中のブックマークは古いオブジェクト参照のままなので、
    // 再読み込み後のデータで差し替えて詳細パネルにも反映する。
    if (state.selectedBookmark) {
      const fresh = state.bookmarks.find((b) => b.bookmark_id === state.selectedBookmark.bookmark_id);
      state.selectedBookmark = fresh || null;
      renderDetail();
    }
    renderAllTrees();
    renderList();
    treeCountEl.textContent = state.bookmarks.length.toLocaleString();
    const label = listData.dirty ? `${listData.count.toLocaleString()} 件 ●` : `${listData.count.toLocaleString()} 件`;
    setStatus(label);
    document.title = listData.dirty ? "NeoBookMarkManager ●" : "NeoBookMarkManager";
  } catch (e) {
    toast(`リロード失敗: ${e.message}`, "error");
  }
}

// --- Operation panel buttons -----------------------------------------------

document.querySelectorAll("[data-cmd]").forEach((btn) => {
  btn.addEventListener("click", () => handleCommand(btn.dataset.cmd));
});

function handleCommand(cmd) {
  // Dispatch — async commands are fire-and-forget (errors shown as toast).
  switch (cmd) {
    case "file.open":           return cmdOpen();
    case "file.save":           return cmdSave();
    case "file.save-as":        return cmdSaveAs();
    case "edit.new-folder":     return cmdNewFolder();
    case "edit.new-bookmark":   return cmdNewBookmark();
    case "edit.delete":         return cmdDeleteSelected();
    case "edit.move-up":        return cmdMoveUp();
    case "edit.undo":           return cmdUndo();
    case "edit.redo":           return cmdRedo();
    case "detail.edit":         return cmdDetailEdit();
    case "detail.edit-tags":    return cmdDetailEditTags();
    case "detail.copy-url":     return cmdCopyUrl();
    case "detail.move":         return cmdDetailMove();
    case "detail.delete":       return cmdDetailDelete();
    case "backup.restore":      return cmdBackupRestore();
    case "backup.undo-latest":      return cmdBackupUndoLatest();
    case "organize.dedupe":         return cmdOrganizeDedupe();
    case "organize.merge-dup-folders": return cmdOrganizeMergeDupFolders();
    case "organize.sort-by-domain":   return cmdOrganizeSortByDomain();
    case "organize.consolidate-domain": return cmdOrganizeConsolidateDomain();
    case "organize.domain-keyword":   return cmdOrganizeDomainKeyword();
    case "network.fix-titles":   return cmdNetworkFixTitles();
    case "network.fetch-preview": return cmdNetworkFetchPreview();
    case "network.proxy-check":  return cmdNetworkProxyCheck();
    case "network.link-check":   return cmdLinkCheck();
    case "autotag.offline":      return cmdAutotagOffline();
    case "ai.classify":
    case "classify.ai":          return cmdAiClassify();
    case "ai.settings":          return cmdAiSettings();
    default:
      toast(`未実装: ${cmd}`, "error");
  }
}

// --- Command implementations -----------------------------------------------

function cmdCopyUrl() {
  const bm = state.selectedBookmark;
  if (!bm) return toast("ブックマークを選択してください", "error");
  navigator.clipboard?.writeText(bm.url);
  toast("URL をコピーしました");
}

async function cmdUndo() {
  try {
    const res = await api("/edit/undo", { method: "POST" });
    await reload();
    updateUndoRedoButtons(res.undo_count, res.redo_count);
    toast(`Undo (残り ${res.undo_count} 件)`);
  } catch (e) {
    toast("これ以上 Undo できません", "error");
  }
}

async function cmdRedo() {
  try {
    const res = await api("/edit/redo", { method: "POST" });
    await reload();
    updateUndoRedoButtons(res.undo_count, res.redo_count);
    toast(`Redo (残り ${res.redo_count} 件)`);
  } catch (e) {
    toast("これ以上 Redo できません", "error");
  }
}

function updateUndoRedoButtons(undoCount, redoCount) {
  const btnUndo = document.getElementById("btnUndo");
  const btnRedo = document.getElementById("btnRedo");
  if (btnUndo) {
    btnUndo.disabled = undoCount === 0;
    btnUndo.textContent = `↩ Undo${undoCount > 0 ? ` (${undoCount})` : ""}`;
  }
  if (btnRedo) {
    btnRedo.disabled = redoCount === 0;
    btnRedo.textContent = `↪ Redo${redoCount > 0 ? ` (${redoCount})` : ""}`;
  }
}

async function cmdSave() {
  try {
    const res = await api("/edit/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    toast(`保存しました → ${res.saved_to}`);
    await reload();
  } catch (e) {
    toast(`保存失敗: ${e.message}`, "error");
  }
}

function getTauriDialog() {
  const t = window.__TAURI__;
  if (!t) throw new Error("Tauri API が見つかりません");
  // Tauri v2: withGlobalTauri=true の場合 window.__TAURI__.dialog に展開される
  return t.dialog || t["tauri-plugin-dialog"];
}

async function cmdOpen() {
  try {
    const { open } = getTauriDialog();
    const selected = await open({
      title: "ブックマークファイルを開く",
      filters: [{ name: "HTML", extensions: ["html", "htm"] }],
      multiple: false,
    });
    const path = typeof selected === "string" ? selected : null;
    if (!path) return;
    const opened = await api("/file/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path }) });
    await maybePromptResume(opened.resume_available, opened.path);
    await reload();
    toast("ファイルを開きました");
  } catch (e) {
    toast(`開けませんでした: ${e.message}`, "error");
  }
}

async function cmdSaveAs() {
  try {
    const { save } = getTauriDialog();
    const path = await save({
      title: "名前を付けて保存",
      filters: [{ name: "HTML", extensions: ["html", "htm"] }],
    });
    if (!path) return;
    const res = await api("/edit/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file_path: path }) });
    toast(`保存しました → ${res.saved_to}`);
    await reload();
  } catch (e) {
    toast(`保存失敗: ${e.message}`, "error");
  }
}

async function cmdNewFolder() {
  const parent = state.selectedFolder ?? "";
  const title = prompt(`新しいフォルダ名を入力 (作成先: /${parent || "ルート"})`);
  if (!title) return;
  try {
    await api("/edit/folder/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parent_path: parent, title }),
    });
    await reload();
    toast(`フォルダを追加しました: ${title}`);
  } catch (e) {
    toast(`フォルダ追加失敗: ${e.message}`, "error");
  }
}

async function cmdNewBookmark() {
  const folder = state.selectedFolder ?? "";
  const url = prompt(`URL を入力 (追加先: /${folder || "ルート"})`);
  if (!url) return;
  const title = prompt("タイトルを入力 (空欄で URL を使用)") || "";
  try {
    const res = await api("/edit/bookmark/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_path: folder, title, url }),
    });
    await reload();
    toast(`ブックマークを追加しました (id: ${res.bookmark_id.slice(0, 8)}…)`);
  } catch (e) {
    toast(`追加失敗: ${e.message}`, "error");
  }
}

async function cmdDeleteSelected() {
  const bm = state.selectedBookmark;
  if (!bm) return toast("ブックマークを選択してください", "error");
  if (!(await confirmDialog(`「${bm.title}」を削除しますか?`))) return;
  try {
    await api(`/edit/bookmark/${encodeURIComponent(bm.bookmark_id)}`, { method: "DELETE" });
    state.selectedBookmark = null;
    renderDetail();
    await reload();
    toast("削除しました");
  } catch (e) {
    toast(`削除失敗: ${e.message}`, "error");
  }
}

async function cmdMoveUp() {
  const bm = state.selectedBookmark;
  if (!bm) return toast("ブックマークを選択してください", "error");
  try {
    await api(`/edit/bookmark/${encodeURIComponent(bm.bookmark_id)}/move-up`, { method: "POST" });
    await reload();
    toast("上に移動しました");
  } catch (e) {
    toast(`移動失敗: ${e.message}`, "error");
  }
}

function cmdDetailEdit() {
  if (!state.selectedBookmark) return toast("ブックマークを選択してください", "error");
  // Inline editing — just focus the title field in the detail pane.
  detailTitle.focus();
  detailTitle.select();
}

async function cmdDetailEditTags() {
  const bm = state.selectedBookmark;
  if (!bm) return toast("ブックマークを選択してください", "error");
  const current = detailTags.textContent.replace(/\s*\[.*?\]/g, "").replace("(なし)", "").trim();
  const raw = prompt("タグをカンマ区切りで入力:", current);
  if (raw === null) return;
  const tags = raw.split(",").map((t) => t.trim()).filter(Boolean);
  try {
    await api("/tags/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bookmark_id: bm.bookmark_id, tags, source: "manual" }),
    });
    await loadTagsFor(bm.bookmark_id);
    toast("タグを更新しました");
  } catch (e) {
    toast(`タグ更新失敗: ${e.message}`, "error");
  }
}

async function cmdDetailMove() {
  const bm = state.selectedBookmark;
  if (!bm) return toast("ブックマークを選択してください", "error");
  const dest = prompt(`移動先フォルダパスを入力 (現在: ${bm.folder_path || "ルート"})`);
  if (dest === null) return;
  try {
    await api(`/edit/bookmark/${encodeURIComponent(bm.bookmark_id)}/move`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_path: dest }),
    });
    await reload();
    toast(`移動しました → ${dest || "ルート"}`);
  } catch (e) {
    toast(`移動失敗: ${e.message}`, "error");
  }
}

async function cmdDetailDelete() {
  const bm = state.selectedBookmark;
  if (!bm) return toast("ブックマークを選択してください", "error");
  if (!(await confirmDialog(`「${bm.title}」を削除しますか?`))) return;
  try {
    await api(`/edit/bookmark/${encodeURIComponent(bm.bookmark_id)}`, { method: "DELETE" });
    state.selectedBookmark = null;
    renderDetail();
    await reload();
    toast("削除しました");
  } catch (e) {
    toast(`削除失敗: ${e.message}`, "error");
  }
}

async function cmdBackupRestore() {
  try {
    const listData = await api("/backup/list");
    if (!listData.backups || !listData.backups.length) {
      return toast("バックアップがありません", "error");
    }
    const choices = listData.backups.slice(0, 10).join("\n");
    const chosen = prompt(`復元するバックアップを選択してください:\n${choices}`);
    if (!chosen) return;
    if (!(await confirmDialog(`「${chosen}」から復元しますか? 現在の変更は失われます。`))) return;
    await api("/backup/restore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup_dir: chosen }),
    });
    await reload();
    toast("バックアップから復元しました");
  } catch (e) {
    toast(`復元失敗: ${e.message}`, "error");
  }
}

// --- SSE progress helper ---------------------------------------------------

// 現在実行中の SSE abort controller (1つのみ)
let _sseAbort = null;

function runSseCommand(endpoint, body, label) {
  return new Promise((resolve) => {
    const ids = body.bookmark_ids || [];
    if (ids.length === 0) {
      toast("対象ブックマークを選択してください", "error");
      resolve();
      return;
    }

    // 前の SSE が走っていればキャンセル
    if (_sseAbort) _sseAbort.abort();
    const abortCtrl = new AbortController();
    _sseAbort = abortCtrl;

    // 中止ボタン付きステータス表示
    setStatus(`${label}: 0/${ids.length} 処理中…`);
    showSseProgress(label, ids.length, abortCtrl);

    fetch(API_BASE + endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: abortCtrl.signal,
    }).then((res) => {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let finished = false;
      const pump = () => reader.read().then(({ value, done: d }) => {
        if (d) { finished = true; hideSseProgress(); reload().then(resolve); return; }
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          try {
            const p = JSON.parse(line.slice(5).trim());
            if (p.status === "done") {
              finished = true;
              hideSseProgress();
              reload().then(resolve);
              return;
            }
            setStatus(`${label}: ${p.processed}/${p.total}`);
            updateSseProgress(p.processed, p.total, p.bookmark_title);
            // 処理完了したブックマークが Detail に表示中なら即時更新
            if (p.bookmark_id && state.selectedBookmark?.bookmark_id === p.bookmark_id) {
              renderDetail();
            }
          } catch (_) {}
        }
        if (!finished) pump();
      }).catch((e) => {
        hideSseProgress();
        if (e.name !== "AbortError") toast(`${label} 失敗: ${e.message}`, "error");
        resolve();
      });
      pump();
    }).catch((e) => {
      hideSseProgress();
      if (e.name !== "AbortError") toast(`${label} 失敗: ${e.message}`, "error");
      resolve();
    });
  });
}

// SSE 進捗バー (画面下部に固定表示)
let _sseProgressEl = null;
// 処理済み件数ごとのタイムスタンプ (ETA算出用、直近5件で計算)
let _sseTimestamps = [];
let _sseEtaText = "";

const SSE_BAR_BLOCKS = 20;

// ■/□ によるテキスト進捗バー
function textProgressBar(processed, total) {
  if (!total) return "□".repeat(SSE_BAR_BLOCKS);
  const filled = Math.min(SSE_BAR_BLOCKS, Math.round((processed / total) * SSE_BAR_BLOCKS));
  return "■".repeat(filled) + "□".repeat(SSE_BAR_BLOCKS - filled);
}

function formatDuration(ms) {
  const totalSec = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}分${s}秒` : `${s}秒`;
}

function showSseProgress(label, total, abortCtrl) {
  hideSseProgress();
  _sseTimestamps = [Date.now()];
  _sseEtaText = "";
  const el = document.createElement("div");
  el.id = "sse-progress";
  el.innerHTML = `
    <span id="sse-progress-label">${label}: 0 / ${total}</span>
    <span id="sse-progress-bar-text" style="font-family:monospace;letter-spacing:-1px">${textProgressBar(0, total)}</span>
    <span id="sse-progress-eta" style="color:#a6adc8;font-size:11px"></span>
    <span id="sse-progress-title" style="color:#a6adc8;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1 1 0;min-width:0"></span>
    <div class="sse-progress-bar-outer"><div class="sse-progress-bar-inner" id="sse-bar" style="width:0%"></div></div>
    <button class="danger-btn" id="sse-cancel-btn" style="height:24px;font-size:11px;padding:0 8px">中止</button>
  `;
  el.dataset.label = label;
  document.body.appendChild(el);
  _sseProgressEl = el;
  document.getElementById("sse-cancel-btn").addEventListener("click", () => {
    abortCtrl.abort();
    hideSseProgress();
    setStatus("中止しました");
    toast("処理を中止しました");
  });
}

function updateSseProgress(processed, total, currentTitle) {
  if (!_sseProgressEl) return;
  _sseTimestamps.push(Date.now());

  // 直近5件の処理時間をもとに、5件ごとに残り時間を再計算する
  if (processed > 0 && processed % 5 === 0 && _sseTimestamps.length > 5) {
    const recent = _sseTimestamps.slice(-6); // 5件分の区間 = 6点
    const elapsed = recent[recent.length - 1] - recent[0];
    const perItem = elapsed / 5;
    const remaining = Math.max(0, total - processed);
    _sseEtaText = remaining > 0 ? `残り約 ${formatDuration(perItem * remaining)}` : "";
  }
  if (processed >= total) _sseEtaText = "";

  const label = _sseProgressEl.querySelector("#sse-progress-label");
  const barText = _sseProgressEl.querySelector("#sse-progress-bar-text");
  const eta = _sseProgressEl.querySelector("#sse-progress-eta");
  const bar = _sseProgressEl.querySelector("#sse-bar");
  const titleEl = _sseProgressEl.querySelector("#sse-progress-title");
  if (label) label.textContent = `${_sseProgressEl.dataset.label || "処理"}: ${processed} / ${total}`;
  if (barText) barText.textContent = textProgressBar(processed, total);
  if (eta) eta.textContent = _sseEtaText;
  if (bar && total > 0) bar.style.width = `${Math.round(processed / total * 100)}%`;
  if (titleEl && currentTitle) titleEl.textContent = `— ${currentTitle}`;
}

function hideSseProgress() {
  if (_sseProgressEl) { _sseProgressEl.remove(); _sseProgressEl = null; }
  _sseAbort = null;
  _sseTimestamps = [];
  _sseEtaText = "";
}

async function cmdNetworkFixTitles() {
  if (!state.bookmarks.length) return toast("ブックマークがありません", "error");
  const ids = await pickScopeTarget("URLからタイトル取得 — 対象を選択");
  if (!ids) return; // cancelled
  if (!ids.length) return toast("対象ブックマークがありません", "error");
  if (!(await confirmDialog(`${ids.length} 件のブックマークのタイトルをURLから更新しますか?`))) return;
  await runSseCommand("/network/fix-titles", { bookmark_ids: ids }, "タイトル更新");
  toast("タイトル更新完了");
}

async function cmdNetworkFetchPreview() {
  if (!state.bookmarks.length) return toast("ブックマークがありません", "error");
  const ids = await pickScopeTarget("説明文を取得 — 対象を選択");
  if (!ids) return; // cancelled
  if (!ids.length) return toast("対象ブックマークがありません", "error");
  await runSseCommand("/network/fetch-preview", { bookmark_ids: ids }, "説明文取得");
  toast("説明文の取得が完了しました");
}

async function cmdNetworkProxyCheck() {
  try {
    const res = await api("/network/proxy-check");
    if (!res.configured) {
      toast("Proxy 設定なし (config.ini [Proxy].url を設定してください)");
    } else {
      toast(`Proxy ${res.url}: ${res.message}`);
    }
  } catch (e) {
    toast(`Proxy 確認失敗: ${e.message}`, "error");
  }
}

async function cmdLinkCheck() {
  const folder = state.selectedFolder ?? "";
  const scope = folder ? `「${folder}」以下` : "全体";
  const ids = state.bookmarks
    .filter((b) => {
      const fp = b.folder_path || "";
      return folder === "" || fp === folder || fp.startsWith(folder + "/");
    })
    .map((b) => b.bookmark_id).filter(Boolean);
  if (!ids.length) return toast(`${scope} にブックマークがありません`, "error");
  if (!(await confirmDialog(`${scope} の ${ids.length} 件のリンクをチェックします。\n(除外パターンに一致するURLはスキップ)\nよろしいですか?`))) return;

  // dead/timeout の結果を蓄積してモーダル表示
  const deadList = [];
  const label = "リンクチェック";

  await new Promise((resolve) => {
    if (_sseAbort) _sseAbort.abort();
    const abortCtrl = new AbortController();
    _sseAbort = abortCtrl;
    setStatus(`${label}: 0/${ids.length} チェック中…`);
    showSseProgress(label, ids.length, abortCtrl);

    fetch(API_BASE + "/network/link-check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bookmark_ids: ids }),
      signal: abortCtrl.signal,
    }).then((res) => {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      const pump = () => reader.read().then(({ value, done: d }) => {
        if (d) { hideSseProgress(); resolve(); return; }
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n"); buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          try {
            const p = JSON.parse(line.slice(5).trim());
            if (p.result === "done") { hideSseProgress(); resolve(); return; }
            setStatus(`${label}: ${p.processed}/${p.total}`);
            updateSseProgress(p.processed, p.total, p.bookmark_title);
            if (p.result === "dead" || p.result === "timeout") {
              deadList.push(p);
            }
          } catch (_) {}
        }
        pump();
      }).catch((e) => {
        hideSseProgress();
        if (e.name !== "AbortError") toast(`${label} 失敗: ${e.message}`, "error");
        resolve();
      });
      pump();
    }).catch((e) => {
      hideSseProgress();
      if (e.name !== "AbortError") toast(`${label} 失敗: ${e.message}`, "error");
      resolve();
    });
  });

  // 結果モーダル表示
  showLinkCheckResults(deadList, ids.length);
}

function showLinkCheckResults(deadList, total) {
  if (deadList.length === 0) {
    toast(`リンクチェック完了 — 切れリンクなし (${total} 件チェック済)`);
    return;
  }
  const modal = document.createElement("div");
  modal.style.cssText =
    "position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:9999;display:flex;align-items:center;justify-content:center";
  modal.innerHTML = `
    <div style="background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:24px;min-width:520px;max-width:700px;max-height:80vh;display:flex;flex-direction:column;gap:12px">
      <h2 style="margin:0;color:var(--danger);font-size:15px">⚠ リンク切れ ${deadList.length} 件 / ${total} 件チェック</h2>
      <div id="lc-list" style="overflow-y:auto;flex:1;display:flex;flex-direction:column;gap:6px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button id="lc-close" class="ghost-btn">閉じる</button>
      </div>
    </div>`;
  document.body.appendChild(modal);

  const listEl = modal.querySelector("#lc-list");
  for (const p of deadList) {
    const badge = p.result === "timeout" ? "⏱ タイムアウト" : `❌ ${p.detail || "切れ"}`;
    const row = document.createElement("div");
    row.style.cssText =
      "padding:8px 10px;background:var(--surface-2);border-radius:6px;border-left:3px solid var(--danger);display:flex;flex-direction:column;gap:3px";
    row.innerHTML = `
      <div style="font-size:13px;color:var(--text-hi);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(p.bookmark_title || "(no title)")}</div>
      <div style="display:flex;align-items:center;gap:8px">
        <span style="font-size:11px;color:var(--danger);white-space:nowrap">${badge}</span>
        <a href="${escHtml(p.url || "")}" style="font-size:11px;color:var(--text-mid);overflow:hidden;text-overflow:ellipsis;white-space:nowrap" target="_blank" rel="noreferrer">${escHtml(p.url || "")}</a>
      </div>`;
    listEl.appendChild(row);
  }

  modal.querySelector("#lc-close").addEventListener("click", () => modal.remove());
  modal.addEventListener("click", (e) => { if (e.target === modal) modal.remove(); });
}

async function cmdAutotagOffline() {
  if (!state.bookmarks.length) return toast("ブックマークがありません", "error");
  const ids = await pickScopeTarget("自動タグ付け — 対象を選択");
  if (!ids) return; // cancelled
  if (!ids.length) return toast("対象ブックマークがありません", "error");

  // 前提: 分類材料（タイトル・説明文）が揃っていないと良いタグが付かない。
  // 選択された対象に未取得があれば警告するが、ブロックはせず実行可否を委ねる。
  const idSet = new Set(ids);
  const targets = state.bookmarks.filter((b) => idSet.has(b.bookmark_id));
  const noTitle = targets.filter((b) => !(b.title || "").trim()).length;
  const noDesc = targets.filter((b) => !(b.description || "").trim()).length;
  if (noTitle > 0 || noDesc > 0) {
    const missing = [];
    if (noTitle > 0) missing.push(`・タイトル未取得 ${noTitle} 件 →「URLからタイトル取得」を先に実行すると精度が上がります`);
    if (noDesc > 0)  missing.push(`・説明文未取得 ${noDesc} 件 →「説明文を取得」を先に実行すると精度が上がります`);
    if (!(await confirmDialog(
      `タグ付けの分類材料が一部不足しています。\n\n${missing.join("\n")}\n\nこのまま ${ids.length} 件にタグ付けを実行しますか?`
    ))) return;
  }

  await runSseCommand("/autotag/local", { bookmark_ids: ids }, "自動タグ付け");
  toast("自動タグ付け完了");
}

async function cmdOrganizeDedupe() {
  const folder = state.selectedFolder ?? "";
  if (!(await confirmDialog(`「${folder || "ルート"}」フォルダの重複ブックマークを削除しますか?`))) return;
  try {
    const res = await api("/organize/dedupe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_path: folder }),
    });
    await reload();
    toast(`重複削除: ${res.count} 件削除しました`);
  } catch (e) {
    toast(`重複削除失敗: ${e.message}`, "error");
  }
}

async function cmdOrganizeMergeDupFolders() {
  const parent = state.selectedFolder ?? "";
  if (!(await confirmDialog(`「${parent || "ルート"}」配下の重複フォルダを統合しますか?`))) return;
  try {
    const res = await api("/organize/merge-duplicate-folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parent_path: parent }),
    });
    await reload();
    toast(`重複フォルダ統合: ${res.count} 個統合しました`);
  } catch (e) {
    toast(`統合失敗: ${e.message}`, "error");
  }
}

async function cmdOrganizeSortByDomain() {
  const folder = state.selectedFolder ?? "";
  const label = folder || "ルート";
  if (!(await confirmDialog(`「${label}」内のブックマークをドメイン順に並び替えますか?`))) return;
  try {
    const res = await api("/organize/sort-by-domain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_path: folder }),
    });
    await reload();
    toast(`ドメイン順ソート: ${res.count} 件を並び替えました`);
  } catch (e) {
    toast(`ソート失敗: ${e.message}`, "error");
  }
}

async function cmdOrganizeConsolidateDomain() {
  const folder = state.selectedFolder ?? "";
  const scope = folder ? `「${folder}」以下` : "全体";

  const scopedBms = state.bookmarks.filter((b) => {
    const fp = b.folder_path || "";
    return folder === "" || fp === folder || fp.startsWith(folder + "/");
  });
  if (!scopedBms.length) return toast(`${scope} にブックマークがありません`, "error");

  const domainMap = new Map();
  for (const b of scopedBms) {
    try {
      const host = new URL(b.url).hostname.replace(/^www\./, "");
      domainMap.set(host, (domainMap.get(host) || 0) + 1);
    } catch (_) {}
  }
  const stats = [...domainMap.entries()]
    .map(([domain, count]) => ({ domain, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 40);

  if (!stats.length) return toast("ドメイン情報がありません");

  const modal = document.createElement("div");
  modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9999;display:flex;align-items:center;justify-content:center";
  modal.innerHTML = `
    <div style="background:#1e1e2e;border-radius:12px;padding:24px;min-width:480px;max-width:640px;max-height:80vh;display:flex;flex-direction:column;gap:12px">
      <h2 style="margin:0;color:#cdd6f4;font-size:16px">ドメイン統合 — ${escHtml(scope)}</h2>
      <p style="margin:0;color:#a6adc8;font-size:12px">チェックしたドメインのブックマークはドメイン名のフォルダに移動されます。</p>
      <div style="display:flex;gap:8px">
        <button id="dm-all"  style="font-size:11px;padding:2px 8px;border-radius:4px;border:1px solid #585b70;background:transparent;color:#cdd6f4;cursor:pointer">全選択</button>
        <button id="dm-none" style="font-size:11px;padding:2px 8px;border-radius:4px;border:1px solid #585b70;background:transparent;color:#cdd6f4;cursor:pointer">全解除</button>
      </div>
      <div id="dm-list" style="overflow-y:auto;flex:1;display:flex;flex-direction:column;gap:4px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button id="dm-cancel" style="padding:8px 16px;border-radius:6px;border:1px solid #585b70;background:transparent;color:#cdd6f4;cursor:pointer">キャンセル</button>
        <button id="dm-apply"  style="padding:8px 16px;border-radius:6px;border:none;background:#89b4fa;color:#1e1e2e;cursor:pointer;font-weight:600">統合する</button>
      </div>
    </div>`;
  document.body.appendChild(modal);

  const listEl = modal.querySelector("#dm-list");
  stats.forEach(({ domain, count }) => {
    const row = document.createElement("label");
    row.style.cssText = "display:flex;align-items:center;gap:10px;padding:6px 10px;background:#313244;border-radius:6px;cursor:pointer";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.dataset.domain = domain;
    cb.checked = false;
    row.appendChild(cb);
    row.insertAdjacentHTML("beforeend",
      `<span style="flex:1;color:#cdd6f4;font-size:13px">${escHtml(domain)}</span>
       <span style="color:#a6e3a1;font-size:12px">${count} 件</span>`);
    listEl.appendChild(row);
  });

  modal.querySelector("#dm-all").addEventListener("click",  () => listEl.querySelectorAll("input").forEach((c) => c.checked = true));
  modal.querySelector("#dm-none").addEventListener("click", () => listEl.querySelectorAll("input").forEach((c) => c.checked = false));
  modal.querySelector("#dm-cancel").addEventListener("click", () => modal.remove());

  modal.querySelector("#dm-apply").addEventListener("click", async () => {
    const checked = Array.from(listEl.querySelectorAll("input:checked")).map((c) => c.dataset.domain);
    if (!checked.length) return toast("ドメインを1つ以上選択してください");
    modal.remove();
    let total = 0, failed = 0;
    for (const domain of checked) {
      try {
        const res = await api("/organize/consolidate-by-domain", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ domain, target_folder: domain, scope_path: folder || null }),
        });
        total += res.count || 0;
      } catch (_) { failed++; }
    }
    await reload();
    if (failed) toast(`統合完了: ${total} 件移動 (${failed} ドメイン失敗)`, "error");
    else toast(`ドメイン統合: ${total} 件を ${checked.length} フォルダに移動しました`);
  });
}

// --- Domain × Keyword振り分け -----------------------------------------------

async function cmdOrganizeDomainKeyword() {
  const folder = state.selectedFolder ?? "";
  const scope  = folder ? `「${folder}」以下` : "全体";

  const scopedBms = state.bookmarks.filter((b) => {
    const fp = b.folder_path || "";
    return folder === "" || fp === folder || fp.startsWith(folder + "/");
  });
  if (!scopedBms.length) return toast(`${scope} にブックマークがありません`, "error");

  const domainMap = new Map();
  for (const b of scopedBms) {
    try {
      const host = new URL(b.url).hostname.replace(/^www\./, "");
      domainMap.set(host, (domainMap.get(host) || 0) + 1);
    } catch (_) {}
  }
  const domainStats = [...domainMap.entries()]
    .map(([domain, count]) => ({ domain, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 40);
  if (!domainStats.length) return toast("ドメイン情報がありません");

  // ウィザード状態
  // confirmed: Map<domain, [{keyword, target}]>  — ドメイン個別ルール
  const confirmed = new Map();
  // selected: チェックで束ねた複数ドメイン。空なら単一クリック動作。
  const selected = new Set();
  // sharedRules: 選択した複数ドメインに共通適用するルール群
  let sharedRules = [];
  let activeDomain = null; // 右ペインに今表示しているドメイン（単一クリック時）

  // ── カラーパレット ────────────────────────────────────────────
  const C = { bg1:"#111111", bg2:"#161616", bg3:"#1c1c1c", border:"#262626",
               accent:"#7c9eff", hi:"#e8e8e8", mid:"#9a9a9a", lo:"#555555", green:"#5bcea8" };

  // ── モーダル骨格: 左ペイン（ドメイン一覧）+ 右ペイン（キーワード入力） ──
  const modal = document.createElement("div");
  modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:9999;display:flex;align-items:center;justify-content:center;font-family:inherit";

  modal.innerHTML = `
    <div style="background:${C.bg1};border:1px solid ${C.border};border-radius:10px;width:760px;max-width:96vw;height:700px;max-height:90vh;display:flex;flex-direction:column;overflow:hidden">
      <div style="padding:16px 20px 12px;border-bottom:1px solid ${C.border};display:flex;align-items:baseline;gap:10px;flex-shrink:0">
        <span style="color:${C.hi};font-size:15px;font-weight:600">ドメイン×キーワード振り分け</span>
        <span style="color:${C.lo};font-size:11px">${escHtml(scope)}</span>
      </div>
      <div style="display:flex;flex:1;min-height:0;overflow:hidden">
        <div id="dkw-left" style="width:220px;flex:0 0 220px;border-right:1px solid ${C.border};overflow-y:auto;padding:6px 0"></div>
        <div id="dkw-right" style="flex:1;display:flex;flex-direction:column;overflow:hidden">
          <p style="margin:12px 18px;color:${C.lo};font-size:12px">← ドメインを選択してください</p>
        </div>
      </div>
      <div style="padding:10px 20px;border-top:1px solid ${C.border};display:flex;gap:8px;justify-content:flex-end;flex-shrink:0">
        <button id="dkw-cancel" style="padding:6px 16px;border-radius:5px;border:1px solid ${C.border};background:transparent;color:${C.mid};cursor:pointer">キャンセル</button>
        <button id="dkw-apply"  style="padding:6px 16px;border-radius:5px;border:none;background:${C.accent};color:#050810;cursor:pointer;font-weight:600">実行する</button>
      </div>
    </div>`;
  document.body.appendChild(modal);

  const leftEl  = modal.querySelector("#dkw-left");
  const rightEl = modal.querySelector("#dkw-right");

  // ── 左ペイン: ドメイン行を描画 ────────────────────────────────
  function renderLeft() {
    leftEl.innerHTML = "";

    // ヘッダー: 全選択/解除
    const hdr = document.createElement("div");
    hdr.style.cssText = `display:flex;align-items:center;gap:6px;padding:4px 14px 8px;border-bottom:1px solid ${C.border};margin-bottom:4px`;
    hdr.innerHTML = `<span style="flex:1;color:${C.lo};font-size:10px;text-transform:uppercase;letter-spacing:.05em">ドメイン（複数選択可）</span>`;
    const selAll = document.createElement("button");
    selAll.style.cssText = `background:none;border:none;color:${C.accent};font-size:10px;cursor:pointer;padding:0`;
    selAll.textContent = selected.size ? "解除" : "全選択";
    selAll.addEventListener("click", () => {
      if (selected.size) selected.clear();
      else domainStats.forEach(d => selected.add(d.domain));
      renderLeft();
      renderRightForSelection();
    });
    hdr.appendChild(selAll);
    leftEl.appendChild(hdr);

    domainStats.forEach(({ domain, count }) => {
      const hasRules = confirmed.has(domain) && confirmed.get(domain).some(r => r.keyword.trim());
      const isChecked = selected.has(domain);
      const isActive = !selected.size && domain === activeDomain;

      const row = document.createElement("div");
      row.style.cssText = `display:flex;align-items:center;gap:8px;padding:7px 14px;cursor:pointer;
        background:${isActive || isChecked ? C.bg3 : "transparent"};
        border-left:2px solid ${isChecked ? C.green : (isActive ? C.accent : "transparent")};
        transition:background 80ms`;

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = isChecked;
      cb.style.cssText = "flex:0 0 auto;cursor:pointer;accent-color:#5bcea8;margin:0";
      cb.addEventListener("click", (e) => {
        e.stopPropagation();
        if (cb.checked) selected.add(domain); else selected.delete(domain);
        renderLeft();
        renderRightForSelection();
      });

      const label = document.createElement("span");
      label.style.cssText = `flex:1;color:${isActive ? C.hi : C.mid};font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap`;
      label.title = domain;
      label.textContent = domain;

      const cnt = document.createElement("span");
      cnt.style.cssText = `color:${C.green};font-size:10px`;
      cnt.textContent = count;

      row.append(cb, label, cnt);
      if (hasRules) {
        const chk = document.createElement("span");
        chk.style.cssText = `color:${C.accent};font-size:10px`;
        chk.title = "個別ルール設定済み";
        chk.textContent = "✓";
        row.appendChild(chk);
      }

      // ラベル部クリックで単一表示（チェックとは独立）
      row.addEventListener("click", () => {
        selected.clear();
        renderRight(domain);
        renderLeft();
      });
      leftEl.appendChild(row);
    });
  }

  // 選択集合に応じて右ペインを更新（選択ありなら共通ルール編集、なしなら案内）
  function renderRightForSelection() {
    if (selected.size) renderRightShared();
    else if (activeDomain) renderRight(activeDomain);
    else {
      rightEl.innerHTML = `<p style="margin:12px 18px;color:${C.lo};font-size:12px">← ドメインを選択してください</p>`;
    }
  }

  // ── 単一ドメイン: 個別ルール編集 ─────────────────────────────
  function renderRight(domain) {
    activeDomain = domain;
    selected.clear();
    if (!confirmed.has(domain)) confirmed.set(domain, []);
    const rules = confirmed.get(domain);
    const { count } = domainStats.find(d => d.domain === domain);
    const bms = scopedBms.filter(b => bmDomain(b) === domain);
    renderRulePane({
      rules,
      bms,
      headLabel: `${escHtml(domain)} <span style="color:${C.green};font-size:11px">${count} 件</span>`,
      fallbackText: () => rules.some(r => r.keyword.trim())
        ? `↳ 上記以外 → ${domain}/` : `（キーワードなし）→ すべて ${domain}/ へ`,
      showSourceDomain: false,
    });
  }

  // ── 複数ドメイン: 共通ルール編集 ─────────────────────────────
  function renderRightShared() {
    activeDomain = null;
    const doms = [...selected];
    const bms = scopedBms.filter(b => selected.has(bmDomain(b)));
    const totalCount = doms.reduce(
      (s, d) => s + (domainStats.find(x => x.domain === d)?.count || 0), 0);
    renderRulePane({
      rules: sharedRules,
      bms,
      headLabel: `${doms.length} ドメイン共通 <span style="color:${C.green};font-size:11px">${totalCount} 件</span>`,
      fallbackText: () => sharedRules.some(r => r.keyword.trim())
        ? `↳ 上記以外 → 各ドメイン名/` : `（キーワードなし）→ 各ドメイン名/ へ`,
      showSourceDomain: true,
    });
  }

  // ── 共通描画コア ──────────────────────────────────────────────
  function renderRulePane({ rules, bms, headLabel, fallbackText, showSourceDomain }) {
    renderLeft();
    rightEl.innerHTML = "";
    rightEl.style.cssText = "flex:1;display:flex;flex-direction:column;overflow:hidden;gap:0";

    const topEl = document.createElement("div");
    topEl.style.cssText = "padding:16px 18px 12px;display:flex;flex-direction:column;gap:8px;flex:0 0 auto;max-height:240px;overflow-y:auto";

    const domHead = document.createElement("div");
    domHead.style.cssText = `display:flex;align-items:baseline;gap:8px;color:${C.hi};font-size:14px;font-weight:600`;
    domHead.innerHTML = headLabel;
    topEl.appendChild(domHead);

    const rulesEl = document.createElement("div");
    rulesEl.style.cssText = "display:flex;flex-direction:column;gap:5px";
    topEl.appendChild(rulesEl);
    rightEl.appendChild(topEl);

    const sep = document.createElement("div");
    sep.style.cssText = `border-top:1px solid ${C.border};margin:0 18px`;
    rightEl.appendChild(sep);

    const bottomWrap = document.createElement("div");
    bottomWrap.style.cssText = "flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden";

    const titleHdr = document.createElement("div");
    titleHdr.style.cssText = `padding:7px 18px 4px;color:${C.lo};font-size:10px;letter-spacing:.05em;text-transform:uppercase`;
    titleHdr.textContent = `タイトル一覧（${bms.length}件）— クリックでキーワード欄に貼り付け`;
    bottomWrap.appendChild(titleHdr);

    const titleList = document.createElement("div");
    titleList.style.cssText = "overflow-y:auto;flex:1;padding:0 18px 12px;display:flex;flex-direction:column;gap:2px";

    bms.forEach(bm => {
      const item = document.createElement("div");
      item.style.cssText = `flex:0 0 auto;padding:4px 8px;border-radius:4px;font-size:12px;line-height:1.4;color:${C.mid};cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border:1px solid transparent;transition:background 60ms`;
      const labelText = bm.title || bm.url;
      if (showSourceDomain) {
        item.innerHTML = `<span style="color:${C.lo};font-size:10px">[${escHtml(bmDomain(bm))}]</span> ${escHtml(labelText)}`;
      } else {
        item.textContent = labelText;
      }
      item.title = labelText;

      item.addEventListener("mouseenter", () => {
        item.style.background = C.bg3;
        item.style.borderColor = C.border;
        item.style.color = C.hi;
      });
      item.addEventListener("mouseleave", () => {
        item.style.background = "";
        item.style.borderColor = "transparent";
        item.style.color = item.dataset.matched ? C.accent : C.mid;
      });

      item.addEventListener("click", () => {
        const focused = rulesEl.querySelector("input.kw-inp:focus");
        if (focused) {
          focused.value = bm.title || "";
          focused.dispatchEvent(new Event("input"));
        } else {
          rules.push({ keyword: bm.title || "", target: "" });
          refreshRules();
        }
        highlightTitles();
      });

      item.dataset.title = (bm.title || "").toLowerCase();
      titleList.appendChild(item);
    });
    bottomWrap.appendChild(titleList);
    rightEl.appendChild(bottomWrap);

    function highlightTitles() {
      const kwds = rules.map(r => r.keyword.trim().toLowerCase()).filter(Boolean);
      titleList.querySelectorAll(":scope > div").forEach(item => {
        const t = item.dataset.title || "";
        const matched = kwds.some(k => k && t.includes(k));
        item.dataset.matched = matched ? "1" : "";
        item.style.color = matched ? C.accent : C.mid;
      });
    }

    function refreshRules() {
      rulesEl.innerHTML = "";
      rules.forEach((rule, i) => {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:5px";

        const kwInp = document.createElement("input");
        kwInp.className = "kw-inp";
        kwInp.style.cssText = `flex:1;background:${C.bg3};border:1px solid ${C.border};border-radius:4px;color:${C.hi};font-size:12px;padding:5px 8px;outline:none;font-family:inherit`;
        kwInp.placeholder = "キーワード";
        kwInp.value = rule.keyword;
        kwInp.addEventListener("input", () => { rule.keyword = kwInp.value; refreshFallback(); highlightTitles(); });

        const arrEl = document.createElement("span");
        arrEl.style.cssText = `color:${C.lo};font-size:12px;flex:0 0 auto`;
        arrEl.textContent = "→";

        const tgtInp = document.createElement("input");
        tgtInp.style.cssText = `flex:1;background:${C.bg3};border:1px solid ${C.border};border-radius:4px;color:${C.accent};font-size:12px;padding:5px 8px;outline:none;font-family:inherit`;
        tgtInp.placeholder = "フォルダ名（省略=KW名）";
        tgtInp.value = rule.target;
        tgtInp.addEventListener("input", () => { rule.target = tgtInp.value; });

        const delBtn = document.createElement("button");
        delBtn.style.cssText = `color:${C.lo};background:none;border:none;font-size:14px;cursor:pointer;padding:0 2px;flex:0 0 auto`;
        delBtn.textContent = "✕";
        delBtn.addEventListener("click", () => { rules.splice(i, 1); refreshRules(); highlightTitles(); });

        row.append(kwInp, arrEl, tgtInp, delBtn);
        rulesEl.appendChild(row);
      });

      const fb = document.createElement("div");
      fb.id = "dkw-fb";
      fb.style.cssText = `font-size:11px;color:${C.lo};padding:1px 0`;
      rulesEl.appendChild(fb);
      refreshFallback();

      const addBtn = document.createElement("button");
      addBtn.style.cssText = `font-size:11px;padding:3px 10px;border-radius:4px;border:1px solid ${C.border};background:transparent;color:${C.accent};cursor:pointer;margin-top:2px`;
      addBtn.textContent = "+ キーワード追加";
      addBtn.addEventListener("click", () => {
        rules.push({ keyword: "", target: "" });
        refreshRules();
        rulesEl.querySelector(".kw-inp")?.focus();
      });
      rulesEl.appendChild(addBtn);
    }

    function refreshFallback() {
      const el = rightEl.querySelector("#dkw-fb");
      if (el) el.textContent = fallbackText();
    }

    refreshRules();
    highlightTitles();
  }

  // ブックマークのドメイン抽出ヘルパ
  function bmDomain(b) {
    try { return new URL(b.url).hostname.replace(/^www\./, ""); }
    catch (_) { return ""; }
  }

  // 初期描画: 左ペインのみ
  renderLeft();

  modal.querySelector("#dkw-cancel").addEventListener("click", () => modal.remove());

  modal.querySelector("#dkw-apply").addEventListener("click", async () => {
    // 各ドメインの最終ルールを構築:
    //   共通ルール(sharedRules, 選択中ドメインに展開) ＋ 個別ルール(confirmed)
    const perDomain = new Map(); // domain -> [{keyword, target}]
    const addRules = (domain, rules) => {
      const list = perDomain.get(domain) || [];
      for (const r of rules) if (r.keyword.trim()) list.push(r);
      perDomain.set(domain, list);
    };
    // 選択ドメインに共通ルールを展開
    if (selected.size && sharedRules.some(r => r.keyword.trim())) {
      for (const domain of selected) addRules(domain, sharedRules);
    }
    // 個別ルール
    for (const [domain, rules] of confirmed.entries()) addRules(domain, rules);

    const targets = [...perDomain.entries()].filter(([, rules]) => rules.length > 0);
    if (!targets.length) return toast("キーワードを1つ以上設定してください");
    modal.remove();

    const calls = [];
    for (const [domain, rules] of targets) {
      // ルールごとのターゲットフォルダ名（「それ以外」呼び出しが
      // これらを丸ごと飲み込んでしまわないよう除外リストとして渡す）
      const ruleTargetNames = rules.map(r => (r.target.trim() || r.keyword.trim()));
      for (const rule of rules) {
        calls.push({ domain, keyword: rule.keyword.trim(),
                     target_folder: rule.target.trim() || rule.keyword.trim(),
                     excludeTargetNames: [] });
      }
      // 「それ以外」: ドメイン名フォルダへ。同ドメインの既存ルールフォルダは除外。
      calls.push({ domain, keyword: null, target_folder: domain, excludeTargetNames: ruleTargetNames });
    }

    let total = 0, failed = 0;
    for (const call of calls) {
      try {
        const res = await api("/organize/consolidate-by-domain", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ domain: call.domain, target_folder: call.target_folder,
                                 keyword: call.keyword, scope_path: folder || null,
                                 exclude_target_names: call.excludeTargetNames }),
        });
        total += res.count || 0;
      } catch (_) { failed++; }
    }
    await reload();
    if (failed) toast(`振り分け完了: ${total} 件移動 (${failed} 件失敗)`, "error");
    else toast(`振り分け完了: ${total} 件を移動しました`);
  });
}

async function cmdBackupUndoLatest() {
  if (!(await confirmDialog("直前のバックアップに戻しますか? 現在の変更は失われます。"))) return;
  try {
    await api("/backup/undo-latest", { method: "POST" });
    await reload();
    toast("直前バックアップに戻しました");
  } catch (e) {
    toast(`復元失敗: ${e.message}`, "error");
  }
}

// --- AI Settings -----------------------------------------------------------

/// 設定モーダル: APIキーをUIから登録 + 現在のキー/単価ステータスを表示。
async function cmdAiSettings() {
  let status, models;
  try {
    [status, models] = await Promise.all([
      api("/config/ai-status"),
      api("/config/models").catch(() => null),
    ]);
  } catch (e) {
    return toast(`設定の読込に失敗: ${e.message}`, "error");
  }

  const C = { bg1:"#111111", bg3:"#1c1c1c", border:"#262626",
              accent:"#7c9eff", hi:"#e8e8e8", mid:"#9a9a9a", lo:"#555555",
              green:"#5bcea8", red:"#ff7c7c" };

  const keyBadge = status.api_key_set
    ? `<span style="color:${C.green}">● 設定済み (${status.api_key_source === "env" ? "環境変数" : "config.ini"})</span>`
    : `<span style="color:${C.red}">● 未設定</span>`;
  const priceBadge = status.pricing_set
    ? `<span style="color:${C.green}">● 設定済み (入力 $${status.input_cost_per_1m}/1M, 出力 $${status.output_cost_per_1m}/1M)</span>`
    : `<span style="color:${C.red}">● 未設定 — AI実行はブロックされます</span>`;
  const envNote = status.api_key_source === "env"
    ? `<div style="color:${C.lo};font-size:11px;margin-top:4px">環境変数が優先されています。ここで保存しても環境変数が使われます。</div>`
    : "";

  // モデル価格表（参照用）。models.json 由来。現在のモデルをハイライト。
  let modelTable = "";
  const catalogModels = models?.catalog?.models;
  if (Array.isArray(catalogModels) && catalogModels.length) {
    const cur = (models.current || status.model || "").toLowerCase();
    const rows = catalogModels.map((m) => {
      const isCur = (m.id || "").toLowerCase() === cur;
      const bg = isCur ? "rgba(124,158,255,.12)" : "transparent";
      const mark = isCur ? `<span style="color:${C.accent};font-weight:600">● </span>` : "";
      const rec = m.recommended ? `<span style="color:${C.green};font-size:10px;margin-left:4px">最安</span>` : "";
      return `<tr class="ais-model-row" data-model-id="${escHtml(m.id || "")}" data-input="${m.input_per_1m}" data-output="${m.output_per_1m}" style="background:${bg};cursor:pointer">
        <td style="padding:5px 8px;color:${C.hi};white-space:nowrap">${mark}${escHtml(m.label || m.id)}${rec}</td>
        <td style="padding:5px 8px;color:${C.mid};font-size:11px">${escHtml(m.note || "")}</td>
        <td style="padding:5px 8px;color:${C.green};text-align:right;white-space:nowrap">$${m.input_per_1m}</td>
        <td style="padding:5px 8px;color:${C.green};text-align:right;white-space:nowrap">$${m.output_per_1m}</td>
      </tr>`;
    }).join("");
    modelTable = `
      <div style="overflow-x:auto;border:1px solid ${C.border};border-radius:6px">
        <table style="border-collapse:collapse;width:100%;font-size:12px">
          <thead><tr style="background:${C.bg3};color:${C.mid};font-size:10px;text-transform:uppercase">
            <th style="padding:6px 8px;text-align:left">モデル</th>
            <th style="padding:6px 8px;text-align:left">特徴・ユースケース</th>
            <th style="padding:6px 8px;text-align:right">入力 /1M</th>
            <th style="padding:6px 8px;text-align:right">出力 /1M</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div style="color:${C.lo};font-size:11px;margin-top:4px">行をクリックすると下の「モデル・コスト単価」欄に反映されます。価格自体は config/models.json で更新可。</div>`;
  } else {
    modelTable = `<div style="color:${C.lo};font-size:11px">モデル一覧を読み込めませんでした（config/models.json）。</div>`;
  }

  const modal = document.createElement("div");
  modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:9999;display:flex;align-items:center;justify-content:center;font-family:inherit";
  modal.innerHTML = `
    <div style="background:${C.bg1};border:1px solid ${C.border};border-radius:10px;width:680px;max-width:94vw;max-height:88vh;overflow-y:auto;display:flex;flex-direction:column">
      <div style="padding:16px 20px 10px;border-bottom:1px solid ${C.border}">
        <div style="color:${C.hi};font-size:15px;font-weight:600">AI 設定</div>
        <div style="color:${C.lo};font-size:11px;margin-top:3px">Gemini APIキーとコスト単価</div>
      </div>
      <div style="padding:14px 20px;display:flex;flex-direction:column;gap:16px">
        <div>
          <div style="color:${C.mid};font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">APIキー ${keyBadge}</div>
          <input id="ais-key" type="password" placeholder="新しいキーを貼り付け（空欄なら変更なし）"
            style="width:100%;box-sizing:border-box;background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.hi};font-size:12px;padding:7px 9px;outline:none;font-family:inherit">
          <div style="color:${C.lo};font-size:11px;margin-top:4px">config/config.ini に保存されます（.gitignore 済み）。</div>
          ${envNote}
        </div>
        <div>
          <div style="color:${C.mid};font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">モデル・コスト単価 ${priceBadge}</div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <input id="ais-model" type="text" value="${escHtml(status.model)}" placeholder="モデルID (例: gemini-2.5-flash-lite)"
              style="flex:1 1 200px;min-width:160px;box-sizing:border-box;background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.hi};font-size:12px;padding:7px 9px;outline:none;font-family:inherit">
            <label style="display:flex;align-items:center;gap:4px;color:${C.mid};font-size:11px">
              入力$/1M
              <input id="ais-input-cost" type="number" step="0.001" min="0" value="${status.input_cost_per_1m ?? ""}"
                style="width:80px;box-sizing:border-box;background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.hi};font-size:12px;padding:7px 9px;outline:none;font-family:inherit">
            </label>
            <label style="display:flex;align-items:center;gap:4px;color:${C.mid};font-size:11px">
              出力$/1M
              <input id="ais-output-cost" type="number" step="0.001" min="0" value="${status.output_cost_per_1m ?? ""}"
                style="width:80px;box-sizing:border-box;background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.hi};font-size:12px;padding:7px 9px;outline:none;font-family:inherit">
            </label>
            <button id="ais-save-pricing" style="padding:7px 14px;border-radius:5px;border:none;background:${C.accent};color:#050810;cursor:pointer;font-weight:600;font-size:12px">単価を保存</button>
          </div>
          <div style="color:${C.lo};font-size:11px;margin-top:4px">下のモデル一覧をクリックすると自動入力されます。未設定/0のままだとAI実行はブロックされます。</div>
        </div>
        <div>
          <div style="color:${C.mid};font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">利用可能なモデルと料金</div>
          ${modelTable}
        </div>
      </div>
      <div style="padding:10px 20px;border-top:1px solid ${C.border};display:flex;gap:8px;justify-content:flex-end">
        <button id="ais-cancel" style="padding:6px 16px;border-radius:5px;border:1px solid ${C.border};background:transparent;color:${C.mid};cursor:pointer">閉じる</button>
        <button id="ais-save" style="padding:6px 16px;border-radius:5px;border:none;background:${C.accent};color:#050810;cursor:pointer;font-weight:600">キーを保存</button>
      </div>
    </div>`;
  document.body.appendChild(modal);

  const close = () => modal.remove();
  modal.querySelector("#ais-cancel").addEventListener("click", close);
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
  modal.querySelector("#ais-save").addEventListener("click", async () => {
    const key = modal.querySelector("#ais-key").value.trim();
    if (!key) return toast("キーが入力されていません", "error");
    try {
      const res = await api("/config/api-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: key }),
      });
      if (res.ok) { toast(res.message); close(); }
      else toast(res.message, "error");
    } catch (e) {
      toast(`保存失敗: ${e.message}`, "error");
    }
  });

  // モデル一覧の行クリックで モデルID / 入力 / 出力 単価を自動入力
  modal.querySelectorAll(".ais-model-row").forEach((row) => {
    row.addEventListener("click", () => {
      modal.querySelector("#ais-model").value = row.dataset.modelId || "";
      modal.querySelector("#ais-input-cost").value = row.dataset.input || "";
      modal.querySelector("#ais-output-cost").value = row.dataset.output || "";
    });
  });

  modal.querySelector("#ais-save-pricing").addEventListener("click", async () => {
    const model = modal.querySelector("#ais-model").value.trim();
    const inputCost = parseFloat(modal.querySelector("#ais-input-cost").value);
    const outputCost = parseFloat(modal.querySelector("#ais-output-cost").value);
    if (!(inputCost > 0) || !(outputCost > 0)) {
      return toast("単価は0より大きい値を入力してください", "error");
    }
    try {
      const res = await api("/config/ai-pricing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: model || null, input_cost_per_1m: inputCost, output_cost_per_1m: outputCost }),
      });
      if (res.ok) { toast(res.message); close(); }
      else toast(res.message, "error");
    } catch (e) {
      toast(`保存失敗: ${e.message}`, "error");
    }
  });
}

/// 実行前の見積もり承認モーダル。estimate を表示し、ユーザーが承認すれば true を resolve。
/// can_run が false（キー/単価未設定）なら実行ボタンを無効化する。
function openEstimateGate(est) {
  return new Promise((resolve) => {
    const C = { bg1:"#111111", bg3:"#1c1c1c", border:"#262626",
                accent:"#7c9eff", hi:"#e8e8e8", mid:"#9a9a9a", lo:"#555555",
                green:"#5bcea8", red:"#ff7c7c" };
    const c = est.cost;
    let usd = "コスト不明";
    if (c.input_cost_usd != null) {
      const low = c.input_cost_usd + (c.output_cost_usd_low || 0);
      const high = c.input_cost_usd + (c.output_cost_usd_high || 0);
      usd = `$${low.toFixed(4)} 〜 $${high.toFixed(4)}`;
    }

    const modal = document.createElement("div");
    modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:9999;display:flex;align-items:center;justify-content:center;font-family:inherit";
    const blocked = !est.can_run;
    modal.innerHTML = `
      <div style="background:${C.bg1};border:1px solid ${C.border};border-radius:10px;width:460px;max-width:94vw;display:flex;flex-direction:column;overflow:hidden">
        <div style="padding:16px 20px 10px;border-bottom:1px solid ${C.border}">
          <div style="color:${C.hi};font-size:15px;font-weight:600">送信前の見積もり確認</div>
          <div style="color:${C.lo};font-size:11px;margin-top:3px">この内容で Gemini に送信します。承認するまで送信しません。</div>
        </div>
        <div style="padding:14px 20px;display:flex;flex-direction:column;gap:8px;font-size:13px;color:${C.hi}">
          <div style="display:flex;justify-content:space-between"><span style="color:${C.mid}">対象件数</span><span>${c.items.toLocaleString()} 件</span></div>
          <div style="display:flex;justify-content:space-between"><span style="color:${C.mid}">チャンク数（API呼び出し）</span><span>${c.chunks}</span></div>
          <div style="display:flex;justify-content:space-between"><span style="color:${C.mid}">入力トークン（推定）</span><span>~${c.input_tokens_est.toLocaleString()}</span></div>
          <div style="display:flex;justify-content:space-between"><span style="color:${C.mid}">出力トークン（推定）</span><span>${c.output_tokens_low.toLocaleString()} 〜 ${c.output_tokens_high.toLocaleString()}</span></div>
          <div style="display:flex;justify-content:space-between;border-top:1px solid ${C.border};padding-top:8px;margin-top:4px"><span style="color:${C.mid}">推定コスト</span><span style="color:${C.green}">${usd}</span></div>
          ${blocked ? `<div style="color:${C.red};font-size:12px;margin-top:8px">${escHtml(est.blocked_reason || "実行できません")}</div>` : ""}
        </div>
        <div style="padding:10px 20px;border-top:1px solid ${C.border};display:flex;gap:8px;justify-content:flex-end">
          <button id="eg-cancel" style="padding:6px 16px;border-radius:5px;border:1px solid ${C.border};background:transparent;color:${C.mid};cursor:pointer">キャンセル</button>
          <button id="eg-run" ${blocked ? "disabled" : ""} style="padding:6px 16px;border-radius:5px;border:none;background:${blocked ? C.lo : C.accent};color:#050810;cursor:${blocked ? "not-allowed" : "pointer"};font-weight:600">この内容で実行</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    const done = (v) => { modal.remove(); resolve(v); };
    modal.querySelector("#eg-cancel").addEventListener("click", () => done(false));
    modal.addEventListener("click", (e) => { if (e.target === modal) done(false); });
    if (!blocked) modal.querySelector("#eg-run").addEventListener("click", () => done(true));
  });
}

// --- AI Classify -----------------------------------------------------------

/// 操作対象のブックマークidを選ばせる共通モーダル（選択中1件 / 現在フォルダ全件 / 全件）。
/// `title` は見出し（例: "AI 分類 — 対象を選択"）。キャンセル時は null を返す。
/// URLからタイトル取得・説明文取得・自動タグ付け・AI分類で共用する。
function pickScopeTarget(title) {
  return new Promise((resolve) => {
    const bm = state.selectedBookmark;
    const allIds = state.bookmarks.map((b) => b.bookmark_id).filter(Boolean);
    const folderBms = visibleBookmarks();
    const folder = state.selectedFolder;

    const options = [];
    if (bm && bm.bookmark_id) options.push({ label: `選択中の1件「${bm.title || bm.url}」`, ids: [bm.bookmark_id] });
    if (folderBms.length && folder != null) {
      const name = folder === "" ? "ルート直下" : `「${folder}」`;
      options.push({ label: `現在のフォルダ${name} 全件（${folderBms.length} 件）`, ids: folderBms.map((b) => b.bookmark_id).filter(Boolean) });
    }
    options.push({ label: `全ブックマーク（${allIds.length} 件）`, ids: allIds });

    const modal = document.createElement("div");
    modal.style.cssText =
      "position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9999;display:flex;align-items:center;justify-content:center";
    const btns = options.map((o, i) =>
      `<button data-i="${i}" style="display:block;width:100%;margin:6px 0;padding:10px 16px;border-radius:6px;border:1px solid #585b70;background:#313244;color:#cdd6f4;cursor:pointer;text-align:left;font-size:13px">${escHtml(o.label)}</button>`
    ).join("");
    modal.innerHTML = `
      <div style="background:#1e1e2e;border-radius:12px;padding:24px;min-width:400px;display:flex;flex-direction:column;gap:8px">
        <h2 style="margin:0 0 8px;color:#cdd6f4;font-size:15px">${escHtml(title)}</h2>
        ${btns}
        <button id="ct-cancel" style="margin-top:4px;padding:8px;border-radius:6px;border:1px solid #585b70;background:transparent;color:#a6adc8;cursor:pointer">キャンセル</button>
      </div>`;
    document.body.appendChild(modal);
    const close = (v) => { modal.remove(); resolve(v); };
    modal.querySelector("#ct-cancel").addEventListener("click", () => close(null));
    modal.addEventListener("click", (e) => { if (e.target === modal) close(null); });
    modal.querySelectorAll("[data-i]").forEach((btn) => {
      btn.addEventListener("click", () => close(options[parseInt(btn.dataset.i)].ids));
    });
  });
}

async function cmdAiClassify() {
  if (!state.bookmarks.length) return toast("ブックマークがありません", "error");

  // まず分類対象を選ばせる（選択フォルダだけ等）。
  const ids = await pickScopeTarget("AI 分類 — 対象を選択");
  if (!ids) return; // cancelled
  if (!ids.length) return toast("対象のブックマークがありません", "error");

  // フィールド選択 + 追加指示をモーダルで受け取る
  const opts = await openAiClassifyOptions(ids.length);
  if (!opts) return; // cancelled

  // 承認ゲート: 送信前にトークン量とコストを見積もり、ユーザーの承認を得る。
  let est;
  try {
    est = await api("/classify/estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bookmark_ids: ids, custom_prompt: opts.customPrompt || undefined, fields: opts.fields }),
    });
  } catch (e) {
    return toast(`見積もりに失敗: ${e.message}`, "error");
  }
  const approved = await openEstimateGate(est);
  if (!approved) return; // ユーザーが承認するまで Gemini に送信しない

  // 承認後にのみ実行（SSE）。
  const modal = openAiReviewModal(ids.length);

  try {
    const moves = await runAiClassifySse(ids, opts.customPrompt || undefined, modal, opts.fields);
    if (!moves || !moves.length) {
      closeAiReviewModal();
      return toast("AI からの提案がありませんでした");
    }
    populateAiReviewModal(moves);
  } catch (e) {
    closeAiReviewModal();
    toast(`AI 分類失敗: ${e.message}`, "error");
  }
}

/// AI分類の事前オプション（送信フィールド + 追加指示）をモーダルで選ばせる。
/// resolve({ fields, customPrompt }) / キャンセル時は resolve(null)。
function openAiClassifyOptions(count) {
  return new Promise((resolve) => {
    const C = { bg1:"#111111", bg3:"#1c1c1c", border:"#262626",
                accent:"#7c9eff", hi:"#e8e8e8", mid:"#9a9a9a", lo:"#555555", green:"#5bcea8" };
    const modal = document.createElement("div");
    modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:9999;display:flex;align-items:center;justify-content:center;font-family:inherit";

    const FIELDS = [
      { key: "tags",  label: "タグ",   hint: "推奨。凝縮された分類シグナル", def: true },
      { key: "title", label: "タイトル", hint: "固有名詞・語順のニュアンス", def: true },
      { key: "url",   label: "URL",    hint: "ドメイン・パスの手がかり", def: true },
      { key: "description", label: "説明文", hint: "情報量は多いがトークン消費大", def: false },
    ];

    modal.innerHTML = `
      <div style="background:${C.bg1};border:1px solid ${C.border};border-radius:10px;width:480px;max-width:94vw;display:flex;flex-direction:column;overflow:hidden">
        <div style="padding:16px 20px 10px;border-bottom:1px solid ${C.border}">
          <div style="color:${C.hi};font-size:15px;font-weight:600">AI 分類オプション</div>
          <div style="color:${C.lo};font-size:11px;margin-top:3px">${count} 件を Gemini で分類します</div>
        </div>
        <div style="padding:14px 20px;display:flex;flex-direction:column;gap:14px">
          <div>
            <div style="color:${C.mid};font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">AIに渡す情報</div>
            <div id="aico-fields" style="display:flex;flex-direction:column;gap:8px"></div>
          </div>
          <div>
            <div style="color:${C.mid};font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">追加指示（任意）</div>
            <textarea id="aico-prompt" rows="3" placeholder="例: 「仕事に役立つ情報」「あとで読む」など用途別に分けて"
              style="width:100%;box-sizing:border-box;background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.hi};font-size:12px;padding:7px 9px;outline:none;font-family:inherit;resize:vertical"></textarea>
          </div>
        </div>
        <div style="padding:10px 20px;border-top:1px solid ${C.border};display:flex;gap:8px;justify-content:flex-end">
          <button id="aico-cancel" style="padding:6px 16px;border-radius:5px;border:1px solid ${C.border};background:transparent;color:${C.mid};cursor:pointer">キャンセル</button>
          <button id="aico-run" style="padding:6px 16px;border-radius:5px;border:none;background:${C.accent};color:#050810;cursor:pointer;font-weight:600">分類する</button>
        </div>
      </div>`;
    document.body.appendChild(modal);

    const fieldsEl = modal.querySelector("#aico-fields");
    for (const f of FIELDS) {
      const row = document.createElement("label");
      row.style.cssText = "display:flex;align-items:center;gap:9px;cursor:pointer";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = f.def;
      cb.dataset.key = f.key;
      cb.style.cssText = "cursor:pointer;accent-color:#7c9eff;margin:0;flex:0 0 auto";
      const txt = document.createElement("div");
      txt.innerHTML = `<span style="color:${C.hi};font-size:13px">${f.label}</span>
        <span style="color:${C.lo};font-size:11px;margin-left:6px">${f.hint}</span>`;
      row.append(cb, txt);
      fieldsEl.appendChild(row);
    }

    const close = (result) => { modal.remove(); resolve(result); };
    modal.querySelector("#aico-cancel").addEventListener("click", () => close(null));
    modal.addEventListener("click", (e) => { if (e.target === modal) close(null); });
    modal.querySelector("#aico-run").addEventListener("click", () => {
      const fields = {};
      fieldsEl.querySelectorAll("input[type=checkbox]").forEach((cb) => {
        fields[cb.dataset.key] = cb.checked;
      });
      if (!Object.values(fields).some(Boolean)) {
        return toast("少なくとも1つの情報を選んでください", "error");
      }
      const customPrompt = modal.querySelector("#aico-prompt").value.trim();
      close({ fields, customPrompt });
    });
  });
}

function runAiClassifySse(ids, customPrompt, modal, fields) {
  return new Promise((resolve, reject) => {
    const url = new URL(API_BASE + "/classify/ai");
    const body = JSON.stringify({ bookmark_ids: ids, custom_prompt: customPrompt, fields });

    fetch(url.toString(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    }).then(async (resp) => {
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let finalMoves = null;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const json = line.slice(5).trim();
          if (!json) continue;
          try {
            const ev = JSON.parse(json);
            updateAiModalProgress(modal, ev);
            if (ev.status === "done") finalMoves = ev.chunk_moves || [];
          } catch (_) {}
        }
      }
      resolve(finalMoves);
    }).catch(reject);
  });
}

// --- AI Review Modal -------------------------------------------------------

let _aiModal = null;

function openAiReviewModal(total) {
  if (_aiModal) _aiModal.remove();
  const div = document.createElement("div");
  div.id = "ai-review-modal";
  div.style.cssText =
    "position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9999;display:flex;align-items:center;justify-content:center";
  div.innerHTML = `
    <div style="background:#1e1e2e;border-radius:12px;padding:24px;min-width:540px;max-width:760px;max-height:80vh;display:flex;flex-direction:column;gap:12px">
      <h2 style="margin:0;color:#cdd6f4">AI 分類 — ${total} 件処理中…</h2>
      <div id="ai-progress-bar" style="background:#313244;border-radius:4px;height:8px">
        <div id="ai-progress-inner" style="background:#89b4fa;height:100%;width:0;border-radius:4px;transition:width .3s"></div>
      </div>
      <div id="ai-status" style="color:#a6adc8;font-size:13px">接続中…</div>
      <div id="ai-cost-info" style="color:#a6e3a1;font-size:12px;display:none"></div>
      <div id="ai-error-log" style="display:none;flex-direction:column;gap:3px;max-height:120px;overflow-y:auto;background:#11111b;border:1px solid #45475a;border-radius:6px;padding:8px;font-size:11px;color:#f38ba8"></div>
      <div id="ai-review-list" style="overflow-y:auto;flex:1;display:none;flex-direction:column;gap:6px"></div>
      <div id="ai-modal-actions" style="display:none;gap:8px;justify-content:space-between;align-items:center">
        <label style="display:flex;align-items:center;gap:7px;cursor:pointer;color:#a6adc8;font-size:12px">
          <input type="checkbox" id="ai-prune-empty" style="cursor:pointer;accent-color:#89b4fa;margin:0">
          空になった元フォルダを削除
        </label>
        <div style="display:flex;gap:8px">
          <button id="ai-btn-cancel" style="padding:8px 16px;border-radius:6px;border:1px solid #585b70;background:transparent;color:#cdd6f4;cursor:pointer">キャンセル</button>
          <button id="ai-btn-apply-selected" style="padding:8px 16px;border-radius:6px;border:none;background:#89b4fa;color:#1e1e2e;cursor:pointer;font-weight:600">選択した提案を適用</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(div);
  _aiModal = div;
  div.querySelector("#ai-btn-cancel")?.addEventListener("click", closeAiReviewModal);
  return div;
}

function closeAiReviewModal() {
  if (_aiModal) { _aiModal.remove(); _aiModal = null; }
}

function updateAiModalProgress(modal, ev) {
  if (!modal) return;
  const pct = ev.total ? Math.round((ev.processed / ev.total) * 100) : 0;
  const inner = modal.querySelector("#ai-progress-inner");
  if (inner) inner.style.width = pct + "%";
  const status = modal.querySelector("#ai-status");
  if (status) {
    if (ev.status === "start") status.textContent = "Gemini へ送信中…";
    else if (ev.status === "progress") status.textContent = `処理中 ${ev.processed}/${ev.total} 件`;
    else if (ev.status === "waiting") status.textContent = `⏳ ${ev.error}`;
    else if (ev.status === "chunk_error") status.textContent = `エラー (一部スキップ): ${ev.error}`;
    else if (ev.status === "done") status.textContent = "完了 — 提案を確認してください";
    else if (ev.status === "error") status.textContent = `エラー: ${ev.error}`;
  }
  // チャンクエラーはステータス行だと次の進捗で上書きされて消えてしまうため、
  // 専用のログ欄に積み上げて完了後も読めるようにする。
  if (ev.status === "chunk_error" || ev.status === "error") {
    const log = modal.querySelector("#ai-error-log");
    if (log) {
      log.style.display = "flex";
      const line = document.createElement("div");
      line.textContent = `[${ev.processed}/${ev.total}] ${ev.error || "不明なエラー"}`;
      log.appendChild(line);
      log.scrollTop = log.scrollHeight;
    }
  }
  if (ev.cost_estimate) {
    const info = modal.querySelector("#ai-cost-info");
    if (info) {
      const c = ev.cost_estimate;
      let usd = "";
      if (c.input_cost_usd != null) {
        const total_low = (c.input_cost_usd + (c.output_cost_usd_low || 0));
        const total_high = (c.input_cost_usd + (c.output_cost_usd_high || 0));
        usd = ` | 推定コスト: $${total_low.toFixed(4)}〜$${total_high.toFixed(4)}`;
      } else {
        usd = " | コスト不明 (config.ini [AI].input_cost_per_1m_tokens 未設定)";
      }
      info.textContent = `入力 ~${c.input_tokens_est.toLocaleString()} tokens | チャンク: ${c.chunks}${usd}`;
      info.style.display = "block";
    }
  }
  const h2 = modal.querySelector("h2");
  if (h2 && ev.total) h2.textContent = `AI 分類 — ${ev.total} 件`;
}

function populateAiReviewModal(moves) {
  if (!_aiModal) return;

  const listEl = _aiModal.querySelector("#ai-review-list");
  const actionsEl = _aiModal.querySelector("#ai-modal-actions");
  if (!listEl || !actionsEl) return;

  listEl.innerHTML = "";
  listEl.style.display = "flex";
  actionsEl.style.display = "flex";

  moves.forEach((mv) => {
    const row = document.createElement("label");
    row.style.cssText =
      "display:flex;align-items:center;gap:10px;padding:8px 10px;background:#313244;border-radius:6px;cursor:pointer";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = mv.confidence >= 0.7;
    cb.dataset.bookmarkId = mv.bookmark_id;
    cb.dataset.folderPath = `/_AI/${mv.folder}`;
    const pct = Math.round(mv.confidence * 100);
    const titleEl = state.bookmarks.find((b) => b.bookmark_id === mv.bookmark_id);
    const title = titleEl ? titleEl.title : mv.bookmark_id.slice(0, 8);
    row.innerHTML = `
      <span style="color:#cdd6f4;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(title)}">${escHtml(title)}</span>
      <span style="color:#89b4fa;white-space:nowrap">→ ${escHtml(mv.folder)}</span>
      <span style="color:#a6e3a1;font-size:11px;white-space:nowrap">${pct}%</span>`;
    row.prepend(cb);
    if (mv.reason) {
      row.title = mv.reason;
    }
    listEl.appendChild(row);
  });

  const applyBtn = _aiModal.querySelector("#ai-btn-apply-selected");
  if (applyBtn) {
    applyBtn.onclick = async () => {
      const checked = listEl.querySelectorAll("input[type=checkbox]:checked");
      const applyMoves = Array.from(checked).map((cb) => ({
        bookmark_id: cb.dataset.bookmarkId,
        folder_path: cb.dataset.folderPath,
      }));
      if (!applyMoves.length) return toast("チェックされた項目がありません");
      const pruneEmpty = !!_aiModal.querySelector("#ai-prune-empty")?.checked;
      try {
        const res = await api("/classify/ai-apply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ moves: applyMoves, prune_empty_source: pruneEmpty }),
        });
        closeAiReviewModal();
        await reload();
        const prunedMsg = res.pruned ? `、空フォルダ ${res.pruned} 件削除` : "";
        toast(`${res.applied} 件移動しました (スキップ: ${res.skipped})${prunedMsg}`);
      } catch (e) {
        toast(`適用失敗: ${e.message}`, "error");
      }
    };
  }
}

function escHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// --- Boot ------------------------------------------------------------------

function restoreView() {
  try {
    const v = localStorage.getItem(VIEW_STORAGE_KEY);
    if (v === "card" || v === "list") setViewMode(v);
  } catch (_) {}
  try {
    const d = localStorage.getItem(DUAL_STORAGE_KEY);
    setDualPane(d === "1");
  } catch (_) {}
  try {
    const raw = localStorage.getItem(TREE_OPEN_STORAGE_KEY);
    if (raw) state.openFolders = new Set(JSON.parse(raw));
  } catch (_) {}
  try {
    const rawB = localStorage.getItem(TREE_OPEN_STORAGE_KEY + "_B");
    if (rawB) state.openFoldersB = new Set(JSON.parse(rawB));
  } catch (_) {}
}

async function boot() {
  setupDetailInlineEdit();
  restoreView();
  restoreSplit();
  if (!API_BASE) {
    setStatus("API 未設定");
    toast("API ベース URL が設定されていません", "error");
    return;
  }
  setStatus("接続中…");
  try {
    const health = await api("/health");
    setStatus(`接続済 v${health.version}`);
  } catch (e) {
    setStatus("接続失敗");
    toast(`/health 失敗: ${e.message}`, "error");
    return;
  }
  // 起動時に開いたファイルが前回の続きなら、引き継ぐか確認（描画前に確定）。
  try {
    const s = await api("/session/state");
    await maybePromptResume(s.resume_available, s.file);
  } catch (_) {}
  await reload();
  // Initialize undo/redo button state
  try {
    const h = await api("/edit/history");
    updateUndoRedoButtons(h.undo_count, h.redo_count);
  } catch (_) {}
}

// ============================================================
// Context menu
// ============================================================

const ctxMenu = (() => {
  const el = document.createElement("div");
  el.id = "ctx-menu";
  el.classList.add("hidden");
  document.body.appendChild(el);

  document.addEventListener("mousedown", (e) => {
    if (!el.contains(e.target)) hide();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hide();
  });

  function hide() { el.classList.add("hidden"); }

  function show(x, y, items) {
    el.innerHTML = "";
    for (const item of items) {
      if (item === "sep") {
        const hr = document.createElement("div");
        hr.className = "ctx-sep";
        el.appendChild(hr);
      } else {
        const btn = document.createElement("button");
        btn.textContent = item.label;
        if (item.danger) btn.classList.add("danger");
        btn.addEventListener("click", () => { hide(); item.action(); });
        el.appendChild(btn);
      }
    }
    el.classList.remove("hidden");
    // Clamp to viewport
    const vw = window.innerWidth, vh = window.innerHeight;
    el.style.left = Math.min(x, vw - el.offsetWidth - 8) + "px";
    el.style.top  = Math.min(y, vh - el.offsetHeight - 8) + "px";
  }

  return { show, hide };
})();

// ---- Folder operations called from context menu ----

async function cmdRenameFolder(folderPath) {
  const current = folderPath.split("/").filter(Boolean).pop() || folderPath;
  const newTitle = prompt("新しいフォルダ名:", current);
  if (!newTitle || newTitle === current) return;
  try {
    await api("/edit/folder/rename", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_path: folderPath, new_title: newTitle }),
    });
    await reload();
    toast(`フォルダ名を変更しました: ${newTitle}`);
  } catch (e) {
    toast(`リネーム失敗: ${e.message}`, "error");
  }
}

async function cmdDeleteFolder(folderPath) {
  if (!(await confirmDialog(`フォルダ「${folderPath}」を削除しますか?\n中のブックマークもすべて削除されます。`))) return;
  try {
    await api(`/edit/folder?folder_path=${encodeURIComponent(folderPath)}`, { method: "DELETE" });
    if (state.selectedFolder === folderPath) state.selectedFolder = null;
    await reload();
    toast("フォルダを削除しました");
  } catch (e) {
    toast(`削除失敗: ${e.message}`, "error");
  }
}

async function cmdNewSubFolder(parentPath) {
  const title = prompt(`新しいサブフォルダ名 (作成先: /${parentPath || "ルート"}):`);
  if (!title) return;
  try {
    await api("/edit/folder/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parent_path: parentPath, title }),
    });
    await reload();
    toast(`フォルダを作成しました: ${title}`);
  } catch (e) {
    toast(`作成失敗: ${e.message}`, "error");
  }
}

// ---- Bookmark operations called from context menu ----

async function cmdAddBookmarkToFolder(folderPath) {
  const url = prompt(`URL を入力 (追加先: /${folderPath || "ルート"}):`);
  if (!url) return;
  const title = prompt("タイトル (空欄で URL を使用):") || "";
  try {
    await api("/edit/bookmark/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_path: folderPath, title, url }),
    });
    await reload();
    toast("ブックマークを追加しました");
  } catch (e) {
    toast(`追加失敗: ${e.message}`, "error");
  }
}

// ---- Attach context menu to tree nodes ----

function attachFolderContextMenu(row, node) {
  row.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    e.stopPropagation();
    ctxMenu.show(e.clientX, e.clientY, [
      { label: "📁 サブフォルダを追加",  action: () => cmdNewSubFolder(node.path) },
      { label: "🔖 ブックマークを追加",  action: () => cmdAddBookmarkToFolder(node.path) },
      "sep",
      { label: "✏️ リネーム",            action: () => cmdRenameFolder(node.path) },
      "sep",
      { label: "🗑 フォルダを削除",       action: () => cmdDeleteFolder(node.path), danger: true },
    ]);
  });
}

function attachBookmarkContextMenu(li, node) {
  li.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const bm = {
      bookmark_id: node.bookmark_id,
      node_id: node.node_id,
      title: node.title,
      url: node.url,
      folder_path: node.parentPath || "",
      add_date: node.add_date,
      last_modified: node.last_modified,
      icon: node.icon,
      description: node.description,
    };
    ctxMenu.show(e.clientX, e.clientY, [
      { label: "✏️ 編集",     action: () => { selectBookmark(bm); cmdDetailEdit(); } },
      { label: "🌐 開く",     action: () => window.__TAURI__ ? window.__TAURI__.shell.open(bm.url) : window.open(bm.url, "_blank") },
      "sep",
      { label: "🗑 削除",     action: () => { selectBookmark(bm); cmdDeleteSelected(); }, danger: true },
    ]);
  });
}

// --- Global keyboard shortcuts ---------------------------------------------

document.addEventListener("keydown", (e) => {
  // Ignore when focus is inside an input/textarea (allow native undo there)
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

  if (e.ctrlKey || e.metaKey) {
    if (e.key === "z" && !e.shiftKey) { e.preventDefault(); cmdUndo(); }
    if (e.key === "y" || (e.key === "z" && e.shiftKey)) { e.preventDefault(); cmdRedo(); }
    if (e.key === "s") { e.preventDefault(); cmdSave(); }
  }
});

// Global DnD guard: WebView2/Chromium shows the "no-drop" cursor whenever a
// dragover bubbles up to an element without preventDefault. Catching it at
// document level keeps the "move" cursor active everywhere and lets nested
// children (icons, labels) pass the event through to their drop targets.
document.addEventListener("dragenter", (e) => {
  e.preventDefault();
});
document.addEventListener("dragover", (e) => {
  e.preventDefault();
  if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
});
document.addEventListener("drop", (e) => {
  // Prevent default browser behaviour (e.g. navigating to dropped URL)
  // when the drop happens outside any registered target.
  e.preventDefault();
});

boot();
