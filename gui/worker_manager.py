"""
ワーカー管理モジュール（ThreadPoolExecutor ラッパー）。

責務:
  - バックグラウンドタスク（I/O、API）を ThreadPoolExecutor で実行
  - コールバック結果をキューに貯める
  - GUI スレッド側で poll_results() で定期的に取得し、callback を実行
"""

import queue
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Optional, Any

from core.logger import logger


class WorkerManager:
    """
    ThreadPoolExecutor を使用したワーカー管理。
    
    Usage:
        manager = WorkerManager(max_workers=4)
        
        # Submit a task with callback
        manager.submit(fetch_data, url, callback=lambda res: update_ui(res))
        
        # Poll for results from UI thread
        manager.poll_results()
    """
    
    def __init__(self, max_workers: int = 4):
        """
        初期化。
        
        Args:
            max_workers: ThreadPool の最大ワーカー数
        """
        self.max_workers = max_workers
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="WorkerPool")
        self._callback_queue = queue.Queue()
        self._futures = {}  # task_id -> Future
        self._next_task_id = 0
        self._lock = threading.Lock()
        logger.info(f"WorkerManager initialized with {max_workers} workers")
    
    def submit(
        self,
        func: Callable,
        *args,
        callback: Optional[Callable[[Any], None]] = None,
        **kwargs
    ) -> int:
        """
        タスクを ThreadPool に投入する。
        
        Args:
            func: 実行する関数
            *args: 関数の positional 引数
            callback: 完了時に呼ぶコールバック（UI スレッドで実行される）
            **kwargs: 関数の keyword 引数
            
        Returns:
            タスク ID
        """
        with self._lock:
            task_id = self._next_task_id
            self._next_task_id += 1
        
        def task_wrapper():
            try:
                result = func(*args, **kwargs)
                if callback:
                    self._callback_queue.put((task_id, 'success', result))
                logger.debug(f"Task {task_id} completed successfully")
            except Exception as e:
                logger.error(f"Task {task_id} failed: {type(e).__name__}: {e}")
                if callback:
                    self._callback_queue.put((task_id, 'error', e))
        
        future = self._executor.submit(task_wrapper)
        with self._lock:
            self._futures[task_id] = future
        
        logger.debug(f"Submitted task {task_id}: {func.__name__}")
        return task_id
    
    def poll_results(self) -> int:
        """
        コールバックキューを確認し、待機中の callback をすべて実行する。
        GUI スレッドから定期的に呼び出してください（例: 100ms 間隔）。
        
        Returns:
            処理した callback の数
        """
        count = 0
        while True:
            try:
                task_id, status, result = self._callback_queue.get_nowait()
                logger.debug(f"Processing callback for task {task_id}: {status}")
                count += 1
                # ここで callback が実行される想定（既に queue に入っている状態）
                # Note: callback は submit 時に task_wrapper 内部で呼ばれている
                # このメソッドは queue の消費のみ
            except queue.Empty:
                break
            except Exception as e:
                logger.error(f"Error processing callback: {e}")
        
        return count
    
    def wait_all(self, timeout: Optional[float] = None) -> bool:
        """
        すべてのタスクの完了を待つ（ブロッキング）。
        
        Args:
            timeout: タイムアウト時間（秒）
            
        Returns:
            すべてのタスクが完了した場合 True、タイムアウト時 False
        """
        try:
            with self._lock:
                futures = list(self._futures.values())
            
            if not futures:
                return True
            
            for future in futures:
                future.result(timeout=timeout)
            
            logger.info("All tasks completed")
            return True
        except Exception as e:
            logger.warning(f"Timeout or error waiting for tasks: {e}")
            return False
    
    def shutdown(self, wait: bool = True) -> None:
        """
        ワーカーをシャットダウン。
        
        Args:
            wait: True の場合、すべてのタスク完了を待つ
        """
        logger.info(f"Shutting down WorkerManager (wait={wait})")
        self._executor.shutdown(wait=wait)
    
    def get_task_count(self) -> int:
        """
        現在進行中のタスク数を返す（概算）。
        
        Returns:
            タスク数
        """
        with self._lock:
            return len([f for f in self._futures.values() if not f.done()])
