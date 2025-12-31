#!/bin/bash
# 仮想環境を有効化するスクリプト

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "❌ 仮想環境が見つかりません: $VENV_DIR"
    echo "   以下のコマンドで仮想環境を作成してください:"
    echo "   python3 -m venv .venv"
    exit 1
fi

if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "❌ 仮想環境のactivateスクリプトが見つかりません"
    exit 1
fi

echo "✅ 仮想環境を有効化しています..."
source "$VENV_DIR/bin/activate"

echo ""
echo "=========================================="
echo "仮想環境が有効化されました"
echo "=========================================="
echo "Python: $(which python3)"
echo "pip: $(which pip)"
echo ""
echo "仮想環境を無効化するには 'deactivate' を実行してください"
echo "=========================================="

