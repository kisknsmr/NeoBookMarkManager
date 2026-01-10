"""
Design Tokens for the application.
Central source of truth for Colors, Typography, and Dimensions.
"""

class Colors:
    """Color Palette - Modern Light Theme"""
    PRIMARY = "#007AFF"      # Action Blue
    PRIMARY_HOVER = "#0062CC"
    BACKGROUND = "#F5F5F7"   # App Background (Light Gray)
    SURFACE = "#FFFFFF"      # Card/Panel Background
    
    TEXT_PRIMARY = "#1C1C1E" # Almost Black
    TEXT_SECONDARY = "#8E8E93" # Gray text
    
    BORDER = "#D2D2D7"       # Subtle border (matches previous default)
    BORDER_FOCUSED = "#007AFF"
    
    SUCCESS = "#34C759"
    DANGER = "#FF3B30"
    WARNING = "#FFCC00"
    
    # Interaction states
    SELECTED_BG = "#E8F4FD"  # Light blue background for selected items
    HOVER_BG = "#F0F0F5"     # Hover state for interactive elements
    DROP_INDICATOR = "#007AFF"

class Fonts:
    """Typography System"""
    # CustomTkinterは単一フォント名のみ対応
    # システムフォントを確認して最適なものを選択
    FAMILY = "Yu Gothic UI"  # Windows 10/11標準の日本語フォント
    FAMILY_FALLBACK = "Meiryo UI"  # フォールバック用
    
    # Font Sizes - コンパクトに調整
    SIZE_XL = 18
    SIZE_L = 14
    SIZE_M = 13
    SIZE_S = 12
    SIZE_XS = 11
    SIZE_XXS = 10
    
    # Weights (CustomTkinter uses string weights)
    WEIGHT_BOLD = "bold"
    WEIGHT_NORMAL = "normal"

class Dims:
    """Dimensions and Spacing"""
    # Corner Radii
    RADIUS_S = 6
    RADIUS_M = 12
    RADIUS_L = 18
    
    # Spacing
    SPACING_XS = 4
    SPACING_S = 8
    SPACING_M = 16
    SPACING_L = 24
    
    # Component Specific
    ICON_SIZE_M = 18
    ICON_SIZE_L = 24
