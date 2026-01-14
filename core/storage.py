import os
import configparser
import json
import re
from urllib.parse import urlparse
from typing import Optional, Dict, Any
from .logger import logger

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
        """設定ファイルを読み込む"""
        if os.path.exists(self.config_path):
            try:
                self.config.read(self.config_path, encoding='utf-8')
                logger.info(f"Loaded configuration from {self.config_path}")
            except Exception as e:
                logger.error(f"Failed to load configuration from {self.config_path}: {e}")
        else:
            logger.warning(f"Configuration file not found at {self.config_path}")

    def get_api_key(self) -> Optional[str]:
        """
        APIキーを取得する（環境変数を優先）。
        
        優先順位:
        1. 環境変数 GENAI_API_KEY
        2. 環境変数 GOOGLE_API_KEY
        3. config.ini の [API] セクション
        
        Returns:
            APIキー文字列、見つからない場合はNone
        """
        # 環境変数を優先（セキュリティベストプラクティス）
        key = os.environ.get("GENAI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if key:
            return key.strip()
        
        # フォールバック: config.ini
        if os.path.exists(self.config_path):
            if self.config.has_section("API") and self.config.has_option("API", "api_key"):
                return self.config.get("API", "api_key", fallback=None)
        return None

    def _validate_proxy_url(self, url: Optional[str]) -> bool:
        """
        プロキシURLの形式を検証する
        
        Args:
            url: 検証するURL文字列
            
        Returns:
            有効な場合はTrue、無効な場合はFalse
        """
        if not url:
            return False
        try:
            parsed = urlparse(url)
            # httpまたはhttpsスキームを要求
            if parsed.scheme.lower() not in ('http', 'https'):
                logger.warning(f"Invalid proxy scheme: {parsed.scheme}")
                return False
            # ホスト名が存在することを確認
            if not parsed.netloc:
                logger.warning("Invalid proxy URL: missing hostname")
                return False
            return True
        except Exception as e:
            logger.error(f"Error validating proxy URL '{url}': {e}")
            return False

    def get_proxy_settings(self) -> Optional[Dict[str, Any]]:
        """
        プロキシ設定を取得し、検証する
        
        Returns:
            プロキシ設定の辞書（'url', 'user', 'password'を含む）、
            無効な設定または設定がない場合はNone
        """
        if 'Proxy' not in self.config:
            return None
        
        proxy_section = self.config['Proxy']
        url = proxy_section.get('url')
        
        # URL検証
        if not self._validate_proxy_url(url):
            return None
        
        return {
            'url': url,
            'user': proxy_section.get('user'),
            'password': proxy_section.get('password')
        }

    def get_proxies_for_requests(self, use_proxy: bool = True) -> Optional[Dict[str, Any]]:
        """
        requestsライブラリ用にプロキシ設定を返す（共通化）
        
        Args:
            use_proxy: プロキシを使用するかどうか
            
        Returns:
            {'proxies': {...}, 'auth': ...} の形式、またはNone
        """
        if not use_proxy:
            return None

        settings = self.get_proxy_settings()
        if not settings or not settings.get('url'):
            return None

        proxy_url = settings['url']
        user = settings.get('user')
        password = settings.get('password')

        auth = (user, password) if user and password else None

        proxies = {
            'http': proxy_url,
            'https': proxy_url
        }
        return {'proxies': proxies, 'auth': auth}

    def get_priority_terms(self) -> list[str]:
        """優先分類用語のリストを取得する"""
        if not (self.config.has_section('Classifier') and
                self.config.has_option('Classifier', 'priority_terms')):
            return []
        terms_str = self.config.get('Classifier', 'priority_terms')
        return [term.strip() for term in terms_str.split(',') if term.strip()]

    def get(self, section: str, option: str, fallback: Optional[Any] = None) -> Optional[Any]:
        """
        汎用的に config.ini から値を取得する。
        
        Args:
            section: セクション名
            option: オプション名
            fallback: デフォルト値（セクション/オプションが存在しない場合に返す）
            
        Returns:
            取得した値、またはfallback
        """
        try:
            if self.config.has_section(section) and self.config.has_option(section, option):
                return self.config.get(section, option)
            return fallback
        except Exception as e:
            logger.warning(f"Error getting config [{section}].{option}: {e}")
            return fallback

    def set(self, section: str, option: str, value: Any) -> bool:
        """
        汎用的に config.ini に値を設定・保存する。
        
        Args:
            section: セクション名
            option: オプション名
            value: 設定値
            
        Returns:
            成功時True、失敗時False
        """
        try:
            if not self.config.has_section(section):
                self.config.add_section(section)
            self.config.set(section, option, str(value))
            with open(self.config_path, 'w', encoding='utf-8') as f:
                self.config.write(f)
            logger.info(f"Set [{section}].{option} = {value}")
            return True
        except Exception as e:
            logger.error(f"Error setting config [{section}].{option}: {e}")
            return False


from .model import NetscapeBookmarkParser, export_netscape_html, Node


def load_bookmarks(path: str) -> tuple[Node, dict, Optional[str]]:
    """Load bookmarks HTML and associated rules sidecar.

    Args:
        path: ブックマークHTMLファイルのパス
        
    Returns:
        (root_node, rules, rules_path) のタプル
        
    Raises:
        IOError: ファイル読み込みエラー
        ValueError: パースエラー
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = f.read()
        logger.info(f"Loaded bookmarks file: {path}")
    except FileNotFoundError:
        logger.error(f"Bookmarks file not found: {path}")
        raise IOError(f"File not found: {path}")
    except Exception as e:
        logger.error(f"Error reading bookmarks file {path}: {e}")
        raise IOError(f"Failed to read file: {e}")

    try:
        parser = NetscapeBookmarkParser()
        parser.feed(data)
        root = parser.root
    except Exception as e:
        logger.error(f"Error parsing bookmarks data: {e}")
        raise ValueError(f"Failed to parse bookmarks: {e}")

    sidecar = os.path.splitext(path)[0] + '.bookmark_rules.json'
    rules = None
    rules_path = None
    if os.path.exists(sidecar):
        try:
            with open(sidecar, 'r', encoding='utf-8') as rf:
                rules = json.load(rf)
                rules_path = sidecar
                logger.info(f"Loaded rules file: {sidecar}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in rules file {sidecar}: {e}")
            rules = None
        except Exception as e:
            logger.error(f"Error reading rules file {sidecar}: {e}")
            rules = None
    
    return root, (rules or {}), rules_path


def save_bookmarks(path: str, root_node: Node, rules: Optional[dict] = None) -> Optional[str]:
    """
    Save bookmarks HTML and optional rules sidecar.
    
    Args:
        path: 保存先のファイルパス
        root_node: ルートノード
        rules: 分類ルール辞書（オプション）
        
    Returns:
        ルールファイルのパス（rulesがNoneの場合はNone）
        
    Raises:
        IOError: ファイル書き込みエラー
    """
    try:
        html_text = export_netscape_html(root_node)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html_text)
        logger.info(f"Saved bookmarks to {path}")
    except Exception as e:
        logger.error(f"Failed to save bookmarks to {path}: {e}")
        raise IOError(f"Failed to save bookmarks: {e}")

    if rules:
        sp = os.path.splitext(path)[0] + '.bookmark_rules.json'
        try:
            with open(sp, 'w', encoding='utf-8') as wf:
                json.dump(rules, wf, ensure_ascii=False, indent=2)
            logger.info(f"Saved rules to {sp}")
            return sp
        except Exception as e:
            logger.error(f"Failed to save rules to {sp}: {e}")
            # rules are secondary, so we might not want to crash everything if this fails, 
            # but usually it's good to know. For now, log it.
            return None
    return None


def load_rules(path: str) -> dict:
    """
    Load rules JSON from a sidecar path.
    
    Args:
        path: ルールファイルのパス
        
    Returns:
        ルール辞書
        
    Raises:
        IOError: ファイル読み込みエラー
        json.JSONDecodeError: JSONパースエラー
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            rules = json.load(f)
            logger.info(f"Loaded rules from {path}")
            return rules
    except FileNotFoundError:
        logger.error(f"Rules file not found: {path}")
        raise IOError(f"File not found: {path}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in {path}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error loading rules from {path}: {e}")
        raise IOError(f"Failed to load rules: {e}")


def save_rules(path: str, rules: dict) -> str:
    """
    Save rules dict to given sidecar path.
    
    Args:
        path: 保存先のファイルパス
        rules: ルール辞書
        
    Returns:
        保存したファイルのパス
        
    Raises:
        IOError: ファイル書き込みエラー
    """
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved rules to {path}")
        return path
    except Exception as e:
        logger.error(f"Failed to save rules to {path}: {e}")
        raise IOError(f"Failed to save rules: {e}")

