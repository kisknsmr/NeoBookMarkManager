"""Worker bus utilities (svc_ prefix)."""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, List

from PySide6.QtCore import QTimer

from services.ModelWorkerEvents import WorkerEvent, PreviewFetchedEvent, TitleFixDoneEvent, event_from_tuple


class WorkerEventHandler:
    """Default app-level worker event handler (UI-friendly callbacks injected)."""

    def __init__(
        self,
        *,
        search_service,
        refresh_list: Callable[[], None],
        status_message: Callable[..., None],
        titlefix_nodes_getter: Callable[[], list],
        titlefix_nodes_setter: Callable[[list], None],
    ) -> None:
        self.search_service = search_service
        self.refresh_list = refresh_list
        self.status_message = status_message
        self._get_titlefix_nodes = titlefix_nodes_getter
        self._set_titlefix_nodes = titlefix_nodes_setter

    def handle(self, event: WorkerEvent) -> None:
        if isinstance(event, PreviewFetchedEvent):
            nodes = self.search_service.find_by_url(event.url)
            for node in nodes:
                if event.title and not node.title:
                    node.title = event.title
                if event.description:
                    node.description = event.description
                self.search_service.update_node(node)
            self.refresh_list()
            return
        if isinstance(event, TitleFixDoneEvent):
            self.status_message("Title fix complete", 4000)
            for node in self._get_titlefix_nodes() or []:
                self.search_service.update_node(node)
            self._set_titlefix_nodes([])
            self.refresh_list()
            return
        if hasattr(event, "percentage"):
            pct = event.percentage if isinstance(event.percentage, (int, float)) else 0
            self.status_message(f"{event.__class__.__name__}: {pct:.0f}%")
        elif hasattr(event, "processed") and hasattr(event, "total"):
            self.status_message(f"Progress: {event.processed}/{event.total}")


class WorkerBus:
    """Queue polling + event dispatch."""

    def __init__(
        self,
        *,
        ui_queue: "queue.Queue[Any]",
        logger,
        qt_parent=None,
        poll_interval_ms: int = 200,
    ) -> None:
        self.ui_queue = ui_queue
        self.logger = logger
        self._handlers: List[Callable[[WorkerEvent], None]] = []
        self._timer = QTimer(qt_parent)
        self._timer.timeout.connect(self.poll_once)
        self._poll_interval_ms = int(poll_interval_ms)

    def on_event(self, handler: Callable[[WorkerEvent], None]) -> None:
        self._handlers.append(handler)

    def start(self) -> None:
        self._timer.start(self._poll_interval_ms)

    def stop(self) -> None:
        self._timer.stop()

    def submit(self, target: Callable, *args: Any) -> None:
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()

    def poll_once(self) -> None:
        try:
            while not self.ui_queue.empty():
                item = self.ui_queue.get_nowait()
                if callable(item):
                    item()
                    continue
                if isinstance(item, WorkerEvent):
                    self._dispatch(item)
                elif isinstance(item, tuple) and len(item) == 2:
                    kind, payload = item
                    event = event_from_tuple(kind, payload)
                    self._dispatch(event)
        except queue.Empty:
            return
        except Exception as exc:  # pragma: no cover
            self.logger.error("Worker polling failed: %s", exc, exc_info=True)

    def _dispatch(self, event: WorkerEvent) -> None:
        for handler in list(self._handlers):
            try:
                handler(event)
            except Exception as exc:  # pragma: no cover
                self.logger.error("Worker event handler failed: %s", exc, exc_info=True)