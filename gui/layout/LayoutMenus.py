"""
Menu bar management for NeoBookMarkManager.

Consolidated module for all menu-related functionality.
"""

from typing import Callable, Dict
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow


class MenuBuilder:
    """Build and manage application menus."""
    
    def __init__(self, main_window: QMainWindow):
        """
        Initialize menu builder.
        
        Args:
            main_window: The main window to attach menus to
        """
        self.main_window = main_window
        self.card_mode_action = None
        self.list_mode_action = None
        self.dual_tree_action = None
    
    def build_menus(self, callbacks: Dict[str, Callable]) -> None:
        """
        Build all menus with the provided callbacks.
        
        Args:
            callbacks: Dictionary of callback functions
                      Keys should match command names (cmd_open, cmd_save, etc.)
        """
        self._create_file_menu(callbacks)
        self._create_edit_menu(callbacks)
        self._create_tools_menu(callbacks)
        self._create_view_menu(callbacks)
    
    def _create_file_menu(self, callbacks: Dict[str, Callable]) -> None:
        """Create File menu."""
        menubar = self.main_window.menuBar()
        file_menu = menubar.addMenu("&File")
        
        open_action = QAction("&Open HTML...", self.main_window)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(callbacks.get("cmd_open", lambda: None))
        file_menu.addAction(open_action)

        save_action = QAction("&Save", self.main_window)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(callbacks.get("cmd_save", lambda: None))
        file_menu.addAction(save_action)

        save_as_action = QAction("Save &As...", self.main_window)
        save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_as_action.triggered.connect(callbacks.get("cmd_save_as", lambda: None))
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self.main_window)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.main_window.close)
        file_menu.addAction(exit_action)
    
    def _create_edit_menu(self, callbacks: Dict[str, Callable]) -> None:
        """Create Edit menu."""
        menubar = self.main_window.menuBar()
        edit_menu = menubar.addMenu("&Edit")
        
        new_folder_action = QAction("New &Folder", self.main_window)
        new_folder_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        new_folder_action.triggered.connect(callbacks.get("cmd_new_folder", lambda: None))
        edit_menu.addAction(new_folder_action)

        new_bookmark_action = QAction("New &Bookmark", self.main_window)
        new_bookmark_action.setShortcut(QKeySequence.StandardKey.New)
        new_bookmark_action.triggered.connect(callbacks.get("cmd_new_bookmark", lambda: None))
        edit_menu.addAction(new_bookmark_action)

        rename_action = QAction("&Rename", self.main_window)
        rename_action.setShortcut(QKeySequence("F2"))
        rename_action.triggered.connect(callbacks.get("cmd_rename", lambda: None))
        edit_menu.addAction(rename_action)

        edit_url_action = QAction("Edit &URL", self.main_window)
        edit_url_action.triggered.connect(callbacks.get("cmd_edit_url", lambda: None))
        edit_menu.addAction(edit_url_action)

        edit_menu.addSeparator()

        move_action = QAction("&Move to Folder...", self.main_window)
        move_action.triggered.connect(callbacks.get("cmd_move_to_folder", lambda: None))
        edit_menu.addAction(move_action)

        move_up_action = QAction("Move &Up", self.main_window)
        move_up_action.setShortcut(QKeySequence("Ctrl+Up"))
        move_up_action.triggered.connect(callbacks.get("cmd_move_up", lambda: None))
        edit_menu.addAction(move_up_action)

        delete_action = QAction("&Delete", self.main_window)
        delete_action.setShortcut(QKeySequence.StandardKey.Delete)
        delete_action.triggered.connect(callbacks.get("cmd_delete", lambda: None))
        edit_menu.addAction(delete_action)
    
    def _create_tools_menu(self, callbacks: Dict[str, Callable]) -> None:
        """Create Tools menu."""
        menubar = self.main_window.menuBar()
        tools_menu = menubar.addMenu("&Tools")
        
        proxy_action = QAction("Use Proxy", self.main_window, checkable=True)
        proxy_action.setChecked(getattr(self.main_window, 'use_proxy', False))
        proxy_action.triggered.connect(
            lambda checked: callbacks.get("set_proxy_flag", lambda x: None)(checked)
        )
        tools_menu.addAction(proxy_action)

        test_proxy_action = QAction("Test Proxy Connection", self.main_window)
        test_proxy_action.triggered.connect(callbacks.get("cmd_check_proxy", lambda: None))
        tools_menu.addAction(test_proxy_action)

        tools_menu.addSeparator()

        classify_action = QAction("Rule-based Classification...", self.main_window)
        classify_action.triggered.connect(callbacks.get("cmd_show_classify_preview", lambda: None))
        tools_menu.addAction(classify_action)

        smart_classify_action = QAction("AI Smart Classification...", self.main_window)
        smart_classify_action.triggered.connect(callbacks.get("cmd_smart_classify", lambda: None))
        tools_menu.addAction(smart_classify_action)

        tools_menu.addSeparator()

        fix_titles_action = QAction("Fix Titles from URL", self.main_window)
        fix_titles_action.triggered.connect(callbacks.get("cmd_fix_titles_from_url", lambda: None))
        tools_menu.addAction(fix_titles_action)
    
    def _create_view_menu(self, callbacks: Dict[str, Callable]) -> None:
        """Create View menu."""
        menubar = self.main_window.menuBar()
        view_menu = menubar.addMenu("&View")
        
        self.card_mode_action = QAction("&Card Mode", self.main_window, checkable=True)
        view_mode = getattr(self.main_window, 'view_mode', 'card')
        self.card_mode_action.setChecked(view_mode == "card")
        self.card_mode_action.triggered.connect(
            lambda: callbacks.get("cmd_set_view_mode", lambda x: None)("card")
        )
        view_menu.addAction(self.card_mode_action)

        self.list_mode_action = QAction("&List Mode", self.main_window, checkable=True)
        self.list_mode_action.setChecked(view_mode == "list")
        self.list_mode_action.triggered.connect(
            lambda: callbacks.get("cmd_set_view_mode", lambda x: None)("list")
        )
        view_menu.addAction(self.list_mode_action)

        view_menu.addSeparator()
        
        self.dual_tree_action = QAction("Two-Pane Tree Mode", self.main_window, checkable=True)
        dual_tree_mode = getattr(self.main_window, 'dual_tree_mode', False)
        self.dual_tree_action.setChecked(dual_tree_mode)
        self.dual_tree_action.triggered.connect(callbacks.get("_set_dual_tree_mode", lambda x: None))
        view_menu.addAction(self.dual_tree_action)
