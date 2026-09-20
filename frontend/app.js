// NeoBookMarkManager — frontend (Phase 3 build).
//
// Phase 3 wires mutation commands to the Rust API:
//   add/edit/delete bookmark+folder, save, tags, move-up, reorder, backup.
// D&D and 2-pane tree-to-tree moves come in Phase 4.

const API_BASE_STORAGE_KEY = "nbm_api_base";
const SPLIT_STORAGE_KEY = "nbm_split_state_v3";
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
  // 操作の対象 ("selection" | "folder" | "all")。Organize / Enrich / AI が共有する。
  scope: "all",
  filePath: null,         // 開いているファイル（null なら未読込）
  dirty: false,           // 未保存の変更があるか
  undoCount: 0,
  redoCount: 0,
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
  if (!res.ok) {
    // The server answers failures with {"error": "..."} — the reason the call
    // was rejected. Dropping it meant every failure reached the user as a bare
    // "404 Not Found" with nothing to act on.
    let detail = "";
    try {
      const body = await res.json();
      if (body && body.error) detail = `: ${body.error}`;
    } catch (_) {}
    throw new Error(`${res.status} ${res.statusText}${detail}`);
  }
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
      // 対象はユーザーが最後に指したものに追従する（スコープバーに即反映される）
      state.scope = "folder";
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

// --- Scope: 操作の対象を1か所で決める --------------------------------------
//
// 「整理する」「情報を補う」「AI」の各操作は、必ず state.scope が指す範囲に
// 対して実行される。以前は Organize が state.selectedFolder を暗黙に使い、
// Enrich / AI は実行のたびにモーダルで対象を訊き直していたため、隣り合う
// ボタン同士で対象の決まり方が違っていた。
//
// scope は直近の明示的な選択に追従する（フォルダを選べば "folder"、
// ブックマークを選べば "selection"）。パネル上部のセグメントで上書きできる。

const SCOPE_KINDS = ["selection", "folder", "all"];

/// 指定スコープの bookmark_id 配列。そのスコープが使えないときは null。
function scopeIdsFor(kind) {
  if (kind === "selection") {
    const ids = [...state.selectedBookmarks].filter(Boolean);
    return ids.length ? ids : null;
  }
  if (kind === "folder") {
    if (state.selectedFolder == null || !state.treeRoot) return null;
    const node = findFolderByPath(state.treeRoot, state.selectedFolder);
    if (!node) return null;
    const out = [];
    flattenBookmarks(node, state.selectedFolder || "", out);
    return out.map((b) => b.bookmark_id).filter(Boolean);
  }
  return state.bookmarks.map((b) => b.bookmark_id).filter(Boolean);
}

/// 現在のスコープを解決する。folderPath はフォルダ単位 API 用
/// （"selection" スコープではフォルダを特定できないので null）。
function currentScope() {
  const kind = state.scope;
  const ids = scopeIdsFor(kind) || [];
  if (kind === "selection") {
    return { kind, ids, folderPath: null, label: `選択中の ${ids.length} 件` };
  }
  if (kind === "folder") {
    const path = state.selectedFolder || "";
    return { kind, ids, folderPath: path, label: `フォルダ「${path || "ルート"}」以下の ${ids.length} 件` };
  }
  return { kind, ids, folderPath: "", label: `全ブックマーク ${ids.length} 件` };
}

function setScope(kind) {
  if (!SCOPE_KINDS.includes(kind)) return;
  state.scope = kind;
  refreshContext();
}

/// 選択操作に追従してスコープを移す。そのスコープが空なら何もしない。
function followScope(kind) {
  if (scopeIdsFor(kind)) state.scope = kind;
}

function renderScopeBar() {
  const idsSel    = scopeIdsFor("selection");
  const idsFolder = scopeIdsFor("folder");
  const idsAll    = scopeIdsFor("all") || [];

  // 使えなくなったスコープが選ばれたままにならないよう退避する
  if (state.scope === "selection" && !idsSel)    state.scope = idsFolder ? "folder" : "all";
  if (state.scope === "folder"    && !idsFolder) state.scope = "all";

  const fmt = (v) => (v ? v.length.toLocaleString() : "—");
  $("scopeNSelection").textContent = fmt(idsSel);
  $("scopeNFolder").textContent    = fmt(idsFolder);
  $("scopeNAll").textContent       = idsAll.length.toLocaleString();

  const avail = { selection: !!idsSel, folder: !!idsFolder, all: true };
  for (const btn of document.querySelectorAll(".scope-opt")) {
    const kind = btn.dataset.scope;
    btn.setAttribute("aria-checked", state.scope === kind ? "true" : "false");
    btn.disabled = !avail[kind];
    btn.title = avail[kind] ? ""
      : kind === "selection" ? "一覧かツリーでブックマークを選択すると使えます"
      : "ツリーでフォルダを選択すると使えます";
  }
  document.body.dataset.scope = state.scope;

  const target = $("scopeTarget");
  if (target) target.textContent = state.filePath ? currentScope().label : "ファイルを開いてください";

  const listLabel = $("listScopeLabel");
  if (listLabel) {
    listLabel.textContent = state.searchQuery ? "検索結果"
      : state.selectedFolder == null ? "すべて"
      : `📂 ${state.selectedFolder || "ルート"}`;
  }
}

// --- Enablement: 押す前に「今できること」を見せる ---------------------------
//
// data-need でボタンの前提条件を宣言し、満たさないものは disabled にして
// 理由を title に出す。以前は全ボタンが常に有効で、押して初めてトーストで
// 「ブックマークを選択してください」と怒られる作りだった。

const NEED_CHECKS = {
  file:           () => !!state.filePath,
  bookmark:       () => !!state.selectedBookmark,
  folder:         () => state.selectedFolder != null,
  dirty:          () => state.dirty,
  undo:           () => state.undoCount > 0,
  redo:           () => state.redoCount > 0,
  "scope-any":    () => currentScope().ids.length > 0,
  "scope-folder": () => !!state.filePath && state.scope !== "selection",
};

function updateEnablement() {
  for (const el of document.querySelectorAll("[data-need]")) {
    const check = NEED_CHECKS[el.dataset.need];
    const ok = check ? check() : true;
    el.disabled = !ok;
    if (el.dataset.titleOn === undefined) el.dataset.titleOn = el.getAttribute("title") || "";
    el.setAttribute("title", ok ? el.dataset.titleOn : (el.dataset.hint || el.dataset.titleOn));
  }
}

/// 選択・スコープ・ファイル状態が変わったら呼ぶ。
function refreshContext() {
  renderScopeBar();
  updateEnablement();
  scheduleEnrichStatus();
}

// --- 「情報を補う」ダッシュボード -------------------------------------------
// 操作の対象(scope)に対して、タイトル・説明文・タグがどれだけ埋まっているか。
let _enrichTimer = null;
let _enrichSeq = 0;
let _enrichNeedFetch = null;   // 直近のステータスで「未取得あり」のID
let _enrichGivenUp = 0;        // 取得を試みて取得できなかった件数

function scheduleEnrichStatus() {
  clearTimeout(_enrichTimer);
  _enrichTimer = setTimeout(refreshEnrichStatus, 250);
}

async function refreshEnrichStatus() {
  const dash = document.getElementById("enrichDash");
  if (!dash || !API_BASE) return;
  const ids = currentScope().ids;
  const seq = ++_enrichSeq;
  let st = null;
  if (ids.length) {
    try {
      st = await api("/enrich/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bookmark_ids: ids }),
      });
    } catch (_) {}
  }
  if (seq !== _enrichSeq) return;   // 新しい問い合わせが走っていたら捨てる
  _enrichNeedFetch = st ? st.need_fetch_ids : null;
  _enrichGivenUp = st ? st.given_up : 0;
  dash.classList.toggle("stale", !st);
  // 取得を試みて何も無かった分(取得不可)も「対応済み」に数え、グレーで区別する。
  const rows = {
    title: [st?.with_title, st?.title_unavailable],
    desc: [st?.with_description, st?.description_unavailable],
    tags: [st?.with_tags, 0],
  };
  for (const [k, [n, u]] of Object.entries(rows)) {
    const row = dash.querySelector(`[data-k="${k}"]`);
    if (!row) continue;
    const total = st?.total || 0;
    const handled = (n || 0) + (u || 0);
    const pct = st && total ? Math.round((handled / total) * 100) : 0;
    const w = (x) => (st && total ? (x / total) * 100 : 0);
    row.querySelector(".enrich-bar > i").style.width = `${w(n || 0)}%`;
    row.querySelector(".enrich-bar > b").style.width = `${w(u || 0)}%`;
    row.querySelector(".enrich-n").innerHTML = st
      ? `${handled.toLocaleString()} / ${total.toLocaleString()}（${pct}%）` +
        (u ? `<small>取得不可 ${u.toLocaleString()}</small>` : "")
      : "—";
    row.classList.toggle("done", !!st && total > 0 && handled >= total);
  }
}

document.addEventListener("click", (e) => {
  const opt = e.target.closest && e.target.closest(".scope-opt");
  if (opt && !opt.disabled) setScope(opt.dataset.scope);
});

/// 実行前に「何件に効くのか」だけ確かめる。対象の選び直しはさせない
/// （それはスコープバーの役目）。キャンセル時は null。
async function confirmScope(message) {
  const sc = currentScope();
  if (!sc.ids.length) {
    toast("対象のブックマークがありません", "error");
    return null;
  }
  const ok = await confirmDialog(`${message}\n\n対象: ${sc.label}`, { okLabel: "実行", cancelLabel: "キャンセル" });
  return ok ? sc.ids : null;
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
  refreshContext();
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
    followScope("selection");
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
  followScope("selection");
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
  followScope("selection");
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
  refreshContext();
}

// --- Detail ----------------------------------------------------------------

