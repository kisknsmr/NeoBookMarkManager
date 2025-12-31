import time
import logging
import queue
from typing import Optional, Dict, Any, Callable

try:
    import requests
except ImportError:
    requests = None
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from core.utils import AppConstants
from core.model import Node
from urllib.parse import urlparse, urljoin
import base64


def _extract_title_and_description(html_content: str) -> Dict[str, str]:
    """
    HTMLコンテンツからタイトルと説明を抽出する共通関数
    
    Args:
        html_content: HTML文字列
        
    Returns:
        {'title': str, 'description': str} の辞書
    """
    if not BeautifulSoup:
        return {"title": "No BeautifulSoup", "description": "Install bs4 for preview"}
    
    soup = BeautifulSoup(html_content, "html.parser")
    
    # タイトル抽出（og:title > title の順で優先）
    title_tag = soup.find("meta", property="og:title") or soup.find("title")
    if title_tag and title_tag.name == "meta":
        title = title_tag.get("content", "")
    elif title_tag:
        title = title_tag.text
    else:
        title = ""
    
    # 説明抽出（og:description > meta[name="description"] の順で優先）
    desc_tag = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
    description = desc_tag.get("content", "") if desc_tag else ""
    
    return {
        "title": title.strip(),
        "description": description.strip()
    }

def fetch_preview(url: str, ui_queue: 'queue.Queue', proxy_info: Optional[Dict[str, Any]] = None) -> None:
    """
    ブックマークのプレビュー情報を非同期で取得（リトライ機能付き）。
    
    Args:
        url: 取得するURL
        ui_queue: UI更新用のキュー
        proxy_info: プロキシ設定（オプション）
    """
    max_retries = AppConstants.MAX_RETRIES
    retry_delay = AppConstants.RETRY_DELAY_BASE
    logger = logging.getLogger(__name__)

    for attempt in range(max_retries):
        try:
            if not requests:
                ui_queue.put(('preview', (url, {"title": "No requests lib", "description": "Install requests"})))
                return
            
            proxies = proxy_info['proxies'] if proxy_info else None
            auth = proxy_info['auth'] if proxy_info else None

            resp = requests.get(
                url,
                timeout=AppConstants.PREVIEW_FETCH_TIMEOUT,
                headers={'User-Agent': 'Mozilla/5.0'},
                proxies=proxies,
                auth=auth
            )
            resp.raise_for_status()

            # 共通のHTMLパース関数を使用
            result = _extract_title_and_description(resp.text)
            ui_queue.put(('preview', (url, result)))
            return

        except requests.exceptions.Timeout as e:
            logger.warning(f"Timeout for {url} (attempt {attempt + 1}): {e}")
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Connection error for {url} (attempt {attempt + 1}): {e}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"URL not found (404) for {url}. No retries.")
                break
            logger.warning(f"HTTP error for {url} (attempt {attempt + 1}): {e}")
        except Exception as e:
            logger.error(f"Unexpected error for {url}: {e}")
            break

        if attempt < max_retries - 1:
            time.sleep(retry_delay * (2 ** attempt))  # 指数バックオフ

    result = {"title": "Could not load preview", "description": ""}
    ui_queue.put(('preview', (url, result)))


def fix_titles(
    nodes: list[Node], 
    ui_queue: 'queue.Queue', 
    proxy_info: Optional[Dict[str, Any]] = None, 
    timeout: int = AppConstants.DEFAULT_FETCH_TIMEOUT, 
    logger: Optional[logging.Logger] = None, 
    check_cancel: Optional[Callable[[], bool]] = None
) -> None:
    """
    各URLにアクセスし、タイトルを上書きする。
    
    Args:
        nodes: タイトルを修正するノードのリスト
        ui_queue: UI更新用のキュー
        proxy_info: プロキシ設定（オプション）
        timeout: リクエストタイムアウト（秒）
        logger: ロガー（オプション）
        check_cancel: キャンセルチェック関数（オプション）
    """
    processed = 0
    total = len(nodes)
    logger = logger or logging.getLogger(__name__)

    for n in nodes:
        if check_cancel and check_cancel(): break
        new_title = None
        try:
            if not requests:
                raise ImportError("requests library not installed")

            proxies = proxy_info['proxies'] if proxy_info else None
            auth = proxy_info['auth'] if proxy_info else None

            resp = requests.get(n.url, headers={'User-Agent': 'Mozilla/5.0'}, proxies=proxies, auth=auth,
                                timeout=timeout)
            resp.raise_for_status()
            
            # 共通のHTMLパース関数を使用
            extracted = _extract_title_and_description(resp.text)
            new_title = extracted.get("title")
            
            if not new_title: 
                new_title = "ERROR: No Title Found"
        except Exception as e:
            try:
                logger.warning("Title fix failed for %s: %s", n.url, str(e))
            except Exception:
                pass
            new_title = f"ERROR: {type(e).__name__}"
        n.title = new_title
        processed += 1
        ui_queue.put(('titlefix_progress', (processed, total)))
    ui_queue.put(('titlefix_done', None))


def fetch_favicon(url: str, proxy_info: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    URLからファビコンを取得する（複数の方法を試行）
    
    Args:
        url: ファビコンを取得するURL
        proxy_info: プロキシ設定（オプション）
        
    Returns:
        ファビコンのbase64データURI、またはNone
    """
    if not requests:
        return None
    
    logger = logging.getLogger(__name__)
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    
    # ファビコン取得の優先順位
    favicon_urls = [
        f"{base_url}/favicon.ico",  # 標準的な場所
        f"{base_url}/favicon.png",
        urljoin(base_url, "/apple-touch-icon.png"),
        urljoin(base_url, "/apple-touch-icon-precomposed.png"),
    ]
    
    proxies = proxy_info['proxies'] if proxy_info else None
    auth = proxy_info['auth'] if proxy_info else None
    
    for favicon_url in favicon_urls:
        try:
            resp = requests.get(
                favicon_url,
                timeout=3,
                headers={'User-Agent': 'Mozilla/5.0'},
                proxies=proxies,
                auth=auth,
                stream=True
            )
            if resp.status_code == 200:
                # 画像データをbase64に変換
                content_type = resp.headers.get('Content-Type', 'image/x-icon')
                if 'image' in content_type:
                    img_data = resp.content
                    if len(img_data) > 0:
                        base64_data = base64.b64encode(img_data).decode('utf-8')
                        return f"data:{content_type};base64,{base64_data}"
        except Exception as e:
            logger.debug(f"Failed to fetch favicon from {favicon_url}: {e}")
            continue
    
    # Google Favicon APIをフォールバックとして使用
    try:
        google_favicon_url = f"https://www.google.com/s2/favicons?domain={parsed.netloc}&sz=32"
        resp = requests.get(google_favicon_url, timeout=3, proxies=proxies, auth=auth, stream=True)
        if resp.status_code == 200:
            img_data = resp.content
            if len(img_data) > 0:
                base64_data = base64.b64encode(img_data).decode('utf-8')
                return f"data:image/png;base64,{base64_data}"
    except Exception as e:
        logger.debug(f"Failed to fetch favicon from Google API: {e}")
    
    return None
