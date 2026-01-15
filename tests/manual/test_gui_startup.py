#!/usr/bin/env python3
"""Test GUI startup and bookmark loading"""

import sys
import os
from pathlib import Path

# Set up path
project_dir = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_dir))

from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow
from core.storage import load_bookmarks

def main():
    """Test GUI startup"""
    
    # Create app
    app = QApplication(sys.argv)
    
    # Test loading bookmarks
    bookmark_file = project_dir / 'tests' / 'fixtures' / 'sampleHTML' / 'bookmarks_2026_01_10.html'
    if bookmark_file.exists():
        print(f"[INFO] Loading bookmarks from {bookmark_file}")
        root, rules, rules_path = load_bookmarks(str(bookmark_file))
        print(f"[OK] Bookmarks loaded: {len(root.children)} items")
    else:
        print(f"[WARN] Bookmark file not found: {bookmark_file}")
        root = None
    
    # Create main window
    try:
        main_window = MainWindow()
        print("[OK] MainWindow created")
        
        # Load bookmarks into GUI
        if root:
            main_window.current_folder = root
            main_window._refresh_content()
            main_window._build_search_index()
            print("[OK] Bookmarks loaded into GUI")
            print(f"[INFO] Root folder has {len(root.children)} children")
        
        # Show window
        main_window.show()
        print("[OK] MainWindow displayed")
        print("[INFO] GUI Test successful! Close window to exit.")
        
        # Run app
        sys.exit(app.exec())
    except Exception as e:
        print(f"[ERROR] GUI startup failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
