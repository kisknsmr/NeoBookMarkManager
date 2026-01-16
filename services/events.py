"""
Worker Events - Type-safe event definitions for async operations.

(kind, payload) の tuple から dataclass イベントに移行。
型安全性と拡張性を向上させ、_handle_worker_event の分岐を明確化。
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
from core.model import Node


@dataclass
class WorkerEvent:
    """Base class for all worker events."""
    pass


@dataclass
class PreviewFetchedEvent(WorkerEvent):
    """Event: Preview/title fetch completed."""
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class TitleFixProgressEvent(WorkerEvent):
    """Event: Title fix progress update."""
    processed: int
    total: int

    @property
    def percentage(self) -> float:
        """Calculate progress percentage."""
        if self.total == 0:
            return 0.0
        return (self.processed / self.total) * 100


@dataclass
class TitleFixDoneEvent(WorkerEvent):
    """Event: Title fix completed."""
    total_processed: int
    total_failed: int = 0

    @property
    def success_count(self) -> int:
        """Calculate success count."""
        return self.total_processed - self.total_failed


@dataclass
class ClassificationProgressEvent(WorkerEvent):
    """Event: AI classification progress."""
    processed: int
    total: int
    current_node_title: Optional[str] = None

    @property
    def percentage(self) -> float:
        """Calculate progress percentage."""
        if self.total == 0:
            return 0.0
        return (self.processed / self.total) * 100


@dataclass
class ClassificationDoneEvent(WorkerEvent):
    """Event: AI classification completed."""
    total_processed: int
    total_moved: int
    error_message: Optional[str] = None


@dataclass
class ProxyTestEvent(WorkerEvent):
    """Event: Proxy connectivity test result."""
    success: bool
    latency_ms: Optional[float] = None
    error_message: Optional[str] = None


@dataclass
class GenericProgressEvent(WorkerEvent):
    """Event: Generic progress update."""
    operation: str  # e.g., "fetching", "sorting"
    status: str     # e.g., "Running", "Completed"
    progress: Optional[float] = None  # 0.0 - 1.0


def event_from_tuple(kind: str, payload: Any) -> WorkerEvent:
    """
    Convert legacy (kind, payload) tuple to typed event.
    
    For backward compatibility during migration.
    
    Args:
        kind: Event type string
        payload: Event data (format depends on kind)
        
    Returns:
        WorkerEvent subclass instance
    """
    if kind == "preview" and isinstance(payload, tuple) and len(payload) == 2:
        url, data = payload
        return PreviewFetchedEvent(
            url=url,
            title=data.get("title"),
            description=data.get("description"),
            metadata=data
        )
    elif kind == "titlefix_progress" and isinstance(payload, tuple) and len(payload) == 2:
        processed, total = payload
        return TitleFixProgressEvent(processed=processed, total=total)
    elif kind == "titlefix_done":
        return TitleFixDoneEvent(total_processed=payload if isinstance(payload, int) else 0)
    elif kind == "classify_progress" and isinstance(payload, tuple) and len(payload) >= 2:
        processed, total = payload[:2]
        current_title = payload[2] if len(payload) > 2 else None
        return ClassificationProgressEvent(processed=processed, total=total, current_node_title=current_title)
    elif kind == "classify_done" and isinstance(payload, tuple) and len(payload) == 2:
        processed, moved = payload
        return ClassificationDoneEvent(total_processed=processed, total_moved=moved)
    elif kind == "proxy_test" and isinstance(payload, tuple) and len(payload) >= 1:
        success = payload[0] if isinstance(payload[0], bool) else False
        latency = payload[1] if len(payload) > 1 else None
        error = payload[2] if len(payload) > 2 else None
        return ProxyTestEvent(success=success, latency_ms=latency, error_message=error)
    else:
        # Fallback to generic event
        return GenericProgressEvent(operation=kind, status="Unknown")
