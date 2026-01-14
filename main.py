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

# フォントローダーを初期化（カスタムフォント登録）
FontLoader.initialize()

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
        from PySide6.QtWidgets import QApplication, QMainWindow
        from PySide6.QtCore import Qt
        from gui.theme import get_stylesheet
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
    
    # ===== グローバルスタイルシート適用 =====
    # Material Design 3 ダークテーマをすべてのウィジェットに適用
    stylesheet = get_stylesheet()
    app.setStyleSheet(stylesheet)
    
    # ===== メインウィンドウ作成 =====
    # gui.main_window.MainWindow クラスをインスタンス化
    # （TODO: gui/main_window.py で MainWindow クラスを実装）
    # from gui.main_window import MainWindow
    # main_window = MainWindow()
    # main_window.show()
    
    # 暫定：簡単なテストウィンドウを表示
    test_window = QMainWindow()
    test_window.setWindowTitle("NeoBookMarkManager - PySide6 Preview")
    test_window.resize(800, 600)
    test_window.show()
    
    # ===== イベントループ実行 =====
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    finally:
        # 念のため明示的にクリーンアップ
        cleanup_on_exit()
