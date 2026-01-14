"""
Design System - Material Design 3 (Material You) Dark Theme
商用品質を前提としたデザイントークン定義

【設計思想】
- Material Design 3 準拠
- Surface階層による奥行き表現
- WCAG AA準拠のコントラスト比
- ライトテーマへの将来的な切替を想定
- カスタムフォント（Inter/Roboto/Noto Sans JP）を使用
"""

# カスタムフォントローダーをインポート
from core.font_loader import FontLoader

# フォントシステムを初期化
FontLoader.initialize()

class ColorTokens:
    """
    Material Design 3 カラートークン
    
    【階層構造 - Elevation System】
    Dark themeでは、半透過の白オーバーレイで奥行きを表現
    - Surface 0: ベース（0% overlay）
    - Surface 1: dp 1-2 相当（5% white overlay）
    - Surface 2: dp 3-4 相当（8% white overlay）
    - Surface 3: dp 6-8 相当（11% white overlay）
    - Surface 4: dp 12+ 相当（14% white overlay）
    
    【アクセシビリティ】
    - テキストとのコントラスト比 4.5:1 以上を保証
    - 色だけに頼らない情報伝達
    """
    
    # === Surface階層（半透過白オーバーレイで奥行き表現） ===
    SURFACE_0 = "#121212"  # ベース（0% white overlay）
    SURFACE_1 = "#1D1D1D"  # dp 1-2: 5% white overlay on #121212
    SURFACE_2 = "#232323"  # dp 3-4: 8% white overlay on #121212
    SURFACE_3 = "#282828"  # dp 6-8: 11% white overlay on #121212
    SURFACE_4 = "#2E2E2E"  # dp 12+: 14% white overlay on #121212
    
    # === Primary（メインアクションカラー）===
    PRIMARY = "#BB86FC"           # Material Purple 200
    PRIMARY_HOVER = "#C89DFF"     # Hover時（+10% Lightness）
    PRIMARY_PRESSED = "#A66FEB"   # Press時（-10% Lightness）
    PRIMARY_DISABLED = "#5A4371"  # Disabled時（透明度50%相当）
    ON_PRIMARY = "#000000"        # Primary上のテキスト
    
    # === Secondary（補助アクションカラー）===
    SECONDARY = "#03DAC6"         # Material Teal 200
    SECONDARY_HOVER = "#1DE5D4"   # Hover時
    SECONDARY_PRESSED = "#02C4B5" # Press時
    ON_SECONDARY = "#000000"      # Secondary上のテキスト
    
    # === Accent（強調表示）===
    ACCENT = "#CF6679"            # Material Pink 200
    
    # === Semantic Colors（意味を持つ色）===
    SUCCESS = "#4CAF50"           # Material Green 500
    WARNING = "#FFA726"           # Material Orange 400
    ERROR = "#CF6679"             # Material Pink 200
    INFO = "#29B6F6"              # Material Light Blue 400
    
    # === Text Colors（テキスト階層）===
    TEXT_PRIMARY = "#FFFFFF"      # High emphasis（87% opacity相当）
    TEXT_SECONDARY = "#E0E0E0"    # Medium emphasis（60% opacity相当）
    TEXT_DISABLED = "#757575"     # Disabled（38% opacity相当）
    TEXT_ON_SURFACE = "#FFFFFF"   # Surface上のテキスト
    
    # === Border & Divider ===
    BORDER_DEFAULT = "#2C2C2C"    # デフォルト境界線
    BORDER_FOCUSED = "#BB86FC"    # フォーカス時（Primary）
    DIVIDER = "#2C2C2C"           # セパレータ
    
    # === Interaction States（インタラクション状態）===
    HOVER_OVERLAY = "#FFFFFF1A"   # Hover時のオーバーレイ（10% white）
    PRESSED_OVERLAY = "#FFFFFF33" # Press時のオーバーレイ（20% white）
    SELECTED_BG = "#2A2A2A"       # 選択状態の背景
    RIPPLE = "#FFFFFF33"          # リップルエフェクト（20% white）
    
    # === Shadows（推奨: 最小限使用）===
    SHADOW_LIGHT = "#00000033"    # 軽い影（20% black）
    SHADOW_MEDIUM = "#00000066"   # 中程度の影（40% black）
    SHADOW_HEAVY = "#00000099"    # 重い影（60% black）

