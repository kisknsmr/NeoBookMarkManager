"""
モダンなWebアプリ風UIコンポーネント
CustomTkinterベースのカード型レイアウトコンポーネント
Premium Apple-inspired Design
"""

import customtkinter as ctk
from typing import Optional, Callable, Dict, Any, List
from core.model import Node
import base64
from io import BytesIO
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from gui.theme import Colors, Fonts, Dims
from gui.ui_kit import StyledCard


# グローバルファビコンキャッシュ（パフォーマンス向上のため）
_favicon_cache: Dict[str, Optional[ctk.CTkImage]] = {}


def get_favicon_image(icon_data: str, size: int = 14) -> Optional[ctk.CTkImage]:
    """ファビコンデータからCTkImageを取得（キャッシュ付き）"""
    if not PIL_AVAILABLE or not icon_data:
        return None
    
    cache_key = f"{hash(icon_data)}_{size}"
    if cache_key in _favicon_cache:
        return _favicon_cache[cache_key]
    
    try:
        if icon_data.startswith('data:image'):
            header, encoded = icon_data.split(',', 1)
            img_data = base64.b64decode(encoded)
            img = Image.open(BytesIO(img_data))
            img = img.resize((size, size), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
            _favicon_cache[cache_key] = ctk_img
            return ctk_img
    except Exception:
        pass
    
    _favicon_cache[cache_key] = None
    return None


class BookmarkCard(StyledCard):
    """個別ブックマークを表示するカードコンポーネント - Compact Design"""
    
    def __init__(self, parent, node: Node, on_click: Optional[Callable] = None, 
                 on_double_click: Optional[Callable] = None,
                 **kwargs):
        super().__init__(parent, **kwargs)
        self.node = node
        self.on_click = on_click
        self.on_double_click = on_double_click
        self.is_selected = False
        self.favicon_image = None
        
        self._build_card()
        self._bind_events()
    
    def _build_card(self):
        """カードのUIを構築 - Compact Style"""
        self.configure(fg_color=Colors.SURFACE)
        
        # ヘッダー（ファビコン + タイトル）
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=(8, 4))
        
        # ファビコン
        self.favicon_image = get_favicon_image(self.node.icon, 16)
        if self.favicon_image:
            icon_lbl = ctk.CTkLabel(header, image=self.favicon_image, text="")
            icon_lbl.pack(side="left", padx=(0, 6))
        else:
            icon_lbl = ctk.CTkLabel(header, text="🔗", font=ctk.CTkFont(size=12))
            icon_lbl.pack(side="left", padx=(0, 6))
        
        # タイトル
        title_text = self.node.title or "(Untitled)"
        if len(title_text) > 28:
            title_text = title_text[:25] + "..."
        
        self.title_label = ctk.CTkLabel(
            header,
            text=title_text,
            font=ctk.CTkFont(family=Fonts.FAMILY, size=12, weight="bold"),
            text_color=Colors.TEXT_PRIMARY,
            anchor="w"
        )
        self.title_label.pack(side="left", fill="x", expand=True)
        
        # URL/ドメイン表示
        if self.node.url:
            from urllib.parse import urlparse
            try:
                domain = urlparse(self.node.url).netloc
                domain_text = domain.replace("www.", "") if domain else self.node.url[:30]
            except:
                domain_text = self.node.url[:30]
        else:
            domain_text = "(No URL)"
        
        self.url_label = ctk.CTkLabel(
            self,
            text=domain_text,
            font=ctk.CTkFont(family=Fonts.FAMILY, size=10),
            text_color=Colors.TEXT_SECONDARY,
            anchor="w"
        )
        self.url_label.pack(pady=(0, 8), padx=8, fill="x")
        
        self.default_fg_color = Colors.SURFACE
    
    def _bind_events(self):
        """イベントバインディング"""
        # Base interaction (Click/Hover)
        self.bind("<ButtonRelease-1>", self._on_click_handler)
        self.bind("<Double-Button-1>", self._on_double_click_handler)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        
        for widget in [self.title_label, self.url_label]:
            widget.bind("<ButtonRelease-1>", self._on_click_handler)
            widget.bind("<Double-Button-1>", self._on_double_click_handler)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

    def _on_click_handler(self, event):
        """Click event propagation"""
        if self.on_click:
            self.on_click(self.node)
    
    def _on_double_click_handler(self, event):
        if self.on_double_click:
            self.on_double_click(self.node)
    
    def _on_enter(self, event):
        if not self.is_selected:
            self.configure(fg_color=Colors.HOVER_BG)
    
    def _on_leave(self, event):
        if not self.is_selected:
            self.configure(fg_color=self.default_fg_color)
    
    def set_selected(self, selected: bool):
        self.is_selected = selected
        if selected:
            self.configure(border_width=2, border_color=Colors.PRIMARY, fg_color=Colors.SELECTED_BG)
        else:
            self.configure(border_width=1, border_color=Colors.BORDER, fg_color=self.default_fg_color)


