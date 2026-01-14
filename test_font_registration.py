"""
フォント登録テストスクリプト
Windowsシステムにフォントが正しく登録されているか確認
"""
import sys
import tkinter as tk
from tkinter import font as tkfont
from core.font_loader import FontLoader

def test_font_registration():
    """フォント登録をテスト"""
    print("=" * 60)
    print("フォント登録テスト")
    print("=" * 60)
    
    # フォントローダーを初期化
    print("\n[1] フォントローダー初期化中...")
    FontLoader.initialize()
    
    # 登録情報を表示
    info = FontLoader.get_font_info()
    print(f"\n初期化状態: {info['initialized']}")
    print(f"フォントディレクトリ: {info['font_dir']}")
    print(f"\n登録されたフォント:")
    for name, path in info['available_fonts'].items():
        print(f"  - {name}")
    
    # Tkinterで利用可能なフォントを確認
    print("\n[2] Tkinterで利用可能なフォントをチェック中...")
    root = tk.Tk()
    root.withdraw()  # ウィンドウを表示しない
    
    available_fonts = sorted(tkfont.families())
    
    # カスタムフォントが登録されているか確認
    print("\nカスタムフォント登録状況:")
    check_fonts = [
        ("Inter Variable Text", "Inter"),
        ("Roboto", "Roboto"),
        ("Noto Sans JP", "Noto Sans JP")
    ]
    
    for font_name, display_name in check_fonts:
        if font_name in available_fonts:
            print(f"  [OK] {display_name} ({font_name}) - 登録成功！")
        else:
            print(f"  [NG] {display_name} ({font_name}) - 未登録")
    
    # 類似フォント名を検索
    print("\n関連フォント名:")
    for font_name in available_fonts:
        if any(keyword in font_name.lower() for keyword in ["inter", "roboto", "noto"]):
            print(f"  - {font_name}")
    
    root.destroy()
    
    # クリーンアップ
    print("\n[3] クリーンアップ中...")
    FontLoader.cleanup()
    
    print("\n" + "=" * 60)
    print("テスト完了")
    print("=" * 60)

if __name__ == "__main__":
    test_font_registration()
