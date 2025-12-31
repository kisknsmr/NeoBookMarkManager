import os
import sys
import io
import json
import html
import time
import re
import threading
import queue
import configparser
import base64
from typing import Optional
from urllib.parse import urlparse, quote_plus, urlunparse
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
import ttkbootstrap as tb
from ttkbootstrap.constants import *
import tkinter.font as tkfont

# Optional external libs — import defensively so module can be imported
try:
    from PIL import Image, ImageTk
except Exception:
    Image = ImageTk = None

try:
    import requests
except Exception:
    requests = None

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

import logging
from logging.handlers import RotatingFileHandler

try:
    from services.ai_classifier import AIBookmarkClassifier, BookmarkNode
except Exception:
    AIBookmarkClassifier = None
    class BookmarkNode:
        def __init__(self, title=None, url=None):
            self.title = title
            self.url = url

from core.utils import is_valid_url, LRUCache, AppConstants
from core.storage import ConfigManager, load_bookmarks, save_bookmarks
from core.model import Node
from gui.dialogs import CustomPromptDialog
from services.workers import fetch_preview, fix_titles, fetch_favicon

class App(tb.Window):
    def __init__(self):
        super().__init__(themename="cosmo")  # モダンで洗練されたライトテーマ
        self.title("Bookmark Studio — Chrome Bookmarks Organizer")
        self.geometry("1400x800")
        self.minsize(1000, 600)
        
        # Ensure 'ttk' is available as 'tb' aliases or we use tb directly
        # For compatibility with existing code that uses ttk.<Widget>, we can alias it or update code.
        # Ideally, we update code to use tb.<Widget> for better styling, or ensure ttk is referencing ttkbootstrap's styling.
        # ttkbootstrap automatically themes standard ttk widgets, so 'from tkinter import ttk' is fine IF we import ttkbootstrap.
        # BUT, to get the specific bootstrap styles (primary, success, etc.), we should use tb widgets or bootstyle.

        self.logger = logging.getLogger(__name__)
        self._setup_logging()

        self.config_manager = ConfigManager()

        self.root_node = Node("folder", "Bookmarks")
        self.current_file = None
        self.rules = self._default_rules()
        self.rules_path = None
        self._iid_to_node = {}
        self.preview_cache = LRUCache(maxsize=AppConstants.PREVIEW_CACHE_SIZE)
        self._preview_fetching = set()  # リクエスト中のURLを追跡（重複防止）
        self.ui_queue = queue.Queue()
        self._search_after_id = None
        self.open_nodes = set()
        self.search_index = {}
        self.dragging_iids = None
        self.drag_start_iid = None
        self.drag_start_pos = None  # ドラッグ開始位置 (x, y)
        self.drag_window = None
        self.drop_line = None
        self.drop_target_info = None
        self._drag_threshold = 5  # ドラッグ開始の閾値（ピクセル）
        self._img_cache = LRUCache(maxsize=AppConstants.IMAGE_CACHE_SIZE)
        self._favicon_cache = {}  # iid -> PhotoImage のマッピング
        self._favicon_fetching = set()  # 取得中のURLを追跡
        self.max_smart_items = AppConstants.DEFAULT_MAX_SMART_ITEMS
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
        self.fetch_timeout = AppConstants.DEFAULT_FETCH_TIMEOUT

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

    # 以下、bookmark_editor.py から App の残りのメソッドをそのまま移植しました
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
        editm.add_separator()
        editm.add_command(label="Expand All", command=self.cmd_expand_all, accelerator="Ctrl+Plus")
        editm.add_command(label="Collapse All", command=self.cmd_collapse_all, accelerator="Ctrl+Minus")
        menubar.add_cascade(label="Edit", menu=editm)

        toolsm = tk.Menu(menubar, tearoff=0)
        toolsm.add_checkbutton(label="プロキシを使用する", variable=self.use_proxy_var, onvalue=True, offvalue=False)
        toolsm.add_command(label="プロキシ接続をテスト", command=self.cmd_check_proxy)
        toolsm.add_separator()
        toolsm.add_command(label="Sort by Title (A→Z)", command=lambda: self.cmd_sort("title"))
        toolsm.add_command(label="Sort by Domain (A→Z)", command=lambda: self.cmd_sort("domain"))
        toolsm.add_command(label="Deduplicate in Folder", command=self.cmd_dedupe)
        toolsm.add_command(label="Merge Duplicate Folders", command=self.cmd_merge_folders)
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

        # ========== トップツールバー（洗練されたライトデザイン） ==========
        toolbar_container = tb.Frame(self, bootstyle="light")
        toolbar_container.pack(fill="x", padx=0, pady=0)
        
        # ツールバー内側のフレーム（パディング付き、背景色付き）
        toolbar = tb.Frame(toolbar_container, bootstyle="light")
        toolbar.pack(fill="x", padx=12, pady=10)
        
        # 左側：検索バー
        search_frame = tb.Frame(toolbar, bootstyle="light")
        search_frame.pack(side="left", fill="y", padx=(0, 20))
        
        search_label = tb.Label(search_frame, text="🔍 Search:", 
                               font=("", 11, "bold"), bootstyle="primary")
        search_label.pack(side="left", padx=(0, 10))
        
        self.search_var = tk.StringVar()
        self.search_var.trace("w", self._on_search_var_changed)
        self.search_entry = tb.Entry(search_frame, textvariable=self.search_var, 
                                    width=50, bootstyle="primary")
        self.search_entry.pack(side="left", padx=(0, 8))
        
        clear_btn = tb.Button(search_frame, text="Clear", command=self._clear_search, 
                            bootstyle="secondary-outline", width=10)
        clear_btn.pack(side="left", padx=3)

        # セパレーター（視覚的な区切り）
        tb.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=20, pady=5)
        
        # 中央：ツールボタン
        tools_frame = tb.Frame(toolbar, bootstyle="light")
        tools_frame.pack(side="left", fill="y")
        
        expand_btn = tb.Button(tools_frame, text="📂 Expand All", command=self.cmd_expand_all,
                               bootstyle="info-outline", width=16)
        expand_btn.pack(side="left", padx=4)
        
        collapse_btn = tb.Button(tools_frame, text="📁 Collapse All", command=self.cmd_collapse_all,
                                bootstyle="info-outline", width=16)
        collapse_btn.pack(side="left", padx=4)
        
        # セパレーター
        tb.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=20, pady=5)
        
        # 右側：統計情報
        stats_frame = tb.Frame(toolbar, bootstyle="light")
        stats_frame.pack(side="right")
        
        self.stats_label = tb.Label(stats_frame, text="📊 0 bookmarks", 
                                   font=("", 10), bootstyle="primary")
        self.stats_label.pack(side="right", padx=5)
        
        # ツールバーの下に罫線（視覚的な区切り）
        toolbar_separator = tb.Separator(self, orient="horizontal")
        toolbar_separator.pack(fill="x", padx=0, pady=0)

        # ========== メインエリア（洗練されたレイアウト） ==========
        main_container = tb.Frame(self, bootstyle="light")
        main_container.pack(fill="both", expand=True, padx=0, pady=0)
        
        main = tb.Panedwindow(main_container, orient="horizontal", bootstyle="light")
        main.pack(fill="both", expand=True, padx=15, pady=15)

        # ========== 左パネル（ツリービュー） ==========
        left_container = tb.Frame(main, bootstyle="light")
        main.add(left_container, weight=3)
        
        # パネルヘッダー（洗練されたデザイン）
        left_header = tb.Frame(left_container, bootstyle="primary")
        left_header.pack(fill="x", padx=0, pady=(0, 3))
        
        left_title = tb.Label(left_header, text="📚 Bookmarks", 
                             font=("", 12, "bold"), bootstyle="inverse-primary")
        left_title.pack(side="left", padx=15, pady=10)
        
        # ヘッダーの下に罫線
        header_sep = tb.Separator(left_container, orient="horizontal")
        header_sep.pack(fill="x", padx=0, pady=0)
        
        # ツリービューフレーム（適切な余白）
        left = tb.Frame(left_container, bootstyle="light")
        left.pack(fill="both", expand=True, padx=3, pady=3)

        cols = ("url",)
        self.tree = tb.Treeview(left, columns=cols, show="tree headings", 
                               selectmode="extended", bootstyle="primary")
        self.tree.heading("#0", text="📑 Title")
        self.tree.heading("url", text="🔗 URL")
        self.tree.column("#0", width=600, anchor="w", minwidth=200)
        self.tree.column("url", width=500, anchor="w", minwidth=150)

        ysb = tb.Scrollbar(left, orient="vertical", command=self.tree.yview, bootstyle="primary-round")
        xsb = tb.Scrollbar(left, orient="horizontal", command=self.tree.xview, bootstyle="primary-round")
        self.tree.configure(yscroll=ysb.set, xscroll=xsb.set)
        
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        # ========== 右パネル（情報とアクション） ==========
        right_container = tb.Frame(main, bootstyle="light")
        main.add(right_container, weight=1)
        
        # スクロール可能な右パネル（Canvas + Scrollbar）
        right_canvas = tk.Canvas(right_container, highlightthickness=0, bg="#FFFFFF")
        right_scrollbar = tb.Scrollbar(right_container, orient="vertical", command=right_canvas.yview, bootstyle="primary-round")
        right_scrollable_frame = tb.Frame(right_canvas, bootstyle="light")
        
        right_scrollable_frame.bind(
            "<Configure>",
            lambda e: right_canvas.configure(scrollregion=right_canvas.bbox("all"))
        )
        
        right_canvas.create_window((0, 0), window=right_scrollable_frame, anchor="nw")
        right_canvas.configure(yscrollcommand=right_scrollbar.set)
        
        right_canvas.pack(side="left", fill="both", expand=True)
        right_scrollbar.pack(side="right", fill="y")
        
        # マウスホイールでスクロール
        def _on_mousewheel(event):
            right_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        right_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        right = right_scrollable_frame
        
        self.info_title = tk.StringVar(value="—")
        self.info_url = tk.StringVar(value="—")
        self.preview_title = tk.StringVar(value="")
        self.preview_desc = tk.StringVar(value="")
        self.right_canvas = right_canvas  # 後でwraplength計算に使用

        # ========== 選択アイテム情報セクション ==========
        info_header = tb.Frame(right, bootstyle="info")
        info_header.pack(fill="x", pady=(0, 3))
        
        info_title_label = tb.Label(info_header, text="ℹ️ Selected Item", 
                                   font=("", 11, "bold"), bootstyle="inverse-info")
        info_title_label.pack(side="left", padx=12, pady=8)
        
        info_sep = tb.Separator(right, orient="horizontal")
        info_sep.pack(fill="x", pady=(0, 10))
        
        lbl_frame = tb.Frame(right, bootstyle="light", relief="flat")
        lbl_frame.pack(fill="x", padx=10, pady=(0, 15))
        
        # コンテンツエリア（適切な余白）
        info_content = tb.Frame(lbl_frame, bootstyle="light")
        info_content.pack(fill="x", padx=10, pady=10)
        
        # wraplengthを動的に計算するラベル
        self.info_title_label = tb.Label(info_content, textvariable=self.info_title, 
                font=("", 12, "bold"), 
                bootstyle="primary", foreground="#2C3E50")
        self.info_title_label.pack(anchor="w", pady=(0, 10))
        
        url_label_frame = tb.Frame(info_content, bootstyle="light")
        url_label_frame.pack(fill="x", pady=(0, 6))
        
        tb.Label(url_label_frame, text="🔗 URL:", 
                font=("", 10, "bold"), bootstyle="secondary").pack(side="left", padx=(0, 8))
        
        url_entry = tb.Entry(info_content, textvariable=self.info_url, 
                           state="readonly", bootstyle="light")
        url_entry.pack(fill="x", pady=(0, 10))

        # ========== プレビューセクション ==========
        preview_header = tb.Frame(right, bootstyle="success")
        preview_header.pack(fill="x", pady=(0, 3))
        
        preview_title_label = tb.Label(preview_header, text="👁️ Preview", 
                                      font=("", 11, "bold"), bootstyle="inverse-success")
        preview_title_label.pack(side="left", padx=12, pady=8)
        
        preview_sep = tb.Separator(right, orient="horizontal")
        preview_sep.pack(fill="x", pady=(0, 10))
        
        prev_frame = tb.Frame(right, bootstyle="light", relief="flat")
        prev_frame.pack(fill="x", padx=10, pady=(0, 15))
        
        preview_content = tb.Frame(prev_frame, bootstyle="light")
        preview_content.pack(fill="x", padx=10, pady=10)
        
        # wraplengthを動的に計算するラベル
        self.preview_title_widget = tb.Label(preview_content, textvariable=self.preview_title, 
                                       font=("", 11, "bold"), 
                                       bootstyle="success", foreground="#27AE60")
        self.preview_title_widget.pack(anchor="w", pady=(0, 8))
        
        # 説明テキストはTextウィジェットでスクロール可能に（マテリアルデザイン風）
        preview_desc_frame = tb.Frame(preview_content, bootstyle="light")
        preview_desc_frame.pack(fill="both", expand=True, anchor="w")
        
        self.preview_desc_text = tk.Text(preview_desc_frame, 
                                        font=("", 10), 
                                        wrap="word",
                                        height=4,
                                        relief="flat",
                                        bg="#F8F9FA",
                                        fg="#34495E",
                                        padx=8,
                                        pady=6,
                                        borderwidth=0,
                                        highlightthickness=1,
                                        highlightbackground="#E0E0E0",
                                        highlightcolor="#2196F3",
                                        state="disabled")
        self.preview_desc_text.pack(fill="both", expand=True)

        # ========== アクションセクション ==========
        actions_header = tb.Frame(right, bootstyle="warning")
        actions_header.pack(fill="x", pady=(0, 3))

        actions_title_label = tb.Label(actions_header, text="⚡ Actions", 
                                      font=("", 11, "bold"), bootstyle="inverse-warning")
        actions_title_label.pack(side="left", padx=12, pady=8)
        
        actions_sep = tb.Separator(right, orient="horizontal")
        actions_sep.pack(fill="x", pady=(0, 10))
        
        act_frame = tb.Frame(right, bootstyle="light", relief="flat")
        act_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        actions_content = tb.Frame(act_frame, bootstyle="light")
        actions_content.pack(fill="both", expand=True, padx=10, pady=10)

        # 作成セクション
        create_section = tb.Label(actions_content, text="Create", 
                                 font=("", 10, "bold"), bootstyle="primary", 
                                 foreground="#2C3E50")
        create_section.pack(anchor="w", pady=(0, 6))
        
        tb.Button(actions_content, text="📁 New Folder", command=self.cmd_new_folder, 
                 bootstyle="info-outline", width=24).pack(fill="x", pady=4)
        tb.Button(actions_content, text="🔖 New Bookmark", command=self.cmd_new_bookmark, 
                 bootstyle="info-outline", width=24).pack(fill="x", pady=4)
        
        tb.Separator(actions_content, orient="horizontal").pack(fill="x", pady=10)
        
        # 編集セクション
        edit_section = tb.Label(actions_content, text="Edit", 
                               font=("", 10, "bold"), bootstyle="primary", 
                               foreground="#2C3E50")
        edit_section.pack(anchor="w", pady=(0, 6))
        
        tb.Button(actions_content, text="✏️ Rename (F2)", command=self.cmd_rename, 
                 bootstyle="secondary-outline", width=24).pack(fill="x", pady=4)
        tb.Button(actions_content, text="🔗 Edit URL", command=self.cmd_edit_url, 
                 bootstyle="secondary-outline", width=24).pack(fill="x", pady=4)
        tb.Button(actions_content, text="📦 Move to Folder…", command=self.cmd_move_to_folder, 
                 bootstyle="secondary-outline", width=24).pack(fill="x", pady=4)
        tb.Button(actions_content, text="⬆️ Move Up (Ctrl+↑)", command=self.cmd_move_up, 
                 bootstyle="secondary-outline", width=24).pack(fill="x", pady=4)
        tb.Button(actions_content, text="🗑️ Delete", command=self.cmd_delete, 
                 bootstyle="danger-outline", width=24).pack(fill="x", pady=4)

        tb.Separator(actions_content, orient="horizontal").pack(fill="x", pady=10)

        # 整理セクション
        organize_section = tb.Label(actions_content, text="Organize", 
                                   font=("", 10, "bold"), bootstyle="primary", 
                                   foreground="#2C3E50")
        organize_section.pack(anchor="w", pady=(0, 6))

        tb.Button(actions_content, text="🔤 Sort by Title", command=lambda: self.cmd_sort("title"), 
                 bootstyle="secondary-outline", width=24).pack(fill="x", pady=4)
        tb.Button(actions_content, text="🌐 Sort by Domain", command=lambda: self.cmd_sort("domain"), 
                 bootstyle="secondary-outline", width=24).pack(fill="x", pady=4)
        tb.Button(actions_content, text="🔍 Deduplicate", command=self.cmd_dedupe, 
                 bootstyle="secondary-outline", width=24).pack(fill="x", pady=4)
        tb.Button(actions_content, text="🔀 Merge Folders", command=self.cmd_merge_folders, 
                 bootstyle="secondary-outline", width=24).pack(fill="x", pady=4)
        
        tb.Separator(actions_content, orient="horizontal").pack(fill="x", pady=10)
        
        # AI機能
        ai_section = tb.Label(actions_content, text="AI Features", 
                             font=("", 10, "bold"), bootstyle="primary", 
                             foreground="#2C3E50")
        ai_section.pack(anchor="w", pady=(0, 6))
        
        tb.Button(actions_content, text="🤖 Smart Classify (AI)", command=self.cmd_smart_classify, 
                 bootstyle="primary", width=24).pack(fill="x", pady=6)

        self.ctx = tk.Menu(self, tearoff=0)
        self.ctx.add_command(label="New Folder", command=self.cmd_new_folder)
        self.ctx.add_command(label="New Bookmark", command=self.cmd_new_bookmark)
        self.ctx.add_separator()
        self.ctx.add_command(label="Rename", command=self.cmd_rename)
        self.ctx.add_command(label="Edit URL", command=self.cmd_edit_url)
        self.ctx.add_command(label="Move to Folder…", command=self.cmd_move_to_folder)
        self.ctx.add_command(label="Move Up", command=self.cmd_move_up)
        self.ctx.add_separator()
        self.ctx.add_command(label="Merge Duplicate Folders", command=self.cmd_merge_folders)
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
        self.bind_all("<Control-plus>", lambda e: self.cmd_expand_all())
        self.bind_all("<Control-equal>", lambda e: self.cmd_expand_all())  # + without shift
        self.bind_all("<Control-minus>", lambda e: self.cmd_collapse_all())

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

        # Configure tags for treeview（ライトテーマ用の洗練されたカラー）
        self.tree.tag_configure('oddrow', background='#FFFFFF')
        self.tree.tag_configure('evenrow', background='#F8F9FA')
        self.tree.tag_configure('nourl', foreground='#95A5A6')
        self.tree.tag_configure('folder', font=bold_font, foreground='#E67E22')  # オレンジ系
        self.tree.tag_configure("match", background="#FFE5E5", foreground="#C0392B")  # 検索ハイライト
        self.tree.tag_configure("drop_folder", background="#E3F2FD", foreground="#1976D2")  # ドロップフォルダハイライト
        self.tree.tag_configure("drop_target", background="#FFF3E0", foreground="#F57C00")  # ドロップターゲットハイライト
        
        # ツリービューのスタイリング改善（読みやすく洗練されたデザイン）
        style = tb.Style()
        base_font = ("Segoe UI", 11) if sys.platform == "win32" else ("", 11)
        style.configure("Treeview", 
                       rowheight=28,  # より広い行間で読みやすく
                       font=base_font,
                       background="#FFFFFF",
                       foreground="#2C3E50",
                       fieldbackground="#FFFFFF",
                       borderwidth=1,
                       relief="flat")
        style.configure("Treeview.Heading", 
                       font=(base_font[0], base_font[1], "bold"),
                       background="#ECF0F1",
                       foreground="#2C3E50",
                       relief="flat",
                       borderwidth=1)
        style.map("Treeview.Heading",
                 background=[("active", "#3498DB")],
                 foreground=[("active", "white")])
        style.map("Treeview",
                 background=[("selected", "#3498DB")],
                 foreground=[("selected", "white")])

        self._refresh_tree()
        
        # ウィンドウサイズ変更時にwraplengthを更新
        self.bind("<Configure>", lambda e: self._update_wraplengths())
        
        # ========== ステータスバー（洗練されたデザイン） ==========
        status_separator = tb.Separator(self, orient="horizontal")
        status_separator.pack(fill="x", padx=0, pady=0)
        
        status_bar = tb.Frame(self, bootstyle="light", height=32)
        status_bar.pack(fill="x", side="bottom", padx=0, pady=0)
        status_bar.pack_propagate(False)
        
        # 左側：ファイル情報
        status_left = tb.Frame(status_bar, bootstyle="light")
        status_left.pack(side="left", fill="y", padx=15, pady=6)
        
        self.status_file_label = tb.Label(status_left, text="📄 No file loaded", 
                                         font=("", 10), bootstyle="secondary")
        self.status_file_label.pack(side="left", padx=(0, 20))
        
        # 中央：統計情報
        status_center = tb.Frame(status_bar, bootstyle="light")
        status_center.pack(side="left", fill="y", expand=True, padx=15, pady=6)
        
        self.status_stats_label = tb.Label(status_center, text="", 
                                          font=("", 10), bootstyle="secondary")
        self.status_stats_label.pack(side="left")
        
        # 右側：その他の情報
        status_right = tb.Frame(status_bar, bootstyle="light")
        status_right.pack(side="right", fill="y", padx=15, pady=6)
        
        self.status_info_label = tb.Label(status_right, text="Ready", 
                                         font=("", 10), bootstyle="secondary")
        self.status_info_label.pack(side="right")

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
                    self._preview_fetching.discard(url)  # リクエスト完了を記録
                    sels = self.tree.selection()
                    if len(sels) == 1:
                        node = self._node_of(sels[0])
                        if node and node.url == url:
                            self._update_preview_pane(preview_data)
                elif task_type == 'favicon':
                    url, favicon_data = data
                    # 該当するノードを探してファビコンを更新
                    for iid, node in self._iid_to_node.items():
                        if node.url == url and node.type == "bookmark":
                            node.icon = favicon_data
                            favicon_image = self._get_favicon_image(url, favicon_data)
                            if favicon_image:
                                self.tree.item(iid, image=favicon_image)
                            break
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
        """requestsライブラリ用にプロキシ設定を返す（ConfigManager経由）。"""
        return self.config_manager.get_proxies_for_requests(self.use_proxy_var.get())

    def _fetch_preview_worker(self, url: str):
        """ブックマークのプレビュー情報を非同期で取得（リトライ機能付き）。"""
        proxy_info = self._get_proxies_for_requests()
        fetch_preview(url, self.ui_queue, proxy_info)

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
                
                # テキストとアイコンの準備
                text = ch.title or ""
                image = None
                
                if ch.type == "folder":
                    # フォルダは絵文字アイコン
                    text = "📁 " + text
                elif ch.type == "bookmark" and ch.url:
                    # ブックマークはファビコンを表示
                    image = self._get_favicon_image(ch.url, ch.icon)
                    if not image:
                        # ファビコンが取得できない場合は非同期で取得
                        self._fetch_favicon_async(ch.url, ch)
                
                url_display = ch.url
                if not ch.url and ch.type == 'bookmark':
                    url_display = '(None)'
                    tags_to_add.append('nourl')
                
                # imageがNoneの場合はパラメータに含めない
                insert_kwargs = {
                    "text": text,
                    "values": (url_display,),
                    "tags": tuple(tags_to_add)
                }
                if image is not None:
                    insert_kwargs["image"] = image
                
                iid = self.tree.insert(parent_iid, "end", **insert_kwargs)
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
        self._update_statistics()

    def _build_search_index(self, updated_nodes: Optional[set] = None):
        """
        検索インデックスを単語ベースの辞書形式で構築
        
        Args:
            updated_nodes: 更新されたノードのセット（Noneの場合は全ノードを再構築）
        """
        if updated_nodes is None:
            # 全ノードを再構築
            self.search_index = {}
            nodes_to_index = self._iid_to_node.items()
        else:
            # 差分更新：更新されたノードに関連するインデックスエントリを削除
            for iid, node in list(self._iid_to_node.items()):
                if node in updated_nodes or iid in updated_nodes:
                    # 既存のインデックスエントリを削除
                    full_text = f"{(node.title or '').lower()} {(node.url or '').lower()}"
                    words = set(re.split(r'\W+', full_text))
                    for word in words:
                        if word and word in self.search_index:
                            self.search_index[word].discard(iid)
                            if not self.search_index[word]:
                                del self.search_index[word]
            # 更新されたノードのみをインデックス化
            nodes_to_index = [(iid, node) for iid, node in self._iid_to_node.items() 
                            if node in updated_nodes or iid in updated_nodes]
        
        # インデックスを構築
        for iid, node in nodes_to_index:
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
        # Textウィジェットに説明を設定
        self.preview_desc_text.config(state="normal")
        self.preview_desc_text.delete("1.0", tk.END)
        self.preview_desc_text.insert("1.0", preview_data.get("description", ""))
        self.preview_desc_text.config(state="disabled")
        # wraplengthを動的に更新
        self._update_wraplengths()

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
                elif node.url not in self._preview_fetching:  # 重複リクエスト防止
                    self._preview_fetching.add(node.url)  # リクエスト開始を記録
                    self.preview_title.set("Loading preview...")
                    self.preview_desc_text.config(state="normal")
                    self.preview_desc_text.delete("1.0", tk.END)
                    self.preview_desc_text.config(state="disabled")
                    threading.Thread(target=self._fetch_preview_worker, args=(node.url,), daemon=True).start()

    def cmd_open(self) -> None:
        # Ubuntuでは大文字小文字が厳格なので、すべてのパターンを明示的に指定
        path = filedialog.askopenfilename(
            title="Open Chrome Bookmarks HTML",
            filetypes=[
                ("HTML files", "*.html"),
                ("HTML files", "*.HTML"),
                ("HTML files", "*.htm"),
                ("HTML files", "*.HTM"),
                ("All files", "*.*")
            ],
        )
        if not path: return
        try:
            root, rules, rules_path = load_bookmarks(path)
            self.root_node = root
            self.rules = rules or self._default_rules()
            self.rules_path = rules_path
            self.current_file = path
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load bookmarks:\n{e}")
            return
        self.open_nodes.clear()
        self._refresh_tree()
        roots = self.tree.get_children("")
        if roots:
            first_node = self._node_of(roots[0])
            if first_node:
                self.open_nodes.add(first_node)
                self.tree.item(roots[0], open=True)
        self.title(f"Bookmark Studio — {os.path.basename(path)}")
        if hasattr(self, 'status_file_label'):
            self.status_file_label.config(text=f"📄 {os.path.basename(path)}")
        self._update_status(f"Loaded: {os.path.basename(path)}")

    def cmd_save(self) -> None:
        if not self.current_file:
            return self.cmd_save_as()
        try:
            sp = save_bookmarks(self.current_file, self.root_node, self.rules)
            if sp:
                self.rules_path = sp
            messagebox.showinfo("Saved", "Saved successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save:\n{e}")

    def cmd_save_as(self) -> None:
        if not self.root_node: return
        # Ubuntuでは大文字小文字が厳格なので、すべてのパターンを明示的に指定
        path = filedialog.asksaveasfilename(
            title="Export Chrome HTML",
            defaultextension=".html",
            filetypes=[
                ("HTML files", "*.html"),
                ("HTML files", "*.HTML"),
                ("HTML files", "*.htm"),
                ("HTML files", "*.HTM"),
                ("All files", "*.*")
            ],
        )
        if not path: return
        try:
            sp = save_bookmarks(path, self.root_node, self.rules)
            messagebox.showinfo("Exported", "Export completed.")
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
        n = Node("bookmark", title=title, url=url, icon="")
        parent.append(n)
        self._refresh_tree()
        new_iid = self._iid_of_node(n)
        if new_iid:
            self.tree.selection_set(new_iid)
            self.tree.see(new_iid)
            # 新規ブックマークのファビコンを非同期で取得
            if url:
                self._fetch_favicon_async(url, n)

    def _start_inline_editor(self, iid: str) -> None:
        node = self._node_of(iid)
        if not node: return
        bbox = self.tree.bbox(iid, column="#0")
        if not bbox: return
        x, y, w, h = bbox
        x_offset = 25
        x += x_offset
        w -= x_offset
        entry = tb.Entry(self.tree)
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
                # 差分更新：変更されたノードのみインデックス更新
                self._build_search_index(updated_nodes={node})

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
        # URL変更時も検索インデックスを更新
        self._build_search_index(updated_nodes={node})
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
        """すべてのフォルダを展開する"""
        self.open_nodes.clear()

        def collect_all_folders(node):
            if node.type == 'folder':
                self.open_nodes.add(node)
                for child in node.children:
                    collect_all_folders(child)

        collect_all_folders(self.root_node)
        self._refresh_tree()
        self._update_status("All folders expanded")

    def cmd_collapse_all(self):
        """すべてのフォルダを折りたたむ"""
        self.open_nodes.clear()
        self._refresh_tree()
        self._update_status("All folders collapsed")
    
    def _get_favicon_image(self, url: str, icon_data: str = "") -> Optional[tk.PhotoImage]:
        """
        ファビコン画像を取得する（キャッシュから、またはicon_dataから）
        
        Args:
            url: ブックマークのURL
            icon_data: HTMLから読み込んだICON属性（base64データURI）
            
        Returns:
            PhotoImageオブジェクト、またはNone
        """
        if not Image or not ImageTk:
            return None
        
        # キャッシュを確認
        cache_key = url
        if cache_key in self._img_cache:
            return self._img_cache[cache_key]
        
        # icon_dataから画像を作成
        if icon_data:
            try:
                if icon_data.startswith("data:image"):
                    # data:image/png;base64,... 形式
                    header, data = icon_data.split(",", 1)
                    img_data = base64.b64decode(data)
                    img = Image.open(io.BytesIO(img_data))
                    # Pillowのバージョン互換性を考慮
                    try:
                        img = img.resize((16, 16), Image.Resampling.LANCZOS)
                    except AttributeError:
                        # 古いバージョンのPillow
                        img = img.resize((16, 16), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    self._img_cache[cache_key] = photo
                    return photo
            except Exception:
                pass
        
        return None
    
    def _fetch_favicon_async(self, url: str, node: Node):
        """ファビコンを非同期で取得する"""
        if url in self._favicon_fetching:
            return
        self._favicon_fetching.add(url)
        
        def worker():
            try:
                proxy_info = self.config_manager.get_proxies_for_requests(self.use_proxy_var.get())
                favicon_data = fetch_favicon(url, proxy_info)
                if favicon_data:
                    node.icon = favicon_data
                    self.ui_queue.put(('favicon', (url, favicon_data)))
            except Exception as e:
                self.logger.debug(f"Failed to fetch favicon for {url}: {e}")
            finally:
                self._favicon_fetching.discard(url)
        
        threading.Thread(target=worker, daemon=True).start()
    
    def _update_statistics(self):
        """統計情報を更新する"""
        def count_items(node):
            folders = 0
            bookmarks = 0
            if node.type == 'folder':
                folders += 1
            else:
                bookmarks += 1
            for child in node.children:
                f, b = count_items(child)
                folders += f
                bookmarks += b
            return folders, bookmarks
        
        folders, bookmarks = count_items(self.root_node)
        # ルートノード自体を除外
        folders = max(0, folders - 1)
        
        stats_text = f"📊 {bookmarks} bookmarks, {folders} folders"
        if hasattr(self, 'stats_label'):
            self.stats_label.config(text=stats_text)
        if hasattr(self, 'status_stats_label'):
            self.status_stats_label.config(text=stats_text)
    
    def _update_wraplengths(self):
        """右パネルのラベルのwraplengthを動的に更新"""
        try:
            if hasattr(self, 'right_canvas') and self.right_canvas.winfo_width() > 0:
                # パディングを考慮してwraplengthを計算（左右各20px + スクロールバー幅）
                canvas_width = self.right_canvas.winfo_width()
                scrollbar_width = 20  # スクロールバーの推定幅
                content_width = canvas_width - scrollbar_width - 40  # 左右パディング
                
                if content_width > 100:  # 最小幅を確保
                    if hasattr(self, 'info_title_label'):
                        self.info_title_label.config(wraplength=content_width)
                    if hasattr(self, 'preview_title_widget'):
                        self.preview_title_widget.config(wraplength=content_width)
        except tk.TclError:
            pass  # ウィンドウがまだ作成されていない場合は無視
    
    def _update_status(self, message: str, duration: int = 3000):
        """ステータスバーにメッセージを表示"""
        if hasattr(self, 'status_info_label'):
            self.status_info_label.config(text=message)
            if duration > 0:
                self.after(duration, lambda: self.status_info_label.config(text="Ready"))

    def _on_search_var_changed(self, *args):
        if self._search_after_id: self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(AppConstants.SEARCH_DELAY_MS, self._apply_search)

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
        """検索バーをクリアする"""
        self.search_var.set("")
        self.search_entry.focus_set()
        self._update_status("Search cleared")

    def _on_tree_press(self, event) -> None:
        """マウスボタン押下時の処理"""
        self.drag_start_iid = self.tree.identify_row(event.y)
        self.drag_start_pos = (event.x_root, event.y_root)  # ドラッグ開始位置を記録
        self.dragging_iids = None  # リセット
        self.drop_target_info = None
        
        if self.drag_start_iid and self.drag_start_iid not in self.tree.selection():
            if not (event.state & 0x0004) and not (event.state & 0x0001):  # Ctrl/Shiftキーが押されていない
                self.tree.selection_set(self.drag_start_iid)

    def _on_tree_drag(self, event) -> None:
        """ドラッグ中の処理"""
        if not self.drag_start_iid or not self.drag_start_pos:
            return
        
        # ドラッグ距離を計算
        dx = abs(event.x_root - self.drag_start_pos[0])
        dy = abs(event.y_root - self.drag_start_pos[1])
        drag_distance = (dx ** 2 + dy ** 2) ** 0.5
        
        # 閾値を超えたらドラッグ開始
        if drag_distance < self._drag_threshold:
            return
        
        # ドラッグ開始（初回のみ）
        if not self.dragging_iids:
            self.dragging_iids = list(self.tree.selection())
            if self.drag_start_iid not in self.dragging_iids:
                self.dragging_iids = None
                return
            
            # ドラッグ開始の視覚的フィードバック
                self.config(cursor="fleur")
                self._create_drag_window()
        
        if not self.dragging_iids:
            return
        
        # ドラッグウィンドウの位置を更新
        if self.drag_window:
            self.drag_window.geometry(f"+{event.x_root + 15}+{event.y_root + 10}")
        
        # ドロップ位置のインジケーターを更新
        self._update_drop_indicator(event.x, event.y)

    def _on_tree_release(self, event) -> None:
        """マウスボタン解放時の処理（ドロップ処理）"""
        self._destroy_drag_window()
        self._destroy_drop_line()
        self.config(cursor="")
        
        # ドラッグが開始されていなかった場合は何もしない
        if not self.dragging_iids:
            self.drag_start_iid = None
            self.drag_start_pos = None
            return
        
        # ドロップ位置が設定されていない場合はキャンセル
        if not self.drop_target_info:
            self.dragging_iids = None
            self.drag_start_iid = None
            self.drag_start_pos = None
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
        if new_iids: 
            self.tree.selection_set(new_iids)
            self.tree.see(new_iids[0])  # 移動先を表示
        
        # 状態をリセット
        self.dragging_iids = None
        self.drop_target_info = None
        self.drag_start_iid = None
        self.drag_start_pos = None
        self._update_status("Items moved successfully")

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
        """ドロップ位置のインジケーターを更新（強化された視覚的フィードバック）"""
        self._destroy_drop_line()
        self.drop_target_info = None
        
        # 前回のドロップハイライトをクリア
        for iid in self._iid_to_node:
            tags = list(self.tree.item(iid, "tags"))
            if "drop_folder" in tags or "drop_target" in tags:
                tags = [t for t in tags if t not in ("drop_folder", "drop_target")]
                self.tree.item(iid, tags=tuple(tags))
        
        # マウス位置のアイテムを取得
        iid = self.tree.identify_row(y)
        if not iid or iid in self.dragging_iids:
            return
        
        bbox = self.tree.bbox(iid)
        if not bbox:
            return
        
        line_x, line_y, line_w, line_h = bbox
        target_node = self._node_of(iid)
        
        if not target_node:
            return
        
        # フォルダの場合は、アイコン部分（左側）にマウスがある場合は「中に入れる」
        # 右側のテキスト部分にマウスがある場合は「前後に入れる」
        if target_node.type == 'folder':
            folder_icon_width = 30  # フォルダアイコンの推定幅
            if x < folder_icon_width:
                # フォルダの中に入れる - マテリアルデザイン風のハイライト
                self.drop_target_info = {"iid": iid, "pos": "in"}
                tags = list(self.tree.item(iid, "tags"))
                tags.append('drop_folder')
                self.tree.item(iid, tags=tuple(tags))
                # ドロップゾーンインジケーター（フォルダ内にドロップ可能なことを示す）
                self.drop_line = tk.Frame(self.tree, height=line_h, bg="#E3F2FD", relief="solid", borderwidth=2, highlightbackground="#2196F3", highlightthickness=1)
                self.drop_line.place(x=line_x, y=line_y, width=line_w, height=line_h)
            else:
                # フォルダの前後に挿入
                drop_pos = 'after' if y > (line_y + line_h / 2) else 'before'
                self.drop_target_info = {"iid": iid, "pos": drop_pos}
                line_y_pos = line_y if drop_pos == 'before' else line_y + line_h
                # より目立つドロップライン（マテリアルデザイン風）
                self.drop_line = tk.Frame(self.tree, height=3, bg="#2196F3", relief="raised", borderwidth=0)
                self.drop_line.place(x=0, y=line_y_pos - 1, width=self.tree.winfo_width())
                # ターゲットアイテムもハイライト
                tags = list(self.tree.item(iid, "tags"))
                tags.append('drop_target')
                self.tree.item(iid, tags=tuple(tags))
        else:
            # ブックマークの場合は前後に挿入
            drop_pos = 'after' if y > (line_y + line_h / 2) else 'before'
            self.drop_target_info = {"iid": iid, "pos": drop_pos}
            line_y_pos = line_y if drop_pos == 'before' else line_y + line_h
            # より目立つドロップライン（マテリアルデザイン風）
            self.drop_line = tk.Frame(self.tree, height=3, bg="#2196F3", relief="raised", borderwidth=0)
            self.drop_line.place(x=0, y=line_y_pos - 1, width=self.tree.winfo_width())
            # ターゲットアイテムもハイライト
            tags = list(self.tree.item(iid, "tags"))
            tags.append('drop_target')
            self.tree.item(iid, tags=tuple(tags))

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
            if not messagebox.askyesno("Auto Classify", "No items selected. Classify ALL bookmarks?"):
                return
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
                response = requests.get(
                    test_url, 
                    proxies=proxy_info['proxies'], 
                    auth=proxy_info['auth'], 
                    timeout=AppConstants.PROXY_TEST_TIMEOUT
                )
                response.raise_for_status()
                self.ui_queue.put(('proxy_check_success', dialog))
            except Exception as e:
                self.ui_queue.put(('proxy_check_failure', (dialog, str(e))))

        threading.Thread(target=worker, daemon=True).start()

    def cmd_set_smart_classify_limit(self) -> None:
        current_limit = self.max_smart_items
        new_limit = simpledialog.askinteger(
            "Smart Classify Limit", 
            f"スマート分類の最大ブックマーク数を入力してください（{AppConstants.MIN_SMART_ITEMS}～{AppConstants.MAX_SMART_ITEMS}）：",
            initialvalue=current_limit, 
            minvalue=AppConstants.MIN_SMART_ITEMS, 
            maxvalue=AppConstants.MAX_SMART_ITEMS, 
            parent=self
        )
        if new_limit is not None: self.max_smart_items = new_limit
        messagebox.showinfo("Smart Classify Limit", f"最大処理数を {new_limit} に設定しました。")

    def cmd_set_title_fetch_timeout(self) -> None:
        new_timeout = simpledialog.askinteger(
            "Title Fetch Timeout", 
            f"タイトル取得のタイムアウト秒数を入力してください（{AppConstants.MIN_FETCH_TIMEOUT}～{AppConstants.MAX_FETCH_TIMEOUT}）：",
            initialvalue=self.fetch_timeout, 
            minvalue=AppConstants.MIN_FETCH_TIMEOUT, 
            maxvalue=AppConstants.MAX_FETCH_TIMEOUT, 
            parent=self
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
        proxy_info = self._get_proxies_for_requests()
        check_cancel = lambda: getattr(self, "_titlefix_cancelled", False)
        fix_titles(nodes, self.ui_queue, proxy_info, self.fetch_timeout, self.logger, check_cancel)

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

