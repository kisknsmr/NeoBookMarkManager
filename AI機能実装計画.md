承知いたしました。ご指摘の通り、ローカルでのタグ判定（コストゼロ・非破壊・非通信優先）こそがこのシステムの「第一防衛線」でした。

これを **Phase 2.2** として正式に組み込み、AI処理（Phase 2.3）の前に実行されるフローを明記した **最終決定版「v2.1」** です。これをCursorに渡して実装を開始しましょう。

---

# 🛡️ NeoBookmarkManager: Engineering Safety Specifications (Final v2.1)

*(Strict Implementation Guidelines for Cursor / 実装前 必読・遵守)*

この仕様は AI機能を「危険物」扱いし、データ破壊・運用破綻・復元不能を物理的に防ぐための最終版です。
本仕様の **[Must]** 項目が未実装の状態では、AI関連機能をUI上で有効化しないこと。

### 用語

* **対象ファイル**: `bookmarks.html`, `user_data.db`, `config.ini`
* **AI処理**: Pattern 1/2/3 のいずれか（分類・移動・タグ付け）を伴うバッチ
* **コミット**: 変更をファイル（HTML/DB）に永続化すること
* **レビュー**: AI提案の適用前にユーザーが確認・選別する工程
* **AI専用ルート**: `/_AI`（HTMLツリーのルート直下に固定で作る運用領域）

---

## 0. Backup & Restore (Storage Lifecycle)

「壊しても戻せる」を物理的に保証する。

### 0.1 自動バックアップ（実行ゲート）

* **[Must] 実行タイミング**: AI処理・一括整理・タグ付け等、破壊的変更を伴うバッチ処理の **開始直前に必ず実行**。
* **[Must] バックアップ対象**: `bookmarks.html`, `user_data.db`, `config.ini` の3点セット。
* **[Must] 保存先**: `backups/YYYYMMDD_HHMMSS/` ディレクトリを作成し、その配下に3点をコピー。
* **[Must] 失敗時の挙動**: バックアップ作成に失敗した場合、後続の処理を **即時中止**し、ユーザーにエラー通知（黙って続行しない）。
* **[Must] クリーンアップ**: 新しいバックアップ作成が成功した場合のみ、古い順に削除して **最新30世代**を維持。
* **[Must] サイズ肥大防止**: 削除処理の失敗もエラー扱い。世代上限超過のまま処理継続しない。

### 0.2 復元（Undo）の定義

* **[Must] UIに以下を提供**:
* 「直前の状態に戻す（Undo）」: 最新バックアップを即復元
* 「バックアップ一覧から復元」: 世代選択復元


* **[Must] 復元プロセス**:
1. 現在の対象ファイル3点を `backups/_pre_restore_safety/YYYYMMDD_HHMMSS/` に退避（復元ミス保険）
2. 選択バックアップの3点を所定位置へコピー（上書き）
3. **アプリを強制再起動（または完全リロード）**。メモリ上の状態は破棄する。



---

## 1. Database & Migration

スキーマ変更時の事故を防ぐ。

### 1.1 スキーマバージョン管理

* **[Must]** `schema_version` テーブルを作成し、現在のバージョン整数を保持。
* **[Must]** 起動時に `CURRENT_VERSION` と比較し、必要なら **順次マイグレーション関数を実行**（1→2→3…）。
* **[Must] 前方互換禁止**: `db_version > CURRENT_VERSION` の場合は **起動拒否**。

### 1.2 安全なマイグレーション

* **[Must]** マイグレーション開始前に **必ずDBバックアップ**。
* **[Must]** `ALTER TABLE` 等が失敗した場合は即座にバックアップから復元し、起動を中止する。

---

## 2. Data Integrity (URL Normalization & Identity)

「別物」を「同一」と誤認するリスクを排除する。

### 2.1 正規化レベルの分離

* **[Must] `safe_canonical` (Default)**: 末尾スラッシュ削除 / `utm_` 系パラメータ削除 / 空クエリ削除 / `#fragment`維持 / プロトコル維持
* **[Must] `aggressive_canonical**`（ユーザー許可時のみ）: プロトコル統一 / `www.` 削除 / 全クエリ削除

### 2.2 オリジナルデータの保持と衝突対策

* **[Must]** ブックマークは **内部ID（`bookmark_id`）** を持つ。
* **[Must]** `url_tags` は `bookmark_id` 単位で紐付け可能な設計にする（URL文字列主キーのみ禁止）。

---

## 3. Enhanced DB Schema (Tags)

運用に耐えるタグDB。

### 3.1 テーブル定義（最終）

