import time
import queue
from typing import Optional, Dict, Any, Callable
from functools import lru_cache

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
from core.logger import logger
from urllib.parse import urlparse, urljoin
import base64


# ==================== I/O 堅牢化・キャッシュ ====================

@lru_cache(maxsize=256)
def _cached_extract_title_and_description(html_hash: str, html_content: str) -> Dict[str, str]:
    """
    HTMLからタイトル・説明を抽出（内容ハッシュでキャッシュ）。
    実装上は html_content を直接使って解析。
    
    Note: LRU キャッシュのキーとして html_hash を使用し、
    html_content は参照用です。実際にはレジストリに登録済みの
    HTMLのみがキャッシュされることを想定。
    """
    if not BeautifulSoup:
        return {"title": "No BeautifulSoup", "description": "Install bs4 for preview"}
    
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        title_tag = soup.find("meta", property="og:title") or soup.find("title")
        if title_tag and title_tag.name == "meta":
            title = title_tag.get("content", "")
        elif title_tag:
            title = title_tag.text
        else:
            title = ""
        
        desc_tag = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
        description = desc_tag.get("content", "") if desc_tag else ""
        
        return {
            "title": title.strip(),
            "description": description.strip()
        }
    except Exception as e:
        logger.error(f"Error parsing HTML content: {e}")
        return {"title": "Parse Error", "description": ""}


def _extract_title_and_description(html_content: str) -> Dict[str, str]:
    """
    HTMLコンテンツからタイトルと説明を抽出する共通関数。
    簡易キャッシュ対応版。
    
    Args:
        html_content: HTML文字列
        
    Returns:
        {'title': str, 'description': str} の辞書
    """
    # 簡易ハッシュ（キャッシュキーとして使用）
    html_hash = str(hash(html_content[:512]))
    return _cached_extract_title_and_description(html_hash, html_content)

def fetch_preview(url: str, ui_queue: 'queue.Queue', proxy_info: Optional[Dict[str, Any]] = None, 
                  timeout: int = None) -> None:
    """
    ブックマークのプレビュー情報を非同期で取得（リトライ・例外堅牢化）。
    
    Args:
        url: 取得するURL
        ui_queue: UI更新用のキュー
        proxy_info: プロキシ設定（オプション）
        timeout: リクエストタイムアウト（秒、デフォルト: AppConstants.PREVIEW_FETCH_TIMEOUT）
    """
    if timeout is None:
        timeout = getattr(AppConstants, 'PREVIEW_FETCH_TIMEOUT', 10)
    
    max_retries = getattr(AppConstants, 'MAX_RETRIES', 3)
    retry_delay = getattr(AppConstants, 'RETRY_DELAY_BASE', 1)

    for attempt in range(max_retries):
        try:
            if not requests:
                logger.warning("Requests library not installed.")
                ui_queue.put(('preview', (url, {"title": "No requests lib", "description": "Install requests"})))
                return
            
            proxies = proxy_info.get('proxies') if proxy_info else None
            auth = proxy_info.get('auth') if proxy_info else None

            logger.debug(f"Fetching preview for {url} (Attempt {attempt + 1}/{max_retries}, timeout={timeout}s)")
            resp = requests.get(
                url,
                timeout=timeout,
                headers={'User-Agent': 'Mozilla/5.0'},
                proxies=proxies,
                auth=auth
            )
            resp.raise_for_status()

            result = _extract_title_and_description(resp.text)
            ui_queue.put(('preview', (url, result)))
            logger.info(f"Successfully fetched preview for {url}")
            return

        except requests.exceptions.Timeout as e:
            logger.warning(f"Timeout for {url} (attempt {attempt + 1}/{max_retries}): {e}")
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Connection error for {url} (attempt {attempt + 1}/{max_retries}): {e}")
        except requests.exceptions.HTTPError as e:
            # 404は リトライしない
            if hasattr(e, 'response') and e.response.status_code == 404:
                logger.warning(f"URL not found (404) for {url}. No retries.")
                ui_queue.put(('preview', (url, {"title": "Not Found (404)", "description": ""})))
                return
            logger.warning(f"HTTP error for {url} (attempt {attempt + 1}/{max_retries}): {e}")
        except requests.exceptions.RequestException as e:
            # requests 系の例外（RequestException に統合）
            logger.warning(f"Request exception for {url} (attempt {attempt + 1}/{max_retries}): {e}")
        except Exception as e:
            logger.error(f"Unexpected error for {url}: {type(e).__name__}: {e}")
            break

        if attempt < max_retries - 1:
            time.sleep(retry_delay * (2 ** attempt))  # 指数バックオフ

    # 全リトライ失敗時
    result = {"title": "Could not load preview", "description": ""}
    ui_queue.put(('preview', (url, result)))
    logger.error(f"Failed to fetch preview for {url} after {max_retries} attempts")


