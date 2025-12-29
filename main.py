import sys
import os

# Ensure the core/gui/services modules are importable
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from gui.main_window import App

if __name__ == "__main__":
    app = App()
    app.mainloop()
