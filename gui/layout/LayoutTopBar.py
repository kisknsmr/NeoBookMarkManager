"""Top bar widget for the main window.

MainWindow should only *instantiate* and wire signals.
"""

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from gui.layout.LayoutComponents import SearchBar
from gui.UtilGuiResources import Typography


class TopBar(QFrame):
    """Top bar with brand, search, and quick actions."""

    search_text_changed = Signal(str)
    search_triggered = Signal(str)
    toggle_dual_tree = Signal(bool)
    expand_all = Signal()
    collapse_all = Signal()

    def __init__(self, *, dual_tree_mode: bool = False, view_mode: str = "card", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("topbar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(12)

        brand_label = QLabel("📑 Bookmark Studio")
        brand_font = QFont(Typography.FONT_FAMILY, 12)
        brand_font.setBold(True)
        brand_label.setFont(brand_font)
        layout.addWidget(brand_label)

        chip1 = QLabel("v1.0")
        chip1.setObjectName("chip")
        layout.addWidget(chip1)

        self.search_bar = SearchBar()
        self.search_bar.search_triggered.connect(self.search_triggered)
        self.search_bar.search_text_changed.connect(self.search_text_changed)
        layout.addWidget(self.search_bar, 1)

        layout.addStretch()

        dual_btn = QPushButton("2画面モード")
        dual_btn.setCheckable(True)
        dual_btn.setChecked(bool(dual_tree_mode))
        dual_btn.setObjectName("chip")
        dual_btn.clicked.connect(self.toggle_dual_tree)
        layout.addWidget(dual_btn)
        self.dual_tree_button = dual_btn

        mode_chip = QLabel("")
        mode_chip.setObjectName("chip")
        self.mode_chip = mode_chip
        self.set_view_mode(view_mode)
        layout.addWidget(mode_chip)

        expand_btn = QPushButton("すべて展開")
        expand_btn.setObjectName("outlineButton")
        expand_btn.setMaximumHeight(30)
        expand_btn.setMinimumWidth(80)
        expand_btn.clicked.connect(self.expand_all)
        layout.addWidget(expand_btn)

        collapse_btn = QPushButton("すべて縮小")
        collapse_btn.setObjectName("ghostButton")
        collapse_btn.setMaximumHeight(30)
        collapse_btn.setMinimumWidth(80)
        collapse_btn.clicked.connect(self.collapse_all)
        layout.addWidget(collapse_btn)

    def set_dual_tree_checked(self, checked: bool) -> None:
        self.dual_tree_button.setChecked(bool(checked))

    def set_view_mode(self, mode: str) -> None:
        display_text = "Card" if mode == "card" else "List"
        self.mode_chip.setText(f"表示: {display_text}")
