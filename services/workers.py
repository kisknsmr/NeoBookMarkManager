import time
try:
    import requests
except ImportError:
    requests = None
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

def fetch_preview(url, ui_queue, proxy_info=None):
    """ブックマークのプレビュー情報を非同期で取得（リトライ機能付き）。"""
    max_retries = 3
    retry_delay = 1
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
                timeout=5,
                headers={'User-Agent': 'Mozilla/5.0'},
                proxies=proxies,
                auth=auth
            )
            resp.raise_for_status()

            if BeautifulSoup:
                soup = BeautifulSoup(resp.text, "html.parser")
                title_tag = soup.find("meta", property="og:title") or soup.find("title")
                title = title_tag.get("content") if title_tag and title_tag.name == "meta" else (
                    title_tag.text if title_tag else "")
                desc_tag = soup.find("meta", property="og:description") or soup.find("meta",
                                                                                     attrs={"name": "description"})
                desc = desc_tag.get("content") if desc_tag else ""
                result = {"title": title.strip(), "description": desc.strip()}
            else:
                result = {"title": "No BeautifulSoup", "description": "Install bs4 for preview"}
            
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
            time.sleep(retry_delay * (2 ** attempt))

    result = {"title": "Could not load preview", "description": ""}
    ui_queue.put(('preview', (url, result)))


def fix_titles(nodes, ui_queue, proxy_info=None, timeout=10, logger=None, check_cancel=None):
    """各URLにアクセスし、タイトルを上書き。"""
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
            if BeautifulSoup:
                soup = BeautifulSoup(resp.text, "html.parser")
                title_tag = soup.find("meta", property="og:title") or soup.find("title")
                if title_tag and title_tag.name == "meta":
                    new_title = title_tag.get("content")
                elif title_tag:
                    new_title = title_tag.text
                if new_title: new_title = new_title.strip()
            
            if not new_title: new_title = "ERROR: No Title Found"
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
