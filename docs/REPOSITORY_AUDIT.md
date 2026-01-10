# リポジトリ棚卸しレポート - Bookmark Studio

## 1. プロジェクト概要（事実）

- **種別**: Desktopアプリケーション（Python + CustomTkinter）
- **エントリポイント**: `main.py` → `gui.main_window.App`
- **ビルド/実行方法**:
  - 直接実行: `python3 main.py`
  - スクリプト実行: `./run.sh`（仮想環境作成・依存関係インストール・起動を自動化）
  - 依存関係インストール: `pip install -r requirements.txt`
  - インストール確認: `python3 test_imports.py`

## 2. ディレクトリ構成（事実）

```
NeoBookMarkManager/
├── core/              # コア機能（データモデル、ストレージ、ログ、ユーティリティ）
├── gui/               # GUIコンポーネント（メインウィンドウ、コンポーネント、テーマ、UIキット）
├── services/          # サービス層（AI分類、ワーカー関数）
├── tests/             # テストコード（pytest）
├── sampleHTML/        # サンプルHTMLファイル（テスト用？）
├── __pycache__/       # Pythonキャッシュ（生成物）
├── .venv/             # 仮想環境（生成物、gitignore対象想定）
├── main.py            # エントリポイント
├── requirements.txt   # 依存関係定義
├── README.md          # プロジェクト説明
├── SPECIFICATION.md   # 仕様書
├── INSTALL.md         # インストール手順
├── prompt.txt         # AI分類用プロンプト
├── test_imports.py    # 依存関係インポートテスト
├── bookmark_editor.log # ログファイル（実行時生成）
└── *.sh               # 各種シェルスクリプト（セットアップ・実行用）
```

## 3. モジュール構成（事実）

### モジュール一覧と責務

- **core**: データモデル、ストレージ、ログ、ユーティリティ
  - `model.py`: Nodeクラス、NetscapeBookmarkParser
  - `storage.py`: ConfigManager、load_bookmarks、save_bookmarks
  - `logger.py`: グローバルロガー設定
  - `utils.py`: URL検証、LRUCache、AppConstants

- **gui**: UIコンポーネントとメインウィンドウ
  - `main_window.py`: Appクラス（メインアプリケーション）
  - `components.py`: BookmarkCard、BookmarkRow、FolderTree、SearchBar、DetailPanel
  - `theme.py`: Colors、Fonts、Dims（デザイントークン）
  - `ui_kit.py`: StyledButton、StyledCard、IconButton
  - `dialogs.py`: CustomPromptDialog
  - `drag_manager.py`: DragManager（ドラッグ&ドロップ管理）

- **services**: バックグラウンド処理
  - `ai_classifier.py`: AIBookmarkClassifier（Gemini API使用）
  - `workers.py`: fetch_preview、fix_titles、fetch_favicon

### モジュール間依存関係

```
main.py
  └─> gui.main_window.App
        ├─> core.* (model, storage, logger, utils)
        ├─> gui.* (components, theme, ui_kit, dialogs, drag_manager)
        └─> services.* (ai_classifier, workers)

gui.components
  └─> gui.ui_kit (StyledCard)
  └─> gui.theme (Colors, Fonts, Dims)

services.ai_classifier
  └─> core.storage (ConfigManager)
  └─> prompt.txt (外部ファイル読み込み)

services.workers
  └─> core.utils (AppConstants)
```

## 4. 主要ファイルの役割（事実）

| ファイルパス | 役割 | 主要クラス・関数 | 参照元 |
|---|---|---|---|
| `main.py` | エントリポイント | - | 直接実行 |
| `gui/main_window.py` | メインアプリケーション | `App` | `main.py` |
| `gui/components.py` | UIコンポーネント | `BookmarkCard`, `BookmarkRow`, `FolderTree`, `SearchBar`, `DetailPanel` | `gui/main_window.py` |
| `gui/theme.py` | デザイントークン | `Colors`, `Fonts`, `Dims` | `gui/components.py`, `gui/main_window.py`, `gui/ui_kit.py` |
| `gui/ui_kit.py` | UI基本コンポーネント | `StyledButton`, `StyledCard`, `IconButton` | `gui/components.py`, `gui/main_window.py` |
| `gui/dialogs.py` | ダイアログ | `CustomPromptDialog` | `gui/main_window.py` |
| `gui/drag_manager.py` | ドラッグ&ドロップ | `DragManager` | `gui/main_window.py` |
| `core/model.py` | データモデル | `Node`, `NetscapeBookmarkParser` | `core/storage.py`, `gui/main_window.py` |
| `core/storage.py` | ストレージ管理 | `ConfigManager`, `load_bookmarks`, `save_bookmarks` | `gui/main_window.py`, `services/ai_classifier.py` |
| `core/logger.py` | ログ設定 | `logger`（グローバル） | `gui/main_window.py`, `core/storage.py` |
| `core/utils.py` | ユーティリティ | `is_valid_url`, `LRUCache`, `AppConstants` | `gui/main_window.py`, `services/workers.py` |
| `services/ai_classifier.py` | AI分類 | `AIBookmarkClassifier` | `gui/main_window.py` |
| `services/workers.py` | バックグラウンド処理 | `fetch_preview`, `fix_titles`, `fetch_favicon` | `gui/main_window.py` |
| `tests/test_core.py` | コア機能テスト | `TestConfigManager`, `TestStorage`, `TestLogger` | pytest |
| `tests/test_services.py` | サービス機能テスト | `TestWorkers` | pytest |
| `tests/conftest.py` | pytest設定 | `mock_bookmarks_file`, `mock_config_ini` | pytest |
| `test_imports.py` | 依存関係インポートテスト | `test_import`, `main` | `README.md`（手動実行） |
| `prompt.txt` | AI分類プロンプト | - | `services/ai_classifier.py` |
| `requirements.txt` | 依存関係定義 | - | `install_dependencies.sh`, `run.sh`, `README.md` |

