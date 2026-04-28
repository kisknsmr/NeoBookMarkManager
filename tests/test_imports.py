#!/usr/bin/env python3
"""
依存関係のインポートテストスクリプト
すべてのモジュールが正常にインポートできるか確認します
"""

import sys
import os
import pytest

# プロジェクトルートをパスに追加（tests/から親ディレクトリへ）
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# テストケース定義
TEST_CASES = [
    ("core.util_core", "from core.util_core import logger, is_valid_url, LRUCache"),
    ("core.ServiceStorage", "from core.ServiceStorage import ConfigManager, load_bookmarks, save_bookmarks"),
    ("core.ModelBookmark", "from core.ModelBookmark import Node, NetscapeBookmarkParser"),
    ("services.WorkerNetwork", "from services.WorkerNetwork import fetch_preview, fix_titles"),
    ("gui.ui_dialogs", "from gui.ui_dialogs import CustomPromptDialog"),
    ("gui.ui_components", "from gui.ui_components import BookmarkCard"),
    ("gui.UtilGuiResources", "from gui.UtilGuiResources import Typography, WindowSize"),
]

@pytest.mark.parametrize("module_name,import_statement", TEST_CASES)
def test_import(module_name, import_statement):
    """モジュールのインポートをテストする"""
    try:
        exec(import_statement)
        return True
    except ImportError as e:
        pytest.fail(f"[NG] {module_name}: インポートエラー - {e}")
    except Exception as e:
        pytest.fail(f"[NG] {module_name}: エラー - {e}")

