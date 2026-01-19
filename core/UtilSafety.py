"""
UtilSafety

URL canonicalization & tag normalization utilities.

Spec: AI機能実装計画.md
- safe_canonical (Default): keep scheme, keep fragment, remove utm_* query only, drop empty query, trim trailing slash
- aggressive_canonical: unify scheme (https), remove www., drop ALL query (warn in UI later)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def normalize_tag(tag: str) -> str:
    """Normalize tag for internal comparison (trim, lowercase, collapse spaces)."""
    t = (tag or "").strip().lower()
    t = " ".join(t.split())
    return t


def safe_canonical(url: str) -> str:
    """
    Safe canonicalization:
    - scheme preserved (http/https NOT unified)
    - fragment preserved
    - remove utm_* query params only
    - remove empty query
    - remove trailing slash on path (except when path == "/")
    """
    raw = (url or "").strip()
    if not raw:
        return ""

    parts = urlsplit(raw)
    scheme = (parts.scheme or "").lower()
    netloc = (parts.netloc or "").lower()
    path = parts.path or ""
    query = parts.query or ""
    fragment = parts.fragment or ""

    # Remove trailing slash for non-root paths
    if path.endswith("/") and path != "/":
        path = path[:-1]

    # Filter utm_* params
    if query:
        kv = [(k, v) for (k, v) in parse_qsl(query, keep_blank_values=True) if not k.lower().startswith("utm_")]
        query = urlencode(kv, doseq=True) if kv else ""

    return urlunsplit((scheme, netloc, path, query, fragment))


def aggressive_canonical(url: str) -> str:
    """
    Aggressive canonicalization (user must opt-in later):
    - unify scheme to https when scheme missing or http/https
    - remove www.
    - drop ALL query params
    - keep fragment (spec doesn't forbid; keep for safety)
    - trim trailing slash on path (except "/")
    """
    raw = (url or "").strip()
    if not raw:
        return ""

    parts = urlsplit(raw)
    scheme = (parts.scheme or "").lower()
    if scheme in ("", "http", "https"):
        scheme = "https"

    netloc = (parts.netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parts.path or ""
    if path.endswith("/") and path != "/":
        path = path[:-1]

    fragment = parts.fragment or ""
    return urlunsplit((scheme, netloc, path, "", fragment))


def detect_safe_canonical_collisions(urls: Iterable[str]) -> dict[str, list[str]]:
    """
    Detect collisions where multiple original URLs map to the same safe_canonical.
    Returns {canonical: [original1, original2, ...]} only for collisions (len>=2).
    """
    buckets: dict[str, list[str]] = {}
    for u in urls:
        canon = safe_canonical(u)
        if not canon:
            continue
        buckets.setdefault(canon, []).append(u)
    return {k: v for k, v in buckets.items() if len(v) >= 2}

