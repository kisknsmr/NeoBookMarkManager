"""Rule/domain plan builders (svc_ prefix)."""

from __future__ import annotations

from typing import Dict, List, Optional
from urllib.parse import urlparse

from core.ModelBookmark import Node


def _iter_bookmarks(node: Node) -> List[Node]:
    bookmarks: List[Node] = []
    for child in getattr(node, "children", []) or []:
        if child.type == "bookmark":
            bookmarks.append(child)
        elif child.type == "folder":
            bookmarks.extend(_iter_bookmarks(child))
    return bookmarks


def build_domain_plan(base_node: Optional[Node]) -> Dict[str, List[Node]]:
    plan: Dict[str, List[Node]] = {}
    if not base_node:
        return plan
    for node in _iter_bookmarks(base_node):
        domain = urlparse(node.url or "").netloc or "Unsorted"
        plan.setdefault(domain, []).append(node)
    return plan


def build_rules_plan(base_node: Optional[Node], rules: dict) -> Dict[str, List[Node]]:
    plan: Dict[str, List[Node]] = {}
    if not base_node or not rules:
        return plan
    for node in _iter_bookmarks(base_node):
        title = (node.title or "").lower()
        url = (node.url or "").lower()
        domain = urlparse(node.url or "").netloc.lower()
        for folder, rule in rules.items():
            domains = [d.lower() for d in rule.get("domains", [])]
            keywords = [k.lower() for k in rule.get("keywords", [])]
            if any(d in domain for d in domains) or any(k in title or k in url for k in keywords):
                plan.setdefault(folder, []).append(node)
                break
    return plan