class BookmarkRow(ctk.CTkFrame):
    """リスト表示用の行コンポーネント - Compact Design"""
    
    def __init__(self, parent, node: Node, on_click: Optional[Callable] = None, 
                 on_double_click: Optional[Callable] = None,
                 **kwargs):
        super().__init__(parent, **kwargs)
        self.node = node
        self.on_click = on_click
        self.on_double_click = on_double_click
        self.is_selected = False
        self.favicon_image = None
        self.default_fg_color = Colors.SURFACE
        
        self._build_row()
        self._bind_events()
    
    def _build_row(self):
        """行のUIを構築 - Compact Style"""
        self.configure(
            corner_radius=Dims.RADIUS_S,
            border_width=0,
            fg_color=Colors.SURFACE,
            height=32
        )
        self.pack_propagate(False)
        
        # ファビコン
        self.favicon_image = get_favicon_image(self.node.icon, 14)
        if self.favicon_image:
            icon_label = ctk.CTkLabel(self, image=self.favicon_image, text="")
            icon_label.pack(side="left", padx=(8, 6))
        else:
            icon_label = ctk.CTkLabel(self, text="🔗", font=ctk.CTkFont(size=11))
            icon_label.pack(side="left", padx=(8, 6))
        
        # タイトル
        title_text = self.node.title or "(Untitled)"
        if len(title_text) > 50:
            title_text = title_text[:47] + "..."
        self.title_label = ctk.CTkLabel(
            self,
            text=title_text,
            font=ctk.CTkFont(family=Fonts.FAMILY, size=12),
            text_color=Colors.TEXT_PRIMARY,
            anchor="w"
        )
        self.title_label.pack(side="left", fill="x", expand=True, padx=4)
        
        # URL/ドメイン (右寄せ)
        if self.node.url:
            from urllib.parse import urlparse
            try:
                domain = urlparse(self.node.url).netloc
                domain_text = domain.replace("www.", "")
                if len(domain_text) > 25:
                    domain_text = domain_text[:22] + "..."
            except:
                domain_text = "..."
        else:
            domain_text = ""
        
        self.url_label = ctk.CTkLabel(
            self,
            text=domain_text,
            font=ctk.CTkFont(family=Fonts.FAMILY, size=10),
            text_color=Colors.TEXT_SECONDARY,
            anchor="e",
            width=150
        )
        self.url_label.pack(side="right", padx=(4, 8))
        
        self.default_fg_color = Colors.SURFACE

    def _bind_events(self):
        """イベントバインディング"""
        self.bind("<ButtonRelease-1>", self._on_click_handler)
        self.bind("<Double-Button-1>", self._on_double_click_handler)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        
        for widget in [self.title_label, self.url_label]:
            widget.bind("<ButtonRelease-1>", self._on_click_handler)
            widget.bind("<Double-Button-1>", self._on_double_click_handler)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
    
    def _on_click_handler(self, event):
        if self.on_click:
            self.on_click(self.node)
    
    def _on_double_click_handler(self, event):
        if self.on_double_click:
            self.on_double_click(self.node)
    
    def _on_enter(self, event):
        if not self.is_selected:
            self.configure(fg_color=Colors.HOVER_BG)
    
    def _on_leave(self, event):
        if not self.is_selected:
            self.configure(fg_color=self.default_fg_color)
    
    def set_selected(self, selected: bool):
        self.is_selected = selected
        if selected:
            self.configure(fg_color=Colors.SELECTED_BG)
        else:
            self.configure(fg_color=self.default_fg_color)


