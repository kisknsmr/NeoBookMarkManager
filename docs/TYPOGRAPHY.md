# タイポグラフィ設計書

## 📝 概要

Bookmark StudioはMaterial Design 3（Material You）の原則に基づき、プロフェッショナル品質のタイポグラフィシステムを採用しています。

## 🎯 設計原則

### 1. フォント選択基準
- **可読性**: 長時間の利用に耐える視認性
- **モダンデザイン**: 2020年代の洗練されたUI/UX
- **Variable Font**: ウェイト調整の柔軟性
- **日本語対応**: CJK文字の美しい表示

### 2. サイズ制約
- **最小サイズ**: 12px（可読性の下限）
- **標準サイズ**: 14px（本文の基準）
- **見出しサイズ**: 16-24px（情報の階層化）

### 3. 長時間利用への配慮
- **行間**: 1.3～1.8（テキストタイプに応じた最適化）
- **余白**: 8dp gridによる統一感
- **コントラスト**: WCAG AA準拠（4.5:1以上）

---

## 🔤 フォントファミリー

### 優先順位

```
1. Inter (Variable Font) ← デフォルト・推奨
2. Roboto (Variable Font) ← Material Design標準
3. Noto Sans JP (Variable Font) ← 日本語対応
4. Segoe UI ← システムフォールバック（Windows）
```

### Variable Font対応

`fonts/`フォルダ内のフォントファイル:
- `InterVariable.ttf` - Inter Variable Font
- `Roboto-VariableFont_wdth,wght.ttf` - Roboto Variable Font
- `NotoSansJP-VariableFont_wght.ttf` - Noto Sans JP Variable Font

### 自動検出・フォールバック

`core/font_loader.py`により以下を自動実行:
1. `fonts/`フォルダ内のフォントファイルを検出
2. 優先順位に従ってフォントを選択
3. 利用不可の場合はシステムフォントにフォールバック

---

## 📐 タイプスケール（Material Design 3準拠）

### 見出し（Headlines）

| 用途 | サイズ | ウェイト | 行間 | 使用例 |
|------|--------|----------|------|--------|
| Large | 24px | Bold | 1.3 | ダイアログタイトル |
| Medium | 22px | Bold | 1.3 | セクション大見出し |
| Small | 20px | Bold | 1.3 | サブセクション見出し |

**サンプルコード**:
```python
font = Typography.create_headline_font()
```

### タイトル（Titles）

| 用途 | サイズ | ウェイト | 行間 | 使用例 |
|------|--------|----------|------|--------|
| Large | 18px | Medium | 1.5 | カードヘッダー |
| Medium | 16px | Medium | 1.5 | リストヘッダー |
| Small | 16px | Medium | 1.5 | セクション見出し |

**サンプルコード**:
```python
font = Typography.create_section_font()
```

### 本文（Body）

| 用途 | サイズ | ウェイト | 行間 | 使用例 |
|------|--------|----------|------|--------|
| Large | 15px | Regular | 1.5 | 長文本文 |
| Medium | 14px | Regular | 1.5 | 標準本文 |
| Small | 14px | Regular | 1.5 | コンパクト表示 |

**サンプルコード**:
```python
font = Typography.create_body_font()
```

### ラベル（Labels）

| 用途 | サイズ | ウェイト | 行間 | 使用例 |
|------|--------|----------|------|--------|
| Large | 13px | Regular | 1.8 | カード補助テキスト |
| Medium | 12px | Regular | 1.8 | フォームラベル |
| Small | 12px | Regular | 1.8 | 補助情報（最小） |

**サンプルコード**:
```python
font = Typography.create_caption_font()
```

### ボタン

| 用途 | サイズ | ウェイト | 使用例 |
|------|--------|----------|--------|
| Button | 14px | Medium | 全てのボタン |

**サンプルコード**:
```python
font = Typography.create_button_font()
```

---

## 🎨 フォントウェイト

### CustomTkinter制約

CustomTkinterは以下の2種類のウェイトのみサポート:
- `"normal"` → Regular（400相当）
- `"bold"` → Medium/SemiBold/Bold（500-700相当）

### Variable Font活用

Variable Fontでは、ファイル内に複数のウェイトが含まれており、CustomTkinterの`"normal"`/`"bold"`指定で自動的に最適なウェイトが選択されます。

### ウェイトマッピング

