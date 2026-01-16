"""
Command registry for organizing all command groups.
Centralizes command access and management.
"""

from .CommandBookmark import BookmarkCommands
from .CommandClassify import ClassifyCommands
from .CommandFile import FileCommands
from .CommandNetwork import NetworkCommands
from .CommandView import ViewCommands


class CommandRegistry:
    """Registry and orchestrator for all command groups."""

    def __init__(self, window):
        """
        Initialize command registry with all command groups.
        
        Args:
            window: MainWindow instance
        """
        self.bookmark = BookmarkCommands(window)
        self.classify = ClassifyCommands(window)
        self.file = FileCommands(window)
        self.network = NetworkCommands(window)
        self.view = ViewCommands(window)


__all__ = [
    "CommandRegistry",
    "BookmarkCommands",
    "ClassifyCommands",
    "FileCommands",
    "NetworkCommands",
    "ViewCommands",
]