function renderDetail() {
  const bm = state.selectedBookmark;
  if (!bm) {
    detailEmpty.classList.remove("hidden");
    detailCard.classList.add("hidden");
    const emptyLabel = $("detailFolderLabel");
    if (emptyLabel) emptyLabel.textContent = "";
    return;
  }
  detailEmpty.classList.add("hidden");
  detailCard.classList.remove("hidden");

  const folderLabel = $("detailFolderLabel");
  if (folderLabel) folderLabel.textContent = bm.folder_path ? `📂 ${bm.folder_path}` : "📂 ルート";

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

// スプリッターはドラッグした片側だけをピクセル固定し、反対側は必ず
// flex: 1 1 0 のままにする。両側を `0 0 Npx` にすると合計がウィンドウ幅に
// 追従しなくなり、端に使われない余白が残る（4K で顕著だった）。
// どちら側を固定にするかは data-fixed で宣言する（既定は prev）。
const SPLIT_MIN_PX = 120;

function splitSides(sp) {
  const prev = sp.previousElementSibling;
  const next = sp.nextElementSibling;
  if (!prev || !next) return null;
  const fixedIsNext = sp.dataset.fixed === "next";
  return {
    prev, next,
    fixed: fixedIsNext ? next : prev,
    fluid: fixedIsNext ? prev : next,
  };
}

function applySplit(sp, sizePx) {
  const sides = splitSides(sp);
  if (!sides) return;
  sides.fixed.style.flex = `0 0 ${Math.round(sizePx)}px`;
  sides.fluid.style.flex = "1 1 0";
}

function initSplitters() {
  document.querySelectorAll(".splitter-h, .splitter-v").forEach((sp) => {
    // ダブルクリックで既定の配分に戻す（掴んだ幅から抜け出せる逃げ道）
    sp.addEventListener("dblclick", () => {
      const sides = splitSides(sp);
      if (!sides) return;
      sides.fixed.style.flex = "";
      sides.fluid.style.flex = "";
      saveSplit();
    });

    sp.addEventListener("pointerdown", (e) => {
      sp.setPointerCapture(e.pointerId);
      const isH = sp.classList.contains("splitter-h"); // horizontal = resizes left/right siblings

      const sides = splitSides(sp);
      if (!sides) return;
      const { prev, next } = sides;

      const startPos = isH ? e.clientX : e.clientY;
      const startPrev = isH ? prev.getBoundingClientRect().width : prev.getBoundingClientRect().height;
      const startNext = isH ? next.getBoundingClientRect().width : next.getBoundingClientRect().height;

      const onMove = (ev) => {
        const delta = (isH ? ev.clientX : ev.clientY) - startPos;
        const newPrev = startPrev + delta;
        const newNext = startNext - delta;
        if (newPrev > SPLIT_MIN_PX && newNext > SPLIT_MIN_PX) {
          applySplit(sp, sp.dataset.fixed === "next" ? newNext : newPrev);
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
    const colRight  = document.querySelector(".col-right");
    const detail    = document.querySelector(".pane-detail");
    localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify({
      colLeft:   colLeft?.style.flex   || "",
      colRight:  colRight?.style.flex  || "",
      actions:   actions?.style.flex   || "",
      detail:    detail?.style.flex    || "",
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
    // 前回より小さいウィンドウで開いたときに、保存値が画面を食い潰さないよう捨てる
    const set = (sel, val, maxPx) => {
      if (!val) return;
      const el = document.querySelector(sel);
      if (!el) return;
      const px = val.startsWith("0 0 ") ? parseFloat(val.slice(4)) : NaN;
      if (!Number.isNaN(px) && px > maxPx) return;
      el.style.flex = val;
    };
    const maxW = window.innerWidth  * 0.7;
    const maxH = window.innerHeight * 0.7;
    set(".col-left",     v.colLeft,   maxW);
    set(".col-right",    v.colRight,  maxW);
    set(".pane-actions", v.actions,   maxW);
    set(".pane-detail",  v.detail,    maxW);
    set(".pane-upper",   v.paneUpper, maxH);
    set(".pane-list",    v.paneList,  maxH);
    set("#paneTreeA",    v.paneTreeA, maxW);
    set("#paneTreB",     v.paneTreB,  maxW);
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

    // 未保存かどうかは保存ボタン自体に出す（タイトルバーの ● は気づけないため）
    state.filePath = listData.file_path || null;
    state.dirty = !!listData.dirty;
    document.body.dataset.loaded = state.filePath ? "true" : "false";
    document.body.dataset.dirty = state.dirty ? "true" : "false";

    const fileChip = $("fileChip");
    if (fileChip) {
      const name = state.filePath ? state.filePath.split(/[\\/]/).pop() : null;
      fileChip.textContent = name || "ファイル未選択";
      fileChip.title = state.filePath || "ファイルが開かれていません";
    }

    setStatus(`${listData.count.toLocaleString()} 件${state.dirty ? " · 未保存" : ""}`);
    document.title = state.dirty ? "NeoBookMarkManager ●" : "NeoBookMarkManager";
    refreshContext();
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
    case "edit.rename-folder":  return cmdRenameFolder(state.selectedFolder ?? "");
    case "edit.undo":           return cmdUndo();
    case "edit.redo":           return cmdRedo();
    case "detail.edit":         return cmdDetailEdit();
    case "detail.edit-tags":    return cmdDetailEditTags();
    case "detail.copy-url":     return cmdCopyUrl();
    case "detail.open":         return cmdOpenInBrowser();
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
    case "enrich.all":           return cmdEnrichAll();
    case "ai.classify":
    case "classify.ai":          return cmdAiClassify();
    case "ai.settings":          return cmdAiSettings();
    case "help.open":            return cmdHelp();
    default:
      toast(`未実装: ${cmd}`, "error");
  }
}

// --- Command implementations -----------------------------------------------

function cmdOpenInBrowser() {
  const bm = state.selectedBookmark;
  if (!bm) return toast("ブックマークを選択してください", "error");
  if (window.__TAURI__) window.__TAURI__.shell.open(bm.url);
  else window.open(bm.url, "_blank");
}

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
  state.undoCount = undoCount || 0;
  state.redoCount = redoCount || 0;
  const ub = $("undoBadge");
  const rb = $("redoBadge");
  if (ub) ub.textContent = state.undoCount > 0 ? state.undoCount : "";
  if (rb) rb.textContent = state.redoCount > 0 ? state.redoCount : "";
  updateEnablement();
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
  // Picking the file and loading it are reported separately: one "開けません
  // でした" for both stages gave no way to tell a missing dialog API from a
  // file the server refused to parse.
  let selected;
  try {
    const { open } = getTauriDialog();
    selected = await open({
      title: "ブックマークファイルを開く",
      filters: [{ name: "HTML", extensions: ["html", "htm"] }],
      multiple: false,
    });
  } catch (e) {
    console.error("[open] dialog failed", e);
    toast(`ファイル選択ダイアログを開けませんでした: ${e.message ?? e}`, "error");
    return;
  }

  // Cancelling returns null. Older dialog builds hand back {path, name}
  // instead of a bare string, which used to fall through as "cancelled" and
  // left the user with a dialog that appeared to do nothing.
  const path =
    typeof selected === "string" ? selected :
    selected && typeof selected.path === "string" ? selected.path :
    null;
  if (!path) {
    if (selected != null) {
      console.error("[open] unexpected dialog result", selected);
      toast(`選択結果を解釈できませんでした: ${JSON.stringify(selected)}`, "error");
    }
    return;
  }

  try {
    const opened = await api("/file/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path }) });
    await maybePromptResume(opened.resume_available, opened.path);
    await reload();
    toast(`ファイルを開きました (${opened.count} 件)`);
  } catch (e) {
    console.error("[open] load failed", path, e);
    toast(`読み込みに失敗しました: ${e.message ?? e}
${path}`, "error");
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
  const ids = await confirmScope("各URLにアクセスして、ページのタイトルで置き換えます。");
  if (!ids) return;
  await runSseCommand("/network/fix-titles", { bookmark_ids: ids }, "タイトル更新");
  toast("タイトル更新完了");
}

async function cmdNetworkFetchPreview() {
  const ids = await confirmScope("各URLにアクセスして、ページの説明文を取り込みます。");
  if (!ids) return;
  await runSseCommand("/network/fetch-preview", { bookmark_ids: ids }, "説明文取得");
  toast("説明文の取得が完了しました");
}

// タイトル・説明文（Webから）→ タグ（ローカル）を1ボタンで順に実行する。
// 取得は既に埋まっている項目を飛ばし、未取得のものだけに通信する。
async function cmdEnrichAll() {
  const sc = currentScope();
  if (!sc.ids.length) return toast("対象のブックマークがありません", "error");
  await refreshEnrichStatus();   // 直前の状態で判定する
  const need = _enrichNeedFetch ? new Set(_enrichNeedFetch) : null;
  const fetchIds = need ? sc.ids.filter((id) => need.has(id)) : sc.ids;

  const ok = await confirmDialog(
    `次を順に実行します。\n\n` +
    `1. タイトル・説明文をWebから取得（未取得の ${fetchIds.length} 件のみ。各URLにアクセスします）\n` +
    (_enrichGivenUp ? `   ※取得を試みて取得できなかった ${_enrichGivenUp} 件は飛ばします（個別ボタンで再試行できます）\n` : "") +
    `2. タイトル・説明文・URLからタグを付ける（${sc.ids.length} 件、ローカル処理）\n\n` +
    `対象: ${sc.label}`,
    { okLabel: "実行", cancelLabel: "キャンセル" }
  );
  if (!ok) return;

  if (fetchIds.length) {
    await runSseCommand("/network/fetch-preview", { bookmark_ids: fetchIds }, "タイトル・説明文取得");
  }
  await runSseCommand("/autotag/local", { bookmark_ids: sc.ids }, "自動タグ付け");
  await refreshEnrichStatus();
  toast("タイトル・説明文・タグの取得が完了しました");
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
  const ids = await confirmScope("各URLにアクセスして、リンク切れを調べます。\n(除外パターンに一致するURLはスキップ)");
  if (!ids) return;

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
      <div style="display:flex;align-items:center;gap:10px;font-size:12px;color:var(--text-mid)">
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
          <input id="lc-all" type="checkbox" checked /> すべて選択
        </label>
        <span style="flex:1"></span>
        <span>タイムアウトは一時的な不通のこともあります。削除前に確認してください。</span>
      </div>
      <div id="lc-list" style="overflow-y:auto;flex:1;display:flex;flex-direction:column;gap:6px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button id="lc-delete" class="danger-btn">🗑 選択した 0 件を削除</button>
        <button id="lc-close" class="ghost-btn">閉じる</button>
      </div>
    </div>`;
  document.body.appendChild(modal);

  const listEl = modal.querySelector("#lc-list");
  const allEl = modal.querySelector("#lc-all");
  const delEl = modal.querySelector("#lc-delete");

  // Timeouts are checked by default but flagged in the hint above: a slow or
  // briefly unreachable host is not the same evidence of rot as a 404.
  for (const p of deadList) {
    const badge = p.result === "timeout" ? "⏱ タイムアウト" : `❌ ${p.detail || "切れ"}`;
    const row = document.createElement("div");
    row.style.cssText =
      "padding:8px 10px;background:var(--surface-2);border-radius:6px;border-left:3px solid var(--danger);display:flex;align-items:center;gap:10px";
    row.innerHTML = `
      <input type="checkbox" class="lc-pick" data-id="${escHtml(p.bookmark_id || "")}" checked
             style="flex:none;cursor:pointer" />
      <div style="min-width:0;display:flex;flex-direction:column;gap:3px;flex:1">
        <div style="font-size:13px;color:var(--text-hi);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(p.bookmark_title || "(no title)")}</div>
        <div style="display:flex;align-items:center;gap:8px;min-width:0">
          <span style="font-size:11px;color:var(--danger);white-space:nowrap">${badge}</span>
          <a href="${escHtml(p.url || "")}" style="font-size:11px;color:var(--text-mid);overflow:hidden;text-overflow:ellipsis;white-space:nowrap" target="_blank" rel="noreferrer">${escHtml(p.url || "")}</a>
        </div>
      </div>`;
    listEl.appendChild(row);
  }

  const picks = () => Array.from(listEl.querySelectorAll(".lc-pick"));
  const checkedIds = () =>
    picks().filter((c) => c.checked && c.dataset.id).map((c) => c.dataset.id);

  const syncButtons = () => {
    const n = checkedIds().length;
    delEl.textContent = `🗑 選択した ${n} 件を削除`;
    delEl.disabled = n === 0;
    const boxes = picks();
    allEl.checked = n > 0 && n === boxes.length;
    allEl.indeterminate = n > 0 && n < boxes.length;
  };

  allEl.addEventListener("change", () => {
    for (const c of picks()) c.checked = allEl.checked;
    syncButtons();
  });
  listEl.addEventListener("change", (e) => {
    if (e.target.classList.contains("lc-pick")) syncButtons();
  });

  delEl.addEventListener("click", async () => {
    const ids = checkedIds();
    if (!ids.length) return;
    if (!(await confirmDialog(
      `リンク切れ ${ids.length} 件をブックマークから削除します。

` +
      `元に戻す場合は削除後に「元に戻す」を1回実行してください。`,
      { okLabel: "削除", cancelLabel: "キャンセル" }
    ))) return;
    delEl.disabled = true;
    try {
      const res = await api("/edit/bookmark/bulk-delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bookmark_ids: ids }),
      });
      modal.remove();
      state.selectedBookmark = null;
      renderDetail();
      await reload();
      const skipped = (res.missing || []).length;
      toast(
        `リンク切れ ${res.deleted} 件を削除しました` +
        (skipped ? `（${skipped} 件は見つからずスキップ）` : "")
      );
    } catch (e) {
      delEl.disabled = false;
      toast(`削除失敗: ${e.message}`, "error");
    }
  });

  modal.querySelector("#lc-close").addEventListener("click", () => modal.remove());
  modal.addEventListener("click", (e) => { if (e.target === modal) modal.remove(); });
  syncButtons();
}

async function cmdAutotagOffline() {
  const ids = currentScope().ids;
  if (!ids.length) return toast("対象のブックマークがありません", "error");

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
      `タグ付けの分類材料が一部不足しています。\n\n${missing.join("\n")}\n\n` +
      `このまま実行しますか?\n\n対象: ${currentScope().label}`,
      { okLabel: "実行", cancelLabel: "キャンセル" }
    ))) return;
  } else if (!(await confirmScope("タイトル・説明文・URL からローカルでタグを付けます。"))) {
    return;
  }

  await runSseCommand("/autotag/local", { bookmark_ids: ids }, "自動タグ付け");
  toast("自動タグ付け完了");
}

async function cmdOrganizeDedupe() {
  const sc = currentScope();
  const folder = sc.folderPath ?? "";
  if (!(await confirmDialog(`同じURLのブックマークをまとめて1件にします。\n\n対象: ${sc.label}`,
        { okLabel: "実行", cancelLabel: "キャンセル" }))) return;
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
  const sc = currentScope();
  const parent = sc.folderPath ?? "";
  if (!(await confirmDialog(`同じ名前のフォルダを1つにまとめます。\n\n対象: ${sc.label}`,
        { okLabel: "実行", cancelLabel: "キャンセル" }))) return;
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
  const sc = currentScope();
  const folder = sc.folderPath ?? "";
  if (!(await confirmDialog(`ブックマークをドメイン順に並べ替えます。\n\n対象: ${sc.label}`,
        { okLabel: "実行", cancelLabel: "キャンセル" }))) return;
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
  const folder = currentScope().folderPath ?? "";
  const scope = currentScope().label;

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
  const folder = currentScope().folderPath ?? "";
  const scope  = currentScope().label;

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
// --- Help ------------------------------------------------------------------
//
// 料金まわりは「models.json が優先」「単価不明なら実行をブロック」など
// 覚えておくべき規則が多く、静的な説明文はすぐ古くなる。そこで実際に
// /config/ai-status と /config/models を読み、その場の設定を表示する。

async function cmdHelp() {
  // 料金セクションは実データで描く。取れなくてもヘルプ自体は開く。
  let status = null, models = null;
  try { status = await api("/config/ai-status"); } catch (_) {}
  try { models = await api("/config/models"); } catch (_) {}

  const C = AI_C;
  const catalog = models?.catalog || null;
  const list = Array.isArray(catalog?.models) ? catalog.models : [];

  const row = (label, value, color) =>
    `<div style="display:flex;justify-content:space-between;gap:12px;padding:3px 0">
       <span style="color:${C.mid};flex:0 0 auto">${label}</span>
       <span style="color:${color || C.hi};text-align:right;word-break:break-all">${value}</span>
     </div>`;

  // 実効単価とその出所。設定画面と同じ解決ロジックの結果が出る。
  let priceRows;
  if (!status) {
    priceRows = row("状態", "サーバに接続できませんでした", C.red);
  } else if (status.pricing_set) {
    const src = { catalog: "config/models.json", config: "config.ini [AI]" }[status.pricing_source] || status.pricing_source;
    priceRows =
      row("既定モデル", escHtml(status.model)) +
      row("入力単価", `$${status.input_cost_per_1m} / 1M tokens`, C.green) +
      row("出力単価", `$${status.output_cost_per_1m} / 1M tokens`, C.green) +
      row("この単価の出所", escHtml(src), C.accent) +
      row("通常キーの枠", status.free_tier == null ? "未申告" : (status.free_tier ? "無料枠" : "有料枠"),
          status.free_tier == null ? C.amber : C.hi) +
      row("有料枠のキー", status.paid_key_set ? "登録済み" : "未登録",
          status.paid_key_set ? C.green : C.lo) +
      row("AI実行", "可能", C.green);
  } else {
    priceRows =
      row("既定モデル", escHtml(status.model)) +
      row("単価", "不明", C.red) +
      row("AI実行", "ブロックされます", C.red);
  }

  // 注記に「※」が入っているモデル＝期限や割増がある要注意モデル。
  // カタログから拾うので、models.json を更新すればここも自動で追随する。
  const caution = list.filter((m) => String(m.note || "").includes("※"));
  const cautionHtml = caution.length
    ? caution.map((m) =>
        `<div style="padding:6px 0;border-top:1px solid ${C.border}">
           <div style="color:${C.hi};font-size:12px">${escHtml(m.label || m.id)}
             <span style="color:${C.lo};font-size:11px">（$${m.input_per_1m} / $${m.output_per_1m}）</span></div>
           <div style="color:${C.amber};font-size:11px;line-height:1.55;margin-top:2px">${escHtml(m.note)}</div>
         </div>`).join("")
    : `<div style="color:${C.lo};font-size:11px">注意が必要なモデルはありません。</div>`;

  const updated = catalog?._updated ? escHtml(catalog._updated) : "不明";
  const sourceUrl = catalog?._source || "https://ai.google.dev/gemini-api/docs/pricing";

  const section = (title, body) =>
    `<section style="border:1px solid ${C.border};border-radius:8px;overflow:hidden">
       <h3 style="margin:0;padding:8px 12px;background:${C.bg2};color:${C.mid};font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase">${title}</h3>
       <div style="padding:11px 12px;font-size:12px;color:${C.hi};line-height:1.7">${body}</div>
     </section>`;

  const kbd = (k) =>
    `<span style="display:inline-block;background:${C.bg3};border:1px solid ${C.border};border-radius:3px;padding:0 5px;font-size:11px;color:${C.hi}">${k}</span>`;

  const modal = document.createElement("div");
  modal.style.cssText =
    "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:9999;display:flex;align-items:center;justify-content:center;font-family:inherit";
  modal.innerHTML = `
    <div style="background:${C.bg1};border:1px solid ${C.border};border-radius:10px;width:720px;max-width:94vw;height:84vh;display:flex;flex-direction:column;overflow:hidden">

      <div style="padding:15px 20px 11px;border-bottom:1px solid ${C.border};flex:0 0 auto">
        <div style="color:${C.hi};font-size:15px;font-weight:600">ヘルプ <span style="color:${C.lo};font-size:11px;font-weight:400;margin-left:6px">NeoBookMarkManager ${appVersion ? "v" + escHtml(appVersion) : ""}</span></div>
        <div style="color:${C.lo};font-size:11px;margin-top:3px">この画面の内容は、いま読み込まれている設定から生成しています。</div>
      </div>

      <div style="flex:1 1 0;overflow-y:auto;padding:14px 20px;display:flex;flex-direction:column;gap:12px">

        ${section("AI の料金 — 現在の状態", `
          <div style="background:${C.bg2};border-radius:6px;padding:9px 11px;margin-bottom:10px">${priceRows}</div>
          <div style="color:${C.mid};font-size:11.5px">
            単価は次の順で解決されます。<br>
            <b style="color:${C.hi}">1.</b> <code style="color:${C.accent}">config/models.json</code> のモデル別価格（通常はこちら）<br>
            <b style="color:${C.hi}">2.</b> <code style="color:${C.accent}">config.ini [AI]</code> の <code>input/output_cost_per_1m_tokens</code>（models.json に無いモデル用のフォールバック）<br>
            <b style="color:${C.red}">3.</b> どちらからも取れない場合は、<b style="color:${C.red}">Gemini に一切送信せず実行をブロック</b>します。
          </div>`)}

        ${section("無料枠と有料枠の違い", `
          <div style="color:${C.amber};font-size:11.5px;margin-bottom:8px;line-height:1.6">
            このアプリが送るのは<b>ブックマークのタイトルとURL</b>です。何を見ているかがほぼ分かる情報なので、
            どちらの枠で使っているかは把握しておいてください。
          </div>
          <div style="overflow-x:auto">
          <table style="border-collapse:collapse;width:100%;font-size:11.5px">
            <thead><tr style="background:${C.bg2};color:${C.mid};font-size:10px;text-transform:uppercase">
              <th style="padding:6px 8px;text-align:left"></th>
              <th style="padding:6px 8px;text-align:left">無料枠 (Free)</th>
              <th style="padding:6px 8px;text-align:left">有料枠 (Tier 1〜3)</th>
            </tr></thead>
            <tbody>
              <tr>
                <td style="padding:6px 8px;color:${C.mid};border-top:1px solid ${C.border};white-space:nowrap">請求</td>
                <td style="padding:6px 8px;border-top:1px solid ${C.border}">なし（請求先アカウント不要）</td>
                <td style="padding:6px 8px;border-top:1px solid ${C.border}">請求先アカウントの紐付けが必要</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:${C.mid};border-top:1px solid ${C.border};white-space:nowrap">送信内容の扱い</td>
                <td style="padding:6px 8px;border-top:1px solid ${C.border};color:${C.red}">
                  Googleが製品の改善・開発に利用。<b>人間のレビュアーが読む場合あり</b>（アカウント・APIキー・プロジェクトとは切り離した上で）
                </td>
                <td style="padding:6px 8px;border-top:1px solid ${C.border};color:${C.green}">
                  製品改善には利用されない。ポリシー違反の検知と法令対応のため、一定期間ログに残るのみ
                </td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:${C.mid};border-top:1px solid ${C.border};white-space:nowrap">レート制限</td>
                <td style="padding:6px 8px;border-top:1px solid ${C.border}">厳しい</td>
                <td style="padding:6px 8px;border-top:1px solid ${C.border}">Tierが上がるほど緩和</td>
              </tr>
            </tbody>
          </table>
          </div>
          <div style="color:${C.mid};font-size:11.5px;margin-top:9px;line-height:1.7">
            <b style="color:${C.red}">公式の利用規約は、無料枠について「機微情報・秘密情報・個人情報を送信しないこと」と明記しています。</b>
            大量のブックマークを投げる前に、自分がどちらの枠かを確認してください。<br><br>
            <b style="color:${C.hi}">Tierの上がり方</b>：Tier 1 = 請求先アカウントを紐付け（上限 $250）／
            Tier 2 = 累計 $100 かつ初回支払いから3日（上限 $2,000）／
            Tier 3 = 累計 $1,000 かつ30日（上限 $20,000〜）。
            無料→Tier 1 は即時、以降は10分以内に反映されます。<br><br>
            <b style="color:${C.hi}">レート制限の数値</b>は RPM（毎分リクエスト）・TPM（毎分入力トークン）・RPD（毎日リクエスト）の3軸ですが、
            <b>モデル別の具体的な数値は公式ドキュメントに載らなくなり、AI Studio で自分のプロジェクトの値を見る方式</b>に変わりました。
            予告なく変更されることがあります。RPD は太平洋時間の0時にリセットされます。<br><br>
            <b style="color:${C.hi}">このアプリでの影響</b>：無料枠だと制限に当たりやすくなります。429 を受けた場合は
            Gemini が返す待機秒数に従って自動で待ち、最大3回まで再送します。それでも落ちたチャンクは
            レビュー画面の「失敗分だけ再実行」から送り直せます。<br><br>
            <b style="color:${C.hi}">このアプリでの枠の切り替え</b>：AI設定にキーを2枠用意しています。
            分類はまず<b>通常キー</b>で実行し、<b>無料枠の上限で止まったときだけ</b>、
            「有料枠のキーで続けますか?」と確認したうえで残りを処理します。
            黙って有料キーに切り替わることはありません。有料キーが未登録なら、その旨だけをお知らせします。<br>
            枠はキー（プロジェクト）単位で決まるので、使い分けるには<b>別プロジェクトのキーが2本</b>必要です。
            同じキーで待っても、日次の上限は当日中には解消しません。<br><br>
            <b style="color:${C.amber}">注意</b>：承認ゲートの金額は単価表から計算しているだけなので、
            通常キーを「無料枠」と申告している場合は<b>「参考コスト」として表示し、請求されない旨を併記</b>します。
            未申告のままだと、課金の有無を正しく表示できません。
          </div>`)}

        ${section("送信前の承認ゲート", `
          AI 分類は必ず見積もり画面を挟みます。<b>対象件数・API呼び出し回数・推定入力トークン・推定金額</b>を提示し、
          「この内容で実行」を押すまで Gemini には何も送りません。<br>
          モデルは実行時に選べ、<b>見積もりは選んだモデルの単価で計算</b>されます。設定画面の「既定モデル」はその初期値です。<br>
          <span style="color:${C.mid};font-size:11.5px">送信する項目（タイトル / URL / タグ / 説明文）もオプション画面で選べます。説明文はトークン消費が大きく、見積もり額にもそのぶん反映されます。</span>`)}

        ${section("分類材料と「該当なし」", `
          オプション画面で、対象のタイトル・タグ・説明文がどれだけ埋まっているかを確認し、不足していれば警告します。<br>
          3つとも空のブックマークは<b>ドメインとURLしか手がかりがなく</b>、分類できずに提案から漏れます。
          全体の3割を超える場合は、実行前にもう一度確認を挟みます。<br>
          <b style="color:${C.amber}">推奨順：タイトルをWebから取得 → 説明文をWebから取得 → 自動でタグを付ける → AI分類</b><br><br>
          <span style="color:${C.mid};font-size:11.5px">
            分類できなかったものは「該当なし」として<b>提案されず、その場に留まります</b>。
            Misc / Others / Ungrouped / 未分類 のような受け皿フォルダは作りません。<br>
            また<b>新しいフォルダは2件以上のときだけ</b>作ります（1件だけのために新規フォルダは作らない）。
            既存フォルダへ入れる場合は1件でも提案されます。<br>
            レビュー画面の見出しに「N件中M件に提案 · K件は該当なし」と出るので、漏れた件数はそこで分かります。
          </span>`)}

        ${section("見積もりに反映されていないもの", `
          <div style="color:${C.mid};font-size:11.5px;margin-bottom:6px">
            以下は models.json の注記としてだけ持っており、<b style="color:${C.amber}">推定金額の計算には入っていません</b>。
            該当モデルを使うときは、表示額より高くなる場合があります。
          </div>
          ${cautionHtml}`)}

        ${section("価格表のメンテナンス", `
          ${row("価格表の最終更新", updated)}
          ${row("価格表の読み込み元", models?.from_file === false ? "アプリ内蔵（models.json が見つからず）" : "config/models.json",
                models?.from_file === false ? C.amber : C.hi)}
          ${row("使用中の config.ini", status?.config_path ? escHtml(status.config_path) : "不明", C.mid)}
          ${row("出典", `<a href="${escHtml(sourceUrl)}" target="_blank" rel="noreferrer" style="color:${C.accent}">${escHtml(sourceUrl)}</a>`)}
          ${row("登録モデル数", `${list.length} 件`)}
          ${models?.error ? `<div style="color:${C.amber};font-size:11px;margin-top:6px">${escHtml(models.error)}</div>` : ""}
          <div style="color:${C.mid};font-size:11.5px;margin-top:8px">
            価格を更新するときは <code style="color:${C.accent}">config/models.json</code> を編集します。コードの変更もアプリの再起動も不要で、
            次回の見積もりから反映されます（呼び出しのたびにファイルを読み直すため）。<br>
            モデルIDは Google 側で変わることがあります（例: <code>gemini-3.1-pro</code> → <code>gemini-3.1-pro-preview</code>）。
            IDが古いと呼び出しが 404 になるので、価格と一緒に確認してください。
          </div>`)}

        ${section("操作の対象（スコープ）", `
          右パネル上部の「操作の対象」が、<b>整理する / 情報を補う / AI</b> のすべての実行範囲を決めます。<br>
          <b>選択中</b>: 一覧やツリーで選んだブックマーク。<br>
          <b>フォルダ</b>: ツリーで選んだフォルダ（サブフォルダを含む）。<br>
          <b>全体</b>: 開いているファイルの全ブックマーク。<br>
          <span style="color:${C.mid};font-size:11.5px">
            対象は最後に選んだものへ自動で移ります（フォルダを選べば「フォルダ」、ブックマークを選べば「選択中」）。セグメントを押せば手動で上書きできます。<br>
            「整理する」はフォルダ単位で動くため、対象が「選択中」のときは使えません。
          </span>`)}

        ${section("元に戻す・保存", `
          ${kbd("Ctrl+Z")} / ${kbd("Ctrl+Y")} で元に戻す・やり直しができます。<b>AI 分類の適用も含めて</b>取り消せます。<br>
          未保存の変更があるときは、上部の<b>保存ボタンが色づいて ● が付きます</b>。ファイルに書き込むまで元のHTMLは変わりません。<br>
          <span style="color:${C.mid};font-size:11.5px">保存時にバックアップが作られます。「直前のバックアップに戻す」「バックアップ一覧から復元」から戻せます。</span>`)}

        ${section("キーボード", `
          ${kbd("Ctrl+O")} ファイルを開く　${kbd("Ctrl+S")} 保存　${kbd("Ctrl+Z")} 元に戻す　${kbd("Ctrl+Y")} やり直し　${kbd("F1")} このヘルプ<br>
          <span style="color:${C.mid};font-size:11.5px">
            一覧では ${kbd("Ctrl+クリック")} で個別に追加選択、${kbd("Shift+クリック")} で範囲選択。
            フォルダやブックマークの右クリックでメニューが出ます。
            ペインの境界線はドラッグで幅を変更、${kbd("ダブルクリック")}で既定の配分に戻ります。
          </span>`)}

      </div>

      <div style="padding:10px 20px;border-top:1px solid ${C.border};flex:0 0 auto;display:flex;gap:8px;justify-content:flex-end">
        <button id="help-ai-settings" style="padding:6px 16px;border-radius:5px;border:1px solid ${C.border};background:transparent;color:${C.mid};cursor:pointer;font-family:inherit">AI 設定を開く</button>
        <button id="help-close" style="padding:6px 16px;border-radius:5px;border:none;background:${C.accent};color:#050810;cursor:pointer;font-weight:600;font-family:inherit">閉じる</button>
      </div>
    </div>`;
  document.body.appendChild(modal);

  const close = () => modal.remove();
  modal.querySelector("#help-close").addEventListener("click", close);
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
  modal.querySelector("#help-ai-settings").addEventListener("click", () => { close(); cmdAiSettings(); });
  const onEsc = (e) => {
    if (e.key === "Escape") { close(); document.removeEventListener("keydown", onEsc); }
  };
  document.addEventListener("keydown", onEsc);
}

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

  const C = AI_C;

  const keyBadge = status.api_key_set
    ? `<span style="color:${C.green}">● 設定済み (${status.api_key_source === "env" ? "環境変数" : "config.ini"})</span>`
    : `<span style="color:${C.red}">● 未設定</span>`;
  // 単価は models.json（モデルごと）→ config.ini（フォールバック）の順で解決される。
  // どちらから来た値なのかを出さないと、config.ini が空でも実行できる理由が伝わらない。
  const priceSrcLabel = { catalog: "models.json", config: "config.ini" }[status.pricing_source] || "";
  const priceBadge = status.pricing_set
    ? `<span style="color:${C.green}">● 入力 $${status.input_cost_per_1m}/1M, 出力 $${status.output_cost_per_1m}/1M（${priceSrcLabel} 由来）</span>`
    : `<span style="color:${C.red}">● 「${escHtml(status.model)}」の単価が不明 — AI実行はブロックされます</span>`;
  const envNote = status.api_key_source === "env"
    ? `<div style="color:${C.lo};font-size:11px;margin-top:4px">環境変数が優先されています。ここで保存しても環境変数が使われます。</div>`
    : "";
  const paidBadge = status.paid_key_set
    ? `<span style="color:${C.green}">● 登録済み</span>`
    : `<span style="color:${C.lo}">● 未登録（無料枠の上限で止まったとき、切り替え先がありません）</span>`;

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
        <div style="display:flex;flex-direction:column;gap:6px">
          <div style="color:${C.mid};font-size:11px;text-transform:uppercase;letter-spacing:.05em">通常使うAPIキー ${keyBadge}</div>
          <div style="display:flex;gap:8px">
            <input id="ais-key" type="password" placeholder="新しいキーを貼り付け（空欄なら変更なし）"
              style="flex:1;min-width:0;box-sizing:border-box;background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.hi};font-size:12px;padding:7px 9px;outline:none;font-family:inherit">
            <button id="ais-save-key" style="padding:7px 14px;border-radius:5px;border:none;background:${C.accent};color:#050810;cursor:pointer;font-weight:600;font-size:12px;white-space:nowrap;font-family:inherit">保存</button>
          </div>
          <label style="display:flex;align-items:center;gap:7px;cursor:pointer;color:${C.mid};font-size:11.5px">
            <input type="checkbox" id="ais-free-tier" ${status.free_tier === true ? "checked" : ""}
              style="cursor:pointer;accent-color:${C.accent};margin:0">
            このキーは<b style="color:${C.hi}">無料枠</b>（請求先アカウント未設定のプロジェクト）
          </label>
          <div style="color:${C.lo};font-size:11px;line-height:1.6">
            ${status.free_tier == null
              ? `<span style="color:${C.amber}">未申告です。</span>申告すると、見積もり画面で課金の有無を正しく表示できます。`
              : status.free_tier
                ? `課金されません。ただし<b style="color:${C.amber}">送信内容はGoogleの製品改善に利用され、人間のレビュアーが読む場合があります</b>。`
                : `有料枠として扱います。送信内容は製品改善には利用されません。`}
          </div>
          ${envNote}
        </div>

        <div style="display:flex;flex-direction:column;gap:6px;border:1px solid ${C.border};border-radius:7px;padding:11px 12px">
          <div style="color:${C.mid};font-size:11px;text-transform:uppercase;letter-spacing:.05em">有料枠のAPIキー（任意） ${paidBadge}</div>
          <div style="display:flex;gap:8px">
            <input id="ais-paid-key" type="password" placeholder="請求先アカウントを紐付けたプロジェクトのキー"
              style="flex:1;min-width:0;box-sizing:border-box;background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.hi};font-size:12px;padding:7px 9px;outline:none;font-family:inherit">
            <button id="ais-save-paid-key" style="padding:7px 14px;border-radius:5px;border:1px solid ${C.border};background:transparent;color:${C.mid};cursor:pointer;font-size:12px;white-space:nowrap;font-family:inherit">保存</button>
          </div>
          <div style="color:${C.lo};font-size:11px;line-height:1.6">
            分類はまず上の通常キーで実行し、<b style="color:${C.hi}">無料枠の上限で止まったときだけ</b>、確認のうえこちらのキーで残りを続行します。
            勝手に切り替わることはありません。<br>
            枠はキー（プロジェクト）ごとに決まるため、無料と有料を使い分けるには別プロジェクトのキーが2本必要です。
          </div>
        </div>
        <div>
          <div style="color:${C.mid};font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">既定モデル・コスト単価 ${priceBadge}</div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <input id="ais-model" type="text" value="${escHtml(status.model)}" placeholder="モデルID (例: gemini-2.5-flash-lite)"
              style="flex:1 1 200px;min-width:160px;box-sizing:border-box;background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.hi};font-size:12px;padding:7px 9px;outline:none;font-family:inherit">
            <label style="display:flex;align-items:center;gap:4px;color:${C.mid};font-size:11px">
              入力$/1M
              <input id="ais-input-cost" type="number" step="0.001" min="0" value="${status.config_input_cost_per_1m ?? ""}"
                style="width:80px;box-sizing:border-box;background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.hi};font-size:12px;padding:7px 9px;outline:none;font-family:inherit">
            </label>
            <label style="display:flex;align-items:center;gap:4px;color:${C.mid};font-size:11px">
              出力$/1M
              <input id="ais-output-cost" type="number" step="0.001" min="0" value="${status.config_output_cost_per_1m ?? ""}"
                style="width:80px;box-sizing:border-box;background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.hi};font-size:12px;padding:7px 9px;outline:none;font-family:inherit">
            </label>
            <button id="ais-save-pricing" style="padding:7px 14px;border-radius:5px;border:none;background:${C.accent};color:#050810;cursor:pointer;font-weight:600;font-size:12px">単価を保存</button>
          </div>
          <div style="color:${C.lo};font-size:11px;margin-top:4px;line-height:1.6">
            単価は <b>models.json のモデル別価格が優先</b>されます。ここの入力欄は models.json に載っていないモデルを使うときのフォールバックです（下の一覧をクリックすると自動入力）。<br>
            モデルは分類の実行時にも選べます。ここで指定するのはその既定値です。
            <a id="ais-help" href="#" style="color:${C.accent};text-decoration:none">料金の扱いをヘルプで見る →</a>
          </div>
        </div>
        <div>
          <div style="color:${C.mid};font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">利用可能なモデルと料金</div>
          ${modelTable}
        </div>
      </div>
      <div style="padding:10px 20px;border-top:1px solid ${C.border};display:flex;gap:8px;justify-content:flex-end">
        <button id="ais-cancel" style="padding:6px 16px;border-radius:5px;border:none;background:${C.accent};color:#050810;cursor:pointer;font-weight:600">閉じる</button>
      </div>
    </div>`;
  document.body.appendChild(modal);

  const close = () => modal.remove();
  modal.querySelector("#ais-cancel").addEventListener("click", close);
  modal.querySelector("#ais-help").addEventListener("click", (e) => {
    e.preventDefault();
    close();
    cmdHelp();
  });
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
  // 2枠それぞれに保存ボタン。paid フラグで config.ini の保存先が分かれる。
  const saveKey = async (inputId, paid) => {
    const key = modal.querySelector(inputId).value.trim();
    if (!key) return toast("キーが入力されていません", "error");
    try {
      const res = await api("/config/api-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: key, paid }),
      });
      if (res.ok) { toast(res.message); close(); }
      else toast(res.message, "error");
    } catch (e) {
      toast(`保存失敗: ${e.message}`, "error");
    }
  };
  modal.querySelector("#ais-save-key").addEventListener("click", () => saveKey("#ais-key", false));
  modal.querySelector("#ais-save-paid-key").addEventListener("click", () => saveKey("#ais-paid-key", true));

  // 枠の申告。API からは問い合わせられないのでユーザーの自己申告。
  modal.querySelector("#ais-free-tier").addEventListener("change", async (e) => {
    const freeTier = e.target.checked;
    try {
      const res = await api("/config/ai-tier", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ free_tier: freeTier }),
      });
      if (res.ok) toast(res.message);
      else { toast(res.message, "error"); e.target.checked = !freeTier; }
    } catch (err) {
      toast(`保存失敗: ${err.message}`, "error");
      e.target.checked = !freeTier;
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
// AI 系モーダル共通のパレット。styles.css のトークンと同じ色に揃えてある。
const AI_C = {
  bg1: "#111111", bg2: "#161616", bg3: "#1c1c1c", surf: "#232323",
  border: "#262626", accent: "#7c9eff", hi: "#e8e8e8", mid: "#9a9a9a",
  lo: "#555555", green: "#5bcea8", red: "#e06c75", amber: "#e5c07b",
};

function openEstimateGate(est, model) {
  return new Promise((resolve) => {
    const C = AI_C;
    const c = est.cost;
    let usd = "コスト不明";
    if (c.input_cost_usd != null) {
      const low = c.input_cost_usd + (c.output_cost_usd_low || 0);
      const high = c.input_cost_usd + (c.output_cost_usd_high || 0);
      usd = `$${low.toFixed(4)} 〜 $${high.toFixed(4)}`;
    }
    // 無料枠では単価表から出した金額は実際には請求されない。
    // 金額だけを見せると判断材料として誤りになるので、扱いを明示する。
    const free = est.free_tier === true;
    const undeclared = est.free_tier == null;
    const costLabel = free ? "参考コスト" : "推定コスト";
    const costColor = free ? C.mid : C.green;
    const costSuffix = free
      ? `<div style="color:${C.green};font-size:11px;margin-top:2px">無料枠のため請求されません</div>`
      : "";
    const tierNote = free
      ? `送信内容は Google の製品改善に利用され、人間のレビュアーが読む場合があります（無料枠）。`
      : undeclared
        ? `使用中の枠が未申告です。AI設定で申告すると、課金の有無を正しく表示できます。`
        : `送信内容は製品改善には利用されません（有料枠）。`;

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
          ${model ? `<div style="display:flex;justify-content:space-between"><span style="color:${C.mid}">モデル</span><span>${escHtml(model)}</span></div>` : ""}
          <div style="display:flex;justify-content:space-between"><span style="color:${C.mid}">対象件数</span><span>${c.items.toLocaleString()} 件</span></div>
          <div style="display:flex;justify-content:space-between"><span style="color:${C.mid}">チャンク数（API呼び出し）</span><span>${c.chunks}</span></div>
          <div style="display:flex;justify-content:space-between"><span style="color:${C.mid}">入力トークン（推定）</span><span>~${c.input_tokens_est.toLocaleString()}</span></div>
          <div style="display:flex;justify-content:space-between"><span style="color:${C.mid}">出力トークン（推定）</span><span>${c.output_tokens_low.toLocaleString()} 〜 ${c.output_tokens_high.toLocaleString()}</span></div>
          <div style="display:flex;justify-content:space-between;border-top:1px solid ${C.border};padding-top:8px;margin-top:4px">
            <span style="color:${C.mid}">${costLabel}</span>
            <span style="text-align:right"><span style="color:${costColor}">${usd}</span>${costSuffix}</span>
          </div>
          <div style="color:${undeclared ? C.amber : C.lo};font-size:11px;line-height:1.6;margin-top:6px">${tierNote}</div>
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

async function cmdAiClassify() {
  if (!state.bookmarks.length) return toast("ブックマークがありません", "error");

  // 対象はスコープバーで既に決まっている（訊き直さない）。
  const scope = currentScope();
  const ids = scope.ids;
  if (!ids.length) return toast("対象のブックマークがありません", "error");

  // フィールド選択・モデル・追加指示をモーダルで受け取る
  const opts = await openAiClassifyOptions(ids.length, ids);
  if (!opts) return; // cancelled

  // フォルダをスコープに実行した場合のみ、そのフォルダを「このrunの対象」
  // として記録する。適用時、ここに残った未選択・未提案のブックマークは
  // 「その他」へ寄せて元フォルダごと削除する対象になる。選択中/全体スコープ
  // では「まとめて空にすべき単一フォルダ」が存在しないため対象にしない。
  opts.archiveScopePaths = scope.kind === "folder" && scope.folderPath ? [scope.folderPath] : [];

  await runAiClassify(ids, opts);
}

/// 見積もり承認 → 実行 → レビュー、の一連。失敗チャンクの再実行からも呼ぶ。
async function runAiClassify(ids, opts) {
  const payload = {
    bookmark_ids: ids,
    custom_prompt: opts.customPrompt || undefined,
    fields: opts.fields,
    model: opts.model,
    chunk_size: opts.chunkSize,
    use_paid_key: false,
    fresh: !!opts.fresh,
  };

  // 承認ゲート: 送信前にトークン量とコストを見積もり、ユーザーの承認を得る。
  let est;
  try {
    est = await api("/classify/estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    return toast(`見積もりに失敗: ${e.message}`, "error");
  }
  const approved = await openEstimateGate(est, opts.model);
  if (!approved) return; // ユーザーが承認するまで Gemini に送信しない

  // 承認後にのみ実行（SSE）。
  const modal = openAiReviewModal(ids.length, opts);

  try {
    const moves = await runAiClassifySse(payload, modal);
    if (!moves || !moves.length) {
      if (_aiReview.failedIds.length) {
        // 全チャンクが落ちたケース。閉じずに再実行の導線を残す。
        finishAiReviewModal([]);
        await maybeOfferPaidFallback();
        return;
      }
      closeAiReviewModal();
      return toast("AI からの提案がありませんでした");
    }
    finishAiReviewModal(moves);
    await maybeOfferPaidFallback();
  } catch (e) {
    closeAiReviewModal();
    toast(`AI 分類失敗: ${e.message}`, "error");
  }
}

/// AI分類の事前オプション（送信フィールド + 追加指示）をモーダルで選ばせる。
/// resolve({ fields, customPrompt }) / キャンセル時は resolve(null)。
async function openAiClassifyOptions(count, ids) {
  // モデル一覧は models.json（価格付き）から取る。実行時に選ばせないと
  // config.ini の既定モデル1つしか使えず、カタログが死んでいた。
  let catalog = null, currentModel = null;
  try {
    const res = await api("/config/models");
    currentModel = res.current || null;
    catalog = res.catalog?.models || null;
  } catch (_) {}

  // タイトル・説明文・タグが揃っていないと、モデルにはドメインとURLしか
  // 渡らず、分類できない項目が大量に出る。送信前に実データで確認する。
  let readiness = null;
  try {
    readiness = await api("/classify/readiness", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bookmark_ids: ids || [] }),
    });
  } catch (_) {}

  // 対象がフォルダなら、その中に結果を作るのが既定。
  const defaultBase = aiDefaultBaseFolder();
  const folderOptions = existingFolderPaths()
    .map((p2) => `<option value="${escHtml(p2)}"></option>`).join("");

  return new Promise((resolve) => {
    const C = AI_C;
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
            <div style="color:${C.mid};font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">分類方針</div>
            <div style="display:flex;flex-direction:column;gap:8px">
              <label style="display:flex;align-items:flex-start;gap:9px;cursor:pointer">
                <input type="radio" name="aico-strategy" id="aico-strategy-reuse" value="reuse" checked
                  style="cursor:pointer;accent-color:${C.accent};margin:3px 0 0">
                <div>
                  <div style="color:${C.hi};font-size:13px">今の分類に合わせて仕分ける</div>
                  <div style="color:${C.lo};font-size:11px;margin-top:2px">既存フォルダを優先して使う</div>
                </div>
              </label>
              <label style="display:flex;align-items:flex-start;gap:9px;cursor:pointer">
                <input type="radio" name="aico-strategy" id="aico-strategy-fresh" value="fresh"
                  style="cursor:pointer;accent-color:${C.accent};margin:3px 0 0">
                <div>
                  <div style="color:${C.hi};font-size:13px">選んだブックマークだけを見て、フォルダ構成を一から作り直す</div>
                  <div style="color:${C.lo};font-size:11px;margin-top:2px">既存フォルダは無視。対象フォルダは整理後に空にして削除。分類できないものは「その他」フォルダへ</div>
                </div>
              </label>
            </div>
          </div>
          <div>
            <div style="color:${C.mid};font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">新しいフォルダの作成先</div>
            <input id="aico-base" list="aico-folder-list" value="${escHtml(defaultBase)}"
              style="width:100%;box-sizing:border-box;background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.hi};font-size:12px;padding:6px 8px;outline:none;font-family:inherit">
            <datalist id="aico-folder-list">${folderOptions}</datalist>
            <div style="color:${C.lo};font-size:11px;margin-top:5px;line-height:1.6">
              AIが新しく作るフォルダは、ここの下にまとめられます。空欄にするとルート直下に作られます。<br>
              AIが<b>既存のフォルダ</b>を指してきた場合は、作成先に関係なくそのフォルダへ統合されます。
            </div>
          </div>
          <div id="aico-warn" style="display:none"></div>
          <div>
            <div style="color:${C.mid};font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">モデル</div>
            <select id="aico-model" style="width:100%;box-sizing:border-box;background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.hi};font-size:12px;padding:6px 8px;outline:none;font-family:inherit"></select>
            <div id="aico-model-note" style="color:${C.lo};font-size:11px;margin-top:5px;line-height:1.5"></div>
          </div>
          <div>
            <div style="color:${C.mid};font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">AIに渡す情報</div>
            <div id="aico-fields" style="display:flex;flex-direction:column;gap:8px"></div>
          </div>
          <div>
            <div style="color:${C.mid};font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">1回のリクエストに含める件数</div>
            <div style="display:flex;align-items:center;gap:10px">
              <input id="aico-chunk" type="range" min="10" max="300" step="10" value="150" style="flex:1;accent-color:${C.accent}">
              <span id="aico-chunk-n" style="color:${C.hi};font-size:12px;min-width:96px;text-align:right"></span>
            </div>
            <div style="color:${C.lo};font-size:11px;margin-top:5px;line-height:1.5">複数回に分かれる場合は、まず全件からフォルダ構成を決め、その構成に沿って各回を振り分けるので、件数の切り方で結果はほぼ変わりません。大きいほどAPI呼び出しが減りますが、1回の失敗の影響が増え、応答が長くなって途中で切れることがあります（既定150件）。</div>
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

    // --- 分類方針（今の分類に合わせる / 一から作り直す）---
    // 「一から作り直す」を選んだときは、作成先の既定値をスコープフォルダの
    // 直下ではなく一段上（親、なければルート）に切り替える。ユーザーが既に
    // 手で書き換えていた場合はそちらを尊重して上書きしない。
    const baseInputEl = modal.querySelector("#aico-base");
    let baseTouched = false;
    baseInputEl.addEventListener("input", () => { baseTouched = true; });
    const strategyRadios = modal.querySelectorAll('input[name="aico-strategy"]');
    for (const r of strategyRadios) {
      r.addEventListener("change", () => {
        if (baseTouched) return;
        const fresh = modal.querySelector("#aico-strategy-fresh").checked;
        baseInputEl.value = fresh ? aiFreshDefaultBaseFolder() : defaultBase;
      });
    }

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
      cb.addEventListener("change", renderWarning);
      row.append(cb, txt);
      fieldsEl.appendChild(row);
    }

    // --- 素材不足の警告 ---
    // 「何が足りないか」だけでなく「先に何を実行すればいいか」まで出す。
    // 選んだフィールドに対してのみ警告する（説明文を送らないなら、
    // 説明文が空でも問題にならない）。
    const warnEl = modal.querySelector("#aico-warn");
    function selectedFields() {
      const f = {};
      fieldsEl.querySelectorAll("input[type=checkbox]").forEach((cb) => { f[cb.dataset.key] = cb.checked; });
      return f;
    }
    function renderWarning() {
      if (!readiness || !readiness.total) { warnEl.style.display = "none"; return; }
      const f = selectedFields();
      const total = readiness.total;
      const pct = (n) => Math.round((n / total) * 100);
      const problems = [];

      if (f.tags && readiness.with_tags < total) {
        problems.push({
          n: total - readiness.with_tags,
          text: `タグ未取得 ${total - readiness.with_tags} 件（${100 - pct(readiness.with_tags)}%）`,
          fix: "「自動でタグを付ける」",
        });
      }
      if (f.title && readiness.with_title < total) {
        problems.push({
          n: total - readiness.with_title,
          text: `タイトル空 ${total - readiness.with_title} 件（${100 - pct(readiness.with_title)}%）`,
          fix: "「タイトルをWebから取得」",
        });
      }
      if (f.description && readiness.with_description < total) {
        problems.push({
          n: total - readiness.with_description,
          text: `説明文未取得 ${total - readiness.with_description} 件（${100 - pct(readiness.with_description)}%）`,
          fix: "「説明文をWebから取得」",
        });
      }

      if (!problems.length && !readiness.bare) { warnEl.style.display = "none"; return; }

      // ドメインとURLしか手がかりがない件数。分類不能が出る直接の原因。
      const severe = readiness.bare > total * 0.3;
      const color = severe ? C.red : C.amber;
      const barePart = readiness.bare
        ? `<div style="color:${color};font-size:12px;font-weight:600;margin-bottom:5px">
             ${readiness.bare} 件（${pct(readiness.bare)}%）は、タイトル・タグ・説明文がすべて空です
           </div>
           <div style="color:${C.mid};font-size:11px;line-height:1.6;margin-bottom:6px">
             これらはドメインとURLだけで判断されるため、分類できず提案から漏れる可能性が高くなります。
           </div>`
        : "";
      const listPart = problems.length
        ? `<ul style="margin:0;padding-left:16px;color:${C.mid};font-size:11px;line-height:1.75">
             ${problems.map((p) => `<li>${escHtml(p.text)} → 先に ${escHtml(p.fix)} を実行すると精度が上がります</li>`).join("")}
           </ul>`
        : "";

      warnEl.innerHTML = `
        <div style="border:1px solid ${color};border-radius:7px;padding:10px 12px;background:rgba(229,192,123,.06)">
          <div style="color:${color};font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;margin-bottom:6px">
            ⚠ 分類材料が不足しています
          </div>
          ${barePart}${listPart}
          <div style="color:${C.lo};font-size:11px;line-height:1.6;margin-top:7px">
            推奨順：タイトル取得 → 説明文取得 → 自動タグ付け → AI分類
          </div>
        </div>`;
      warnEl.style.display = "block";
    }
    renderWarning();

    // --- モデル選択 ---
    const modelSel = modal.querySelector("#aico-model");
    const modelNote = modal.querySelector("#aico-model-note");
    const models = catalog && catalog.length
      ? catalog
      : [{ id: currentModel || "gemini-2.5-flash-lite", label: currentModel || "既定モデル", note: "models.json を読み込めませんでした。" }];
    for (const m of models) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = m.label || m.id;
      if (m.recommended) opt.textContent += "（推奨）";
      modelSel.appendChild(opt);
    }
    // 既定は config.ini の設定値、無ければ推奨、それも無ければ先頭。
    modelSel.value =
      (currentModel && models.some((m) => m.id === currentModel)) ? currentModel
      : (models.find((m) => m.recommended) || models[0]).id;

    const renderModelNote = () => {
      const m = models.find((x) => x.id === modelSel.value);
      if (!m) { modelNote.textContent = ""; return; }
      const price = (m.input_per_1m != null && m.output_per_1m != null)
        ? `　入力 $${m.input_per_1m}/1M・出力 $${m.output_per_1m}/1M`
        : "　単価不明（見積もりできません）";
      modelNote.textContent = `${m.note || ""}${price}`;
    };
    modelSel.addEventListener("change", renderModelNote);
    renderModelNote();

    // --- チャンクサイズ ---
    const chunkEl = modal.querySelector("#aico-chunk");
    const chunkNEl = modal.querySelector("#aico-chunk-n");
    const renderChunk = () => {
      const n = parseInt(chunkEl.value, 10);
      const calls = Math.ceil(count / n);
      chunkNEl.textContent = `${n} 件 × ${calls} 回`;
    };
    chunkEl.addEventListener("input", renderChunk);
    renderChunk();

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
      const finish = () => close({
        fields,
        customPrompt,
        model: modelSel.value,
        chunkSize: parseInt(chunkEl.value, 10),
        baseFolder: modal.querySelector("#aico-base").value.trim(),
        fresh: modal.querySelector("#aico-strategy-fresh").checked,
      });

      // 材料が大きく欠けている場合だけ、明示的に確認を挟む。
      // ブロックはしない（ドメインだけで分類したいこともある）。
      if (readiness && readiness.total && readiness.bare > readiness.total * 0.3) {
        confirmDialog(
          `${readiness.bare} 件（全体の ${Math.round((readiness.bare / readiness.total) * 100)}%）は\n` +
          `タイトル・タグ・説明文がすべて空です。\n\n` +
          `このまま実行すると、多くが分類できず提案から漏れる見込みです。\n` +
          `先に「タイトルをWebから取得」→「自動でタグを付ける」を実行することを推奨します。\n\n` +
          `それでもこのまま実行しますか?`,
          { okLabel: "このまま実行", cancelLabel: "戻る" }
        ).then((ok) => { if (ok) finish(); });
        return;
      }
      finish();
    });
  });
}

function runAiClassifySse(payload, modal) {
  return new Promise((resolve, reject) => {
    fetch(API_BASE + "/classify/ai", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
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
          let ev;
          try { ev = JSON.parse(json); } catch (_) { continue; }
          updateAiModalProgress(modal, ev);
          if (ev.status === "done") finalMoves = ev.chunk_moves || [];
        }
      }
      resolve(finalMoves);
    }).catch(reject);
  });
}

// --- AI Review Modal -------------------------------------------------------
//
// 提案はフォルダ単位でまとめて見せる。フラットな1行リストでは「AIがどんな
// 構成を作ろうとしているか」が読めず、263件が並ぶだけだった。
// 提案は bookmark_id をキーに保持し、表示のたびにグループを導出する。
// こうしておくと、途中経過の暫定表示・確定結果・失敗分の再実行が
// すべて同じ Map への上書きで済み、重複が生じない。

let _aiModal = null;
let _aiReview = null;

function newAiReviewState(opts) {
  return {
    opts,
    byId: new Map(),        // bookmark_id -> { folder, confidence, reason, checked, title, from }
    failedIds: [],
    quotaExhausted: false,  // 枠の上限で打ち切られたか
    modelUnavailable: false, // モデルが利用不可で打ち切られたか（再送では直らない）
    usingPaidKey: false,    // 有料枠のキーに切り替え済みか
    expanded: new Set(),    // 展開中のフォルダ
    query: "",
    minConfidence: 0.7,
    finished: false,
    requested: 0,
    base: "_AI",       // 新規フォルダの作成先
  };
}

/// ツリー上に実在するフォルダのフルパス一覧（移動先の候補・統合先に使う）。
function existingFolderPaths() {
  const out = [];
  const walk = (node, prefix) => {
    for (const c of node.children || []) {
      if (c.type !== "folder") continue;
      const path = prefix ? `${prefix}/${c.title}` : c.title;
      out.push(path);
      walk(c, path);
    }
  };
  if (state.treeRoot) walk(state.treeRoot, "");
  return out;
}

/// 実行対象がフォルダなら、その中に結果を作る。「フォルダを選んで分類」は
/// そのフォルダを整理する操作なので、離れた `_AI/` に積まれるのは想定外。
/// 全体・選択中を対象にした場合は既存構造を壊さないよう `_AI/` に寄せる。
function aiDefaultBaseFolder() {
  const sc = currentScope();
  if (sc.kind === "folder" && sc.folderPath) return sc.folderPath;
  return "_AI";
}

/// 「選んだブックマークだけを見て、フォルダ構成を一から作り直す」場合の
/// 既定の作成先。元のフォルダの中に新設すると、対象フォルダ自体が空になっ
/// て消えるべき、という結果と矛盾するので、一段上（親、なければルート）に
/// 作る。フォルダ以外のスコープ（選択中・全体）はそもそも「片付けるべき
/// 元フォルダ」がないので、ルート直下でよい。
function aiFreshDefaultBaseFolder() {
  const sc = currentScope();
  if (sc.kind === "folder" && sc.folderPath) {
    const parts = sc.folderPath.split("/").filter(Boolean);
    parts.pop();
    return parts.join("/");
  }
  return "";
}

/// AI が返したフォルダ名を実際の移動先パスに変換する。
/// 既存フォルダをそのまま指してきた場合はその場所へ（＝統合）、
/// 新しく考えた名前なら作成先ベースの下に作る。
function aiInitialTarget(folder, existingSet) {
  const clean = String(folder || "").replace(/^\/+|\/+$/g, "");
  const base = (_aiReview?.base ?? "_AI").replace(/^\/+|\/+$/g, "");
  if (!clean) return base ? `${base}/Unsorted` : "Unsorted";
  if (existingSet.has(clean)) return clean;
  return base ? `${base}/${clean}` : clean;
}

/// moves を取り込む。replace=true で総入れ替え（確定結果の反映）。
function aiIngestMoves(moves, replace) {
  if (!_aiReview) return;
  if (replace) _aiReview.byId.clear();

  const existingSet = new Set(existingFolderPaths());
  const bmById = new Map(state.bookmarks.map((b) => [b.bookmark_id, b]));

  for (const mv of moves || []) {
    const bm = bmById.get(mv.bookmark_id);
    const prev = _aiReview.byId.get(mv.bookmark_id);
    _aiReview.byId.set(mv.bookmark_id, {
      folder: aiInitialTarget(mv.folder, existingSet),
      confidence: mv.confidence ?? 0,
      reason: mv.reason || "",
      title: bm ? (bm.title || bm.url || mv.bookmark_id) : mv.bookmark_id.slice(0, 8),
      from: bm ? (bm.folder_path || "ルート") : "",
      // ユーザーが触ったチェック状態は保持する
      checked: prev ? prev.checked : (mv.confidence ?? 0) >= _aiReview.minConfidence,
    });
  }
}

/// byId からフォルダ単位のグループを導出する（件数の多い順）。
function aiGroups() {
  const byFolder = new Map();
  for (const [id, m] of _aiReview.byId) {
    if (!byFolder.has(m.folder)) byFolder.set(m.folder, []);
    byFolder.get(m.folder).push({ id, ...m });
  }
  return [...byFolder.entries()]
    .map(([folder, items]) => ({ folder, items }))
    .sort((a, b) => b.items.length - a.items.length || a.folder.localeCompare(b.folder));
}

function openAiReviewModal(total, opts) {
  if (_aiModal) _aiModal.remove();
  _aiReview = newAiReviewState(opts);
  _aiReview.requested = total;
  _aiReview.base = opts?.baseFolder || aiDefaultBaseFolder();

  const C = AI_C;
  const div = document.createElement("div");
  div.id = "ai-review-modal";
  div.style.cssText =
    "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:9999;display:flex;align-items:center;justify-content:center;font-family:inherit";
  div.innerHTML = `
    <div style="background:${C.bg1};border:1px solid ${C.border};border-radius:10px;width:820px;max-width:95vw;height:82vh;display:flex;flex-direction:column;overflow:hidden">

      <div style="padding:14px 20px 11px;border-bottom:1px solid ${C.border};flex:0 0 auto">
        <div style="color:${C.hi};font-size:15px;font-weight:600">AI 分類の提案</div>
        <div id="ai-sub" style="color:${C.lo};font-size:11px;margin-top:3px">${total.toLocaleString()} 件を送信します</div>
      </div>

      <div id="ai-run-area" style="padding:12px 20px;border-bottom:1px solid ${C.border};flex:0 0 auto;display:flex;flex-direction:column;gap:8px">
        <div style="background:${C.surf};border-radius:3px;height:4px;overflow:hidden">
          <div id="ai-progress-inner" style="background:${C.accent};height:100%;width:0;border-radius:3px;transition:width .3s"></div>
        </div>
        <div id="ai-status" style="color:${C.mid};font-size:12px">接続中…</div>
        <div id="ai-cost-info" style="color:${C.green};font-size:11px;display:none"></div>
        <div id="ai-error-log" style="display:none;flex-direction:column;gap:3px;max-height:96px;overflow-y:auto;background:${C.bg1};border:1px solid ${C.border};border-radius:5px;padding:7px;font-size:11px;color:${C.red}"></div>
      </div>

      <div id="ai-toolbar" style="display:none;padding:9px 20px;border-bottom:1px solid ${C.border};flex:0 0 auto;align-items:center;gap:8px;flex-wrap:wrap">
        <input id="ai-search" placeholder="タイトル・フォルダで絞り込み"
          style="flex:1;min-width:150px;background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.hi};font-size:12px;padding:5px 8px;outline:none;font-family:inherit">
        <select id="ai-conf" style="background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.mid};font-size:11px;padding:5px 6px;outline:none;font-family:inherit">
          <option value="0.9">信頼度 90% 以上を選択</option>
          <option value="0.7" selected>信頼度 70% 以上を選択</option>
          <option value="0.5">信頼度 50% 以上を選択</option>
          <option value="0">すべて選択</option>
        </select>
        <button id="ai-uncheck-all" style="background:transparent;border:1px solid ${C.border};border-radius:5px;color:${C.mid};font-size:11px;padding:5px 10px;cursor:pointer;font-family:inherit">全解除</button>
        <button id="ai-toggle-expand" style="background:transparent;border:1px solid ${C.border};border-radius:5px;color:${C.mid};font-size:11px;padding:5px 10px;cursor:pointer;font-family:inherit">すべて展開</button>
        <label style="display:flex;align-items:center;gap:6px;color:${C.mid};font-size:11px;white-space:nowrap">
          新規フォルダの作成先
          <input id="ai-base" list="ai-folder-list" title="ここを変えると、新しく作るフォルダの置き場所をまとめて付け替えます"
            style="width:190px;background:${C.bg3};border:1px solid ${C.border};border-radius:5px;color:${C.hi};font-size:11px;padding:4px 7px;outline:none;font-family:inherit">
        </label>
      </div>

      <div id="ai-retry" style="display:none;padding:9px 20px;border-bottom:1px solid ${C.border};flex:0 0 auto;align-items:center;justify-content:space-between;gap:10px;background:rgba(224,108,117,.07)">
        <span id="ai-retry-msg" style="color:${C.red};font-size:12px"></span>
        <button id="ai-retry-btn" style="background:transparent;border:1px solid ${C.red};border-radius:5px;color:${C.red};font-size:11px;padding:5px 12px;cursor:pointer;white-space:nowrap;font-family:inherit">失敗分だけ再実行</button>
      </div>

      <div id="ai-review-list" style="flex:1 1 0;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding:10px 20px;display:none;flex-direction:column;gap:6px"></div>

      <div id="ai-modal-actions" style="display:none;padding:11px 20px;border-top:1px solid ${C.border};flex:0 0 auto;align-items:center;justify-content:space-between;gap:12px">
        <label style="display:flex;align-items:center;gap:7px;cursor:pointer;color:${C.mid};font-size:11px"
          title="フォルダを対象に実行した場合、そのフォルダに取り残された(未選択・AIが提案しなかった)ブックマークは「その他」フォルダへ移動したうえで、元フォルダを削除します。">
          <input type="checkbox" id="ai-prune-empty" style="cursor:pointer;accent-color:${C.accent};margin:0">
          元フォルダを整理して削除(取り残しは「その他」へ)
        </label>
        <div style="display:flex;align-items:center;gap:10px">
          <span id="ai-selected-count" style="color:${C.mid};font-size:11px"></span>
          <button id="ai-btn-cancel" style="padding:7px 16px;border-radius:5px;border:1px solid ${C.border};background:transparent;color:${C.mid};cursor:pointer;font-family:inherit">キャンセル</button>
          <button id="ai-btn-apply-selected" style="padding:7px 16px;border-radius:5px;border:none;background:${C.accent};color:#050810;cursor:pointer;font-weight:600;font-family:inherit">選択した提案を適用</button>
        </div>
      </div>

      <style>#ai-review-list > * { flex: 0 0 auto; }</style>
      <datalist id="ai-folder-list"></datalist>
    </div>`;
  document.body.appendChild(div);
  _aiModal = div;

  // 「一から作り直す」で実行した場合は、対象フォルダが空になったら消える
  // のが期待される結果なので、削除チェックを既定でONにしておく
  // （ユーザーはOFFに戻せる）。
  if (opts?.fresh) {
    const pruneEl = div.querySelector("#ai-prune-empty");
    if (pruneEl) pruneEl.checked = true;
  }

  const list = document.getElementById("ai-folder-list");
  for (const p of existingFolderPaths()) {
    const o = document.createElement("option");
    o.value = p;
    list.appendChild(o);
  }

  div.querySelector("#ai-btn-cancel").addEventListener("click", closeAiReviewModal);
  div.querySelector("#ai-search").addEventListener("input", (e) => {
    _aiReview.query = e.target.value.trim().toLowerCase();
    renderAiReview();
  });
  div.querySelector("#ai-conf").addEventListener("change", (e) => {
    const th = parseFloat(e.target.value);
    _aiReview.minConfidence = th;
    for (const m of _aiReview.byId.values()) m.checked = m.confidence >= th;
    renderAiReview();
  });
  div.querySelector("#ai-uncheck-all").addEventListener("click", () => {
    for (const m of _aiReview.byId.values()) m.checked = false;
    renderAiReview();
  });
  div.querySelector("#ai-toggle-expand").addEventListener("click", (e) => {
    const groups = aiGroups();
    const allOpen = groups.length > 0 && groups.every((g) => _aiReview.expanded.has(g.folder));
    _aiReview.expanded = allOpen ? new Set() : new Set(groups.map((g) => g.folder));
    e.target.textContent = allOpen ? "すべて展開" : "すべて閉じる";
    renderAiReview();
  });
  const baseInput = div.querySelector("#ai-base");
  if (baseInput) {
    baseInput.value = _aiReview.base;
    // 作成先を変えたら、まだそのベースの下にいるグループだけ付け替える。
    // 個別に編集済みのグループや、既存フォルダへの統合はそのまま残す。
    baseInput.addEventListener("change", () => {
      const oldBase = _aiReview.base.replace(/^\/+|\/+$/g, "");
      const newBase = baseInput.value.trim().replace(/^\/+|\/+$/g, "");
      if (newBase === oldBase) return;
      const prefix = oldBase ? oldBase + "/" : "";
      for (const m of _aiReview.byId.values()) {
        if (!prefix || m.folder.startsWith(prefix)) {
          const rest = prefix ? m.folder.slice(prefix.length) : m.folder;
          m.folder = newBase ? `${newBase}/${rest}` : rest;
        }
      }
      _aiReview.base = newBase;
      _aiReview.expanded = new Set();
      renderAiReview();
      toast(newBase ? `新規フォルダの作成先: ${newBase}` : "新規フォルダをルート直下に作ります");
    });
  }

  div.querySelector("#ai-retry-btn").addEventListener("click", () => {
    if (_aiReview?.modelUnavailable) cmdAiSettings();
    else if (_aiReview?.quotaExhausted && !_aiReview.usingPaidKey) maybeOfferPaidFallback();
    else retryFailedChunks();
  });
  div.querySelector("#ai-btn-apply-selected").addEventListener("click", applyAiReview);

  return div;
}

function closeAiReviewModal() {
  if (_aiModal) { _aiModal.remove(); _aiModal = null; }
  _aiReview = null;
}

function showAiRunArea(on) {
  const area = _aiModal?.querySelector("#ai-run-area");
  if (area) area.style.display = on ? "flex" : "none";
}

/// 実行完了。確定した moves で総入れ替えし、レビューUIを出す。
function finishAiReviewModal(moves) {
  if (!_aiModal || !_aiReview) return;
  _aiReview.finished = true;
  aiIngestMoves(moves, true);

  const proposed = _aiReview.byId.size;
  const requested = _aiReview.requested || proposed;
  const skipped = Math.max(0, requested - proposed - _aiReview.failedIds.length);
  const sub = _aiModal.querySelector("#ai-sub");
  if (sub) {
    const parts = [`${requested.toLocaleString()} 件中 ${proposed.toLocaleString()} 件に提案`];
    // 「該当なし」はエラーではない。材料不足か、既存構成に馴染まなかったか。
    if (skipped) parts.push(`${skipped.toLocaleString()} 件は該当なし（移動しません）`);
    if (_aiReview.failedIds.length) parts.push(`${_aiReview.failedIds.length.toLocaleString()} 件は未処理`);
    sub.textContent = parts.join(" · ");
  }
  showAiRunArea(_aiReview.failedIds.length > 0);
  _aiModal.querySelector("#ai-toolbar").style.display = "flex";
  _aiModal.querySelector("#ai-review-list").style.display = "flex";
  _aiModal.querySelector("#ai-modal-actions").style.display = "flex";
  renderAiReview();
}

function updateAiModalProgress(modal, ev) {
  if (!modal) return;
  const C = AI_C;
  const pct = ev.total ? Math.round((ev.processed / ev.total) * 100) : 0;
  const inner = modal.querySelector("#ai-progress-inner");
  if (inner) inner.style.width = pct + "%";
  const status = modal.querySelector("#ai-status");
  if (status) {
    if (ev.status === "start") status.textContent = "Gemini へ送信中…";
    else if (ev.status === "progress") status.textContent = `処理中 ${ev.processed}/${ev.total} 件`;
    else if (ev.status === "waiting") status.textContent = `⏳ ${ev.error}`;
    else if (ev.status === "chunk_error") status.textContent = `エラー (一部スキップ): ${ev.error}`;
    else if (ev.status === "quota_exhausted") status.textContent = `⛔ ${ev.error}`;
    else if (ev.status === "model_unavailable") status.textContent = `⛔ ${ev.error}`;
    else if (ev.status === "done") status.textContent = "完了 — 提案を確認してください";
    else if (ev.status === "error") status.textContent = `エラー: ${ev.error}`;
  }

  // 途中経過を暫定表示する。SSE ではチャンクごとに結果が届いているのに、
  // 完了までリストが空のままで、数十秒〜数分ただ待つ画面になっていた。
  if (ev.status === "progress" && ev.chunk_moves && ev.chunk_moves.length && _aiReview) {
    aiIngestMoves(ev.chunk_moves, false);
    const listEl = modal.querySelector("#ai-review-list");
    if (listEl) listEl.style.display = "flex";
    renderAiReview();
  }

  // 失敗チャンク・枠切れの id を控えておき、再実行の導線を出す。
  if (
    (ev.status === "chunk_error" || ev.status === "quota_exhausted" || ev.status === "model_unavailable") &&
    ev.failed_ids && _aiReview
  ) {
    for (const id of ev.failed_ids) {
      if (!_aiReview.failedIds.includes(id)) _aiReview.failedIds.push(id);
    }
    if (ev.status === "quota_exhausted") _aiReview.quotaExhausted = true;
    // A same-model retry cannot succeed here — the model itself is gone —
    // so this is tracked separately from quotaExhausted, which does retry.
    if (ev.status === "model_unavailable") _aiReview.modelUnavailable = true;
    renderAiRetryBar();
  }

  // チャンクエラーはステータス行だと次の進捗で上書きされて消えてしまうため、
  // 専用のログ欄に積み上げて完了後も読めるようにする。
  if (
    ev.status === "chunk_error" || ev.status === "error" ||
    ev.status === "quota_exhausted" || ev.status === "model_unavailable"
  ) {
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
      let usd;
      if (c.input_cost_usd != null) {
        const low = c.input_cost_usd + (c.output_cost_usd_low || 0);
        const high = c.input_cost_usd + (c.output_cost_usd_high || 0);
        usd = ` | 推定コスト: $${low.toFixed(4)}〜$${high.toFixed(4)}`;
      } else {
        usd = " | コスト不明";
      }
      info.textContent = `入力 ~${c.input_tokens_est.toLocaleString()} tokens | ${c.chunks} 回の呼び出し${usd}`;
      info.style.display = "block";
    }
  }

  const sub = modal.querySelector("#ai-sub");
  if (sub && ev.total) {
    sub.textContent = ev.status === "done"
      ? `${ev.total.toLocaleString()} 件を処理しました`
      : `${ev.total.toLocaleString()} 件を処理中`;
  }
  if (status) {
    status.style.color =
      (ev.status === "error" || ev.status === "quota_exhausted" || ev.status === "model_unavailable")
        ? C.red : C.mid;
  }
}

/// 再実行バーの文面は、単発の送信失敗か枠切れかで変える。
function renderAiRetryBar() {
  if (!_aiModal || !_aiReview) return;
  const bar = _aiModal.querySelector("#ai-retry");
  const msg = _aiModal.querySelector("#ai-retry-msg");
  const btn = _aiModal.querySelector("#ai-retry-btn");
  if (!bar || !msg || !btn) return;
  if (!_aiReview.failedIds.length) { bar.style.display = "none"; return; }

  const n = _aiReview.failedIds.length;
  if (_aiReview.modelUnavailable) {
    // Retrying with the same model would just reproduce the same 404 — point
    // at AI settings instead of offering a retry that cannot work.
    const model = _aiReview.opts?.model || "";
    msg.textContent = `モデル「${model}」が利用できないため中断しました（未処理 ${n} 件）`;
    btn.textContent = "AI設定を開く";
  } else if (_aiReview.quotaExhausted && !_aiReview.usingPaidKey) {
    msg.textContent = `無料枠の上限に達したため中断しました（未処理 ${n} 件）`;
    btn.textContent = "有料枠のキーで続ける";
  } else {
    msg.textContent = `${n} 件が分類できませんでした（チャンクの送信に失敗）`;
    btn.textContent = _aiReview.usingPaidKey ? "失敗分を再実行（有料枠）" : "失敗分だけ再実行";
  }
  bar.style.display = "flex";
}

/// 枠切れで打ち切られたとき、有料枠のキーで続けるかを尋ねる。
/// 枠はプロジェクト単位で決まるため、続行には有料枠プロジェクトのキーが要る。
async function maybeOfferPaidFallback() {
  if (!_aiReview || !_aiReview.quotaExhausted || _aiReview.usingPaidKey) return;
  const n = _aiReview.failedIds.length;
  if (!n) return;

  let status = null;
  try { status = await api("/config/ai-status"); } catch (_) {}

  if (!status?.paid_key_set) {
    const open = await confirmDialog(
      `無料枠の上限に達したため、${n} 件が未処理のまま中断しました。

` +
      `続けるには、請求先アカウントを紐付けたプロジェクトのAPIキー（有料枠のキー）が必要です。
` +
      `枠はキー（プロジェクト）ごとに決まるため、同じキーで待っても当日中は解消しません。

` +
      `AI設定を開いて有料枠のキーを登録しますか?`,
      { okLabel: "AI設定を開く", cancelLabel: "あとで" }
    );
    if (open) cmdAiSettings();
    return;
  }

  const go = await confirmDialog(
    `無料枠の上限に達したため、${n} 件が未処理のまま中断しました。

` +
    `登録済みの有料枠のキーで残りを処理しますか?
` +
    `※ こちらは実際に課金されます。送信前にもう一度、見積もりを確認できます。`,
    { okLabel: "有料枠で続ける", cancelLabel: "中断したままにする" }
  );
  if (!go) return;
  await retryFailedChunks({ usePaidKey: true });
}

// --- Review rendering ------------------------------------------------------

function renderAiReview() {
  if (!_aiModal || !_aiReview) return;
  const C = AI_C;
  const listEl = _aiModal.querySelector("#ai-review-list");
  if (!listEl) return;

  const q = _aiReview.query;
  const matches = (it, folder) =>
    !q || it.title.toLowerCase().includes(q) || folder.toLowerCase().includes(q);

  listEl.innerHTML = "";
  const groups = aiGroups();

  if (!groups.length) {
    const empty = document.createElement("div");
    empty.style.cssText = `color:${C.lo};font-size:12px;padding:20px;text-align:center`;
    empty.textContent = _aiReview.finished ? "提案はありませんでした。" : "提案を待っています…";
    listEl.appendChild(empty);
    updateAiSelectedCount();
    return;
  }

  for (const g of groups) {
    const shown = g.items.filter((it) => matches(it, g.folder));
    if (!shown.length) continue;

    const box = document.createElement("div");
    box.style.cssText = `border:1px solid ${C.border};border-radius:7px;overflow:hidden`;

    // --- グループ見出し: フォルダ名は編集でき、既存フォルダ名を入れれば統合される ---
    const head = document.createElement("div");
    head.style.cssText = `display:flex;align-items:center;gap:9px;padding:8px 10px;background:${C.bg2}`;

    const groupCb = document.createElement("input");
    groupCb.type = "checkbox";
    groupCb.style.cssText = `cursor:pointer;accent-color:${C.accent};margin:0;flex:0 0 auto`;
    const checkedN = g.items.filter((it) => it.checked).length;
    groupCb.checked = checkedN === g.items.length;
    groupCb.indeterminate = checkedN > 0 && checkedN < g.items.length;
    groupCb.addEventListener("change", () => {
      for (const it of g.items) _aiReview.byId.get(it.id).checked = groupCb.checked;
      renderAiReview();
    });

    const caret = document.createElement("button");
    const open = _aiReview.expanded.has(g.folder);
    caret.textContent = open ? "▾" : "▸";
    caret.title = open ? "閉じる" : "中身を見る";
    caret.style.cssText = `background:none;border:none;color:${C.mid};cursor:pointer;font-size:12px;padding:0 2px;flex:0 0 auto;font-family:inherit`;
    caret.addEventListener("click", () => {
      if (open) _aiReview.expanded.delete(g.folder);
      else _aiReview.expanded.add(g.folder);
      renderAiReview();
    });

    const nameInput = document.createElement("input");
    nameInput.value = g.folder;
    nameInput.setAttribute("list", "ai-folder-list");
    nameInput.title = "移動先。既存フォルダのパスを入れるとそのフォルダに統合されます。";
    nameInput.style.cssText =
      `flex:1;min-width:0;background:transparent;border:1px solid transparent;border-radius:4px;color:${C.hi};font-size:12.5px;padding:3px 6px;outline:none;font-family:inherit`;
    nameInput.addEventListener("focus", () => {
      nameInput.style.background = C.bg3;
      nameInput.style.borderColor = C.accent;
    });
    nameInput.addEventListener("blur", () => {
      nameInput.style.background = "transparent";
      nameInput.style.borderColor = "transparent";
      const next = nameInput.value.trim().replace(/^\/+|\/+$/g, "");
      if (!next || next === g.folder) { nameInput.value = g.folder; return; }
      for (const it of g.items) _aiReview.byId.get(it.id).folder = next;
      if (_aiReview.expanded.delete(g.folder)) _aiReview.expanded.add(next);
      renderAiReview();
    });
    nameInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); nameInput.blur(); }
      if (e.key === "Escape") { nameInput.value = g.folder; nameInput.blur(); }
    });

    const avg = Math.round(
      (g.items.reduce((s, it) => s + it.confidence, 0) / g.items.length) * 100
    );
    const meta = document.createElement("span");
    meta.style.cssText = `color:${C.lo};font-size:11px;white-space:nowrap;flex:0 0 auto`;
    meta.textContent = `${g.items.length} 件 · 平均 ${avg}%`;

    head.append(groupCb, caret, nameInput, meta);
    box.appendChild(head);

    // --- 中身（既定は閉じている。まず構成を俯瞰できるように） ---
    if (open || q) {
      const body = document.createElement("div");
      body.style.cssText = "display:flex;flex-direction:column";
      for (const it of shown) {
        const row = document.createElement("label");
        row.style.cssText =
          `display:grid;grid-template-columns:auto 1fr auto;gap:4px 9px;align-items:center;padding:6px 10px 6px 30px;border-top:1px solid ${C.border};cursor:pointer`;

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = it.checked;
        cb.style.cssText = `cursor:pointer;accent-color:${C.accent};margin:0`;
        cb.addEventListener("change", () => {
          _aiReview.byId.get(it.id).checked = cb.checked;
          updateAiSelectedCount();
          // 見出しの三状態チェックだけ更新すれば足りるので全再描画はしない
          const n = g.items.filter((x) => _aiReview.byId.get(x.id).checked).length;
          groupCb.checked = n === g.items.length;
          groupCb.indeterminate = n > 0 && n < g.items.length;
        });

        const title = document.createElement("div");
        title.style.cssText = `color:${C.hi};font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap`;
        title.textContent = it.title;
        title.title = it.title;

        const pct = document.createElement("span");
        const conf = Math.round(it.confidence * 100);
        pct.style.cssText =
          `font-size:11px;white-space:nowrap;color:${conf >= 70 ? C.green : conf >= 50 ? C.amber : C.red}`;
        pct.textContent = `${conf}%`;

        row.append(cb, title, pct);

        // 理由はツールチップではなく本文に出す。判断材料が隠れていた。
        const sub = document.createElement("div");
        sub.style.cssText = `grid-column:2 / span 2;color:${C.lo};font-size:11px;line-height:1.4;overflow:hidden;text-overflow:ellipsis;white-space:nowrap`;
        sub.textContent = it.reason ? `${it.from} → ${it.reason}` : `元: ${it.from}`;
        sub.title = it.reason || "";
        row.appendChild(sub);

        body.appendChild(row);
      }
      box.appendChild(body);
    }

    listEl.appendChild(box);
  }

  updateAiSelectedCount();
}