| 指定 | Variable Font | 用途 |
|------|---------------|------|
| `WEIGHT_REGULAR` | 400 (Regular) | 本文・補助テキスト |
| `WEIGHT_MEDIUM` | 500-600 (Medium/SemiBold) | セクション見出し・ボタン |
| `WEIGHT_BOLD` | 700 (Bold) | 大見出し・強調 |

---

## 📏 行間（Line Height）

長時間利用を前提とした快適な行間設計:

| 設定 | 値 | 用途 |
|------|-----|------|
| `LINE_HEIGHT_TIGHT` | 1.3 | 見出し（スペース効率重視） |
| `LINE_HEIGHT_NORMAL` | 1.5 | 本文（標準的な可読性） |
| `LINE_HEIGHT_COMFORTABLE` | 1.6 | 長文（読みやすさ重視） |
| `LINE_HEIGHT_LOOSE` | 1.8 | リスト・カード（視認性・操作性重視） |

---

## 💻 実装例

### 基本的な使い方

```python
from gui.theme import Typography

# 見出しフォント
headline_font = Typography.create_headline_font()

# セクション見出しフォント
section_font = Typography.create_section_font()

# 本文フォント
body_font = Typography.create_body_font()

# ボタンフォント
button_font = Typography.create_button_font()

# 補助テキストフォント
caption_font = Typography.create_caption_font()
```

### UIコンポーネントでの使用

```python
from gui.ui_kit import StyledButton

# ボタンは自動的にカスタムフォント（Inter 14px Medium）を使用
button = StyledButton(
    parent=frame,
    text="保存",
    variant="primary"
)
```

### カスタムフォント設定

```python
import customtkinter as ctk
from core.font_loader import FontLoader

# Robotoフォントを使用（Interが無い場合の代替）
font = FontLoader.create_font(
    family="Roboto",
    size=16,
    weight="bold"
)

label = ctk.CTkLabel(
    parent=frame,
    text="Custom Font",
    font=font
)
```

---

## 🚫 禁止事項

### サイズ
- ❌ **12px未満のフォントサイズ** → 可読性の問題
- ✅ 最小12px以上を使用

### フォント選択
- ❌ **装飾フォント**（Comic Sans、手書き風等） → プロフェッショナル品質を損なう
- ❌ **コード表示以外での等幅フォント** → UI/UXの統一感を損なう
- ✅ Inter / Roboto / Noto Sans JPを優先使用

### ウェイト
- ❌ **Light（300以下）の使用** → 視認性が低下
- ✅ Regular（400）以上を使用

---

## 🔧 トラブルシューティング

### フォントが適用されない

**原因**: `fonts/`フォルダが存在しない、またはフォントファイルが不足

**解決策**:
1. `fonts/`フォルダがプロジェクトルートに存在することを確認
2. 以下のフォントファイルが配置されていることを確認:
   - `InterVariable.ttf`
   - `Roboto-VariableFont_wdth,wght.ttf`
   - `NotoSansJP-VariableFont_wght.ttf`
3. アプリケーション起動時のログを確認:
   ```
   フォント検出: Inter -> InterVariable.ttf
   フォント検出: Roboto -> Roboto-VariableFont_wdth,wght.ttf
   フォント検出: Noto Sans JP -> NotoSansJP-VariableFont_wght.ttf
   ```

### システムフォールバックの確認

```python
from core.font_loader import FontLoader

# 利用可能なフォント情報を表示
info = FontLoader.get_font_info()
print(f"初期化状態: {info['initialized']}")
print(f"フォントディレクトリ: {info['font_dir']}")
print(f"利用可能なフォント: {list(info['available_fonts'].keys())}")
```

### フォントの優先順位を変更

```python
from core.font_loader import FontLoader

# Robotoを優先的に使用
font_family = FontLoader.get_font_family("Roboto")
print(f"使用フォント: {font_family}")
```

---

## 📚 参考資料

- [Material Design 3 Typography](https://m3.material.io/styles/typography)
- [Inter Font Family](https://rsms.me/inter/)
- [Roboto Font Family](https://fonts.google.com/specimen/Roboto)
- [Noto Sans JP](https://fonts.google.com/noto/specimen/Noto+Sans+JP)
- [WCAG 2.1 Guidelines](https://www.w3.org/WAI/WCAG21/quickref/)
- [8-Point Grid System](https://builttoadapt.io/intro-to-the-8-point-grid-system-d2573cde8632)

---

## 📝 更新履歴

- **2026-01-14**: Variable Font対応、カスタムフォントローダー実装
- **2026-01-14**: Material Design 3タイポグラフィスケール採用
- **2026-01-14**: 初版作成
