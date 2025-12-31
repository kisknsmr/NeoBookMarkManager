#!/usr/bin/env python3
"""
依存関係のインポートテストスクリプト
すべてのモジュールが正常にインポートできるか確認します
"""

import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_import(module_name, import_statement):
    """モジュールのインポートをテストする"""
    try:
        exec(import_statement)
        print(f"✓ {module_name}: OK")
        return True
    except ImportError as e:
        print(f"✗ {module_name}: インポートエラー - {e}")
        return False
    except Exception as e:
        print(f"✗ {module_name}: エラー - {e}")
        return False

def main():
    print("=" * 60)
    print("依存関係のインポートテスト")
    print("=" * 60)
    print()
    
    results = []
    
    # 標準ライブラリ
    print("【標準ライブラリ】")
    results.append(test_import("tkinter", "import tkinter as tk"))
    results.append(test_import("queue", "import queue"))
    results.append(test_import("threading", "import threading"))
    print()
    
    # 外部ライブラリ
    print("【外部ライブラリ】")
    results.append(test_import("requests", "import requests"))
    results.append(test_import("beautifulsoup4", "from bs4 import BeautifulSoup"))
    results.append(test_import("google-generativeai", "import google.generativeai as genai"))
    results.append(test_import("PIL (Pillow)", "from PIL import Image"))
    results.append(test_import("ttkbootstrap", "import ttkbootstrap as tb"))
    print()
    
    # プロジェクトモジュール
    print("【プロジェクトモジュール】")
    results.append(test_import("core.storage", "from core.storage import ConfigManager"))
    results.append(test_import("core.utils", "from core.utils import AppConstants"))
    results.append(test_import("core.model", "from core.model import Node"))
    results.append(test_import("services.ai_classifier", "from services.ai_classifier import AIBookmarkClassifier"))
    results.append(test_import("services.workers", "from services.workers import fetch_preview"))
    results.append(test_import("gui.main_window", "from gui.main_window import App"))
    print()
    
    # 結果サマリー
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"結果: {passed}/{total} テストが成功しました")
    
    if passed == total:
        print("✅ すべての依存関係が正常にインストールされています！")
        return 0
    else:
        print("⚠️  一部の依存関係が不足しています。")
        print("   以下のコマンドでインストールしてください：")
        print("   ./install_dependencies.sh")
        return 1

if __name__ == "__main__":
    sys.exit(main())