function updateAiSelectedCount() {
  if (!_aiModal || !_aiReview) return;
  let n = 0;
  for (const m of _aiReview.byId.values()) if (m.checked) n++;
  const label = _aiModal.querySelector("#ai-selected-count");
  if (label) label.textContent = `${n} 件を選択中`;
  const apply = _aiModal.querySelector("#ai-btn-apply-selected");
  if (apply) {
    apply.disabled = n === 0;
    apply.style.opacity = n === 0 ? ".4" : "1";
    apply.style.cursor = n === 0 ? "not-allowed" : "pointer";
  }
}

async function applyAiReview() {
  if (!_aiReview) return;
  const moves = [];
  for (const [id, m] of _aiReview.byId) {
    if (m.checked) moves.push({ bookmark_id: id, folder_path: m.folder });
  }
  if (!moves.length) return toast("チェックされた項目がありません");

  const pruneEmpty = !!_aiModal?.querySelector("#ai-prune-empty")?.checked;
  try {
    const res = await api("/classify/ai-apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        moves,
        prune_empty_source: pruneEmpty,
        archive_scope_paths: pruneEmpty ? (_aiReview.opts?.archiveScopePaths || []) : [],
        // 取り残し(未選択・AI未提案)は、AI自身の分類不能グループと同じ「その他」へ
        leftover_folder: `${_aiReview.base ? _aiReview.base + "/" : ""}その他`,
      }),
    });
    closeAiReviewModal();
    await reload();
    try {
      const h = await api("/edit/history");
      updateUndoRedoButtons(h.undo_count, h.redo_count);
    } catch (_) {}
    const prunedMsg = res.pruned ? `、空フォルダ ${res.pruned} 件削除` : "";
    const archivedMsg = res.archived ? `、取り残し ${res.archived} 件を「その他」へ` : "";
    toast(`${res.applied} 件移動しました (スキップ: ${res.skipped})${prunedMsg}${archivedMsg} — Ctrl+Z で取り消せます`);
  } catch (e) {
    toast(`適用失敗: ${e.message}`, "error");
  }
}