class FolderTree(ctk.CTkFrame):
    """高速なツリービュー - ttk.Treeview使用"""
    
    def __init__(self, parent, root_node: Node, 
                 on_folder_select: Optional[Callable] = None,
                 on_bookmark_click: Optional[Callable] = None,
                 on_bookmark_double_click: Optional[Callable] = None,
                 **kwargs):
        # CTkFrameの初期化（fg_colorなどのCustomTkinter固有引数を処理）
        super().__init__(parent, **kwargs)
        
        self.root_node = root_node
        self.on_folder_select = on_folder_select
        self.on_bookmark_click = on_bookmark_click
        self.on_bookmark_double_click = on_bookmark_double_click
        self.selected_folder = None
        self.node_map = {}  # tree_id -> Node
        self.id_map = {}    # id(Node) -> tree_id
        self.other_tree = None  # 他のツリービューへの参照（2画面モード用）
        
        self._build_tree()
    
    def _build_tree(self):
        """ツリーを構築"""
        import tkinter as tk
        from tkinter import ttk
        
        # スタイル設定
        style = ttk.Style()
        style.configure("Treeview", 
                       font=(Fonts.FAMILY, 11),
                       rowheight=22)
        style.configure("Treeview.Heading", 
                       font=(Fonts.FAMILY, 10, "bold"))
        
        # Treeview作成（タイトルとURL列）
        self.tree = ttk.Treeview(
            self, 
            columns=("url",),
            show="tree headings",
            selectmode="browse"
        )
        
        # 列設定
        self.tree.heading("#0", text="タイトル", anchor="w")
        self.tree.heading("url", text="URL", anchor="w")
        self.tree.column("#0", width=350, minwidth=200)
        self.tree.column("url", width=250, minwidth=100)
        
        # スクロールバー
        scrollbar_y = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        scrollbar_x = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        
        # レイアウト
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")
        
        # ノードを追加
        self._add_nodes(self.root_node, "")
        
        # イベントバインド
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double_click)
        
        # ドラッグ&ドロップ用のイベント
        self.tree.bind("<Button-1>", self._on_tree_button1)
        self.tree.bind("<B1-Motion>", self._on_tree_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release)
        
        # グローバルなマウス位置検出（他のツリービュー上でのドラッグ検出用）
        root = self.winfo_toplevel()
        root.bind_all("<B1-Motion>", self._on_global_motion)
        root.bind_all("<ButtonRelease-1>", self._on_global_release)
        
        # ドラッグ状態
        self.drag_start_item = None
        self.drag_start_y = 0
        self.drag_threshold = 5
        self.drag_source_tree = None  # ドラッグ元のツリービュー
    
    def _add_nodes(self, node: Node, parent_id: str):
        """ノードを再帰的に追加"""
        # アイコンとタイトル
        if node.type == "folder":
            icon = "📁 "
            title = icon + (node.title or "Untitled")
        else:
            # ファビコンがある場合は別のアイコンで区別
            if node.icon:
                icon = "🌐 "  # ファビコンあり
            else:
                icon = "🔗 "  # ファビコンなし
            title = icon + (node.title or "(Untitled)")
        
        # URL（ドメインのみ）
        url_display = ""
        if node.url:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(node.url)
                url_display = parsed.netloc or node.url[:40]
            except:
                url_display = node.url[:40]
        
        # ノード追加
        tree_id = self.tree.insert(
            parent_id, 
            "end", 
            text=title,
            values=(url_display,),
            open=(node.type == "folder" and node == self.root_node)  # ルートのみ展開
        )
        
        self.node_map[tree_id] = node
        self.id_map[id(node)] = tree_id
        
        # 子ノードを追加
        if node.type == "folder":
            for child in node.children:
                self._add_nodes(child, tree_id)
    
    def _on_select(self, event):
        """選択時のイベント"""
        selection = self.tree.selection()
        if not selection:
            return
        
        tree_id = selection[0]
        node = self.node_map.get(tree_id)
        if not node:
            return
        
        if node.type == "folder":
            self.selected_folder = node
            if self.on_folder_select:
                self.on_folder_select(node)
        else:
            if self.on_bookmark_click:
                self.on_bookmark_click(node)
    
    def _on_double_click(self, event):
        """ダブルクリック時のイベント"""
        selection = self.tree.selection()
        if not selection:
            return
        
        tree_id = selection[0]
        node = self.node_map.get(tree_id)
        if not node:
            return
        
        if node.type == "bookmark" and self.on_bookmark_double_click:
            self.on_bookmark_double_click(node)
    
    def _on_tree_button1(self, event):
        """ツリービューのButton-1イベント（ドラッグ開始の準備）"""
        item = self.tree.identify_row(event.y)
        if item:
            self.drag_start_item = item
            self.drag_start_y = event.y
            self.drag_source_tree = self  # このツリービューがドラッグ元
        else:
            self.drag_start_item = None
            self.drag_source_tree = None
    
    def _on_tree_motion(self, event):
        """ツリービューのB1-Motionイベント（ドラッグ中）"""
        if not self.drag_start_item or not self.drag_source_tree:
            return
        
        # 閾値を超えた場合のみドラッグ開始
        if abs(event.y - self.drag_start_y) < self.drag_threshold:
            return
        
        # このツリービュー上の場合
        if event.widget == self.tree:
            item = self.tree.identify_row(event.y)
            if item and item != self.drag_start_item:
                # ドラッグ先のアイテムをハイライト（視覚的フィードバック）
                self.tree.selection_set(item)
    
    def _on_global_motion(self, event):
        """グローバルなB1-Motionイベント（他のツリービュー上でのドラッグ検出）"""
        if not self.drag_start_item or not self.drag_source_tree:
            return
        
        # 他のツリービュー上にマウスがある場合
        if hasattr(self.drag_source_tree, 'other_tree') and self.drag_source_tree.other_tree:
            other_tree = self.drag_source_tree.other_tree
            try:
                # グローバル座標からローカル座標に変換
                local_y = event.y_root - other_tree.tree.winfo_rooty()
                item = other_tree.tree.identify_row(local_y)
                if item:
                    other_tree.tree.selection_set(item)
            except:
                pass
    
    def _on_tree_release(self, event):
        """ツリービューのButtonRelease-1イベント（ドロップ処理）"""
        if not self.drag_start_item or not self.drag_source_tree:
            self.drag_start_item = None
            self.drag_source_tree = None
            return
        
        # このツリービュー上でドロップされた場合
        if event.widget == self.tree:
            self._process_drop(event, self)
    
    def _on_global_release(self, event):
        """グローバルなButtonRelease-1イベント（他のツリービュー上でのドロップ検出）"""
        if not self.drag_start_item or not self.drag_source_tree:
            return
        
        # 他のツリービュー上でドロップされた場合
        if hasattr(self.drag_source_tree, 'other_tree') and self.drag_source_tree.other_tree:
            other_tree = self.drag_source_tree.other_tree
            try:
                # マウス位置が他のツリービュー上にあるか確認
                other_tree_x = other_tree.tree.winfo_rootx()
                other_tree_y = other_tree.tree.winfo_rooty()
                other_tree_w = other_tree.tree.winfo_width()
                other_tree_h = other_tree.tree.winfo_height()
                
                if (other_tree_x <= event.x_root <= other_tree_x + other_tree_w and
                    other_tree_y <= event.y_root <= other_tree_y + other_tree_h):
                    self._process_drop(event, other_tree)
            except:
                pass
    
    def _process_drop(self, event, target_tree):
        """ドロップ処理の共通ロジック"""
        if not self.drag_start_item or not self.drag_source_tree:
            return
        
        # ローカル座標に変換
        try:
            if event.widget == target_tree.tree:
                local_y = event.y
            else:
                local_y = event.y_root - target_tree.tree.winfo_rooty()
            item = target_tree.tree.identify_row(local_y)
        except:
            item = None
        
        if not item:
            self.drag_start_item = None
            self.drag_source_tree = None
            return
        
        # ドロップ処理
        source_node = self.drag_source_tree.node_map.get(self.drag_start_item)
        target_node = target_tree.node_map.get(item)
        
        if not source_node or not target_node:
            self.drag_start_item = None
            self.drag_source_tree = None
            return
        
        # 自分自身を子に移動することはできない
        if source_node == target_node:
            self.drag_start_item = None
            self.drag_source_tree = None
            return
        
        # ターゲットがフォルダの場合、そのフォルダに移動
        if target_node.type == "folder":
            # 元の親から削除
            if source_node.parent:
                source_node.parent.children.remove(source_node)
            
            # 新しい親に追加
            target_node.append(source_node)
            
            # 両方のツリービューを更新
            self.drag_source_tree.refresh(self.drag_source_tree.root_node)
            if target_tree != self.drag_source_tree:
                target_tree.refresh(target_tree.root_node)
        else:
            # ターゲットがブックマークの場合、同じ親フォルダ内で並び替え
            if source_node.parent == target_node.parent and source_node.parent:
                parent = source_node.parent
                old_idx = parent.children.index(source_node)
                new_idx = parent.children.index(target_node)
                
                parent.children.remove(source_node)
                parent.children.insert(new_idx, source_node)
                
                # ツリービューを更新（順序のみ）
                if target_tree == self.drag_source_tree:
                    target_tree._reorder_tree_items(parent)
                else:
                    # 異なるツリービュー間の場合は両方更新
                    self.drag_source_tree.refresh(self.drag_source_tree.root_node)
                    target_tree.refresh(target_tree.root_node)
        
        self.drag_start_item = None
        self.drag_source_tree = None
    
    def _reorder_tree_items(self, folder_node: Node):
        """フォルダ内のアイテム順序をツリービューに反映"""
        folder_tree_id = self.id_map.get(id(folder_node))
        if not folder_tree_id:
            return
        
        # 現在の子アイテムを取得
        current_children = list(self.tree.get_children(folder_tree_id))
        
        # 新しい順序に並び替え
        new_order = []
        for child_node in folder_node.children:
            child_tree_id = self.id_map.get(id(child_node))
            if child_tree_id in current_children:
                new_order.append(child_tree_id)
        
        # 順序が変わっていない場合は何もしない
        if new_order == current_children:
            return
        
        # アイテムを削除して新しい順序で再挿入
        # まず、各アイテムの情報を保存
        items_data = {}
        for child_id in current_children:
            node = self.node_map.get(child_id)
            if node:
                # アイコンとタイトル
                if node.type == "folder":
                    icon = "📁 "
                    title = icon + (node.title or "Untitled")
                else:
                    if node.icon:
                        icon = "🌐 "
                    else:
                        icon = "🔗 "
                    title = icon + (node.title or "(Untitled)")
                
                # URL
                url_display = ""
                if node.url:
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(node.url)
                        url_display = parsed.netloc or node.url[:40]
                    except:
                        url_display = node.url[:40]
                
                # 展開状態
                is_open = self.tree.item(child_id, "open")
                
                items_data[child_id] = {
                    "text": title,
                    "values": (url_display,),
                    "open": is_open,
                    "node": node
                }
        
        # 全ての子アイテムを削除
        for child_id in current_children:
            self.tree.delete(child_id)
        
        # 新しい順序で再挿入
        for child_id in new_order:
            data = items_data[child_id]
            new_id = self.tree.insert(
                folder_tree_id,
                "end",
                text=data["text"],
                values=data["values"],
                open=data["open"]
            )
            # マッピングを更新
            node = data["node"]
            self.node_map[new_id] = node
            self.id_map[id(node)] = new_id
            
            # 子ノードも再帰的に追加
            if node.type == "folder":
                for grandchild in node.children:
                    self._add_nodes(grandchild, new_id)
    
    def refresh(self, new_root_node: Node):
        """ツリーを更新"""
        self.root_node = new_root_node
        self.node_map.clear()
        self.id_map.clear()
        self.selected_folder = None
        
        # 全アイテム削除
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # 再構築
        self._add_nodes(new_root_node, "")
        
        # 2画面モードの場合、もう一方のツリービューも更新
        if hasattr(self, 'other_tree') and self.other_tree:
            self.other_tree.root_node = new_root_node
            self.other_tree.node_map.clear()
            self.other_tree.id_map.clear()
            self.other_tree.selected_folder = None
            for item in self.other_tree.tree.get_children():
                self.other_tree.tree.delete(item)
            self.other_tree._add_nodes(new_root_node, "")
    
    def expand_all(self):
        """すべてのフォルダを展開"""
        if not hasattr(self, 'tree'):
            return
        
        def expand_recursive(item_id):
            # このアイテムを展開
            self.tree.item(item_id, open=True)
            # 子アイテムも再帰的に展開
            for child_id in self.tree.get_children(item_id):
                expand_recursive(child_id)
        
        # ルートレベルから開始
        for item_id in self.tree.get_children(""):
            expand_recursive(item_id)
    
    def collapse_all(self):
        """すべてのフォルダを縮小"""
        if not hasattr(self, 'tree'):
            return
        
        def collapse_recursive(item_id):
            # 子アイテムを先に縮小
            for child_id in self.tree.get_children(item_id):
                collapse_recursive(child_id)
            # このアイテムを縮小
            self.tree.item(item_id, open=False)
        
        # ルートレベルから開始（ルート自体は縮小しない）
        for item_id in self.tree.get_children(""):
            # ルートは開いたままにする
            for child_id in self.tree.get_children(item_id):
                collapse_recursive(child_id)
    
    def expand_selected(self):
        """選択されたフォルダを展開"""
        if not hasattr(self, 'tree'):
            return
        selection = self.tree.selection()
        if selection:
            # 選択アイテムとその子を展開
            def expand_with_children(item_id):
                self.tree.item(item_id, open=True)
                for child_id in self.tree.get_children(item_id):
                    if self.node_map.get(child_id, {}).type == "folder" if hasattr(self.node_map.get(child_id), 'type') else False:
                        self.tree.item(child_id, open=True)
            expand_with_children(selection[0])
    
    def collapse_selected(self):
        """選択されたフォルダを縮小"""
        if not hasattr(self, 'tree'):
            return
        selection = self.tree.selection()
        if selection:
            self.tree.item(selection[0], open=False)
    
    def set_favicon(self, url: str, favicon_data: str):
        """ファビコンデータを設定（互換性のため残す）"""
        pass
    
    def select_node(self, node: Node):
        """指定したノードを選択"""
        tree_id = self.id_map.get(id(node))
        if tree_id:
            self.tree.selection_set(tree_id)
            self.tree.see(tree_id)


