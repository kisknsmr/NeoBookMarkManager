"""
グローバルフォント適用ヘルパー
CustomTkinterウィジェットにデフォルトフォントを自動適用

【使い方】
main.pyまたはmain_window.pyの最初で:
    from gui.font_helper import apply_global_fonts
    apply_global_fonts()
"""
import customtkinter as ctk
from gui.theme import Typography

# オリジナルクラスを保存
_original_CTkLabel = ctk.CTkLabel
_original_CTkButton = ctk.CTkButton
_original_CTkEntry = ctk.CTkEntry
_original_CTkTextbox = ctk.CTkTextbox
_original_CTkCheckBox = ctk.CTkCheckBox
_original_CTkRadioButton = ctk.CTkRadioButton

_fonts_applied = False

def apply_global_fonts():
    """
    CustomTkinterの全ウィジェットにデフォルトフォントを適用
    アプリ起動時に一度だけ呼ぶこと
    """
    global _fonts_applied
    
    if _fonts_applied:
        print("[INFO] グローバルフォントは既に適用済みです")
        return
    
    print("[INFO] グローバルフォント適用中...")
    
    # CTkLabel: 本文フォント
    class CTkLabelWithFont(_original_CTkLabel):
        def __init__(self, *args, **kwargs):
            if 'font' not in kwargs:
                kwargs['font'] = Typography.create_body_font()
            super().__init__(*args, **kwargs)
    
    # CTkButton: ボタンフォント
    class CTkButtonWithFont(_original_CTkButton):
        def __init__(self, *args, **kwargs):
            if 'font' not in kwargs:
                kwargs['font'] = Typography.create_button_font()
            super().__init__(*args, **kwargs)
    
    # CTkEntry: 本文フォント
    class CTkEntryWithFont(_original_CTkEntry):
        def __init__(self, *args, **kwargs):
            if 'font' not in kwargs:
                kwargs['font'] = Typography.create_body_font()
            super().__init__(*args, **kwargs)
    
    # CTkTextbox: 本文フォント
    class CTkTextboxWithFont(_original_CTkTextbox):
        def __init__(self, *args, **kwargs):
            if 'font' not in kwargs:
                kwargs['font'] = Typography.create_body_font()
            super().__init__(*args, **kwargs)
    
    # CTkCheckBox: 本文フォント
    class CTkCheckBoxWithFont(_original_CTkCheckBox):
        def __init__(self, *args, **kwargs):
            if 'font' not in kwargs:
                kwargs['font'] = Typography.create_body_font()
            super().__init__(*args, **kwargs)
    
    # CTkRadioButton: 本文フォント
    class CTkRadioButtonWithFont(_original_CTkRadioButton):
        def __init__(self, *args, **kwargs):
            if 'font' not in kwargs:
                kwargs['font'] = Typography.create_body_font()
            super().__init__(*args, **kwargs)
    
    # モンキーパッチ適用
    ctk.CTkLabel = CTkLabelWithFont
    ctk.CTkButton = CTkButtonWithFont
    ctk.CTkEntry = CTkEntryWithFont
    ctk.CTkTextbox = CTkTextboxWithFont
    ctk.CTkCheckBox = CTkCheckBoxWithFont
    ctk.CTkRadioButton = CTkRadioButtonWithFont
    
    _fonts_applied = True
    print("[OK] グローバルフォント適用完了")
    print(f"     - デフォルトフォント: {Typography.FAMILY_UI}")
    print(f"     - 本文サイズ: {Typography.BODY_MEDIUM}px")
    print(f"     - ボタンサイズ: {Typography.BODY_LARGE}px")

def restore_original_classes():
    """オリジナルクラスに戻す（テスト用）"""
    global _fonts_applied
    
    ctk.CTkLabel = _original_CTkLabel
    ctk.CTkButton = _original_CTkButton
    ctk.CTkEntry = _original_CTkEntry
    ctk.CTkTextbox = _original_CTkTextbox
    ctk.CTkCheckBox = _original_CTkCheckBox
    ctk.CTkRadioButton = _original_CTkRadioButton
    
    _fonts_applied = False
    print("[INFO] オリジナルクラスに戻しました")

# 使用例
if __name__ == "__main__":
    # テストウィンドウ
    apply_global_fonts()
    
    app = ctk.CTk()
    app.title("グローバルフォントテスト")
    app.geometry("500x400")
    
    # フォント指定なしでウィジェット作成
    ctk.CTkLabel(app, text="見出し（自動フォント適用）").pack(pady=10)
    ctk.CTkLabel(app, text="日本語テキスト：あいうえお").pack(pady=5)
    ctk.CTkButton(app, text="ボタン（自動フォント適用）").pack(pady=10)
    ctk.CTkEntry(app, placeholder_text="入力欄（自動フォント適用）").pack(pady=5)
    ctk.CTkCheckBox(app, text="チェックボックス（自動フォント適用）").pack(pady=5)
    
    # 明示的にフォント指定した場合は上書きされる
    custom_font = Typography.create_headline_font()
    ctk.CTkLabel(app, text="カスタム見出し（24px）", font=custom_font).pack(pady=10)
    
    app.mainloop()
