"""
PySide6 Material Design 3 準拠 UI コンポーネント

【設計原則】
- ColorTokens, Typography, Elevation を使用
- カスタムフォント（Inter/Roboto/Noto Sans JP）を自動適用
- バリアント（primary, secondary, text）を明確に区別
- インタラクション状態（hover, pressed, disabled）を実装
- アクセシビリティを考慮

【PySide6移行】
- QPushButton: StyledButton として実装
- QFrame: StyledCard として実装
- QSS スタイルシートで統一的に管理
"""

from typing import Optional, Callable
from PySide6.QtWidgets import QPushButton, QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QCursor
from gui.theme import ColorTokens, Typography, Elevation, Spacing, Colors, create_qfont


class StyledButton(QPushButton):
    """
    Material Design 3 準拠ボタン
    カスタムフォント自動適用
    
    バリアント:
    - primary: メインアクション（塗りつぶし）
    - secondary: 副次アクション（アウトライン）
    - text: テキストのみ
    - danger: 危険なアクション（削除等）
    - success: 成功アクション（保存等）
    """
    
    def __init__(self, parent: Optional[QWidget] = None, text: str = "", 
                 command: Optional[Callable] = None, 
                 variant: str = "primary", **kwargs):
        
        super().__init__(text, parent)
        
        # カスタムフォント適用
        self.setFont(create_qfont(family="Noto Sans JP", size=14, bold=True))
        
        # バリアント別スタイル定義
        if variant == "primary":
            # メインアクション（開く、保存、分類実行など）
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ColorTokens.PRIMARY};
                    color: {ColorTokens.ON_PRIMARY};
                    border: none;
                    border-radius: {Elevation.RADIUS_M}px;
                    padding: 8px 16px;
                    min-height: 36px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {ColorTokens.PRIMARY_HOVER};
                }}
                QPushButton:pressed {{
                    background-color: {ColorTokens.PRIMARY_PRESSED};
                }}
                QPushButton:disabled {{
                    background-color: {ColorTokens.PRIMARY_DISABLED};
                    color: {ColorTokens.TEXT_DISABLED};
                }}
            """)
        
        elif variant == "secondary":
            # 補助アクション（ニュートラル、アウトライン）
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {ColorTokens.TEXT_PRIMARY};
                    border: 1px solid {ColorTokens.BORDER_DEFAULT};
                    border-radius: {Elevation.RADIUS_M}px;
                    padding: 7px 15px;
                    min-height: 36px;
                }}
                QPushButton:hover {{
                    background-color: {ColorTokens.SURFACE_3};
                    border: 1px solid {ColorTokens.BORDER_FOCUSED};
                }}
                QPushButton:pressed {{
                    background-color: {ColorTokens.SURFACE_2};
                }}
            """)
        
        elif variant == "text":
            # テキストのみ
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {ColorTokens.TEXT_PRIMARY};
                    border: none;
                    border-radius: {Elevation.RADIUS_M}px;
                    padding: 8px 16px;
                }}
                QPushButton:hover {{
                    background-color: {ColorTokens.HOVER_OVERLAY};
                }}
                QPushButton:pressed {{
                    background-color: {ColorTokens.PRESSED_OVERLAY};
                }}
            """)
        
        elif variant == "danger":
            # 破壊的アクション（削除のみ）
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ColorTokens.ERROR};
                    color: {ColorTokens.ON_PRIMARY};
                    border: none;
                    border-radius: {Elevation.RADIUS_M}px;
                    padding: 8px 16px;
                    min-height: 36px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: #E07585;
                }}
                QPushButton:pressed {{
                    background-color: #CF6679;
                }}
            """)
        
        else:  # デフォルトはsecondary
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {ColorTokens.TEXT_PRIMARY};
                    border: 1px solid {ColorTokens.BORDER_DEFAULT};
                    border-radius: {Elevation.RADIUS_M}px;
                    padding: 7px 15px;
                    min-height: 36px;
                }}
                QPushButton:hover {{
                    background-color: {ColorTokens.SURFACE_3};
                }}
            """)
        
        # クリックハンドラ設定
        if command:
            self.clicked.connect(command)
        
        # カーソル設定
        self.setCursor(QCursor(Qt.PointingHandCursor))


class StyledCard(QFrame):
    """
    Material Design 3 準拠カード
    
    Surface階層を表現するコンテナ
    """
    def __init__(self, parent: Optional[QWidget] = None, **kwargs):
        super().__init__(parent)
        
        # スタイルシート設定
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {ColorTokens.SURFACE_2};
                border: 1px solid {ColorTokens.BORDER_DEFAULT};
                border-radius: {Elevation.RADIUS_M}px;
                padding: {Spacing.M}px;
            }}
        """)
        
        # フレームスタイル
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Plain)


class SectionHeader(QLabel):
    """
    セクション見出しコンポーネント
    """
    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        
        # フォント設定
        self.setFont(create_qfont(family="Noto Sans JP", size=18, bold=True))
        
        # スタイル設定
        self.setStyleSheet(f"""
            QLabel {{
                color: {ColorTokens.TEXT_PRIMARY};
                background-color: transparent;
                padding: 8px 0px;
            }}
        """)


class SubHeader(QLabel):
    """
    小見出しコンポーネント
    """
    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        
        # フォント設定
        self.setFont(create_qfont(family="Noto Sans JP", size=14, bold=True))
        
        # スタイル設定
        self.setStyleSheet(f"""
            QLabel {{
                color: {ColorTokens.TEXT_SECONDARY};
                background-color: transparent;
                padding: 4px 0px;
            }}
        """)


class BodyText(QLabel):
    """
    本文テキストコンポーネント
    """
    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        
        # フォント設定
        self.setFont(create_qfont(family="Noto Sans JP", size=13, bold=False))
        
        # スタイル設定
        self.setStyleSheet(f"""
            QLabel {{
                color: {ColorTokens.TEXT_PRIMARY};
                background-color: transparent;
            }}
        """)
        
        # テキストの折り返し有効化
        self.setWordWrap(True)

