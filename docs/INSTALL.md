# インストール手順

## 必要なシステムパッケージのインストール

以下のコマンドを実行して、必要なシステムパッケージをインストールしてください：

```bash
sudo apt-get update
sudo apt-get install -y python3-tk python3-pip
```

## Pythonパッケージのインストール

システムパッケージのインストールが完了したら、以下のコマンドでPythonパッケージをインストールします：

```bash
cd /home/kei/PythonProject/NeoBookMarkManager
python3 -m pip install -r requirements.txt
```

または、ユーザー環境にインストールする場合：

```bash
python3 -m pip install --user -r requirements.txt
```

## インストール確認

インストールが完了したら、以下のコマンドで確認できます：

```bash
python3 -c "import tkinter; print('✓ tkinter: OK')"
python3 -c "import google.generativeai; print('✓ google-generativeai: OK')"
python3 -c "import requests; print('✓ requests: OK')"
python3 -c "from bs4 import BeautifulSoup; print('✓ beautifulsoup4: OK')"
```

## 実行テスト

すべての依存関係がインストールされたら、以下のコマンドでプログラムを実行できます：

```bash
python3 main.py
```

