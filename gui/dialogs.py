import tkinter as tk
from tkinter import simpledialog
import customtkinter as ctk
from gui.theme import Colors, Fonts
from typing import Optional, List, Tuple
from core.model import Node

class CustomPromptDialog(simpledialog.Dialog):
    def __init__(self, parent, title=None, previous_prompts=None):
        self.previous_prompts = previous_prompts or []
        super().__init__(parent, title)

    def body(self, master):
        self.result = None
        # Using customtkinter widgets inside the dialog
        if self.previous_prompts:
            ctk.CTkLabel(master, text="現在の指示:", font=("", 12, "bold"), text_color=Colors.TEXT_SECONDARY).pack(anchor="w", padx=5, pady=(5, 0))
            
            # Use CTkTextbox for read-only history if possible, or standard Text with styling
            # Standard Text is easier to fit in simpledialog geometry management sometimes, but let's try CTk
            history_text = ctk.CTkTextbox(master, height=80, width=400, border_width=1)
            history_text.pack(padx=5, pady=2, fill="x", expand=True)
            display_str = "\n".join([f"- {p}" for p in self.previous_prompts])
            history_text.insert("1.0", display_str)
            history_text.configure(state="disabled", fg_color=Colors.BACKGROUND, text_color=Colors.TEXT_PRIMARY)
        
        ctk.CTkLabel(master, text="追加の指示を入力:", font=("", 12, "bold"), text_color=Colors.TEXT_PRIMARY).pack(anchor="w", padx=5, pady=(10, 0))
        self.text_widget = ctk.CTkTextbox(master, height=100, width=400, border_width=1)
        self.text_widget.pack(padx=5, pady=5, fill="both", expand=True)
        
        # simpledialog expects the initial focus widget return
        return self.text_widget

    def apply(self):
        self.result = self.text_widget.get("1.0", "end-1c").strip()


class FolderSelectDialog(ctk.CTkToplevel):
    """フォルダ選択ダイアログ"""
    
    def __init__(self, parent, root_node: Node, exclude_nodes: Optional[List[Node]] = None):
        super().__init__(parent)
        self.title("フォルダを選択")
        self.geometry("500x400")
        self.transient(parent)
        self.grab_set()
        self.resizable(True, True)
        
        self.result = None
        self.exclude_nodes = set(exclude_nodes) if exclude_nodes else set()
        
        # フォルダリストを構築
        self.folder_list: List[Tuple[str, Node]] = []
        self._build_folder_list(root_node, [])
        
        # UI構築
        self._build_ui()
        
        # フォーカスを設定（不要になったため削除）
    
    def _build_folder_list(self, node: Node, path: List[str]):
        """フォルダリストを再帰的に構築"""
        if node in self.exclude_nodes:
            return
        
        if node.type == 'folder':
            # パス文字列を作成（"Bookmarks / Folder1 / Folder2" 形式）
            if path:
                path_str = " / ".join(path[1:] + [node.title])  # "Bookmarks" を除外
            else:
                path_str = node.title or "Bookmarks"
            
            self.folder_list.append((path_str, node))
            
            # 子フォルダを再帰的に追加
            for child in node.children:
                self._build_folder_list(child, path + [node.title])
    
    def _build_ui(self):
        """UIを構築"""
        # 説明ラベル
        label = ctk.CTkLabel(
            self,
            text="移動先のフォルダを選択してください:",
            font=ctk.CTkFont(family=Fonts.FAMILY, size=Fonts.SIZE_M),
            text_color=Colors.TEXT_PRIMARY
        )
        label.pack(pady=(10, 5), padx=10, anchor="w")
        
        # スクロール可能なフレーム（CustomTkinterのみを使用）
        scrollable_frame = ctk.CTkScrollableFrame(self, fg_color=Colors.SURFACE_1)
        scrollable_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # 選択されたインデックスを保持
        self.selected_index = 0 if self.folder_list else None
        
        # フォルダをボタンとして表示
        self.folder_buttons = []
        for i, (path_str, node) in enumerate(self.folder_list):
            btn = ctk.CTkButton(
                scrollable_frame,
                text=path_str,
                command=lambda idx=i, n=node: self._on_folder_selected(idx, n),
                anchor="w",
                fg_color=Colors.SURFACE_1 if i != self.selected_index else Colors.PRIMARY,
                text_color=Colors.TEXT_PRIMARY if i != self.selected_index else "white",
                hover_color=Colors.HOVER_BG if i != self.selected_index else Colors.PRIMARY_HOVER,
                height=32
            )
            btn.pack(fill="x", padx=5, pady=2)
            self.folder_buttons.append(btn)
        
        # 最初の項目を選択状態にする
        if self.folder_list and self.folder_buttons:
            self.folder_buttons[0].configure(
                fg_color=Colors.PRIMARY,
                text_color="white"
            )
    
    def _on_folder_selected(self, index: int, node: Node):
        """フォルダが選択されたとき"""
        # 以前の選択を解除
        if self.selected_index is not None and self.selected_index < len(self.folder_buttons):
            self.folder_buttons[self.selected_index].configure(
                fg_color=Colors.SURFACE_1,
                text_color=Colors.TEXT_PRIMARY
            )
        
        # 新しい選択を設定
        self.selected_index = index
        self.folder_buttons[index].configure(
            fg_color=Colors.PRIMARY,
            text_color="white"
        )
        
        # 結果を設定
        self.result = node
        
        # ボタンフレーム
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)
        
        # OKボタン
        ok_btn = ctk.CTkButton(
            btn_frame,
            text="OK",
            command=self._on_ok,
            width=100
        )
        ok_btn.pack(side="right", padx=(5, 0))
        
        # キャンセルボタン
        cancel_btn = ctk.CTkButton(
            btn_frame,
            text="キャンセル",
            command=self._on_cancel,
            width=100,
            fg_color=Colors.SURFACE_1,
            text_color=Colors.TEXT_PRIMARY,
            hover_color=Colors.HOVER_BG
        )
        cancel_btn.pack(side="right", padx=(0, 5))
        
        # EnterキーでOK、Escapeキーでキャンセル
        self.bind("<Return>", lambda e: self._on_ok())
        self.bind("<Escape>", lambda e: self._on_cancel())
    
    def _on_ok(self):
        """OKボタンが押されたとき"""
        if self.selected_index is not None and 0 <= self.selected_index < len(self.folder_list):
            self.result = self.folder_list[self.selected_index][1]
            self.destroy()
        elif self.folder_list:
            # 選択がない場合は最初の項目を使用
            self.result = self.folder_list[0][1]
            self.destroy()
    
    def _on_cancel(self):
        """キャンセルボタンが押されたとき"""
        self.result = None
        self.destroy()
