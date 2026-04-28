"""
ServiceAiClassifier (Safety-first)

AI機能実装計画.md Phase 2: AI Core with Safety
- チャンク処理（30〜50件）
- 進捗報告（callback / generator-ready）
- リトライ（JSON不正は1回だけ再試行、429/5xxは指数バックオフで最大3回）
- コスト試算と承認ゲート（単価未設定なら安全側で実行を止める）
- Pydantic によるレスポンス検証（厳格）
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse, urlsplit, urlunsplit

import google.generativeai as genai
from pydantic import BaseModel, Field, ValidationError

from core.ServiceStorage import ConfigManager
from core.util_core import logger

# Local defaults replacing missing AppConstants (safety-first)
AI_REQUEST_TIMEOUT = 30
DEFAULT_MAX_SMART_ITEMS = 200
MAX_RETRIES = 3
RETRY_DELAY_BASE = 1.5


@dataclass(frozen=True)
class BookmarkNode:
    """AI分類用の軽量データ（Nodeとは別物・副作用なし）"""
    title: str = ""
    url: str = ""


@dataclass(frozen=True)
class AICostEstimate:
    model: str
    items: int
    chunks: int
    input_tokens_est: int
    output_tokens_est_range: Tuple[int, int]
    input_cost_usd_est: float
    output_cost_usd_est_range: Tuple[float, float]


@dataclass
class AIClassificationResult:
    plan: Dict[str, List[BookmarkNode]]  # folder -> items
    decisions: List[Tuple[BookmarkNode, str, float, str]]  # (item, folder, confidence, reason)
    traffic_stats: Dict[str, int]        # sent/received bytes
    processing_time: float
    skipped_chunks: int = 0
    cancelled: bool = False


class _Move(BaseModel):
    index: int = Field(ge=0)
    folder: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)


class _MovesResponse(BaseModel):
    moves: List[_Move] = Field(default_factory=list)


def _pydantic_validate(model_cls, data):
    """
    pydantic v1/v2 compatibility.
    - v2: model_validate
    - v1: parse_obj
    """
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(data)  # type: ignore[attr-defined]
    return model_cls.parse_obj(data)  # type: ignore[attr-defined]


class AIBookmarkClassifier:
    """
    安全仕様準拠のAI分類器。
    UIは Phase 3 でレビュー画面を追加する想定だが、現時点でも:
    - コスト承認
    - 構造化出力検証
    - 失敗時のスキップ/中断
    を提供する。
    """

    def __init__(self, config_path: str = "config.ini") -> None:
        self.config_manager = ConfigManager(config_path)
        self.traffic_sent = 0
        self.traffic_received = 0
        self.is_cancelled = False
        self.progress_callback: Optional[Callable[[int, int, int, int], None]] = None

    def set_progress_callback(self, callback: Callable[[int, int, int, int], None]) -> None:
        self.progress_callback = callback

    def cancel(self) -> None:
        self.is_cancelled = True
        logger.info("[AI_ENGINE] Classification cancelled by user.")

    def _read_api_key(self) -> Optional[str]:
        return self.config_manager.get_api_key()

    def _get_domain(self, url: str) -> str:
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return ""

    def _sanitize_url_for_ai(self, url: str) -> str:
        """Privacy (default ON): drop query params before sending to AI."""
        try:
            parts = urlsplit(url)
            return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
        except Exception:
            return url

    def _load_external_prompt(self) -> str:
        # legacy仕様維持（Prompt.prompt_file → config/prompt.txt → prompt.txt）
        prompt_path = self.config_manager.get("Prompt", "prompt_file", fallback=None)
        if not prompt_path or not str(prompt_path):
            prompt_path = "config/prompt.txt"
        if not prompt_path:
            raise FileNotFoundError("prompt file path is empty")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            raise FileNotFoundError(f"Prompt file not found/readable: {prompt_path} ({e})") from e

    def _create_payload(self, priority_terms: List[str], additional_prompt: Optional[str]) -> str:
        base_prompt = self._load_external_prompt()
        priority_terms_str = ", ".join([f'"{term}"' for term in (priority_terms or [])])
        final_prompt = base_prompt.replace("{priority_terms_placeholder}", priority_terms_str)

        # Safety override: enforce output schema with confidence/reason per item
        schema_override = """

