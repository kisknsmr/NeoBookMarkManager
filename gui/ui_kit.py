"""
Core Components (Atoms) for the Design System.
"""

import customtkinter as ctk
from typing import Optional, Callable
from gui.theme import Colors, Fonts, Dims

class StyledButton(ctk.CTkButton):
    """
    Standard button component with variants.
    Variants: 'primary', 'secondary', 'danger', 'success'
    """
    def __init__(self, parent, text: str, command: Optional[Callable] = None, variant: str = "primary", **kwargs):
        
        # Default styles based on variant
        fg_color = Colors.PRIMARY
        hover_color = Colors.PRIMARY_HOVER
        text_color = "white"
        
        if variant == "secondary":
            fg_color = "transparent"
            text_color = Colors.PRIMARY
            hover_color = Colors.HOVER_BG
            # Add border for secondary if needed, or keep it as text/ghost button
            # Let's make it a ghost button by default or a light gray button
            # Making it a 'subtle' button
        elif variant == "danger":
            fg_color = Colors.DANGER
            hover_color = "#D03025" # Slightly darker red
        elif variant == "success":
            fg_color = Colors.SUCCESS
            hover_color = "#28A745"
            
        # Merge with kwargs, allowing overrides
        final_kwargs = {
            "text": text,
            "command": command,
            "font": ctk.CTkFont(family=Fonts.FAMILY, size=Fonts.SIZE_S, weight=Fonts.WEIGHT_BOLD),
            "height": 32,
            "corner_radius": Dims.RADIUS_S,
            "fg_color": fg_color,
            "hover_color": hover_color,
            "text_color": text_color
        }
        final_kwargs.update(kwargs)
        
        super().__init__(parent, **final_kwargs)

class StyledCard(ctk.CTkFrame):
    """
    Standard card container.
    """
    def __init__(self, parent, **kwargs):
        final_kwargs = {
            "corner_radius": Dims.RADIUS_M,
            "fg_color": Colors.SURFACE,
            "border_width": 1,
            "border_color": Colors.BORDER
        }
        final_kwargs.update(kwargs)
        super().__init__(parent, **final_kwargs)

