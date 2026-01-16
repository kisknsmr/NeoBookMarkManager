import queue
import pytest
from unittest.mock import MagicMock, patch
from services.WorkerNetwork import _extract_title_and_description, fetch_preview

class TestWorkers:
    def test_extract_info_normal(self):
        html = """
        <html>
            <head>
                <title>Test Page</title>
                <meta name="description" content="This is a test description.">
            </head>
            <body></body>
        </html>
        """
        res = _extract_title_and_description(html)
        assert res["title"] == "Test Page"
        assert res["description"] == "This is a test description."

    def test_extract_info_og(self):
        html = """
        <html>
            <head>
                <meta property="og:title" content="OG Title">
                <meta property="og:description" content="OG Description">
                <title>Ignored Title</title>
            </head>
            <body></body>
        </html>
        """
        res = _extract_title_and_description(html)
        assert res["title"] == "OG Title"
        assert res["description"] == "OG Description"

    @patch('services.WorkerNetwork.requests.get')
    def test_fetch_preview_success(self, mock_get):
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><title>Success</title></html>"
        mock_get.return_value = mock_response

        q = queue.Queue()
        fetch_preview("http://example.com", q)

        # Check queue for result
        msg_type, data = q.get()
        assert msg_type == 'preview'
        url, info = data
        assert url == "http://example.com"
        assert info["title"] == "Success"

    @patch('services.WorkerNetwork.requests.get')
    def test_fetch_preview_404(self, mock_get):
        # Mock 404 response
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = Exception("404 Error") # requests.exceptions.HTTPError usually
        # Simulating raise_for_status behavior manually for simple mock
        from requests.exceptions import HTTPError
        error = HTTPError(response=mock_response)
        mock_get.side_effect = error

        q = queue.Queue()
        fetch_preview("http://example.com/404", q)

        msg_type, data = q.get()
        assert msg_type == 'preview'
        url, info = data
        # Modified workers.py returns "Not Found (404)" for 404 errors
        assert "Not Found (404)" in info["title"]