CRITICAL OUTPUT RULES (SAFETY OVERRIDE):
- Output VALID JSON ONLY. No code fences, no extra text.
- Return this schema (ignore any previous schema description):
{
  "moves": [
    {"index": 0, "folder": "FolderName", "confidence": 0.92, "reason": "short reason"}
  ]
}
- confidence must be 0.0 to 1.0
- reason must be short and specific
- Only include moves you are confident about; if none, return {"moves": []}.
"""
        final_prompt = final_prompt + schema_override

        if additional_prompt:
            final_prompt = f"USER OVERRIDE INSTRUCTIONS:\n{additional_prompt}\n\n" + final_prompt

        return final_prompt

    def _chunk(self, items: List[BookmarkNode], chunk_size: int) -> Iterable[List[BookmarkNode]]:
        for i in range(0, len(items), chunk_size):
            yield items[i : i + chunk_size]

    def estimate_cost(
        self,
        bookmarks: List[BookmarkNode],
        *,
        priority_terms: Optional[List[str]] = None,
        additional_prompt: Optional[str] = None,
        chunk_size: int = 40,
        model_name: str = "gemini-1.5-flash",
        sanitize_urls: bool = True,
    ) -> AICostEstimate:
        prompt = self._create_payload(priority_terms or [], additional_prompt)
        # approximate tokens: 1 token ≈ 4 chars (rough)
        def tok(s: str) -> int:
            return max(1, int(len((s or "")) / 4))

        sent_tokens = tok(prompt)
        chunks = list(self._chunk(bookmarks, max(1, chunk_size)))
        for batch in chunks:
            items = [
                {
                    "index": i,
                    "title": (b.title or "")[:150],
                    "domain": self._get_domain(b.url or ""),
                    "url": self._sanitize_url_for_ai(b.url or "") if sanitize_urls else (b.url or ""),
                }
                for i, b in enumerate(batch)
            ]
            data_json = json.dumps({"bookmarks": items}, ensure_ascii=False)
            sent_tokens += tok(data_json)

        # output estimate: ~40-120 tokens per moved item (range)
        out_low = 40 * len(bookmarks)
        out_high = 120 * len(bookmarks)

        in_price = self.config_manager.get("AI", "input_cost_per_1m_tokens", fallback=None)
        out_price = self.config_manager.get("AI", "output_cost_per_1m_tokens", fallback=None)
        try:
            in_price_f = float(in_price)
            out_price_f = float(out_price)
        except Exception:
            in_price_f = -1.0
            out_price_f = -1.0

        if in_price_f <= 0 or out_price_f <= 0:
            # 安全側：単価未設定なら実行ゲートで止めるため、ここでも -1 を返す
            in_cost = -1.0
            out_cost_low = -1.0
            out_cost_high = -1.0
        else:
            in_cost = sent_tokens / 1_000_000 * in_price_f
            out_cost_low = out_low / 1_000_000 * out_price_f
            out_cost_high = out_high / 1_000_000 * out_price_f

        return AICostEstimate(
            model=model_name,
            items=len(bookmarks),
            chunks=len(chunks),
            input_tokens_est=sent_tokens,
            output_tokens_est_range=(out_low, out_high),
            input_cost_usd_est=in_cost,
            output_cost_usd_est_range=(out_cost_low, out_cost_high),
        )

    def _is_retryable_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if code in (429, 500, 502, 503, 504):
            return True
        if "429" in msg or "too many requests" in msg:
            return True
        if "500" in msg or "502" in msg or "503" in msg or "504" in msg:
            return True
        if "deadline" in msg or "timeout" in msg:
            return True
        return False

    def _extract_json(self, text: str) -> Optional[str]:
        t = (text or "").strip()
        if not t:
            return None
        # naive extraction: find first '{' and last '}'
        start = t.find("{")
        end = t.rfind("}")
        if start >= 0 and end > start:
            return t[start : end + 1]
        return None

    def _process_batch(
        self,
        model,
        final_prompt: str,
        batch: List[BookmarkNode],
        *,
        sanitize_urls: bool,
    ) -> List[_Move]:
        items = [
            {
                "index": i,
                "title": (b.title or "")[:150],
                "domain": self._get_domain(b.url or ""),
                "url": self._sanitize_url_for_ai(b.url or "") if sanitize_urls else (b.url or ""),
            }
            for i, b in enumerate(batch)
        ]
        data_json = json.dumps({"bookmarks": items}, ensure_ascii=False)

        self.traffic_sent += len(final_prompt.encode("utf-8")) + len(data_json.encode("utf-8"))

        last_text = ""
        for json_retry in range(2):  # 0: normal, 1: JSON re-ask once
            prompt2 = final_prompt
            if json_retry == 1:
                prompt2 = (
                    final_prompt
                    + "\n\nThe previous output was not valid JSON or did not match the required schema. "
                    + "Output correct JSON strictly matching the schema now."
                )
            resp = model.generate_content(
                [prompt2, data_json],
                request_options={"timeout": AI_REQUEST_TIMEOUT},
                generation_config={"response_mime_type": "application/json"},
            )
            text = (getattr(resp, "text", "") or "").strip()
            last_text = text
            self.traffic_received += len(text.encode("utf-8"))

            raw = self._extract_json(text) or text
            try:
                data = json.loads(raw)
                parsed = _pydantic_validate(_MovesResponse, data)
                return parsed.moves
            except (json.JSONDecodeError, ValidationError) as e:
                logger.warning(f"[AI_ENGINE] Response validation failed (attempt={json_retry+1}): {e}")
                continue

        # give up for this batch
        logger.error(f"[AI_ENGINE] Failed to parse/validate AI response. Text preview: {last_text[:200]}")
        return []

    def classify_bookmarks(
        self,
        bookmarks: List[BookmarkNode],
        *,
        priority_terms: Optional[List[str]] = None,
        max_items: int = DEFAULT_MAX_SMART_ITEMS,
        additional_prompt: Optional[str] = None,
        chunk_size: int = 40,
        model_name: str = "gemini-1.5-flash",
        sanitize_urls: bool = True,
        cancel_checker: Optional[Callable[[], bool]] = None,
    ) -> AIClassificationResult:
        start_time = time.time()
        self.traffic_sent = 0
        self.traffic_received = 0
        self.is_cancelled = False

        api_key = self._read_api_key()
        if not api_key:
            raise ValueError("API key not found (set GENAI_API_KEY/GOOGLE_API_KEY or config.ini [API].api_key)")

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)

        limited = (bookmarks or [])[: int(max_items)]
        final_prompt = self._create_payload(priority_terms or [], additional_prompt)

        total = len(limited)
        processed = 0
        skipped_chunks = 0
        decisions: List[Tuple[BookmarkNode, str, float, str]] = []

        for batch in self._chunk(limited, max(1, int(chunk_size))):
            if self.is_cancelled or (cancel_checker and cancel_checker()):
                self.is_cancelled = True
                break

            # Retry for 429/5xx with exponential backoff
            moves: List[_Move] = []
            for attempt in range(MAX_RETRIES):
                try:
                    moves = self._process_batch(model, final_prompt, batch, sanitize_urls=sanitize_urls)
                    break
                except Exception as exc:
                    if self._is_retryable_error(exc) and attempt < AppConstants.MAX_RETRIES - 1:
                        delay = RETRY_DELAY_BASE * (2**attempt)
                        logger.warning(f"[AI_ENGINE] Retryable error, retrying in {delay}s: {exc}")
                        time.sleep(delay)
                        continue
                    raise

            if not moves and batch:
                skipped_chunks += 1

            # apply moves (indices are relative to batch)
            for mv in moves:
                if 0 <= mv.index < len(batch):
                    folder = (mv.folder or "Unsorted").strip().replace("/", "_")
                    decisions.append((batch[mv.index], folder, float(mv.confidence), str(mv.reason)))

            processed += len(batch)
            if self.progress_callback:
                self.progress_callback(processed, total, self.traffic_sent, self.traffic_received)

        # minimum group size rule (>=2) enforced like legacy (adjust decisions)
        if not self.is_cancelled:
            # count per folder
            folder_counts: Dict[str, int] = {}
            for _it, folder, _c, _r in decisions:
                folder_counts[folder] = folder_counts.get(folder, 0) + 1

            large_folders = {f for f, c in folder_counts.items() if c >= 2}
            small_folders = {f for f, c in folder_counts.items() if c < 2}

            if large_folders and small_folders:
                # move all small-folder items into the largest folder (legacy behavior)
                largest = max(large_folders, key=lambda f: folder_counts.get(f, 0))
                decisions = [
                    (it, (largest if folder in small_folders else folder), conf, reason)
                    for (it, folder, conf, reason) in decisions
                ]
            elif not large_folders and decisions:
                decisions = [(it, "Unsorted", conf, reason) for (it, _folder, conf, reason) in decisions]

        # build plan from decisions
        plan: Dict[str, List[BookmarkNode]] = {}
        for it, folder, _conf, _reason in decisions:
            plan.setdefault(folder, []).append(it)

        elapsed = time.time() - start_time
        return AIClassificationResult(
            plan=plan,
            decisions=decisions,
            traffic_stats={"sent": self.traffic_sent, "received": self.traffic_received},
            processing_time=elapsed,
            skipped_chunks=skipped_chunks,
            cancelled=self.is_cancelled,
        )