class Colors:
    """
    後方互換性のためのエイリアス
    新規コードでは ColorTokens を使用することを推奨
    
    【Elevation マッピング】
    - BACKGROUND: 最も奥（Surface 0）
    - SURFACE: カード・パネル（Surface 1）
    - SURFACE_2: 強調カード（Surface 2）
    - SURFACE_3: モーダル・ダイアログ（Surface 3）
    - HOVER_BG: ホバー時の強調（Surface 3）
    """
    PRIMARY = ColorTokens.PRIMARY
    PRIMARY_HOVER = ColorTokens.PRIMARY_HOVER
    BACKGROUND = ColorTokens.SURFACE_0  # アプリ背景（最奥）
    SURFACE = ColorTokens.SURFACE_1     # カード背景（中層）
    # 互換エイリアス
    SURFACE_0 = ColorTokens.SURFACE_0
    SURFACE_1 = ColorTokens.SURFACE_1
    SURFACE_2 = ColorTokens.SURFACE_2   # 強調カード
    SURFACE_3 = ColorTokens.SURFACE_3   # モーダル・ダイアログ
    
    TEXT_PRIMARY = ColorTokens.TEXT_PRIMARY
    TEXT_SECONDARY = ColorTokens.TEXT_SECONDARY
    
    BORDER = ColorTokens.BORDER_DEFAULT
    BORDER_FOCUSED = ColorTokens.BORDER_FOCUSED
    
    SUCCESS = ColorTokens.SUCCESS
    DANGER = ColorTokens.ERROR
    WARNING = ColorTokens.WARNING
    
    SELECTED_BG = ColorTokens.SELECTED_BG
    HOVER_BG = ColorTokens.SURFACE_3
    DROP_INDICATOR = ColorTokens.PRIMARY
    # 追加エイリアス（UIコード互換性確保）
    ON_PRIMARY = ColorTokens.ON_PRIMARY
    SURFACE_4 = ColorTokens.SURFACE_4
    HOVER_OVERLAY = ColorTokens.HOVER_OVERLAY