class SearchBar(ctk.CTkFrame):
    """検索バーコンポーネント"""
    
    def __init__(self, parent, on_search: Optional[Callable[[str], None]] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.on_search = on_search
        self.search_after_id = None
        
        self._build_search_bar()
    
    def _build_search_bar(self):
        """検索バーを構築"""
        # 検索アイコンとラベル
        search_label = ctk.CTkLabel(
            self,
            text="🔍",
            font=ctk.CTkFont(size=16)
        )
        search_label.pack(side="left", padx=(10, 5))
        
        # 検索入力フィールド
        self.search_entry = ctk.CTkEntry(
            self,
            placeholder_text="ブックマークを検索...",
            font=ctk.CTkFont(size=12),
            width=300
        )
        self.search_entry.pack(side="left", padx=5, fill="x", expand=True)
        self.search_entry.bind("<KeyRelease>", self._on_search_changed)
        
        # クリアボタン
        clear_btn = ctk.CTkButton(
            self,
            text="✕",
            width=30,
            height=30,
            command=self._clear_search,
            fg_color="transparent",
            hover_color=("gray80", "gray30")
        )
        clear_btn.pack(side="left", padx=5)
    
    def _on_search_changed(self, event):
        """検索文字列が変更されたとき（デバウンス付き）"""
        if self.search_after_id:
            self.after_cancel(self.search_after_id)
        
        def do_search():
            query = self.search_entry.get().strip()
            if self.on_search:
                self.on_search(query)
        
        self.search_after_id = self.after(300, do_search)
    
    def _clear_search(self):
        """検索をクリア"""
        self.search_entry.delete(0, "end")
        if self.on_search:
            self.on_search("")
    
    def get_query(self) -> str:
        """現在の検索クエリを取得"""
        return self.search_entry.get().strip()


class DetailPanel(ctk.CTkScrollableFrame):
    """選択したブックマークの詳細情報を表示するパネル"""
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.current_node = None
        
        self._build_panel()
    
    def _build_panel(self):
        """パネルを構築"""
        # タイトル
        self.title_label = ctk.CTkLabel(
            self,
            text="—",
            font=ctk.CTkFont(family=Fonts.FAMILY, size=14, weight="bold"),
            anchor="w",
            wraplength=280
        )
        self.title_label.pack(pady=(8, 4), padx=10, fill="x")
        
        # セパレータ
        separator = ctk.CTkFrame(self, height=1, fg_color=Colors.BORDER)
        separator.pack(fill="x", padx=10, pady=4)
        
        # URL表示
        url_label_text = ctk.CTkLabel(
            self,
            text="URL:",
            font=ctk.CTkFont(family=Fonts.FAMILY, size=11, weight="bold"),
            text_color=Colors.TEXT_SECONDARY,
            anchor="w"
        )
        url_label_text.pack(pady=(6, 2), padx=10, fill="x")
        
        self.url_text = ctk.CTkTextbox(
            self,
            height=50,
            font=ctk.CTkFont(family=Fonts.FAMILY, size=10),
            wrap="word"
        )
        self.url_text.pack(pady=(0, 6), padx=10, fill="x")
        
        # プレビューセクション
        preview_label = ctk.CTkLabel(
            self,
            text="Preview:",
            font=ctk.CTkFont(family=Fonts.FAMILY, size=11, weight="bold"),
            text_color=Colors.TEXT_SECONDARY,
            anchor="w"
        )
        preview_label.pack(pady=(6, 2), padx=10, fill="x")
        
        self.preview_title = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(family=Fonts.FAMILY, size=11, weight="bold"),
            text_color=Colors.TEXT_PRIMARY,
            anchor="w",
            wraplength=280
        )
        self.preview_title.pack(pady=(0, 3), padx=10, fill="x")
        
        self.preview_desc = ctk.CTkTextbox(
            self,
            height=80,
            font=ctk.CTkFont(family=Fonts.FAMILY, size=10),
            wrap="word"
        )
        self.preview_desc.pack(pady=(0, 8), padx=10, fill="x")
    
    def update_node(self, node: Optional[Node], preview_data: Optional[Dict[str, Any]] = None):
        """表示するノードを更新"""
        self.current_node = node
        
        if node:
            # タイトル
            title = node.title or "(Untitled)"
            self.title_label.configure(text=title)
            
            # URL
            self.url_text.delete("1.0", "end")
            self.url_text.insert("1.0", node.url or "(No URL)")
            
            # プレビュー
            if preview_data:
                self.preview_title.configure(text=preview_data.get("title", ""))
                self.preview_desc.delete("1.0", "end")
                self.preview_desc.insert("1.0", preview_data.get("description", ""))
            else:
                self.preview_title.configure(text="")
                self.preview_desc.delete("1.0", "end")
        else:
            self.title_label.configure(text="—")
            self.url_text.delete("1.0", "end")
            self.url_text.insert("1.0", "")
            self.preview_title.configure(text="")
            self.preview_desc.delete("1.0", "end")
