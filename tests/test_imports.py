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
    ("core.UtilLogger", "from core.UtilLogger import logger"),
    ("core.ServiceStorage", "from core.ServiceStorage import ConfigManager, load_bookmarks, save_bookmarks"),
    ("core.ModelBookmark", "from core.ModelBookmark import Node, NetscapeBookmarkParser"),
    ("core.UtilCoreUtils", "from core.UtilCoreUtils import is_valid_url, LRUCache"),
    ("services.WorkerNetwork", "from services.WorkerNetwork import fetch_preview, fix_titles"),
    ("gui.layout.LayoutDialogs", "from gui.layout.LayoutDialogs import CustomPromptDialog"),
    ("gui.layout.LayoutComponents", "from gui.layout.LayoutComponents import BookmarkCard"),
    ("gui.UtilTheme", "from gui.UtilTheme import Colors, Fonts"),
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

