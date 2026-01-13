"""
CustomTkinterベースの新しいメインウィンドウ
モダンなWebアプリ風UI
"""

import os
import json
import re
import threading
import queue
from urllib.parse import urlparse
from typing import Optional, Dict, List, Set, Any
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
import customtkinter as ctk
import logging
from logging.handlers import RotatingFileHandler

# Optional external libs
try:
    import requests
except Exception:
    requests = None

try:
    from services.ai_classifier import AIBookmarkClassifier, BookmarkNode
except Exception:
    AIBookmarkClassifier = None
    class BookmarkNode:
        def __init__(self, title=None, url=None):
            self.title = title
            self.url = url

from core.utils import is_valid_url, LRUCache
from core.storage import ConfigManager, load_bookmarks, save_bookmarks
from core.model import Node
from core.logger import logger  # Import global logger
from gui.dialogs import CustomPromptDialog, FolderSelectDialog
from gui.components import BookmarkCard, FolderTree, SearchBar, DetailPanel, BookmarkRow
from services.workers import fetch_preview, fix_titles
from gui.drag_manager import DragManager

# CustomTkinterのテーマ設定 - Apple-inspired Light Theme
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

from gui.ui_kit import StyledButton
from gui.theme import Colors, Fonts, Dims


class App(ctk.CTk):
    """メインアプリケーションクラス（CustomTkinterベース）"""
    
    def __init__(self):
        # #region agent log
        import json
        from datetime import datetime
        def debug_log(loc, msg, data=None, hid=None):
            try:
                with open("/home/kei/PythonProject/NeoBookMarkManager/.cursor/debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":hid,"location":loc,"message":msg,"data":data or {},"timestamp":int(datetime.now().timestamp()*1000)}) + "\n")
            except: pass
        # #endregion
        
        debug_log("main_window.py:55", "App.__init__ entry", {}, "H3")
        
        try:
            debug_log("main_window.py:58", "Calling super().__init__()", {}, "H3")
            super().__init__()
            debug_log("main_window.py:60", "super().__init__() completed", {}, "H3")
        except Exception as e:
            debug_log("main_window.py:62", "Error in super().__init__()", {"error": str(e)}, "H3")
            raise

        # ---- Font family stabilization (Hypothesis H6) ----
        # Some environments crash in C-layer when CTkFont is created with a non-existent family.
        # We pick the first available font from a safe candidate list.
        try:
            debug_log("main_window.py:66", "Selecting safe font family", {"preferred": getattr(Fonts, "FAMILY", None)}, "H6")
            import tkinter.font as tkfont
            available = set(tkfont.families(self))
            candidates = [
                getattr(Fonts, "FAMILY", None),
                getattr(Fonts, "FAMILY_FALLBACK", None),
                "Noto Sans CJK JP",
                "Noto Sans JP",
                "Noto Sans",
                "DejaVu Sans",
                "Arial",
            ]
            chosen = None
            for cand in candidates:
                if cand and cand in available:
                    chosen = cand
                    break
            if not chosen:
                chosen = tkfont.nametofont("TkDefaultFont").cget("family")
            Fonts.FAMILY = chosen
            debug_log("main_window.py:86", "Font family chosen", {"chosen": chosen, "available_count": len(available)}, "H6")
        except Exception as e:
            debug_log("main_window.py:88", "Failed to select safe font family", {"error": str(e)}, "H6")
        
        self.title("Bookmark Studio — Chrome Bookmarks Organizer")
        self.geometry("1400x800")
        self.minsize(1000, 600)
        
        debug_log("main_window.py:69", "Window properties set", {}, "H3")
        
        # ログ設定 (Use centralized logger)
        self.logger = logger
        self._setup_logging()
        debug_log("main_window.py:73", "Logging setup completed", {}, "H3")
        
        # 設定管理
        try:
            debug_log("main_window.py:76", "Creating ConfigManager", {}, "H3")
            self.config_manager = ConfigManager()
            debug_log("main_window.py:78", "ConfigManager created", {}, "H3")
        except Exception as e:
            debug_log("main_window.py:80", "Error creating ConfigManager", {"error": str(e)}, "H3")
            raise
        
        # ドラッグマネージャー
        try:
            debug_log("main_window.py:84", "Creating DragManager", {}, "H3")
            self.drag_manager = DragManager(self, on_drop=self._on_drop_item)
            debug_log("main_window.py:86", "DragManager created", {}, "H3")
        except Exception as e:
            debug_log("main_window.py:88", "Error creating DragManager", {"error": str(e)}, "H3")
            raise

        # データモデル
        self.root_node = Node("folder", "Bookmarks")
        self.current_file = None
        self.rules = self._default_rules()
        self.rules_path = None
        self.current_folder = self.root_node  # 現在表示中のフォルダ
        
        # UI状態
        self.card_to_node: Dict[Any, Node] = {} # Card or Row -> Node
        self.selected_cards: Set[Any] = set()
        self.preview_cache = LRUCache(maxsize=50)
        self.ui_queue = queue.Queue()
        self.search_index = {}
        self.max_smart_items = 300
        self.progress_history = []
        self.use_proxy_var = ctk.BooleanVar(value=True)
        self.view_mode = "card" # "card" or "list"
        
        # AI分類関連
        self.last_classified_bookmarks = []
        self.last_classification_prompts = []
        self._smart_dialog = None
        self._smart_cancelled = False
        self.progress_var = None
        self.progress_label = None
        self.traffic_label = None
        
        # タイトル修正関連
        self._titlefix_dialog = None
        self._titlefix_cancelled = False
        self._titlefix_var = None
        self._titlefix_label = None
        self.fetch_timeout = 10
        
        # HTML読み込み関連
        self._load_dialog = None
        self._load_cancelled = False
        self._load_var = None
        self._load_label = None
        
        debug_log("main_window.py:130", "Before _build_ui()", {}, "H4")
        
        # UI構築
        try:
            self._build_ui()
            debug_log("main_window.py:134", "_build_ui() completed", {}, "H4")
        except Exception as e:
            debug_log("main_window.py:136", "Error in _build_ui()", {"error": str(e)}, "H4")
            raise
        
        try:
            debug_log("main_window.py:140", "Before _build_search_index()", {}, "H3")
            self._build_search_index()
            debug_log("main_window.py:142", "_build_search_index() completed", {}, "H3")
        except Exception as e:
            debug_log("main_window.py:144", "Error in _build_search_index()", {"error": str(e)}, "H3")
            raise
        
        self.after(100, self._process_ui_queue)
        debug_log("main_window.py:148", "UI queue processor scheduled", {}, "H3")
        
        self.logger.info("Application started.")
        debug_log("main_window.py:151", "App.__init__ completed successfully", {}, "H3")
    
    def _setup_logging(self):
        """ログ設定 (Add file handler to global logger)"""
        # Ensure we don't add multiple handlers if called multiple times
        for handler in self.logger.handlers:
            if isinstance(handler, RotatingFileHandler):
                return

        log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        file_handler = RotatingFileHandler('bookmark_editor.log', maxBytes=1024 * 1024 * 5, backupCount=3, encoding='utf-8')
        file_handler.setFormatter(log_formatter)
        file_handler.setLevel(logging.INFO)
        
        self.logger.addHandler(file_handler)

    def _build_ui(self):
        """UIを構築"""
        # メニューバー
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
        
        # CustomTkinterではメニューバーを直接設定できないため、tkinterのメニューを使用
        try:
            self.tk.call('tk', 'windowingsystem') == 'aqua'
            self.createcommand('tk::mac::ReopenApplication', lambda: None)
        except Exception as e:
            # macOS固有の処理なので、非macOS環境では例外が発生する可能性がある（正常）
            self.logger.debug(f"macOS-specific menu setup skipped: {e}")
        self.config(menu=menubar)
        
        # メインレイアウト: 2カラム（メインエリア、右サイドパネル）
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0, minsize=360) # Right panel fixed/wrap (340 + padding)
        self.grid_rowconfigure(0, weight=1)
        
        # メインエリア (Tree + Search/Cards)
        main_area = ctk.CTkFrame(self, fg_color=Colors.BACKGROUND)
        main_area.grid(row=0, column=0, sticky="nsew", padx=Dims.SPACING_S, pady=Dims.SPACING_S)
        main_area.grid_columnconfigure(0, weight=1)
        # ツリービュー 65%、パネルビュー 30%の比率（残り5%は余白）
        main_area.grid_rowconfigure(0, weight=65)  # Tree area: 65%
        main_area.grid_rowconfigure(1, weight=30)  # Cards area: 30%
        
        # 上部エリア (Folder Tree)
        tree_container = ctk.CTkFrame(main_area, fg_color=Colors.SURFACE, corner_radius=Dims.RADIUS_M)
        tree_container.grid(row=0, column=0, sticky="nsew", padx=Dims.SPACING_S, pady=(0, Dims.SPACING_S))
        tree_container.grid_columnconfigure(0, weight=1)
        tree_container.grid_rowconfigure(1, weight=1)
        
        # ツリーヘッダー（タイトルとボタン）
        tree_header = ctk.CTkFrame(tree_container, fg_color="transparent")
        tree_header.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        tree_header.grid_columnconfigure(0, weight=1)
        
        tree_label = ctk.CTkLabel(tree_header, text="📁 Bookmarks", font=ctk.CTkFont(family=Fonts.FAMILY, size=14, weight="bold"))
        tree_label.grid(row=0, column=0, sticky="w")
        
        # 2画面モードトグルボタン
        self.dual_view_mode = False
        self.dual_view_btn = ctk.CTkButton(
            tree_header, text="2画面モード", width=80, height=22,
            font=ctk.CTkFont(family=Fonts.FAMILY, size=10), fg_color=Colors.SURFACE,
            text_color=Colors.TEXT_PRIMARY, hover_color=Colors.HOVER_BG,
            command=self._toggle_dual_view_mode
        )
        self.dual_view_btn.grid(row=0, column=1, sticky="e", padx=(0, 5))
        
        # 展開/縮小ボタン
        btn_frame = ctk.CTkFrame(tree_header, fg_color="transparent")
        btn_frame.grid(row=0, column=2, sticky="e")
        
        # 選択フォルダの展開/縮小
        expand_one_btn = ctk.CTkButton(
            btn_frame, text="展開", width=50, height=22,
            font=ctk.CTkFont(family=Fonts.FAMILY, size=10), fg_color=Colors.SURFACE,
            text_color=Colors.TEXT_PRIMARY, hover_color=Colors.HOVER_BG,
            command=lambda: self.folder_tree.expand_selected()
        )
        expand_one_btn.pack(side="left", padx=1)
        
        collapse_one_btn = ctk.CTkButton(
            btn_frame, text="縮小", width=50, height=22,
            font=ctk.CTkFont(family=Fonts.FAMILY, size=10), fg_color=Colors.SURFACE,
            text_color=Colors.TEXT_PRIMARY, hover_color=Colors.HOVER_BG,
            command=lambda: self.folder_tree.collapse_selected()
        )
        collapse_one_btn.pack(side="left", padx=1)
        
        # セパレータ
        sep = ctk.CTkFrame(btn_frame, width=1, height=18, fg_color=Colors.BORDER)
        sep.pack(side="left", padx=4)
        
        # すべて展開/縮小
        expand_all_btn = ctk.CTkButton(
            btn_frame, text="すべて展開", width=70, height=22,
            font=ctk.CTkFont(family=Fonts.FAMILY, size=10), fg_color=Colors.PRIMARY,
            command=lambda: self.folder_tree.expand_all()
        )
        expand_all_btn.pack(side="left", padx=1)
        
        collapse_all_btn = ctk.CTkButton(
            btn_frame, text="すべて縮小", width=70, height=22,
            font=ctk.CTkFont(family=Fonts.FAMILY, size=10), fg_color=Colors.SURFACE,
            text_color=Colors.TEXT_PRIMARY, hover_color=Colors.HOVER_BG,
            command=lambda: self.folder_tree.collapse_all()
        )
        collapse_all_btn.pack(side="left", padx=1)
        
        # 左側ツリービュー（通常モードではこれのみ表示）
        self.folder_tree = FolderTree(
            tree_container,
            self.root_node,
            on_folder_select=self._on_folder_selected,
            on_bookmark_click=self._on_card_click,
            on_bookmark_double_click=self._on_card_double_click
        )
        self.folder_tree.grid(row=1, column=0, sticky="nsew", padx=Dims.SPACING_S, pady=Dims.SPACING_S)
        
        # 右側ツリービュー（2画面モード時のみ表示）
        self.folder_tree_right = FolderTree(
            tree_container,
            self.root_node,
            on_folder_select=self._on_folder_selected_right,
            on_bookmark_click=self._on_card_click,
            on_bookmark_double_click=self._on_card_double_click
        )
        # 初期状態では非表示
        self.folder_tree_right.grid_remove()
        
        # 2つのツリービューを相互参照（2画面モード間のドラッグ&ドロップ用）
        self.folder_tree.other_tree = self.folder_tree_right
        self.folder_tree_right.other_tree = self.folder_tree
        
        # 下部エリア (Header + Cards)
        cards_container = ctk.CTkFrame(main_area, fg_color="transparent")
        cards_container.grid(row=1, column=0, sticky="nsew", padx=Dims.SPACING_S, pady=0)
        cards_container.grid_columnconfigure(0, weight=1)
        cards_container.grid_rowconfigure(1, weight=1)
        
        # ヘッダー（検索バーとアクションボタン）
        header_frame = ctk.CTkFrame(cards_container, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 5))
        header_frame.grid_columnconfigure(0, weight=1)
        
        self.search_bar = SearchBar(header_frame, on_search=self._on_search)
        self.search_bar.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        # ビュー切り替えボタン
        self.view_toggle_btn = ctk.CTkButton(
            header_frame, 
            text="List View", 
            width=100, 
            height=36,
            font=ctk.CTkFont(family=Fonts.FAMILY, size=Fonts.SIZE_S),
            command=self._toggle_view_mode
        )
        self.view_toggle_btn.grid(row=0, column=1, padx=0)

        # #region agent log
        import json
        from datetime import datetime
        def debug_log(loc, msg, data=None, hid=None):
            try:
                with open("/home/kei/PythonProject/NeoBookMarkManager/.cursor/debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":hid,"location":loc,"message":msg,"data":data or {},"timestamp":int(datetime.now().timestamp()*1000)}) + "\n")
            except: pass
        # #endregion
        
        debug_log("main_window.py:364", "Before creating cards_frame", {}, "H4")
        
        # ブックマーク表示エリア
        try:
            # NOTE: CTkScrollableFrame は環境によって Segmentation fault を起こすことがあるため
            # まず安定化優先で通常の CTkFrame に置換して切り分ける（スクロールは後で復元）
            self.cards_frame = ctk.CTkFrame(cards_container, fg_color=Colors.BACKGROUND)
            debug_log("main_window.py:369", "cards_frame (CTkFrame) created (no scroll)", {}, "H4")
            
            self.cards_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
            debug_log("main_window.py:372", "cards_frame.grid() called", {}, "H4")
            
            self.cards_frame.grid_columnconfigure(0, weight=1)
            debug_log("main_window.py:375", "cards_frame.grid_columnconfigure() called", {}, "H4")
        except Exception as e:
            debug_log("main_window.py:377", "Error creating cards_frame", {"error": str(e)}, "H4")
            raise
        
        debug_log("main_window.py:380", "Before creating right_frame", {}, "H5")
        
        # 右側詳細パネル（サイドバー）
        try:
            right_frame = ctk.CTkFrame(self, fg_color=Colors.SURFACE, width=340)
            debug_log("main_window.py:330", "right_frame created", {}, "H5")
            
            right_frame.grid(row=0, column=1, sticky="nsew", padx=Dims.SPACING_S, pady=Dims.SPACING_S)
            debug_log("main_window.py:333", "right_frame.grid() called", {}, "H5")
        except Exception as e:
            debug_log("main_window.py:335", "Error creating right_frame", {"error": str(e)}, "H5")
            raise
        
        # 右側パネル内ではpackを使用（CTkScrollableFrameとの互換性のため）
        
        debug_log("main_window.py:404", "Before creating scrollable_frame", {}, "H5")
        
        # スクロール可能なボタンエリア（上部）
        # CTkScrollableFrameがSegmentation faultを引き起こすため、通常のCTkFrameに変更
        # スクロールは手動で実装するか、後で追加
        try:
            debug_log("main_window.py:409", "Using CTkFrame instead of CTkScrollableFrame to avoid segfault", {}, "H5")
            scrollable_frame = ctk.CTkFrame(right_frame, fg_color="transparent")
            debug_log("main_window.py:411", "scrollable_frame (CTkFrame) created", {}, "H5")
            
            debug_log("main_window.py:413", "Before scrollable_frame.pack()", {}, "H5")
            scrollable_frame.pack(fill="both", expand=True, padx=0, pady=0)
            debug_log("main_window.py:415", "scrollable_frame.pack() completed", {}, "H5")
        except Exception as e:
            debug_log("main_window.py:417", "Error creating scrollable_frame", {"error": str(e)}, "H5")
            raise
        except:
            debug_log("main_window.py:420", "Unexpected error creating scrollable_frame", {}, "H5")
            raise
        
        # #region agent log
        import json
        from datetime import datetime
        def debug_log(loc, msg, data=None, hid=None):
            try:
                with open("/home/kei/PythonProject/NeoBookMarkManager/.cursor/debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":hid,"location":loc,"message":msg,"data":data or {},"timestamp":int(datetime.now().timestamp()*1000)}) + "\n")
            except: pass
        # #endregion
        
        debug_log("main_window.py:423", "Before adding File section", {}, "H4")
        
        # === File セクション ===
        self._add_section_header(scrollable_frame, "📁 ファイル")
        self._add_button(scrollable_frame, "📂 開く (Ctrl+O)", self.cmd_open, "primary")
        self._add_button(scrollable_frame, "💾 保存 (Ctrl+S)", self.cmd_save, "primary")
        self._add_button(scrollable_frame, "💾 名前を付けて保存 (Ctrl+Shift+S)", self.cmd_save_as, "secondary")
        self._add_separator(scrollable_frame)
        self._add_button(scrollable_frame, "🚪 終了", self.destroy, "secondary")
        
        debug_log("main_window.py:434", "File section added", {}, "H4")
        
        # === Edit セクション ===
        debug_log("main_window.py:447", "Before adding Edit section", {}, "H4")
        try:
            debug_log("main_window.py:449", "Calling _add_section_header for Edit", {}, "H4")
            self._add_section_header(scrollable_frame, "✏️ 編集")
            debug_log("main_window.py:451", "_add_section_header for Edit completed", {}, "H4")
            
            debug_log("main_window.py:453", "Before adding buttons to Edit section", {}, "H4")
            self._add_button(scrollable_frame, "📁 新規フォルダ (Ctrl+Shift+N)", self.cmd_new_folder, "success")
            debug_log("main_window.py:455", "First button added", {}, "H4")
            
            self._add_button(scrollable_frame, "🔖 新規ブックマーク (Ctrl+N)", self.cmd_new_bookmark, "success")
            debug_log("main_window.py:458", "Second button added", {}, "H4")
            
            self._add_separator(scrollable_frame)
            debug_log("main_window.py:461", "Separator added", {}, "H4")
            
            self._add_button(scrollable_frame, "✏️ 名前を変更 (F2)", self.cmd_rename, "primary")
            self._add_button(scrollable_frame, "🔗 URLを編集", self.cmd_edit_url, "primary")
            self._add_separator(scrollable_frame)
            self._add_button(scrollable_frame, "📦 フォルダに移動", self.cmd_move_to_folder, "secondary")
            self._add_button(scrollable_frame, "⬆️ 上に移動 (Ctrl+Up)", self.cmd_move_up, "secondary")
            self._add_button(scrollable_frame, "🗑️ 削除 (Delete)", self.cmd_delete, "danger")
            debug_log("main_window.py:470", "Edit section added", {}, "H4")
        except Exception as e:
            debug_log("main_window.py:472", "Error adding Edit section", {"error": str(e)}, "H4")
            raise
        
        # === Tools - 並び替え・整理 セクション ===
        self._add_section_header(scrollable_frame, "🔄 並び替え・整理")
        self._add_button(scrollable_frame, "🔤 タイトル順に並び替え", lambda: self.cmd_sort("title"), "secondary")
        self._add_button(scrollable_frame, "🌐 ドメイン順に並び替え", lambda: self.cmd_sort("domain"), "secondary")
        self._add_separator(scrollable_frame)
        self._add_button(scrollable_frame, "🔍 重複を削除", self.cmd_dedupe, "secondary")
        self._add_button(scrollable_frame, "📁 重複フォルダを統合", self.cmd_merge_folders, "secondary")
        
        # === Tools - AI分類 セクション ===
        self._add_section_header(scrollable_frame, "🤖 AI分類")
        self._add_button(scrollable_frame, "✨ スマート分類 (AI)", self.cmd_smart_classify, "primary")
        self._add_button(scrollable_frame, "📋 ルール分類", self.cmd_show_classify_preview, "primary")
        self._add_button(scrollable_frame, "⚙️ 分類ルールを編集", self.cmd_edit_rules, "secondary")
        self._add_button(scrollable_frame, "📊 分類上限を設定", self.cmd_set_smart_classify_limit, "secondary")
        
        # === Tools - タイトル修正 セクション ===
        self._add_section_header(scrollable_frame, "🔧 タイトル修正")
        self._add_button(scrollable_frame, "🔗 URLからタイトルを取得", self.cmd_fix_titles_from_url, "primary")
        self._add_button(scrollable_frame, "⏱️ タイムアウト設定", self.cmd_set_title_fetch_timeout, "secondary")
        
        # === Tools - プロキシ設定 セクション ===
        self._add_section_header(scrollable_frame, "🌐 プロキシ設定")
        proxy_check_frame = ctk.CTkFrame(scrollable_frame, fg_color="transparent")
        proxy_check_frame.pack(fill="x", padx=10, pady=2)
        ctk.CTkCheckBox(
            proxy_check_frame,
            text="プロキシを使用する",
            variable=self.use_proxy_var,
            font=ctk.CTkFont(family=Fonts.FAMILY, size=Fonts.SIZE_S)
        ).pack(side="left", padx=(0, 5))
        self._add_button(scrollable_frame, "🔌 プロキシ接続をテスト", self.cmd_check_proxy, "secondary")
        
        # === Tools - その他 セクション ===
        debug_log("main_window.py:492", "Before adding Other section", {}, "H4")
        self._add_section_header(scrollable_frame, "📊 その他")
        self._add_button(scrollable_frame, "📈 進捗チャートを表示", self.cmd_show_progress_chart, "secondary")
        debug_log("main_window.py:495", "All sections added to scrollable_frame", {}, "H4")
        
        # 詳細パネル（下部、固定）
        debug_log("main_window.py:498", "Before creating detail_container", {}, "H4")
        detail_container = ctk.CTkFrame(right_frame, fg_color=Colors.SURFACE, height=200)
        detail_container.pack(fill="x", padx=0, pady=0, side="bottom")
        debug_log("main_window.py:501", "detail_container created and packed", {}, "H4")
        # packではgrid_propagateは使用できないため、heightでサイズを固定
        
        detail_header = ctk.CTkLabel(
            detail_container,
            text="ℹ️ 詳細情報",
            font=ctk.CTkFont(family=Fonts.FAMILY, size=Fonts.SIZE_S, weight=Fonts.WEIGHT_BOLD),
            text_color=Colors.TEXT_PRIMARY,
            anchor="w"
        )
        detail_header.pack(fill="x", padx=10, pady=(8, 4))
        debug_log("main_window.py:512", "detail_header created", {}, "H4")
        
        self.detail_panel = DetailPanel(detail_container)
        self.detail_panel.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        debug_log("main_window.py:516", "detail_panel created", {}, "H4")
        
        # キーバインド
        debug_log("main_window.py:519", "Before setting key bindings", {}, "H4")
        self.bind_all("<Control-o>", lambda e: self.cmd_open())
        self.bind_all("<Control-s>", lambda e: self.cmd_save())
        self.bind_all("<Control-S>", lambda e: self.cmd_save_as())
        self.bind_all("<Control-n>", lambda e: self.cmd_new_bookmark())
        self.bind_all("<Control-N>", lambda e: self.cmd_new_folder())
        self.bind_all("<Delete>", lambda e: self.cmd_delete())
        self.bind_all("<F2>", lambda e: self.cmd_rename())
        self.bind_all("<Control-Up>", lambda e: self.cmd_move_up())
        
        # #region agent log
        import json
        from datetime import datetime
        def debug_log(loc, msg, data=None, hid=None):
            try:
                with open("/home/kei/PythonProject/NeoBookMarkManager/.cursor/debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":hid,"location":loc,"message":msg,"data":data or {},"timestamp":int(datetime.now().timestamp()*1000)}) + "\n")
            except: pass
        # #endregion
        
        debug_log("main_window.py:530", "Key bindings completed, before _refresh_content()", {}, "H4")
        
        # 初期表示
        self._refresh_content()
        debug_log("main_window.py:533", "_refresh_content() completed", {}, "H4")
        debug_log("main_window.py:534", "_build_ui() completed successfully", {}, "H4")
    
    def _add_section_header(self, parent, text: str):
        """セクションヘッダーを追加"""
        # #region agent log
        import json
        from datetime import datetime
        def debug_log(loc, msg, data=None, hid=None):
            try:
                with open("/home/kei/PythonProject/NeoBookMarkManager/.cursor/debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":hid,"location":loc,"message":msg,"data":data or {},"timestamp":int(datetime.now().timestamp()*1000)}) + "\n")
            except: pass
        # #endregion
        
        try:
            debug_log("main_window.py:562", "_add_section_header entry", {"text": text[:30]}, "H4")
            header = ctk.CTkLabel(
                parent,
                text=text,
                font=ctk.CTkFont(family=Fonts.FAMILY, size=Fonts.SIZE_S, weight=Fonts.WEIGHT_BOLD),
                text_color=Colors.TEXT_PRIMARY,
                anchor="w"
            )
            debug_log("main_window.py:572", "CTkLabel created", {}, "H4")
            header.pack(fill="x", padx=10, pady=(12, 4))
            debug_log("main_window.py:574", "header.pack() completed", {}, "H4")
        except Exception as e:
            debug_log("main_window.py:576", "Error in _add_section_header", {"error": str(e)}, "H4")
            raise
    
    def _add_button(self, parent, text: str, command, variant: str = "primary"):
        """ボタンを追加（統一されたスタイル）"""
        # #region agent log
        import json
        from datetime import datetime
        def debug_log(loc, msg, data=None, hid=None):
            try:
                with open("/home/kei/PythonProject/NeoBookMarkManager/.cursor/debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":hid,"location":loc,"message":msg,"data":data or {},"timestamp":int(datetime.now().timestamp()*1000)}) + "\n")
            except: pass
        # #endregion
        
        try:
            debug_log("main_window.py:589", "_add_button entry", {"text": text[:30], "variant": variant}, "H4")
            btn = StyledButton(
                parent,
                text=text,
                command=command,
                variant=variant
            )
            debug_log("main_window.py:597", "StyledButton created", {}, "H4")
            btn.pack(fill="x", padx=10, pady=2)
            debug_log("main_window.py:599", "btn.pack() completed", {}, "H4")
        except Exception as e:
            debug_log("main_window.py:601", "Error in _add_button", {"error": str(e)}, "H4")
            raise
    
    def _add_separator(self, parent):
        """セパレータを追加"""
        # #region agent log
        import json
        from datetime import datetime
        def debug_log(loc, msg, data=None, hid=None):
            try:
                with open("/home/kei/PythonProject/NeoBookMarkManager/.cursor/debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":hid,"location":loc,"message":msg,"data":data or {},"timestamp":int(datetime.now().timestamp()*1000)}) + "\n")
            except: pass
        # #endregion
        
        try:
            debug_log("main_window.py:614", "_add_separator entry", {}, "H4")
            sep = ctk.CTkFrame(parent, height=1, fg_color=Colors.BORDER)
            debug_log("main_window.py:616", "CTkFrame separator created", {}, "H4")
            sep.pack(fill="x", padx=10, pady=6)
            debug_log("main_window.py:618", "sep.pack() completed", {}, "H4")
        except Exception as e:
            debug_log("main_window.py:620", "Error in _add_separator", {"error": str(e)}, "H4")
            raise

    def _toggle_view_mode(self):
        """ビューモードの切り替え"""
        if self.view_mode == "card":
            self.view_mode = "list"
            self.view_toggle_btn.configure(text="Card View")
        else:
            self.view_mode = "card"
            self.view_toggle_btn.configure(text="List View")
        self._refresh_content()
    
    def _toggle_dual_view_mode(self):
        """2画面モードの切り替え"""
        self.dual_view_mode = not self.dual_view_mode
        
        if self.dual_view_mode:
            # 2画面モード: 左右に2つのツリービューを表示
            self.dual_view_btn.configure(text="1画面モード", fg_color=Colors.PRIMARY)
            tree_container = self.folder_tree.master
            
            # 左側ツリービュー
            self.folder_tree.grid(row=1, column=0, sticky="nsew", padx=(Dims.SPACING_S, Dims.SPACING_S // 2), pady=Dims.SPACING_S)
            
            # 右側ツリービュー
            self.folder_tree_right.grid(row=1, column=1, sticky="nsew", padx=(Dims.SPACING_S // 2, Dims.SPACING_S), pady=Dims.SPACING_S)
            
            # カラム設定
            tree_container.grid_columnconfigure(0, weight=1)
            tree_container.grid_columnconfigure(1, weight=1)
            
            # 右側ツリービューを更新
            self.folder_tree_right.refresh(self.root_node)
        else:
            # 1画面モード: 左側のみ表示
            self.dual_view_btn.configure(text="2画面モード", fg_color=Colors.SURFACE)
            tree_container = self.folder_tree.master
            
            # 左側ツリービュー
            self.folder_tree.grid(row=1, column=0, sticky="nsew", padx=Dims.SPACING_S, pady=Dims.SPACING_S)
            
            # 右側ツリービューを非表示
            self.folder_tree_right.grid_remove()
            
            # カラム設定
            tree_container.grid_columnconfigure(0, weight=1)
            tree_container.grid_columnconfigure(1, weight=0)
    
    def _on_folder_selected_right(self, folder_node: Node):
        """右側ツリービューでフォルダが選択されたとき"""
        # 右側のツリービューでは、下側のパネルは更新しない（左側のみ）
        pass
    
    def _on_folder_selected(self, folder_node: Node):
        """フォルダが選択されたとき"""
        self.current_folder = folder_node
        self._refresh_content()
    
    def _on_search(self, query: str):
        """検索クエリが変更されたとき"""
        self._apply_search(query)

    def _refresh_content(self):
        """コンテンツ表示を更新（カードまたはリスト）"""
        # スクロール位置と選択状態を保存
        scroll_position = None
        selected_node_ids = set()
        
        try:
            # スクロール位置を取得
            if hasattr(self.cards_frame, '_parent_canvas'):
                canvas = self.cards_frame._parent_canvas
                if canvas:
                    scroll_position = canvas.canvasy(0)
        except Exception as e:
            self.logger.debug(f"Failed to get scroll position: {e}")
        
        # 選択されているノードのIDを保存（ノードオブジェクトのIDを使用）
        for card in self.selected_cards:
            if card in self.card_to_node:
                node = self.card_to_node[card]
                selected_node_ids.add(id(node))
        
        # 既存のアイテムを削除
        for item in list(self.card_to_node.keys()):
            item.destroy()
        self.card_to_node.clear()
        self.selected_cards.clear()
        self.drag_manager.clear_targets() # Clear old drop targets
        
        # 現在のフォルダのブックマークを表示
        if not self.current_folder:
            return
            
        if self.view_mode == "card":
            self._render_cards()
        else:
            self._render_list()
        
        # スクロール位置と選択状態を復元
        try:
            # スクロール位置を復元
            if scroll_position is not None:
                if hasattr(self.cards_frame, '_parent_canvas'):
                    canvas = self.cards_frame._parent_canvas
                    if canvas:
                        # yview_scrollは'pixels'をサポートしていないため、yview_movetoを使用
                        # scroll_positionはピクセル単位なので、全体の高さに対する比率に変換
                        canvas.update_idletasks()  # レイアウトを更新
                        total_height = canvas.winfo_height()
                        if total_height > 0:
                            ratio = scroll_position / total_height
                            canvas.yview_moveto(max(0, min(1, ratio)))
        except Exception as e:
            self.logger.debug(f"Failed to restore scroll position: {e}")
        
        # 選択状態を復元
        if selected_node_ids:
            for card, node in self.card_to_node.items():
                if id(node) in selected_node_ids:
                    self.selected_cards.add(card)
                    if hasattr(card, 'set_selected'):
                        card.set_selected(True)

    def _render_cards(self):
        """カードビューで表示 - Premium Design"""
        row = 0
        col = 0
        max_cols = 3
        
        for child in self.current_folder.children:
            if child.type == "bookmark":
                card = BookmarkCard(
                    self.cards_frame,
                    child,
                    on_click=self._on_card_click,
                    on_double_click=self._on_card_double_click,
                    width=250,
                    height=100
                )
                card.grid(row=row, column=col, padx=12, pady=12, sticky="nsew")
                self.card_to_node[card] = child
                
                # Register drag events
                self._bind_drag(card, child)
                
                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1
        
        for i in range(max_cols):
            self.cards_frame.grid_columnconfigure(i, weight=1, uniform="cards")
    
    def _reorder_cards(self):
        """カードの位置のみ更新（再作成しない）"""
        if not self.current_folder:
            return
        
        # ノードからカードへのマッピングを作成
        node_to_card = {node: card for card, node in self.card_to_node.items()}
        
        if self.view_mode == "card":
            row = 0
            col = 0
            max_cols = 3
            
            for child in self.current_folder.children:
                if child.type == "bookmark" and child in node_to_card:
                    card = node_to_card[child]
                    card.grid(row=row, column=col, padx=12, pady=12, sticky="nsew")
                    col += 1
                    if col >= max_cols:
                        col = 0
                        row += 1
        else:
            for i, child in enumerate(self.current_folder.children):
                if child.type == "bookmark" and child in node_to_card:
                    card = node_to_card[child]
                    card.grid(row=i, column=0, padx=12, pady=4, sticky="ew")

    def _render_list(self):
        """リストビューで表示 - Premium Design"""
        self.cards_frame.grid_columnconfigure(0, weight=1)
        for i in range(1, 4):
            self.cards_frame.grid_columnconfigure(i, weight=0)

        for i, child in enumerate(self.current_folder.children):
            if child.type == "bookmark":
                row_widget = BookmarkRow(
                    self.cards_frame,
                    child,
                    on_click=self._on_card_click,
                    on_double_click=self._on_card_double_click
                )
                row_widget.grid(row=i, column=0, padx=12, pady=4, sticky="ew")
                self.card_to_node[row_widget] = child
                
                # Register drag events
                self._bind_drag(row_widget, child)

    def _bind_drag(self, widget, node):
        """Bind drag start/motion/end events to DragManager (親ウィジェットと全子ウィジェット)"""
        def get_all_children(w):
            """再帰的に全ての子ウィジェットを取得"""
            children = []
            try:
                for child in w.winfo_children():
                    children.append(child)
                    children.extend(get_all_children(child))
            except Exception as e:
                # ウィジェットが破棄されている場合など
                self.logger.debug(f"Failed to get children of widget: {e}")
            return children
        
        # 親ウィジェットと全子ウィジェットのリスト
        all_widgets = [widget] + get_all_children(widget)
        
        # 各ウィジェットにドラッグイベントをbind
        for w in all_widgets:
            # Start drag wrapper - 子ウィジェットからでも親カード/行をsource_widgetとして使用
            def start_drag_wrapper(event, parent_widget=widget, child_widget=w):
                # 子ウィジェットからドラッグ開始した場合、offsetを親ウィジェット座標系に変換
                if child_widget != parent_widget:
                    try:
                        # 子ウィジェットの座標を親ウィジェットの座標に変換
                        child_x = event.x
                        child_y = event.y
                        # 子ウィジェットの親ウィジェット相対座標を取得
                        child_root_x = child_widget.winfo_rootx()
                        child_root_y = child_widget.winfo_rooty()
                        parent_root_x = parent_widget.winfo_rootx()
                        parent_root_y = parent_widget.winfo_rooty()
                        # 親ウィジェット相対座標に変換
                        parent_x = child_x + (child_root_x - parent_root_x)
                        parent_y = child_y + (child_root_y - parent_root_y)
                        # イベントオブジェクトを作成
                        class EventProxy:
                            def __init__(self, orig, x, y):
                                self.x = x
                                self.y = y
                                self.x_root = orig.x_root
                                self.y_root = orig.y_root
                        proxy_event = EventProxy(event, parent_x, parent_y)
                        self.drag_manager.start_drag(parent_widget, node, proxy_event)
                    except Exception as e:
                        # 変換に失敗した場合は元のイベントを使用
                        self.logger.debug(f"Failed to convert widget coordinates, using original event: {e}")
                        self.drag_manager.start_drag(parent_widget, node, event)
                else:
                    # 親ウィジェットから開始した場合はそのまま
                    self.drag_manager.start_drag(parent_widget, node, event)
            
            # Motion wrapper - x_root/y_rootはそのまま使える
            def motion_wrapper(event):
                self.drag_manager.update_drag(event)
            
            # Bind events
            w.bind("<Button-1>", start_drag_wrapper, add="+")
            w.bind("<B1-Motion>", motion_wrapper, add="+")
            # ButtonRelease-1はグローバルで処理するので、ここではbindしない
        
        # Also register as drop target (親ウィジェットのみ)
        self.drag_manager.register_target(widget, node)

    def _on_drop_item(self, source_node, target_node):
        """Handle drop event from DragManager"""
        if not self.current_folder:
            return
            
        if source_node == target_node:
            return

        children = self.current_folder.children
        if source_node in children and target_node in children:
            old_idx = children.index(source_node)
            new_idx = children.index(target_node)
            
            children.remove(source_node)
            children.insert(new_idx, source_node)
            
            self.logger.info(f"Interactive Drop: Moved '{source_node.title}' from {old_idx} to {new_idx}")
            
            # 位置のみ更新（全体再構築しない）
            self._reorder_cards()
            
            # ツリービューも更新
            if hasattr(self.folder_tree, '_reorder_tree_items'):
                self.folder_tree._reorder_tree_items(self.current_folder)
    
    def _on_card_click(self, node: Node, event=None):
        """カードがクリックされたとき"""
        # ブックマークがツリービューからクリックされた場合、親フォルダを表示
        if node.type == "bookmark" and node.parent:
            parent_folder = node.parent
            if parent_folder != self.current_folder:
                self.current_folder = parent_folder
                self._refresh_content()
        
        # 対応するカードを探す
        card = None
        for c, n in self.card_to_node.items():
            if n is node:
                card = c
                break
        
        if not card:
            # カードがない場合は詳細パネルのみ更新
            self._update_detail_panel(node)
            return
        
        # イベントからキー状態を取得（Ctrl/Cmdキーの判定）
        # event.state のビット: 0x0004 = Control (Windows/Linux), 0x0001 = Shift, 0x0008 = Alt
        # macOSでは Command キーは通常 0x0004 として扱われる（tkinterの実装による）
        is_ctrl_or_cmd = False
        if event and hasattr(event, 'state'):
            # Control キー（Windows/Linux）または Command キー（macOS）
            is_ctrl_or_cmd = bool(event.state & 0x0004)
        
        # 選択状態を切り替え（Ctrl/Cmdキーで複数選択）
        if card in self.selected_cards:
            # 既に選択されている場合、Ctrl/Cmdキーが押されていれば選択解除
            if is_ctrl_or_cmd:
                self.selected_cards.remove(card)
                card.set_selected(False)
            else:
                # Ctrl/Cmdキーが押されていない場合は、既存の選択をクリアして再選択
                for c in self.selected_cards:
                    c.set_selected(False)
                self.selected_cards.clear()
                self.selected_cards.add(card)
                card.set_selected(True)
        else:
            # 選択されていない場合
            if not is_ctrl_or_cmd:
                # Ctrl/Cmdキーが押されていない場合は、既存の選択をクリア
                for c in self.selected_cards:
                    c.set_selected(False)
                self.selected_cards.clear()
            
            self.selected_cards.add(card)
            card.set_selected(True)
        
        # 詳細パネルを更新
        self._update_detail_panel(node)
    
    def _on_card_double_click(self, node: Node):
        """カードがダブルクリックされたとき"""
        if node.url:
            import webbrowser
            try:
                webbrowser.open(node.url)
            except Exception as e:
                self.logger.error(f"Failed to open URL: {e}")
    
    
    def _update_detail_panel(self, node: Optional[Node]):
        """詳細パネルを更新"""
        if not node:
            self.detail_panel.update_node(None)
            return
        
        preview_data = None
        if node.type == "bookmark" and node.url:
            if node.url in self.preview_cache:
                preview_data = self.preview_cache[node.url]
            else:
                # プレビューを非同期で取得
                self.detail_panel.update_node(node, {"title": "Loading preview...", "description": ""})
                threading.Thread(target=self._fetch_preview_worker, args=(node.url,), daemon=True).start()
                return
        
        self.detail_panel.update_node(node, preview_data)
    
    def _fetch_preview_worker(self, url: str):
        """プレビュー情報を非同期で取得"""
        proxy_info = self._get_proxies_for_requests()
        fetch_preview(url, self.ui_queue, proxy_info)
    
    def _process_ui_queue(self):
        """UIキューを処理（スレッドセーフな更新）"""
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
                        self.traffic_label.configure(text=f"Traffic: Sent {sent_kb:.2f} KB | Received {recv_kb:.2f} KB")
                elif task_type == 'proxy_check_success':
                    dialog = data
                    if dialog.winfo_exists():
                        dialog.destroy()
                    messagebox.showinfo("Proxy Check", "プロキシ接続は正常です。")
                elif task_type == 'proxy_check_failure':
                    dialog, error_msg = data
                    if dialog.winfo_exists():
                        dialog.destroy()
                    messagebox.showerror("Proxy Check", f"プロキシ接続に失敗しました。\nconfig.iniの設定を確認してください。\n\nエラー: {error_msg}")
                elif task_type == 'preview':
                    url, preview_data = data
                    self.preview_cache[url] = preview_data
                    # 現在選択中のノードのURLと一致する場合、詳細パネルを更新
                    selected_nodes = [self.card_to_node[card] for card in self.selected_cards if card in self.card_to_node]
                    if selected_nodes and len(selected_nodes) == 1:
                        node = selected_nodes[0]
                        if node and node.url == url:
                            self._update_detail_panel(node)
                elif task_type == 'titlefix_progress':
                    processed, total = data
                    if self._titlefix_dialog and self._titlefix_dialog.winfo_exists():
                        try:
                            # CTkProgressBarは0.0から1.0の範囲で値を設定
                            progress_value = processed / total if total > 0 else 0.0
                            self._titlefix_var.set(progress_value)
                            self._titlefix_label.configure(text=f"{processed} / {total}")
                        except tk.TclError:
                            pass
                elif task_type == 'titlefix_done':
                    if self._titlefix_dialog and self._titlefix_dialog.winfo_exists():
                        try:
                            self._titlefix_dialog.destroy()
                        except tk.TclError:
                            pass
                    self._titlefix_dialog = None
                    self._refresh_content()
                    self.folder_tree.refresh(self.root_node)
                    messagebox.showinfo("Fix Titles", "処理が完了しました。")
                elif task_type == 'load_progress':
                    current, total, message = data
                    if self._load_dialog and self._load_dialog.winfo_exists():
                        try:
                            # CTkProgressBarは0.0から1.0の範囲で値を設定
                            progress_value = current / total if total > 0 else 0.0
                            self._load_var.set(progress_value)
                            self._load_label.configure(text=message or f"{current} / {total}")
                            # UIを強制的に更新
                            self._load_dialog.update_idletasks()
                        except tk.TclError:
                            pass
                elif task_type == 'load_done':
                    # データを受け取る（検索インデックスも含む）
                    if len(data) == 5:
                        root, rules, rules_path, path, search_index = data
                    else:
                        # 後方互換性のため
                        root, rules, rules_path, path = data
                        search_index = None
                    
                    # プログレスバーを閉じる前にUIを更新
                    if not self._load_cancelled:
                        # データを設定
                        self.root_node = root
                        self.rules = rules or self._default_rules()
                        self.rules_path = rules_path
                        self.current_file = path
                        self.current_folder = root
                        
                        # 検索インデックスを設定（既に構築済み）
                        if search_index is not None:
                            self.search_index = search_index
                        else:
                            # フォールバック：検索インデックスが無い場合は構築
                            self._build_search_index()
                        
                        # タイトルを更新
                        self.title(f"Bookmark Studio — {os.path.basename(path)}")
                        
                        # フォルダツリーとコンテンツを更新
                        self.folder_tree.refresh(root)
                        self._refresh_content()
                        
                        # UIを強制的に更新（プログレスバーを閉じる前に）
                        self.update_idletasks()
                    
                    # プログレスバーを閉じる（UIは既に更新済み）
                    if self._load_dialog and self._load_dialog.winfo_exists():
                        try:
                            self._load_dialog.destroy()
                        except tk.TclError:
                            pass
                    self._load_dialog = None
                elif task_type == 'load_error':
                    error_msg = data
                    if self._load_dialog and self._load_dialog.winfo_exists():
                        try:
                            self._load_dialog.destroy()
                        except tk.TclError:
                            pass
                    self._load_dialog = None
                    messagebox.showerror("Error", f"Failed to load bookmarks:\n{error_msg}")
        except queue.Empty:
            pass
        finally:
            self.after(100, self._process_ui_queue)
    
    def _get_proxies_for_requests(self):
        """requestsライブラリ用にプロキシ設定を返す"""
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
    
    def _build_search_index(self):
        """検索インデックスを構築"""
        self.search_index = {}
        
        def index_node(node: Node):
            if node.type == "bookmark":
                full_text = f"{(node.title or '').lower()} {(node.url or '').lower()}"
                words = set(re.split(r'\W+', full_text))
                for word in words:
                    if not word:
                        continue
                    if word not in self.search_index:
                        self.search_index[word] = set()
                    self.search_index[word].add(node)
            
            for child in node.children:
                index_node(child)
        
        index_node(self.root_node)
    
    def _apply_search(self, query: str):
        """検索を適用（完全一致方式に変更して性能向上）"""
        if not query:
            self._refresh_content()
            return
        
        query_lower = query.lower()
        search_words = [word for word in re.split(r'\W+', query_lower) if word]
        
        if not search_words:
            self._refresh_content()
            return
        
        # 完全一致方式：検索語がインデックスのキーに完全一致する場合のみマッチ
        # これにより全走査を避け、O(1)のルックアップが可能
        matching_nodes = None
        for word in search_words:
            found_nodes = self.search_index.get(word, set())
            if matching_nodes is None:
                matching_nodes = found_nodes.copy()
            else:
                matching_nodes.intersection_update(found_nodes)
        
        # マッチするノードを含むフォルダを表示
        if matching_nodes:
            # 最初のマッチノードの親フォルダを表示
            first_node = next(iter(matching_nodes))
            if first_node.parent:
                self.current_folder = first_node.parent
                self.folder_tree._select_folder(first_node.parent)
                self._refresh_content()
    
    # 以下、既存のコマンドメソッドを移植（簡略版）
    # 完全な実装には、元のファイルからすべてのメソッドを移植する必要があります
    
    def cmd_open(self):
        """ブックマークファイルを開く"""
        path = filedialog.askopenfilename(
            title="Open Chrome Bookmarks HTML",
            filetypes=[("HTML files", "*.html;*.htm"), ("All files", "*.*")]
        )
        if not path:
            return
        
        # ファイルサイズを取得してプログレス表示用の最大値を設定
        try:
            file_size = os.path.getsize(path)
            self._show_load_progress(file_size)
            self._load_cancelled = False
            threading.Thread(target=self._load_bookmarks_worker, args=(path,), daemon=True).start()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to get file info:\n{e}")
    
    def _show_load_progress(self, file_size: int):
        """HTML読み込みの進捗ダイアログ"""
        if self._load_dialog and self._load_dialog.winfo_exists():
            return
        
        d = ctk.CTkToplevel(self)
        d.title("Loading Bookmarks")
        d.geometry("400x140")
        d.transient(self)
        d.grab_set()
        d.resizable(False, False)
        self._load_dialog = d
        self._load_cancelled = False
        
        file_size_mb = file_size / (1024 * 1024)
        ctk.CTkLabel(d, text=f"ブックマークファイルを読み込み中... ({file_size_mb:.2f} MB)").pack(pady=10)
        
        self._load_var = ctk.DoubleVar(value=0.0)
        pb = ctk.CTkProgressBar(d, variable=self._load_var)
        pb.pack(fill="x", padx=12, pady=6)
        
        self._load_label = ctk.CTkLabel(d, text="読み込み中...")
        self._load_label.pack()
        
        def on_cancel():
            self._load_cancelled = True
            try:
                d.destroy()
            except tk.TclError:
                pass
        
        ctk.CTkButton(d, text="Cancel", command=on_cancel).pack(pady=10)
        d.protocol("WM_DELETE_WINDOW", on_cancel)
    
    def _load_bookmarks_worker(self, path: str):
        """ブックマーク読み込みを別スレッドで実行"""
        import time
        import threading
        
        def update_progress_with_delay(progress, message, delay=0.05):
            """進捗を更新し、UI更新の機会を与える"""
            if self._load_cancelled:
                return False
            self.ui_queue.put(('load_progress', (progress, 100, message)))
            time.sleep(delay)
            return not self._load_cancelled
        
        try:
            # 開始（5%）
            if not update_progress_with_delay(5, "準備中..."):
                return
            
            # ファイルサイズを取得
            file_size = os.path.getsize(path)
            chunk_size = max(1024 * 1024, file_size // 20)  # 20チャンクに分割
            
            # ファイル読み込み（チャンクごとに進捗更新）
            if not update_progress_with_delay(10, "ファイルを読み込み中..."):
                return
            
            data_parts = []
            read_bytes = 0
            with open(path, 'r', encoding='utf-8') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    data_parts.append(chunk)
                    read_bytes += len(chunk.encode('utf-8'))
                    # 進捗を更新（10%から30%まで）
                    progress = 10 + int((read_bytes / file_size) * 20)
                    if not update_progress_with_delay(progress, f"ファイルを読み込み中... ({read_bytes // 1024} KB / {file_size // 1024} KB)", 0.01):
                        return
            
            data = ''.join(data_parts)
            
            # ファイル読み込み完了
            if not update_progress_with_delay(30, "ファイル読み込み完了"):
                return
            
            # HTMLパース開始
            if not update_progress_with_delay(35, "HTML構造を解析中..."):
                return
            
            from core.model import NetscapeBookmarkParser
            parser = NetscapeBookmarkParser()
            
            # パース処理中に進捗を更新（アニメーション効果）
            parse_progress = 35
            parse_dots = 0
            parse_messages = [
                "HTML構造を解析中...",
                "ブックマークデータを処理中...",
                "フォルダ階層を構築中...",
                "メタデータを読み込み中..."
            ]
            parse_msg_index = 0
            
            # パース処理を別スレッドで実行し、進捗を更新
            parse_done = threading.Event()
            parse_error = [None]
            
            def do_parse():
                try:
                    parser.feed(data)
                    parse_done.set()
                except Exception as e:
                    parse_error[0] = e
                    parse_done.set()
            
            parse_thread = threading.Thread(target=do_parse, daemon=True)
            parse_thread.start()
            
            # パース処理中、定期的に進捗を更新
            while not parse_done.is_set() and not self._load_cancelled:
                parse_progress = min(parse_progress + 2, 75)  # 35%から75%まで
                msg = parse_messages[parse_msg_index % len(parse_messages)]
                dots = "." * ((parse_dots % 3) + 1)
                if not update_progress_with_delay(parse_progress, f"{msg}{dots}", 0.2):
                    return
                parse_msg_index += 1
                parse_dots += 1
            
            # パース処理完了を待つ
            parse_thread.join(timeout=1.0)
            
            if parse_error[0]:
                raise parse_error[0]
            
            root = parser.root
            
            # HTMLパース完了
            if not update_progress_with_delay(80, "HTML解析完了"):
                return
            
            # ルールファイル読み込み
            if not update_progress_with_delay(85, "ルールファイルを確認中..."):
                return
            
            sidecar = os.path.splitext(path)[0] + '.bookmark_rules.json'
            rules = None
            rules_path = None
            if os.path.exists(sidecar):
                if not update_progress_with_delay(90, "ルールファイルを読み込み中..."):
                    return
                try:
                    with open(sidecar, 'r', encoding='utf-8') as rf:
                        rules = json.load(rf)
                        rules_path = sidecar
                except Exception as e:
                    self.logger.warning(f"Failed to load rules file '{sidecar}': {e}")
                    rules = None
            
            # 検索インデックス構築（プログレスバー表示中に完了させる）
            if not update_progress_with_delay(90, "検索インデックスを構築中..."):
                return
            
            # 検索インデックスを構築（重い処理なので進捗を更新しながら）
            search_index = {}
            total_nodes = 0
            processed_nodes = 0
            
            def count_nodes(node):
                nonlocal total_nodes
                total_nodes += 1
                for child in node.children:
                    count_nodes(child)
            
            count_nodes(root)
            
            def build_search_index(node):
                nonlocal processed_nodes
                if node.type == "bookmark":
                    full_text = f"{(node.title or '').lower()} {(node.url or '').lower()}"
                    words = set(re.split(r'\W+', full_text))
                    for word in words:
                        if not word:
                            continue
                        if word not in search_index:
                            search_index[word] = set()
                        search_index[word].add(node)
                
                processed_nodes += 1
                # 100ノードごとに進捗を更新
                if processed_nodes % 100 == 0 or processed_nodes == total_nodes:
                    progress = 90 + int((processed_nodes / total_nodes) * 8)  # 90%から98%まで
                    msg = f"検索インデックスを構築中... ({processed_nodes} / {total_nodes})"
                    if not update_progress_with_delay(progress, msg, 0.01):
                        return False
                
                for child in node.children:
                    if not build_search_index(child):
                        return False
                return True
            
            if not build_search_index(root):
                return
            
            # UI更新準備（プログレスバー表示中に完了）
            if not update_progress_with_delay(98, "UIを準備中..."):
                return
            
            # 完了
            if not update_progress_with_delay(100, "完了"):
                return
            
            time.sleep(0.1)  # UI更新の機会を与える
            if not self._load_cancelled:
                # 検索インデックスも含めて完了データを送信
                self.ui_queue.put(('load_done', (root, rules or {}, rules_path, path, search_index)))
        except Exception as e:
            if not self._load_cancelled:
                self.ui_queue.put(('load_error', str(e)))
    
    def cmd_save(self):
        """保存"""
        if not self.current_file:
            return self.cmd_save_as()
        try:
            sp = save_bookmarks(self.current_file, self.root_node, self.rules)
            if sp:
                self.rules_path = sp
            messagebox.showinfo("Saved", "Saved successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save:\n{e}")
    
    def cmd_save_as(self):
        """名前を付けて保存"""
        if not self.root_node:
            return
        path = filedialog.asksaveasfilename(
            title="Export Chrome HTML",
            defaultextension=".html",
            filetypes=[("HTML files", "*.html;*.htm")]
        )
        if not path:
            return
        try:
            sp = save_bookmarks(path, self.root_node, self.rules)
            messagebox.showinfo("Exported", "Export completed.")
            self.rules_path = sp
            self.current_file = path
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export:\n{e}")
    
    def cmd_new_folder(self):
        """新しいフォルダを作成"""
        if not self.current_folder:
            return
        name = simpledialog.askstring("New Folder", "Folder name:")
        if name is None:
            return
        n = Node("folder", title=name)
        self.current_folder.append(n)
        self.folder_tree.refresh(self.root_node)
        self._refresh_content()
    
    def cmd_new_bookmark(self):
        """新しいブックマークを作成"""
        if not self.current_folder:
            return
        title = simpledialog.askstring("New Bookmark", "Title:")
        if title is None:
            return
        url = simpledialog.askstring("New Bookmark", "URL:")
        if url is None:
            return
        if url and not is_valid_url(url):
            messagebox.showerror("Error", "無効なURL形式です。http:// または https:// で始まるURLを入力してください。")
            return
        n = Node("bookmark", title=title, url=url)
        self.current_folder.append(n)
        self._build_search_index()
        self._refresh_content()
    
    def cmd_rename(self):
        """選択したアイテムの名前を変更"""
        selected_nodes = [self.card_to_node[card] for card in self.selected_cards if card in self.card_to_node]
        if not selected_nodes or len(selected_nodes) > 1:
            messagebox.showinfo("Rename", "1つのアイテムを選択してください。")
            return
        
        node = selected_nodes[0]
        new_name = simpledialog.askstring("Rename", "New name:", initialvalue=node.title or "")
        if new_name is None:
            return
        node.title = new_name
        self._build_search_index()
        self._refresh_content()
        self.folder_tree.refresh(self.root_node)
    
    def cmd_edit_url(self):
        """選択したブックマークのURLを編集"""
        selected_nodes = [self.card_to_node[card] for card in self.selected_cards if card in self.card_to_node]
        if not selected_nodes or len(selected_nodes) > 1:
            messagebox.showinfo("Edit URL", "1つのブックマークを選択してください。")
            return
        
        node = selected_nodes[0]
        if node.type != "bookmark":
            messagebox.showinfo("Edit URL", "ブックマークを選択してください。")
            return
        
        new_url = simpledialog.askstring("Edit URL", "New URL:", initialvalue=node.url or "")
        if new_url is None:
            return
        if new_url and not is_valid_url(new_url):
            messagebox.showerror("Error", "無効なURL形式です。http:// または https:// で始まるURLを入力してください。")
            return
        node.url = new_url
        self._build_search_index()
        self._refresh_content()
    
    def cmd_move_to_folder(self):
        """選択したアイテムをフォルダに移動"""
        selected_nodes = [self.card_to_node[card] for card in self.selected_cards if card in self.card_to_node]
        if not selected_nodes:
            messagebox.showinfo("Move to Folder", "移動するアイテムを選択してください。")
            return
        
        # フォルダ選択ダイアログを表示
        dialog = FolderSelectDialog(self, self.root_node, exclude_nodes=selected_nodes)
        self.wait_window(dialog)
        
        target_folder = dialog.result
        if not target_folder:
            # ユーザーがキャンセルした場合
            return
        
        # 選択したアイテムを移動
        moved_count = 0
        for node in selected_nodes:
            # 自分自身や親フォルダへの移動はスキップ
            if node == target_folder or (node.parent and node.parent == target_folder):
                continue
            
            # 移動先が移動対象の子孫フォルダでないことを確認
            is_descendant = False
            current = target_folder.parent
            while current:
                if current == node:
                    is_descendant = True
                    break
                current = current.parent
            
            if is_descendant:
                continue
            
            # 移動実行
            if node.parent:
                node.parent.children.remove(node)
            target_folder.append(node)
            moved_count += 1
        
        if moved_count > 0:
            self._build_search_index()
            self._refresh_content()
            self.folder_tree.refresh(self.root_node)
            messagebox.showinfo("Move to Folder", f"{moved_count}個のアイテムを移動しました。")
        else:
            messagebox.showinfo("Move to Folder", "移動できるアイテムがありませんでした。")
    
    def cmd_move_up(self):
        """選択したアイテムを一つ上の階層に移動"""
        selected_nodes = [self.card_to_node[card] for card in self.selected_cards if card in self.card_to_node]
        if not selected_nodes:
            messagebox.showinfo("Move Up", "移動するアイテムを選択してください。")
            return
        
        for node in selected_nodes:
            if not node.parent or not node.parent.parent:
                messagebox.showwarning("Move Up", "トップレベルのアイテムはこれ以上上に移動できません。")
                return
        
        new_parent = selected_nodes[0].parent.parent
        for node in selected_nodes:
            if node.parent:
                node.parent.children.remove(node)
            new_parent.append(node)
        
        self._refresh_content()
        self.folder_tree.refresh(self.root_node)
    
    def cmd_delete(self):
        """選択したアイテムを削除"""
        selected_nodes = [self.card_to_node[card] for card in self.selected_cards if card in self.card_to_node]
        if not selected_nodes:
            return
        
        if not messagebox.askyesno("Delete", f"Delete {len(selected_nodes)} selected item(s)?"):
            return
        
        for node in selected_nodes:
            if node.parent:
                node.parent.children.remove(node)
        
        self._build_search_index()
        self._refresh_content()
        self.folder_tree.refresh(self.root_node)
    
    def cmd_sort(self, mode: str = "title"):
        """ソート"""
        if not self.current_folder:
            return
        
        def sort_key(n: Node):
            # フォルダを常に先頭に（0: folder, 1: bookmark）
            type_score = 0 if n.type == "folder" else 1
            
            if mode == "domain" and n.type == "bookmark":
                return (type_score, self._domain_of(n.url), (n.title or "").lower())
            return (type_score, (n.title or "").lower())
        
        self.current_folder.children.sort(key=sort_key)
        self._refresh_content()
    
    def cmd_dedupe(self):
        """重複削除"""
        if not self.current_folder:
            return
        
        seen, new_children, removed = set(), [], 0
        for ch in self.current_folder.children:
            if ch.type == "bookmark":
                key = (ch.url or "").strip().rstrip("/")
                if key and key in seen:
                    removed += 1
                    continue
                if key:
                    seen.add(key)
            new_children.append(ch)
        
        self.current_folder.children = new_children
        self._refresh_content()
        messagebox.showinfo("Deduplicate", f"Removed {removed} duplicated bookmark(s).")
    
    def cmd_merge_folders(self):
        """重複フォルダを統合"""
        if not self.current_folder:
            return
        
        folders_by_name = {}
        nodes_to_remove = []
        merged_count = 0
        
        for child in list(self.current_folder.children):
            if child.type == 'folder':
                key = child.title.lower()
                if key in folders_by_name:
                    primary_folder = folders_by_name[key]
                    for sub_child in list(child.children):
                        child.children.remove(sub_child)
                        primary_folder.append(sub_child)
                    nodes_to_remove.append(child)
                    merged_count += 1
                else:
                    folders_by_name[key] = child
        
        if nodes_to_remove:
            for node_to_remove in nodes_to_remove:
                self.current_folder.children.remove(node_to_remove)
            self._refresh_content()
            self.folder_tree.refresh(self.root_node)
            messagebox.showinfo("Merge Folders", f"{merged_count}個の重複フォルダを統合しました。")
        else:
            messagebox.showinfo("Merge Folders", "重複する名前のフォルダは見つかりませんでした。")
    
    def _domain_of(self, url: str) -> str:
        """URLからドメインを取得"""
        try:
            return urlparse(url).netloc.lower()
        except Exception as e:
            self.logger.debug(f"Failed to parse URL domain from '{url}': {e}")
            return ""
    
    def _default_rules(self):
        """デフォルトの分類ルール"""
        return {
            "Google": {"domains": ["google.com", "gmail.com", "drive.google.com"], "keywords": ["google", "gmail", "drive"]},
            "YouTube": {"domains": ["youtube.com", "youtu.be"], "keywords": ["youtube", "yt"]},
            "News": {"domains": ["cnn.com", "bbc.co.uk", "nytimes.com", "news.yahoo"], "keywords": ["news", "article"]},
            "Social": {"domains": ["twitter.com", "x.com", "facebook.com", "instagram.com", "linkedin.com"], "keywords": ["twitter", "facebook", "instagram", "linkedin"]},
            "Dev": {"domains": ["github.com", "gitlab.com", "stackoverflow.com", "pypi.org", "readthedocs"], "keywords": ["github", "docs", "api", "stack overflow"]},
            "Shopping": {"domains": ["amazon.", "rakuten.", "taobao.", "jd.com"], "keywords": ["cart", "buy", "store"]},
        }
    
    def _match_rule(self, url: str, title: str, rule: dict) -> bool:
        """ルールにマッチするかチェック"""
        u = (url or "").lower()
        t = (title or "").lower()
        for d in rule.get("domains", []):
            if d in u:
                return True
        for k in rule.get("keywords", []):
            if k in u or k in t:
                return True
        return False
    
    def _get_classification_plan(self, bookmarks_to_check: List[Node]) -> Dict[str, List[Node]]:
        """分類プランを取得"""
        plan = {}
        for bm in bookmarks_to_check:
            if bm.type != 'bookmark':
                continue
            for folder_name, rule in self.rules.items():
                if self._match_rule(bm.url, bm.title, rule):
                    current_parent = bm.parent
                    if current_parent and current_parent.title == folder_name:
                        continue
                    if folder_name not in plan:
                        plan[folder_name] = []
                    plan[folder_name].append(bm)
                    break
        return plan
    
    def _find_common_parent(self, nodes):
        """共通の親フォルダを探す"""
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
    
    def _execute_classification_plan(self, plan: Dict[str, List[Node]], base_node: Node):
        """分類プランを実行"""
        if not plan:
            return
        target_folders_parent = base_node if base_node else self.root_node
        
        existing_folders_map = {
            ch.title.lower(): ch for ch in target_folders_parent.children if ch.type == "folder"
        }
        
        for folder_name, bookmarks in plan.items():
            target_folder = existing_folders_map.get(folder_name.lower())
            if not target_folder:
                target_folder = Node("folder", folder_name)
                target_folders_parent.append(target_folder)
                existing_folders_map[folder_name.lower()] = target_folder
            
            for bm in bookmarks:
                if bm.parent and bm in bm.parent.children:
                    bm.parent.children.remove(bm)
                target_folder.append(bm)
        
        self._build_search_index()
        self._refresh_content()
        self.folder_tree.refresh(self.root_node)
        messagebox.showinfo("Auto Classify", f"Moved {sum(len(v) for v in plan.values())} bookmarks.")
    
    def cmd_show_classify_preview(self):
        """分類プレビューを表示"""
        # 現在のフォルダのブックマークを取得
        bookmarks_to_classify = [ch for ch in self.current_folder.children if ch.type == 'bookmark']
        
        if not bookmarks_to_classify:
            if not messagebox.askyesno("Auto Classify", "No items selected. Classify ALL bookmarks?"):
                return
            # すべてのブックマークを収集
            bookmarks_to_classify = []
            def collect_all(node):
                for child in node.children:
                    if child.type == 'bookmark':
                        bookmarks_to_classify.append(child)
                    elif child.type == 'folder':
                        collect_all(child)
            collect_all(self.root_node)
        
        plan = self._get_classification_plan(list(set(bookmarks_to_classify)))
        if not plan:
            messagebox.showinfo("Auto Classify", "No bookmarks to move based on current rules.")
            return
        
        base_node = self._find_common_parent(bookmarks_to_classify)
        # プレビューダイアログ（簡易版）
        preview_text = "\n".join([f"{folder}: {len(bms)} bookmarks" for folder, bms in plan.items()])
        if messagebox.askyesno("Classification Preview", f"Apply classification?\n\n{preview_text}"):
            self._execute_classification_plan(plan, base_node)
    
    def cmd_edit_rules(self):
        """分類ルールを編集"""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Edit Classify Rules (JSON)")
        dialog.geometry("720x520")
        
        text_widget = tk.Text(dialog, wrap="none")
        text_widget.pack(fill="both", expand=True, padx=5, pady=5)
        
        try:
            pretty = json.dumps(self.rules, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to serialize rules to JSON: {e}", exc_info=True)
            pretty = "{}"
        text_widget.insert("1.0", pretty)
        
        btn_frame = ctk.CTkFrame(dialog)
        btn_frame.pack(fill="x", padx=5, pady=5)
        
        def save_rules():
            try:
                data = json.loads(text_widget.get("1.0", "end-1c"))
                self.rules = data
                if self.rules_path:
                    with open(self.rules_path, "w", encoding="utf-8") as wf:
                        json.dump(self.rules, wf, ensure_ascii=False, indent=2)
                messagebox.showinfo("Rules", "Saved.", parent=dialog)
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("Rules", f"Invalid JSON:\n{e}", parent=dialog)
        
        ctk.CTkButton(btn_frame, text="Save", command=save_rules).pack(side="right", padx=5)
        ctk.CTkButton(btn_frame, text="Cancel", command=dialog.destroy).pack(side="right", padx=5)
    
    def cmd_smart_classify(self):
        """AI分類を実行"""
        self.progress_history = []
        self._smart_cancelled = False
        self.last_classification_prompts = []
        
        # 現在のフォルダのブックマークを取得
        bookmarks_to_process = [ch for ch in self.current_folder.children if ch.type == 'bookmark' and ch.url]
        
        if not bookmarks_to_process:
            # すべてのブックマークを収集
            def collect(node):
                result = []
                if not node:
                    return result
                if node.type == 'bookmark' and node.url:
                    result.append(node)
                elif node.type == 'folder':
                    for ch in node.children:
                        result.extend(collect(ch))
                return result
            bookmarks_to_process = collect(self.root_node)
        
        bookmarks_to_process = list({id(b): b for b in bookmarks_to_process}.values())
        self.last_classified_bookmarks = bookmarks_to_process
        
        if not bookmarks_to_process:
            messagebox.showinfo("Smart Classify", "対象ブックマークがありません。")
            return
        
        total_to_process = min(len(bookmarks_to_process), self.max_smart_items)
        self._show_smart_progress(total_to_process)
        threading.Thread(target=self._run_ai_classification_worker, args=(bookmarks_to_process, None), daemon=True).start()
    
    def _run_ai_classification_worker(self, bookmarks, additional_prompt):
        """AI分類を別スレッドで実行"""
        try:
            bookmark_nodes = [BookmarkNode(title=b.title, url=b.url) for b in bookmarks]
            classifier = AIBookmarkClassifier(logger=self.logger)
            
            def progress_callback(processed, total, sent, received):
                if not self._smart_cancelled:
                    self.ui_queue.put(('progress_update', (processed, total, sent, received)))
            
            classifier.set_progress_callback(progress_callback)
            priority_terms = self.config_manager.get_priority_terms()
            result = classifier.classify_bookmarks(
                bookmarks=bookmark_nodes,
                priority_terms=priority_terms,
                max_items=self.max_smart_items,
                additional_prompt=additional_prompt
            )
            if not self._smart_cancelled:
                self.ui_queue.put(('smart_classify_result', result))
        except Exception as e:
            self.logger.error("AI Classification worker failed: %s", str(e), exc_info=True)
            if not self._smart_cancelled:
                self.ui_queue.put(('error', f"Smart Classify failed: {e}"))
    
    def _show_smart_progress(self, total):
        """AI分類の進捗ダイアログ"""
        if self._smart_dialog and self._smart_dialog.winfo_exists():
            return
        
        d = ctk.CTkToplevel(self)
        d.title("Smart Classify")
        d.geometry("400x150")
        d.transient(self)
        d.grab_set()
        d.resizable(False, False)
        self._smart_dialog = d
        
        ctk.CTkLabel(d, text=f"AIが最大{total}件のブックマークを解析中です...").pack(pady=12)
        
        # CustomTkinterのCTkProgressBarはindeterminateモードをサポートしていないため、
        # 代わりにアニメーション効果を実装
        pb_frame = ctk.CTkFrame(d)
        pb_frame.pack(fill="x", padx=14, pady=5)
        pb = ctk.CTkProgressBar(pb_frame)
        pb.pack(fill="x")
        # 簡易的なアニメーション（実際には別の方法が必要かもしれません）
        pb.set(0.5)  # 中間位置に設定
        
        self.traffic_label = ctk.CTkLabel(d, text="AIと通信中...")
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
        
        ctk.CTkButton(d, text="Cancel", command=on_hide).pack(pady=10)
        d.protocol("WM_DELETE_WINDOW", on_hide)
    
    def _show_smart_classify_preview(self, plan: Dict, base_node: Node):
        """AI分類の結果プレビュー"""
        if not plan:
            if self.last_classification_prompts:
                messagebox.showinfo("Smart Classify", "現在の指示では、これ以上分類できる候補が見つかりませんでした。")
            else:
                messagebox.showinfo("Smart Classify", "AIによる分類候補が見つかりませんでした。")
            return
        
        preview_text = "\n".join([f"{folder}: {len(bms)} bookmarks" for folder, bms in plan.items()])
        if messagebox.askyesno("Smart Classification Preview", f"Apply classification?\n\n{preview_text}"):
            self._execute_classification_plan(plan, base_node)
    
    def cmd_check_proxy(self):
        """プロキシ接続をテスト"""
        proxy_info = self._get_proxies_for_requests()
        if not proxy_info:
            if not self.use_proxy_var.get():
                messagebox.showinfo("Proxy Check", "プロキシは使用しない設定です。")
            else:
                messagebox.showinfo("Proxy Check", "プロキシ設定がconfig.iniに見つかりません。")
            return
        
        dialog = ctk.CTkToplevel(self)
        dialog.title("Proxy Test")
        dialog.geometry("300x100")
        dialog.transient(self)
        dialog.grab_set()
        ctk.CTkLabel(dialog, text="Testing proxy connection...").pack(pady=20)
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
    
    def cmd_set_smart_classify_limit(self):
        """スマート分類の上限を設定"""
        current_limit = self.max_smart_items
        new_limit = simpledialog.askinteger(
            "Smart Classify Limit",
            "スマート分類の最大ブックマーク数を入力してください（50～1000）：",
            initialvalue=current_limit,
            minvalue=50,
            maxvalue=1000,
            parent=self
        )
        if new_limit is not None:
            self.max_smart_items = new_limit
            messagebox.showinfo("Smart Classify Limit", f"最大処理数を {new_limit} に設定しました。")
    
    def cmd_set_title_fetch_timeout(self):
        """タイトル取得のタイムアウトを設定"""
        new_timeout = simpledialog.askinteger(
            "Title Fetch Timeout",
            "タイトル取得のタイムアウト秒数を入力してください（2～60）：",
            initialvalue=self.fetch_timeout,
            minvalue=2,
            maxvalue=60,
            parent=self
        )
        if new_timeout is not None:
            self.fetch_timeout = new_timeout
            messagebox.showinfo("Title Fetch Timeout", f"タイムアウトを {new_timeout} 秒に設定しました。")
    
    def cmd_show_progress_chart(self):
        """進捗チャートを表示"""
        if not self.progress_history:
            messagebox.showinfo("Progress Chart", "進捗データがありません。スマート分類を先に行ってください。")
            return
        
        dialog = ctk.CTkToplevel(self)
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
    
    def cmd_fix_titles_from_url(self):
        """URLからタイトルを修正"""
        selected_nodes = [self.card_to_node[card] for card in self.selected_cards if card in self.card_to_node]
        if not selected_nodes:
            messagebox.showinfo("Fix Titles", "対象のブックマークを選択してください。")
            return
        
        targets = []
        def collect(node):
            if not node:
                return
            if node.type == "bookmark" and node.url:
                t = (node.title or "").strip()
                if t == node.url.strip() or is_valid_url(t):
                    targets.append(node)
            elif node.type == "folder":
                for ch in node.children:
                    collect(ch)
        
        for node in selected_nodes:
            collect(node)
        
        targets = list({id(n): n for n in targets}.values())
        if not targets:
            messagebox.showinfo("Fix Titles", "選択範囲に修正対象（タイトルがURLのブックマーク）はありません。")
            return
        
        self._show_titlefix_progress(len(targets))
        threading.Thread(target=self._fix_titles_worker, args=(targets,), daemon=True).start()
    
    def _show_titlefix_progress(self, total: int):
        """タイトル修正の進捗ダイアログ"""
        if self._titlefix_dialog and self._titlefix_dialog.winfo_exists():
            return
        
        d = ctk.CTkToplevel(self)
        d.title("Fix Titles from URL")
        d.geometry("360x140")
        d.transient(self)
        d.grab_set()
        d.resizable(False, False)
        self._titlefix_dialog = d
        self._titlefix_cancelled = False
        
        ctk.CTkLabel(d, text=f"合計 {total} 件のタイトルを修正中...").pack(pady=10)
        
        self._titlefix_var = ctk.DoubleVar(value=0.0)
        pb = ctk.CTkProgressBar(d, variable=self._titlefix_var)
        pb.pack(fill="x", padx=12, pady=6)
        
        self._titlefix_label = ctk.CTkLabel(d, text=f"0 / {total}")
        self._titlefix_label.pack()
        
        def on_cancel():
            self._titlefix_cancelled = True
            try:
                d.destroy()
            except tk.TclError:
                pass
        
        ctk.CTkButton(d, text="Cancel", command=on_cancel).pack(pady=10)
        d.protocol("WM_DELETE_WINDOW", on_cancel)
    
    def _fix_titles_worker(self, nodes):
        """タイトル修正を別スレッドで実行"""
        proxy_info = self._get_proxies_for_requests()
        check_cancel = lambda: getattr(self, "_titlefix_cancelled", False)
        fix_titles(nodes, self.ui_queue, proxy_info, self.fetch_timeout, self.logger, check_cancel)

