"""NeoBookMarkManager - メインエントリポイント

PySide6 (Qt6) を使用したクロスプラットフォームデスクトップアプリケーション。
"""

import atexit
import os
import sys
from pathlib import Path

# Prevent __pycache__ directory creation (集約設定)
# この設定により、どの方法で実行しても __pycache__ が生成されません
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

# Ensure the core/gui/services modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.UtilFontLoader import FontLoader


def cleanup_on_exit() -> None:
    """アプリケーション終了時のクリーンアップ処理"""

    FontLoader.cleanup()


atexit.register(cleanup_on_exit)


def main() -> None:
    """アプリケーションのメインエントリポイント"""

    try:
        from PySide6.QtGui import QFont, QFontDatabase
        from PySide6.QtWidgets import QApplication, QSplashScreen
        from PySide6.QtCore import Qt, QTimer
    except ImportError as e:
        print("=" * 60)
        print("エラー: PySide6 がインストールされていません")
        print("=" * 60)
        print(f"詳細: {e}")
        print("\n以下のコマンドでインストールしてください:")
        print("  pip install PySide6")
        print("\nまたは requirements.txt から:")
        print("  pip install -r requirements.txt")
        print("=" * 60)
        raise SystemExit(1)

    # 高DPI対応を有効化
    from PySide6.QtCore import Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)
    
    # アプリケーション情報を設定ファイルから取得
    from config.app_config import APP_NAME_SHORT, VERSION
    
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME_SHORT)
    app.setApplicationVersion(VERSION)

    # QApplication 作成後に実行する必要がある
    FontLoader.initialize()

    # フォント管理システムの初期化（最優先）
    from core.FontManager import FontManager
    FontManager.initialize(app, project_root=Path(__file__).parent)

    # グローバルスタイルシート適用
    style_path = Path(__file__).parent / "gui" / "style.qss"
    if style_path.exists():
        with open(style_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    from PySide6.QtCore import QTimer
    from gui.splash import create_splash_screen
    from config.app_config import (
        SPLASH_APP_NAME,
        SPLASH_VERSION,
        SPLASH_LOADING_MESSAGE,
        SPLASH_WIDTH,
        SPLASH_HEIGHT
    )
    
    # スプラッシュ画面を作成（設定ファイルから情報を取得）
    splash = create_splash_screen(
        app=app,
        app_name=SPLASH_APP_NAME,
        version=SPLASH_VERSION,
        loading_message=SPLASH_LOADING_MESSAGE,
        width=SPLASH_WIDTH,
        height=SPLASH_HEIGHT
    )
    
    from gui.controllers.ControllerMainWindow import MainWindow

    try:
        # スプラッシュ画面を閉じる関数
        def close_splash():
            splash.finish(main_window)
            main_window.show()
            print("[INFO] MainWindow created and shown, entering event loop...")
        
        main_window = MainWindow()
        
        # SessionControllerにスプラッシュ画面を閉じるコールバックを設定
        # HTML読み込み完了時にスプラッシュ画面を閉じる
        if hasattr(main_window, 'session_controller'):
            original_auto_load = main_window.session_controller.auto_load_bookmarks
            
            def auto_load_with_splash(file_path: str):
                try:
                    original_auto_load(file_path)
                finally:
                    # 読み込み完了（成功・失敗問わず）後にスプラッシュ画面を閉じる
                    QTimer.singleShot(100, close_splash)
            
            main_window.session_controller.auto_load_bookmarks = auto_load_with_splash
        
        # メインウィンドウは最初は非表示（HTML読み込み完了後に表示）
        # もしHTMLファイルが存在しない場合は、一定時間後にスプラッシュを閉じる
        def fallback_close_splash():
            if not main_window.isVisible():
                close_splash()
        
        # フォールバック: 3秒後にスプラッシュを閉じる（HTMLファイルがない場合など）
        QTimer.singleShot(3000, fallback_close_splash)
        
    except Exception as e:
        import traceback
        splash.close()
        
        print("=" * 60)
        print("[FATAL] Failed to initialize MainWindow:")
        print(e)
        print("-" * 60)
        traceback.print_exc()
        print("=" * 60)
        raise SystemExit(1)

    raise SystemExit(app.exec())


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup_on_exit()
