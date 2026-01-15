# リポジトリ整理・棚卸しレポート - Bookmark Studio

## 1. プロジェクト概要（事実）

- **種別**: Desktopアプリケーション（Python + PySide6）
- **エントリポイント**: `main.py` → `gui.main_window.App`
- **ビルド・実行方法**:
  - 直接実行: `python3 main.py`
  - スクリプト実行: `./run.sh`（仮想環境作成・依存関係インストール・起動を自動化）
  - 依存関係インストール: `pip install -r requirements.txt`
  - テスト実行: `pytest tests/`（pytestが自動的に`tests/`ディレクトリを探索）
  - インストール確認: `python3 test_imports.py`（手動実行）

## 2. 現在のディレクトリ構成（事実）

```
NeoBookMarkManager/
├── core/                    # コア機能（データモデル、ストレージ、ログ、ユーティリティ）
│   ├── __init__.py
│   ├── logger.py
│   ├── model.py
│   ├── storage.py
│   └── utils.py
├── gui/                     # GUIコンポーネント（メインウィンドウ、コンポーネント、テーマ、UIキット）
│   ├── __init__.py
│   ├── components.py
│   ├── dialogs.py
│   ├── drag_manager.py
│   ├── main_window.py
│   ├── theme.py
│   └── ui_kit.py
├── services/                # サービス層（AI分類、ワーカー関数）
│   ├── __init__.py
│   ├── ai_classifier.py
│   └── workers.py
├── tests/                   # テストコード（pytest）
│   ├── conftest.py
│   ├── test_core.py
│   └── test_services.py
├── sampleHTML/              # サンプルHTMLファイル（テスト用？）
│   ├── bookmarks_2026_01_10.html
│   └── bookmarks_2026_01_10.bookmark_rules.json
├── __pycache__/             # Pythonキャッシュ（生成物、.gitignore対象）
├── main.py                  # エントリポイント
├── requirements.txt         # 依存関係定義
├── README.md                # プロジェクト説明
├── INSTALL.md               # インストール手順
├── SPECIFICATION.md         # 仕様書
├── REPOSITORY_AUDIT.md      # 前回の棚卸しレポート
├── prompt.txt               # AI分類用プロンプト（必須ファイル）
├── test_imports.py          # 依存関係インポートテスト（単体スクリプト）
├── bookmark_editor.log      # ログファイル（実行時生成、.gitignore対象）
├── run.sh                   # 実行スクリプト（仮想環境作成・起動）
├── install_dependencies.sh  # 依存関係インストールスクリプト
└── activate_venv.sh         # 仮想環境有効化スクリプト
```

### 各ディレクトリの役割