* `tags`: `id`, `name`, `normalized_name` (UNIQUE), `created_at`
* `url_tags`: `bookmark_id`, `tag_id`, `source` ('manual','ai','rule'), `confidence`, `created_at`
* **[Must] インデックス**: `url_tags(bookmark_id)`, `url_tags(tag_id)`, `tags(normalized_name UNIQUE)`

---

## 4. AI Robustness (Retry, Validation, Logging)

AIは不安定・不正確であることを前提とする。

### 4.1 リトライ戦略

* **[Must] リトライ**: JSON不正時は修正指示付きで1回再試行。429/5xxは指数バックオフで最大3回。
* **[Must] Validation**: Pydantic等で型チェック。必須フィールド欠落はエラー。
* **[Must] Confidence**: AIプロンプトに `confidence` と `reason` を必須出力として指示。

---

## 5. Scalability & Transaction

大規模データでの破綻を防ぐ。

### 5.1 チャンク処理とトランザクション

* **[Must] チャンクサイズ**: 30〜50件。
* **[Must] 原則コミット**: レビュー承認後に一括コミット。
* **[Must] キャンセル保証**: キャンセルは「次チャンク開始前」のみ。未コミット変更は破棄（Rollback）。

---

## 6. UI/UX Safety (Review & Feedback)

AIの「勝手な判断」を許さない。

### 6.1 レビューUI（Pre-flight Check）

* **[Must]** AI提案は **必ずレビュー画面を経由**。
* **[Must] 表示項目**: 元フォルダ, 提案先, タイトル, URL, Confidence, Reason。
* **[Must] ソート初期値**: Confidence 昇順（不安なものを上に）。

### 6.2 コスト試算と承認

* **[Must]** 通信前に概算コストを表示し、ユーザー承認を得る。

---

## 7. Logic Safety (Folder & Unsorted)

構造破壊を防ぐ。

* **[Must] フォルダ作成制限**: `/_AI` 配下、または指定ルート直下のみ。既存階層に勝手にフォルダを掘らない。
* **[Must] 退避先固定**: 失敗・低Confidence項目は `/_AI/Review` へ。
* **[Must] Pattern 1**: 「再構築」ではなく **削除なしのMove** として実装。

---

## 8. Privacy & Local Priority (Final)

* **[Must] 送信前サニタイズ**: URLからクエリパラメータを削除するオプションを提供（デフォルトON）。
* **[Must] ローカル優先**: **ローカルルールベース判定（Tier 1）を第一優先**とし、AI通信は二次的なオプションとする。
* **[Must] APIキー**: OS Keyring またはユーザー管理の `config.ini` のみに保存。

---

# 🗺️ Implementation Master Plan (for Cursor)

### Phase 1: Robust Infrastructure

1. **`core/UtilBackupManager.py`（新規）**
* バックアップ（3点セット）、世代管理（30世代）、復元（Undo）。


2. **`core/DatabaseManager.py`（改修）**
* `schema_version` 管理、マイグレーション基盤。


3. **`core/UtilSafety.py`（新規）**
* `safe_canonical(url)`、タグ正規化。



### Phase 2: Core Logic (Local & AI)

1. **`services/ServiceBookmark.py`（改修）**
* AI専用ルート `/_AI` 管理、Moveガード。


2. **`services/ServiceAutoTag.py`（新規・ローカル優先機能）**
* **[Must] Tier 1**: ドメイン/キーワード辞書による高速タグ付け（非通信）。
* **[Must] Tier 2**: 軽量スクレイピング（Timeout **3s厳守**、エラー無視）。
* **[Must]**: 結果を `source='rule'` としてDB保存。


3. **`services/ServiceAiClassifier.py`（改修）**
* チャンク処理、コスト試算、リトライ、Pydantic検証。



### Phase 3: Safe UI Integration

1. **`gui/components.py`（追加）**
* `AiReviewDialog`（提案一覧、Confidence、一括除外）。
* `AiProgressDialog`（進捗、キャンセル）、`RestoreDialog`。


2. **`gui/controllers/ControllerMainWindow.py`（改修）**
* フロー統合: **バックアップ → ローカルタグ → (選択時のみ)AI処理 → レビュー → 適用**。
* **AI機能は Phase 1 の Must を満たすまで無効化。**



---

### Cursorへの最上位指示（必ず冒頭に置く）

* 本仕様の **[Must]** を削除・緩和・省略して実装しないこと。
* Must が未実装なら AI関連UIは無効化すること。
* 「例外時に黙って続行」を禁止すること（必ずユーザーへ明示）。
