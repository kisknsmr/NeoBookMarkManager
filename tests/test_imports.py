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
    ("core.logger", "from core.logger import logger"),
    ("core.storage", "from core.storage import ConfigManager, load_bookmarks, save_bookmarks"),
    ("core.model", "from core.model import Node, NetscapeBookmarkParser"),
    ("core.utils", "from core.utils import is_valid_url, LRUCache"),
    ("services.workers", "from services.workers import fetch_preview, fix_titles"),
    ("gui.dialogs", "from gui.dialogs import CustomPromptDialog"),
    ("gui.components", "from gui.components import BookmarkCard"),
    ("gui.theme", "from gui.theme import Colors, Fonts"),
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

