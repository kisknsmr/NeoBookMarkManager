"""
Minimal theme tokens for PySide6 dialogs.
"""

from PySide6.QtGui import QFont


class ColorTokens:
    PRIMARY = "#BB86FC"
    SECONDARY = "#03DAC6"
    TEXT_PRIMARY = "#FFFFFF"
    TEXT_SECONDARY = "#E0E0E0"
    BORDER_DEFAULT = "#2C2C2C"
    BORDER_FOCUSED = "#BB86FC"
    SURFACE_1 = "#1D1D1D"
    SURFACE_2 = "#232323"
    SURFACE_3 = "#282828"
    HOVER_OVERLAY = "#FFFFFF1A"


class Typography:
    @staticmethod
    def get_title_font() -> QFont:
        font = QFont("Noto Sans JP", 14)
        font.setBold(True)
        return font


def create_qfont(size: int = 12, bold: bool = False) -> QFont:
    font = QFont("Noto Sans JP", size)
    font.setBold(bold)
    return font

