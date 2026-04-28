"""Core utility shims for compatibility.

Provides `logger`, `LRUCache`, and `is_valid_url` expected by other modules.
"""
import logging
from collections import OrderedDict
from typing import Any, Optional
from urllib.parse import urlparse

# Basic app-wide logger
logger = logging.getLogger("NeoBookMarkManager")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

class LRUCache:
    """Minimal LRU cache with `get`, `set`, and `clear` methods."""
    def __init__(self, maxsize: int = 128) -> None:
        self.maxsize = maxsize
        self._data: OrderedDict[Any, Any] = OrderedDict()

    def get(self, key: Any, default: Optional[Any] = None) -> Any:
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return default

    def set(self, key: Any, value: Any) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    # Dict-like interface for compatibility
    def __contains__(self, key: Any) -> bool:
        return key in self._data

    def __getitem__(self, key: Any) -> Any:
        val = self.get(key)
        if val is None and key not in self._data:
            raise KeyError(key)
        return val

    def __setitem__(self, key: Any, value: Any) -> None:
        self.set(key, value)

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def pop(self, key: Any, default: Optional[Any] = None) -> Any:
        if key in self._data:
            return self._data.pop(key)
        if default is not None:
            return default
        raise KeyError(key)

    def items(self):
        return self._data.items()

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

def is_valid_url(url: str) -> bool:
    """Return True if URL has http/https scheme and a netloc."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False

def normalize_tag(name: str) -> str:
    """Normalize tag names for uniqueness.

    Lowercase, strip surrounding spaces, collapse inner whitespace to single
    hyphen, and remove simple punctuation at ends.
    """
    if not isinstance(name, str):
        return ""
    s = name.strip().lower()
    # Collapse whitespace to single hyphen
    parts = s.split()
    s = "-".join(parts)
    # Trim common punctuation
    s = s.strip("#@!.,;:()[]{}")
    return s