## 5. 参照・依存の棚卸し（事実）

### 外部依存（主要ライブラリ）

- **customtkinter>=5.2.0**: メインGUIフレームワーク（実際に使用）
- **ttkthemes**: requirements.txtに記載（**コード内で未使用**）
- **ttkbootstrap>=1.19.0**: requirements.txtに記載（**コード内で未使用**、`test_imports.py`でのみインポートテスト）
- **Pillow>=9.0.0**: 画像処理（ファビコン・プレビュー表示）
- **requests>=2.28.0**: ネットワーク通信（プレビュー取得、タイトル修正）
- **beautifulsoup4>=4.11.0**: HTMLパース（プレビュー取得）
- **google-generativeai>=0.3.0**: AI分類（Gemini API）
- **pyperclip>=1.8.2**: クリップボード操作（使用箇所未確認）

### 設定ファイル

- **config.ini**: 実行時に読み込み（`core/storage.py`の`ConfigManager`）
  - `[API]`: APIキー設定
  - `[Proxy]`: プロキシ設定
  - `[Classifier]`: 優先分類用語
- **.bookmark_rules.json**: HTMLファイルと同名で自動生成（ルール分類用）

### 生成物/成果物の扱い

- **`__pycache__/`**: Pythonキャッシュ（自動生成、gitignore対象想定）
- **`.venv/`**: 仮想環境（自動生成、gitignore対象想定）
- **`bookmark_editor.log`**: ログファイル（実行時生成、RotatingFileHandler、最大5MB、バックアップ3ファイル）
- **`.bookmark_rules.json`**: ルールファイル（HTMLファイル保存時に生成）

## 6. "不要かもしれない"ファイル候補（提案：候補＋根拠＋確認手順＋危険度＋隔離案）

| 候補ファイル/ディレクトリ | 危険度(L/M/H) | 不要の疑い（理由） | 参照確認結果（参照元） | 削除前にやる確認 | Highの場合の隔離(deprecate)案 | 削除した場合の影響予測 |
|---|---|---|---|---|---|---|
| `requirements.txt`内の`ttkthemes` | **L** | コード内でimport/使用されていない | `grep -r "ttkthemes"` → 0件 | `pip show ttkthemes`でインストール状況確認 | - | 影響なし（未使用のため） |
| `requirements.txt`内の`ttkbootstrap` | **L** | コード内でimport/使用されていない（`test_imports.py`でのみテスト） | `grep -r "ttkbootstrap\|ttkb"` → `test_imports.py`のみ | `test_imports.py`の該当行を削除してから`requirements.txt`から削除 | - | `test_imports.py`のテストが失敗する可能性（ただし実際のアプリには影響なし） |
| `gui/ui_kit.py`の`IconButton`クラス | **L** | 定義されているが使用されていない | `grep -r "IconButton"` → `ui_kit.py`のみ | 将来的な使用予定がないか確認 | - | 影響なし（未使用のため） |
| `sampleHTML/`ディレクトリ | **L** | テスト用サンプルファイルと思われるが、コードから参照されていない | `grep -r "sampleHTML\|bookmarks_2026"` → 0件 | 開発・テスト時の手動使用がないか確認 | - | 影響なし（参照されていないため） |
| `cleanup_all.sh` | **L** | 開発用スクリプト、README等で参照されていない | `grep -r "cleanup_all"` → 0件 | 開発者が手動で使用していないか確認 | - | 影響なし（参照されていないため） |
| `cleanup_user_packages.sh` | **L** | 開発用スクリプト、README等で参照されていない | `grep -r "cleanup_user"` → 0件 | 開発者が手動で使用していないか確認 | - | 影響なし（参照されていないため） |
| `activate_venv.sh` | **M** | `run.sh`で仮想環境有効化を自動化しているため、手動実行の必要性が低い | `README.md`で参照あり（手動セットアップ手順） | `README.md`の手動セットアップ手順が実際に使用されているか確認 | - | `README.md`の手動セットアップ手順が使えなくなる（ただし`run.sh`で代替可能） |
| `test_imports.py` | **M** | pytestテストスイートとは別の単体スクリプト、`README.md`で参照されているがCI/CDには未統合 | `README.md`で参照あり | CI/CDパイプラインに統合されているか確認 | - | `README.md`のインストール確認手順が使えなくなる（ただし`pytest`で代替可能） |
| `INSTALL.md` | **M** | `README.md`と内容が重複（インストール手順）、`README.md`の方が詳細 | `README.md`で参照なし | ユーザーが`INSTALL.md`を直接参照しているか確認 | - | インストール手順の参照先が`README.md`のみになる |
| `SPECIFICATION.md` | **L** | 仕様書だが、コードと乖離している可能性（例：ドラッグ&ドロップの制限が実装で改善されている） | コードから参照なし | 仕様書としての価値があるか、最新化されているか確認 | - | 影響なし（参照されていないため） |
| `prompt.txt` | **H** | AI分類機能で使用されているが、ハードコードされたパス（`"prompt.txt"`） | `services/ai_classifier.py:73`で読み込み | パスが相対パスのため、実行ディレクトリに依存。設定ファイル化または絶対パス化を検討 | **隔離案**: 1) `config.ini`に`[AI] prompt_file = prompt.txt`を追加、2) デフォルト値として`prompt.txt`を使用、3) 設定可能にする、4) 移行期間を設けてから削除 | AI分類機能が動作しなくなる（**削除不可**） |
| `bookmark_editor.log` | **L** | 実行時生成ファイル（gitignore対象想定） | `gui/main_window.py:126`で生成 | `.gitignore`に追加されているか確認 | - | 影響なし（生成物のため） |

