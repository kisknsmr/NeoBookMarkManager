"""Search controller.

Handles: UI events -> SearchService -> AppState updates -> refresh.
Moves debounce logic out of MainWindow.
"""

from PySide6.QtCore import QTimer


class SearchController:
    def __init__(
        self,
        *,
        window,
        app_state,
        search_service,
        debounce_ms: int = 200,
        parent=None,
    ) -> None:
        self.window = window
        self.app_state = app_state
        self.search_service = search_service
        self.debounce_ms = int(debounce_ms)

        self._pending_query = ""

        self._query_timer = QTimer(parent or window)
        self._query_timer.setSingleShot(True)
        self._query_timer.timeout.connect(self.apply_pending)

        self._tree_timer = QTimer(parent or window)
        self._tree_timer.setSingleShot(True)
        self._tree_timer.timeout.connect(self.refresh_tree_if_needed)

    def on_text_changed(self, query: str) -> None:
        self._pending_query = query
        self._query_timer.stop()
        delay_ms = 80 if not query.strip() else self.debounce_ms
        self._query_timer.start(max(0, int(delay_ms)))

    def on_triggered(self, query: str) -> None:
        self._query_timer.stop()
        self._pending_query = query
        self.apply_query(query)
        self.window.refresh_list()
        self.window.refresh_counts()
        self.window.refresh_tree(select_node=self.window.current_folder or self.window.root_node)

    def apply_pending(self) -> None:
        query = self._pending_query
        self.apply_query(query)
        self.window.refresh_list()
        self.window.refresh_counts()

        delay_ms = 80 if not query.strip() else self.debounce_ms
        self.schedule_tree_refresh(delay_ms=delay_ms)

    def schedule_tree_refresh(self, *, delay_ms: int = 200) -> None:
        self._tree_timer.stop()
        self._tree_timer.start(max(0, int(delay_ms)))

    def refresh_tree_if_needed(self) -> None:
        self.window.refresh_tree(select_node=self.window.current_folder or self.window.root_node)

    def apply_query(self, query: str) -> None:
        self.app_state.set_search_query(query)
        if not query.strip():
            self.app_state.search_hits.clear()
            return

        hits = self.search_service.query(query)
        self.app_state.search_hits = hits
