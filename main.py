import sys
import os
import atexit

# Ensure the core/gui/services modules are importable
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# グローバルフォント適用（全ウィジェットに自動適用）
from gui.font_helper import apply_global_fonts
apply_global_fonts()

from gui.main_window import App
from core.font_loader import FontLoader

# アプリケーション終了時にフォントをクリーンアップ
atexit.register(FontLoader.cleanup)

if __name__ == "__main__":
    app = App()
    try:
        app.mainloop()
    finally:
        # 念のため明示的にクリーンアップ
        FontLoader.cleanup()