- **core/**: アプリケーションのコア機能（データモデル、設定管理、ログ、ユーティリティ）
- **gui/**: ユーザーインターフェース関連（ウィンドウ、コンポーネント、テーマ、ドラッグ&ドロップ）
- **services/**: バックグラウンド処理（AI分類、プレビュー取得、タイトル修正、ファビコン取得）
- **tests/**: pytestテストスイート（`conftest.py`でpytest設定、`test_*.py`が自動発見される）

## 3. モジュール構成（事実）

### モジュール一覧と責務

- **core**: データモデル、ストレージ、ログ、ユーティリティ
  - `model.py`: `Node`（ブックマーク/フォルダのデータ構造）、`NetscapeBookmarkParser`（HTMLパーサー）
  - `storage.py`: `ConfigManager`（`config.ini`管理）、`load_bookmarks`、`save_bookmarks`
  - `logger.py`: ログ設定（グローバル`logger`）
  - `utils.py`: `is_valid_url`、`LRUCache`、`AppConstants`

- **gui**: ユーザーインターフェース
  - `main_window.py`: `App`（メインアプリケーションクラス、UI構築、イベントハンドリング）
  - `components.py`: `BookmarkCard`、`BookmarkRow`、`FolderTree`、`SearchBar`、`DetailPanel`
  - `theme.py`: `Colors`、`Fonts`、`Dims`（デザイントークン）
  - `ui_kit.py`: `StyledButton`、`StyledCard`（基本UIコンポーネント）
  - `dialogs.py`: `CustomPromptDialog`（カスタムダイアログ）
  - `drag_manager.py`: `DragManager`（ドラッグ&ドロップ管理）

- **services**: バックグラウンド処理
  - `ai_classifier.py`: `AIBookmarkClassifier`（Gemini APIを使用したAI分類）
  - `workers.py`: `fetch_preview`、`fix_titles`、`fetch_favicon`（非同期処理関数）

- **tests**: テストコード（pytest）
  - `conftest.py`: pytest設定（`mock_bookmarks_file`、`mock_config_ini`フィクスチャ）
  - `test_core.py`: コア機能のテスト（`TestConfigManager`、`TestStorage`、`TestLogger`）
  - `test_services.py`: サービス機能のテスト（`TestWorkers`）

### モジュール間依存関係

```
main.py
  └─> gui.main_window.App

gui/main_window.py
  ├─> core.model.Node
  ├─> core.storage.ConfigManager, load_bookmarks, save_bookmarks
  ├─> core.logger.logger
  ├─> core.utils.is_valid_url, LRUCache, AppConstants
  ├─> gui.components.*
  ├─> gui.theme.Colors, Fonts, Dims
  ├─> gui.ui_kit.StyledButton, StyledCard
  ├─> gui.dialogs.CustomPromptDialog
  ├─> gui.drag_manager.DragManager
  ├─> services.ai_classifier.AIBookmarkClassifier
  └─> services.workers.fetch_preview, fix_titles, fetch_favicon

gui/components.py
  ├─> core.model.Node
  ├─> gui.theme.Colors, Fonts, Dims
  └─> gui.ui_kit.StyledButton

services/ai_classifier.py
  ├─> core.storage.ConfigManager
  ├─> core.logger.logger
  └─> prompt.txt（外部ファイル読み込み）

services/workers.py
  └─> core.utils.is_valid_url, LRUCache

tests/test_core.py
  ├─> core.storage.ConfigManager, load_bookmarks, save_bookmarks
  └─> core.logger.logger

tests/test_services.py
  └─> services.workers.*
```

## 4. 主要ファイルの役割（事実）

| ファイルパス | 役割 | 主要クラス・関数 | 参照元 |
|---|---|---|---|
| `main.py` | エントリポイント | `App`のインスタンス化と起動 | 直接実行、`run.sh` |
| `gui/main_window.py` | メインアプリケーション | `App` | `main.py` |
| `gui/components.py` | UIコンポーネント | `BookmarkCard`, `BookmarkRow`, `FolderTree`, `SearchBar`, `DetailPanel` | `gui/main_window.py` |
| `gui/theme.py` | デザイントークン | `Colors`, `Fonts`, `Dims` | `gui/components.py`, `gui/main_window.py`, `gui/ui_kit.py` |
| `gui/ui_kit.py` | UI基本コンポーネント | `StyledButton`, `StyledCard` | `gui/components.py`, `gui/main_window.py` |
| `gui/dialogs.py` | ダイアログ | `CustomPromptDialog` | `gui/main_window.py` |
| `gui/drag_manager.py` | ドラッグ&ドロップ | `DragManager` | `gui/main_window.py` |
| `core/model.py` | データモデル | `Node`, `NetscapeBookmarkParser` | `core/storage.py`, `gui/main_window.py` |
| `core/storage.py` | ストレージ管理 | `ConfigManager`, `load_bookmarks`, `save_bookmarks` | `gui/main_window.py`, `services/ai_classifier.py` |
| `core/logger.py` | ログ設定 | `logger`（グローバル） | `gui/main_window.py`, `core/storage.py` |
| `core/utils.py` | ユーティリティ | `is_valid_url`, `LRUCache`, `AppConstants` | `gui/main_window.py`, `services/workers.py` |
| `services/ai_classifier.py` | AI分類 | `AIBookmarkClassifier` | `gui/main_window.py` |
| `services/workers.py` | バックグラウンド処理 | `fetch_preview`, `fix_titles`, `fetch_favicon` | `gui/main_window.py` |
| `tests/test_core.py` | コア機能テスト | `TestConfigManager`, `TestStorage`, `TestLogger` | pytest（自動発見） |
| `tests/test_services.py` | サービス機能テスト | `TestWorkers` | pytest（自動発見） |
| `tests/conftest.py` | pytest設定 | `mock_bookmarks_file`, `mock_config_ini` | pytest（自動読み込み） |
| `test_imports.py` | 依存関係インポートテスト | `test_import`, `main` | `README.md`（手動実行） |
| `prompt.txt` | AI分類プロンプト | - | `services/ai_classifier.py:73` |
| `requirements.txt` | 依存関係定義 | - | `install_dependencies.sh`, `run.sh`, `README.md` |
| `run.sh` | 実行スクリプト | - | `README.md` |
| `install_dependencies.sh` | 依存関係インストールスクリプト | - | `README.md` |
| `activate_venv.sh` | 仮想環境有効化スクリプト | - | `README.md`（手動セットアップ手順） |

## 5. 参照・依存の棚卸し（事実）

### 主要外部ライブラリ

- **PySide6==6.7.0**: メインGUIフレームワーク（実際に使用）
- **google-generativeai**: Gemini APIクライアント（AI分類機能）
- **requests**: HTTPリクエスト（プレビュー取得、タイトル修正、ファビコン取得）
- **beautifulsoup4**: HTMLパーサー（ブックマークHTML解析、プレビュー取得）
- **pytest**: テストフレームワーク（`tests/`ディレクトリを自動発見）

### 設定ファイル一覧

- **`config.ini`**: アプリケーション設定（APIキー、プロキシ設定、優先用語）
  - 参照元: `core/storage.py:ConfigManager.__init__`（デフォルト: `"config.ini"`）
  - 参照元: `services/ai_classifier.py:AIBookmarkClassifier.__init__`（デフォルト: `"config.ini"`）
  - 生成物: 実行時に作成される可能性あり（`.gitignore`対象）

- **`requirements.txt`**: Python依存関係定義
  - 参照元: `install_dependencies.sh`, `run.sh`, `README.md`

- **`prompt.txt`**: AI分類用プロンプト（必須ファイル）
  - 参照元: `services/ai_classifier.py:73`（ハードコードされた相対パス `"prompt.txt"`）
  - 実行ディレクトリに依存（`main.py`の実行ディレクトリがルートである必要がある）

### 生成物・成果物ディレクトリ

- **`__pycache__/`**: Pythonバイトコードキャッシュ（`.gitignore`対象）
- **`.venv/`**: 仮想環境（`.gitignore`対象）
- **`bookmark_editor.log`**: ログファイル（実行時生成、`.gitignore`対象）

## 6. ルート直下に「残すべきファイル」（提案）

| ファイル | 理由 |
|---|---|
| `main.py` | エントリポイント（必須） |
| `requirements.txt` | pipがルート前提で探索する設定ファイル（必須） |
| `README.md` | プロジェクト説明（入口ファイル、必須） |
| `prompt.txt` | AI分類機能の必須ファイル（現在ハードコードされた相対パスで参照） |
| `config.ini` | アプリケーション設定（実行時にルートで探索される） |
| `.gitignore` | Git設定ファイル（ルート前提） |

**合計: 6ファイル**（目標20個以下を満たす）

## 7. 集約・移動候補（提案：危険度付き）

| 対象 | 移動先 | 危険度(L/M/H) | 移動理由 | 移動時に修正が必要な点 |
|---|---|---|---|---|
| `INSTALL.md` | `docs/INSTALL.md` | **L** | ルート直下のMarkdownを`docs/`に集約 | `README.md`内の参照があれば更新（現状参照なし） |
| `SPECIFICATION.md` | `docs/SPECIFICATION.md` | **L** | ルート直下のMarkdownを`docs/`に集約 | 参照元なし（影響なし） |
| `REPOSITORY_AUDIT.md` | `docs/REPOSITORY_AUDIT.md` | **L** | ルート直下のMarkdownを`docs/`に集約 | 参照元なし（影響なし） |
| `REPOSITORY_REORGANIZATION.md` | `docs/REPOSITORY_REORGANIZATION.md` | **L** | ルート直下のMarkdownを`docs/`に集約 | 参照元なし（影響なし） |
| `run.sh` | `scripts/run.sh` | **M** | スクリプト類を`scripts/`に集約 | `README.md`内の参照を更新（`./run.sh` → `./scripts/run.sh`） |
| `install_dependencies.sh` | `scripts/install_dependencies.sh` | **M** | スクリプト類を`scripts/`に集約 | `README.md`内の参照を更新 |
| `activate_venv.sh` | `scripts/activate_venv.sh` | **M** | スクリプト類を`scripts/`に集約 | `README.md`内の参照を更新（手動セットアップ手順） |
| `test_imports.py` | `tests/test_imports.py` | **M** | テスト関連を`tests/`に集約 | `README.md`内の参照を更新（`python3 test_imports.py` → `python3 tests/test_imports.py`） |
| `sampleHTML/` | `tests/fixtures/sampleHTML/` | **L** | テスト用サンプルファイルを`tests/fixtures/`に集約 | 参照元なし（影響なし） |
| `prompt.txt` | `config/prompt.txt` | **H** | 設定ファイルを`config/`に集約 | **`services/ai_classifier.py:73`のパスを修正**（`"prompt.txt"` → `"config/prompt.txt"`または設定化） |

## 8. "不要かもしれない"ファイル候補（提案）

| 候補ファイル/ディレクトリ | 危険度(L/M/H) | 不要の疑い（理由） | 参照確認結果 | Highの場合の隔離(deprecate)案 | 削除した場合の影響予測 |
|---|---|---|---|---|---|
| `sampleHTML/`ディレクトリ | **L** | テスト用サンプルファイルと思われるが、コードから参照されていない | `grep -r "sampleHTML\|bookmarks_2026"` → 0件 | - | 影響なし（参照されていないため） |
| `INSTALL.md` | **L** | `README.md`と内容が重複（インストール手順）、`README.md`の方が詳細 | `README.md`で参照なし | - | インストール手順の参照先が`README.md`のみになる（影響なし） |
| `SPECIFICATION.md` | **L** | 仕様書だが、コードと乖離している可能性（例：ドラッグ&ドロップの制限が実装で改善されている） | コードから参照なし | - | 影響なし（参照されていないため） |
| `REPOSITORY_AUDIT.md` | **L** | 前回の棚卸しレポート、今回の`REPOSITORY_REORGANIZATION.md`で置き換え可能 | 参照元なし | - | 影響なし（参照されていないため） |
| `activate_venv.sh` | **M** | `run.sh`で仮想環境有効化を自動化しているため、手動実行の必要性が低い | `README.md`で参照あり（手動セットアップ手順） | - | `README.md`の手動セットアップ手順が使えなくなる（ただし`run.sh`で代替可能） |
| `test_imports.py` | **M** | pytestテストスイートとは別の単体スクリプト、`README.md`で参照されているがCI/CDには未統合 | `README.md`で参照あり | **隔離案**: 1) pytestに統合（`tests/test_imports.py`として移動）、2) `README.md`の参照を削除してpytest推奨に変更 | `README.md`のインストール確認手順が使えなくなる（ただし`pytest`で代替可能） |
| `prompt.txt` | **H** | AI分類機能で使用されているが、ハードコードされたパス（`"prompt.txt"`） | `services/ai_classifier.py:73`で読み込み | **隔離案**: 1) `config.ini`に`[AI] prompt_file = prompt.txt`を追加、2) `ConfigManager`から読み込むように変更（デフォルト値: `"prompt.txt"`）、3) 設定可能にする、4) 移行期間を設けてから削除 | AI分類機能が動作しなくなる（**削除不可**） |

## 9. 安全に整理を進めるための手順（提案）

### Step 1: Low 危険度のみを対象に整理（移動・削除）

1. **Markdownファイルの集約**
   - `INSTALL.md` → `docs/INSTALL.md`（移動）
   - `SPECIFICATION.md` → `docs/SPECIFICATION.md`（移動）
   - `REPOSITORY_AUDIT.md` → `docs/REPOSITORY_AUDIT.md`（移動）
   - `REPOSITORY_REORGANIZATION.md` → `docs/REPOSITORY_REORGANIZATION.md`（移動）

2. **サンプルファイルの整理**
   - `sampleHTML/` → `tests/fixtures/sampleHTML/`（移動、または削除）

3. **確認手順**
   - `pytest tests/`（全テストが通ることを確認）
   - `python3 main.py`（アプリが正常に起動することを確認）

### Step 2: Med を検討（影響範囲限定で対応）

1. **スクリプトファイルの集約**
   - `run.sh` → `scripts/run.sh`（移動）
   - `install_dependencies.sh` → `scripts/install_dependencies.sh`（移動）
   - `activate_venv.sh` → `scripts/activate_venv.sh`（移動、または削除）
   - `README.md`内の参照を更新（`./run.sh` → `./scripts/run.sh`など）

2. **テストファイルの集約**
   - `test_imports.py` → `tests/test_imports.py`（移動）
   - `README.md`内の参照を更新（`python3 test_imports.py` → `python3 tests/test_imports.py`）
   - または、`test_imports.py`をpytestに統合（`tests/test_imports.py`として新規作成）

3. **確認手順**
   - `pytest tests/`（全テストが通ることを確認）
   - `python3 main.py`（アプリが正常に起動することを確認）
   - `./scripts/run.sh`（スクリプトが正常に動作することを確認）
   - `README.md`の手順を実際に実行して確認

### Step 3: High は deprecate → 移行完了後に削除

1. **`prompt.txt`の設定ファイル化（段階的移行）**
   - **Step 3.1**: `config.ini`に`[AI] prompt_file = prompt.txt`を追加
   - **Step 3.2**: `services/ai_classifier.py`を修正して`ConfigManager`から読み込むように変更（デフォルト値: `"prompt.txt"`）
   - **Step 3.3**: テストを実行して動作確認
   - **Step 3.4**: `prompt.txt` → `config/prompt.txt`（移動）
   - **Step 3.5**: `config.ini`のデフォルト値を`config/prompt.txt`に更新
   - **Step 3.6**: テストを実行して動作確認

2. **確認手順**
   - `pytest tests/`（全テストが通ることを確認）
   - `python3 main.py`（アプリが正常に起動することを確認）
   - AI分類機能を実際に使用して動作確認

### 各ステップで実行すべき確認（build / test / lint / 起動）

1. **ビルド確認**: `python3 -m py_compile <対象ファイル>`（該当する場合）
2. **インポート確認**: `python3 -c "import <モジュール名>"`（該当する場合）
3. **テスト実行**: `pytest tests/`（全テストが通ることを確認）
4. **起動確認**: `python3 main.py`（アプリが正常に起動することを確認）
5. **スクリプト確認**: `./scripts/run.sh`（スクリプトが正常に動作することを確認）
6. **Lint確認**: `pylint`または`flake8`（該当する場合）

### 注意事項

- **削除・移動は PR を分けること**（整理専用PR）
- **`prompt.txt`は削除不可**（AI分類機能の必須ファイル）
- **`requirements.txt`の変更は、仮想環境再構築が必要**（`pip install -r requirements.txt`を再実行）
- **スクリプトファイル（`.sh`）の削除は、Windows環境での動作に影響しない**（Linux/macOS環境のみ）
- **pytestは`tests/`ディレクトリを自動発見するため、`test_imports.py`を`tests/`に移動すると自動的にテストとして実行される可能性がある**（`test_`プレフィックスがあるため）

### 推奨される整理後のディレクトリ構成

```
NeoBookMarkManager/
├── core/                    # コア機能
├── gui/                     # GUIコンポーネント
├── services/                # サービス層
├── tests/                   # テストコード
│   ├── fixtures/           # テスト用サンプルファイル
│   │   └── sampleHTML/     # （オプション）
│   ├── conftest.py
│   ├── test_core.py
│   ├── test_services.py
│   └── test_imports.py      # （移動後）
├── scripts/                 # スクリプト類
│   ├── run.sh
│   ├── install_dependencies.sh
│   └── activate_venv.sh    # （オプション、削除可）
├── docs/                    # ドキュメント
│   ├── INSTALL.md
│   ├── SPECIFICATION.md
│   ├── REPOSITORY_AUDIT.md
│   └── REPOSITORY_REORGANIZATION.md
├── config/                  # 設定ファイル（オプション）
│   └── prompt.txt           # （移動後）
├── main.py                  # エントリポイント
├── requirements.txt         # 依存関係定義
├── config.ini               # アプリケーション設定（実行時に作成される可能性）
├── README.md                 # プロジェクト説明
└── .gitignore               # Git設定
```

**ルート直下のファイル数: 5ファイル**（目標20個以下を満たす）