class Typography:
    """
    Material Design 3 タイポグラフィスケール
    カスタムフォント（Inter/Roboto/Noto Sans JP）を使用
    
    【フォント優先順位】
    1. Inter（Variable Font - 推奨）
    2. Roboto（Variable Font - Material Design標準）
    3. Noto Sans JP（Variable Font - 日本語対応）
    4. システムフォント（フォールバック）
    
    【サイズ制約】
    - 最小サイズ: 13px（可読性重視）
    - 見出し: 22-26px / SemiBold
    - セクション見出し: 17-19px / Medium
    - 本文: 15-16px / Regular
    - 補助テキスト: 13-14px / Regular
    
    【Variable Font対応】
    - fonts/フォルダ内のカスタムフォントを自動読み込み
    - FontLoaderが自動的に最適なフォントを選択
    """
    
    # === Font Family（FontLoaderから取得）===
    # 日本語優先: Noto Sans JPを最優先、欧文はInter
    # 注: Variable FontはOSに登録される際、異なる名前になる
    FAMILY_PRIMARY = FontLoader.get_font_family("Noto Sans JP")  # 日本語優先
    FAMILY_SECONDARY = FontLoader.get_font_family("Inter")  # 欧文用
    FAMILY_JAPANESE = FontLoader.get_font_family("Noto Sans JP")
    
    # デバッグ: 実際に取得されたフォント名をログ出力
    print(f"[DEBUG] FAMILY_PRIMARY (Noto Sans JP要求): '{FAMILY_PRIMARY}'")
    print(f"[DEBUG] FAMILY_SECONDARY (Inter要求): '{FAMILY_SECONDARY}'")
    print(f"[DEBUG] FAMILY_JAPANESE (Noto Sans JP要求): '{FAMILY_JAPANESE}'")
    
    # None/空文字チェック
    if not FAMILY_PRIMARY or FAMILY_PRIMARY.strip() == "":
        print("[WARNING] FAMILY_PRIMARY が None または空文字です！システムフォントにフォールバックします")
    if FAMILY_PRIMARY not in ["Noto Sans JP", "Inter Variable Text", "Roboto"]:
        print(f"[WARNING] FAMILY_PRIMARY が想定外の値です: '{FAMILY_PRIMARY}'")
    
    # UI用のデフォルトフォント（日本語優先）
    FAMILY_UI = FAMILY_PRIMARY  # Noto Sans JP
    FAMILY_MONOSPACE = "Consolas"  # コード表示専用
    
    # === Type Scale - 日本語UI最適化（Noto Sans JP用に+2px）===
    # 注: 日本語可読性を重視、Noto Sans JPに最適化
    
    # 見出し（24-28px / SemiBold）+2px
    HEADLINE_LARGE = 28        # 大見出し
    HEADLINE_MEDIUM = 26       # 中見出し
    HEADLINE_SMALL = 24        # 小見出し
    
    # セクション見出し（19-21px / Medium）+2px
    TITLE_LARGE = 21           # セクション大
    TITLE_MEDIUM = 20          # セクション標準
    TITLE_SMALL = 19           # セクション小
    
    # 本文（16px / Regular） - 可読性を重視して16px基準に調整
    BODY_LARGE = 16            # 本文大
    BODY_MEDIUM = 16           # 本文標準
    BODY_SMALL = 15            # 本文小（最小15px）
    
    # 補助テキスト（15-16px / Regular）+2px
    LABEL_LARGE = 16           # ラベル大
    LABEL_MEDIUM = 15          # ラベル標準
    LABEL_SMALL = 15           # ラベル小（最小15px）
    
    # === Font Weights ===
    # CustomTkinterは "normal" と "bold" のみサポート
    WEIGHT_REGULAR = "normal"  # Regular（400相当）
    WEIGHT_MEDIUM = "bold"     # Medium/SemiBold（500-600相当）
    WEIGHT_BOLD = "bold"       # Bold（700相当）
    
    # === Line Height（行間）===
    # 長時間利用を考慮した快適な行間設定
    LINE_HEIGHT_TIGHT = 1.3    # 見出し用（狭め）
    LINE_HEIGHT_NORMAL = 1.5   # 本文用（標準）
    LINE_HEIGHT_COMFORTABLE = 1.6  # 長文用（広め）
    LINE_HEIGHT_LOOSE = 1.8    # リスト・カード用（最も広い）
    
    # === Letter Spacing（字間）===
    LETTER_SPACING_TIGHT = -0.5   # 見出し用
    LETTER_SPACING_NORMAL = 0     # 標準
    LETTER_SPACING_WIDE = 0.5     # 強調用
    
    # === 用途別フォント設定（FontLoaderを使用）===
    @staticmethod
    def create_headline_font():
        """見出しフォント: 26px / SemiBold（Noto Sans JP優先）"""
        return FontLoader.create_font(
            family="Noto Sans JP",
            size=Typography.HEADLINE_MEDIUM,  # 26px
            weight=Typography.WEIGHT_BOLD
        )
    
    @staticmethod
    def create_section_font():
        """セクション見出しフォント: 20px / Medium（Noto Sans JP優先）"""
        return FontLoader.create_font(
            family="Noto Sans JP",
            size=Typography.TITLE_MEDIUM,     # 20px
            weight=Typography.WEIGHT_MEDIUM
        )
    
    @staticmethod
    def create_body_font():
        """本文フォント: 17px / Regular（Noto Sans JP優先）"""
        return FontLoader.create_font(
            family="Noto Sans JP",
            size=Typography.BODY_MEDIUM,      # 16px
            weight=Typography.WEIGHT_REGULAR
        )
    
    @staticmethod
    def create_button_font():
        """ボタンフォント: 18px / Medium（Noto Sans JP優先）"""
        return FontLoader.create_font(
            family="Noto Sans JP",
            size=16,       # ボタンを16pxに調整（可読性向上）
            weight=Typography.WEIGHT_MEDIUM
        )
    
    @staticmethod
    def create_caption_font():
        """補助テキストフォント: 15px / Regular（Noto Sans JP優先）"""
        return FontLoader.create_font(
            family="Noto Sans JP",
            size=Typography.LABEL_MEDIUM,     # 15px
            weight=Typography.WEIGHT_REGULAR
        )
    
    # === 旧形式フォント設定（dict形式・後方互換性）===
    # 注: 新規コードでは create_*_font() メソッドを使用すること
    FONT_HEADLINE = {
        "family": FAMILY_UI,      # Noto Sans JP
        "size": HEADLINE_MEDIUM,  # 26px
        "weight": WEIGHT_BOLD,    # SemiBold相当
    }
    
    # セクション見出し: 19-21px / Medium
    FONT_SECTION = {
        "family": FAMILY_UI,      # Noto Sans JP
        "size": TITLE_MEDIUM,     # 20px
        "weight": WEIGHT_MEDIUM,  # Medium相当
    }
    
    # 本文: 17-18px / Regular
    FONT_BODY = {
        "family": FAMILY_UI,      # Noto Sans JP
        "size": BODY_MEDIUM,      # 17px
        "weight": WEIGHT_REGULAR,
    }
    
    # ボタン: 17px / Medium
    FONT_BUTTON = {
        "family": FAMILY_UI,      # Noto Sans JP
        "size": BODY_MEDIUM,      # 17px
        "weight": WEIGHT_MEDIUM,
    }
    
    # 補助テキスト: 15-16px / Regular
    FONT_CAPTION = {
        "family": FAMILY_UI,      # Noto Sans JP
        "size": LABEL_MEDIUM,     # 15px
        "weight": WEIGHT_REGULAR,
    }
    
    # === 禁止事項 ===
    # - 15px未満のフォントサイズ使用禁止（Noto Sans JP + 日本語可読性重視）
    # - 装飾フォント（Comic Sans等）使用禁止
    # - コード表示以外での等幅フォント使用禁止

