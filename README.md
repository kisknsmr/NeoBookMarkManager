# 🔖 Bookmark Studio — Professional Organizer

**ブックマークを整理・統合するデスクトップツール**

> **🎉 Status**: Version 2.0.0 (PySide6 Edition) — READY FOR USE
> 
> ✅ Full PySide6 GUI migration complete | ✅ All features functional | ✅ Session memory ready
>
> See [docs/MIGRATION_COMPLETE.md](docs/MIGRATION_COMPLETE.md) for detailed technical report.

Bookmark Studioは、Chrome等のブラウザからエクスポートしたブックマークHTMLファイルを読み込み、階層構造の編集、重複削除、そしてドメインベースの分類を行うことができる管理ツールです。AI分類はレガシーとして隔離されており、UIからは未接続です。

## 📋 目次

- [概要](#概要)
- [主要機能](#主要機能)
- [デザイン方針](#デザイン方針)
- [セットアップ](#セットアップ)
- [ロギング仕様](#ロギング仕様)
- [エラーハンドリング方針](#エラーハンドリング方針)
- [基本的な使い方](#基本的な使い方)
- [対応フォーマット](#対応フォーマット)
- [技術仕様](#技術仕様)

## 概要

### 目的

大量のブックマークを効率的に整理・分類し、重複を削除し、階層構造を最適化することを目的としたデスクトップアプリケーションです。現行UIではドメインベースの分類を提供します。

### 主要機能

#### 1. AIスマート分類

- **AI自動フォルダ分け**: Gemini APIを活用し、ブックマークのタイトルとURLから最適なカテゴリを推測して自動分類します
- **追加指示（プロンプト）対応**: 「技術系は細かく分けて」「英語のサイトはまとめないで」といった追加の指示をAIに与えて再分類させることが可能です
- **優先用語設定**: `config/config.ini` に特定のキーワードを設定することで、優先的に分類したいカテゴリを指定できます
- **ルールベース分類**: カスタムルールファイル（`.bookmark_rules.json`）を使用した自動分類もサポート

#### 2. 高度な編集・整理機能

- **ドラッグ＆ドロップ**: 直感的な操作でブックマークやフォルダを移動・並び替えできます
- **2画面モード**: 2つのツリービューを並べて表示し、効率的にブックマークを整理できます
- **重複削除**: フォルダ内での重複ブックマークを自動検出・削除します
- **重複フォルダ統合**: 同名のフォルダを1つにまとめる機能を搭載しています
- **並び替え**: タイトル順、ドメイン順での並び替えが可能です
- **リアルタイム検索**: インデックスベースの高速な検索により、大量のブックマークから目的のものを即座に特定します

#### 3. インテリジェント・メンテナンス

- **タイトル自動修正**: URLしか表示されていないブックマークのタイトルを、実際のウェブサイトから取得して自動的に書き換えます
- **ファビコン表示**: ブックマークのファビコンを自動取得・表示します
- **プレビュー表示**: 選択したブックマークの概要（メタデータ）を即座に表示します
- **プロキシ対応**: 企業環境等での利用を想定し、詳細なプロキシ設定と接続テスト機能を備えています

## デザイン方針

### Material Design 3 (Material You) Dark Theme

Bookmark Studioは、Google Material Design 3（Material You）の原則に基づいた商用品質のUIを提供します。

#### 🎨 デザイン特徴

- **Surface階層**: 奥行きを表現する3層のSurface設計（#121212 → #1E1E1E → #232323）
- **カラーシステム**: Primary (#BB86FC) / Secondary (#03DAC6) の統一されたカラーパレット
- **WCAG AA準拠**: 4.5:1以上のコントラスト比を保証、アクセシビリティ対応
- **8dp Grid**: Material Design 3の基準に準拠したスペーシングシステム

#### ✍️ タイポグラフィ

**カスタムフォント自動適用**:
- **Inter** (Variable Font) - メインUI（推奨）
- **Roboto** (Variable Font) - Material Design標準
- **Noto Sans JP** (Variable Font) - 日本語対応

`fonts/`フォルダに配置されたVariable Fontファイルを自動検出・適用します。

**フォントサイズ規定**:
- 見出し: 20-24px / SemiBold
- セクション見出し: 16-18px / Medium
- 本文: 14-15px / Regular
- 補助テキスト: 12-13px / Regular
- **最小サイズ: 12px**（可読性保証）

**行間設計**:
- 長時間利用を前提とした快適な行間（1.3～1.8）
- 適切な余白により、視認性と操作性を向上

#### 🎯 設計思想

1. **長時間利用への最適化**: 目に優しいダークテーマと適切な行間・余白
2. **プロフェッショナル品質**: 商用アプリケーションとして通用する完成度
3. **アクセシビリティ**: WCAG AA準拠、誰もが使いやすいUI
4. **拡張性**: 将来的なライトテーマ切替を想定した設計

### Modern Light Theme: Material Design 3 + Apple UI

本アプリケーションは、**Material Design 3（MD3）**と**Apple UI**のデザイン原則を融合した、モダンで洗練されたライトテーマを採用しています。

#### カラーパレット

- **プライマリカラー**: `#007AFF`（アクションブルー）
- **背景色**: `#F5F5F7`（ライトグレー）
- **サーフェス色**: `#FFFFFF`（白）
- **テキスト色**: `#1C1C1E`（プライマリ）、`#8E8E93`（セカンダリ）
- **アクセントカラー**: 成功（`#34C759`）、危険（`#FF3B30`）、警告（`#FFCC00`）

#### タイポグラフィ

- **フォントファミリー**: Yu Gothic UI（Windows 10/11標準の日本語フォント）
- **フォントサイズ**: 10px（XXS）～18px（XL）の階層システム
- **フォントウェイト**: Normal、Bold

#### レイアウト原則

- **角丸**: 6px（小）、12px（中）、18px（大）
- **スペーシング**: 4px（XS）～24px（L）の統一された間隔システム
- **カード型UI**: シャドウとボーダーを活用した階層的な情報表示
- **レスポンシブ**: 最小サイズ1000x600px、デフォルト1400x800px

#### UIコンポーネント

- **ボタン**: プライマリ、セカンダリ、成功、危険の4つのバリアント
- **ツリービュー**: PySide6 のツリー表示（`QTreeWidget`）
- **カード/リスト/ツリービュー**: 切り替え可能な3つの表示モード
- **ドラッグ＆ドロップ**: ツリービュー上で移動・並び替え

## セットアップ

### 必須環境

- **Python 3.10以上**
- **Google AI APIキー**: AI分類を利用する場合のみ必要です（`config/config.ini`または環境変数`GENAI_API_KEY`で設定）

### 依存関係のインストール

#### 方法1: 仮想環境を使用（推奨）

仮想環境を使用することで、システムのPython環境を汚染せずに依存関係を管理できます。

**自動セットアップスクリプト**：
```bash
./scripts/run.sh
```
このスクリプトは仮想環境の作成、依存関係のインストール、プログラムの起動を自動で行います。

**手動セットアップ**：
```bash
# 1. 仮想環境を作成
python3 -m venv .venv

# 2. 仮想環境を有効化
source .venv/bin/activate  # Linux/macOS
# または
.venv\Scripts\activate  # Windows

# 3. 依存関係をインストール
pip install -r requirements.txt

# 4. インストール確認
python3 tests/test_imports.py

# 5. プログラムを実行
python3 main.py
```

#### 方法2: システム環境に直接インストール

```bash
# 依存関係をインストール
pip install -r requirements.txt

# または、ユーザー環境にインストール
pip install --user -r requirements.txt
```

### 設定ファイル（`config/config.ini`）

アプリケーションの`config/`ディレクトリに`config.ini`を作成し、以下の形式で設定を行います：

```ini
[API]
api_key = YOUR_GOOGLE_AI_API_KEY

[Proxy]
url = http://proxy.example.com:8080
user = username
password = password

[Classifier]
priority_terms = tech, AI, development, design
```

**注意事項**：
- APIキーは環境変数`GENAI_API_KEY`または`GOOGLE_API_KEY`が優先されます
- プロキシURLは`http://`または`https://`で始まる必要があります
- プロキシ設定はオプションです（企業環境等で必要な場合のみ）

### プロンプトファイル（`config/prompt.txt`）

AI分類機能で使用するプロンプトファイルです。`config/prompt.txt` に配置してください（後方互換としてルートの `prompt.txt` もフォールバック参照されます）。

## ロギング仕様

### ログフォーマット

```
[TIMESTAMP] [LEVEL] MESSAGE
```

- **タイムスタンプ形式**: `YYYY-MM-DD HH:MM:SS`
- **ログレベル**: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

### 出力先

1. **標準出力（コンソール）**: すべてのログレベルを出力
   - フォーマット: `[%(asctime)s] [%(levelname)s] %(message)s`
   - 日時フォーマット: `%Y-%m-%d %H:%M:%S`

2. **ファイル出力**: `logs/bookmark_editor.log`
   - ログレベル: `INFO`以上
   - ローテーション: 最大5MB、バックアップ3ファイル
   - エンコーディング: UTF-8
   - フォーマット: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`

### ロガー設定

- **ロガー名**: `NeoBookMarkManager`
- **ログレベル**: `DEBUG`（コンソール）、`INFO`（ファイル）
- **設定場所**: `core/logger.py`
- **使用方法**: `from core.logger import logger`でインポート

### ログ出力例

```
[2026-01-10 17:30:45] [INFO] Application started.
[2026-01-10 17:30:50] [INFO] Loading bookmarks from: bookmarks.html
[2026-01-10 17:30:52] [WARNING] Failed to fetch preview for https://example.com: Connection timeout
[2026-01-10 17:31:00] [ERROR] AI classification failed: API key not found
```

## エラーハンドリング方針

### 例外処理の原則

1. **すべての例外を捕捉**: 予期しないエラーでもアプリケーションがクラッシュしないように、適切な例外処理を実装しています
2. **ログ出力**: すべての例外はログに記録され、デバッグと問題解決を支援します
3. **ユーザー通知**: 重要なエラーはユーザーに分かりやすいメッセージで通知されます

### エラー表示方法

#### メッセージボックス（`PySide6.QtWidgets.QMessageBox`）

- **`information`**: 情報表示（成功メッセージ等）
- **`warning`**: 警告表示（軽微な問題、注意喚起）
- **`critical`**: エラー表示（重大な問題、操作失敗）
- **`question`**: 確認ダイアログ（削除確認等）

#### エラーハンドリングパターン

```python
try:
    # 処理
    result = some_operation()
except SpecificException as e:
    logger.error(f"Operation failed: {e}")
    QMessageBox.critical(self, "Error", f"操作に失敗しました: {e}")
except Exception as e:
    logger.exception("Unexpected error occurred")
    QMessageBox.critical(self, "Error", "予期しないエラーが発生しました。")
```

### 主要なエラーハンドリング箇所

1. **ファイルI/O**: ファイル読み込み/書き込み時のエラーを捕捉し、ユーザーに通知
2. **ネットワーク通信**: タイムアウト、接続エラー、HTTPエラーを適切に処理
3. **AI API呼び出し**: APIキー不足、レート制限、ネットワークエラーを処理
4. **データ解析**: HTMLパースエラー、JSON解析エラーを処理

### リトライ機構

ネットワーク関連の操作（プレビュー取得、タイトル修正等）では、以下のリトライ機構を実装：

- **最大リトライ回数**: 3回
- **リトライ間隔**: 指数バックオフ（1秒、2秒、4秒）
- **404エラー**: リトライしない（即座に失敗として処理）

## 基本的な使い方

### プログラムの起動

**仮想環境を使用する場合**（推奨）：
```bash
./scripts/run.sh
```

または

```bash
source .venv/bin/activate
python3 main.py
```

**システム環境を使用する場合**：
```bash
python3 main.py
```

### アプリケーションの使い方

1. **ブックマークファイルの読み込み**
   - メニューから **[File] > [Open HTML…]** を選択
   - または右側パネルの **[📂 開く]** ボタンをクリック
   - Chrome/Edge/FirefoxからエクスポートしたHTMLファイルを選択

2. **ブックマークの整理**
   - **表示モード切替**: Tree / List / Card を切り替え
   - **ドラッグ＆ドロップ**: ツリービュー上でブックマーク/フォルダを移動・並び替え
   - **2画面モード**: ツリービューを左右に並べて整理
   - **検索**: 上部の検索バーでブックマークを検索

3. **スマート分類（ドメインベース）の実行**
   - 整理したいフォルダやブックマークを選択
   - 右側パネルの **[✨ スマート分類]** ボタンをクリック
   - プレビュー画面で分類結果を確認

4. **その他の操作**
   - **重複削除**: 右側パネルの **[🔍 重複を削除]** ボタン
   - **タイトル修正**: 右側パネルの **[🔗 URLからタイトルを取得]** ボタン
   - **並び替え**: 右側パネルの **[🔤 タイトル順に並び替え]** または **[🌐 ドメイン順に並び替え]** ボタン

5. **保存**
   - メニューから **[File] > [Save]** または **[File] > [Save As…]** を選択
   - または右側パネルの **[💾 保存]** または **[💾 名前を付けて保存]** ボタンをクリック
   - 編集したブックマークをHTMLファイルとして保存

## 対応フォーマット

### 入力/出力フォーマット

- **Netscape Bookmark HTML形式**: Chrome、Edge、Firefox等の標準エクスポート形式に対応
- **分類ロジック**: ドメインベース分類（UI）/ AI分類（レガシー）
- **ルールファイル**: JSON形式（`.bookmark_rules.json`、HTMLファイルと同名で自動生成）

### 互換性

- **Python**: 3.10以上
- **OS**: Windows 10/11、Linux、macOS
- **GUI**: PySide6 (Qt6)

## 技術仕様

### アーキテクチャ

- **フレームワーク**: PySide6（Qt6ベース）
- **データモデル**: 階層的な`Node`構造（フォルダ/ブックマーク）
- **非同期処理**: `threading`と`queue`を使用したバックグラウンド処理
- **キャッシュ**: LRUキャッシュによるパフォーマンス最適化

### 主要モジュール

- **`core/`**: データモデル、ストレージ、ログ、ユーティリティ
- **`gui/`**: メインウィンドウ、UIコンポーネント、テーマ
- **`services/`**: 分類（ドメインベース/レガシーAI）、バックグラウンド処理（プレビュー取得、タイトル修正、ファビコン取得）

### 依存ライブラリ

詳細は`requirements.txt`を参照してください。主要なライブラリ：

- `PySide6==6.7.0`: GUIフレームワーク
- `Pillow==10.2.0`: 画像処理
- `requests==2.31.0`: HTTP通信
- `beautifulsoup4==4.12.3`: HTML解析
- `google-generativeai==0.3.2`: AI分類（レガシー）

---

## ⚠️ 注意事項

本ツールは正式リリース前の開発版です。重要なブックマークの整理前には、**必ず元ファイルのバックアップを取ってください**。

実行ログはコンソールと`logs/bookmark_editor.log`に出力されます。問題が発生した場合は、ログファイルを確認してください。

---

## アーキテクチャ（v2.0+）

### 非同期化・パフォーマンス最適化

v2.0 では、以下の改善を実施しました：

#### 1. ワーカーマネージャー（`gui/worker_manager.py`）

- **ThreadPoolExecutor 導入**: I/O 処理（HTTP リクエスト、ファイル読み込み等）をバックグラウンドスレッドで実行
- **コールバック型の非同期処理**: `worker.submit(func, callback=ui_callback)` でタスク投入し、完了時に UI スレッドで `callback` を実行
- **UI スレッドブロック防止**: ネットワーク待機時に UI が応答不能になることを防止

#### 2. 画像最適化（`core/image_utils.py`）

- **自動縮小**: bytes から PIL Image に変換する際、指定サイズ（デフォルト 256x256）以下にリサイズ
- **LRU キャッシュ**: 同じバイト列の画像処理結果をメモリキャッシュし、重複処理を削減
- **PhotoImage 参照保持**: `App._image_refs` または `ImageCache` で参照を保持し、ガベージコレクションを防止
  - **重要**: 生成した `ImageTk.PhotoImage` は何らかのオブジェクトが参照を保持していないと、即座に消滅して画像が表示されません

#### 3. 設定管理の拡張（`core/storage.py`）

```python
# ConfigManager に汎用 get/set メソッドを追加
config_manager.get(section, option, fallback=None)
config_manager.set(section, option, value)
```

- **プロンプトファイル場所の統一**: `[Prompt]` セクションで `prompt_file` を指定可能
- **フォールバック対応**: 設定値が見つからない場合のデフォルト値対応

#### 4. I/O 堅牢化（`services/workers.py`）

- **timeout 設定**: すべての `requests.get()` に timeout を明示的に設定
- **例外細分化**: `Timeout`, `ConnectionError`, `HTTPError` を分けて処理
- **リトライ対応**: 指数バックオフでリトライ
- **404 非リトライ**: HTTP 404 の場合はリトライせず即座に終了
- **HTML キャッシュ**: LRU キャッシュでプレビュー抽出結果を保存

#### 5. UI 状態管理（`gui/ui_state.py`）

- **Observer パターン**: 状態変更時にコールバック実行
- **軽量ストア**: ノード選択、フォルダ展開、ソート順などを集中管理

#### 6. 仮想化リスト（`gui/virtual_list.py`）- プロトタイプ

- Canvas ベースの遅延レンダリング
- スクロール時に見える範囲のアイテムのみ描画（将来の本格実装に向けたプロトタイプ）

### アーキテクチャ図

```
main.py
  ↓
gui/ControllerMainWindow.py (MainWindow)
  ├─ gui/worker_manager.py (ThreadPoolExecutor ラッパー)
  ├─ gui/ui_state.py (状態管理 - self.ui_state)
  ├─ gui/command_handlers.py (メニューコマンド)
  ├─ gui/menu_bar.py (メニュー組み立て)
  ├─ core/storage.py (ConfigManager 拡張)
  ├─ core/image_utils.py (画像キャッシュ)
  └─ services/workers.py (非同期 I/O)
```

### 使用例

#### ワーカーでバックグラウンド実行

```python
# In gui/command_handlers.py
app.worker.submit(
   services.WorkerNetwork.fetch_preview,
    url,
    callback=lambda res: app.apply_preview_to_node(node_id, res)
)

# UI スレッドで定期的にポーリング
app.after(100, app.worker.poll_results)
```

#### 画像キャッシュ

```python
# In gui/LayoutComponents.py
photo = core.image_utils.bytes_to_tkphoto(img_bytes, max_width=256)
app.cache_image(node_id, photo)  # GC 対策
component.config(image=photo)
```

#### UI 状態管理

```python
# In gui/command_handlers.py
app.ui_state.set_sort_order("alphabetical")
app.ui_state.select_node(node_id)
```

#### ConfigManager 経由のプロンプト読み込み

```python
# In services/ai_classifier.py
prompt_path = self.config_manager.get('Prompt', 'prompt_file', fallback='config/prompt.txt')
```

### 段階的移行戦略

- **既存コード互換性を維持**: `gui/main_window.py` の App クラスは従来の呼び出しを受け付ける
- **新規コンポーネントは新 API を使用**: 新しい `gui/command_handlers.py`, `gui/menu_bar.py` は `gui/worker_manager.py`, `gui/ui_state.py` を活用
- **将来的な完全置換**: コンポーネント単位で段階的に新アーキテクチャに移行可能

---

## 📄 ライセンス

（ライセンス情報をここに追加）

---

## 🤝 コントリビューション

（コントリビューションガイドラインをここに追加）
