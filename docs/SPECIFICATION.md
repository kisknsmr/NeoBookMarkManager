# 仕様書 - Bookmark Studio

## 1. アプリ概要
- **種別**: Desktopアプリケーション（Python + PySide6）
- **主な目的**: ブックマークHTMLファイルの読み込み、階層構造の編集、重複削除、AI分類、保存
- **想定ユーザー**: ブックマークを整理する個人ユーザー

## 2. 画面・UI構成

### 画面一覧
- **メインウィンドウ**: 1400x800ピクセル（最小サイズ: 1000x600）
  - フォルダツリー（上部）
  - ブックマーク表示エリア（下部）
  - 検索バー（ブックマーク表示エリア上部）
  - 詳細パネル（右側）
  - アクションボタン（右側パネル上部）

### 共通UI要素
- **メニューバー**: File（Open/Save/Save As/Exit）、Edit（New Folder/New Bookmark/Rename/Edit URL/Move/Delete）、Tools（各種ツール）
- **ボタン**: QPushButton（primary/secondary/dangerスタイル）
- **カード**: BookmarkCard（カードビュー用）
- **行**: BookmarkRow（リストビュー用）
- **ダイアログ**: 進捗表示、確認、エラー表示用

### 状態表示
- **ローディング**: AI分類・タイトル修正時に進捗ダイアログを表示
- **エラー**: `QMessageBox`でエラーメッセージを表示
- **空状態**: コード上で明示的な実装は未確認

## 3. 操作フロー

### 主要ユースケース
1. **ファイル読み込み**: File > Open HTML → HTMLファイル選択 → パース → ツリー/カード表示
2. **ブックマーク作成**: Edit > New Bookmark → タイトル/URL入力 → 現在フォルダに追加
3. **フォルダ作成**: Edit > New Folder → 名前入力 → 現在フォルダに追加
4. **編集**: アイテム選択 → Edit > Rename/Edit URL → 入力 → 更新
5. **削除**: アイテム選択 → Delete → 確認ダイアログ → 削除
6. **ドラッグ&ドロップ**: ツリービュー上でブックマーク/フォルダを移動・並び替え
7. **2画面モード**: ツリービューを左右に並べて整理
8. **検索**: 検索バーに入力 → インデックス検索 → マッチするノードを表示
9. **スマート分類（ドメインベース）**: Tools > Rule-based Classification → プレビュー表示 → 分類実行
10. **タイトル修正**: アイテム選択 → Tools > Fix Titles from URL → 進捗表示 → タイトル更新
11. **保存**: File > Save/Save As → HTML出力 → ルールファイル（.bookmark_rules.json）も保存

## 4. UI実装構造

### UIコンポーネントの構成方針
- **フレームワーク**: PySide6（Qt6ベース）
- **コンポーネント化**: `gui/components.py`に定義
  - `BookmarkCard`: カード表示用コンポーネント
  - `BookmarkRow`: リスト表示用コンポーネント
  - `FolderTree`: フォルダツリーコンポーネント
  - `SearchBar`: 検索バーコンポーネント
  - `DetailPanel`: 詳細パネルコンポーネント

### スタイル定義の場所
- **テーマシステム**: `gui/style.qss` と `gui/resources.py` に定義

## 5. エラーハンドリング

### ユーザー向けエラー表示の方法
- **メッセージボックス**: `QMessageBox`を使用
  - `information`: 情報表示
  - `warning`: 警告表示
  - `critical`: エラー表示
  - `question`: 確認ダイアログ

### 例外処理の実装有無
- **実装あり**: try-exceptで例外を捕捉し、ログ出力後に`messagebox`でユーザーに通知

### ログ出力仕様
- **形式**: `[%(asctime)s] [%(levelname)s] %(message)s`
- **日時フォーマット**: `%Y-%m-%d %H:%M:%S`
- **出力先**:
  - コンソール（`sys.stdout`）
  - ファイル（`logs/bookmark_editor.log`、RotatingFileHandler、最大5MB、バックアップ3ファイル）
- **ログレベル**: DEBUG以上
- **ロガー**: `core/logger.py`で一元管理（`logger`）

## 6. 制約・前提

