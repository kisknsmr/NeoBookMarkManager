import os
import io
import json
import html
import time
import re
import threading
import queue
import configparser
from html.parser import HTMLParser
from urllib.parse import urlparse, quote_plus, urlunparse
from collections import OrderedDict
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
import tkinter.font as tkfont
from PIL import Image, ImageTk
import requests
from bs4 import BeautifulSoup
from ttkthemes import ThemedTk
import logging
from logging.handlers import RotatingFileHandler

# AI分類モジュールをインポート
from ai_classifier import AIBookmarkClassifier, BookmarkNode

# Netscape Bookmark HTML Format
BOOKMARK_HTML_HEADER = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
"""
BOOKMARK_HTML_FOOTER = """</DL><p>
"""


# ==============================================================================
# ▼▼▼ レビュー反映 6: バリデーション強化 ▼▼▼
# ==============================================================================
def is_valid_url(url: str) -> bool:
    """より厳密なURL検証"""
    if not url:
        return False
    try:
        result = urlparse(url)
        if not all([result.scheme, result.netloc]):
            return False
        if result.scheme.lower() not in ['http', 'https', 'ftp', 'file']:
            return False
        if result.scheme.lower() in ['http', 'https']:
            # ホスト名の形式チェック（基本的な検証）
            hostname_pattern = re.compile(
                r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$')
            if not hostname_pattern.match(result.netloc.split(':')[0]):
                return False
        return True
    except (ValueError, AttributeError):
        return False


# ==============================================================================
# ▼▼▼ レビュー反映 5: コード構造の改善 (ConfigManager) ▼▼▼
# ==============================================================================
class ConfigManager:
    """設定ファイル(config.ini)の管理を専門に行うクラス。"""

    def __init__(self, config_path='config.ini'):
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        self.load_config()

    def load_config(self):
        if os.path.exists(self.config_path):
            self.config.read(self.config_path, encoding='utf-8')

    def get_proxy_settings(self):
        if 'Proxy' not in self.config:
            return None
        proxy_section = self.config['Proxy']
        return {
            'url': proxy_section.get('url'),
            'user': proxy_section.get('user'),
            'password': proxy_section.get('password')
        }

    def get_priority_terms(self):
        if not (self.config.has_section('Classifier') and
                self.config.has_option('Classifier', 'priority_terms')):
            return []
        terms_str = self.config.get('Classifier', 'priority_terms')
        return [term.strip() for term in terms_str.split(',') if term.strip()]


# ==============================================================================
# ▼▼▼ レビュー反映 4: メモリ管理の改善 (LRUCache) ▼▼▼
# ==============================================================================
class LRUCache(OrderedDict):
    """容量制限付きのキャッシュ(Least Recently Used)。"""

    def __init__(self, maxsize=100):
        super().__init__()
        self.maxsize = maxsize

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            self.popitem(last=False)


class Node:
    __slots__ = ("type", "title", "url", "add_date", "last_modified", "children", "parent")

    def __init__(self, type_, title="", url="", add_date="", last_modified=""):
        self.type = type_
        self.title = title
        self.url = url
        self.add_date = add_date
        self.last_modified = last_modified
        self.children = []
        self.parent = None

    def append(self, child):
        child.parent = self
        self.children.append(child)

    def __repr__(self):
        return f"Node(type='{self.type}', title='{self.title}')"


class NetscapeBookmarkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("folder", "Bookmarks")
        self.stack = [self.root]
        self._pending_link = None
        self._pending_folder = None
        self._capture_text_for = None
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        tag = tag.lower()
        if tag == "h3":
            self._pending_folder = Node("folder", title="", add_date=attr.get("add_date", ""),
                                        last_modified=attr.get("last_modified", ""))
            self._capture_text_for = "folder";
            self._buffer = []
        elif tag == "a":
            self._pending_link = Node("bookmark", title="", url=attr.get("href", ""), add_date=attr.get("add_date", ""),
                                      last_modified=attr.get("last_modified", ""))
            self._capture_text_for = "link";
            self._buffer = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("h3", "a"):
            text = "".join(self._buffer).strip()
            self._buffer = []
            if self._capture_text_for == "folder" and self._pending_folder:
                self._pending_folder.title = text or "Untitled"
                self.stack[-1].append(self._pending_folder)
                self.stack.append(self._pending_folder)
                self._pending_folder = None
            elif self._capture_text_for == "link" and self._pending_link:
                self._pending_link.title = text
                self.stack[-1].append(self._pending_link)
                self._pending_link = None
            self._capture_text_for = None
        elif tag == "dl":
            if len(self.stack) > 1: self.stack.pop()

    def handle_data(self, data):
        if self._capture_text_for in ("folder", "link"): self._buffer.append(data)


def export_netscape_html(root: Node) -> str:
    out = io.StringIO()
    out.write(BOOKMARK_HTML_HEADER)

    def esc(s: str) -> str:
        return html.escape(s or "", quote=True)

    def write_folder(node: Node, indent: int = 1) -> None:
        ind = "    " * indent
        out.write(
            f'{ind}<DT><H3 ADD_DATE="{esc(node.add_date)}" LAST_MODIFIED="{esc(node.last_modified)}">{esc(node.title)}</H3>\n')
        out.write(f"{ind}<DL><p>\n")
        for ch in node.children:
            if ch.type == "folder":
                write_folder(ch, indent + 1)
            else:
                out.write(
                    f'{ind}    <DT><A HREF="{esc(ch.url)}" ADD_DATE="{esc(ch.add_date)}" LAST_MODIFIED="{esc(ch.last_modified)}">{esc(ch.title)}</A>\n')
        out.write(f"{ind}</DL><p>\n")

    for ch in root.children:
        if ch.type == "folder":
            write_folder(ch, 1)
        else:
            out.write(
                f'    <DT><A HREF="{esc(ch.url)}" ADD_DATE="{esc(ch.add_date)}" LAST_MODIFIED="{esc(ch.last_modified)}">{esc(ch.title)}</A>\n')
    out.write(BOOKMARK_HTML_FOOTER)
    return out.getvalue()


class CustomPromptDialog(simpledialog.Dialog):
    def __init__(self, parent, title=None, previous_prompts=None):
        self.previous_prompts = previous_prompts or []
        super().__init__(parent, title)

    def body(self, master):
        self.result = None
        if self.previous_prompts:
            ttk.Label(master, text="現在の指示:", font=("", 10, "bold")).pack(anchor="w", padx=5, pady=(5, 0))
            history_text = tk.Text(master, height=4, width=60, wrap="word", relief="sunken", borderwidth=1)
            history_text.pack(padx=5, pady=2, fill="x", expand=True)
            display_str = "\n".join([f"- {p}" for p in self.previous_prompts])
            history_text.insert("1.0", display_str)
            history_text.config(state="disabled", background="#f0f0f0")
        ttk.Label(master, text="追加の指示を入力:", font=("", 10, "bold")).pack(anchor="w", padx=5, pady=(10, 0))
        self.text_widget = tk.Text(master, height=8, width=60, wrap="word")
        self.text_widget.pack(padx=5, pady=5, fill="both", expand=True)
        return self.text_widget

    def apply(self):
        self.result = self.text_widget.get("1.0", "end-1c").strip()


class App(ThemedTk):
    def __init__(self):
        super().__init__(theme="clam")
        self.title("Bookmark Studio — Chrome Bookmarks Organizer")
        self.geometry("1400x800")
        self.minsize(1000, 600)

        self.logger = logging.getLogger(__name__)
        self._setup_logging()

        self.config_manager = ConfigManager()

        self.root_node = Node("folder", "Bookmarks")
        self.current_file = None
        self.rules = self._default_rules()
        self.rules_path = None
        self._iid_to_node = {}
        self.preview_cache = LRUCache(maxsize=50)
        self.ui_queue = queue.Queue()
        self._search_after_id = None
        self.open_nodes = set()
        self.search_index = {}
        self.dragging_iids = None
        self.drag_start_iid = None
        self.drag_window = None
        self.drop_line = None
        self.drop_target_info = None
        self._img_cache = LRUCache(maxsize=200)
        self.max_smart_items = 300
        self.progress_history = []
        self.use_proxy_var = tk.BooleanVar(value=True)

        self.last_classified_bookmarks = []
        self.last_classification_prompts = []

        self._smart_dialog = None
        self._smart_cancelled = False
        self.progress_var = None
        self.progress_label = None
        self.traffic_label = None

        self._titlefix_dialog = None
        self._titlefix_cancelled = False
        self._titlefix_var = None
        self._titlefix_label = None
        self.fetch_timeout = 10

        self._build_ui()
        self._build_search_index()
        self.after(100, self._process_ui_queue)

    def _setup_logging(self):
        """ログ設定を改善。"""
        self.logger.setLevel(logging.INFO)
        log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        file_handler = RotatingFileHandler('bookmark_editor.log', maxBytes=1024 * 1024 * 5, backupCount=3,
                                           encoding='utf-8')
        file_handler.setFormatter(log_formatter)
        file_handler.setLevel(logging.INFO)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        console_handler.setLevel(logging.WARNING)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def _build_ui(self) -> None:
        menubar = tk.Menu(self)
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="Open HTML…", command=self.cmd_open, accelerator="Ctrl+O")
        filem.add_command(label="Save", command=self.cmd_save, accelerator="Ctrl+S")
        filem.add_command(label="Save As…", command=self.cmd_save_as, accelerator="Ctrl+Shift+S")
        filem.add_separator()
        filem.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filem)

        editm = tk.Menu(menubar, tearoff=0)
        editm.add_command(label="New Folder", command=self.cmd_new_folder, accelerator="Ctrl+Shift+N")
        editm.add_command(label="New Bookmark", command=self.cmd_new_bookmark, accelerator="Ctrl+N")
        editm.add_command(label="Rename", command=self.cmd_rename, accelerator="F2")
        editm.add_command(label="Edit URL", command=self.cmd_edit_url)
        editm.add_separator()
        editm.add_command(label="Move to Folder…", command=self.cmd_move_to_folder)
        editm.add_command(label="Move Up", command=self.cmd_move_up, accelerator="Ctrl+Up")
        editm.add_command(label="Delete", command=self.cmd_delete, accelerator="Delete")
        menubar.add_cascade(label="Edit", menu=editm)

        toolsm = tk.Menu(menubar, tearoff=0)
        toolsm.add_checkbutton(label="プロキシを使用する", variable=self.use_proxy_var, onvalue=True, offvalue=False)
        toolsm.add_command(label="プロキシ接続をテスト", command=self.cmd_check_proxy)
        toolsm.add_separator()
        toolsm.add_command(label="Sort by Title (A→Z)", command=lambda: self.cmd_sort("title"))
        toolsm.add_command(label="Sort by Domain (A→Z)", command=lambda: self.cmd_sort("domain"))
        toolsm.add_command(label="Deduplicate in Folder", command=self.cmd_dedupe)
        toolsm.add_command(label="Merge Duplicate Folders", command=self.cmd_merge_folders)  # ★★★ 新機能 ★★★
        toolsm.add_separator()
        toolsm.add_command(label="Auto Classify (Rules)…", command=self.cmd_show_classify_preview)
        toolsm.add_command(label="Smart Classify (AI)…", command=self.cmd_smart_classify)
        toolsm.add_command(label="Set Smart Classify Limit…", command=self.cmd_set_smart_classify_limit)
        toolsm.add_separator()
        toolsm.add_command(label="Fix Titles from URL…", command=self.cmd_fix_titles_from_url)
        toolsm.add_command(label="Set Title Fetch Timeout…", command=self.cmd_set_title_fetch_timeout)
        toolsm.add_separator()
        toolsm.add_command(label="Edit Classify Rules…", command=self.cmd_edit_rules)
        toolsm.add_command(label="Show Progress Chart", command=self.cmd_show_progress_chart)
        menubar.add_cascade(label="Tools", menu=toolsm)

        self.config(menu=menubar)

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace("w", self._on_search_var_changed)
        ent = ttk.Entry(top, textvariable=self.search_var, width=44)
        ent.pack(side="left", padx=(6, 8))
        ttk.Button(top, text="Clear", command=self._clear_search).pack(side="left", padx=(6, 0))

        main = ttk.Panedwindow(self, orient="horizontal")
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main)
        main.add(left, weight=3)

        cols = ("url",)
        self.tree = ttk.Treeview(left, columns=cols, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Title")
        self.tree.heading("url", text="URL")
        self.tree.column("#0", width=600, anchor="w")
        self.tree.column("url", width=500, anchor="w")

        ysb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=ysb.set, xscroll=xsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(main, padding=8)
        main.add(right, weight=1)
        self.info_title = tk.StringVar(value="—")
        self.info_url = tk.StringVar(value="—")
        self.preview_title = tk.StringVar(value="")
        self.preview_desc = tk.StringVar(value="")
        ttk.Label(right, text="Selected:").pack(anchor="w")
        ttk.Label(right, textvariable=self.info_title, font=("", 10, "bold")).pack(anchor="w", pady=(0, 6))
        ttk.Label(right, text="URL:").pack(anchor="w")
        ttk.Entry(right, textvariable=self.info_url, state="readonly").pack(fill="x")

        ttk.Separator(right).pack(fill="x", pady=8)
        ttk.Label(right, text="Preview:").pack(anchor="w")
        ttk.Label(right, textvariable=self.preview_title, wraplength=200).pack(anchor="w")
        ttk.Label(right, textvariable=self.preview_desc, wraplength=200).pack(anchor="w")

        ttk.Separator(right).pack(fill="x", pady=8)
        ttk.Button(right, text="New Folder", command=self.cmd_new_folder).pack(fill="x")
        ttk.Button(right, text="New Bookmark", command=self.cmd_new_bookmark).pack(fill="x", pady=6)
        ttk.Button(right, text="Rename (F2)", command=self.cmd_rename).pack(fill="x")
        ttk.Button(right, text="Edit URL", command=self.cmd_edit_url).pack(fill="x", pady=6)
        ttk.Button(right, text="Move to Folder…", command=self.cmd_move_to_folder).pack(fill="x")
        ttk.Button(right, text="Move Up (Ctrl+Up)", command=self.cmd_move_up).pack(fill="x", pady=6)
        ttk.Button(right, text="Delete", command=self.cmd_delete).pack(fill="x")

        ttk.Separator(right).pack(fill="x", pady=8)
        ttk.Button(right, text="Sort by Title", command=lambda: self.cmd_sort("title")).pack(fill="x")
        ttk.Button(right, text="Sort by Domain", command=lambda: self.cmd_sort("domain")).pack(fill="x", pady=6)
        ttk.Button(right, text="Deduplicate in Folder", command=self.cmd_dedupe).pack(fill="x")
        ttk.Button(right, text="Merge Duplicate Folders", command=self.cmd_merge_folders).pack(fill="x",
                                                                                               pady=6)  # ★★★ 新機能 ★★★
        ttk.Button(right, text="Auto Classify…", command=self.cmd_show_classify_preview).pack(fill="x")
        ttk.Button(right, text="Smart Classify (AI)…", command=self.cmd_smart_classify).pack(fill="x", pady=6)
        ttk.Separator(right).pack(fill="x", pady=8)
        ttk.Button(right, text="Expand All", command=self.cmd_expand_all).pack(fill="x")
        ttk.Button(right, text="Collapse All", command=self.cmd_collapse_all).pack(fill="x", pady=6)

        self.ctx = tk.Menu(self, tearoff=0)
        self.ctx.add_command(label="New Folder", command=self.cmd_new_folder)
        self.ctx.add_command(label="New Bookmark", command=self.cmd_new_bookmark)
        self.ctx.add_separator()
        self.ctx.add_command(label="Rename", command=self.cmd_rename)
        self.ctx.add_command(label="Edit URL", command=self.cmd_edit_url)
        self.ctx.add_command(label="Move to Folder…", command=self.cmd_move_to_folder)
        self.ctx.add_command(label="Move Up", command=self.cmd_move_up)
        self.ctx.add_separator()
        self.ctx.add_command(label="Merge Duplicate Folders", command=self.cmd_merge_folders)  # ★★★ 新機能 ★★★
        self.ctx.add_separator()
        self.ctx.add_command(label="Delete", command=self.cmd_delete)
        self.tree.bind("<Button-3>", self._popup_ctx)

        self.bind_all("<Control-o>", lambda e: self.cmd_open())
        self.bind_all("<Control-s>", lambda e: self.cmd_save())
        self.bind_all("<Control-S>", lambda e: self.cmd_save_as())
        self.bind_all("<Control-n>", lambda e: self.cmd_new_bookmark())
        self.bind_all("<Control-N>", lambda e: self.cmd_new_folder())
        self.bind_all("<Delete>", lambda e: self.cmd_delete())
        self.bind_all("<F2>", lambda e: self.cmd_rename())
        self.bind_all("<Control-Up>", lambda e: self.cmd_move_up())

        self.tree.bind("<<TreeviewSelect>>", self._update_info_from_selection)
        self.tree.bind("<ButtonPress-1>", self._on_tree_press)
        self.tree.bind("<B1-Motion>", self._on_tree_drag)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release)
        self.tree.bind("<Double-1>", self._on_double_click_inline_edit)
        self.tree.bind("<<TreeviewOpen>>", self._on_folder_open)
        self.tree.bind("<<TreeviewClose>>", self._on_folder_close)

        default_font = tkfont.nametofont("TkDefaultFont")
        bold_font = default_font.copy()
        bold_font.configure(weight="bold")

        self.tree.tag_configure('oddrow', background='#FFFFFF')
        self.tree.tag_configure('evenrow', background='#F0F0F0')
        self.tree.tag_configure('nourl', foreground='gray')
        self.tree.tag_configure('folder', font=bold_font)
        self.tree.tag_configure("match", background="#FFFACD")

        style = ttk.Style()
        style.configure("Line.TFrame", background="blue")
        self._refresh_tree()

    def _process_ui_queue(self):
        """UIキューを処理してスレッドセーフな更新を行う。"""
        try:
            while True:
                task_type, data = self.ui_queue.get_nowait()
                if task_type == 'smart_classify_result':
                    if self._smart_dialog and self._smart_dialog.winfo_exists():
                        self._smart_dialog.destroy()
                    self._smart_dialog = None
                    if not self._smart_cancelled:
                        result_obj = data
                        plan = result_obj.plan
                        all_nodes_to_move = []
                        original_nodes_map = {(node.title, node.url): node for node in self.last_classified_bookmarks}
                        final_plan = {}
                        for folder, bm_nodes in plan.items():
                            original_nodes = []
                            for bm_node in bm_nodes:
                                original = original_nodes_map.get((bm_node.title, bm_node.url))
                                if original:
                                    original_nodes.append(original)
                            if original_nodes:
                                final_plan[folder] = original_nodes
                                all_nodes_to_move.extend(original_nodes)
                        base_node = self._find_common_parent(all_nodes_to_move)
                        self._show_smart_classify_preview(final_plan, base_node)
                elif task_type == 'error':
                    if self._smart_dialog and self._smart_dialog.winfo_exists():
                        self._smart_dialog.destroy()
                    self._smart_dialog = None
                    messagebox.showwarning("Error", data)
                elif task_type == 'progress_update':
                    loaded_count, total_bms, sent_bytes, recv_bytes = data
                    self.progress_history.append(loaded_count)
                    if self.traffic_label and self._smart_dialog and self._smart_dialog.winfo_exists():
                        sent_kb = sent_bytes / 1024
                        recv_kb = recv_bytes / 1024
                        self.traffic_label.config(text=f"Traffic: Sent {sent_kb:.2f} KB | Received {recv_kb:.2f} KB")
                elif task_type == 'proxy_check_success':
                    dialog = data
                    if dialog.winfo_exists(): dialog.destroy()
                    messagebox.showinfo("Proxy Check", "プロキシ接続は正常です。")
                elif task_type == 'proxy_check_failure':
                    dialog, error_msg = data
                    if dialog.winfo_exists(): dialog.destroy()
                    messagebox.showerror("Proxy Check",
                                         f"プロキシ接続に失敗しました。\nconfig.iniの設定を確認してください。\n\nエラー: {error_msg}")
                elif task_type == 'preview':
                    url, preview_data = data
                    self.preview_cache[url] = preview_data
                    sels = self.tree.selection()
                    if len(sels) == 1:
                        node = self._node_of(sels[0])
                        if node and node.url == url:
                            self._update_preview_pane(preview_data)
                elif task_type == 'titlefix_progress':
                    processed, total = data
                    if self._titlefix_dialog and self._titlefix_dialog.winfo_exists():
                        try:
                            self._titlefix_var.set(processed)
                            self._titlefix_label.config(text=f"{processed} / {total}")
                        except tk.TclError:
                            pass
                elif task_type == 'titlefix_done':
                    if self._titlefix_dialog and self._titlefix_dialog.winfo_exists():
                        try:
                            self._titlefix_dialog.destroy()
                        except tk.TclError:
                            pass
                    self._titlefix_dialog = None
                    self._refresh_tree()
                    messagebox.showinfo("Fix Titles", "処理が完了しました。")
        except queue.Empty:
            pass
        finally:
            self.after(100, self._process_ui_queue)

    def _get_proxies_for_requests(self):
        """requestsライブラリ用にプロキシ設定を返す。"""
        if not self.use_proxy_var.get():
            return None

        settings = self.config_manager.get_proxy_settings()
        if not settings or not settings.get('url'):
            return None

        proxy_url = settings['url']
        user = settings['user']
        password = settings['password']

        auth = (user, password) if user and password else None

        proxies = {
            'http': proxy_url,
            'https': proxy_url
        }
        return {'proxies': proxies, 'auth': auth}

    def _fetch_preview_worker(self, url: str):
        """ブックマークのプレビュー情報を非同期で取得（リトライ機能付き）。"""
        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                proxy_info = self._get_proxies_for_requests()
                proxies = proxy_info['proxies'] if proxy_info else None
                auth = proxy_info['auth'] if proxy_info else None

                resp = requests.get(
                    url,
                    timeout=5,
                    headers={'User-Agent': 'Mozilla/5.0'},
                    proxies=proxies,
                    auth=auth
                )
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "html.parser")
                title_tag = soup.find("meta", property="og:title") or soup.find("title")
                title = title_tag.get("content") if title_tag and title_tag.name == "meta" else (
                    title_tag.text if title_tag else "")
                desc_tag = soup.find("meta", property="og:description") or soup.find("meta",
                                                                                     attrs={"name": "description"})
                desc = desc_tag.get("content") if desc_tag else ""
                result = {"title": title.strip(), "description": desc.strip()}
                self.ui_queue.put(('preview', (url, result)))
                return

            except requests.exceptions.Timeout as e:
                self.logger.warning(f"Timeout for {url} (attempt {attempt + 1}): {e}")
            except requests.exceptions.ConnectionError as e:
                self.logger.warning(f"Connection error for {url} (attempt {attempt + 1}): {e}")
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    self.logger.warning(f"URL not found (404) for {url}. No retries.")
                    break
                self.logger.warning(f"HTTP error for {url} (attempt {attempt + 1}): {e}")
            except Exception as e:
                self.logger.error(f"Unexpected error for {url}: {e}")
                break

            if attempt < max_retries - 1:
                time.sleep(retry_delay * (2 ** attempt))

        result = {"title": "Could not load preview", "description": ""}
        self.ui_queue.put(('preview', (url, result)))

    def _popup_ctx(self, e) -> None:
        try:
            self.ctx.tk_popup(e.x_root, e.y_root)
        finally:
            self.ctx.grab_release()

    def _refresh_tree(self) -> None:
        """ツリービューをデータモデルに基づいて再描画し、選択状態と展開状態を復元する。"""
        selected_nodes = {self._node_of(iid) for iid in self.tree.selection() if self._node_of(iid)}
        self.tree.delete(*self.tree.get_children())
        self._iid_to_node.clear()
        self.row_counter = 0

        def add_items(parent_iid: str, node: Node) -> None:
            for ch in node.children:
                tag = 'oddrow' if self.row_counter % 2 == 0 else 'evenrow'
                self.row_counter += 1
                tags_to_add = [tag]
                if ch.type == "folder": tags_to_add.append('folder')
                icon = "📁 " if ch.type == "folder" else ""
                text = icon + (ch.title or "")
                url_display = ch.url
                if not ch.url and ch.type == 'bookmark':
                    url_display = '(None)'
                    tags_to_add.append('nourl')
                iid = self.tree.insert(parent_iid, "end", text=text, values=(url_display,), tags=tuple(tags_to_add))
                self._iid_to_node[iid] = ch
                if ch.type == "folder": add_items(iid, ch)

        add_items("", self.root_node)
        new_iids_to_select = []
        for iid, node in self._iid_to_node.items():
            if node in self.open_nodes: self.tree.item(iid, open=True)
            if node in selected_nodes: new_iids_to_select.append(iid)
        if new_iids_to_select:
            self.tree.selection_set(new_iids_to_select)
            self.tree.see(new_iids_to_select[-1])
        self._build_search_index()

    def _build_search_index(self):
        """検索インデックスを単語ベースの辞書形式で構築"""
        self.search_index = {}
        for iid, node in self._iid_to_node.items():
            full_text = f"{(node.title or '').lower()} {(node.url or '').lower()}"
            words = set(re.split(r'\W+', full_text))
            for word in words:
                if not word: continue
                if word not in self.search_index:
                    self.search_index[word] = set()
                self.search_index[word].add(iid)

    def _node_of(self, iid: str):
        return self._iid_to_node.get(iid)

    def _iid_of_node(self, target: Node) -> str:
        for iid, n in self._iid_to_node.items():
            if n is target: return iid
        return ""

    def _find_parent_iid(self, iid: str) -> str:
        return self.tree.parent(iid)

    def _selected_folder_and_node(self):
        sel = self.tree.selection()
        if sel:
            iid = sel[0]
            node = self._node_of(iid)
            if node and node.type == "folder": return iid, node
            pid = self._find_parent_iid(iid)
            pnode = self._node_of(pid) if pid else self.root_node
            return pid, pnode
        return "", self.root_node

    def _update_preview_pane(self, preview_data):
        self.preview_title.set(preview_data.get("title", ""))
        self.preview_desc.set(preview_data.get("description", ""))

    def _update_info_from_selection(self, event=None) -> None:
        sels = self.tree.selection()
        if not sels or len(sels) > 1:
            self.info_title.set(f"{len(sels)} items selected" if sels else "—")
            self.info_url.set("")
            self._update_preview_pane({})
            return
        iid = sels[0]
        node = self._node_of(iid)
        if node:
            self.info_title.set(f"{node.title or '(Untitled)'}  [{node.type}]")
            self.info_url.set(node.url or "")
            if node.type == "bookmark" and node.url:
                if node.url in self.preview_cache:
                    self._update_preview_pane(self.preview_cache[node.url])
                else:
                    self.preview_title.set("Loading preview...")
                    self.preview_desc.set("")
                    threading.Thread(target=self._fetch_preview_worker, args=(node.url,), daemon=True).start()

    def cmd_open(self) -> None:
        path = filedialog.askopenfilename(
            title="Open Chrome Bookmarks HTML", filetypes=[("HTML files", "*.html;*.htm"), ("All files", "*.*")],
        )
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = f.read()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read file:\n{e}");
            return
        parser = NetscapeBookmarkParser()
        try:
            parser.feed(data)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse bookmarks HTML:\n{e}");
            return
        self.root_node = parser.root
        self.current_file = path
        sidecar = os.path.splitext(path)[0] + ".bookmark_rules.json"
        if os.path.exists(sidecar):
            try:
                with open(sidecar, "r", encoding="utf-8") as rf:
                    self.rules = json.load(rf)
                    self.rules_path = sidecar
            except Exception:
                self.rules = self._default_rules()
                self.rules_path = None
        self.open_nodes.clear()
        self._refresh_tree()
        roots = self.tree.get_children("")
        if roots:
            first_node = self._node_of(roots[0])
            if first_node:
                self.open_nodes.add(first_node)
                self.tree.item(roots[0], open=True)
        self.title(f"Bookmark Studio — {os.path.basename(path)}")

    def cmd_save(self) -> None:
        if not self.current_file:
            return self.cmd_save_as()
        try:
            html_text = export_netscape_html(self.root_node)
            with open(self.current_file, "w", encoding="utf-8") as f:
                f.write(html_text)
            if self.rules:
                sp = os.path.splitext(self.current_file)[0] + ".bookmark_rules.json"
                with open(sp, "w", encoding="utf-8") as wf:
                    json.dump(self.rules, wf, ensure_ascii=False, indent=2)
                self.rules_path = sp
            messagebox.showinfo("Saved", "Saved successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save:\n{e}")

    def cmd_save_as(self) -> None:
        if not self.root_node: return
        path = filedialog.asksaveasfilename(
            title="Export Chrome HTML", defaultextension=".html", filetypes=[("HTML files", "*.html;*.htm")],
        )
        if not path: return
        try:
            html_text = export_netscape_html(self.root_node)
            with open(path, "w", encoding="utf-8") as f:
                f.write(html_text)
            messagebox.showinfo("Exported", "Export completed.")
            sp = os.path.splitext(path)[0] + ".bookmark_rules.json"
            with open(sp, "w", encoding="utf-8") as wf:
                json.dump(self.rules, wf, ensure_ascii=False, indent=2)
            self.rules_path = sp
            self.current_file = path
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export:\n{e}")

    def cmd_new_folder(self) -> None:
        _, parent = self._selected_folder_and_node()
        if not parent: return
        name = simpledialog.askstring("New Folder", "Folder name:")
        if name is None: return
        n = Node("folder", title=name)
        parent.append(n)
        self._refresh_tree()
        new_iid = self._iid_of_node(n)
        if new_iid:
            self.tree.selection_set(new_iid)
            self.tree.see(new_iid)

    def cmd_new_bookmark(self) -> None:
        _, parent = self._selected_folder_and_node()
        if not parent: return
        title = simpledialog.askstring("New Bookmark", "Title:")
        if title is None: return
        url = simpledialog.askstring("New Bookmark", "URL:")
        if url is None: return
        if url and not is_valid_url(url):
            messagebox.showerror("Error", "無効なURL形式です。http:// または https:// で始まるURLを入力してください。")
            return
        n = Node("bookmark", title=title, url=url)
        parent.append(n)
        self._refresh_tree()
        new_iid = self._iid_of_node(n)
        if new_iid:
            self.tree.selection_set(new_iid)
            self.tree.see(new_iid)

    def _start_inline_editor(self, iid: str) -> None:
        node = self._node_of(iid)
        if not node: return
        bbox = self.tree.bbox(iid, column="#0")
        if not bbox: return
        x, y, w, h = bbox
        x_offset = 25
        x += x_offset
        w -= x_offset
        entry = ttk.Entry(self.tree)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, node.title)
        entry.select_range(0, 'end')
        entry.focus_set()

        def commit(event):
            new_title = entry.get()
            entry.destroy()
            if node.title != new_title:
                node.title = new_title
                icon = "📁 " if node.type == "folder" else ""
                text = icon + (node.title or "")
                self.tree.item(iid, text=text)
                self._build_search_index()

        def cancel(event):
            entry.destroy()

        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Escape>", cancel)

    def _on_double_click_inline_edit(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid or self.tree.identify_column(event.x) != "#0": return
        self._start_inline_editor(iid)

    def cmd_rename(self) -> None:
        sels = self.tree.selection()
        if sels: self._start_inline_editor(sels[0])

    def cmd_edit_url(self) -> None:
        sels = self.tree.selection()
        if not sels: return
        node = self._node_of(sels[0])
        if not node or node.type != "bookmark":
            messagebox.showinfo("Edit URL", "Select a bookmark to edit its URL.")
            return
        new_url = simpledialog.askstring("Edit URL", "New URL:", initialvalue=node.url or "")
        if new_url is None: return
        if new_url and not is_valid_url(new_url):
            messagebox.showerror("Error", "無効なURL形式です。http:// または https:// で始まるURLを入力してください。")
            return
        node.url = new_url
        self._refresh_tree()
        new_iid = self._iid_of_node(node)
        if new_iid: self.tree.selection_set(new_iid)

    def cmd_move_to_folder(self) -> None:
        sels = list(self.tree.selection())
        if not sels:
            messagebox.showinfo("Move to Folder", "移動するアイテムを選択してください。")
            return
        dragged_nodes = [self._node_of(i) for i in sels if self._node_of(i)]
        if not dragged_nodes: return
        folder_nodes = []

        def find_folders(node, path):
            if node in dragged_nodes: return
            if node.type == 'folder':
                folder_nodes.append((path, node))
                for child in node.children:
                    find_folders(child, path + [node.title])

        find_folders(self.root_node, [])
        dialog = tk.Toplevel(self)
        dialog.title("Move Items to Folder")
        dialog.geometry("450x400")
        dialog.transient(self)
        dialog.grab_set()
        tk.Label(dialog, text=f"Move {len(dragged_nodes)} item(s) to:").pack(pady=10)
        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        folder_listbox = tk.Listbox(list_frame)
        folder_listbox.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=folder_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        folder_listbox.config(yscrollcommand=scrollbar.set)
        folder_map = {}
        for path, node in folder_nodes:
            display_path = " / ".join(path[1:] + [node.title]) or "Bookmarks Bar"
            folder_listbox.insert("end", display_path)
            folder_map[display_path] = node
        result_node = None

        def on_ok():
            nonlocal result_node
            selected_indices = folder_listbox.curselection()
            if selected_indices:
                result_node = folder_map.get(folder_listbox.get(selected_indices[0]))
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", padx=10, pady=10)
        ok_button = ttk.Button(btn_frame, text="Move", command=on_ok)
        ok_button.pack(side="right", padx=5)
        cancel_button = ttk.Button(btn_frame, text="Cancel", command=dialog.destroy)
        cancel_button.pack(side="right")
        self.wait_window(dialog)
        if not result_node: return
        for node in dragged_nodes:
            if node.parent: node.parent.children.remove(node)
            result_node.append(node)
        self._refresh_tree()
        new_iids = [self._iid_of_node(n) for n in dragged_nodes if self._iid_of_node(n)]
        if new_iids:
            self.tree.selection_set(new_iids)
            self.tree.see(new_iids[-1])

    def cmd_move_up(self) -> None:
        """選択したアイテムを一つ上の階層に移動する。"""
        sels = list(self.tree.selection())
        if not sels:
            messagebox.showinfo("Move Up", "移動するアイテムを選択してください。")
            return
        nodes_to_move = [self._node_of(i) for i in sels if self._node_of(i)]
        if not nodes_to_move: return
        for node in nodes_to_move:
            if not node.parent or not node.parent.parent:
                messagebox.showwarning("Move Up", "トップレベルのアイテムはこれ以上上に移動できません。")
                return
        new_parent = nodes_to_move[0].parent.parent
        for node in nodes_to_move:
            if node.parent:
                node.parent.children.remove(node)
            new_parent.append(node)
        self._refresh_tree()
        new_iids = [self._iid_of_node(n) for n in nodes_to_move if self._iid_of_node(n)]
        if new_iids:
            self.tree.selection_set(new_iids)
            self.tree.see(new_iids[-1])

    def cmd_delete(self) -> None:
        sels = list(self.tree.selection())
        if not sels: return
        if not messagebox.askyesno("Delete", f"Delete {len(sels)} selected item(s)?"): return
        for iid in sels:
            node = self._node_of(iid)
            if node and node.parent:
                node.parent.children.remove(node)
        self._refresh_tree()

    def cmd_sort(self, mode: str = "title") -> None:
        _, folder = self._selected_folder_and_node()
        if not folder: return

        def sort_key(n: Node):
            if mode == "domain" and n.type == "bookmark":
                return (0, self._domain_of(n.url), (n.title or "").lower())
            return (0 if n.type == "folder" else 1, (n.title or "").lower())

        folder.children.sort(key=sort_key)
        self._refresh_tree()

    def cmd_dedupe(self) -> None:
        _, folder = self._selected_folder_and_node()
        if not folder: return
        seen, new_children, removed = set(), [], 0
        for ch in folder.children:
            if ch.type == "bookmark":
                key = (ch.url or "").strip().rstrip("/")
                if key and key in seen:
                    removed += 1;
                    continue
                if key: seen.add(key)
            new_children.append(ch)
        folder.children = new_children
        self._refresh_tree()
        messagebox.showinfo("Deduplicate", f"Removed {removed} duplicated bookmark(s).")

    def cmd_expand_all(self):
        self.open_nodes.clear()

        def collect_all_folders(node):
            if node.type == 'folder':
                self.open_nodes.add(node)
                for child in node.children:
                    collect_all_folders(child)

        collect_all_folders(self.root_node)
        self._refresh_tree()

    def cmd_collapse_all(self):
        self.open_nodes.clear()
        self._refresh_tree()

    def _on_search_var_changed(self, *args):
        if self._search_after_id: self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(200, self._apply_search)

    def _apply_search(self) -> None:
        for tag in self.tree.tag_names():
            if tag.startswith("match"):
                self.tree.tag_delete(tag)
        q = self.search_var.get().strip().lower()
        if not q: return
        matching_iids = set()
        search_words = [word for word in re.split(r'\W+', q) if word]
        for i, word in enumerate(search_words):
            found_iids = set()
            for term, iids in self.search_index.items():
                if term.startswith(word):
                    found_iids.update(iids)
            if i == 0:
                matching_iids = found_iids
            else:
                matching_iids.intersection_update(found_iids)
        if matching_iids:
            self.tree.tag_configure("match", background="#FFFACD")
            open_parents = set()
            for iid in matching_iids:
                self.tree.item(iid, tags=self.tree.item(iid, "tags") + ("match",))
                p = self.tree.parent(iid)
                while p:
                    if p in open_parents: break
                    open_parents.add(p)
                    p = self.tree.parent(p)
            for p_iid in open_parents:
                self.tree.item(p_iid, open=True)
                p_node = self._node_of(p_iid)
                if p_node: self.open_nodes.add(p_node)

    def _clear_search(self) -> None:
        self.search_var.set("")

    def _on_tree_press(self, event) -> None:
        self.drag_start_iid = self.tree.identify_row(event.y)
        if self.drag_start_iid and self.drag_start_iid not in self.tree.selection():
            if not (event.state & 0x0004) and not (event.state & 0x0001):
                self.tree.selection_set(self.drag_start_iid)

    def _on_tree_drag(self, event) -> None:
        if self.drag_start_iid:
            self.dragging_iids = list(self.tree.selection())
            if self.drag_start_iid in self.dragging_iids:
                self.config(cursor="fleur")
                self._create_drag_window()
            else:
                self.dragging_iids = None
            self.drag_start_iid = None
        if not self.dragging_iids: return
        if self.drag_window: self.drag_window.geometry(f"+{event.x_root + 15}+{event.y_root + 10}")
        self._update_drop_indicator(event.x, event.y)

    def _on_tree_release(self, event) -> None:
        self._destroy_drag_window()
        self._destroy_drop_line()
        self.config(cursor="")
        if not self.dragging_iids or not self.drop_target_info:
            self.dragging_iids = None;
            return
        target_iid = self.drop_target_info["iid"]
        drop_pos = self.drop_target_info["pos"]
        target_node = self._node_of(target_iid)
        if not target_node:
            self.dragging_iids = None;
            return
        dragged_nodes = [self._node_of(i) for i in self.dragging_iids if self._node_of(i)]
        for dn in dragged_nodes:
            if dn.type == 'folder':
                temp = target_node
                while temp:
                    if temp == dn:
                        messagebox.showwarning("Invalid Move", "Cannot move a folder into its own descendant.")
                        self.dragging_iids = None;
                        return
                    temp = temp.parent
        if target_node.type == "folder" and drop_pos == 'in':
            for dn in dragged_nodes:
                if dn.parent: dn.parent.children.remove(dn)
                target_node.append(dn)
        else:
            parent = target_node.parent or self.root_node
            try:
                insert_idx = parent.children.index(target_node)
                if drop_pos == 'after': insert_idx += 1
                for dn in reversed(dragged_nodes):
                    if dn.parent: dn.parent.children.remove(dn)
                    parent.children.insert(insert_idx, dn)
                    dn.parent = parent
            except ValueError:
                for dn in dragged_nodes:
                    if dn.parent: dn.parent.children.remove(dn)
                    parent.append(dn)
        self._refresh_tree()
        new_iids = [self._iid_of_node(n) for n in dragged_nodes if self._iid_of_node(n)]
        if new_iids: self.tree.selection_set(new_iids)
        self.dragging_iids = None
        self.drop_target_info = None

    def _create_drag_window(self):
        if self.drag_window: self.drag_window.destroy()
        self.drag_window = tk.Toplevel(self)
        self.drag_window.overrideredirect(True)
        self.drag_window.attributes('-alpha', 0.7)
        self.drag_window.attributes('-topmost', True)
        text = f"{len(self.dragging_iids)}個のアイテムを移動中"
        if len(self.dragging_iids) == 1:
            node = self._node_of(self.dragging_iids[0])
            text = node.title or "(Untitled)"
        label = ttk.Label(self.drag_window, text=text, padding=5, background="#DDDDDD", relief="solid", borderwidth=1)
        label.pack()

    def _destroy_drag_window(self):
        if self.drag_window:
            self.drag_window.destroy()
            self.drag_window = None

    def _update_drop_indicator(self, x, y):
        self._destroy_drop_line()
        self.drop_target_info = None
        for iid in self._iid_to_node:
            tags = list(self.tree.item(iid, "tags"))
            if "drop_folder" in tags:
                tags.remove("drop_folder")
                self.tree.item(iid, tags=tuple(tags))
        iid = self.tree.identify_row(y)
        if not iid or iid in self.dragging_iids: return
        bbox = self.tree.bbox(iid)
        if not bbox: return
        line_x, line_y, line_w, line_h = bbox
        target_node = self._node_of(iid)
        if target_node.type == 'folder':
            self.drop_target_info = {"iid": iid, "pos": "in"}
            self.tree.item(iid, tags=self.tree.item(iid, "tags") + ('drop_folder',))
        else:
            drop_pos = 'after' if y > (line_y + line_h / 2) else 'before'
            self.drop_target_info = {"iid": iid, "pos": drop_pos}
            line_y_pos = line_y if drop_pos == 'before' else line_y + line_h
            self.drop_line = ttk.Frame(self.tree, height=2, style="Line.TFrame")
            self.drop_line.place(x=line_x, y=line_y_pos, width=self.tree.winfo_width())

    def _destroy_drop_line(self):
        if self.drop_line:
            self.drop_line.destroy()
            self.drop_line = None
        for iid in self._iid_to_node:
            tags = list(self.tree.item(iid, "tags"))
            if "drop_folder" in tags:
                tags.remove("drop_folder")
                self.tree.item(iid, tags=tuple(tags))

    def _on_folder_open(self, event=None):
        iid = self.tree.focus()
        if iid:
            node = self._node_of(iid)
            if node and node.type == 'folder':
                self.open_nodes.add(node)

    def _on_folder_close(self, event=None):
        iid = self.tree.focus()
        if iid:
            node = self._node_of(iid)
            if node and node.type == 'folder':
                if node in self.open_nodes:
                    self.open_nodes.remove(node)

    def _default_rules(self):
        return {
            "Google": {"domains": ["google.com", "gmail.com", "drive.google.com"],
                       "keywords": ["google", "gmail", "drive"]},
            "YouTube": {"domains": ["youtube.com", "youtu.be"], "keywords": ["youtube", "yt"]},
            "News": {"domains": ["cnn.com", "bbc.co.uk", "nytimes.com", "news.yahoo"], "keywords": ["news", "article"]},
            "Social": {"domains": ["twitter.com", "x.com", "facebook.com", "instagram.com", "linkedin.com"],
                       "keywords": ["twitter", "facebook", "instagram", "linkedin"]},
            "Dev": {"domains": ["github.com", "gitlab.com", "stackoverflow.com", "pypi.org", "readthedocs"],
                    "keywords": ["github", "docs", "api", "stack overflow"]},
            "Shopping": {"domains": ["amazon.", "rakuten.", "taobao.", "jd.com"], "keywords": ["cart", "buy", "store"]},
        }

    def _match_rule(self, url: str, title: str, rule: dict) -> bool:
        u = (url or "").lower()
        t = (title or "").lower()
        for d in rule.get("domains", []):
            if d in u: return True
        for k in rule.get("keywords", []):
            if k in u or k in t: return True
        return False

    def _get_classification_plan(self, bookmarks_to_check: list[Node]) -> dict[str, list[Node]]:
        plan = {}
        for bm in bookmarks_to_check:
            if bm.type != 'bookmark': continue
            for folder_name, rule in self.rules.items():
                if self._match_rule(bm.url, bm.title, rule):
                    current_parent = bm.parent
                    if current_parent and current_parent.title == folder_name:
                        continue
                    if folder_name not in plan: plan[folder_name] = []
                    plan[folder_name].append(bm)
                    break
        return plan

    def _find_common_parent(self, nodes):
        """Finds the deepest common parent folder for a list of nodes."""
        if not nodes:
            return self.root_node
        paths = []
        for node in nodes:
            path = []
            curr = node.parent
            while curr:
                path.insert(0, curr)
                curr = curr.parent
            paths.append(path)
        if not paths:
            return self.root_node
        shortest_path = min(paths, key=len)
        common_parent = self.root_node
        for i, parent in enumerate(shortest_path):
            if all(i < len(p) and p[i] is parent for p in paths):
                common_parent = parent
            else:
                break
        return common_parent

    def _execute_classification_plan(self, plan: dict[str, list[Node]], base_node: Node):
        """Executes the classification plan within a specified base node."""
        if not plan: return
        target_folders_parent = base_node if base_node else self.root_node

        # ★★★ 修正点: 大文字小文字を区別しないフォルダ検索 ★★★
        existing_folders_map = {
            ch.title.lower(): ch for ch in target_folders_parent.children if ch.type == "folder"
        }

        for folder_name, bookmarks in plan.items():
            # 既存のフォルダを大文字小文字を区別せずに探す
            target_folder = existing_folders_map.get(folder_name.lower())

            if not target_folder:
                target_folder = Node("folder", folder_name)
                target_folders_parent.append(target_folder)
                existing_folders_map[folder_name.lower()] = target_folder

            for bm in bookmarks:
                if bm.parent and bm in bm.parent.children:
                    bm.parent.children.remove(bm)
                target_folder.append(bm)

        self._refresh_tree()
        messagebox.showinfo("Auto Classify", f"Moved {sum(len(v) for v in plan.values())} bookmarks.")

    def cmd_show_classify_preview(self) -> None:
        selection_iids = self.tree.selection()
        bookmarks_to_classify = []
        if not selection_iids:
            if not messagebox.askyesno("Auto Classify", "No items selected. Classify ALL bookmarks?"): return

            def collect_all(node):
                for child in node.children:
                    if child.type == 'bookmark':
                        bookmarks_to_classify.append(child)
                    elif child.type == 'folder':
                        collect_all(child)

            collect_all(self.root_node)
        else:
            for iid in selection_iids:
                node = self._node_of(iid)
                if not node: continue
                if node.type == 'bookmark':
                    bookmarks_to_classify.append(node)
                elif node.type == 'folder':
                    def collect_from_folder(folder_node):
                        for child in folder_node.children:
                            if child.type == 'bookmark':
                                bookmarks_to_classify.append(child)
                            elif child.type == 'folder':
                                collect_from_folder(child)

                    collect_from_folder(node)
        plan = self._get_classification_plan(list(set(bookmarks_to_classify)))
        if not plan:
            messagebox.showinfo("Auto Classify", "No bookmarks to move based on current rules.")
            return
        base_node = self._find_common_parent(bookmarks_to_classify)
        dialog = tk.Toplevel(self)
        dialog.title("Classification Preview")
        dialog.geometry("600x400")
        preview_tree = ttk.Treeview(dialog, columns=("original_location"), show="tree headings")
        preview_tree.heading("#0", text="Bookmark to Move")
        preview_tree.heading("original_location", text="Original Location")
        preview_tree.column("original_location", width=200)
        preview_tree.pack(fill="both", expand=True, padx=10, pady=10)
        for folder_name, bookmarks in sorted(plan.items()):
            folder_iid = preview_tree.insert("", "end", text=f"📁 Create in '{base_node.title}': {folder_name}",
                                             open=True)
            for bm in bookmarks:
                parent_path = []
                curr = bm.parent
                while curr and curr != self.root_node:
                    parent_path.insert(0, curr.title or "(Untitled)")
                    curr = curr.parent
                preview_tree.insert(folder_iid, "end", text=f"🔗 {bm.title}", values=("/".join(parent_path),))
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", padx=10, pady=5)

        def on_apply():
            dialog.destroy()
            self._execute_classification_plan(plan, base_node)

        ttk.Button(btn_frame, text="Apply", command=on_apply).pack(side="right")
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="right", padx=5)

    def cmd_edit_rules(self) -> None:
        tl = tk.Toplevel(self)
        tl.title("Edit Classify Rules (JSON)")
        tl.geometry("720x520")
        text = tk.Text(tl, wrap="none")
        text.pack(fill="both", expand=True, padx=5, pady=5)
        try:
            pretty = json.dumps(self.rules, ensure_ascii=False, indent=2)
        except Exception:
            pretty = "{}"
        text.insert("1.0", pretty)
        btns = ttk.Frame(tl)
        btns.pack(fill="x", padx=5, pady=5)

        def save_rules() -> None:
            try:
                data = json.loads(text.get("1.0", "end-1c"))
                self.rules = data
                if self.rules_path:
                    with open(self.rules_path, "w", encoding="utf-8") as wf:
                        json.dump(self.rules, wf, ensure_ascii=False, indent=2)
                messagebox.showinfo("Rules", "Saved.", parent=tl)
                tl.destroy()
            except Exception as e:
                messagebox.showerror("Rules", f"Invalid JSON:\n{e}", parent=tl)

        ttk.Button(btns, text="Save", command=save_rules).pack(side="right")
        ttk.Button(btns, text="Cancel", command=tl.destroy).pack(side="right", padx=6)

    def cmd_smart_classify(self):
        """AI分類の初回実行を行う。"""
        self.progress_history = []
        self._smart_cancelled = False
        self.last_classification_prompts = []
        selection_iids = self.tree.selection()
        bookmarks_to_process = []

        def collect(node):
            if not node: return
            if node.type == 'bookmark' and node.url:
                bookmarks_to_process.append(node)
            elif node.type == 'folder':
                for ch in node.children: collect(ch)

        if not selection_iids:
            collect(self.root_node)
        else:
            for iid in selection_iids:
                collect(self._node_of(iid))
        bookmarks_to_process = list({id(b): b for b in bookmarks_to_process}.values())
        self.last_classified_bookmarks = bookmarks_to_process
        if not bookmarks_to_process:
            messagebox.showinfo("Smart Classify", "対象ブックマークがありません。");
            return
        total_to_process = min(len(bookmarks_to_process), self.max_smart_items)
        self._show_smart_progress(total_to_process)
        threading.Thread(target=self._run_ai_classification_worker, args=(bookmarks_to_process, None),
                         daemon=True).start()

    def _run_ai_classification_worker(self, bookmarks, additional_prompt):
        """AI分類器を別スレッドで実行する。"""
        try:
            bookmark_nodes = [BookmarkNode(title=b.title, url=b.url) for b in bookmarks]
            classifier = AIBookmarkClassifier(logger=self.logger)

            def progress_callback(processed, total, sent, received):
                if not self._smart_cancelled:
                    self.ui_queue.put(('progress_update', (processed, total, sent, received)))

            classifier.set_progress_callback(progress_callback)
            priority_terms = self.config_manager.get_priority_terms()
            result = classifier.classify_bookmarks(
                bookmarks=bookmark_nodes, priority_terms=priority_terms, max_items=self.max_smart_items,
                additional_prompt=additional_prompt
            )
            if not self._smart_cancelled:
                self.ui_queue.put(('smart_classify_result', result))
        except Exception as e:
            self.logger.error("AI Classification worker failed: %s", str(e), exc_info=True)
            if not self._smart_cancelled:
                self.ui_queue.put(('error', f"Smart Classify failed: {e}"))

    def _show_smart_progress(self, total):
        """スマート分類の進捗ダイアログを表示（不確定モード版）。"""
        if self._smart_dialog and self._smart_dialog.winfo_exists(): return
        d = tk.Toplevel(self)
        d.title("Smart Classify")
        d.geometry("400x150")
        d.transient(self)
        d.grab_set()
        d.resizable(False, False)
        self._smart_dialog = d
        ttk.Label(d, text=f"AIが最大{total}件のブックマークを解析中です...").pack(pady=12)
        pb = ttk.Progressbar(d, mode="indeterminate")
        pb.pack(fill="x", padx=14, pady=5)
        pb.start(10)
        self.progress_var = None
        self.progress_label = None
        self.traffic_label = ttk.Label(d, text="AIと通信中...")
        self.traffic_label.pack(pady=8)

        def on_hide():
            self._smart_cancelled = True
            self.traffic_label = None
            if self._smart_dialog:
                try:
                    self._smart_dialog.destroy()
                except tk.TclError:
                    pass
            self._smart_dialog = None

        ttk.Button(d, text="Cancel", command=on_hide).pack(pady=10)
        d.protocol("WM_DELETE_WINDOW", on_hide)

    def cmd_check_proxy(self) -> None:
        proxy_info = self._get_proxies_for_requests()
        if not proxy_info:
            if not self.use_proxy_var.get():
                messagebox.showinfo("Proxy Check", "プロキシは使用しない設定です。")
            else:
                messagebox.showinfo("Proxy Check", "プロキシ設定がconfig.iniに見つかりません。")
            return
        dialog = tk.Toplevel(self)
        dialog.title("Proxy Test")
        dialog.geometry("300x100")
        dialog.transient(self)
        dialog.grab_set()
        label = ttk.Label(dialog, text="Testing proxy connection...")
        label.pack(pady=20)
        self.update_idletasks()

        def worker():
            try:
                test_url = "http://www.google.com/generate_204"
                response = requests.get(test_url, proxies=proxy_info['proxies'], auth=proxy_info['auth'], timeout=10)
                response.raise_for_status()
                self.ui_queue.put(('proxy_check_success', dialog))
            except Exception as e:
                self.ui_queue.put(('proxy_check_failure', (dialog, str(e))))

        threading.Thread(target=worker, daemon=True).start()

    def cmd_set_smart_classify_limit(self) -> None:
        current_limit = self.max_smart_items
        new_limit = simpledialog.askinteger(
            "Smart Classify Limit", "スマート分類の最大ブックマーク数を入力してください（50～1000）：",
            initialvalue=current_limit, minvalue=50, maxvalue=1000, parent=self
        )
        if new_limit is not None: self.max_smart_items = new_limit
        messagebox.showinfo("Smart Classify Limit", f"最大処理数を {new_limit} に設定しました。")

    def cmd_set_title_fetch_timeout(self) -> None:
        new_timeout = simpledialog.askinteger(
            "Title Fetch Timeout", "タイトル取得のタイムアウト秒数を入力してください（2～60）：",
            initialvalue=self.fetch_timeout, minvalue=2, maxvalue=60, parent=self
        )
        if new_timeout is not None:
            self.fetch_timeout = new_timeout
            messagebox.showinfo("Title Fetch Timeout", f"タイムアウトを {new_timeout} 秒に設定しました。")

    def cmd_show_progress_chart(self):
        if not self.progress_history:
            messagebox.showinfo("Progress Chart", "進捗データがありません。スマート分類を先に行ってください。");
            return
        dialog = tk.Toplevel(self)
        dialog.title("Smart Classification Progress")
        dialog.geometry("500x350")
        canvas = tk.Canvas(dialog, bg="white")
        canvas.pack(fill="both", expand=True, padx=10, pady=10)
        history = self.progress_history
        max_val = max(history) if history else 1
        canvas_width, canvas_height, padding = 480, 330, 20
        chart_area_height = canvas_height - (padding * 2)
        chart_area_width = canvas_width - (padding * 2)
        bar_count = len(history)
        bar_width = chart_area_width / (bar_count + 1) if bar_count > 0 else chart_area_width
        canvas.create_line(padding, padding, padding, canvas_height - padding)
        canvas.create_line(padding, canvas_height - padding, canvas_width - padding, canvas_height - padding)
        for i, val in enumerate(history):
            x0 = padding + (i * bar_width) + (bar_width * 0.1)
            y0 = canvas_height - padding - ((val / max_val) * chart_area_height)
            x1 = x0 + bar_width * 0.8
            y1 = canvas_height - padding
            canvas.create_rectangle(x0, y0, x1, y1, fill="#4CAF50", outline="#388E3C")
            if i % (len(history) // 10 or 1) == 0:
                canvas.create_text(x0 + (bar_width * 0.4), y1 + 10, text=str(val), anchor="n")
        canvas.create_text(canvas_width / 2, padding / 2, text="Processed Bookmarks Over Time", font=("", 12, "bold"))
        canvas.create_text(padding - 10, canvas_height / 2, text=f"Total: {max_val}", angle=90, anchor="s")

    def _domain_of(self, url: str) -> str:
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return ""

    def _show_smart_classify_preview(self, plan: dict, base_node: Node) -> None:
        """AI分類の結果プレビューダイアログを表示する。"""
        if not plan:
            if self.last_classification_prompts:
                messagebox.showinfo("Smart Classify", "現在の指示では、これ以上分類できる候補が見つかりませんでした。")
            else:
                messagebox.showinfo("Smart Classify", "AIによる分類候補が見つかりませんでした。")
            return
        dialog = tk.Toplevel(self)
        dialog.title("Smart Classification Preview (AI)")
        dialog.geometry("700x500")
        dialog.transient(self)
        dialog.grab_set()
        preview_tree = ttk.Treeview(dialog, columns=("original_location"), show="tree headings")
        preview_tree.heading("#0", text="Bookmark to Move")
        preview_tree.heading("original_location", text="Original Location")
        preview_tree.column("#0", width=400)
        preview_tree.column("original_location", width=200)
        preview_tree.pack(fill="both", expand=True, padx=10, pady=10)
        for folder_name, bookmarks in sorted(plan.items()):
            folder_iid = preview_tree.insert("", "end", text=f"📁 Create in '{base_node.title}': {folder_name}",
                                             open=True)
            for bm in bookmarks:
                parent_path = []
                curr = bm.parent
                while curr and curr != self.root_node:
                    parent_path.insert(0, curr.title or "(Untitled)")
                    curr = curr.parent
                preview_tree.insert(folder_iid, "end", text=f"🔗 {bm.title}", values=("/".join(parent_path),))
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", padx=10, pady=5)

        def on_apply():
            dialog.destroy()
            self._execute_classification_plan(plan, base_node)

        def on_reclassify():
            """再分類ボタンが押されたときの処理"""
            dialog.destroy()
            prompt_dialog = CustomPromptDialog(self, title="AIへの追加指示",
                                               previous_prompts=self.last_classification_prompts)
            new_prompt = prompt_dialog.result
            if new_prompt:
                self.last_classification_prompts.append(new_prompt)
                bookmarks_to_reclassify = self.last_classified_bookmarks
                if not bookmarks_to_reclassify:
                    messagebox.showerror("Error", "再分類対象のブックマークリストが見つかりませんでした。");
                    return
                full_prompt = "\n- ".join(self.last_classification_prompts)
                total_to_process = min(len(bookmarks_to_reclassify), self.max_smart_items)
                self._show_smart_progress(total_to_process)
                threading.Thread(
                    target=self._run_ai_classification_worker,
                    args=(bookmarks_to_reclassify, full_prompt), daemon=True
                ).start()

        ttk.Button(btn_frame, text="Apply", command=on_apply).pack(side="right")
        ttk.Button(btn_frame, text="再分類...", command=on_reclassify).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="right", padx=5)

    def cmd_fix_titles_from_url(self) -> None:
        """選択中のブックマークのタイトルをウェブサイトから取得して修正する。"""
        sels = list(self.tree.selection())
        if not sels:
            messagebox.showinfo("Fix Titles", "対象のブックマークを選択してください。フォルダ選択もOKです。")
            return
        targets = []

        def collect(node):
            if not node: return
            if node.type == "bookmark" and node.url:
                t = (node.title or "").strip()
                if t == node.url.strip() or is_valid_url(t):
                    targets.append(node)
            elif node.type == "folder":
                for ch in node.children: collect(ch)

        for iid in sels:
            collect(self._node_of(iid))
        targets = list({id(n): n for n in targets}.values())
        if not targets:
            messagebox.showinfo("Fix Titles", "選択範囲に修正対象（タイトルがURLのブックマーク）はありません。")
            return
        self._show_titlefix_progress(len(targets))
        threading.Thread(target=self._fix_titles_worker, args=(targets,), daemon=True).start()

    def _show_titlefix_progress(self, total: int):
        """タイトル修正の進捗ダイアログ"""
        if self._titlefix_dialog and self._titlefix_dialog.winfo_exists(): return
        d = tk.Toplevel(self)
        d.title("Fix Titles from URL")
        d.geometry("360x140")
        d.transient(self)
        d.grab_set()
        d.resizable(False, False)
        self._titlefix_dialog = d
        self._titlefix_cancelled = False
        ttk.Label(d, text=f"合計 {total} 件のタイトルを修正中...").pack(pady=10)
        self._titlefix_var = tk.DoubleVar(value=0)
        pb = ttk.Progressbar(d, variable=self._titlefix_var, maximum=total, mode="determinate")
        pb.pack(fill="x", padx=12, pady=6)
        self._titlefix_label = ttk.Label(d, text=f"0 / {total}")
        self._titlefix_label.pack()

        def on_cancel():
            self._titlefix_cancelled = True
            try:
                d.destroy()
            except tk.TclError:
                pass

        ttk.Button(d, text="Cancel", command=on_cancel).pack(pady=10)
        d.protocol("WM_DELETE_WINDOW", on_cancel)

    def _fix_titles_worker(self, nodes):
        """別スレッド：各URLにアクセスし、タイトルを上書き。"""
        processed = 0
        total = len(nodes)
        for n in nodes:
            if getattr(self, "_titlefix_cancelled", False): break
            new_title = None
            try:
                proxy_info = self._get_proxies_for_requests()
                proxies = proxy_info['proxies'] if proxy_info else None
                auth = proxy_info['auth'] if proxy_info else None

                resp = requests.get(n.url, headers={'User-Agent': 'Mozilla/5.0'}, proxies=proxies, auth=auth,
                                    timeout=self.fetch_timeout)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                title_tag = soup.find("meta", property="og:title") or soup.find("title")
                if title_tag and title_tag.name == "meta":
                    new_title = title_tag.get("content")
                elif title_tag:
                    new_title = title_tag.text
                if new_title: new_title = new_title.strip()
                if not new_title: new_title = "ERROR: No Title Found"
            except Exception as e:
                try:
                    self.logger.warning("Title fix failed for %s: %s", n.url, str(e))
                except Exception:
                    pass
                new_title = f"ERROR: {type(e).__name__}"
            n.title = new_title
            processed += 1
            self.ui_queue.put(('titlefix_progress', (processed, total)))
        self.ui_queue.put(('titlefix_done', None))

    # ★★★ 新機能 ★★★
    def cmd_merge_folders(self) -> None:
        """選択されたフォルダ内の重複する名前のフォルダを統合する。"""
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Merge Folders", "フォルダを選択してください。")
            return

        iid = sel[0]
        node = self._node_of(iid)

        # 選択されたアイテムがフォルダでない場合、その親フォルダを対象とする
        target_folder = node if node.type == 'folder' else node.parent

        if not target_folder:
            messagebox.showerror("Error", "対象フォルダが見つかりません。")
            return

        folders_by_name = {}
        nodes_to_remove = []
        merged_count = 0

        # フォルダ内の子要素をループ
        for child in list(target_folder.children):  # イテレート中にリストを変更するためコピー
            if child.type == 'folder':
                # 大文字小文字を区別しないキー
                key = child.title.lower()
                if key in folders_by_name:
                    # 重複が見つかった場合
                    primary_folder = folders_by_name[key]
                    self.logger.info(f"Merging '{child.title}' into '{primary_folder.title}'")

                    # 重複フォルダの中身をすべてプライマリフォルダに移動
                    for sub_child in list(child.children):
                        child.children.remove(sub_child)
                        primary_folder.append(sub_child)

                    nodes_to_remove.append(child)
                    merged_count += 1
                else:
                    # 初めて見るフォルダ名
                    folders_by_name[key] = child

        # 空になった重複フォルダを削除
        if nodes_to_remove:
            for node_to_remove in nodes_to_remove:
                target_folder.children.remove(node_to_remove)
            self._refresh_tree()
            messagebox.showinfo("Merge Folders", f"{merged_count}個の重複フォルダを統合しました。")
        else:
            messagebox.showinfo("Merge Folders", "重複する名前のフォルダは見つかりませんでした。")


if __name__ == "__main__":
    app = App()
    app.mainloop()
import os
import io
import json
import html
import time
import re
import threading
import queue
import configparser
from html.parser import HTMLParser
from urllib.parse import urlparse, quote_plus, urlunparse
from collections import OrderedDict
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
import tkinter.font as tkfont
from PIL import Image, ImageTk
import requests
from bs4 import BeautifulSoup
from ttkthemes import ThemedTk
import logging
from logging.handlers import RotatingFileHandler

# AI分類モジュールをインポート
from ai_classifier import AIBookmarkClassifier, BookmarkNode

# Netscape Bookmark HTML Format
BOOKMARK_HTML_HEADER = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
"""
BOOKMARK_HTML_FOOTER = """</DL><p>
"""


