"""
UI 状態管理モジュール。

責務:
  - ノード選択状態の管理
  - フォルダツリー展開状態の管理
  - ソート・フィルター設定の保存
"""

from typing import Set, Dict, Any, Optional
from core.logger import logger


class UIState:
    """
    GUI 全体の状態を管理する軽量ストア。
    """
    
    def __init__(self):
        """初期化"""
        self.selected_node_ids: Set[str] = set()
        self.expanded_folder_ids: Set[str] = set()
        self.sort_order: str = "default"  # "default", "alphabetical", "date"
        self.filter_text: str = ""
        self.view_mode: str = "list"  # "list", "grid", "tree"
        self._observers: Dict[str, list] = {
            'selection': [],
            'expansion': [],
            'sort': [],
            'filter': [],
            'view_mode': []
        }
        logger.info("UIState initialized")
    
    # ==================== 選択状態 ====================
    
    def set_selected_nodes(self, node_ids: Set[str]) -> None:
        """
        選択ノード ID セットを設定。
        
        Args:
            node_ids: 選択されたノード ID のセット
        """
        if self.selected_node_ids != node_ids:
            self.selected_node_ids = node_ids
            self._notify('selection', node_ids)
            logger.debug(f"Selected nodes: {len(node_ids)}")
    
    def select_node(self, node_id: str, multi: bool = False) -> None:
        """
        単一ノードを選択。
        
        Args:
            node_id: ノード ID
            multi: True の場合、複数選択モード
        """
        if multi:
            self.selected_node_ids.add(node_id)
        else:
            self.selected_node_ids = {node_id}
        self._notify('selection', self.selected_node_ids)
    
    def deselect_node(self, node_id: str) -> None:
        """
        単一ノードの選択を解除。
        
        Args:
            node_id: ノード ID
        """
        self.selected_node_ids.discard(node_id)
        self._notify('selection', self.selected_node_ids)
    
    def clear_selection(self) -> None:
        """すべてのノードの選択を解除"""
        if self.selected_node_ids:
            self.selected_node_ids.clear()
            self._notify('selection', self.selected_node_ids)
    
    def is_selected(self, node_id: str) -> bool:
        """
        ノードが選択されているかチェック。
        
        Args:
            node_id: ノード ID
            
        Returns:
            選択されている場合 True
        """
        return node_id in self.selected_node_ids
    
    # ==================== フォルダ展開状態 ====================
    
    def expand_folder(self, folder_id: str) -> None:
        """
        フォルダを展開状態に設定。
        
        Args:
            folder_id: フォルダ ID
        """
        if folder_id not in self.expanded_folder_ids:
            self.expanded_folder_ids.add(folder_id)
            self._notify('expansion', folder_id)
    
    def collapse_folder(self, folder_id: str) -> None:
        """
        フォルダを折りたたみ状態に設定。
        
        Args:
            folder_id: フォルダ ID
        """
        self.expanded_folder_ids.discard(folder_id)
        self._notify('expansion', folder_id)
    
    def toggle_folder(self, folder_id: str) -> None:
        """
        フォルダの展開状態をトグル。
        
        Args:
            folder_id: フォルダ ID
        """
        if folder_id in self.expanded_folder_ids:
            self.collapse_folder(folder_id)
        else:
            self.expand_folder(folder_id)
    
    def is_expanded(self, folder_id: str) -> bool:
        """
        フォルダが展開状態かチェック。
        
        Args:
            folder_id: フォルダ ID
            
        Returns:
            展開されている場合 True
        """
        return folder_id in self.expanded_folder_ids
    
    # ==================== ソート・フィルター ====================
    
    def set_sort_order(self, order: str) -> None:
        """
        ソート順序を設定。
        
        Args:
            order: "default", "alphabetical", "date" など
        """
        if self.sort_order != order:
            self.sort_order = order
            self._notify('sort', order)
            logger.debug(f"Sort order changed to: {order}")
    
    def set_filter(self, text: str) -> None:
        """
        フィルター用の検索文字列を設定。
        
        Args:
            text: フィルター文字列
        """
        if self.filter_text != text:
            self.filter_text = text
            self._notify('filter', text)
            logger.debug(f"Filter set to: {text}")
    
    def set_view_mode(self, mode: str) -> None:
        """
        ビューモードを設定。
        
        Args:
            mode: "list", "grid", "tree" など
        """
        if self.view_mode != mode:
            self.view_mode = mode
            self._notify('view_mode', mode)
            logger.debug(f"View mode changed to: {mode}")
    
    # ==================== Observer パターン ====================
    
    def subscribe(self, event_name: str, callback) -> None:
        """
        状態変更時のコールバックを登録。
        
        Args:
            event_name: イベント名（'selection', 'expansion', 'sort', 'filter', 'view_mode'）
            callback: コールバック関数（引数: event_data）
        """
        if event_name in self._observers:
            self._observers[event_name].append(callback)
            logger.debug(f"Subscribed to {event_name}")
    
    def unsubscribe(self, event_name: str, callback) -> None:
        """
        コールバック登録を解除。
        
        Args:
            event_name: イベント名
            callback: 登録済みのコールバック関数
        """
        if event_name in self._observers and callback in self._observers[event_name]:
            self._observers[event_name].remove(callback)
            logger.debug(f"Unsubscribed from {event_name}")
    
    def _notify(self, event_name: str, data: Any) -> None:
        """
        登録済みのコールバックを実行。
        
        Args:
            event_name: イベント名
            data: イベントデータ
        """
        if event_name in self._observers:
            for callback in self._observers[event_name]:
                try:
                    callback(data)
                except Exception as e:
                    logger.error(f"Error in observer callback for {event_name}: {e}")
