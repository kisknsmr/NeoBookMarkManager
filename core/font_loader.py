"""
カスタムフォント読み込みモジュール
CustomTkinterでカスタムフォントを使用するための機能を提供

【重要】
Tkinter/CustomTkinterはOSにインストールされたフォントのみ使用可能。
プロジェクトフォルダに配置しただけでは認識されないため、
Windows API（AddFontResourceEx）を使って動的に登録する。
"""
import os
import sys
from pathlib import Path
from typing import Optional, List
import customtkinter as ctk

# Windows用フォント登録API
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    
    # Windows GDI32.dll関数定義
    gdi32 = ctypes.windll.gdi32
    
    # フォント登録（一時的・プライベート）
    FR_PRIVATE = 0x10
    FR_NOT_ENUM = 0x20
    
    def add_font_resource(font_path: str) -> bool:
        """
        フォントをシステムに一時登録（アプリ終了時に自動削除）
        
        Args:
            font_path: フォントファイルの絶対パス
        
        Returns:
            bool: 登録成功時True
        """
        try:
            # AddFontResourceExW を使用（Unicode対応）
            result = gdi32.AddFontResourceExW(
                font_path,
                FR_PRIVATE,  # プロセスのみで有効
                0
            )
            return result > 0
        except Exception as e:
            print(f"フォント登録エラー: {font_path} - {e}")
            return False
    
    def remove_font_resource(font_path: str) -> bool:
        """
        一時登録したフォントを削除
        
        Args:
            font_path: フォントファイルの絶対パス
        
        Returns:
            bool: 削除成功時True
        """
        try:
            result = gdi32.RemoveFontResourceExW(
                font_path,
                FR_PRIVATE,
                0
            )
            return result > 0
        except Exception as e:
            print(f"フォント削除エラー: {font_path} - {e}")
            return False
else:
    # macOS/Linux用のダミー実装
    def add_font_resource(font_path: str) -> bool:
        print(f"警告: {sys.platform} ではフォント動的登録は非サポート")
        return False
    
    def remove_font_resource(font_path: str) -> bool:
        return False

# CustomTkinterのフォントマネージャー
try:
    from customtkinter.windows.widgets.font import CTkFont
except ImportError:
    CTkFont = None


