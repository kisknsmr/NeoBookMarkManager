#!/bin/bash
# 依存関係インストールスクリプト（仮想環境を使用）

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "=========================================="
echo "依存関係のインストールを開始します"
echo "=========================================="
echo ""

# システムパッケージのインストール
echo "1. システムパッケージ（python3-tk, python3-pip）のインストール..."
sudo apt-get update -qq
sudo apt-get install -y python3-tk python3-pip python3-venv

echo ""
echo "2. 仮想環境の作成/確認..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "✅ 仮想環境を作成しました"
else
    echo "✅ 仮想環境は既に存在します"
fi

echo ""
echo "3. 仮想環境を有効化してPythonパッケージのインストール..."
cd "$SCRIPT_DIR"
source "$VENV_DIR/bin/activate"
python3 -m pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "=========================================="
echo "インストール完了！"
echo "=========================================="
echo ""
echo "インストール確認を実行します..."
echo ""

# インストール確認
python3 -c "import tkinter; print('✓ tkinter: OK')" || echo "✗ tkinter: エラー"
python3 -c "import google.generativeai; print('✓ google-generativeai: OK')" || echo "✗ google-generativeai: エラー"
python3 -c "import requests; print('✓ requests: OK')" || echo "✗ requests: エラー"
python3 -c "from bs4 import BeautifulSoup; print('✓ beautifulsoup4: OK')" || echo "✗ beautifulsoup4: エラー"

echo ""
echo "すべての確認が完了しました。"
