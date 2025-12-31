#!/bin/bash
# ユーザー環境にインストールされたパッケージをクリーンアップするスクリプト

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"

echo "=========================================="
echo "ユーザー環境のパッケージクリーンアップ"
echo "=========================================="
echo ""

# requirements.txtからパッケージ名を抽出
PACKAGES=()
while IFS= read -r line; do
    # コメント行と空行をスキップ
    if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "$line" ]]; then
        continue
    fi
    
    # パッケージ名を抽出（>=, ==, >, < などのバージョン指定を除去）
    package=$(echo "$line" | sed -E 's/[[:space:]]*(>=|==|>|<|<=).*$//' | xargs)
    if [ -n "$package" ]; then
        PACKAGES+=("$package")
    fi
done < "$REQUIREMENTS_FILE"

echo "削除対象のパッケージ:"
for pkg in "${PACKAGES[@]}"; do
    echo "  - $pkg"
done
echo ""

# 確認
read -p "これらのパッケージをユーザー環境から削除しますか？ (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "キャンセルしました。"
    exit 0
fi

echo ""
echo "パッケージを削除しています..."

# 各パッケージを削除
REMOVED=0
NOT_FOUND=0

for pkg in "${PACKAGES[@]}"; do
    if python3 -m pip show "$pkg" --user &>/dev/null; then
        echo "  削除中: $pkg"
        python3 -m pip uninstall -y "$pkg" --user 2>&1 | grep -v "^$" || true
        REMOVED=$((REMOVED + 1))
    else
        echo "  見つかりません（既に削除済み？）: $pkg"
        NOT_FOUND=$((NOT_FOUND + 1))
    fi
done

echo ""
echo "=========================================="
echo "クリーンアップ完了"
echo "=========================================="
echo "削除したパッケージ: $REMOVED"
echo "見つからなかったパッケージ: $NOT_FOUND"
echo ""
echo "✅ ユーザー環境のクリーンアップが完了しました。"
echo "   仮想環境（.venv）のみを使用することを推奨します。"
echo ""