class Fonts:
    """後方互換性のためのエイリアス"""
    FAMILY = Typography.FAMILY_UI  # Noto Sans JP
    FAMILY_FALLBACK = "Noto Sans JP"  # 日本語フォールバック
    
    # サイズは日本語UI最適化（Noto Sans JP用: +2px）
    SIZE_XL = Typography.HEADLINE_MEDIUM  # 26px
    SIZE_L = Typography.TITLE_LARGE       # 21px
    SIZE_M = Typography.BODY_LARGE        # 15px
    SIZE_S = Typography.BODY_MEDIUM       # 15px
    SIZE_XS = Typography.LABEL_LARGE      # 16px
    SIZE_XXS = Typography.LABEL_MEDIUM    # 15px（最小）
    
    WEIGHT_BOLD = Typography.WEIGHT_BOLD
    WEIGHT_NORMAL = Typography.WEIGHT_REGULAR

class Spacing:
    """
    Material Design 3 スペーシングシステム
    
    【8dpグリッド】
    基準値を8pxとし、4px刻みでスケール
    """
    
    # 基準スペーシング（8dpグリッド）
    UNIT = 8
    
    # スペーシングスケール
    XXS = 2   # 極小（例外的用途）
    XS = 4    # 最小
    S = 8     # 小
    M = 16    # 中（標準）
    L = 24    # 大
    XL = 32   # 特大
    XXL = 48  # 最大
    
    # コンポーネント固有
    PADDING_BUTTON = 16       # ボタン内余白
    PADDING_CARD = 16         # カード内余白
    GAP_INLINE = 8            # 横並び要素間
    GAP_STACK = 12            # 縦並び要素間

