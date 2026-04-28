"""Compatibility shim for legacy FontLoader import.

Provides a minimal `FontLoader` with `initialize()` and `cleanup()` methods
so existing code importing `core.util_font` continues to work.
"""
from typing import Optional

class FontLoader:
    """Minimal FontLoader that acts as a no-op shim.

    In newer architecture, font management is handled by `core.FontManager`.
    These methods are retained for backward compatibility.
    """
    _initialized: bool = False

    @staticmethod
    def initialize(app: Optional[object] = None) -> None:
        """Initialize font loader. No-op for compatibility.
        Accepts optional `app` to match potential legacy signatures.
        """
        FontLoader._initialized = True

    @staticmethod
    def cleanup() -> None:
        """Cleanup resources, if any. No-op for compatibility."""
        FontLoader._initialized = False
