"""NeoBookMarkManager - メインエントリポイント

PySide6 (Qt6) を使用したクロスプラットフォームデスクトップアプリケーション。
"""

import atexit
import os
import sys
from pathlib import Path

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
        from PySide6.QtWidgets import QApplication
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

    app = QApplication(sys.argv)
    app.setApplicationName("NeoBookMarkManager")
    app.setApplicationVersion("2.0.0")

    # QApplication 作成後に実行する必要がある
    FontLoader.initialize()

    # フォント登録（Qt側）
    noto_family = "Noto Sans JP"
    if noto_family not in QFontDatabase.families():
        noto_path = Path(__file__).parent / "fonts" / "NotoSansJP-VariableFont_wght.ttf"
        if noto_path.exists():
            QFontDatabase.addApplicationFont(str(noto_path))

    if noto_family in QFontDatabase.families():
        app.setFont(QFont(noto_family, 13))

    # グローバルスタイルシート適用
    style_path = Path(__file__).parent / "gui" / "style.qss"
    if style_path.exists():
        with open(style_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    from gui.controllers.ControllerMainWindow import MainWindow

    try:
        main_window = MainWindow()
        main_window.show()
        print("[INFO] MainWindow created and shown, entering event loop...")
    except Exception as e:
        import traceback

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