def fix_titles(
    nodes: list[Node], 
    ui_queue: 'queue.Queue', 
    proxy_info: Optional[Dict[str, Any]] = None, 
    timeout: int = None, 
    logger_arg: Optional[Any] = None, 
    check_cancel: Optional[Callable[[], bool]] = None
) -> None:
    """
    各URLにアクセスし、タイトルを上書きする（堅牢化版）。
    
    Args:
        nodes: タイトルを修正するノードのリスト
        ui_queue: UI更新用のキュー
        proxy_info: プロキシ設定（オプション）
        timeout: リクエストタイムアウト（秒、デフォルト: DEFAULT_FETCH_TIMEOUT）
        logger_arg: (deprecated) グローバル logger を使用
        check_cancel: キャンセルチェック関数（オプション）
    """
    if timeout is None:
        timeout = getattr(AppConstants, 'DEFAULT_FETCH_TIMEOUT', 10)
    
    processed = 0
    total = len(nodes)
    
    logger.info(f"Starting title fix for {total} nodes (timeout={timeout}s).")

    for n in nodes:
        if check_cancel and check_cancel(): 
            logger.info("Title fix cancelled by user.")
            break
        
        new_title = None
        try:
            if not requests:
                raise ImportError("requests library not installed")

            proxies = proxy_info.get('proxies') if proxy_info else None
            auth = proxy_info.get('auth') if proxy_info else None

            resp = requests.get(n.url, headers={'User-Agent': 'Mozilla/5.0'}, 
                                proxies=proxies, auth=auth, timeout=timeout)
            resp.raise_for_status()
            
            extracted = _extract_title_and_description(resp.text)
            new_title = extracted.get("title")
            
            if not new_title: 
                new_title = "ERROR: No Title Found"
            
            logger.debug(f"Fixed title for {n.url} -> {new_title}")

        except requests.exceptions.Timeout as e:
            logger.warning(f"Timeout for {n.url}: {e}")
            new_title = f"ERROR: Timeout"
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Connection error for {n.url}: {e}")
            new_title = f"ERROR: Connection"
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP error for {n.url}: {e}")
            new_title = f"ERROR: HTTP {getattr(e.response, 'status_code', '?')}"
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request error for {n.url}: {e}")
            new_title = f"ERROR: {type(e).__name__}"
        except Exception as e:
            logger.warning(f"Unexpected error for {n.url}: {type(e).__name__}: {e}")
            new_title = f"ERROR: {type(e).__name__}"
            
        # new_title が None でなければ反映
        if new_title:
            n.title = new_title
        
        processed += 1
        ui_queue.put(('titlefix_progress', (processed, total)))
    
    ui_queue.put(('titlefix_done', None))
    logger.info("Title fix completed.")


def fetch_favicon(url: str, proxy_info: Optional[Dict[str, Any]] = None, timeout: int = 3) -> Optional[str]:
    """
    URLからファビコンを取得する（複数の方法を試行、堅牢化版）。
    
    Args:
        url: ファビコンを取得するURL
        proxy_info: プロキシ設定（オプション）
        timeout: リクエストタイムアウト（秒）
        
    Returns:
        ファビコンのbase64データURI、またはNone
    """
    if not requests:
        logger.warning("Requests library missing, cannot fetch favicon.")
        return None
    
    try:
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        # ファビコン取得の優先順位
        favicon_urls = [
            f"{base_url}/favicon.ico",
            f"{base_url}/favicon.png",
            urljoin(base_url, "/apple-touch-icon.png"),
            urljoin(base_url, "/apple-touch-icon-precomposed.png"),
        ]
        
        proxies = proxy_info.get('proxies') if proxy_info else None
        auth = proxy_info.get('auth') if proxy_info else None
        
        for favicon_url in favicon_urls:
            try:
                resp = requests.get(
                    favicon_url,
                    timeout=timeout,
                    headers={'User-Agent': 'Mozilla/5.0'},
                    proxies=proxies,
                    auth=auth,
                    stream=True
                )
                if resp.status_code == 200:
                    content_type = resp.headers.get('Content-Type', 'image/x-icon')
                    if 'image' in content_type:
                        img_data = resp.content
                        if len(img_data) > 0:
                            base64_data = base64.b64encode(img_data).decode('utf-8')
                            return f"data:{content_type};base64,{base64_data}"
            except requests.exceptions.RequestException as e:
                logger.debug(f"Failed to fetch favicon from {favicon_url}: {type(e).__name__}")
                continue
            except Exception as e:
                logger.debug(f"Unexpected error fetching favicon from {favicon_url}: {e}")
                continue
        
        # Google Favicon APIをフォールバックとして使用
        try:
            google_favicon_url = f"https://www.google.com/s2/favicons?domain={parsed.netloc}&sz=32"
            resp = requests.get(google_favicon_url, timeout=timeout, proxies=proxies, auth=auth, stream=True)
            if resp.status_code == 200:
                img_data = resp.content
                if len(img_data) > 0:
                    base64_data = base64.b64encode(img_data).decode('utf-8')
                    logger.debug(f"Got favicon for {url} from Google API")
                    return f"data:image/png;base64,{base64_data}"
        except requests.exceptions.RequestException as e:
            logger.debug(f"Failed to fetch favicon from Google API: {type(e).__name__}")
        except Exception as e:
            logger.debug(f"Unexpected error with Google favicon API: {e}")
    
    except Exception as e:
        logger.warning(f"Error in fetch_favicon for {url}: {e}")
    
    return None
