"""
PySide6 グローバルフォント適用ヘルパー
QApplication 起動後、全ウィジェットにデフォルトフォントを自動適用

【使い方】
main.py で QApplication 初期化後に呼び出す:
    from PySide6.QtWidgets import QApplication
    from gui.font_helper import apply_global_fonts
    
    app = QApplication(sys.argv)
    apply_global_fonts()
"""

from typing import Optional
from gui.theme import Typography

_fonts_applied = False


def apply_global_fonts() -> None:
    """
    PySide6 アプリケーション全体にグローバルフォントを適用
    
    QApplication 初期化直後に一度だけ呼び出すこと。
    QSS（Qt Style Sheets）を通じてすべてのウィジェットに
    デフォルトフォントを適用します。
    """
    global _fonts_applied
    
    if _fonts_applied:
        print("[INFO] グローバルフォントは既に適用済みです")
        return
    
    print("[INFO] PySide6 グローバルフォント適用中...")
    
    try:
        from PySide6.QtWidgets import QApplication
        from gui.theme import get_stylesheet
        
        app = QApplication.instance()
        if app is None:
            print("[ERROR] QApplication がまだ初期化されていません")
            return
        
        # PySide6 のスタイルシート適用（theme.py で定義済み）
        stylesheet = get_stylesheet()
        app.setStyleSheet(stylesheet)
        
        _fonts_applied = True
        print("[OK] PySide6 グローバルフォント適用完了")
        print(f"     - デフォルトフォント: {Typography.FAMILY_UI}")
        print(f"     - 本文サイズ: {Typography.BODY_MEDIUM}px")
        print(f"     - ボタンサイズ: {Typography.LABEL_LARGE}px")
        
    except ImportError as e:
        print(f"[ERROR] PySide6 インポートエラー: {e}")


def get_default_font(font_type: str = "body"):
    """
    指定したタイプのデフォルト QFont を取得
    
    Args:
        font_type: "body", "button", "headline", "caption" など
    
    Returns:
        QFont: 設定済みのフォントオブジェクト
    """
    from gui.theme import create_qfont
    
    font_map = {
        "body": ("Noto Sans JP", Typography.BODY_MEDIUM, False),
        "button": ("Noto Sans JP", Typography.LABEL_LARGE, True),
        "headline": ("Noto Sans JP", Typography.HEADLINE_LARGE, True),
        "section": ("Noto Sans JP", Typography.TITLE_LARGE, True),
        "caption": ("Noto Sans JP", Typography.LABEL_MEDIUM, False),
    }
    
    if font_type not in font_map:
        font_type = "body"
    
    family, size, bold = font_map[font_type]
    return create_qfont(family=family, size=size, bold=bold)


# 使用例
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QPushButton
    
    app = QApplication(sys.argv)
    apply_global_fonts()
    
    # テストウィンドウ
    window = QMainWindow()
    window.setWindowTitle("PySide6 グローバルフォントテスト")
    window.resize(500, 400)
    
    central_widget = QWidget()
    layout = QVBoxLayout(central_widget)
    
    # ラベル
    label1 = QLabel("見出し（自動フォント適用）")
    label1.setFont(get_default_font("headline"))
    layout.addWidget(label1)
    
    label2 = QLabel("日本語テキスト：あいうえお")
    label2.setFont(get_default_font("body"))
    layout.addWidget(label2)
    
    # ボタン
    button = QPushButton("ボタン（自動フォント適用）")
    button.setFont(get_default_font("button"))
    layout.addWidget(button)
    
    window.setCentralWidget(central_widget)
    window.show()
    
    sys.exit(app.exec())
