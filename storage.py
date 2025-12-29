import os
import configparser
import json

"""
ストレージ／設定モジュール。
- `ConfigManager` : `config.ini` を管理するクラス
"""


class ConfigManager:
    """設定ファイル(config.ini)の管理を専門に行うクラス（`bookmark_editor.py` から移植）。"""

    def __init__(self, config_path='config.ini'):
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        self.load_config()

    def load_config(self):
        if os.path.exists(self.config_path):
            self.config.read(self.config_path, encoding='utf-8')

    def get_proxy_settings(self):
        if 'Proxy' not in self.config:
            return None
        proxy_section = self.config['Proxy']
        return {
            'url': proxy_section.get('url'),
            'user': proxy_section.get('user'),
            'password': proxy_section.get('password')
        }

    def get_priority_terms(self):
        if not (self.config.has_section('Classifier') and
                self.config.has_option('Classifier', 'priority_terms')):
            return []
        terms_str = self.config.get('Classifier', 'priority_terms')
        return [term.strip() for term in terms_str.split(',') if term.strip()]


from model import NetscapeBookmarkParser, export_netscape_html


def load_bookmarks(path: str):
    """Load bookmarks HTML and associated rules sidecar.

    Returns (root_node, rules, rules_path)
    Raises exceptions on I/O or parse errors.
    """
    with open(path, 'r', encoding='utf-8') as f:
        data = f.read()
    parser = NetscapeBookmarkParser()
    parser.feed(data)
    root = parser.root
    sidecar = os.path.splitext(path)[0] + '.bookmark_rules.json'
    rules = None
    rules_path = None
    if os.path.exists(sidecar):
        try:
            with open(sidecar, 'r', encoding='utf-8') as rf:
                rules = json.load(rf)
                rules_path = sidecar
        except Exception:
            rules = None
            rules_path = None
    return root, (rules or {}), rules_path


def save_bookmarks(path: str, root_node, rules: dict | None = None):
    """Save bookmarks HTML and optional rules sidecar. Raises on I/O errors."""
    html_text = export_netscape_html(root_node)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html_text)
    if rules:
        sp = os.path.splitext(path)[0] + '.bookmark_rules.json'
        with open(sp, 'w', encoding='utf-8') as wf:
            json.dump(rules, wf, ensure_ascii=False, indent=2)
        return sp
    return None


def load_rules(path: str):
    """Load rules JSON from a sidecar path. Returns dict."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_rules(path: str, rules: dict):
    """Save rules dict to given sidecar path."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)
    return path

