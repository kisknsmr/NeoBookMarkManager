# ai_classifier.py (外部プロンプト・ドメイン解析強化版)

import os
import json
import time
import logging
import datetime
from urllib.parse import urlparse
from typing import List, Dict, Optional, Callable
import google.generativeai as genai
from core.storage import ConfigManager


class BookmarkNode:
    """ブックマークノードの軽量版（AI分類用）"""

    def __init__(self, title: str = "", url: str = "", node_type: str = "bookmark"):
        self.title = title
        self.url = url
        self.type = node_type


class AIClassificationResult:
    """AI分類の結果を格納するクラス"""

    def __init__(self, plan: Dict[str, List], traffic_stats: Dict[str, int], processing_time: float):
        self.plan = plan
        self.traffic_stats = traffic_stats
        self.processing_time = processing_time


class AIBookmarkClassifier:
    """AIを使用したブックマーク分類器（外部プロンプトファイル参照型）"""

    def __init__(self, config_path: str = "config.ini", logger: Optional[logging.Logger] = None):
        self.config_manager = ConfigManager(config_path)
        self.logger = logger or logging.getLogger(__name__)
        self.traffic_sent = 0
        self.traffic_received = 0
        self.is_cancelled = False
        self.progress_callback: Optional[Callable] = None

    def _log_immediate(self, message: str):
        """ログ出力（正式版リリースまで）"""
        now = datetime.datetime.now().strftime("%H:%M:%S")
        if self.logger:
            self.logger.info(f"[{now}] [AI_ENGINE] {message}")
        else:
            print(f"[{now}] [AI_ENGINE] {message}")

    def set_progress_callback(self, callback: Callable[[int, int, int, int], None]):
        """進捗コールバックを設定する"""
        self.progress_callback = callback

    def cancel(self):
        """処理をキャンセルする"""
        self.is_cancelled = True

    def _read_api_key(self) -> Optional[str]:
        """APIキーを取得する（ConfigManager経由）"""
        return self.config_manager.get_api_key()

    def _get_domain(self, url: str) -> str:
        """AIが判断しやすいようにURLからドメインを抽出"""
        try:
            return urlparse(url).netloc.lower()
        except:
            return ""

    def _load_external_prompt(self) -> str:
        """外部の prompt.txt から指示文を読み込む（中身はコードに入れない）"""
        prompt_path = "prompt.txt"
        if not os.path.exists(prompt_path):
            self._log_immediate(f"CRITICAL: {prompt_path} が見つかりません。")
            raise FileNotFoundError(f"外部プロンプトファイル '{prompt_path}' が必要です。")

        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            self._log_immediate(f"Prompt loaded from {prompt_path} ({len(content)} chars).")
            return content

    def _create_payload(self, priority_terms: List[str], additional_prompt: Optional[str] = None) -> str:
        """外部プロンプトと追加指示、動的ルールを統合した最終指示文を作成"""
        base_prompt = self._load_external_prompt()

        # プレースホルダ置換（既存のprompt.txtの仕様を維持）
        priority_terms_str = ", ".join([f'"{term}"' for term in priority_terms])
        final_prompt = base_prompt.replace("{priority_terms_placeholder}", priority_terms_str)

        # ドメイン情報を活用させるための「動的な補足指示」のみ追加
        logic_booster = "\n\n**Data Analysis Tip:** Use the provided 'domain' field to understand the site's context when titles are vague."
        final_prompt += logic_booster

        if additional_prompt:
            self._log_immediate(f"User custom instructions added.")
            final_prompt = f"**USER OVERRIDE INSTRUCTIONS:**\n{additional_prompt}\n\n" + final_prompt

        return final_prompt

    def _process_batch(self, model, final_prompt: str, batch: List[BookmarkNode]) -> Dict[str, List[BookmarkNode]]:
        # AIに渡すデータをドメイン付きで構造化
        items = [
            {
                "index": i,
                "title": (b.title or "")[:150],
                "domain": self._get_domain(b.url or ""),
                "url": b.url or ""
            }
            for i, b in enumerate(batch)
        ]

        data_json = json.dumps({"bookmarks": items}, ensure_ascii=False)
        self._log_immediate(f"Processing batch of {len(batch)} items...")

        self.traffic_sent += len(final_prompt.encode('utf-8')) + len(data_json.encode('utf-8'))

        from core.utils import AppConstants
        
        resp = model.generate_content(
            [final_prompt, data_json],
            request_options={"timeout": AppConstants.AI_REQUEST_TIMEOUT},
            generation_config={"response_mime_type": "application/json"}
        )

        text = (getattr(resp, "text", "") or "").strip()
        self.traffic_received += len(text.encode('utf-8'))

        try:
            res_data = json.loads(text)
        except json.JSONDecodeError:
            self._log_immediate("AI response parse failed. Attempting rescue...")
            return {}

        batch_plan = {}
        groups = res_data.get("groups", [])
        for g in groups:
            folder = g.get("folder", "Unsorted").strip().replace('/', '_')
            indices = g.get("indices", [])
            for idx in indices:
                if 0 <= idx < len(batch):
                    batch_plan.setdefault(folder, []).append(batch[idx])

        return batch_plan

    def classify_bookmarks(self,
                           bookmarks: List[BookmarkNode],
                           priority_terms: List[str] = None,
                           max_items: int = 300,
                           additional_prompt: Optional[str] = None) -> AIClassificationResult:
        start_time = time.time()
        self.traffic_sent = 0
        self.traffic_received = 0
        self.is_cancelled = False

        self._log_immediate(f"Starting Smart Classify: {len(bookmarks)} items.")

        api_key = self._read_api_key()
        if not api_key: raise ValueError("API key not found")

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        limited_bookmarks = bookmarks[:max_items]

        # 外部プロンプトを読み込んで統合指示文を作成
        final_prompt = self._create_payload(priority_terms or [], additional_prompt)

        plan = {}
        if limited_bookmarks:
            plan = self._process_batch(model, final_prompt, limited_bookmarks)
            if self.progress_callback:
                self.progress_callback(len(limited_bookmarks), len(limited_bookmarks), self.traffic_sent,
                                       self.traffic_received)

        # 1件フォルダを「Unsorted」に寄せる既存のクリーンアップ
        if not self.is_cancelled:
            large_categories = {n: items for n, items in plan.items() if len(items) >= 2}
            small_items = [it for n, items in plan.items() if len(items) < 2 for it in items]
            if small_items and large_categories:
                largest = max(large_categories, key=lambda k: len(large_categories[k]))
                large_categories[largest].extend(small_items)
                plan = large_categories
            elif not large_categories and small_items:
                plan = {"Unsorted": small_items}
            else:
                plan = large_categories

        elapsed = time.time() - start_time
        self._log_immediate(
            f"Success. Time: {elapsed:.1f}s, Sent: {self.traffic_sent}b, Recv: {self.traffic_received}b")

        return AIClassificationResult(
            plan=plan,
            traffic_stats={'sent': self.traffic_sent, 'received': self.traffic_received},
            processing_time=elapsed
        )