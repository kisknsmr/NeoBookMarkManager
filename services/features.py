"""
Feature Flags - Unified feature control interface.

AI分類・ネットワーク・プロキシなどの有効化を統一インターフェースで管理。
実行時に"明示的にON→OFF"可能にしてデバッグ性向上。
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class FeatureFlags:
    """
    Feature control flags.
    
    All features are opt-in (default False) to prevent unexpected behavior.
    """
    # Network & Proxy
    network_enabled: bool = False          # Enable/disable all network operations
    proxy_enabled: bool = False            # Use proxy for network requests
    proxy_host: Optional[str] = None       # Proxy host (http://proxy.example.com:8080)
    
    # AI & Classification
    ai_enabled: bool = False               # Enable AI-based classification
    ai_max_items: int = 300                # Max items to classify in one batch
    
    # Preview & Title
    auto_fetch_title: bool = False         # Auto-fetch title from URL
    auto_fetch_preview: bool = False       # Auto-fetch preview from URL
    
    # Performance & Debug
    tree_diff_update: bool = False         # Use diff-based tree updates (vs full refresh)
    card_virtualization: bool = False      # Virtualize bookmark cards (for large collections)
    debug_log: bool = False                # Enable debug logging

    def __repr__(self) -> str:
        flags = {k: v for k, v in self.__dict__.items()}
        return f"FeatureFlags({flags})"


class FeatureFlagManager:
    """
    Global feature flag manager.
    
    Single source of truth for all feature toggles.
    """
    _instance: Optional["FeatureFlagManager"] = None
    _flags: FeatureFlags

    def __new__(cls) -> "FeatureFlagManager":
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._flags = FeatureFlags()
        return cls._instance

    @classmethod
    def get(cls) -> "FeatureFlagManager":
        """Get singleton instance."""
        return cls()

    @classmethod
    def reset(cls):
        """Reset to defaults (for testing)."""
        cls._instance = None

    def flags(self) -> FeatureFlags:
        """Get current flags."""
        return self._flags

    def set_flag(self, name: str, value) -> None:
        """
        Set individual flag.
        
        Args:
            name: Flag name (e.g., "network_enabled")
            value: New value
            
        Raises:
            AttributeError: If flag doesn't exist
        """
        if not hasattr(self._flags, name):
            raise AttributeError(f"Unknown flag: {name}")
        setattr(self._flags, name, value)

    def enable_network(self, enabled: bool = True, proxy_host: Optional[str] = None) -> None:
        """Enable/disable network operations."""
        self._flags.network_enabled = enabled
        if proxy_host:
            self._flags.proxy_enabled = True
            self._flags.proxy_host = proxy_host

    def enable_ai(self, enabled: bool = True, max_items: int = 300) -> None:
        """Enable/disable AI features."""
        self._flags.ai_enabled = enabled
        self._flags.ai_max_items = max_items

    def enable_auto_fetch(self, title: bool = False, preview: bool = False) -> None:
        """Enable/disable auto-fetch features."""
        self._flags.auto_fetch_title = title
        self._flags.auto_fetch_preview = preview

    def enable_performance_features(self, diff_update: bool = False, virtualization: bool = False) -> None:
        """Enable/disable performance features."""
        self._flags.tree_diff_update = diff_update
        self._flags.card_virtualization = virtualization

    def enable_debug(self, enabled: bool = True) -> None:
        """Enable/disable debug logging."""
        self._flags.debug_log = enabled

    def is_network_available(self) -> bool:
        """Check if network operations are enabled."""
        return self._flags.network_enabled

    def is_ai_available(self) -> bool:
        """Check if AI operations are enabled."""
        return self._flags.ai_enabled and self._flags.network_enabled

    def should_use_proxy(self) -> bool:
        """Check if proxy should be used."""
        return self._flags.proxy_enabled and self._flags.network_enabled

    def get_proxy_host(self) -> Optional[str]:
        """Get proxy host."""
        if self.should_use_proxy():
            return self._flags.proxy_host
        return None


# Global singleton
_flag_manager = FeatureFlagManager.get()


def get_flags() -> FeatureFlags:
    """Get current feature flags."""
    return _flag_manager.flags()


def set_flag(name: str, value) -> None:
    """Set individual flag."""
    _flag_manager.set_flag(name, value)