/// 落ちたチャンクの分だけ再送する。以前は 40 件まとめて捨てられ、
/// ログに残るだけで手の打ちようがなかった。
async function retryFailedChunks({ usePaidKey = false } = {}) {
  if (!_aiReview || !_aiReview.failedIds.length) return;
  const ids = _aiReview.failedIds.slice();
  const opts = _aiReview.opts;
  const paid = usePaidKey || _aiReview.usingPaidKey;
  const payload = {
    bookmark_ids: ids,
    custom_prompt: opts.customPrompt || undefined,
    fields: opts.fields,
    model: opts.model,
    chunk_size: opts.chunkSize,
    use_paid_key: paid,
    fresh: !!opts.fresh,
  };

  let est;
  try {
    est = await api("/classify/estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    return toast(`見積もりに失敗: ${e.message}`, "error");
  }
  if (!(await openEstimateGate(est, opts.model))) return;

  _aiReview.failedIds = [];
  _aiReview.quotaExhausted = false;
  if (paid) _aiReview.usingPaidKey = true;
  const bar = _aiModal?.querySelector("#ai-retry");
  if (bar) bar.style.display = "none";
  showAiRunArea(true);

  try {
    const moves = await runAiClassifySse(payload, _aiModal);
    // 総入れ替えではなく上書きマージ。既存の提案とユーザーの選択を壊さない。
    aiIngestMoves(moves || [], false);
  } catch (e) {
    toast(`再実行に失敗: ${e.message}`, "error");
  }
  showAiRunArea(_aiReview.failedIds.length > 0);
  renderAiRetryBar();
  renderAiReview();
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

let appVersion = "";

async function boot() {
  setupDetailInlineEdit();
  restoreView();
  restoreSplit();
  refreshContext();
  if (!API_BASE) {
    setStatus("API 未設定");
    toast("API ベース URL が設定されていません", "error");
    return;
  }
  setStatus("接続中…");
  try {
    const health = await api("/health");
    setStatus(`接続済 v${health.version}`);
    appVersion = health.version;
    const bv = document.getElementById("brandVer");
    if (bv) bv.textContent = `v${health.version}`;
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

  if (e.key === "F1") { e.preventDefault(); cmdHelp(); return; }

  if (e.ctrlKey || e.metaKey) {
    if (e.key === "z" && !e.shiftKey) { e.preventDefault(); cmdUndo(); }
    if (e.key === "y" || (e.key === "z" && e.shiftKey)) { e.preventDefault(); cmdRedo(); }
    if (e.key === "s") { e.preventDefault(); cmdSave(); }
    if (e.key === "o") { e.preventDefault(); cmdOpen(); }
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