class Elevation:
    """
    Material Design 3 エレベーション（奥行き）
    
    【推奨】
    - Shadowは最小限に抑え、Surface階層とトーン差で表現
    - 必要な場合のみ軽い影を使用
    """
    
    # Corner Radius
    RADIUS_NONE = 0
    RADIUS_XS = 4
    RADIUS_S = 8
    RADIUS_M = 12
    RADIUS_L = 16
    RADIUS_XL = 28
    RADIUS_FULL = 9999
    
    # Shadow Blur (使用は最小限に)
    SHADOW_LEVEL_0 = 0
    SHADOW_LEVEL_1 = 2
    SHADOW_LEVEL_2 = 4
    SHADOW_LEVEL_3 = 8

class Dims:
    """後方互換性のためのエイリアス"""
    RADIUS_S = Elevation.RADIUS_S
    RADIUS_M = Elevation.RADIUS_M
    RADIUS_L = Elevation.RADIUS_L
    
    SPACING_XS = Spacing.XS
    SPACING_S = Spacing.S
    SPACING_M = Spacing.M
    SPACING_L = Spacing.L
    
    ICON_SIZE_M = 18
    ICON_SIZE_L = 24

class ComponentStyles:
    """
    コンポーネント別スタイル定義例
    実際の使用時にはCustomTkinterの仕様に合わせて適用
    """
    
    # Primary Button
    BUTTON_PRIMARY = {
        "fg_color": ColorTokens.PRIMARY,
        "hover_color": ColorTokens.PRIMARY_HOVER,
        "text_color": ColorTokens.ON_PRIMARY,
        "corner_radius": Elevation.RADIUS_M,
        "height": 40,
        "font_size": Typography.LABEL_LARGE,
        "font_weight": Typography.WEIGHT_MEDIUM,
    }
    
    # Secondary Button
    BUTTON_SECONDARY = {
        "fg_color": "transparent",
        "hover_color": ColorTokens.SURFACE_3,
        "text_color": ColorTokens.PRIMARY,
        "border_width": 1,
        "border_color": ColorTokens.PRIMARY,
        "corner_radius": Elevation.RADIUS_M,
        "height": 40,
    }
    
    # Text Button
    BUTTON_TEXT = {
        "fg_color": "transparent",
        "hover_color": ColorTokens.HOVER_OVERLAY,
        "text_color": ColorTokens.PRIMARY,
        "corner_radius": Elevation.RADIUS_M,
        "height": 40,
    }
    
    # Input Field
    INPUT_FIELD = {
        "fg_color": ColorTokens.SURFACE_2,
        "border_color": ColorTokens.BORDER_DEFAULT,
        "text_color": ColorTokens.TEXT_PRIMARY,
        "corner_radius": Elevation.RADIUS_S,
        "height": 40,
    }
    
    # Card
    CARD = {
        "fg_color": ColorTokens.SURFACE_2,
        "corner_radius": Elevation.RADIUS_M,
        "border_width": 1,
        "border_color": ColorTokens.BORDER_DEFAULT,
    }

# === 使用例（コメント） ===
"""
# Primary Button の作成例
button = ctk.CTkButton(
    parent,
    text="保存",
    fg_color=ColorTokens.PRIMARY,
    hover_color=ColorTokens.PRIMARY_HOVER,
    text_color=ColorTokens.ON_PRIMARY,
    corner_radius=Elevation.RADIUS_M,
    height=40,
    font=ctk.CTkFont(
        family=Typography.FAMILY_PRIMARY,
        size=Typography.LABEL_LARGE,
        weight=Typography.WEIGHT_MEDIUM
    )
)

# Input Field の作成例
entry = ctk.CTkEntry(
    parent,
    fg_color=ColorTokens.SURFACE_2,
    border_color=ColorTokens.BORDER_DEFAULT,
    text_color=ColorTokens.TEXT_PRIMARY,
    corner_radius=Elevation.RADIUS_S,
    height=40
)

# Card の作成例
card = ctk.CTkFrame(
    parent,
    fg_color=ColorTokens.SURFACE_2,
    corner_radius=Elevation.RADIUS_M,
    border_width=1,
    border_color=ColorTokens.BORDER_DEFAULT
)
"""

