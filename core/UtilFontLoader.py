"""
カスタムフォント読み込みモジュール
PySide6でカスタムフォントを使用するための機能を提供
"""
import os
import sys
from pathlib import Path
from typing import Optional, List
from PySide6.QtGui import QFontDatabase

class FontLoader:
    """カスタムフォントローダー（PySide6対応）"""
    
    _initialized = False
    _font_dir: Optional[Path] = None
    _registered_fonts: List[str] = []
    
    @classmethod
    def initialize(cls) -> bool:
        """
        フォントローダーを初期化し、fontsディレクトリ内のフォントを登録する
        """
        if cls._initialized:
            return True
            
        # プロジェクトルートからのパスを解決
        base_dir = Path(__file__).parent.parent
        cls._font_dir = base_dir / "fonts"
        
        if not cls._font_dir.exists():
            print(f"[WARN] Font dir not found: {cls._font_dir}")
            return False
            
        print(f"[INFO] Loading fonts from: {cls._font_dir}")
        cls._load_fonts_recursively(cls._font_dir)
        
        cls._initialized = True
        return True
    
    @classmethod
    def _load_fonts_recursively(cls, directory: Path) -> None:
        """ディレクトリ内のフォントファイルを再帰的に登録"""
        for entry in directory.iterdir():
            if entry.is_dir():
                cls._load_fonts_recursively(entry)
            elif entry.suffix.lower() in ('.ttf', '.otf'):
                cls._register_font(entry)

    @classmethod
    def _register_font(cls, font_path: Path) -> bool:
        """PySide6を使用してフォントを登録"""
        path_str = str(font_path.absolute())
        
        # QFontDatabaseを使用してフォントをロード
        font_id = QFontDatabase.addApplicationFont(path_str)
        
        if font_id != -1:
            families = QFontDatabase.applicationFontFamilies(font_id)
            print(f"[OK] Registered font: {font_path.name} -> {families}")
            cls._registered_fonts.append(path_str)
            return True
        else:
            print(f"[ERR] Failed to register font: {font_path.name}")
            return False

    @classmethod
    def cleanup(cls) -> None:
        """
        PySide6ではアプリケーション終了時に自動的にクリーンアップされるため、
        明示的な削除は基本的に不要だが、インターフェース互換性のため残す。
        """
        cls._registered_fonts.clear()
        cls._initialized = False

    @classmethod
    def get_font(cls, family: str, size: int = 12, weight: str = "normal") -> str:
        """フォントファミリー名を返す（PySide6ではQFontで使用）"""
        return family

    @classmethod
    def create_font(cls, family: str = "Noto Sans JP", size: int = 12, weight: str = "normal") -> str:
        """
        互換性のために残されたメソッド。単にファミリー名を返す。
        """
        return family




