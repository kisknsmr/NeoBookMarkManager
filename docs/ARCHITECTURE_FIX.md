# アーキテクチャ修正プラン

## 現在の問題

### 1. レンダリングパフォーマンス
- **問題**: 全ブックマーク（数千件）を同期的に描画
- **影響**: UIスレッドが数秒〜数十秒ブロック
- **原因**: `_render_cards()`が全要素を`BookmarkCard`として生成

### 2. メモリ使用量
- **問題**: 全カードをメモリに保持
- **影響**: 大量のTkinterウィジェット（Card × 1000 = Label × 5000+）
- **原因**: 仮想化リストが未実装

### 3. デバッグ不可能
- **問題**: 全エラーを`pass`で無視
- **影響**: 問題発生時に原因特定不可
- **原因**: 過剰な最適化

## 修正方針

### Phase 1: 緊急対応（即時実装）

#### 1.1 ログシステムの復旧
```python
# ログレベルの適切な管理
logger.setLevel(logging.WARNING)  # 本番はWARNING以上
# DEBUG/INFOは開発時のみ

# クリティカルなエラーは必ず記録
try:
    ...
except Exception as e:
    logger.error(f"Critical error: {e}", exc_info=True)
    # ユーザーに通知
```

#### 1.2 レンダリングの段階的実装
```python
def _render_cards_incremental(self, batch_size=50):
    """段階的にカードを描画（UIをブロックしない）"""
    def render_batch(start_idx):
        end_idx = min(start_idx + batch_size, len(nodes))
        for i in range(start_idx, end_idx):
            # カード描画
            ...
        
        if end_idx < len(nodes):
            # 次のバッチを50ms後に実行
            self.after(50, lambda: render_batch(end_idx))
        else:
            # 完了後の処理
            self._restore_scroll_position()
    
    render_batch(0)
```

#### 1.3 表示件数制限（暫定対応）
```python
MAX_INITIAL_RENDER = 100  # 最初は100件まで
# 「もっと読み込む」ボタンで追加
```

### Phase 2: 根本的な解決（v2.1）

#### 2.1 仮想スクロール実装
```python
class VirtualizedCardList:
    """Canvas + ウィンドウベースの仮想化リスト"""
    
    def __init__(self, parent, items, render_item):
        self.canvas = ctk.CTkCanvas(parent)
        self.viewport_height = 0
        self.item_height = 120  # カードの高さ
        self.visible_items = {}  # 現在表示中のウィジェット
        
        self.canvas.bind("<Configure>", self._on_scroll)
    
    def _on_scroll(self, event):
        """スクロール時に表示範囲のアイテムのみ描画"""
        visible_start = self.canvas.yview()[0]
        visible_end = self.canvas.yview()[1]
        
        start_idx = int(visible_start * len(self.items))
        end_idx = int(visible_end * len(self.items)) + 1
        
        # 範囲外のウィジェットを破棄
        for idx in list(self.visible_items.keys()):
            if idx < start_idx or idx >= end_idx:
                self.visible_items[idx].destroy()
                del self.visible_items[idx]
        
        # 範囲内のウィジェットを生成
        for idx in range(start_idx, end_idx):
            if idx not in self.visible_items:
                item_widget = self.render_item(self.items[idx])
                self.canvas.create_window(...)
                self.visible_items[idx] = item_widget
```

#### 2.2 非同期プレビュー取得
```python
def _load_previews_async(self, nodes):
    """背景でプレビューを取得し、準備できたものから表示"""
    for node in nodes:
        if node.url:
            self.worker.submit(
                fetch_preview,
                args=(node.url,),
                callback=lambda result: self._update_card_preview(node, result)
            )
```

#### 2.3 軽量カードモード
```python
class LightweightBookmarkCard:
    """必要最小限のウィジェットのみ"""
    # ファビコン + タイトル + URL のみ
    # プレビュー画像は遅延ロード
```

### Phase 3: パフォーマンス計測（継続的改善）

#### 3.1 プロファイリング追加
```python
import cProfile
import pstats

def profile_render():
    profiler = cProfile.Profile()
    profiler.enable()
    
    self._render_cards()
    
    profiler.disable()
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumtime')
    stats.print_stats(20)  # Top 20遅い処理
```

#### 3.2 メトリクス収集
```python
class PerformanceMonitor:
    def measure_render_time(self):
        start = time.perf_counter()
        self._render_cards()
        elapsed = time.perf_counter() - start
        logger.info(f"Render time: {elapsed:.2f}s")
```

## 実装優先順位

1. **最優先** (今すぐ): ログ復旧、エラーハンドリング復旧
2. **高優先** (今日中): 段階的レンダリング、表示件数制限
3. **中優先** (今週中): 仮想スクロール実装
4. **低優先** (次バージョン): プロファイリング、メトリクス

## 成功基準

- [ ] 1000件のブックマーク表示が3秒以内
- [ ] スクロールが60fps
- [ ] メモリ使用量が500MB以下
- [ ] エラー発生時に原因が特定可能
- [ ] ログファイルサイズが10MB以下/日
