"""
実行中アプリのフォント検証スクリプト
main_window.pyの実際のウィジェットが使用しているフォントを解析
"""
import tkinter as tk
from tkinter import font as tkfont
import customtkinter as ctk
from gui.main_window import App

def inspect_widget_fonts(widget, depth=0, max_depth=3):
    """ウィジェットツリーを再帰的に走査してフォント情報を取得"""
    results = []
    indent = "  " * depth
    
    try:
        widget_type = widget.__class__.__name__
        
        # フォント情報取得を試みる
        font_info = "フォント情報なし"
        try:
            if hasattr(widget, 'cget'):
                font_obj = widget.cget('font')
                if font_obj:
                    if isinstance(font_obj, ctk.CTkFont):
                        font_info = f"CTkFont(family='{font_obj.cget('family')}', size={font_obj.cget('size')})"
                    elif isinstance(font_obj, tuple):
                        font_info = f"Tuple: {font_obj}"
                    else:
                        font_info = f"Font: {font_obj}"
        except:
            pass
        
        # テキスト内容取得（あれば）
        text_content = ""
        try:
            if hasattr(widget, 'cget'):
                text = widget.cget('text')
                if text and len(str(text)) > 0:
                    text_content = f" | text='{str(text)[:30]}...'" if len(str(text)) > 30 else f" | text='{text}'"
        except:
            pass
        
        result_line = f"{indent}{widget_type}{text_content} -> {font_info}"
        results.append(result_line)
        
        # 子ウィジェットを探索
        if depth < max_depth:
            try:
                children = widget.winfo_children()
                for child in children:
                    results.extend(inspect_widget_fonts(child, depth + 1, max_depth))
            except:
                pass
                
    except Exception as e:
        results.append(f"{indent}エラー: {str(e)}")
    
    return results

def analyze_app_fonts():
    """アプリケーションのフォント使用状況を解析"""
    print("\n" + "=" * 70)
    print("実行中アプリのフォント検証")
    print("=" * 70)
    
    print("\n[INFO] アプリケーション起動中...")
    app = App()
    
    # メインウィンドウのフォント情報を収集
    print("\n[1] ウィジェットツリー解析:")
    print("-" * 70)
    
    font_results = inspect_widget_fonts(app, max_depth=4)
    
    # フォントファミリーの統計
    family_count = {}
    for line in font_results:
        if "family=" in line:
            # family='...' を抽出
            start = line.find("family='") + 8
            end = line.find("'", start)
            if start > 7 and end > start:
                family = line[start:end]
                family_count[family] = family_count.get(family, 0) + 1
    
    # 結果表示
    for line in font_results[:50]:  # 最初の50件のみ表示
        print(line)
    
    if len(font_results) > 50:
        print(f"\n... 他 {len(font_results) - 50} 件のウィジェット")
    
    print("\n" + "-" * 70)
    print("[2] フォントファミリー使用統計:")
    print("-" * 70)
    
    if family_count:
        sorted_families = sorted(family_count.items(), key=lambda x: x[1], reverse=True)
        for family, count in sorted_families:
            status = ""
            if "Inter" in family:
                status = " <- [カスタムフォント: Inter]"
            elif "Roboto" in family:
                status = " <- [カスタムフォント: Roboto]"
            elif "Noto Sans JP" in family:
                status = " <- [カスタムフォント: Noto Sans JP]"
            elif "Yu Gothic" in family or "游ゴシック" in family:
                status = " <- [システムフォント: 游ゴシック]"
            elif "Segoe UI" in family:
                status = " <- [システムフォント: Segoe UI]"
            else:
                status = " <- [その他]"
            
            print(f"  {family}: {count}回{status}")
    else:
        print("  フォント情報を取得できませんでした")
    
    print("\n" + "=" * 70)
    print("[判定]")
    
    # 判定ロジック
    inter_used = any("Inter" in f for f in family_count.keys())
    noto_used = any("Noto Sans JP" in f for f in family_count.keys())
    roboto_used = any("Roboto" in f for f in family_count.keys())
    fallback_used = any(f in ["Yu Gothic UI", "Segoe UI", "游ゴシック UI"] for f in family_count.keys())
    
    if inter_used or noto_used or roboto_used:
        print("✓ カスタムフォントが適用されています")
        if inter_used:
            print("  - Inter Variable Text: 検出")
        if roboto_used:
            print("  - Roboto: 検出")
        if noto_used:
            print("  - Noto Sans JP: 検出")
    else:
        print("✗ カスタムフォントが適用されていません")
    
    if fallback_used:
        print("! システムフォントへのフォールバックも検出されました")
        print("  一部ウィジェットでカスタムフォント指定が漏れている可能性があります")
    
    print("=" * 70)
    print("\n[INFO] ウィンドウを閉じて終了してください")
    
    app.mainloop()
    
    # クリーンアップ
    from core.font_loader import FontLoader
    FontLoader.cleanup()

if __name__ == "__main__":
    analyze_app_fonts()
