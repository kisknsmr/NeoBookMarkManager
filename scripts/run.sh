#!/bin/bash
# 仮想環境を有効化してプログラムを実行するスクリプト

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"

# 仮想環境が存在しない場合は作成
if [ ! -d "$VENV_DIR" ]; then
    echo "仮想環境が見つかりません。作成します..."
    python3 -m venv "$VENV_DIR"
    echo "✅ 仮想環境を作成しました"
fi

# 仮想環境を有効化
source "$VENV_DIR/bin/activate"

# プロジェクトディレクトリに移動
cd "$PROJECT_ROOT"

# 依存関係をインストール（必要に応じて）
if [ ! -f "$VENV_DIR/.installed" ]; then
    echo "依存関係をインストールしています..."
    pip install -r "$PROJECT_ROOT/requirements.txt"
    touch "$VENV_DIR/.installed"
    echo "✅ 依存関係のインストールが完了しました"
fi

# プログラムを実行
echo "プログラムを起動します..."
python3 "$PROJECT_ROOT/main.py"

