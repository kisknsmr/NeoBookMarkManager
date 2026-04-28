"""
PySide6 GUI Dialogs - Dialog Components Module

This module contains all dialog components for the NeoBookMarkManager application.

Dialogs:
- CustomPromptDialog: AI instruction input with history
- AiProgressDialog: AI processing progress with cancellation
- AiReviewDialog: AI proposal review and selection
- RestoreDialog: Backup restore selection
- TagEditDialog: Local tag editing
- FolderSelectDialog: Folder selection from tree
- BookmarkEditDialog: Bookmark title and URL editing
- DomainConsolidationDialog: Domain consolidation settings
"""

from typing import Optional, List, Dict, Any, Tuple
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QProgressBar,
    QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from core.ModelBookmark import Node
from core.FontManager import FontManager
from gui.UtilGuiResources import ColorTokens, create_qfont


# ==================== Dialogs ====================

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
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._accept)
        ok_btn.setObjectName("primaryButton")
        ok_btn.setMaximumWidth(100)
        btn_layout.addWidget(ok_btn)
        
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self._reject)
        cancel_btn.setObjectName("secondaryButton")
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


class AiProgressDialog(QDialog):
    """AI処理の進捗表示＋キャンセル（チャンク境界でキャンセルされる想定）。"""

    def __init__(self, parent: Optional[QWidget] = None, title: str = "AI処理", total: int = 0):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(520)
        self._cancelled = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setFont(FontManager.get_heading_font(13))
        layout.addWidget(title_label)

        self.status_label = QLabel("準備中...")
        self.status_label.setFont(FontManager.get_body_font(11))
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, max(0, int(total)))
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.traffic_label = QLabel("")
        self.traffic_label.setFont(FontManager.get_body_font(10))
        self.traffic_label.setStyleSheet(f"color: {ColorTokens.TEXT_SECONDARY};")
        layout.addWidget(self.traffic_label)

        btns = QHBoxLayout()
        btns.addStretch()
        self.cancel_btn = QPushButton("キャンセル")
        self.cancel_btn.setObjectName("ghostButton")
        self.cancel_btn.clicked.connect(self._on_cancel)
        btns.addWidget(self.cancel_btn)
        layout.addLayout(btns)

    def _on_cancel(self) -> None:
        self._cancelled = True
        try:
            self.cancel_btn.setEnabled(False)
        except Exception:
            pass
        self.status_label.setText("キャンセル要求を送信しました。次の中断点で停止します…")

    def is_cancelled(self) -> bool:
        return bool(self._cancelled)

    def update_progress(self, processed: int, total: int, sent_bytes: int, recv_bytes: int) -> None:
        self.progress.setRange(0, max(0, int(total)))
        self.progress.setValue(int(processed))
        self.status_label.setText(f"処理中: {processed}/{total}")
        self.traffic_label.setText(f"送信: {sent_bytes:,} bytes / 受信: {recv_bytes:,} bytes")


