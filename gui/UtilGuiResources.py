"""
NeoBookMarkManager - GUI Resources
リソース、定数、列挙型を一元管理するモジュール
"""

from pathlib import Path
from typing import Final
from PySide6.QtGui import QFont

# ============ ファイルパス ============
PROJECT_ROOT: Final[Path] = Path(__file__).parent.parent
ASSETS_DIR: Final[Path] = PROJECT_ROOT / "assets"
FONTS_DIR: Final[Path] = PROJECT_ROOT / "fonts"
CONFIG_DIR: Final[Path] = PROJECT_ROOT / "config"
STYLE_FILE: Final[Path] = Path(__file__).parent / "style.qss"


# ============ Window Size Constants ============
class WindowSize:
    """ウィンドウサイズ定数"""
    DEFAULT_WIDTH: Final[int] = 1200
    DEFAULT_HEIGHT: Final[int] = 800
    MIN_WIDTH: Final[int] = 800
    MIN_HEIGHT: Final[int] = 600


# ============ Theme Constants ============
class Theme:
    """テーマ関連の定数"""
    # Material Design 3 Colors
    PRIMARY: Final[str] = "#BB86FC"
    SECONDARY: Final[str] = "#03DAC6"
    ERROR: Final[str] = "#CF6679"
    
    BACKGROUND: Final[str] = "#121212"
    SURFACE_0: Final[str] = "#121212"
    SURFACE_1: Final[str] = "#1D1D1D"
    SURFACE_2: Final[str] = "#232323"
    SURFACE_3: Final[str] = "#282828"
    SURFACE_4: Final[str] = "#2C2C2C"
    
    TEXT_PRIMARY: Final[str] = "#FFFFFF"
    TEXT_SECONDARY: Final[str] = "#E0E0E0"
    TEXT_DISABLED: Final[str] = "#757575"
    TEXT_HINT: Final[str] = "#9E9E9E"
    
    BORDER: Final[str] = "#2C2C2C"
    BORDER_DEFAULT: Final[str] = "#2C2C2C"  # Alias for BORDER
    BORDER_FOCUSED: Final[str] = "#BB86FC"  # Same as PRIMARY
    DIVIDER: Final[str] = "#1F1F1F"
    HOVER_OVERLAY: Final[str] = "#FFFFFF1A"  # 10% white overlay


# ============ Typography ============
class Typography:
    """タイポグラフィ定数"""
    # Font Families
    FAMILY_PRIMARY: Final[str] = "Noto Sans JP"
    FONT_FAMILY: Final[str] = "Noto Sans JP"  # Alias for compatibility
    FAMILY_MONO: Final[str] = "Roboto Mono"
    
    # Font Sizes (in pixels)
    SIZE_EXTRA_SMALL: Final[int] = 11
    SIZE_SMALL: Final[int] = 12
    SIZE_BODY: Final[int] = 13
    SIZE_BODY_LARGE: Final[int] = 14
    SIZE_TITLE: Final[int] = 16
    SIZE_HEADING: Final[int] = 18
    SIZE_DISPLAY: Final[int] = 24
    
    # Font Weights
    WEIGHT_NORMAL: Final[int] = 400
    WEIGHT_MEDIUM: Final[int] = 500
    WEIGHT_SEMIBOLD: Final[int] = 600
    WEIGHT_BOLD: Final[int] = 700
    
    @staticmethod
    def get_title_font():
        """タイトル用QFontを取得"""
        font = QFont(Typography.FONT_FAMILY, Typography.SIZE_TITLE)
        font.setWeight(QFont.Weight.Bold)
        return font


# ============ Spacing ============
class Spacing:
    """スペーシング定数（Dp）"""
    XXSMALL: Final[int] = 2
    XSMALL: Final[int] = 4
    SMALL: Final[int] = 8
    MEDIUM: Final[int] = 12
    LARGE: Final[int] = 16
    XLARGE: Final[int] = 24
    XXLARGE: Final[int] = 32


# ============ Border Radius ============
class BorderRadius:
    """ボーダーラジアス定数"""
    EXTRA_SMALL: Final[int] = 2
    SMALL: Final[int] = 4
    MEDIUM: Final[int] = 6
    LARGE: Final[int] = 8
    EXTRA_LARGE: Final[int] = 12
    FULL: Final[int] = 9999


# ============ Component Sizes ============
class ComponentSize:
    """UI コンポーネントのサイズ定数"""
    BUTTON_HEIGHT: Final[int] = 36
    BUTTON_HEIGHT_SMALL: Final[int] = 28
    
    ICON_SMALL: Final[int] = 16
    ICON_MEDIUM: Final[int] = 24
    ICON_LARGE: Final[int] = 32
    
    CARD_MIN_WIDTH: Final[int] = 200
    CARD_MIN_HEIGHT: Final[int] = 120
    
    SIDEBAR_WIDTH: Final[int] = 280
    SIDEBAR_WIDTH_COLLAPSED: Final[int] = 64
    
    DETAIL_PANEL_WIDTH: Final[int] = 300
    DETAIL_PANEL_MIN_WIDTH: Final[int] = 250


