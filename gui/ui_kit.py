"""
Material Design 3 準拠 UI コンポーネント

【設計原則】
- ColorTokens, Typography, Elevation を使用
- カスタムフォント（Inter/Roboto/Noto Sans JP）を自動適用
- バリアント（primary, secondary, text）を明確に区別
- インタラクション状態（hover, pressed, disabled）を実装
- アクセシビリティを考慮
"""

import customtkinter as ctk
from typing import Optional, Callable
from gui.theme import ColorTokens, Typography, Elevation, Spacing, Colors

class StyledButton(ctk.CTkButton):
    """
    Material Design 3 準拠ボタン
    カスタムフォント自動適用
    
    バリアント:
    - primary: メインアクション（塗りつぶし）
    - secondary: 副次アクション（アウトライン）
    - text: テキストのみ
    - danger: 危険なアクション（削除等）
    - success: 成功アクション（保存等）
    """
    
    def __init__(self, parent, text: str, command: Optional[Callable] = None, 
                 variant: str = "primary", **kwargs):
        
        # バリアント別スタイル定義
        # 【設計方針】アクセントカラーは primary と danger のみ
        # その他はニュートラルカラーで統一し、視覚的な混乱を削減
        
        if variant == "primary":
            # メインアクション（開く、保存、分類実行など）
            style = {
                "fg_color": Colors.PRIMARY,
                "hover_color": Colors.PRIMARY_HOVER,
                "text_color": Colors.ON_PRIMARY,
                "border_width": 0,
            }
        elif variant == "secondary":
            # 補助アクション（ニュートラル、アウトライン）
            style = {
                "fg_color": "transparent",
                "hover_color": Colors.SURFACE_3,
                "text_color": Colors.TEXT_PRIMARY,
                "border_width": 1,
                "border_color": Colors.BORDER,
            }
        elif variant == "ghost":
            # 控えめなアクション（背景なし）
            style = {
                "fg_color": "transparent",
                "hover_color": Colors.SURFACE_3,
                "text_color": Colors.TEXT_SECONDARY,
                "border_width": 0,
            }
        elif variant == "text":
            # テキストのみ
            style = {
                "fg_color": "transparent",
                "hover_color": Colors.HOVER_OVERLAY,
                "text_color": Colors.TEXT_PRIMARY,
                "border_width": 0,
            }
        elif variant == "danger":
            # 破壊的アクション（削除のみ）
            style = {
                "fg_color": Colors.DANGER,
                "hover_color": "#E07585",
                "text_color": Colors.ON_PRIMARY,
                "border_width": 0,
            }
        elif variant == "success":
            # 成功アクション（ニュートラルに変更）
            style = {
                "fg_color": Colors.SURFACE_3,
                "hover_color": Colors.SURFACE_4,
                "text_color": Colors.TEXT_PRIMARY,
                "border_width": 0,
            }
        else:
            # デフォルトはsecondary（ニュートラル）
            style = {
                "fg_color": "transparent",
                "hover_color": Colors.SURFACE_3,
                "text_color": Colors.TEXT_PRIMARY,
                "border_width": 1,
                "border_color": Colors.BORDER,
            }
        
        # デフォルト設定（カスタムフォント使用）
        default_config = {
            "text": text,
            "command": command,
            "font": Typography.create_button_font(),  # Noto Sans JP 18px Medium
            "height": 36,
            "corner_radius": Elevation.RADIUS_M,
        }
        
        # スタイルをマージ
        default_config.update(style)
        
        # ユーザー指定のkwargsで上書き
        default_config.update(kwargs)
        
        super().__init__(parent, **default_config)

class StyledCard(ctk.CTkFrame):
    """
    Material Design 3 準拠カード
    
    Surface階層を表現するコンテナ
    """
    def __init__(self, parent, **kwargs):
        final_kwargs = {
            "corner_radius": Elevation.RADIUS_M,
            "fg_color": Colors.SURFACE_2,
            "border_width": 1,
            "border_color": Colors.BORDER,
        }
        final_kwargs.update(kwargs)
        super().__init__(parent, **final_kwargs)