class AiReviewDialog(QDialog):
    """
    AI提案のレビュー（選別適用）。
    - confidence 昇順を初期表示（不安なものを上に）
    """

    def __init__(self, parent: Optional[QWidget] = None, rows: Optional[List[Dict[str, Any]]] = None):
        super().__init__(parent)
        self.setWindowTitle("AI提案のレビュー")
        self.setMinimumWidth(980)
        self.setMinimumHeight(520)
        self._rows: List[Dict[str, Any]] = rows or []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QLabel("適用する項目を選択してください（confidenceが低い順に表示）")
        header.setFont(FontManager.get_heading_font(12))
        layout.addWidget(header)

        controls = QHBoxLayout()
        self.chk_select_all = QCheckBox("すべて選択")
        self.chk_select_all.setChecked(True)
        self.chk_select_all.stateChanged.connect(self._on_select_all)
        controls.addWidget(self.chk_select_all)

        self.btn_exclude_low = QPushButton("confidence < 0.8 を一括除外")
        self.btn_exclude_low.setObjectName("secondaryButton")
        self.btn_exclude_low.clicked.connect(self._exclude_low_confidence)
        controls.addWidget(self.btn_exclude_low)

        self.chk_send_excluded = QCheckBox("除外項目を _AI/Review に送る")
        self.chk_send_excluded.setChecked(True)
        controls.addWidget(self.chk_send_excluded)
        controls.addStretch()
        layout.addLayout(controls)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["適用", "元フォルダ", "提案先", "タイトル", "URL", "confidence", "reason"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.setObjectName("ghostButton")
        cancel_btn.clicked.connect(self.reject)
        apply_btn = QPushButton("選択した項目を適用")
        apply_btn.setObjectName("primaryButton")
        apply_btn.clicked.connect(self.accept)
        btns.addWidget(cancel_btn)
        btns.addWidget(apply_btn)
        layout.addLayout(btns)

        self._populate()

    def _populate(self) -> None:
        # confidence昇順
        self._rows.sort(key=lambda r: float(r.get("confidence", 1.0)))
        self.table.setRowCount(len(self._rows))
        for i, r in enumerate(self._rows):
            apply_item = QTableWidgetItem("")
            apply_item.setFlags(apply_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # 低confidenceは初期で除外
            try:
                conf = float(r.get("confidence", 0.0))
            except Exception:
                conf = 0.0
            apply_item.setCheckState(Qt.CheckState.Checked if conf >= 0.8 else Qt.CheckState.Unchecked)
            self.table.setItem(i, 0, apply_item)

            self.table.setItem(i, 1, QTableWidgetItem(r.get("from_folder", "") or ""))
            self.table.setItem(i, 2, QTableWidgetItem(r.get("to_folder", "") or ""))
            self.table.setItem(i, 3, QTableWidgetItem(r.get("title", "") or ""))
            self.table.setItem(i, 4, QTableWidgetItem(r.get("url", "") or ""))
            self.table.setItem(i, 5, QTableWidgetItem(f'{float(r.get("confidence", 0.0)):.2f}'))
            self.table.setItem(i, 6, QTableWidgetItem(r.get("reason", "") or ""))

    def _on_select_all(self) -> None:
        checked = self.chk_select_all.isChecked()
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _exclude_low_confidence(self) -> None:
        for i, r in enumerate(self._rows):
            try:
                conf = float(r.get("confidence", 0.0))
            except Exception:
                conf = 0.0
            if conf < 0.8:
                item = self.table.item(i, 0)
                if item:
                    item.setCheckState(Qt.CheckState.Unchecked)

    def get_selected_rows(self) -> List[Dict[str, Any]]:
        selected: List[Dict[str, Any]] = []
        for i, r in enumerate(self._rows):
            item = self.table.item(i, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                selected.append(r)
        return selected

    def should_send_excluded_to_review(self) -> bool:
        return bool(self.chk_send_excluded.isChecked())


class RestoreDialog(QDialog):
    """バックアップ一覧から復元先（世代）を選ぶダイアログ。"""

    def __init__(self, parent: Optional[QWidget] = None, backups: Optional[List[str]] = None):
        super().__init__(parent)
        self.setWindowTitle("バックアップから復元")
        self.setMinimumWidth(560)
        self._backups = backups or []
        self.selected_backup: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        desc = QLabel("復元する世代を選択してください（復元後、アプリは再起動されます）。")
        desc.setWordWrap(True)
        desc.setFont(FontManager.get_body_font(11))
        layout.addWidget(desc)

        self.list_widget = QListWidget()
        for b in self._backups:
            self.list_widget.addItem(QListWidgetItem(b))
        if self._backups:
            self.list_widget.setCurrentRow(0)
        layout.addWidget(self.list_widget, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.setObjectName("ghostButton")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("復元")
        ok_btn.setObjectName("dangerButton")
        ok_btn.clicked.connect(self._accept)
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        layout.addLayout(btns)

    def _accept(self) -> None:
        item = self.list_widget.currentItem()
        if not item:
            return
        self.selected_backup = item.text()
        self.accept()


class TagEditDialog(QDialog):
    """ローカルタグ編集（カンマ区切り）。"""

    def __init__(self, parent: Optional[QWidget] = None, *, current_tags: Optional[List[str]] = None):
        super().__init__(parent)
        self.setWindowTitle("タグ編集")
        self.setMinimumWidth(600)
        self._result: Optional[List[str]] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        label = QLabel("タグをカンマ区切りで入力してください（例: python, ai, news）")
        label.setWordWrap(True)
        label.setFont(FontManager.get_body_font(11))
        layout.addWidget(label)

        self.input = QLineEdit()
        self.input.setText(", ".join(current_tags or []))
        layout.addWidget(self.input)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.setObjectName("ghostButton")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("保存")
        ok_btn.setObjectName("primaryButton")
        ok_btn.clicked.connect(self._accept)
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        layout.addLayout(btns)

    def _accept(self) -> None:
        raw = self.input.text()
        tags = [t.strip() for t in (raw or "").split(",") if t.strip()]
        self._result = tags
        self.accept()

    def get_tags(self) -> List[str]:
        return self._result or []


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
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._accept)
        ok_btn.setObjectName("primaryButton")
        ok_btn.setMaximumWidth(100)
        btn_layout.addWidget(ok_btn)
        
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self._reject)
        cancel_btn.setObjectName("secondaryButton")
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


class BookmarkEditDialog(QDialog):
    """
    ブックマークのタイトルとURLを編集するための統合ダイアログ。
    """

    def __init__(self, parent=None, node: Node | None = None):
        super().__init__(parent)
        self.node = node
        self.setWindowTitle("ブックマークの編集")
        self.setMinimumWidth(600)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # タイトル入力
        title_layout = QVBoxLayout()
        title_label = QLabel("タイトル:")
        title_label.setFont(create_qfont(size=10, bold=True))
        self.title_input = QLineEdit()
        self.title_input.setText(getattr(self.node, "title", "") or "")
        self.title_input.setPlaceholderText("タイトルを入力してください")
        title_layout.addWidget(title_label)
        title_layout.addWidget(self.title_input)
        layout.addLayout(title_layout)

        # URL入力
        url_layout = QVBoxLayout()
        url_label = QLabel("URL:")
        url_label.setFont(create_qfont(size=10, bold=True))
        self.url_input = QTextEdit()
        self.url_input.setPlainText(getattr(self.node, "url", "") or "")
        self.url_input.setPlaceholderText("URLを入力してください")
        self.url_input.setMaximumHeight(80)
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        layout.addLayout(url_layout)

        # ボタンエリア
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("キャンセル")
        cancel_btn.setObjectName("ghostButton")
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("保存")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self.accept)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def get_data(self) -> tuple[str, str]:
        """編集後のタイトルとURLを返す"""
        return self.title_input.text().strip(), self.url_input.toPlainText().strip()


class DomainConsolidationDialog(QDialog):
    """ドメイン統計を表示し、統合先を指定するダイアログ"""

    def __init__(self, stats: List[Tuple[str, int]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("ドメイン一括統合")
        self.setMinimumWidth(500)
        self.stats = stats
        self.result_data: tuple[str, str] | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("統合したいドメインを選択してください:")
        title.setFont(create_qfont(size=11, bold=True))
        layout.addWidget(title)

        self.list_widget = QListWidget()
        for domain, count in self.stats:
            item = QListWidgetItem(f"{domain} ({count}件)")
            item.setData(Qt.UserRole, domain)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("作成するフォルダ名:"))
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("例: Google関連, ニュースサイト など")
        folder_layout.addWidget(self.folder_input, 1)
        layout.addLayout(folder_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.setObjectName("ghostButton")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("統合を実行")
        ok_btn.setObjectName("primaryButton")
        ok_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

    def _on_accept(self) -> None:
        selected = self.list_widget.currentItem()
        folder_name = self.folder_input.text().strip()
        if not selected or not folder_name:
            QMessageBox.warning(self, "入力不足", "ドメインの選択とフォルダ名の入力が必要です。")
            return
        self.result_data = (str(selected.data(Qt.UserRole)), folder_name)
        self.accept()