# ============ Timing Constants ============
class Timing:
    """アニメーション・トランジション時間（ミリ秒）"""
    INSTANT: Final[int] = 0
    EXTRA_FAST: Final[int] = 50
    FAST: Final[int] = 100
    NORMAL: Final[int] = 300
    SLOW: Final[int] = 500
    EXTRA_SLOW: Final[int] = 1000


# ============ Signal Slot Roles ============
class DataRole:
    """Qt.ItemDataRole カスタム定義"""
    NODE_ID: Final[int] = 256  # Qt.UserRole = 256
    NODE_TYPE: Final[int] = 257
    NODE_ICON: Final[int] = 258
    IS_FAVORITE: Final[int] = 259
    DISPLAY_TEXT: Final[int] = 260


# ============ Dialog Sizes ============
class DialogSize:
    """ダイアログサイズ定数"""
    SMALL_WIDTH: Final[int] = 400
    SMALL_HEIGHT: Final[int] = 250
    
    MEDIUM_WIDTH: Final[int] = 600
    MEDIUM_HEIGHT: Final[int] = 400
    
    LARGE_WIDTH: Final[int] = 800
    LARGE_HEIGHT: Final[int] = 600


# ============ String Constants ============
class Strings:
    """UI テキスト定数"""
    APP_NAME: Final[str] = "NeoBookMarkManager"
    APP_VERSION: Final[str] = "2.0.0"
    
    # Menu Items
    FILE: Final[str] = "ファイル"
    EDIT: Final[str] = "編集"
    VIEW: Final[str] = "表示"
    TOOLS: Final[str] = "ツール"
    HELP: Final[str] = "ヘルプ"
    
    # Common Actions
    NEW: Final[str] = "新規"
    OPEN: Final[str] = "開く"
    SAVE: Final[str] = "保存"
    DELETE: Final[str] = "削除"
    EDIT_ACTION: Final[str] = "編集"
    CANCEL: Final[str] = "キャンセル"
    OK: Final[str] = "OK"
    APPLY: Final[str] = "適用"
    CLOSE: Final[str] = "閉じる"
    
    # Bookmarks
    ADD_BOOKMARK: Final[str] = "ブックマークを追加"
    EDIT_BOOKMARK: Final[str] = "ブックマークを編集"
    DELETE_BOOKMARK: Final[str] = "ブックマークを削除"
    OPEN_BOOKMARK: Final[str] = "ブックマークを開く"
    
    # Folders
    NEW_FOLDER: Final[str] = "新規フォルダ"
    EDIT_FOLDER: Final[str] = "フォルダを編集"
    DELETE_FOLDER: Final[str] = "フォルダを削除"
    
    # Search
    SEARCH: Final[str] = "検索"
    SEARCH_PLACEHOLDER: Final[str] = "ブックマークを検索..."
    NO_RESULTS: Final[str] = "検索結果がありません"
    
    # Settings
    SETTINGS: Final[str] = "設定"
    APPEARANCE: Final[str] = "外観"
    ABOUT: Final[str] = "について"
    
    # Messages
    CONFIRM_DELETE: Final[str] = "削除してもよろしいですか？"
    LOADING: Final[str] = "読み込み中..."
    ERROR: Final[str] = "エラー"
    WARNING: Final[str] = "警告"
    INFO: Final[str] = "情報"


# ============ ColorTokens (for backward compatibility) ============
class ColorTokens:
    """
    色トークンクラス（後方互換性のため）
    Theme クラスのエイリアスとして機能
    """
    PRIMARY = Theme.PRIMARY
    SECONDARY = Theme.SECONDARY
    TEXT_PRIMARY = Theme.TEXT_PRIMARY
    TEXT_SECONDARY = Theme.TEXT_SECONDARY
    BORDER_DEFAULT = Theme.BORDER_DEFAULT
    BORDER_FOCUSED = Theme.BORDER_FOCUSED
    SURFACE_1 = Theme.SURFACE_1
    SURFACE_2 = Theme.SURFACE_2
    SURFACE_3 = Theme.SURFACE_3
    HOVER_OVERLAY = Theme.HOVER_OVERLAY


# ============ Utility Functions ============
def create_qfont(size: int = 12, bold: bool = False) -> QFont:
    """
    QFont を作成するヘルパー関数
    
    Args:
        size: フォントサイズ（デフォルト: 12）
        bold: 太字にするか（デフォルト: False）
    
    Returns:
        QFont オブジェクト
    """
    font = QFont(Typography.FONT_FAMILY, size)
    if bold:
        font.setWeight(QFont.Weight.Bold)
    return font


# ============ Backward-compatible aliases ============
# UtilTheme.py との後方互換性のため
Colors = ColorTokens
Fonts = Typography
