# リリース手順

配布物は `NeoBookMarkManager.exe` 1本（ポータブル）です。

## 1. バージョンを上げる

3か所を同じ番号に揃えます。ずれると、画面表示と実際のビルドが食い違います。

| ファイル | 場所 |
|---|---|
| `Cargo.toml` | `[workspace.package] version` |
| `src-tauri/tauri.conf.json` | `version` |
| `CHANGELOG.md` | 新しい見出しと、末尾のリンク |

画面左上とヘルプに出るバージョンは `Cargo.toml` の値（`/health` 経由）です。

## 2. 確認する

```powershell
cargo clippy --package nbm-core --package nbm-server -- -D warnings
cargo test --workspace
```

CI（GitHub Actions）でも同じものが回ります。

## 3. ビルドする

```powershell
cargo tauri build --no-bundle
```

生成物: `target/release/NeoBookMarkManager.exe`

- **アプリを終了してから**実行してください。起動中だと `os error 5 / 拒绝访问` で失敗します。
- メモリ不足（`os error 1455`、`STATUS_STACK_BUFFER_OVERRUN`）が出たら `-- -j 2` で並列数を下げます。
- 終了コードを必ず確認してください。`| tail` などに通すと失敗が隠れます。

インストーラ（MSI / NSIS）が必要な場合は `tauri.conf.json` の `bundle.active` を `true` にしてから
`cargo tauri build` を実行します。※この構成でのビルドは未検証です。

## 4. 動作を確認する

最低限、次を実機で確認します（自動テストはありません）。

- [ ] EXEを空のフォルダに置いて起動し、`config/` `data/` `backups/` が生成される
- [ ] 既存のブックマークHTMLを開ける
- [ ] 「⚡まとめて取得」が最後まで走り、ダッシュボードが100%になる
- [ ] AI分類を実行し、`logs/ai_classify.log` に `plan ok` が残る
- [ ] 保存し、`backups/` に新しい世代ができる
- [ ] いったん終了して再起動し、前回のファイルが開き、引き継ぎの確認が出る
- [ ] 画面左上のバージョン表示が、上げた番号になっている

## 5. 署名する（未対応）

現状、署名はしていません。このまま配布すると Windows SmartScreen が
「不明な発行元」の警告を出します。対応する場合は次が必要です。

1. コード署名証明書（OV または EV）を取得する。EVなら SmartScreen の評価が最初から付きます。
2. `signtool sign /fd SHA256 /tr <タイムスタンプURL> /td SHA256 /a NeoBookMarkManager.exe`
3. Tauri から自動で署名する場合は `tauri.conf.json` の `bundle.windows.certificateThumbprint` を設定します。

証明書は秘密情報です。リポジトリには置かず、CIで使う場合は GitHub Secrets に入れてください。

## 6. 配布する

```powershell
Get-FileHash target\release\NeoBookMarkManager.exe -Algorithm SHA256
```

1. タグを打つ: `git tag v1.0.0 && git push origin v1.0.0`
2. GitHub Release を作り、EXEとSHA256を添える（`.github/workflows/release.yml` がタグで自動実行します。※未検証）
3. `CHANGELOG.md` の該当セクションをリリースノートに使う

## 7. 配布後

- 使用中のフォルダにEXEを差し替える場合、`config/` `data/` `backups/` `logs/` はそのまま残してください。EXEだけを置き換えます。
- DBのスキーマが上がるときは、移行前に `user_data.db.bak-vN` が自動で作られます。
