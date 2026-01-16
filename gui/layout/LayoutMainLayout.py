"""Main window layout installer.

Keeps MainWindow responsible only for "placing widgets".
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QVBoxLayout, QWidget


def install_main_layout(*, window, topbar: QWidget, left_panel: QWidget, right_panel: QWidget) -> None:
    """Install the main layout (topbar + left/right splitter) into a QMainWindow."""
    central = QWidget()
    window.setCentralWidget(central)

    main_layout = QVBoxLayout(central)
    main_layout.setContentsMargins(0, 0, 0, 0)
    main_layout.setSpacing(0)

    main_layout.addWidget(topbar)

    content_widget = QWidget()
    content_layout = QHBoxLayout(content_widget)
    content_layout.setContentsMargins(8, 8, 8, 8)
    content_layout.setSpacing(8)

    splitter = QSplitter(Qt.Orientation.Horizontal)
    content_layout.addWidget(splitter)

    splitter.addWidget(left_panel)
    splitter.addWidget(right_panel)

    splitter.setSizes([600, 300])
    splitter.setStretchFactor(0, 2)
    splitter.setStretchFactor(1, 1)

    main_layout.addWidget(content_widget, 1)