## 7. 安全に整理する手順（提案）

### Phase 1: Low危険度の削除（削除のみPR）

1. **`requirements.txt`から未使用ライブラリを削除**
   - `ttkthemes`を削除
   - `ttkbootstrap`を削除（`test_imports.py`の該当行も削除）

2. **未使用クラスの削除**
   - `gui/ui_kit.py`の`IconButton`クラスを削除

3. **未参照ファイルの削除**
   - `sampleHTML/`ディレクトリを削除（または`.gitignore`に追加）
   - `cleanup_all.sh`を削除
   - `cleanup_user_packages.sh`を削除

4. **生成物の`.gitignore`確認**
   - `bookmark_editor.log`が`.gitignore`に含まれているか確認・追加

### Phase 2: Medium危険度の整理（置換 or 影響範囲を絞って削除）

1. **`test_imports.py`の扱い**
   - オプション1: pytestに統合（`tests/test_imports.py`として移動）
   - オプション2: `README.md`から参照を削除し、開発者向けドキュメントに移動

2. **`INSTALL.md`の扱い**
   - オプション1: `README.md`に統合して削除
   - オプション2: `README.md`から`INSTALL.md`へのリンクを追加して保持

3. **`activate_venv.sh`の扱い**
   - `README.md`の手動セットアップ手順を`run.sh`使用に統一して削除
   - または、`run.sh`の内部で`activate_venv.sh`を呼び出すように変更

### Phase 3: High危険度の隔離（deprecate → 移行完了後に削除）

1. **`prompt.txt`の設定ファイル化（段階的移行）**
   - **Step 1**: `config.ini`に`[AI] prompt_file = prompt.txt`を追加
   - **Step 2**: `services/ai_classifier.py`を修正して`ConfigManager`から読み込むように変更（デフォルト値: `"prompt.txt"`）
   - **Step 3**: 移行期間を設ける（例: 2-3リリース）
   - **Step 4**: デフォルト値の使用を非推奨化（警告ログを出力）
   - **Step 5**: デフォルト値を削除し、設定必須にする（または別のデフォルトパスに変更）

### 最低実行セット（確認手順）

削除PRごとに以下を実行：

1. **ビルド確認**: `python3 -m py_compile <削除対象ファイル>`（該当する場合）
2. **インポート確認**: `python3 -c "import <モジュール名>"`（該当する場合）
3. **テスト実行**: `pytest tests/`（全テストが通ることを確認）
4. **起動確認**: `python3 main.py`（アプリが正常に起動することを確認）
5. **Lint確認**: `pylint`または`flake8`（該当する場合）

### 注意事項

- **`prompt.txt`は削除不可**（AI分類機能の必須ファイル）
- **`requirements.txt`の変更は、仮想環境再構築が必要**（`pip install -r requirements.txt`を再実行）
- **スクリプトファイル（`.sh`）の削除は、Windows環境での動作に影響しない**（Linux/macOS環境のみ）
