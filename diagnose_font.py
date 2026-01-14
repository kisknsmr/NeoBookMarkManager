"""
フォント適用診断ツール（CustomTkinter専用）
実際にどのフォントが適用されているか視覚的に確認
"""
import tkinter as tk
from tkinter import font as tkfont
import customtkinter as ctk
from core.font_loader import FontLoader

def diagnose_fonts():
    """フォント診断ウィンドウを表示"""
    
    # フォントローダー初期化
    print("\n" + "=" * 60)
    print("フォント診断開始")
    print("=" * 60)
    FontLoader.initialize()
    
    # 利用可能なフォント一覧取得
    root = tk.Tk()
    root.withdraw()
    system_fonts = set(tkfont.families())
    
    # チェック対象フォント
    target_fonts = [
        ("Inter Variable Text", "Inter"),
        ("Roboto", "Roboto"),
        ("Noto Sans JP", "Noto Sans JP"),
        ("Yu Gothic UI", "游ゴシック UI（フォールバック）"),
        ("Segoe UI", "Segoe UI（フォールバック）"),
    ]
    
    print("\n[1] システム登録確認:")
    for font_name, display in target_fonts:
        status = "[OK]" if font_name in system_fonts else "[NG]"
        print(f"  {status} {display} ({font_name})")
    
    root.destroy()
    
    # CustomTkinter診断ウィンドウ作成
    print("\n[2] CustomTkinter診断ウィンドウ起動中...")
    ctk.set_appearance_mode("dark")
    
    app = ctk.CTk()
    app.title("フォント診断ツール")
    app.geometry("900x700")
    
    # スクロール可能フレーム
    scroll_frame = ctk.CTkScrollableFrame(
        app,
        width=850,
        height=650,
        fg_color="#1E1E1E"
    )
    scroll_frame.pack(padx=20, pady=20, fill="both", expand=True)
    
    # タイトル
    title = ctk.CTkLabel(
        scroll_frame,
        text="フォント診断：各フォントの表示確認",
        font=ctk.CTkFont(family="Inter Variable Text", size=24, weight="bold"),
        text_color="#FFFFFF"
    )
    title.pack(pady=(0, 20))
    
    # サンプルテキスト
    sample_texts = [
        ("日本語", "あいうえお かきくけこ さしすせそ"),
        ("漢字", "日本語フォント適用確認テスト"),
        ("英数字", "The quick brown fox jumps over 0123456789"),
        ("記号", "!@#$%^&*()_+-=[]{}|;:',.<>?/"),
    ]
    
    # 各フォントでテスト
    for font_name, display_name in target_fonts:
        # セクション区切り
        separator = ctk.CTkFrame(scroll_frame, height=2, fg_color="#BB86FC")
        separator.pack(fill="x", pady=10)
        
        # フォント名表示
        registered = "[登録済み]" if font_name in system_fonts else "[未登録]"
        header = ctk.CTkLabel(
            scroll_frame,
            text=f"{registered} {display_name}",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#BB86FC",
            anchor="w"
        )
        header.pack(fill="x", padx=10, pady=(10, 5))
        
        # 技術名表示
        tech_name = ctk.CTkLabel(
            scroll_frame,
            text=f"内部名: {font_name}",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color="#999999",
            anchor="w"
        )
        tech_name.pack(fill="x", padx=10)
        
        # サンプルテキスト表示
        for label, text in sample_texts:
            try:
                # CTkFontを作成
                test_font = ctk.CTkFont(
                    family=font_name,
                    size=15,
                    weight="normal"
                )
                
                # ラベル表示
                label_widget = ctk.CTkLabel(
                    scroll_frame,
                    text=f"{label}: {text}",
                    font=test_font,
                    text_color="#E0E0E0",
                    anchor="w"
                )
                label_widget.pack(fill="x", padx=20, pady=2)
                
            except Exception as e:
                error_label = ctk.CTkLabel(
                    scroll_frame,
                    text=f"  エラー: {str(e)}",
                    font=ctk.CTkFont(family="Consolas", size=12),
                    text_color="#CF6679",
                    anchor="w"
                )
                error_label.pack(fill="x", padx=20, pady=2)
    
    # 底部に注意書き
    separator = ctk.CTkFrame(scroll_frame, height=2, fg_color="#666666")
    separator.pack(fill="x", pady=20)
    
    note = ctk.CTkLabel(
        scroll_frame,
        text="【確認ポイント】\n"
             "・日本語が明朝体でなくゴシック体になっているか\n"
             "・Noto Sans JPは游ゴシックよりも太さが均一\n"
             "・Interは欧文が洗練されて見える（aの形状など）\n"
             "・フォールバック時は游ゴシックUIまたはSegoe UIが使われる",
        font=ctk.CTkFont(family="Segoe UI", size=13),
        text_color="#999999",
        justify="left",
        anchor="w"
    )
    note.pack(fill="x", padx=10, pady=10)
    
    # 閉じるボタン
    close_btn = ctk.CTkButton(
        scroll_frame,
        text="診断完了・閉じる",
        command=app.quit,
        font=ctk.CTkFont(family="Inter Variable Text", size=14, weight="bold"),
        fg_color="#BB86FC",
        hover_color="#C89DFF",
        height=40
    )
    close_btn.pack(pady=20)
    
    print("\n[3] ウィンドウで各フォントの見た目を確認してください")
    print("    特にNoto Sans JPと游ゴシックUIの違いに注目")
    print("=" * 60)
    
    app.mainloop()
    
    # クリーンアップ
    FontLoader.cleanup()
    print("\n診断終了")

if __name__ == "__main__":
    diagnose_fonts()
