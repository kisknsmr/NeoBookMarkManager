"""
仮想化リスト実装（Canvas ベース）。

特徴:
  - 大量のアイテム表示に対応（遅延レンダリング）
  - スクロール時に見える範囲のアイテムのみ描画
  - プロトタイプ段階（今後の本番化を想定）

Note:
  このモジュールは将来 gui/main_window.py から使用される予定。
  現在は gui/app.py が完成するまでスケルトン実装。
"""

import tkinter as tk
from typing import List, Callable, Optional, Any, Tuple
from dataclasses import dataclass
from core.logger import logger


@dataclass
class ListItem:
    """リストアイテムの基本構造"""
    item_id: str
    text: str
    height: int = 40
    data: Optional[Any] = None


class VirtualList:
    """
    Canvas ベースの仮想化リスト。
    
    大量のアイテムを効率的に表示するためのコンポーネント。
    スクロール時は見える範囲のアイテムのみをレンダリング。
    """
    
    def __init__(self, parent: tk.Widget, on_item_select: Optional[Callable[[str], None]] = None):
        """
        初期化。
        
        Args:
            parent: 親ウィジェット
            on_item_select: アイテム選択時のコールバック
        """
        self.parent = parent
        self.on_item_select = on_item_select
        
        self._items: List[ListItem] = []
        self._selected_item_id: Optional[str] = None
        self._visible_range: Tuple[int, int] = (0, 0)
        
        # Canvas の作成
        self.canvas = tk.Canvas(parent, bg='white', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # スクロールバーの作成（細身化: width=8）
        self.scrollbar = tk.Scrollbar(parent, orient=tk.VERTICAL, command=self.canvas.yview, width=8)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.canvas.config(yscrollcommand=self.scrollbar.set)
        self.canvas.bind('<MouseWheel>', self._on_mousewheel)
        self.canvas.bind('<Button-4>', self._on_mousewheel)
        self.canvas.bind('<Button-5>', self._on_mousewheel)
        self.canvas.bind('<Button-1>', self._on_canvas_click)
        
        # 内部 frame
        self._frame_in_canvas = tk.Frame(self.canvas, bg='white')
        self._window_in_canvas = self.canvas.create_window((0, 0), window=self._frame_in_canvas, anchor=tk.NW)
        
        logger.info("VirtualList initialized")
    
    def set_items(self, items: List[ListItem]) -> None:
        """
        リストアイテムを設定。
        
        Args:
            items: ListItem のリスト
        """
        self._items = items
        self._selected_item_id = None
        self._render_visible_items()
        logger.info(f"VirtualList set with {len(items)} items")
    
    def add_item(self, item: ListItem) -> None:
        """
        アイテムを追加。
        
        Args:
            item: ListItem
        """
        self._items.append(item)
        self._render_visible_items()
    
    def remove_item(self, item_id: str) -> None:
        """
        アイテムを削除。
        
        Args:
            item_id: アイテム ID
        """
        self._items = [item for item in self._items if item.item_id != item_id]
        self._render_visible_items()
    
    def clear(self) -> None:
        """すべてのアイテムをクリア"""
        self._items.clear()
        self._selected_item_id = None
        self.canvas.delete("all")
    
    def _render_visible_items(self) -> None:
        """
        見える範囲のアイテムのみをレンダリング（プロトタイプ実装）。
        """
        self.canvas.delete("all")
        
        y_offset = 0
        for i, item in enumerate(self._items):
            # 簡易実装：すべてのアイテムを描画
            # TODO: 実際のスクロール位置に基づいて表示範囲を制限
            
            bg_color = '#e8f4f8' if item.item_id == self._selected_item_id else 'white'
            
            # テキストアイテムの描画
            self.canvas.create_rectangle(
                (0, y_offset),
                (self.canvas.winfo_width(), y_offset + item.height),
                fill=bg_color,
                outline='#e0e0e0'
            )
            
            self.canvas.create_text(
                (10, y_offset + item.height // 2),
                text=item.text,
                anchor=tk.W,
                font=('Arial', 10)
            )
            
            # クリック領域の登録
            rect_id = self.canvas.create_rectangle(
                (0, y_offset),
                (self.canvas.winfo_width(), y_offset + item.height),
                fill='',
                outline='',
                activefill='#b3e5fc'
            )
            self.canvas.tag_bind(rect_id, '<Button-1>', lambda e, iid=item.item_id: self._select_item(iid))
            
            # アイテムタグの登録
            self.canvas.addtag_withtag(f"item_{item.item_id}", rect_id)
            
            y_offset += item.height
        
        # Canvas サイズの更新
        self.canvas.config(scrollregion=self.canvas.bbox("all"))
    
    def _select_item(self, item_id: str) -> None:
        """
        アイテムを選択。
        
        Args:
            item_id: アイテム ID
        """
        self._selected_item_id = item_id
        self._render_visible_items()
        if self.on_item_select:
            self.on_item_select(item_id)
    
    def _on_canvas_click(self, event) -> None:
        """Canvas クリックイベント"""
        # _select_item で処理済みのため、ここでは何もしない
        pass
    
    def _on_mousewheel(self, event) -> None:
        """マウスホイールスクロールイベント"""
        if event.num == 5 or event.delta < 0:
            self.canvas.yview_scroll(1, tk.UNITS)
        elif event.num == 4 or event.delta > 0:
            self.canvas.yview_scroll(-1, tk.UNITS)
    
    def get_selected_item_id(self) -> Optional[str]:
        """
        選択されたアイテム ID を取得。
        
        Returns:
            選択されたアイテム ID、または None
        """
        return self._selected_item_id
