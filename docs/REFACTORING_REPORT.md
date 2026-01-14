"""
実装完了レポート：NeoBookMarkManager v2.0 リファクタリング
================================================================

日時: 2026-01-13
ブランチ: feature/refactor-main-window

【概要】
UI スレッドのブロック除去、画像キャッシュ・メモリ最適化、
仮想化リスト導入、main_window.py の分割による保守性向上を実装。

【実装ファイル一覧】

1. 既存ファイル修正
────────────────────────────────────────────────────────────

✓ core/storage.py
  - ConfigManager に get(section, option, fallback=None) を追加
  - ConfigManager に set(section, option, value) を追加
  → 汎用的な設定値取得・設定が可能に
  → prompt_file の場所を config.ini 経由で管理可能

✓ services/workers.py
  - fetch_preview() に timeout パラメータを追加（明示的設定）
  - timeout=None 時は AppConstants から取得
  - 例外を細分化（Timeout, ConnectionError, HTTPError 等）
  - 404 時はリトライしない
  - _extract_title_and_description() を LRU キャッシュ対応
  - _cached_extract_title_and_description() を新規追加
  - fix_titles() に timeout パラメータを追加
  - fetch_favicon() に timeout パラメータを追加
  - すべて例外に堅牢化（try-except で細分化）

✓ services/ai_classifier.py
  - _load_external_prompt() を修正
  - ConfigManager の [Prompt] セクションから prompt_file を取得
  - フォールバック: prompt.txt（ルートディレクトリ）

✓ gui/main_window.py
  - App クラスに互換性シムレイヤーを追加
  - __init__ 内で新規アーキテクチャ（worker, state）を初期化
  - _poll_worker_results() メソッドを追加（100ms 間隔でポーリング）
  - _new_app_available フラグで新規機能の有無を判定

✓ config.ini
  - [Prompt] セクションを追加
  - prompt_file = prompt.txt を設定


2. 新規ファイル作成
────────────────────────────────────────────────────────────

✓ core/image_utils.py
  新規ファイル（209 行）
  
  クラス・関数:
    - @lru_cache bytes_to_resized_image(): bytes → PIL Image（LRU キャッシュ）
    - bytes_to_tkphoto(): bytes → ImageTk.PhotoImage（縮小・キャッシュ）
    - class ImageCache: LRU ベースのフォト管理
  
  特徴:
    - 画像を指定サイズ以下にリサイズ（デフォルト 256x256）
    - LRU キャッシュで重複処理を削減
    - PhotoImage GC 対策（参照保持の重要性をドキュメント化）

✓ gui/worker_manager.py
  新規ファイル（116 行）
  
  クラス:
    - class WorkerManager: ThreadPoolExecutor ラッパー
  
  メソッド:
    - submit(func, *args, callback=None, **kwargs): タスク投入
    - poll_results(): キューから結果を消費（UI スレッド用）
    - wait_all(timeout=None): 全タスク完了を待つ
    - shutdown(wait=True): ワーカーシャットダウン
    - get_task_count(): 進行中のタスク数取得
  
  特徴:
    - ThreadPoolExecutor による非同期実行
    - コールバック型インターフェース
    - UI スレッドブロック防止

✓ gui/ui_state.py
  新規ファイル（184 行）
  
  クラス:
    - class UIState: GUI 状態管理の軽量ストア
  
  機能:
    - 選択状態管理（select_node, deselect_node等）
    - フォルダ展開状態管理（expand_folder, toggle_folder等）
    - ソート・フィルター設定
    - Observer パターン実装（subscribe/unsubscribe）
  
  イベント:
    - 'selection': ノード選択変更時
    - 'expansion': フォルダ展開状態変更時
    - 'sort': ソート順序変更時
    - 'filter': フィルター変更時
    - 'view_mode': ビューモード変更時

✓ gui/app.py
  新規ファイル（125 行）
  
  クラス:
    - class App(ctk.CTk): メインアプリケーション（新規アーキテクチャ）
  
  属性:
    - self.worker: WorkerManager インスタンス
    - self.state: UIState インスタンス
    - self._image_cache: ImageCache インスタンス
    - self._image_refs: Dict（PhotoImage 参照保持）
    - self.root_node: ブックマークツリー
    - self.rules: 分類ルール
  
  メソッド:
    - load_bookmarks(filepath): ブックマークを読み込み
    - start_poller(interval_ms=100): ワーカーポーラー開始
    - apply_preview_to_node(node_id, result): プレビュー反映
    - cache_image(node_id, photo): 画像参照保持
    - get_cached_image(node_id): キャッシュから取得
    - clear_image_cache(): キャッシュクリア
    - run(): アプリケーション起動
  
  ファクトリー:
    - create_app(config_path): App インスタンス生成

✓ gui/command_handlers.py
  新規ファイル（223 行）
  
  クラス:
    - class CommandHandlers: メニューコマンドハンドラー
  
  ファイル操作:
    - cmd_open_bookmarks(): ファイルを開く
    - cmd_save_bookmarks(): ファイルを保存
  
  表示・編集:
    - cmd_check_all_previews(): プレビュー確認（非同期）
    - cmd_fix_titles(): タイトル修正（非同期）
    - cmd_sort_by_name(): 名前順ソート
    - cmd_sort_by_date(): 日付順ソート
    - cmd_dedupe(): 重複削除
    - cmd_merge_folders(): フォルダマージ
    - cmd_check_dead_links(): リンク確認（非同期）
  
  特徴:
    - App インスタンスを受け取り worker・state を操作
    - 非同期処理は worker.submit() で実行

✓ gui/menu_bar.py
  新規ファイル（67 行）
  
  関数:
    - build_menu_bar(root, app): メニューバー構築
  
  メニュー:
    - File: Open, Save, Exit
    - Edit: Fix Titles, Check Previews, Dedupe, Merge
    - Tools: Check Dead Links, AI Classify
    - View: Sort by Name, Sort by Date
    - Help: About
  
  特徴:
    - CommandHandlers を経由してコマンド実行
    - UI スレッドセーフな設計

✓ gui/virtual_list.py
  新規ファイル（177 行）
  
  クラス:
    - @dataclass ListItem: リストアイテムの基本構造
    - class VirtualList: Canvas ベースの仮想化リスト
  
  メソッド:
    - set_items(items): アイテムセット
    - add_item(item): アイテム追加
    - remove_item(item_id): アイテム削除
    - clear(): すべてクリア
    - get_selected_item_id(): 選択アイテム ID 取得
  
  特徴:
    - プロトタイプ段階（将来の本番化想定）
    - Canvas レンダリング（遅延表示対応可能）
    - スクロール・マウスホイール対応


【主要な技術的ポイント】

1. UI スレッドのブロック除去
   ✓ WorkerManager で I/O を ThreadPoolExecutor で実行
   ✓ UI スレッド側で app.after(100, poll_results) でポーリング
   ✓ ネットワーク待機時に UI が応答不能にならない

2. 画像メモリ最適化
   ✓ bytes → PIL Image を LRU キャッシュ
   ✓ 自動リサイズで メモリ削減
   ✓ PhotoImage 参照を App._image_refs で保持（GC 対策）

3. I/O 堅牢化
   ✓ timeout を明示的に設定（デフォルト値取得）
   ✓ 例外を細分化（Timeout/ConnectionError/HTTPError）
   ✓ 404 時はリトライしない
   ✓ すべての外部ライブラリ呼び出しをエラーハンドル

4. 設定管理の統一
   ✓ ConfigManager に汎用 get/set メソッド
   ✓ prompt_file を config.ini 経由で管理
   ✓ fallback サポート

5. 段階的移行
   ✓ gui/main_window.py を shim 化
   ✓ 既存コードとの互換性を保持
   ✓ 新しいコンポーネントから新 API を使用可能


【推奨コミット順序】

1. core/storage.py: ConfigManager 拡張
   "Add get/set methods to ConfigManager for unified config access"

2. services/workers.py: I/O 堅牢化
   "Add timeout, exception handling, HTML caching to workers"

3. core/image_utils.py: 画像最適化
   "Add image resize and PhotoImage LRU cache utility"

4. gui/worker_manager.py: ワーカー管理
   "Add WorkerManager (ThreadPoolExecutor wrapper) for async I/O"

5. gui/ui_state.py: 状態管理
   "Add UIState for centralized UI state management"

6. gui/virtual_list.py: 仮想リスト
   "Add VirtualList (Canvas-based) as prototype for large lists"

7. gui/app.py: App コア
   "Add App core with worker, state, image refs"

8. gui/command_handlers.py: コマンドハンドラー
   "Add command handlers for menu actions"

9. gui/menu_bar.py: メニュー
   "Add menu bar builder with new architecture"

10. services/ai_classifier.py: プロンプト変更
    "Update ai_classifier to load prompt from ConfigManager"

11. gui/main_window.py: shim 化
    "Make App a compatibility shim for new architecture"

12. config.ini: 設定追加
    "Add [Prompt] section to config.ini"

13. README.md: ドキュメント更新
    "Document v2.0 architecture, performance optimizations, async design"


【動作確認チェックリスト】

□ python -m pytest tests/test_core.py （既存テスト確認）
□ python main.py （アプリ起動確認）
□ File > Open Bookmarks で正常に読み込める
□ Edit > Fix Titles で非同期実行される（UI がブロックしない）
□ ワーカーのタスク数が表示される
□ 画像キャッシュが機能している（重複ダウンロードがない）
□ プレビュー取得が timeout で失敗しない
□ リトライロジックが動作している
□ メニューコマンドが正常に実行される


【今後の推奨タスク】

1. 仮想化リスト（gui/virtual_list.py）の本格実装
   - スクロール時の見える範囲のみレンダリング
   - 数万件のブックマーク表示に対応

2. 他のコンポーネント（gui/components.py 等）の段階的移行
   - 新規 App API（app.worker / app.state）を使用するように修正
   - 互換性 shim を段階的に削減

3. テストカバレッジ向上
   - gui/worker_manager.py のユニットテスト
   - gui/command_handlers.py の統合テスト

4. プロキシ周りのテスト強化
   - proxy_info の None チェック（AppConstants 参照時）

5. エラーハンドリングの UX 改善
   - タイムアウトエラーをユーザー向けメッセージに翻訳
   - プログレスダイアログの表示

---
実装完了日: 2026-01-13
"""
