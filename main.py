"""
NeoBookMarkManager - メインエントリポイント
PySide6 (Qt6) を使用したクロスプラットフォームデスクトップアプリケーション

【実装状況】
- PySide6 依存関係ファイルは更新済み（requirements.txt）
- theme.py に get_stylesheet() 等のPySide6ヘルパー関数を追加
- gui/main_window.py は CustomTkinter → PySide6 への移行が必要（後続タスク）
"""

import sys
import os
import atexit
from pathlib import Path

# Ensure the core/gui/services modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ===== フォント初期化 =====
from core.font_loader import FontLoader

# フォントローダー初期化（※QApplication作成後に実行するためここではスキップ）
# FontLoader.initialize()

# アプリケーション終了時にフォントをクリーンアップ
def cleanup_on_exit():
    """アプリケーション終了時のクリーンアップ処理"""
    FontLoader.cleanup()

atexit.register(cleanup_on_exit)


def main():
    """
    アプリケーションのメインエントリポイント
    
    1. QApplication を初期化
    2. グローバルスタイルシートを適用
    3. メインウィンドウを作成・表示
    4. イベントループを実行
    
    【PySide6 インポート】
    PySide6 がまだインストールされていない場合、
    以下のコマンドでインストールしてください：
        pip install PySide6
    """
    
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFontDatabase, QFont
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
        sys.exit(1)
    
    # ===== QApplication 作成 =====
    # QApplication はアプリケーション全体の制御と設定を管理
    app = QApplication(sys.argv)
    
    # ===== アプリケーション設定 =====
    app.setApplicationName("NeoBookMarkManager")
    app.setApplicationVersion("2.0.0")

    # ===== フォントローダー初期化 =====
    # QApplication作成後に実行する必要がある
    FontLoader.initialize()

    # ===== フォント登録（Qt側） =====
    # QFontDatabase にフォントを登録してからアプリ全体のフォントを設定
    noto_family = "Noto Sans JP"
    if noto_family not in QFontDatabase.families():
        noto_path = Path(__file__).parent / "fonts" / "NotoSansJP-VariableFont_wght.ttf"
        if noto_path.exists():
            QFontDatabase.addApplicationFont(str(noto_path))

    if noto_family in QFontDatabase.families():
        app.setFont(QFont(noto_family, 13))
    
    # ===== グローバルスタイルシート適用 =====
    # Material Design 3 ダークテーマをすべてのウィジェットに適用
    style_path = Path(__file__).parent / "gui" / "style.qss"
    if style_path.exists():
        with open(style_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    
    # ===== メインウィンドウ作成 =====
    from gui.main_window import MainWindow
    try:
        main_window = MainWindow()
        main_window.show()
        print("[INFO] MainWindow created and shown, entering event loop...")
    except Exception as e:
        import traceback
        print("="*60)
        print("[FATAL] Failed to initialize MainWindow:")
        print(e)
        print("-" * 60)
        traceback.print_exc()
        print("="*60)
        sys.exit(1)
    
    # ===== イベントループ実行 =====
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    finally:
        # 念のため明示的にクリーンアップ
        cleanup_on_exit()
