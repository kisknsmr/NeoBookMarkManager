"""
PySide6 ダイアログコンポーネント
CustomPromptDialog、FolderSelectDialog をPySide6に実装
"""

from typing import Optional, List, Tuple
from PySide6.QtWidgets import (
    QDialog, QLabel, QTextEdit, QVBoxLayout, QHBoxLayout, 
    QPushButton, QListWidget, QListWidgetItem, QWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from gui.theme import ColorTokens, Typography, create_qfont
from core.model import Node
from gui.ui_kit import StyledButton


class CustomPromptDialog(QDialog):
    """
    プロンプト入力ダイアログ
    以前のプロンプト履歴表示 + 新規プロンプト入力
    """
    
    def __init__(self, parent=None, title="指示入力", previous_prompts=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setGeometry(100, 100, 500, 400)
        self.previous_prompts = previous_prompts or []
        self.result = None
        
        self._build_ui()
    
    def _build_ui(self):
        """UIを構築"""
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 以前のプロンプト履歴
        if self.previous_prompts:
            history_label = QLabel("現在の指示:")
            history_label.setFont(create_qfont(size=12, bold=True))
            history_label.setStyleSheet(f"color: {ColorTokens.TEXT_SECONDARY};")
            layout.addWidget(history_label)
            
            history_text = QTextEdit()
            history_text.setReadOnly(True)
            history_text.setFont(create_qfont(size=11))
            history_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {ColorTokens.SURFACE_2};
                    color: {ColorTokens.TEXT_PRIMARY};
                    border: 1px solid {ColorTokens.BORDER_DEFAULT};
                    border-radius: 4px;
                    padding: 5px;
                }}
            """)
            
            display_str = "\n".join([f"• {p}" for p in self.previous_prompts])
            history_text.setPlainText(display_str)
            history_text.setMaximumHeight(100)
            layout.addWidget(history_text)
        
        # 新規プロンプト入力
        prompt_label = QLabel("追加の指示を入力:")
        prompt_label.setFont(create_qfont(size=12, bold=True))
        prompt_label.setStyleSheet(f"color: {ColorTokens.TEXT_PRIMARY};")
        layout.addWidget(prompt_label)
        
        self.text_input = QTextEdit()
        self.text_input.setFont(create_qfont(size=11))
        self.text_input.setStyleSheet(f"""
            QTextEdit {{
                background-color: {ColorTokens.SURFACE_2};
                color: {ColorTokens.TEXT_PRIMARY};
                border: 1px solid {ColorTokens.BORDER_DEFAULT};
                border-radius: 4px;
                padding: 8px;
            }}
            QTextEdit:focus {{
                border: 2px solid {ColorTokens.BORDER_FOCUSED};
                padding: 7px;
            }}
        """)
        layout.addWidget(self.text_input)
        
        # ボタンレイアウト
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        ok_btn = StyledButton(text="OK", command=self._accept, variant="primary")
        ok_btn.setMaximumWidth(100)
        btn_layout.addWidget(ok_btn)
        
        cancel_btn = StyledButton(text="キャンセル", command=self._reject, variant="secondary")
        cancel_btn.setMaximumWidth(100)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
    
    def _accept(self):
        """OKが押されたとき"""
        self.result = self.text_input.toPlainText().strip()
        self.accept()
    
    def _reject(self):
        """キャンセルが押されたとき"""
        self.result = None
        self.reject()


class FolderSelectDialog(QDialog):
    """
    フォルダ選択ダイアログ
    ツリー構造内のフォルダを選択
    """
    
    def __init__(self, parent=None, root_node: Node = None, exclude_nodes: Optional[List[Node]] = None):
        super().__init__(parent)
        self.setWindowTitle("フォルダを選択")
        self.setGeometry(100, 100, 500, 400)
        
        self.result = None
        self.root_node = root_node
        self.exclude_nodes = set(exclude_nodes) if exclude_nodes else set()
        
        # フォルダリストを構築
        self.folder_list: List[Tuple[str, Node]] = []
        if root_node:
            self._build_folder_list(root_node, [])
        
        self._build_ui()
        
        # 最初のフォルダを選択
        if self.folder_list:
            self.folder_widget.setCurrentRow(0)
    
    def _build_folder_list(self, node: Node, path: List[str]):
        """フォルダリストを再帰的に構築"""
        if node in self.exclude_nodes:
            return
        
        if node.type == "folder":
            # パス文字列を作成
            if path:
                path_str = " / ".join([p for p in path[1:] if p] + [node.title or "Untitled"])
            else:
                path_str = node.title or "Bookmarks"
            
            self.folder_list.append((path_str, node))
            
            # 子フォルダを再帰的に追加
            for child in getattr(node, 'children', []):
                self._build_folder_list(child, path + [node.title or ""])
    
    def _build_ui(self):
        """UIを構築"""
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 説明ラベル
        label = QLabel("移動先のフォルダを選択してください:")
        label.setFont(create_qfont(size=12, bold=True))
        label.setStyleSheet(f"color: {ColorTokens.TEXT_PRIMARY};")
        layout.addWidget(label)
        
        # フォルダリスト
        self.folder_widget = QListWidget()
        self.folder_widget.setFont(create_qfont(size=11))
        self.folder_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {ColorTokens.SURFACE_1};
                color: {ColorTokens.TEXT_PRIMARY};
                border: 1px solid {ColorTokens.BORDER_DEFAULT};
                border-radius: 4px;
            }}
            QListWidget::item:selected {{
                background-color: {ColorTokens.PRIMARY};
                color: white;
            }}
            QListWidget::item:hover {{
                background-color: {ColorTokens.HOVER_OVERLAY};
            }}
        """)
        
        for path_str, node in self.folder_list:
            item = QListWidgetItem(path_str)
            item.setData(Qt.UserRole, node)
            self.folder_widget.addItem(item)
        
        layout.addWidget(self.folder_widget)
        
        # ボタンレイアウト
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        ok_btn = StyledButton(text="OK", command=self._accept, variant="primary")
        ok_btn.setMaximumWidth(100)
        btn_layout.addWidget(ok_btn)
        
        cancel_btn = StyledButton(text="キャンセル", command=self._reject, variant="secondary")
        cancel_btn.setMaximumWidth(100)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
    
    def _accept(self):
        """OKが押されたとき"""
        current_item = self.folder_widget.currentItem()
        if current_item:
            self.result = current_item.data(Qt.UserRole)
        self.accept()
    
    def _reject(self):
        """キャンセルが押されたとき"""
        self.result = None
        self.reject()