### 技術的制約
- **Python**: 3.10以上必須
- **GUIフレームワーク**: PySide6 6.7.0
- **AI API**: Google Generative AI API（Gemini 1.5 Flash）必須（AI分類機能使用時）

### 互換性要件
- **入力/出力フォーマット**: Netscape Bookmark HTML形式（Chrome/Edge/Firefox標準エクスポート形式）
- **ルールファイル**: JSON形式（`.bookmark_rules.json`、HTMLファイルと同名で自動生成）

### 変更しにくい前提条件
- **設定ファイル**: `config/config.ini`の存在（APIキー・プロキシ設定用）
- **プロンプトファイル**: `config/prompt.txt`の存在（AI分類用プロンプト）
- **外部ライブラリ**: `requests`、`beautifulsoup4`、`google-generativeai`（オプションだが機能制限あり）

## 7. 設定ファイル・データ構造

### config.iniの構造（推測・実装状況不明確）
```ini
[API]
api_key = YOUR_API_KEY

[Proxy]
url = http://proxy.example.com:8080
user = username
password = password

[Classifier]
priority_terms = term1, term2, term3
```

**注意**: 
- APIキーは環境変数`GENAI_API_KEY`または`GOOGLE_API_KEY`が優先される
- プロキシURLは`http://`または`https://`で始まる必要がある
- `priority_terms`はカンマ区切りの文字列

### ルールファイル（.bookmark_rules.json）のスキーマ
```json
{
  "フォルダ名": {
    "domains": ["domain1.com", "domain2.com"],
    "keywords": ["keyword1", "keyword2"]
  }
}
```

**デフォルトルール例**:
- Google: domains=["google.com", "gmail.com", "drive.google.com"], keywords=["google", "gmail", "drive"]
- YouTube: domains=["youtube.com", "youtu.be"], keywords=["youtube", "yt"]
- News: domains=["cnn.com", "bbc.co.uk", "nytimes.com", "news.yahoo"], keywords=["news", "article"]
- Social: domains=["twitter.com", "x.com", "facebook.com", "instagram.com", "linkedin.com"], keywords=["twitter", "facebook", "instagram", "linkedin"]
- Dev: domains=["github.com", "gitlab.com", "stackoverflow.com", "pypi.org", "readthe docs"], keywords=["github", "docs", "api", "stack overflow"]
- Shopping: domains=["amazon.", "rakuten.", "taobao.", "jd.com"], keywords=["cart", "buy", "store"]

## 8. 未実装・不安定な機能

### ファビコン表示
- **実装状況**: `services/workers.py`に`fetch_favicon()`関数が定義されているが、UIコンポーネントでの呼び出し箇所が見つからない
- **状態**: **未使用・未実装**

### 進捗チャート
- **実装状況**: `cmd_show_progress_chart()`メソッドは存在し、`progress_history`を棒グラフで表示する
- **問題点**: `progress_history`は`progress_update`イベントで`loaded_count`を追加するが、AI分類の進捗更新タイミングが不明確
- **状態**: **実装あり（動作不安定の可能性）**

### ドラッグ&ドロップ
- **実装状況**: `DragManager`クラスと`_on_drop_item()`メソッドが実装されている
- **制限**: 
  - 同一フォルダ内での順序変更のみ実装
  - フォルダ間移動は未実装（`_on_drop_item()`は`self.current_folder.children`内でのみ動作）
- **状態**: **部分実装（フォルダ間移動未対応）**

### 検索機能
- **実装状況**: `_build_search_index()`と`_apply_search()`が実装されている
- **問題点**: 
  - 検索結果の絞り込み表示が未実装
  - マッチするノードの親フォルダを表示するだけで、マッチしたアイテムのみを表示する機能がない
- **状態**: **部分実装（結果の絞り込み表示未対応）**

## 9. 不明点・コード上から判断不可な点

- `config.ini`の完全な構造（上記は推測、実際のファイル例がない）
- プロキシ設定の詳細フォーマット（認証方式、プロトコル指定方法等）
- ルールファイルの完全なスキーマ（上記はデフォルトルールから推測）
- 進捗チャートのデータ更新タイミング（AI分類の進捗イベント発火タイミング）
- ドラッグ&ドロップの完全な動作仕様（フォルダへのドロップ時の動作）
- 検索結果の表示方法（マッチしたアイテムのみを表示する機能の有無）
