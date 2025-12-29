import re
from urllib.parse import urlparse
from collections import OrderedDict

"""
ユーティリティモジュール。
- `is_valid_url` : URL 検証
- `LRUCache` : シンプルな LRU キャッシュ
"""


def is_valid_url(url: str) -> bool:
    """より厳密なURL検証（元の `bookmark_editor.py` から移植）。"""
    if not url:
        return False
    try:
        result = urlparse(url)
        if not all([result.scheme, result.netloc]):
            return False
        if result.scheme.lower() not in ['http', 'https', 'ftp', 'file']:
            return False
        if result.scheme.lower() in ['http', 'https']:
            hostname_pattern = re.compile(
                r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$')
            if not hostname_pattern.match(result.netloc.split(':')[0]):
                return False
        return True
    except (ValueError, AttributeError):
        return False


class LRUCache(OrderedDict):
    """容量制限付きのキャッシュ(Least Recently Used)。"""

    def __init__(self, maxsize=100):
        super().__init__()
        self.maxsize = maxsize

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            self.popitem(last=False)
