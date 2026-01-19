"""
ServiceAutoTag - Local Auto-Tagging Service (Phase 2.3)

[Must] Tier 1: ルールベース判定 (高速・オフライン)
- ドメイン辞書（github.com -> Dev 等）
- キーワード判定（url に login -> Login, .pdf -> PDF 等）

[Must] Tier 2: 軽量スクレイピング (Safety)
- 実行条件: allow_network=True の場合のみ
- 取得対象: <title>, <meta name="keywords">, <meta property="article:tag">
- Timeout: 3秒（厳守）
- User-Agent: NeoBookmarkManager/1.0
- Error handling: すべて無視（スキップ）、処理継続

[Must] DB連携:
- DatabaseManager.save_tags_for_url(bookmark_id=..., tags=..., source='rule')
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import re
import requests
from bs4 import BeautifulSoup

from core.DatabaseManager import DatabaseManager
from core.ModelBookmark import Node
from core.UtilLogger import logger


@dataclass(frozen=True)
class AutoTagResult:
    processed: int
    tagged: int
    allow_network: bool
    scraped: int
    missing_id: int = 0
    save_failed: int = 0


class AutoTagService:
    USER_AGENT = "NeoBookmarkManager/1.0"
    TIMEOUT_SEC = 3

    # Tier1 presets (hard-coded for now; config.ini etc. later)
    DOMAIN_TAGS: Dict[str, List[str]] = {
        "github.com": ["Dev"],
        "gitlab.com": ["Dev"],
        "bitbucket.org": ["Dev"],
        "stackoverflow.com": ["Dev"],
        "youtube.com": ["Video"],
        "youtu.be": ["Video"],
        "docs.google.com": ["Docs"],
        "drive.google.com": ["Docs"],
        "qiita.com": ["Dev"],
        "zenn.dev": ["Dev"],
        "medium.com": ["Blog"],
        "note.com": ["Blog"],
        "news.ycombinator.com": ["News"],
        "reddit.com": ["Community"],
        "twitter.com": ["Social"],
        "x.com": ["Social"],
        "amazon.co.jp": ["Shopping"],
        "amazon.com": ["Shopping"],
        "support.google.com": ["Support"],
    }

    KEYWORD_RULES: List[Tuple[str, str]] = [
        ("login", "Login"),
        ("signin", "Login"),
        ("sign-in", "Login"),
        ("signup", "Signup"),
        ("register", "Signup"),
        (".pdf", "PDF"),
        ("/pdf", "PDF"),
        (".ppt", "Slides"),
        (".pptx", "Slides"),
        (".xls", "Excel"),
        (".xlsx", "Excel"),
        (".zip", "Download"),
        (".tar", "Download"),
        (".gz", "Download"),
        ("/api", "API"),
        ("docs", "Docs"),
        ("blog", "Blog"),
        ("news", "News"),
        ("wiki", "Wiki"),
        ("pricing", "Pricing"),
        ("support", "Support"),
    ]

    TOKEN_TAGS: Dict[str, str] = {
        # EN
        "doc": "Docs",
        "docs": "Docs",
        "documentation": "Docs",
        "api": "API",
        "blog": "Blog",
        "news": "News",
        "wiki": "Wiki",
        "video": "Video",
        "login": "Login",
        "signin": "Login",
        "signup": "Signup",
        "register": "Signup",
        "pricing": "Pricing",
        "support": "Support",
        "download": "Download",
        "release": "Release",
        "tutorial": "Tutorial",
        "guide": "Tutorial",
        # JP (very small)
        "ドキュメント": "Docs",
        "公式": "Official",
        "ニュース": "News",
        "ブログ": "Blog",
        "入門": "Tutorial",
        "チュートリアル": "Tutorial",
        "動画": "Video",
        "ログイン": "Login",
        "登録": "Signup",
    }

    def __init__(self, *, project_root, db_filename: str = "user_data.db") -> None:
        self.dbm = DatabaseManager(project_root=project_root, db_filename=db_filename)

    # ----------------------------- Tokenize / Normalize ------------------------------
    _TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[ぁ-ん]+|[ァ-ヴー]+|[一-龯]+")
    _STOPWORDS: Set[str] = {
        # EN
        "the", "and", "or", "of", "to", "in", "for", "with", "on", "at", "by", "from",
        "home", "index", "top", "page", "site",
        # JP (minimal)
        "公式", "ホーム", "トップ", "ページ", "サイト", "記事", "一覧", "まとめ", "検索", "無料",
        "ログイン", "登録", "新規", "利用規約", "プライバシー",
    }

    def _normalize_token(self, token: str) -> Optional[str]:
        s = (token or "").strip()
        if not s:
            return None
        # strip common bracket-like wrappers
        s = s.strip("[](){}<>【】『』「」\"'`")
        if not s:
            return None
        # ignore pure digits / too short / too long
        if s.isdigit():
            return None
        if len(s) > 40:
            return None
        # normalize for stopword check
        key = s.lower()
        if key in self._STOPWORDS:
            return None
        return s

    def _tokenize_text(self, text: str) -> List[str]:
        """
        Very lightweight "分かち書き":
        - Extract contiguous alnum / Hiragana / Katakana / Kanji runs
        - Remove stopwords / symbols
        """
        if not text:
            return []
        out: List[str] = []
        seen: Set[str] = set()
        for raw in self._TOKEN_RE.findall(text):
            t = self._normalize_token(raw)
            if not t:
                continue
            k = t.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(t)
            if len(out) >= 15:
                break
        return out

    def _extract_candidate_tags(self, text: str) -> List[str]:
        """
        Split by typical delimiters first, then tokenize each part.
        This helps keep meaningful Japanese compounds and avoids punctuation-as-tags.
        """
        if not text:
            return []
        parts = re.split(r"[,、/|｜·•・\n\r\t]+", text)
        out: List[str] = []
        seen: Set[str] = set()
        for p in parts:
            toks = self._tokenize_text(p)
            if not toks:
                continue
            for t in toks:
                k = t.lower()
                if k in seen:
                    continue
                seen.add(k)
                out.append(t)
                if len(out) >= 10:
                    return out
        return out

    def _domain(self, url: str) -> str:
        try:
            netloc = (urlparse(url).netloc or "").lower()
        except Exception:
            return ""
        if ":" in netloc:
            netloc = netloc.split(":", 1)[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc

    def _tier1_tags(self, url: str) -> List[str]:
        url_l = (url or "").lower()
        tags: List[str] = []
        domain = self._domain(url)
        tags.extend(self.DOMAIN_TAGS.get(domain, []))
        for key, tag in self.KEYWORD_RULES:
            if key in url_l:
                tags.append(tag)

        # URLからもトークン抽出してタグに寄せる（オフライン強化）
        try:
            parsed = urlparse(url)
            url_text = " ".join([parsed.netloc or "", parsed.path or ""])
        except Exception:
            url_text = url or ""
        for tok in self._tokenize_text(url_text)[:12]:
            mapped = self.TOKEN_TAGS.get(tok.lower()) or self.TOKEN_TAGS.get(tok)
            if mapped:
                tags.append(mapped)
        return tags

    def _tier2_scrape_tags(self, url: str, *, proxy_info: Optional[dict] = None) -> List[str]:
        """
        returns tags from meta keywords/article:tag; title is used only for keyword-based heuristics (minimal).
        """
        try:
            proxies = proxy_info.get("proxies") if proxy_info else None
            auth = proxy_info.get("auth") if proxy_info else None
            resp = requests.get(
                url,
                timeout=self.TIMEOUT_SEC,
                headers={"User-Agent": self.USER_AGENT},
                proxies=proxies,
                auth=auth,
            )
            if not (200 <= int(resp.status_code) < 400):
                return []
            html = resp.text or ""
        except Exception:
            return []

        try:
            soup = BeautifulSoup(html, "html.parser")
            head = soup.find("head") or soup
            tags: List[str] = []

            # <meta name="keywords" content="a,b,c">
            kw = head.find("meta", attrs={"name": "keywords"})
            if kw and kw.get("content"):
                tags.extend(self._extract_candidate_tags(kw.get("content") or ""))

            # <meta property="article:tag" content="tag">
            for mt in head.find_all("meta", attrs={"property": "article:tag"}):
                c = (mt.get("content") or "").strip()
                if c:
                    tags.extend(self._extract_candidate_tags(c))

            # <title> ... </title> (use for small heuristic)
            t = head.find("title")
            title = (t.get_text(strip=True) if t else "")
            title_l = title.lower()
            if "login" in title_l or "sign in" in title_l:
                tags.append("Login")
            if "pdf" in title_l:
                tags.append("PDF")
            # Tokenize title lightly (avoid flooding)
            for tt in self._tokenize_text(title)[:6]:
                tags.append(tt)

            # safety limits
            cleaned: List[str] = []
            seen: Set[str] = set()
            for x in tags:
                s = (x or "").strip()
                if not s:
                    continue
                if len(s) > 40:
                    continue
                k = s.lower()
                if k in seen:
                    continue
                seen.add(k)
                cleaned.append(s)
                if len(cleaned) >= 20:
                    break
            return cleaned
        except Exception:
            return []

    def auto_tag(
        self,
        *,
        nodes: List[Node],
        allow_network: bool,
        proxy_info: Optional[dict] = None,
    ) -> AutoTagResult:
        processed = 0
        tagged = 0
        scraped = 0
        missing_id = 0
        save_failed = 0
        for node in nodes or []:
            if not node or getattr(node, "type", "") != "bookmark":
                continue
            url = getattr(node, "url", "") or ""
            bid = getattr(node, "bookmark_id", "") or ""
            if not url or not bid:
                if url and not bid:
                    missing_id += 1
                processed += 1
                continue

            tags = self._tier1_tags(url)
            if allow_network:
                extra = self._tier2_scrape_tags(url, proxy_info=proxy_info)
                if extra:
                    scraped += 1
                tags.extend(extra)

            # de-dup preserving order
            out: List[str] = []
            seen: Set[str] = set()
            for t in tags:
                k = (t or "").strip()
                if not k:
                    continue
                key = k.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(k)

            if out:
                try:
                    self.dbm.save_tags_for_url(bookmark_id=bid, tags=out, source="rule")
                    tagged += 1
                except Exception as e:
                    # Must: ignore errors and continue
                    logger.warning(f"[AutoTag] save failed (skip): {e}")
                    save_failed += 1

            processed += 1

        return AutoTagResult(
            processed=processed,
            tagged=tagged,
            allow_network=bool(allow_network),
            scraped=scraped,
            missing_id=missing_id,
            save_failed=save_failed,
        )

