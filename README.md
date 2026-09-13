# NeoBookMarkManager

ブックマークHTML（Netscape形式）を読み込み、整理・タグ付け・AI分類・リンク切れチェックを行うデスクトップアプリ（Tauri + axum）。

## セットアップ

### ビルド

```powershell
cargo tauri build --no-bundle
```

`target/release/NeoBookMarkManager.exe` が単体で生成されます（インストーラは作りません。`bundle.active` を `tauri.conf.json` で `true` にすればMSI/NSISも作れます）。

このEXEは**どこに置いても動く**ポータブル構成です。初回起動時に、EXEと同じフォルダに以下を自動生成します。

```
NeoBookMarkManager.exe
config/
  config.ini       ← 設定（APIキーなど）
  models.json       ← Geminiモデルの価格表
data/
  bookmarks.html
  user_data.db
backups/
```

### AI機能（Gemini）のAPIキー設定

`config/config.ini` の `[API]` セクションを編集します。

```ini
[API]
api_key = あなたのAPIキー
```

アプリ内の「AI設定」画面からも保存できます（`POST /config/api-key` 経由で同じファイルに書き込みます）。

環境変数 `GENAI_API_KEY` / `GOOGLE_API_KEY` を設定すると、`config.ini` より優先されます。通常は使わなくてOKです。

## Geminiモデルの一覧と料金（メンテナンス用メモ）

`config/models.json` に価格・特徴を一覧化してあります。コスト承認ゲート（実行前の見積もり表示）はこのファイルの単価を優先して使います。**このファイル自体がメンテナンス対象**で、コードを直さずテキスト編集だけで更新できるようにしてあります。

以下は `_updated: 2026-08-29` 時点の内容です。

| モデルID | 名称 | 入力 $/1M tokens | 出力 $/1M tokens | 備考 |
|---|---|---|---|---|
| `gemini-2.5-flash-lite` | Gemini 2.5 Flash-Lite（推奨・既定） | $0.10 | $0.40 | 最安。文書仕分けや単純な抽出タスクで圧倒的なコスパ。ブックマーク分類の既定。 |
| `gemini-3.1-flash-lite` | Gemini 3.1 Flash-Lite | $0.25 | $1.50 | 3.1世代の軽量モデル。2.5 Flash-Lite より賢く、2.5 Flash より安い。プレビューを終えて正式版に。 |
| `gemini-2.5-flash` | Gemini 2.5 Flash | $0.30 | $2.50 | 速度・価格・精度のバランス型。枯れた世代で挙動が安定している。 |
| `gemini-3.5-flash-lite` | Gemini 3.5 Flash-Lite | $0.30 | $2.50 | 3.5世代の軽量モデル。2.5 Flash と同単価でより新しい。 |
| `gemini-3.6-flash` | Gemini 3.6 Flash | $0.75 | $3.75 | ※導入価格。2026-12-31までは上記、以降は入力$1.50/出力$7.50に戻る。 |
| `gemini-3.7-flash` | Gemini 3.7 Flash | $0.75 | $3.75 | 最新かつ最も高性能なFlash。複雑なコーディングや多段の実行向け。※導入価格（上と同条件）。 |
| `gemini-2.5-pro` | Gemini 2.5 Pro | $1.25 | $10.00 | 高度な推論用。複雑な長文読解や難しい仕分けに。※20万トークン超は別単価（見積もり未反映）。 |
| `gemini-3.5-flash` | Gemini 3.5 Flash | $1.50 | $9.00 | 3.5世代の標準Flash。エージェント的な多段タスク向けで、Flashとしては高価格帯。 |
| `gemini-3.1-pro-preview` | Gemini 3.1 Pro (Preview) | $2.00 | $12.00 | 最高峰の文脈理解。プレビュー版のため予告なく変更・終了の可能性あり。※20万トークン超は別単価（見積もり未反映）。 |

出典: https://ai.google.dev/gemini-api/docs/pricing

> **⚠️ 注意: この一覧はGoogleの仕様変更で古くなります**
>
> Geminiのモデルラインナップ・価格は、このアプリのコードとは無関係にGoogle側の都合で変わります。具体的には：
>
> - **モデルが廃止・リネームされる**ことがあります。設定中のモデルが廃止されると、AI分類の実行時に「モデル「X」は利用できません」というエラーで停止します（`config/models.json` を書き換えず、当時のまま放置していると起こります）。
> - **価格が変わる**ことがあります。見積もり画面の金額が実際の請求と一致しなくなります。
> - **新しいモデルが追加される**ことがあります。追加しないと選択肢に出てきません。
>
> **対応方法**: [https://ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing) で最新のモデル一覧・価格を確認し、`config/models.json` を直接編集してください（アプリの再ビルドは不要、テキストファイルを書き換えて保存するだけで反映されます）。このREADMEの表も定期的に更新することを推奨します。
>
> モデルが利用不可になった場合、アプリはその場でAI分類を停止し、AI設定画面で別のモデルに切り替えるよう案内します（未処理分は失われず再実行できます）。ただし「まだ動くと思って設定していたら実は廃止されていた」という事前検知は行っていません。

## 開発メモ

- Rustワークスペース: `cargo build --workspace` / `cargo test --workspace`
- サーバー単体起動: `cargo run -p nbm-server -- <bookmarks.html>`
- フロントエンドはビルド不要の素のHTML/CSS/JS（`frontend/`）