class FontLoader:
    """カスタムフォントローダー（Windows API対応）"""
    
    _initialized = False
    _font_dir: Optional[Path] = None
    _available_fonts = {
        "Inter Variable Text": None,  # Variable Fontの実際の登録名
        "Roboto": None,
        "Noto Sans JP": None,
    }
    _registered_fonts: List[str] = []  # 登録済みフォントパスのリスト
    
    @classmethod
    def initialize(cls) -> bool:
        """
        フォントシステムを初期化
        フォントファイルをWindowsシステムに動的登録
        
        Returns:
            bool: 初期化が成功したかどうか
        """
        if cls._initialized:
            return True
        
        # フォントディレクトリを検索
        base_path = Path(__file__).parent.parent
        font_dir = base_path / "fonts"
        
        if not font_dir.exists():
            print(f"警告: フォントディレクトリが見つかりません: {font_dir}")
            return False
        
        cls._font_dir = font_dir
        
        # フォントファイルをマッピング
        # 注: Variable Fontの場合、実際のフォント名はファイル名と異なる
        font_files = {
            "Inter Variable Text": "InterVariable.ttf",  # 実際は "Inter Variable Text" として登録される
            "Roboto": "Roboto-VariableFont_wdth,wght.ttf",
            "Noto Sans JP": "NotoSansJP-VariableFont_wght.ttf",
        }
        
        # 各フォントファイルの存在を確認し、システムに登録
        for font_name, filename in font_files.items():
            font_path = font_dir / filename
            if font_path.exists():
                font_path_str = str(font_path.absolute())
                cls._available_fonts[font_name] = font_path_str
                
                # Windowsの場合、フォントをシステムに登録
                if sys.platform == "win32":
                    if add_font_resource(font_path_str):
                        cls._registered_fonts.append(font_path_str)
                        print(f"[OK] フォント登録成功: {font_name} -> {filename}")
                    else:
                        print(f"[NG] フォント登録失敗: {font_name} -> {filename}")
                        # 登録失敗してもパスは保存（フォールバック用）
                else:
                    print(f"フォント検出: {font_name} -> {filename}")
            else:
                print(f"警告: フォントファイルが見つかりません: {filename}")
        
        cls._initialized = True
        
        # Windows: GDI+ にフォント変更を通知
        if sys.platform == "win32" and cls._registered_fonts:
            try:
                # すべてのウィンドウにフォント変更を通知
                HWND_BROADCAST = 0xFFFF
                WM_FONTCHANGE = 0x001D
                ctypes.windll.user32.SendMessageW(HWND_BROADCAST, WM_FONTCHANGE, 0, 0)
                print("[OK] システムにフォント変更を通知")
            except Exception as e:
                print(f"フォント変更通知エラー: {e}")
        
        return True
    
    @classmethod
    def cleanup(cls):
        """
        登録したフォントをシステムから削除（アプリ終了時に呼ぶ）
        """
        if sys.platform == "win32":
            for font_path in cls._registered_fonts:
                if remove_font_resource(font_path):
                    print(f"[OK] フォント削除: {font_path}")
                else:
                    print(f"[NG] フォント削除失敗: {font_path}")
            cls._registered_fonts.clear()
    
    @classmethod
    def get_font_family(cls, preferred: str = "Noto Sans JP") -> str:
        """
        優先フォントファミリーを取得
        
        Args:
            preferred: 優先フォント名 ("Noto Sans JP", "Inter Variable Text", "Roboto")
        
        Returns:
            str: 使用可能なフォントファミリー名
        """
        if not cls._initialized:
            cls.initialize()
        
        # デバッグログ: 要求されたフォント名
        print(f"[DEBUG] FontLoader.get_font_family() 要求: '{preferred}'")
        
        # 優先順位: Noto Sans JP > Inter > Roboto > システムフォント
        # "Inter" エイリアスを "Inter Variable Text" に変換
        if preferred == "Inter":
            preferred = "Inter Variable Text"
            print(f"[DEBUG] 'Inter' → 'Inter Variable Text' に変換")
        
        priority = [preferred, "Noto Sans JP", "Inter Variable Text", "Roboto"]
        print(f"[DEBUG] 検索優先順位: {priority}")
        print(f"[DEBUG] 利用可能フォント: {list(cls._available_fonts.keys())}")
        
        for font_name in priority:
            font_path = cls._available_fonts.get(font_name)
            print(f"[DEBUG] チェック中: '{font_name}' -> {font_path}")
            if font_path:
                # CustomTkinterではフォントファミリー名をそのまま使用
                # Variable fontの場合は自動的に適切なウェイトが選択される
                print(f"[OK] フォント選択: '{font_name}'")
                return font_name
        
        # フォールバック: システムフォント
        fallback = None
        if sys.platform == "win32":
            fallback = "Segoe UI"
        elif sys.platform == "darwin":
            fallback = "SF Pro"
        else:
            fallback = "Ubuntu"
        
        print(f"[WARNING] カスタムフォント見つからず、システムフォントにフォールバック: '{fallback}'")
        return fallback
    
    @classmethod
    def create_font(cls, family: str = "Noto Sans JP", size: int = 17, 
                   weight: str = "normal", **kwargs) -> ctk.CTkFont:
        """
        CustomTkinterフォントオブジェクトを作成
        
        Args:
            family: フォントファミリー名（"Inter"は自動的に"Inter Variable Text"に変換）
            size: フォントサイズ（15以上推奨、Noto Sans JP最適化）
            weight: フォントウェイト ("normal" or "bold")
            **kwargs: その他のCTkFontパラメータ
        
        Returns:
            CTkFont: CustomTkinterフォントオブジェクト
        """
        if not cls._initialized:
            cls.initialize()
        
        # "Inter" エイリアスを変換
        if family == "Inter":
            family = "Inter Variable Text"
        
        # サイズ制約（最小15px、Noto Sans JP + 日本語可読性重視）
        size = max(15, size)
        
        # フォントファミリーを取得
        font_family = cls.get_font_family(family)
        
        # CustomTkinterフォントを作成
        return ctk.CTkFont(
            family=font_family,
            size=size,
            weight=weight,
            **kwargs
        )
    
    @classmethod
    def get_font_info(cls) -> dict:
        """
        利用可能なフォント情報を取得
        
        Returns:
            dict: フォント情報
        """
        if not cls._initialized:
            cls.initialize()
        
        return {
            "font_dir": str(cls._font_dir) if cls._font_dir else None,
            "available_fonts": {
                name: path for name, path in cls._available_fonts.items() 
                if path is not None
            },
            "initialized": cls._initialized,
        }


# モジュール読み込み時に自動初期化
FontLoader.initialize()


# 使用例とテスト
if __name__ == "__main__":
    print("=" * 60)
    print("フォントローダー情報")
    print("=" * 60)
    
    info = FontLoader.get_font_info()
    print(f"\n初期化状態: {info['initialized']}")
    print(f"フォントディレクトリ: {info['font_dir']}")
    print(f"\n利用可能なフォント:")
    for name, path in info['available_fonts'].items():
        print(f"  - {name}")
        print(f"    {path}")
    
    print("\n" + "=" * 60)
    print("フォントファミリーテスト")
    print("=" * 60)
    
    for preferred in ["Inter", "Roboto", "Noto Sans JP", "Unknown"]:
        family = FontLoader.get_font_family(preferred)
        print(f"優先: {preferred:15} -> 使用: {family}")
