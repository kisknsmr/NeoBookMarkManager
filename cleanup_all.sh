#!/bin/bash
# requirements.txtに記載されているパッケージをすべて削除するスクリプト（システム環境とユーザー環境の両方）

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"

echo "=========================================="
echo "パッケージクリーンアップ（システム環境 + ユーザー環境）"
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
read -p "これらのパッケージをシステム環境とユーザー環境の両方から削除しますか？ (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "キャンセルしました。"
    exit 0
fi

echo ""
echo "パッケージを削除しています..."

# 各パッケージを削除（ユーザー環境から）
REMOVED_USER=0
REMOVED_SYSTEM=0
NOT_FOUND=0

for pkg in "${PACKAGES[@]}"; do
    # ユーザー環境から削除
    if python3 -m pip show "$pkg" --user &>/dev/null; then
        echo "  [ユーザー環境] 削除中: $pkg"
        python3 -m pip uninstall -y "$pkg" --user 2>&1 | grep -v "^$" || true
        REMOVED_USER=$((REMOVED_USER + 1))
    fi
    
    # システム環境から削除（sudoが必要な場合がある）
    if python3 -m pip show "$pkg" &>/dev/null && ! python3 -m pip show "$pkg" --user &>/dev/null; then
        echo "  [システム環境] 削除中: $pkg"
        if python3 -m pip uninstall -y "$pkg" 2>&1 | grep -v "^$"; then
            REMOVED_SYSTEM=$((REMOVED_SYSTEM + 1))
        else
            echo "    （sudo権限が必要な可能性があります）"
        fi
    fi
    
    # どちらにも見つからない場合
    if ! python3 -m pip show "$pkg" &>/dev/null && ! python3 -m pip show "$pkg" --user &>/dev/null; then
        echo "  見つかりません（既に削除済み？）: $pkg"
        NOT_FOUND=$((NOT_FOUND + 1))
    fi
done

echo ""
echo "=========================================="
echo "クリーンアップ完了"
echo "=========================================="
echo "ユーザー環境から削除: $REMOVED_USER パッケージ"
echo "システム環境から削除: $REMOVED_SYSTEM パッケージ"
echo "見つからなかったパッケージ: $NOT_FOUND"
echo ""
echo "✅ クリーンアップが完了しました。"
echo "   今後は仮想環境（.venv）のみを使用することを推奨します。"
echo ""

