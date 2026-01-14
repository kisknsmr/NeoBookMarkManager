"""
画像処理ユーティリティモジュール（I/O パフォーマンス最適化）。

機能:
  - bytes から ImageTk.PhotoImage への変換
  - LRU キャッシュによる画像メモリ最適化
  - GC 対策（App または Component が参照を保持必須）
"""

import io
import logging
from functools import lru_cache
from typing import Optional
from PIL import Image

try:
    from PIL import ImageTk
except ImportError:
    ImageTk = None

from .logger import logger


# ==================== 画像キャッシュとリサイズ ====================

@lru_cache(maxsize=512)
def bytes_to_resized_image(img_bytes: bytes, max_width: int = 256, max_height: int = 256) -> Optional[Image.Image]:
    """
    bytes を PIL Image に変換し、指定サイズ以下にリサイズする（LRU キャッシュ）。
    
    Note: 
      - キャッシュキーは bytes オブジェクトそのもの（ハッシュ可能）
      - 同じ画像バイトなら複数回の読み込みを避ける
      - PIL Image は再度 PhotoImage に変換される
    
    Args:
        img_bytes: 画像の bytes
        max_width: 最大幅（ピクセル）
        max_height: 最大高さ（ピクセル）
        
    Returns:
        リサイズされた PIL.Image.Image、またはエラー時 None
    """
    try:
        img = Image.open(io.BytesIO(img_bytes))
        
        # RGBA へ変換（透明度対応）
        if img.mode not in ('RGBA', 'RGB'):
            img = img.convert('RGB')
        
        # リサイズ（アスペクト比保持）
        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        
        logger.debug(f"Resized image to {img.size}")
        return img
    except Exception as e:
        logger.error(f"Error converting bytes to image: {e}")
        return None


def bytes_to_tkphoto(img_bytes: bytes, max_width: int = 256, max_height: int = 256) -> Optional['ImageTk.PhotoImage']:
    """
    bytes から ImageTk.PhotoImage を生成する（縮小・キャッシュ）。
    
    Important:
      生成された PhotoImage は GC から保護される必要があります。
      App または Component が参照を保持してください。
      例: app._image_refs[node_id] = photo_image
    
    Args:
        img_bytes: 画像の bytes
        max_width: 最大幅（ピクセル）
        max_height: 最大高さ（ピクセル）
        
    Returns:
        ImageTk.PhotoImage、またはエラー時 None
    """
    if not ImageTk:
        logger.warning("PIL.ImageTk not available; cannot create PhotoImage")
        return None
    
    try:
        pil_img = bytes_to_resized_image(img_bytes, max_width, max_height)
        if pil_img is None:
            return None
        
        photo = ImageTk.PhotoImage(pil_img)
        logger.debug(f"Created PhotoImage: {photo.width()}x{photo.height()}")
        return photo
    except Exception as e:
        logger.error(f"Error creating PhotoImage: {e}")
        return None


class ImageCache:
    """
    画像キャッシュマネージャー（スレッドセーフではない、GUIスレッド専用）。
    
    用途:
      - ノード ID ごとに PhotoImage を保存
      - LRU ルール（最大容量超過時に古いものを削除）
    
    Note:
      - TK は UI スレッドでのみ実行を想定
      - thread-safe にする必要がある場合は locks を追加
    """
    
    def __init__(self, max_size: int = 256):
        """
        初期化。
        
        Args:
            max_size: キャッシュの最大ノード数
        """
        self.max_size = max_size
        self._cache = {}  # node_id -> PhotoImage
        self._access_order = []  # LRU 順序
    
    def get(self, node_id: str) -> Optional['ImageTk.PhotoImage']:
        """
        キャッシュから PhotoImage を取得。
        
        Args:
            node_id: ノード ID
            
        Returns:
            PhotoImage または None
        """
        if node_id in self._cache:
            # LRU 更新：アクセス順序の更新
            self._access_order.remove(node_id)
            self._access_order.append(node_id)
            return self._cache[node_id]
        return None
    
    def put(self, node_id: str, photo: 'ImageTk.PhotoImage') -> None:
        """
        PhotoImage をキャッシュに保存。
        
        Args:
            node_id: ノード ID
            photo: ImageTk.PhotoImage オブジェクト
        """
        if node_id in self._cache:
            # 既存の場合は削除（新しくする）
            self._access_order.remove(node_id)
        
        # 容量チェック
        if len(self._cache) >= self.max_size and node_id not in self._cache:
            # 最も古いアイテムを削除（LRU）
            oldest_id = self._access_order.pop(0)
            del self._cache[oldest_id]
            logger.debug(f"Evicted image cache for node {oldest_id}")
        
        self._cache[node_id] = photo
        self._access_order.append(node_id)
        logger.debug(f"Cached image for node {node_id}")
    
    def clear(self) -> None:
        """
        キャッシュをすべてクリア。
        """
        self._cache.clear()
        self._access_order.clear()
        logger.info("Image cache cleared")
    
    def remove(self, node_id: str) -> None:
        """
        特定のノード ID のキャッシュを削除。
        
        Args:
            node_id: ノード ID
        """
        if node_id in self._cache:
            del self._cache[node_id]
            if node_id in self._access_order:
                self._access_order.remove(node_id)
            logger.debug(f"Removed image cache for node {node_id}")
