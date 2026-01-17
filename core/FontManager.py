"""
Font Manager Module
共通モジュール: Tantal R.D. Bower

プロジェクト全体のフォント管理システム。
Variable Font (Inter, Noto Sans JP) の統一されたレンダリングを提供します。

仕様:
- Variable Fontの登録と管理
- 統一されたフォントウェイト設定（100-900、CSS互換）
- アンチエイリアスとヒンティングの最適化
- 高DPI対応
- プロジェクト全体で一貫したフォント設定

使用方法:
    from core.FontManager import FontManager
    
    app = QApplication(sys.argv)
    FontManager.initialize(app)
    
    # フォントを取得
    font = FontManager.get_ui_font(12)  # UI要素用
    font = FontManager.get_heading_font(16)  # 見出し用
    font = FontManager.get_font(10, 500)  # カスタム
"""

import os
from pathlib import Path
from typing import Optional
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


class FontManager:
    """プロジェクト全体のフォント管理"""
    
    _initialized = False
    _project_root: Optional[Path] = None
    
    @classmethod
    def initialize(cls, app: QApplication, project_root: Optional[Path] = None) -> None:
        """
        アプリ起動時に一度だけ呼ぶ
        
        Args:
            app: QApplicationインスタンス
            project_root: プロジェクトルートのパス（Noneの場合は自動検出）
        """
        if cls._initialized:
            return
        
        if project_root is None:
            # このファイルの位置からプロジェクトルートを推定
            cls._project_root = Path(__file__).parent.parent
        else:
            cls._project_root = project_root
        
        # Variable Fontの登録
        fonts_dir = cls._project_root / "fonts"
        inter_path = fonts_dir / "InterVariable.ttf"
        noto_path = fonts_dir / "NotoSansJP-VariableFont_wght.ttf"
        
        if inter_path.exists():
            QFontDatabase.addApplicationFont(str(inter_path))
        
        if noto_path.exists():
            QFontDatabase.addApplicationFont(str(noto_path))
        
        # アプリ全体のデフォルトフォント設定
        default_font = cls.get_font(13, 400)  # Regular, 13pt
        app.setFont(default_font)
        
        cls._initialized = True
    
    @staticmethod
    def get_font(size: int = 10, weight: int = 400) -> QFont:
        """
        プロジェクト標準フォントを取得
        
        Args:
            size: フォントサイズ (pt)
            weight: 100-900 (CSS互換)
                    300 = Light
                    400 = Regular (推奨)
                    500 = Medium
                    600 = SemiBold (推奨)
                    700 = Bold
        
        Returns:
            QFontインスタンス（最適化済み）
        """
        font = QFont(["Inter", "Noto Sans JP"], size)
        font.setWeight(QFont.Weight(weight))
        # Variable Fontのレンダリング品質向上
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        return font
    
    @staticmethod
    def get_ui_font(size: int = 10) -> QFont:
        """
        UI要素用フォント (Medium)
        
        Args:
            size: フォントサイズ (pt)
        
        Returns:
            QFontインスタンス（ウェイト500）
        """
        return FontManager.get_font(size, 500)
    
    @staticmethod
    def get_heading_font(size: int = 16) -> QFont:
        """
        見出し用フォント (SemiBold)
        
        Args:
            size: フォントサイズ (pt)
        
        Returns:
            QFontインスタンス（ウェイト600）
        """
        return FontManager.get_font(size, 600)
    
    @staticmethod
    def get_body_font(size: int = 10) -> QFont:
        """
        本文用フォント (Regular)
        
        Args:
            size: フォントサイズ (pt)
        
        Returns:
            QFontインスタンス（ウェイト400）
        """
        return FontManager.get_font(size, 400)
    
    @staticmethod
    def get_bold_font(size: int = 10) -> QFont:
        """
        太字フォント (Bold)
        
        Args:
            size: フォントサイズ (pt)
        
        Returns:
            QFontインスタンス（ウェイト700）
        """
        return FontManager.get_font(size, 700)