# ==============================================================================
# ▼▼▼ レビュー反映 6: バリデーション強化 ▼▼▼
# ==============================================================================
def is_valid_url(url: str) -> bool:
    """より厳密なURL検証"""
    if not url:
        return False
    try:
        result = urlparse(url)
        if not all([result.scheme, result.netloc]):
            return False
        if result.scheme.lower() not in ['http', 'https', 'ftp', 'file']:
            return False
        if result.scheme.lower() in ['http', 'https']:
            # ホスト名の形式チェック（基本的な検証）
            hostname_pattern = re.compile(
                r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$')
            if not hostname_pattern.match(result.netloc.split(':')[0]):
                return False
        return True
    except (ValueError, AttributeError):
        return False


# ==============================================================================
# ▼▼▼ レビュー反映 5: コード構造の改善 (ConfigManager) ▼▼▼
# ==============================================================================
class ConfigManager:
    """設定ファイル(config.ini)の管理を専門に行うクラス。"""

    def __init__(self, config_path='config.ini'):
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        self.load_config()

    def load_config(self):
        if os.path.exists(self.config_path):
            self.config.read(self.config_path, encoding='utf-8')

    def get_proxy_settings(self):
        if 'Proxy' not in self.config:
            return None
        proxy_section = self.config['Proxy']
        return {
            'url': proxy_section.get('url'),
            'user': proxy_section.get('user'),
            'password': proxy_section.get('password')
        }

    def get_priority_terms(self):
        if not (self.config.has_section('Classifier') and
                self.config.has_option('Classifier', 'priority_terms')):
            return []
        terms_str = self.config.get('Classifier', 'priority_terms')
        return [term.strip() for term in terms_str.split(',') if term.strip()]


# ==============================================================================
# ▼▼▼ レビュー反映 4: メモリ管理の改善 (LRUCache) ▼▼▼
# ==============================================================================
class LRUCache(OrderedDict):
    """容量制限付きのキャッシュ(Least Recently Used)。"""

    def __init__(self, maxsize=100):
        super().__init__()
        self.maxsize = maxsize

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            self.popitem(last=False)


class Node:
    __slots__ = ("type", "title", "url", "add_date", "last_modified", "children", "parent")

    def __init__(self, type_, title="", url="", add_date="", last_modified=""):
        self.type = type_
        self.title = title
        self.url = url
        self.add_date = add_date
        self.last_modified = last_modified
        self.children = []
        self.parent = None

    def append(self, child):
        child.parent = self
        self.children.append(child)

    def __repr__(self):
        return f"Node(type='{self.type}', title='{self.title}')"


class NetscapeBookmarkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("folder", "Bookmarks")
        self.stack = [self.root]
        self._pending_link = None
        self._pending_folder = None
        self._capture_text_for = None
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        tag = tag.lower()
        if tag == "h3":
            self._pending_folder = Node("folder", title="", add_date=attr.get("add_date", ""),
                                        last_modified=attr.get("last_modified", ""))
            self._capture_text_for = "folder";
            self._buffer = []
        elif tag == "a":
            self._pending_link = Node("bookmark", title="", url=attr.get("href", ""), add_date=attr.get("add_date", ""),
                                      last_modified=attr.get("last_modified", ""))
            self._capture_text_for = "link";
            self._buffer = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("h3", "a"):
            text = "".join(self._buffer).strip()
            self._buffer = []
            if self._capture_text_for == "folder" and self._pending_folder:
                self._pending_folder.title = text or "Untitled"
                self.stack[-1].append(self._pending_folder)
                self.stack.append(self._pending_folder)
                self._pending_folder = None
            elif self._capture_text_for == "link" and self._pending_link:
                self._pending_link.title = text
                self.stack[-1].append(self._pending_link)
                self._pending_link = None
            self._capture_text_for = None
        elif tag == "dl":
            if len(self.stack) > 1: self.stack.pop()

    def handle_data(self, data):
        if self._capture_text_for in ("folder", "link"): self._buffer.append(data)


def export_netscape_html(root: Node) -> str:
    out = io.StringIO()
    out.write(BOOKMARK_HTML_HEADER)

    def esc(s: str) -> str:
        return html.escape(s or "", quote=True)

    def write_folder(node: Node, indent: int = 1) -> None:
        ind = "    " * indent
        out.write(
            f'{ind}<DT><H3 ADD_DATE="{esc(node.add_date)}" LAST_MODIFIED="{esc(node.last_modified)}">{esc(node.title)}</H3>\n')
        out.write(f"{ind}<DL><p>\n")
        for ch in node.children:
            if ch.type == "folder":
                write_folder(ch, indent + 1)
            else:
                out.write(
                    f'{ind}    <DT><A HREF="{esc(ch.url)}" ADD_DATE="{esc(ch.add_date)}" LAST_MODIFIED="{esc(ch.last_modified)}">{esc(ch.title)}</A>\n')
        out.write(f"{ind}</DL><p>\n")

    for ch in root.children:
        if ch.type == "folder":
            write_folder(ch, 1)
        else:
            out.write(
                f'    <DT><A HREF="{esc(ch.url)}" ADD_DATE="{esc(ch.add_date)}" LAST_MODIFIED="{esc(ch.last_modified)}">{esc(ch.title)}</A>\n')
    out.write(BOOKMARK_HTML_FOOTER)
    return out.getvalue()


class CustomPromptDialog(simpledialog.Dialog):
    def __init__(self, parent, title=None, previous_prompts=None):
        self.previous_prompts = previous_prompts or []
        super().__init__(parent, title)

    def body(self, master):
        self.result = None
        if self.previous_prompts:
            ttk.Label(master, text="現在の指示:", font=("", 10, "bold")).pack(anchor="w", padx=5, pady=(5, 0))
            history_text = tk.Text(master, height=4, width=60, wrap="word", relief="sunken", borderwidth=1)
            history_text.pack(padx=5, pady=2, fill="x", expand=True)
            display_str = "\n".join([f"- {p}" for p in self.previous_prompts])
            history_text.insert("1.0", display_str)
            history_text.config(state="disabled", background="#f0f0f0")
        ttk.Label(master, text="追加の指示を入力:", font=("", 10, "bold")).pack(anchor="w", padx=5, pady=(10, 0))
        self.text_widget = tk.Text(master, height=8, width=60, wrap="word")
        self.text_widget.pack(padx=5, pady=5, fill="both", expand=True)
        return self.text_widget

    def apply(self):
        self.result = self.text_widget.get("1.0", "end-1c").strip()


class App(ThemedTk):
    def __init__(self):
        super().__init__(theme="clam")
        self.title("Bookmark Studio — Chrome Bookmarks Organizer")
        self.geometry("1400x800")
        self.minsize(1000, 600)

        self.logger = logging.getLogger(__name__)
        self._setup_logging()

        self.config_manager = ConfigManager()

        self.root_node = Node("folder", "Bookmarks")
        self.current_file = None
        self.rules = self._default_rules()
        self.rules_path = None
        self._iid_to_node = {}
        self.preview_cache = LRUCache(maxsize=50)
        self.ui_queue = queue.Queue()
        self._search_after_id = None
        self.open_nodes = set()
        self.search_index = {}
        self.dragging_iids = None
        self.drag_start_iid = None
        self.drag_window = None
        self.drop_line = None
        self.drop_target_info = None
        self._img_cache = LRUCache(maxsize=200)
        self.max_smart_items = 300
        self.progress_history = []
        self.use_proxy_var = tk.BooleanVar(value=True)

        self.last_classified_bookmarks = []
        self.last_classification_prompts = []

        self._smart_dialog = None
        self._smart_cancelled = False
        self.progress_var = None
        self.progress_label = None
        self.traffic_label = None

        self._titlefix_dialog = None
        self._titlefix_cancelled = False
        self._titlefix_var = None
        self._titlefix_label = None
        self.fetch_timeout = 10

        self._build_ui()
        self._build_search_index()
        self.after(100, self._process_ui_queue)

    def _setup_logging(self):
        """ログ設定を改善。"""
        self.logger.setLevel(logging.INFO)
        log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        file_handler = RotatingFileHandler('bookmark_editor.log', maxBytes=1024 * 1024 * 5, backupCount=3,
                                           encoding='utf-8')
        file_handler.setFormatter(log_formatter)
        file_handler.setLevel(logging.INFO)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        console_handler.setLevel(logging.WARNING)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def _build_ui(self) -> None:
        menubar = tk.Menu(self)
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="Open HTML…", command=self.cmd_open, accelerator="Ctrl+O")
        filem.add_command(label="Save", command=self.cmd_save, accelerator="Ctrl+S")
        filem.add_command(label="Save As…", command=self.cmd_save_as, accelerator="Ctrl+Shift+S")
        filem.add_separator()
        filem.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filem)

        editm = tk.Menu(menubar, tearoff=0)
        editm.add_command(label="New Folder", command=self.cmd_new_folder, accelerator="Ctrl+Shift+N")
        editm.add_command(label="New Bookmark", command=self.cmd_new_bookmark, accelerator="Ctrl+N")
        editm.add_command(label="Rename", command=self.cmd_rename, accelerator="F2")
        editm.add_command(label="Edit URL", command=self.cmd_edit_url)
        editm.add_separator()
        editm.add_command(label="Move to Folder…", command=self.cmd_move_to_folder)
        editm.add_command(label="Move Up", command=self.cmd_move_up, accelerator="Ctrl+Up")
        editm.add_command(label="Delete", command=self.cmd_delete, accelerator="Delete")
        menubar.add_cascade(label="Edit", menu=editm)

        toolsm = tk.Menu(menubar, tearoff=0)
        toolsm.add_checkbutton(label="プロキシを使用する", variable=self.use_proxy_var, onvalue=True, offvalue=False)
        toolsm.add_command(label="プロキシ接続をテスト", command=self.cmd_check_proxy)
        toolsm.add_separator()
        toolsm.add_command(label="Sort by Title (A→Z)", command=lambda: self.cmd_sort("title"))
        toolsm.add_command(label="Sort by Domain (A→Z)", command=lambda: self.cmd_sort("domain"))
        toolsm.add_command(label="Deduplicate in Folder", command=self.cmd_dedupe)
        toolsm.add_command(label="Merge Duplicate Folders", command=self.cmd_merge_folders)  # ★★★ 新機能 ★★★
        toolsm.add_separator()
        toolsm.add_command(label="Auto Classify (Rules)…", command=self.cmd_show_classify_preview)
        toolsm.add_command(label="Smart Classify (AI)…", command=self.cmd_smart_classify)
        toolsm.add_command(label="Set Smart Classify Limit…", command=self.cmd_set_smart_classify_limit)
        toolsm.add_separator()
        toolsm.add_command(label="Fix Titles from URL…", command=self.cmd_fix_titles_from_url)
        toolsm.add_command(label="Set Title Fetch Timeout…", command=self.cmd_set_title_fetch_timeout)
        toolsm.add_separator()
        toolsm.add_command(label="Edit Classify Rules…", command=self.cmd_edit_rules)
        toolsm.add_command(label="Show Progress Chart", command=self.cmd_show_progress_chart)
        menubar.add_cascade(label="Tools", menu=toolsm)

        self.config(menu=menubar)

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace("w", self._on_search_var_changed)
        ent = ttk.Entry(top, textvariable=self.search_var, width=44)
        ent.pack(side="left", padx=(6, 8))
        ttk.Button(top, text="Clear", command=self._clear_search).pack(side="left", padx=(6, 0))

        main = ttk.Panedwindow(self, orient="horizontal")
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main)
        main.add(left, weight=3)

        cols = ("url",)
        self.tree = ttk.Treeview(left, columns=cols, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Title")
        self.tree.heading("url", text="URL")
        self.tree.column("#0", width=600, anchor="w")
        self.tree.column("url", width=500, anchor="w")

        ysb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=ysb.set, xscroll=xsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(main, padding=8)
        main.add(right, weight=1)
        self.info_title = tk.StringVar(value="—")
        self.info_url = tk.StringVar(value="—")
        self.preview_title = tk.StringVar(value="")
        self.preview_desc = tk.StringVar(value="")
        ttk.Label(right, text="Selected:").pack(anchor="w")
        ttk.Label(right, textvariable=self.info_title, font=("", 10, "bold")).pack(anchor="w", pady=(0, 6))
        ttk.Label(right, text="URL:").pack(anchor="w")
        ttk.Entry(right, textvariable=self.info_url, state="readonly").pack(fill="x")

        ttk.Separator(right).pack(fill="x", pady=8)
        ttk.Label(right, text="Preview:").pack(anchor="w")
        ttk.Label(right, textvariable=self.preview_title, wraplength=200).pack(anchor="w")
        ttk.Label(right, textvariable=self.preview_desc, wraplength=200).pack(anchor="w")

        ttk.Separator(right).pack(fill="x", pady=8)
        ttk.Button(right, text="New Folder", command=self.cmd_new_folder).pack(fill="x")
        ttk.Button(right, text="New Bookmark", command=self.cmd_new_bookmark).pack(fill="x", pady=6)
        ttk.Button(right, text="Rename (F2)", command=self.cmd_rename).pack(fill="x")
        ttk.Button(right, text="Edit URL", command=self.cmd_edit_url).pack(fill="x", pady=6)
        ttk.Button(right, text="Move to Folder…", command=self.cmd_move_to_folder).pack(fill="x")
        ttk.Button(right, text="Move Up (Ctrl+Up)", command=self.cmd_move_up).pack(fill="x", pady=6)
        ttk.Button(right, text="Delete", command=self.cmd_delete).pack(fill="x")

        ttk.Separator(right).pack(fill="x", pady=8)
        ttk.Button(right, text="Sort by Title", command=lambda: self.cmd_sort("title")).pack(fill="x")
        ttk.Button(right, text="Sort by Domain", command=lambda: self.cmd_sort("domain")).pack(fill="x", pady=6)
        ttk.Button(right, text="Deduplicate in Folder", command=self.cmd_dedupe).pack(fill="x")
        ttk.Button(right, text="Merge Duplicate Folders", command=self.cmd_merge_folders).pack(fill="x",
                                                                                               pady=6)  # ★★★ 新機能 ★★★
        ttk.Button(right, text="Auto Classify…", command=self.cmd_show_classify_preview).pack(fill="x")
        ttk.Button(right, text="Smart Classify (AI)…", command=self.cmd_smart_classify).pack(fill="x", pady=6)
        ttk.Separator(right).pack(fill="x", pady=8)
        ttk.Button(right, text="Expand All", command=self.cmd_expand_all).pack(fill="x")
        ttk.Button(right, text="Collapse All", command=self.cmd_collapse_all).pack(fill="x", pady=6)

        self.ctx = tk.Menu(self, tearoff=0)
        self.ctx.add_command(label="New Folder", command=self.cmd_new_folder)
        self.ctx.add_command(label="New Bookmark", command=self.cmd_new_bookmark)
        self.ctx.add_separator()
        self.ctx.add_command(label="Rename", command=self.cmd_rename)
        self.ctx.add_command(label="Edit URL", command=self.cmd_edit_url)
        self.ctx.add_command(label="Move to Folder…", command=self.cmd_move_to_folder)
        self.ctx.add_command(label="Move Up", command=self.cmd_move_up)
        self.ctx.add_separator()
        self.ctx.add_command(label="Merge Duplicate Folders", command=self.cmd_merge_folders)  # ★★★ 新機能 ★★★
        self.ctx.add_separator()
        self.ctx.add_command(label="Delete", command=self.cmd_delete)
        self.tree.bind("<Button-3>", self._popup_ctx)

        self.bind_all("<Control-o>", lambda e: self.cmd_open())
        self.bind_all("<Control-s>", lambda e: self.cmd_save())
        self.bind_all("<Control-S>", lambda e: self.cmd_save_as())
        self.bind_all("<Control-n>", lambda e: self.cmd_new_bookmark())
        self.bind_all("<Control-N>", lambda e: self.cmd_new_folder())
        self.bind_all("<Delete>", lambda e: self.cmd_delete())
        self.bind_all("<F2>", lambda e: self.cmd_rename())
        self.bind_all("<Control-Up>", lambda e: self.cmd_move_up())

        self.tree.bind("<<TreeviewSelect>>", self._update_info_from_selection)
        self.tree.bind("<ButtonPress-1>", self._on_tree_press)
        self.tree.bind("<B1-Motion>", self._on_tree_drag)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release)
        self.tree.bind("<Double-1>", self._on_double_click_inline_edit)
        self.tree.bind("<<TreeviewOpen>>", self._on_folder_open)
        self.tree.bind("<<TreeviewClose>>", self._on_folder_close)

        default_font = tkfont.nametofont("TkDefaultFont")
        bold_font = default_font.copy()
        bold_font.configure(weight="bold")

        self.tree.tag_configure('oddrow', background='#FFFFFF')
        self.tree.tag_configure('evenrow', background='#F0F0F0')
        self.tree.tag_configure('nourl', foreground='gray')
        self.tree.tag_configure('folder', font=bold_font)
        self.tree.tag_configure("match", background="#FFFACD")

        style = ttk.Style()
        style.configure("Line.TFrame", background="blue")
        self._refresh_tree()

    def _process_ui_queue(self):
        """UIキューを処理してスレッドセーフな更新を行う。"""
        try:
            while True:
                task_type, data = self.ui_queue.get_nowait()
                if task_type == 'smart_classify_result':
                    if self._smart_dialog and self._smart_dialog.winfo_exists():
                        self._smart_dialog.destroy()
                    self._smart_dialog = None
                    if not self._smart_cancelled:
                        result_obj = data
                        plan = result_obj.plan
                        all_nodes_to_move = []
                        original_nodes_map = {(node.title, node.url): node for node in self.last_classified_bookmarks}
                        final_plan = {}
                        for folder, bm_nodes in plan.items():
                            original_nodes = []
                            for bm_node in bm_nodes:
                                original = original_nodes_map.get((bm_node.title, bm_node.url))
                                if original:
                                    original_nodes.append(original)
                            if original_nodes:
                                final_plan[folder] = original_nodes
                                all_nodes_to_move.extend(original_nodes)
                        base_node = self._find_common_parent(all_nodes_to_move)
                        self._show_smart_classify_preview(final_plan, base_node)
                elif task_type == 'error':
                    if self._smart_dialog and self._smart_dialog.winfo_exists():
                        self._smart_dialog.destroy()
                    self._smart_dialog = None
                    messagebox.showwarning("Error", data)
                elif task_type == 'progress_update':
                    loaded_count, total_bms, sent_bytes, recv_bytes = data
                    self.progress_history.append(loaded_count)
                    if self.traffic_label and self._smart_dialog and self._smart_dialog.winfo_exists():
                        sent_kb = sent_bytes / 1024
                        recv_kb = recv_bytes / 1024
                        self.traffic_label.config(text=f"Traffic: Sent {sent_kb:.2f} KB | Received {recv_kb:.2f} KB")
                elif task_type == 'proxy_check_success':
                    dialog = data
                    if dialog.winfo_exists(): dialog.destroy()
                    messagebox.showinfo("Proxy Check", "プロキシ接続は正常です。")
                elif task_type == 'proxy_check_failure':
                    dialog, error_msg = data
                    if dialog.winfo_exists(): dialog.destroy()
                    messagebox.showerror("Proxy Check",
                                         f"プロキシ接続に失敗しました。\nconfig.iniの設定を確認してください。\n\nエラー: {error_msg}")
                elif task_type == 'preview':
                    url, preview_data = data
                    self.preview_cache[url] = preview_data
                    sels = self.tree.selection()
                    if len(sels) == 1:
                        node = self._node_of(sels[0])
                        if node and node.url == url:
                            self._update_preview_pane(preview_data)
                elif task_type == 'titlefix_progress':
                    processed, total = data
                    if self._titlefix_dialog and self._titlefix_dialog.winfo_exists():
                        try:
                            self._titlefix_var.set(processed)
                            self._titlefix_label.config(text=f"{processed} / {total}")
                        except tk.TclError:
                            pass
                elif task_type == 'titlefix_done':
                    if self._titlefix_dialog and self._titlefix_dialog.winfo_exists():
                        try:
                            self._titlefix_dialog.destroy()
                        except tk.TclError:
                            pass
                    self._titlefix_dialog = None
                    self._refresh_tree()
                    messagebox.showinfo("Fix Titles", "処理が完了しました。")
        except queue.Empty:
            pass
        finally:
            self.after(100, self._process_ui_queue)

    def _get_proxies_for_requests(self):
        """requestsライブラリ用にプロキシ設定を返す。"""
        if not self.use_proxy_var.get():
            return None

        settings = self.config_manager.get_proxy_settings()
        if not settings or not settings.get('url'):
            return None

        proxy_url = settings['url']
        user = settings['user']
        password = settings['password']

        auth = (user, password) if user and password else None

        proxies = {
            'http': proxy_url,
            'https': proxy_url
        }
        return {'proxies': proxies, 'auth': auth}

    def _fetch_preview_worker(self, url: str):
        """ブックマークのプレビュー情報を非同期で取得（リトライ機能付き）。"""
        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                proxy_info = self._get_proxies_for_requests()
                proxies = proxy_info['proxies'] if proxy_info else None
                auth = proxy_info['auth'] if proxy_info else None

                resp = requests.get(
                    url,
                    timeout=5,
                    headers={'User-Agent': 'Mozilla/5.0'},
                    proxies=proxies,
                    auth=auth
                )
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "html.parser")
                title_tag = soup.find("meta", property="og:title") or soup.find("title")
                title = title_tag.get("content") if title_tag and title_tag.name == "meta" else (
                    title_tag.text if title_tag else "")
                desc_tag = soup.find("meta", property="og:description") or soup.find("meta",
                                                                                     attrs={"name": "description"})
                desc = desc_tag.get("content") if desc_tag else ""
                result = {"title": title.strip(), "description": desc.strip()}
                self.ui_queue.put(('preview', (url, result)))
                return

            except requests.exceptions.Timeout as e:
                self.logger.warning(f"Timeout for {url} (attempt {attempt + 1}): {e}")
            except requests.exceptions.ConnectionError as e:
                self.logger.warning(f"Connection error for {url} (attempt {attempt + 1}): {e}")
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    self.logger.warning(f"URL not found (404) for {url}. No retries.")
                    break
                self.logger.warning(f"HTTP error for {url} (attempt {attempt + 1}): {e}")
            except Exception as e:
                self.logger.error(f"Unexpected error for {url}: {e}")
                break

            if attempt < max_retries - 1:
                time.sleep(retry_delay * (2 ** attempt))

        result = {"title": "Could not load preview", "description": ""}
        self.ui_queue.put(('preview', (url, result)))

    def _popup_ctx(self, e) -> None:
        try:
            self.ctx.tk_popup(e.x_root, e.y_root)
        finally:
            self.ctx.grab_release()

    def _refresh_tree(self) -> None:
        """ツリービューをデータモデルに基づいて再描画し、選択状態と展開状態を復元する。"""
        selected_nodes = {self._node_of(iid) for iid in self.tree.selection() if self._node_of(iid)}
        self.tree.delete(*self.tree.get_children())
        self._iid_to_node.clear()
        self.row_counter = 0

        def add_items(parent_iid: str, node: Node) -> None:
            for ch in node.children:
                tag = 'oddrow' if self.row_counter % 2 == 0 else 'evenrow'
                self.row_counter += 1
                tags_to_add = [tag]
                if ch.type == "folder": tags_to_add.append('folder')
                icon = "📁 " if ch.type == "folder" else ""
                text = icon + (ch.title or "")
                url_display = ch.url
                if not ch.url and ch.type == 'bookmark':
                    url_display = '(None)'
                    tags_to_add.append('nourl')
                iid = self.tree.insert(parent_iid, "end", text=text, values=(url_display,), tags=tuple(tags_to_add))
                self._iid_to_node[iid] = ch
                if ch.type == "folder": add_items(iid, ch)

        add_items("", self.root_node)
        new_iids_to_select = []
        for iid, node in self._iid_to_node.items():
            if node in self.open_nodes: self.tree.item(iid, open=True)
            if node in selected_nodes: new_iids_to_select.append(iid)
        if new_iids_to_select:
            self.tree.selection_set(new_iids_to_select)
            self.tree.see(new_iids_to_select[-1])
        self._build_search_index()

    def _build_search_index(self):
        """検索インデックスを単語ベースの辞書形式で構築"""
        self.search_index = {}
        for iid, node in self._iid_to_node.items():
            full_text = f"{(node.title or '').lower()} {(node.url or '').lower()}"
            words = set(re.split(r'\W+', full_text))
            for word in words:
                if not word: continue
                if word not in self.search_index:
                    self.search_index[word] = set()
                self.search_index[word].add(iid)

    def _node_of(self, iid: str):
        return self._iid_to_node.get(iid)

    def _iid_of_node(self, target: Node) -> str:
        for iid, n in self._iid_to_node.items():
            if n is target: return iid
        return ""

    def _find_parent_iid(self, iid: str) -> str:
        return self.tree.parent(iid)

    def _selected_folder_and_node(self):
        sel = self.tree.selection()
        if sel:
            iid = sel[0]
            node = self._node_of(iid)
            if node and node.type == "folder": return iid, node
            pid = self._find_parent_iid(iid)
            pnode = self._node_of(pid) if pid else self.root_node
            return pid, pnode
        return "", self.root_node

    def _update_preview_pane(self, preview_data):
        self.preview_title.set(preview_data.get("title", ""))
        self.preview_desc.set(preview_data.get("description", ""))

    def _update_info_from_selection(self, event=None) -> None:
        sels = self.tree.selection()
        if not sels or len(sels) > 1:
            self.info_title.set(f"{len(sels)} items selected" if sels else "—")
            self.info_url.set("")
            self._update_preview_pane({})
            return
        iid = sels[0]
        node = self._node_of(iid)
        if node:
            self.info_title.set(f"{node.title or '(Untitled)'}  [{node.type}]")
            self.info_url.set(node.url or "")
            if node.type == "bookmark" and node.url:
                if node.url in self.preview_cache:
                    self._update_preview_pane(self.preview_cache[node.url])
                else:
                    self.preview_title.set("Loading preview...")
                    self.preview_desc.set("")
                    threading.Thread(target=self._fetch_preview_worker, args=(node.url,), daemon=True).start()

    def cmd_open(self) -> None:
        path = filedialog.askopenfilename(
            title="Open Chrome Bookmarks HTML", filetypes=[("HTML files", "*.html;*.htm"), ("All files", "*.*")],
        )
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = f.read()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read file:\n{e}");
            return
        parser = NetscapeBookmarkParser()
        try:
            parser.feed(data)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse bookmarks HTML:\n{e}");
            return
        self.root_node = parser.root
        self.current_file = path
        sidecar = os.path.splitext(path)[0] + ".bookmark_rules.json"
        if os.path.exists(sidecar):
            try:
                with open(sidecar, "r", encoding="utf-8") as rf:
                    self.rules = json.load(rf)
                    self.rules_path = sidecar
            except Exception:
                self.rules = self._default_rules()
                self.rules_path = None
        self.open_nodes.clear()
        self._refresh_tree()
        roots = self.tree.get_children("")
        if roots:
            first_node = self._node_of(roots[0])
            if first_node:
                self.open_nodes.add(first_node)
                self.tree.item(roots[0], open=True)
        self.title(f"Bookmark Studio — {os.path.basename(path)}")

    def cmd_save(self) -> None:
        if not self.current_file:
            return self.cmd_save_as()
        try:
            html_text = export_netscape_html(self.root_node)
            with open(self.current_file, "w", encoding="utf-8") as f:
                f.write(html_text)
            if self.rules:
                sp = os.path.splitext(self.current_file)[0] + ".bookmark_rules.json"
                with open(sp, "w", encoding="utf-8") as wf:
                    json.dump(self.rules, wf, ensure_ascii=False, indent=2)
                self.rules_path = sp
            messagebox.showinfo("Saved", "Saved successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save:\n{e}")

    def cmd_save_as(self) -> None:
        if not self.root_node: return
        path = filedialog.asksaveasfilename(
            title="Export Chrome HTML", defaultextension=".html", filetypes=[("HTML files", "*.html;*.htm")],
        )
        if not path: return
        try:
            html_text = export_netscape_html(self.root_node)
            with open(path, "w", encoding="utf-8") as f:
                f.write(html_text)
            messagebox.showinfo("Exported", "Export completed.")
            sp = os.path.splitext(path)[0] + ".bookmark_rules.json"
            with open(sp, "w", encoding="utf-8") as wf:
                json.dump(self.rules, wf, ensure_ascii=False, indent=2)
            self.rules_path = sp
            self.current_file = path
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export:\n{e}")

    def cmd_new_folder(self) -> None:
        _, parent = self._selected_folder_and_node()
        if not parent: return
        name = simpledialog.askstring("New Folder", "Folder name:")
        if name is None: return
        n = Node("folder", title=name)
        parent.append(n)
        self._refresh_tree()
        new_iid = self._iid_of_node(n)
        if new_iid:
            self.tree.selection_set(new_iid)
            self.tree.see(new_iid)

    def cmd_new_bookmark(self) -> None:
        _, parent = self._selected_folder_and_node()
        if not parent: return
        title = simpledialog.askstring("New Bookmark", "Title:")
        if title is None: return
        url = simpledialog.askstring("New Bookmark", "URL:")
        if url is None: return
        if url and not is_valid_url(url):
            messagebox.showerror("Error", "無効なURL形式です。http:// または https:// で始まるURLを入力してください。")
            return
        n = Node("bookmark", title=title, url=url)
        parent.append(n)
        self._refresh_tree()
        new_iid = self._iid_of_node(n)
        if new_iid:
            self.tree.selection_set(new_iid)
            self.tree.see(new_iid)

    def _start_inline_editor(self, iid: str) -> None:
        node = self._node_of(iid)
        if not node: return
        bbox = self.tree.bbox(iid, column="#0")
        if not bbox: return
        x, y, w, h = bbox
        x_offset = 25
        x += x_offset
        w -= x_offset
        entry = ttk.Entry(self.tree)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, node.title)
        entry.select_range(0, 'end')
        entry.focus_set()

        def commit(event):
            new_title = entry.get()
            entry.destroy()
            if node.title != new_title:
                node.title = new_title
                icon = "📁 " if node.type == "folder" else ""
                text = icon + (node.title or "")
                self.tree.item(iid, text=text)
                self._build_search_index()

        def cancel(event):
            entry.destroy()

        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Escape>", cancel)

    def _on_double_click_inline_edit(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid or self.tree.identify_column(event.x) != "#0": return
        self._start_inline_editor(iid)

    def cmd_rename(self) -> None:
        sels = self.tree.selection()
        if sels: self._start_inline_editor(sels[0])

    def cmd_edit_url(self) -> None:
        sels = self.tree.selection()
        if not sels: return
        node = self._node_of(sels[0])
        if not node or node.type != "bookmark":
            messagebox.showinfo("Edit URL", "Select a bookmark to edit its URL.")
            return
        new_url = simpledialog.askstring("Edit URL", "New URL:", initialvalue=node.url or "")
        if new_url is None: return
        if new_url and not is_valid_url(new_url):
            messagebox.showerror("Error", "無効なURL形式です。http:// または https:// で始まるURLを入力してください。")
            return
        node.url = new_url
        self._refresh_tree()
        new_iid = self._iid_of_node(node)
        if new_iid: self.tree.selection_set(new_iid)

    def cmd_move_to_folder(self) -> None:
        sels = list(self.tree.selection())
        if not sels:
            messagebox.showinfo("Move to Folder", "移動するアイテムを選択してください。")
            return
        dragged_nodes = [self._node_of(i) for i in sels if self._node_of(i)]
        if not dragged_nodes: return
        folder_nodes = []

        def find_folders(node, path):
            if node in dragged_nodes: return
            if node.type == 'folder':
                folder_nodes.append((path, node))
                for child in node.children:
                    find_folders(child, path + [node.title])

        find_folders(self.root_node, [])
        dialog = tk.Toplevel(self)
        dialog.title("Move Items to Folder")
        dialog.geometry("450x400")
        dialog.transient(self)
        dialog.grab_set()
        tk.Label(dialog, text=f"Move {len(dragged_nodes)} item(s) to:").pack(pady=10)
        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        folder_listbox = tk.Listbox(list_frame)
        folder_listbox.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=folder_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        folder_listbox.config(yscrollcommand=scrollbar.set)
        folder_map = {}
        for path, node in folder_nodes:
            display_path = " / ".join(path[1:] + [node.title]) or "Bookmarks Bar"
            folder_listbox.insert("end", display_path)
            folder_map[display_path] = node
        result_node = None

        def on_ok():
            nonlocal result_node
            selected_indices = folder_listbox.curselection()
            if selected_indices:
                result_node = folder_map.get(folder_listbox.get(selected_indices[0]))
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", padx=10, pady=10)
        ok_button = ttk.Button(btn_frame, text="Move", command=on_ok)
        ok_button.pack(side="right", padx=5)
        cancel_button = ttk.Button(btn_frame, text="Cancel", command=dialog.destroy)
        cancel_button.pack(side="right")
        self.wait_window(dialog)
        if not result_node: return
        for node in dragged_nodes:
            if node.parent: node.parent.children.remove(node)
            result_node.append(node)
        self._refresh_tree()
        new_iids = [self._iid_of_node(n) for n in dragged_nodes if self._iid_of_node(n)]
        if new_iids:
            self.tree.selection_set(new_iids)
            self.tree.see(new_iids[-1])

    def cmd_move_up(self) -> None:
        """選択したアイテムを一つ上の階層に移動する。"""
        sels = list(self.tree.selection())
        if not sels:
            messagebox.showinfo("Move Up", "移動するアイテムを選択してください。")
            return
        nodes_to_move = [self._node_of(i) for i in sels if self._node_of(i)]
        if not nodes_to_move: return
        for node in nodes_to_move:
            if not node.parent or not node.parent.parent:
                messagebox.showwarning("Move Up", "トップレベルのアイテムはこれ以上上に移動できません。")
                return
        new_parent = nodes_to_move[0].parent.parent
        for node in nodes_to_move:
            if node.parent:
                node.parent.children.remove(node)
            new_parent.append(node)
        self._refresh_tree()
        new_iids = [self._iid_of_node(n) for n in nodes_to_move if self._iid_of_node(n)]
        if new_iids:
            self.tree.selection_set(new_iids)
            self.tree.see(new_iids[-1])

    def cmd_delete(self) -> None:
        sels = list(self.tree.selection())
        if not sels: return
        if not messagebox.askyesno("Delete", f"Delete {len(sels)} selected item(s)?"): return
        for iid in sels:
            node = self._node_of(iid)
            if node and node.parent:
                node.parent.children.remove(node)
        self._refresh_tree()

    def cmd_sort(self, mode: str = "title") -> None:
        _, folder = self._selected_folder_and_node()
        if not folder: return

        def sort_key(n: Node):
            if mode == "domain" and n.type == "bookmark":
                return (0, self._domain_of(n.url), (n.title or "").lower())
            return (0 if n.type == "folder" else 1, (n.title or "").lower())

        folder.children.sort(key=sort_key)
        self._refresh_tree()

    def cmd_dedupe(self) -> None:
        _, folder = self._selected_folder_and_node()
        if not folder: return
        seen, new_children, removed = set(), [], 0
        for ch in folder.children:
            if ch.type == "bookmark":
                key = (ch.url or "").strip().rstrip("/")
                if key and key in seen:
                    removed += 1;
                    continue
                if key: seen.add(key)
            new_children.append(ch)
        folder.children = new_children
        self._refresh_tree()
        messagebox.showinfo("Deduplicate", f"Removed {removed} duplicated bookmark(s).")

    def cmd_expand_all(self):
        self.open_nodes.clear()

        def collect_all_folders(node):
            if node.type == 'folder':
                self.open_nodes.add(node)
                for child in node.children:
                    collect_all_folders(child)

        collect_all_folders(self.root_node)
        self._refresh_tree()

    def cmd_collapse_all(self):
        self.open_nodes.clear()
        self._refresh_tree()

    def _on_search_var_changed(self, *args):
        if self._search_after_id: self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(200, self._apply_search)

    def _apply_search(self) -> None:
        for tag in self.tree.tag_names():
            if tag.startswith("match"):
                self.tree.tag_delete(tag)
        q = self.search_var.get().strip().lower()
        if not q: return
        matching_iids = set()
        search_words = [word for word in re.split(r'\W+', q) if word]
        for i, word in enumerate(search_words):
            found_iids = set()
            for term, iids in self.search_index.items():
                if term.startswith(word):
                    found_iids.update(iids)
            if i == 0:
                matching_iids = found_iids
            else:
                matching_iids.intersection_update(found_iids)
        if matching_iids:
            self.tree.tag_configure("match", background="#FFFACD")
            open_parents = set()
            for iid in matching_iids:
                self.tree.item(iid, tags=self.tree.item(iid, "tags") + ("match",))
                p = self.tree.parent(iid)
                while p:
                    if p in open_parents: break
                    open_parents.add(p)
                    p = self.tree.parent(p)
            for p_iid in open_parents:
                self.tree.item(p_iid, open=True)
                p_node = self._node_of(p_iid)
                if p_node: self.open_nodes.add(p_node)

    def _clear_search(self) -> None:
        self.search_var.set("")

    def _on_tree_press(self, event) -> None:
        self.drag_start_iid = self.tree.identify_row(event.y)
        if self.drag_start_iid and self.drag_start_iid not in self.tree.selection():
            if not (event.state & 0x0004) and not (event.state & 0x0001):
                self.tree.selection_set(self.drag_start_iid)

    def _on_tree_drag(self, event) -> None:
        if self.drag_start_iid:
            self.dragging_iids = list(self.tree.selection())
            if self.drag_start_iid in self.dragging_iids:
                self.config(cursor="fleur")
                self._create_drag_window()
            else:
                self.dragging_iids = None
            self.drag_start_iid = None
        if not self.dragging_iids: return
        if self.drag_window: self.drag_window.geometry(f"+{event.x_root + 15}+{event.y_root + 10}")
        self._update_drop_indicator(event.x, event.y)

    def _on_tree_release(self, event) -> None:
        self._destroy_drag_window()
        self._destroy_drop_line()
        self.config(cursor="")
        if not self.dragging_iids or not self.drop_target_info:
            self.dragging_iids = None;
            return
        target_iid = self.drop_target_info["iid"]
        drop_pos = self.drop_target_info["pos"]
        target_node = self._node_of(target_iid)
        if not target_node:
            self.dragging_iids = None;
            return
        dragged_nodes = [self._node_of(i) for i in self.dragging_iids if self._node_of(i)]
        for dn in dragged_nodes:
            if dn.type == 'folder':
                temp = target_node
                while temp:
                    if temp == dn:
                        messagebox.showwarning("Invalid Move", "Cannot move a folder into its own descendant.")
                        self.dragging_iids = None;
                        return
                    temp = temp.parent
        if target_node.type == "folder" and drop_pos == 'in':
            for dn in dragged_nodes:
                if dn.parent: dn.parent.children.remove(dn)
                target_node.append(dn)
        else:
            parent = target_node.parent or self.root_node
            try:
                insert_idx = parent.children.index(target_node)
                if drop_pos == 'after': insert_idx += 1
                for dn in reversed(dragged_nodes):
                    if dn.parent: dn.parent.children.remove(dn)
                    parent.children.insert(insert_idx, dn)
                    dn.parent = parent
            except ValueError:
                for dn in dragged_nodes:
                    if dn.parent: dn.parent.children.remove(dn)
                    parent.append(dn)
        self._refresh_tree()
        new_iids = [self._iid_of_node(n) for n in dragged_nodes if self._iid_of_node(n)]
        if new_iids: self.tree.selection_set(new_iids)
        self.dragging_iids = None
        self.drop_target_info = None

    def _create_drag_window(self):
        if self.drag_window: self.drag_window.destroy()
        self.drag_window = tk.Toplevel(self)
        self.drag_window.overrideredirect(True)
        self.drag_window.attributes('-alpha', 0.7)
        self.drag_window.attributes('-topmost', True)
        text = f"{len(self.dragging_iids)}個のアイテムを移動中"
        if len(self.dragging_iids) == 1:
            node = self._node_of(self.dragging_iids[0])
            text = node.title or "(Untitled)"
        label = ttk.Label(self.drag_window, text=text, padding=5, background="#DDDDDD", relief="solid", borderwidth=1)
        label.pack()

    def _destroy_drag_window(self):
        if self.drag_window:
            self.drag_window.destroy()
            self.drag_window = None

    def _update_drop_indicator(self, x, y):
        self._destroy_drop_line()
        self.drop_target_info = None
        for iid in self._iid_to_node:
            tags = list(self.tree.item(iid, "tags"))
            if "drop_folder" in tags:
                tags.remove("drop_folder")
                self.tree.item(iid, tags=tuple(tags))
        iid = self.tree.identify_row(y)
        if not iid or iid in self.dragging_iids: return
        bbox = self.tree.bbox(iid)
        if not bbox: return
        line_x, line_y, line_w, line_h = bbox
        target_node = self._node_of(iid)
        if target_node.type == 'folder':
            self.drop_target_info = {"iid": iid, "pos": "in"}
            self.tree.item(iid, tags=self.tree.item(iid, "tags") + ('drop_folder',))
        else:
            drop_pos = 'after' if y > (line_y + line_h / 2) else 'before'
            self.drop_target_info = {"iid": iid, "pos": drop_pos}
            line_y_pos = line_y if drop_pos == 'before' else line_y + line_h
            self.drop_line = ttk.Frame(self.tree, height=2, style="Line.TFrame")
            self.drop_line.place(x=line_x, y=line_y_pos, width=self.tree.winfo_width())

    def _destroy_drop_line(self):
        if self.drop_line:
            self.drop_line.destroy()
            self.drop_line = None
        for iid in self._iid_to_node:
            tags = list(self.tree.item(iid, "tags"))
            if "drop_folder" in tags:
                tags.remove("drop_folder")
                self.tree.item(iid, tags=tuple(tags))

    def _on_folder_open(self, event=None):
        iid = self.tree.focus()
        if iid:
            node = self._node_of(iid)
            if node and node.type == 'folder':
                self.open_nodes.add(node)

    def _on_folder_close(self, event=None):
        iid = self.tree.focus()
        if iid:
            node = self._node_of(iid)
            if node and node.type == 'folder':
                if node in self.open_nodes:
                    self.open_nodes.remove(node)

    def _default_rules(self):
        return {
            "Google": {"domains": ["google.com", "gmail.com", "drive.google.com"],
                       "keywords": ["google", "gmail", "drive"]},
            "YouTube": {"domains": ["youtube.com", "youtu.be"], "keywords": ["youtube", "yt"]},
            "News": {"domains": ["cnn.com", "bbc.co.uk", "nytimes.com", "news.yahoo"], "keywords": ["news", "article"]},
            "Social": {"domains": ["twitter.com", "x.com", "facebook.com", "instagram.com", "linkedin.com"],
                       "keywords": ["twitter", "facebook", "instagram", "linkedin"]},
            "Dev": {"domains": ["github.com", "gitlab.com", "stackoverflow.com", "pypi.org", "readthedocs"],
                    "keywords": ["github", "docs", "api", "stack overflow"]},
            "Shopping": {"domains": ["amazon.", "rakuten.", "taobao.", "jd.com"], "keywords": ["cart", "buy", "store"]},
        }

    def _match_rule(self, url: str, title: str, rule: dict) -> bool:
        u = (url or "").lower()
        t = (title or "").lower()
        for d in rule.get("domains", []):
            if d in u: return True
        for k in rule.get("keywords", []):
            if k in u or k in t: return True
        return False

    def _get_classification_plan(self, bookmarks_to_check: list[Node]) -> dict[str, list[Node]]:
        plan = {}
        for bm in bookmarks_to_check:
            if bm.type != 'bookmark': continue
            for folder_name, rule in self.rules.items():
                if self._match_rule(bm.url, bm.title, rule):
                    current_parent = bm.parent
                    if current_parent and current_parent.title == folder_name:
                        continue
                    if folder_name not in plan: plan[folder_name] = []
                    plan[folder_name].append(bm)
                    break
        return plan

    def _find_common_parent(self, nodes):
        """Finds the deepest common parent folder for a list of nodes."""
        if not nodes:
            return self.root_node
        paths = []
        for node in nodes:
            path = []
            curr = node.parent
            while curr:
                path.insert(0, curr)
                curr = curr.parent
            paths.append(path)
        if not paths:
            return self.root_node
        shortest_path = min(paths, key=len)
        common_parent = self.root_node
        for i, parent in enumerate(shortest_path):
            if all(i < len(p) and p[i] is parent for p in paths):
                common_parent = parent
            else:
                break
        return common_parent

    def _execute_classification_plan(self, plan: dict[str, list[Node]], base_node: Node):
        """Executes the classification plan within a specified base node."""
        if not plan: return
        target_folders_parent = base_node if base_node else self.root_node

        # ★★★ 修正点: 大文字小文字を区別しないフォルダ検索 ★★★
        existing_folders_map = {
            ch.title.lower(): ch for ch in target_folders_parent.children if ch.type == "folder"
        }

        for folder_name, bookmarks in plan.items():
            # 既存のフォルダを大文字小文字を区別せずに探す
            target_folder = existing_folders_map.get(folder_name.lower())

            if not target_folder:
                target_folder = Node("folder", folder_name)
                target_folders_parent.append(target_folder)
                existing_folders_map[folder_name.lower()] = target_folder

            for bm in bookmarks:
                if bm.parent and bm in bm.parent.children:
                    bm.parent.children.remove(bm)
                target_folder.append(bm)

        self._refresh_tree()
        messagebox.showinfo("Auto Classify", f"Moved {sum(len(v) for v in plan.values())} bookmarks.")

    def cmd_show_classify_preview(self) -> None:
        selection_iids = self.tree.selection()
        bookmarks_to_classify = []
        if not selection_iids:
            if not messagebox.askyesno("Auto Classify", "No items selected. Classify ALL bookmarks?"): return

            def collect_all(node):
                for child in node.children:
                    if child.type == 'bookmark':
                        bookmarks_to_classify.append(child)
                    elif child.type == 'folder':
                        collect_all(child)

            collect_all(self.root_node)
        else:
            for iid in selection_iids:
                node = self._node_of(iid)
                if not node: continue
                if node.type == 'bookmark':
                    bookmarks_to_classify.append(node)
                elif node.type == 'folder':
                    def collect_from_folder(folder_node):
                        for child in folder_node.children:
                            if child.type == 'bookmark':
                                bookmarks_to_classify.append(child)
                            elif child.type == 'folder':
                                collect_from_folder(child)

                    collect_from_folder(node)
        plan = self._get_classification_plan(list(set(bookmarks_to_classify)))
        if not plan:
            messagebox.showinfo("Auto Classify", "No bookmarks to move based on current rules.")
            return
        base_node = self._find_common_parent(bookmarks_to_classify)
        dialog = tk.Toplevel(self)
        dialog.title("Classification Preview")
        dialog.geometry("600x400")
        preview_tree = ttk.Treeview(dialog, columns=("original_location"), show="tree headings")
        preview_tree.heading("#0", text="Bookmark to Move")
        preview_tree.heading("original_location", text="Original Location")
        preview_tree.column("original_location", width=200)
        preview_tree.pack(fill="both", expand=True, padx=10, pady=10)
        for folder_name, bookmarks in sorted(plan.items()):
            folder_iid = preview_tree.insert("", "end", text=f"📁 Create in '{base_node.title}': {folder_name}",
                                             open=True)
            for bm in bookmarks:
                parent_path = []
                curr = bm.parent
                while curr and curr != self.root_node:
                    parent_path.insert(0, curr.title or "(Untitled)")
                    curr = curr.parent
                preview_tree.insert(folder_iid, "end", text=f"🔗 {bm.title}", values=("/".join(parent_path),))
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", padx=10, pady=5)

        def on_apply():
            dialog.destroy()
            self._execute_classification_plan(plan, base_node)

        ttk.Button(btn_frame, text="Apply", command=on_apply).pack(side="right")
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="right", padx=5)

    def cmd_edit_rules(self) -> None:
        tl = tk.Toplevel(self)
        tl.title("Edit Classify Rules (JSON)")
        tl.geometry("720x520")
        text = tk.Text(tl, wrap="none")
        text.pack(fill="both", expand=True, padx=5, pady=5)
        try:
            pretty = json.dumps(self.rules, ensure_ascii=False, indent=2)
        except Exception:
            pretty = "{}"
        text.insert("1.0", pretty)
        btns = ttk.Frame(tl)
        btns.pack(fill="x", padx=5, pady=5)

        def save_rules() -> None:
            try:
                data = json.loads(text.get("1.0", "end-1c"))
                self.rules = data
                if self.rules_path:
                    with open(self.rules_path, "w", encoding="utf-8") as wf:
                        json.dump(self.rules, wf, ensure_ascii=False, indent=2)
                messagebox.showinfo("Rules", "Saved.", parent=tl)
                tl.destroy()
            except Exception as e:
                messagebox.showerror("Rules", f"Invalid JSON:\n{e}", parent=tl)

        ttk.Button(btns, text="Save", command=save_rules).pack(side="right")
        ttk.Button(btns, text="Cancel", command=tl.destroy).pack(side="right", padx=6)

    def cmd_smart_classify(self):
        """AI分類の初回実行を行う。"""
        self.progress_history = []
        self._smart_cancelled = False
        self.last_classification_prompts = []
        selection_iids = self.tree.selection()
        bookmarks_to_process = []

        def collect(node):
            if not node: return
            if node.type == 'bookmark' and node.url:
                bookmarks_to_process.append(node)
            elif node.type == 'folder':
                for ch in node.children: collect(ch)

        if not selection_iids:
            collect(self.root_node)
        else:
            for iid in selection_iids:
                collect(self._node_of(iid))
        bookmarks_to_process = list({id(b): b for b in bookmarks_to_process}.values())
        self.last_classified_bookmarks = bookmarks_to_process
        if not bookmarks_to_process:
            messagebox.showinfo("Smart Classify", "対象ブックマークがありません。");
            return
        total_to_process = min(len(bookmarks_to_process), self.max_smart_items)
        self._show_smart_progress(total_to_process)
        threading.Thread(target=self._run_ai_classification_worker, args=(bookmarks_to_process, None),
                         daemon=True).start()

    def _run_ai_classification_worker(self, bookmarks, additional_prompt):
        """AI分類器を別スレッドで実行する。"""
        try:
            bookmark_nodes = [BookmarkNode(title=b.title, url=b.url) for b in bookmarks]
            classifier = AIBookmarkClassifier(logger=self.logger)

            def progress_callback(processed, total, sent, received):
                if not self._smart_cancelled:
                    self.ui_queue.put(('progress_update', (processed, total, sent, received)))

            classifier.set_progress_callback(progress_callback)
            priority_terms = self.config_manager.get_priority_terms()
            result = classifier.classify_bookmarks(
                bookmarks=bookmark_nodes, priority_terms=priority_terms, max_items=self.max_smart_items,
                additional_prompt=additional_prompt
            )
            if not self._smart_cancelled:
                self.ui_queue.put(('smart_classify_result', result))
        except Exception as e:
            self.logger.error("AI Classification worker failed: %s", str(e), exc_info=True)
            if not self._smart_cancelled:
                self.ui_queue.put(('error', f"Smart Classify failed: {e}"))

    def _show_smart_progress(self, total):
        """スマート分類の進捗ダイアログを表示（不確定モード版）。"""
        if self._smart_dialog and self._smart_dialog.winfo_exists(): return
        d = tk.Toplevel(self)
        d.title("Smart Classify")
        d.geometry("400x150")
        d.transient(self)
        d.grab_set()
        d.resizable(False, False)
        self._smart_dialog = d
        ttk.Label(d, text=f"AIが最大{total}件のブックマークを解析中です...").pack(pady=12)
        pb = ttk.Progressbar(d, mode="indeterminate")
        pb.pack(fill="x", padx=14, pady=5)
        pb.start(10)
        self.progress_var = None
        self.progress_label = None
        self.traffic_label = ttk.Label(d, text="AIと通信中...")
        self.traffic_label.pack(pady=8)

        def on_hide():
            self._smart_cancelled = True
            self.traffic_label = None
            if self._smart_dialog:
                try:
                    self._smart_dialog.destroy()
                except tk.TclError:
                    pass
            self._smart_dialog = None

        ttk.Button(d, text="Cancel", command=on_hide).pack(pady=10)
        d.protocol("WM_DELETE_WINDOW", on_hide)

    def cmd_check_proxy(self) -> None:
        proxy_info = self._get_proxies_for_requests()
        if not proxy_info:
            if not self.use_proxy_var.get():
                messagebox.showinfo("Proxy Check", "プロキシは使用しない設定です。")
            else:
                messagebox.showinfo("Proxy Check", "プロキシ設定がconfig.iniに見つかりません。")
            return
        dialog = tk.Toplevel(self)
        dialog.title("Proxy Test")
        dialog.geometry("300x100")
        dialog.transient(self)
        dialog.grab_set()
        label = ttk.Label(dialog, text="Testing proxy connection...")
        label.pack(pady=20)
        self.update_idletasks()

        def worker():
            try:
                test_url = "http://www.google.com/generate_204"
                response = requests.get(test_url, proxies=proxy_info['proxies'], auth=proxy_info['auth'], timeout=10)
                response.raise_for_status()
                self.ui_queue.put(('proxy_check_success', dialog))
            except Exception as e:
                self.ui_queue.put(('proxy_check_failure', (dialog, str(e))))

        threading.Thread(target=worker, daemon=True).start()

    def cmd_set_smart_classify_limit(self) -> None:
        current_limit = self.max_smart_items
        new_limit = simpledialog.askinteger(
            "Smart Classify Limit", "スマート分類の最大ブックマーク数を入力してください（50～1000）：",
            initialvalue=current_limit, minvalue=50, maxvalue=1000, parent=self
        )
        if new_limit is not None: self.max_smart_items = new_limit
        messagebox.showinfo("Smart Classify Limit", f"最大処理数を {new_limit} に設定しました。")

    def cmd_set_title_fetch_timeout(self) -> None:
        new_timeout = simpledialog.askinteger(
            "Title Fetch Timeout", "タイトル取得のタイムアウト秒数を入力してください（2～60）：",
            initialvalue=self.fetch_timeout, minvalue=2, maxvalue=60, parent=self
        )
        if new_timeout is not None:
            self.fetch_timeout = new_timeout
            messagebox.showinfo("Title Fetch Timeout", f"タイムアウトを {new_timeout} 秒に設定しました。")

    def cmd_show_progress_chart(self):
        if not self.progress_history:
            messagebox.showinfo("Progress Chart", "進捗データがありません。スマート分類を先に行ってください。");
            return
        dialog = tk.Toplevel(self)
        dialog.title("Smart Classification Progress")
        dialog.geometry("500x350")
        canvas = tk.Canvas(dialog, bg="white")
        canvas.pack(fill="both", expand=True, padx=10, pady=10)
        history = self.progress_history
        max_val = max(history) if history else 1
        canvas_width, canvas_height, padding = 480, 330, 20
        chart_area_height = canvas_height - (padding * 2)
        chart_area_width = canvas_width - (padding * 2)
        bar_count = len(history)
        bar_width = chart_area_width / (bar_count + 1) if bar_count > 0 else chart_area_width
        canvas.create_line(padding, padding, padding, canvas_height - padding)
        canvas.create_line(padding, canvas_height - padding, canvas_width - padding, canvas_height - padding)
        for i, val in enumerate(history):
            x0 = padding + (i * bar_width) + (bar_width * 0.1)
            y0 = canvas_height - padding - ((val / max_val) * chart_area_height)
            x1 = x0 + bar_width * 0.8
            y1 = canvas_height - padding
            canvas.create_rectangle(x0, y0, x1, y1, fill="#4CAF50", outline="#388E3C")
            if i % (len(history) // 10 or 1) == 0:
                canvas.create_text(x0 + (bar_width * 0.4), y1 + 10, text=str(val), anchor="n")
        canvas.create_text(canvas_width / 2, padding / 2, text="Processed Bookmarks Over Time", font=("", 12, "bold"))
        canvas.create_text(padding - 10, canvas_height / 2, text=f"Total: {max_val}", angle=90, anchor="s")

    def _domain_of(self, url: str) -> str:
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return ""

    def _show_smart_classify_preview(self, plan: dict, base_node: Node) -> None:
        """AI分類の結果プレビューダイアログを表示する。"""
        if not plan:
            if self.last_classification_prompts:
                messagebox.showinfo("Smart Classify", "現在の指示では、これ以上分類できる候補が見つかりませんでした。")
            else:
                messagebox.showinfo("Smart Classify", "AIによる分類候補が見つかりませんでした。")
            return
        dialog = tk.Toplevel(self)
        dialog.title("Smart Classification Preview (AI)")
        dialog.geometry("700x500")
        dialog.transient(self)
        dialog.grab_set()
        preview_tree = ttk.Treeview(dialog, columns=("original_location"), show="tree headings")
        preview_tree.heading("#0", text="Bookmark to Move")
        preview_tree.heading("original_location", text="Original Location")
        preview_tree.column("#0", width=400)
        preview_tree.column("original_location", width=200)
        preview_tree.pack(fill="both", expand=True, padx=10, pady=10)
        for folder_name, bookmarks in sorted(plan.items()):
            folder_iid = preview_tree.insert("", "end", text=f"📁 Create in '{base_node.title}': {folder_name}",
                                             open=True)
            for bm in bookmarks:
                parent_path = []
                curr = bm.parent
                while curr and curr != self.root_node:
                    parent_path.insert(0, curr.title or "(Untitled)")
                    curr = curr.parent
                preview_tree.insert(folder_iid, "end", text=f"🔗 {bm.title}", values=("/".join(parent_path),))
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", padx=10, pady=5)

        def on_apply():
            dialog.destroy()
            self._execute_classification_plan(plan, base_node)

        def on_reclassify():
            """再分類ボタンが押されたときの処理"""
            dialog.destroy()
            prompt_dialog = CustomPromptDialog(self, title="AIへの追加指示",
                                               previous_prompts=self.last_classification_prompts)
            new_prompt = prompt_dialog.result
            if new_prompt:
                self.last_classification_prompts.append(new_prompt)
                bookmarks_to_reclassify = self.last_classified_bookmarks
                if not bookmarks_to_reclassify:
                    messagebox.showerror("Error", "再分類対象のブックマークリストが見つかりませんでした。");
                    return
                full_prompt = "\n- ".join(self.last_classification_prompts)
                total_to_process = min(len(bookmarks_to_reclassify), self.max_smart_items)
                self._show_smart_progress(total_to_process)
                threading.Thread(
                    target=self._run_ai_classification_worker,
                    args=(bookmarks_to_reclassify, full_prompt), daemon=True
                ).start()

        ttk.Button(btn_frame, text="Apply", command=on_apply).pack(side="right")
        ttk.Button(btn_frame, text="再分類...", command=on_reclassify).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="right", padx=5)

    def cmd_fix_titles_from_url(self) -> None:
        """選択中のブックマークのタイトルをウェブサイトから取得して修正する。"""
        sels = list(self.tree.selection())
        if not sels:
            messagebox.showinfo("Fix Titles", "対象のブックマークを選択してください。フォルダ選択もOKです。")
            return
        targets = []

        def collect(node):
            if not node: return
            if node.type == "bookmark" and node.url:
                t = (node.title or "").strip()
                if t == node.url.strip() or is_valid_url(t):
                    targets.append(node)
            elif node.type == "folder":
                for ch in node.children: collect(ch)

        for iid in sels:
            collect(self._node_of(iid))
        targets = list({id(n): n for n in targets}.values())
        if not targets:
            messagebox.showinfo("Fix Titles", "選択範囲に修正対象（タイトルがURLのブックマーク）はありません。")
            return
        self._show_titlefix_progress(len(targets))
        threading.Thread(target=self._fix_titles_worker, args=(targets,), daemon=True).start()

    def _show_titlefix_progress(self, total: int):
        """タイトル修正の進捗ダイアログ"""
        if self._titlefix_dialog and self._titlefix_dialog.winfo_exists(): return
        d = tk.Toplevel(self)
        d.title("Fix Titles from URL")
        d.geometry("360x140")
        d.transient(self)
        d.grab_set()
        d.resizable(False, False)
        self._titlefix_dialog = d
        self._titlefix_cancelled = False
        ttk.Label(d, text=f"合計 {total} 件のタイトルを修正中...").pack(pady=10)
        self._titlefix_var = tk.DoubleVar(value=0)
        pb = ttk.Progressbar(d, variable=self._titlefix_var, maximum=total, mode="determinate")
        pb.pack(fill="x", padx=12, pady=6)
        self._titlefix_label = ttk.Label(d, text=f"0 / {total}")
        self._titlefix_label.pack()

        def on_cancel():
            self._titlefix_cancelled = True
            try:
                d.destroy()
            except tk.TclError:
                pass

        ttk.Button(d, text="Cancel", command=on_cancel).pack(pady=10)
        d.protocol("WM_DELETE_WINDOW", on_cancel)

    def _fix_titles_worker(self, nodes):
        """別スレッド：各URLにアクセスし、タイトルを上書き。"""
        processed = 0
        total = len(nodes)
        for n in nodes:
            if getattr(self, "_titlefix_cancelled", False): break
            new_title = None
            try:
                proxy_info = self._get_proxies_for_requests()
                proxies = proxy_info['proxies'] if proxy_info else None
                auth = proxy_info['auth'] if proxy_info else None

                resp = requests.get(n.url, headers={'User-Agent': 'Mozilla/5.0'}, proxies=proxies, auth=auth,
                                    timeout=self.fetch_timeout)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                title_tag = soup.find("meta", property="og:title") or soup.find("title")
                if title_tag and title_tag.name == "meta":
                    new_title = title_tag.get("content")
                elif title_tag:
                    new_title = title_tag.text
                if new_title: new_title = new_title.strip()
                if not new_title: new_title = "ERROR: No Title Found"
            except Exception as e:
                try:
                    self.logger.warning("Title fix failed for %s: %s", n.url, str(e))
                except Exception:
                    pass
                new_title = f"ERROR: {type(e).__name__}"
            n.title = new_title
            processed += 1
            self.ui_queue.put(('titlefix_progress', (processed, total)))
        self.ui_queue.put(('titlefix_done', None))

    # ★★★ 新機能 ★★★
    def cmd_merge_folders(self) -> None:
        """選択されたフォルダ内の重複する名前のフォルダを統合する。"""
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Merge Folders", "フォルダを選択してください。")
            return

        iid = sel[0]
        node = self._node_of(iid)

        # 選択されたアイテムがフォルダでない場合、その親フォルダを対象とする
        target_folder = node if node.type == 'folder' else node.parent

        if not target_folder:
            messagebox.showerror("Error", "対象フォルダが見つかりません。")
            return

        folders_by_name = {}
        nodes_to_remove = []
        merged_count = 0

        # フォルダ内の子要素をループ
        for child in list(target_folder.children):  # イテレート中にリストを変更するためコピー
            if child.type == 'folder':
                # 大文字小文字を区別しないキー
                key = child.title.lower()
                if key in folders_by_name:
                    # 重複が見つかった場合
                    primary_folder = folders_by_name[key]
                    self.logger.info(f"Merging '{child.title}' into '{primary_folder.title}'")

                    # 重複フォルダの中身をすべてプライマリフォルダに移動
                    for sub_child in list(child.children):
                        child.children.remove(sub_child)
                        primary_folder.append(sub_child)

                    nodes_to_remove.append(child)
                    merged_count += 1
                else:
                    # 初めて見るフォルダ名
                    folders_by_name[key] = child

        # 空になった重複フォルダを削除
        if nodes_to_remove:
            for node_to_remove in nodes_to_remove:
                target_folder.children.remove(node_to_remove)
            self._refresh_tree()
            messagebox.showinfo("Merge Folders", f"{merged_count}個の重複フォルダを統合しました。")
        else:
            messagebox.showinfo("Merge Folders", "重複する名前のフォルダは見つかりませんでした。")


if __name__ == "__main__":
    app = App()
    app.mainloop()
