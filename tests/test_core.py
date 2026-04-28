import os
import pytest
from core.ServiceStorage import ConfigManager, load_bookmarks, save_bookmarks
from core.util_core import logger

class TestConfigManager:
    def test_load_config(self, mock_config_ini):
        config_manager = ConfigManager(mock_config_ini)
        assert config_manager.config.has_section("API")
        assert config_manager.get_api_key() == "DEFAULT_TEST_KEY"

    def test_api_key_env_priority(self, mock_config_ini, monkeypatch):
        monkeypatch.setenv("GENAI_API_KEY", "ENV_KEY")
        config_manager = ConfigManager(mock_config_ini)
        assert config_manager.get_api_key() == "ENV_KEY"

    def test_proxy_validation_invalid(self, mock_config_ini):
        cm = ConfigManager(mock_config_ini)
        assert cm._validate_proxy_url("ftp://example.com") is False
        assert cm._validate_proxy_url("not_a_url") is False

    def test_proxy_validation_valid(self, mock_config_ini):
        cm = ConfigManager(mock_config_ini)
        assert cm._validate_proxy_url("http://proxy.example.com:8080") is True

class TestStorage:
    def test_load_bookmarks_valid(self, mock_bookmarks_file):
        root, rules, rules_path = load_bookmarks(mock_bookmarks_file)
        assert root is not None
        # Verify root has children (H1 Bookmarks Menu -> DL -> ...)
        # Note: Exact structure depends on parser implementation, checking basic existence
        assert len(root.children) > 0

    def test_load_bookmarks_not_found(self):
        with pytest.raises(IOError):
            load_bookmarks("non_existent_file.html")

    def test_save_bookmarks(self, mock_bookmarks_file, tmp_path):
        root, _, _ = load_bookmarks(mock_bookmarks_file)
        save_path = tmp_path / "saved_bookmarks.html"
        save_bookmarks(str(save_path), root)
        assert os.path.exists(save_path)
        
        # Verify content is not empty
        assert os.path.getsize(save_path) > 0

class TestLogger:
    def test_logger_exists(self):
        assert logger is not None
        # Basic smoke test to ensure log calls don't crash
        logger.info("Test log message")
