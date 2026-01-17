# カスタムフォント導入ガイド

## 📁 フォルダ構成

```
NeoBookMarkManager/
├── fonts/                          ← カスタムフォントディレクトリ
│   ├── InterVariable.ttf           ← Inter Variable Font（推奨）
│   ├── Roboto-VariableFont_wdth,wght.ttf  ← Roboto Variable Font
│   └── NotoSansJP-VariableFont_wght.ttf   ← Noto Sans JP Variable Font
├── core/
│   └── font_loader.py              ← フォントローダー（自動検出）
└── gui/
    └── theme.py                    ← タイポグラフィ設定
```

## ✅ 現在の状態

### フォント検出状況

起動時に以下のログが表示されます:

```
フォント検出: Inter -> InterVariable.ttf
フォント検出: Roboto -> Roboto-VariableFont_wdth,wght.ttf
フォント検出: Noto Sans JP -> NotoSansJP-VariableFont_wght.ttf
```

### 自動適用済み

- ✅ **Inter** が第一優先フォントとして自動選択
- ✅ UI全体に Material Design 3 タイポグラフィスケール適用
- ✅ Variable Font対応（ウェイト自動調整）
- ✅ システムフォントへの自動フォールバック

## 🎯 フォント優先順位

```python
1. Inter           ← デフォルト（推奨）
2. Roboto          ← Material Design標準
3. Noto Sans JP    ← 日本語最適化
4. Segoe UI        ← システムフォールバック（Windows）
```

## 🔧 動作確認

### フォントローダーのテスト

```powershell
# フォント情報を表示
python -c "from core.font_loader import FontLoader; import json; print(json.dumps(FontLoader.get_font_info(), indent=2, ensure_ascii=False))"
```

### 期待される出力

```json
{
  "font_dir": "E:\\...\\NeoBookMarkManager\\fonts",
  "available_fonts": {
    "Inter": "E:\\...\\fonts\\InterVariable.ttf",
    "Roboto": "E:\\...\\fonts\\Roboto-VariableFont_wdth,wght.ttf",
    "Noto Sans JP": "E:\\...\\fonts\\NotoSansJP-VariableFont_wght.ttf"
  },
  "initialized": true
}
```

## 🎨 適用箇所

### 自動適用されているコンポーネント

| コンポーネント | フォント | サイズ | ウェイト |
|---------------|----------|--------|----------|
| **StyledButton** | Inter | 14px | Medium |
| **見出し** | Inter | 22px | Bold |
| **セクション** | Inter | 16px | Medium |
| **本文** | Inter | 14px | Regular |
| **補助テキスト** | Inter | 12px | Regular |

### UIコンポーネント例

```python
from gui.ui_kit import StyledButton
from gui.theme import Typography

# ボタン: Inter 14px Medium（自動適用）
button = StyledButton(parent, text="保存", variant="primary")

# カスタムラベル: Inter 22px Bold
label = ctk.CTkLabel(
    parent,
    text="見出し",
    font=Typography.create_headline_font()
)
```

## 📝 カスタマイズ

### 優先フォントを変更

`gui/theme.py` を編集:

```python
class Typography:
    # === Font Family（FontLoaderから取得）===
    FAMILY_PRIMARY = FontLoader.get_font_family("Roboto")  # ← 変更
    # ...
```

### 新しいフォントを追加

1. **フォントファイルを配置**:
   ```
   fonts/
   └── YourCustomFont.ttf
   ```

2. **`core/font_loader.py` を編集**:
   ```python
   font_files = {
       "Inter": "InterVariable.ttf",
       "Roboto": "Roboto-VariableFont_wdth,wght.ttf",
       "Noto Sans JP": "NotoSansJP-VariableFont_wght.ttf",
       "Your Custom": "YourCustomFont.ttf",  # ← 追加
   }
   ```

3. **使用例**:
   ```python
   font = FontLoader.create_font(
       family="Your Custom",
       size=16,
       weight="bold"
   )
   ```

## 🚀 パフォーマンス

### 起動時の処理

1. `core/font_loader.py` モジュール読み込み時に自動初期化
2. `fonts/` フォルダをスキャン（約10ms）
3. 利用可能なフォントをキャッシュ
4. GUI構築時はキャッシュから即座に取得

### メモリ使用量

- Variable Font 1ファイル: 約200-500KB
- 3フォント合計: 約1-1.5MB
- 起動時にメモリ展開、以降は再利用

## 🔒 本番環境での注意点

### フォントライセンス

- **Inter**: SIL Open Font License 1.1（商用利用可）
- **Roboto**: Apache License 2.0（商用利用可）
- **Noto Sans JP**: SIL Open Font License 1.1（商用利用可）

すべて商用利用可能なオープンソースフォントです。

### 配布時の推奨

1. `fonts/` フォルダを含めて配布
2. README.mdにフォントライセンス情報を記載
3. フォントが無い場合でも動作（システムフォントにフォールバック）

## 📚 関連ドキュメント

- [TYPOGRAPHY.md](./TYPOGRAPHY.md) - タイポグラフィ設計詳細
- [README.md](../README.md) - プロジェクト概要
- [SPECIFICATION.md](./SPECIFICATION.md) - 技術仕様

## 🎓 参考情報

### Variable Fontとは？

1つのフォントファイルに複数のウェイト（太さ）やスタイルを含めることができる次世代フォーマット。

**メリット**:
- ファイルサイズ削減（複数ファイル不要）
- スムーズなウェイト調整
- パフォーマンス向上

### フォントダウンロード元

- Inter: https://rsms.me/inter/
- Roboto: https://fonts.google.com/specimen/Roboto
- Noto Sans JP: https://fonts.google.com/noto/specimen/Noto+Sans+JP

---

**最終更新**: 2026-01-14  
**バージョン**: 1.0.0
