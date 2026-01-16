"""
Network-related commands.
Handles preview fetching and title fixing from URLs.
"""

from PySide6.QtWidgets import QMessageBox

from services.WorkerNetwork import fetch_preview, fix_titles


class NetworkCommands:
    """Commands for network operations (preview, title fix)."""

    def __init__(self, window):
        """
        Initialize with main window reference.
        
        Args:
            window: MainWindow instance
        """
        self.window = window

    def fix_titles_from_url(self) -> None:
        """Fix bookmark titles by fetching from URLs."""
        self.enable_network_updates("タイトル取得")
        
        nodes = list(self.window.bookmark_service.iter_bookmarks(self.window.current_folder)) \
            if self.window.current_folder else []
        if not nodes:
            QMessageBox.information(self.window, "Info", "No bookmarks to update.")
            return

        # keep for search index update on completion
        self.window._titlefix_nodes = nodes
        
        proxy_info = self.window.config_manager.get_proxies_for_requests(
            use_proxy=self.window.use_proxy
        )
        self.window.statusBar().showMessage("Starting title fix...", 2000)
        self.window.worker_bus.submit(
            fix_titles,
            nodes,
            self.window.worker_bus.ui_queue,
            proxy_info,
            self.window.fetch_timeout,
            None,
            None
        )

    def fetch_preview(self) -> None:
        """Fetch preview for selected bookmark (on demand)."""
        if not self.window.selected_node or \
           self.window.selected_node.type != "bookmark":
            QMessageBox.information(
                self.window,
                "Info",
                "プレビュー取得はブックマークを選択してください。"
            )
            return
        
        self.enable_network_updates("プレビュー取得")
        self.enqueue_preview_fetch(self.window.selected_node)

    def enable_network_updates(self, reason: str) -> None:
        if not self.window.network_updates_enabled:
            self.window.network_updates_enabled = True
            self.window.statusBar().showMessage(f"ネットワーク更新を有効化: {reason}", 3000)

    def enqueue_preview_fetch(self, node) -> None:
        if not node or not getattr(node, "url", None):
            return
        if not self.window.network_updates_enabled:
            return

        proxy_info = self.window.config_manager.get_proxies_for_requests(use_proxy=self.window.use_proxy)
        self.window.worker_bus.submit(
            fetch_preview,
            node.url,
            self.window.worker_bus.ui_queue,
            proxy_info,
            self.window.fetch_timeout,
        )

    def check_proxy(self) -> None:
        """Check proxy settings."""
        settings = self.window.config_manager.get_proxy_settings()
        if not settings:
            QMessageBox.information(
                self.window,
                "Proxy",
                "Proxy is disabled or not configured."
            )
            return
        
        summary = settings.get("url", "")
        QMessageBox.information(self.window, "Proxy", f"Using proxy: {summary}")
