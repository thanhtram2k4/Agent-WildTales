# tests/test_mcp_server.py — MCP server tool handler tests
"""
Tests for MCP tool handlers (unit-level, no actual MCP transport).
Verifies URL validation, tool routing, and response formatting.
"""
import json
import pytest
from unittest.mock import patch, MagicMock


class TestMcpToolDefinitions:
    """Verify tool definitions are correctly structured."""

    def test_tools_list_has_three_tools(self):
        from mcp_server import TOOLS
        assert len(TOOLS) == 3

    def test_tool_names(self):
        from mcp_server import TOOLS
        names = {t.name for t in TOOLS}
        assert names == {"ingest_url", "search_knowledge", "get_wildcats_events"}

    def test_all_tools_have_descriptions(self):
        from mcp_server import TOOLS
        for tool in TOOLS:
            assert tool.description and len(tool.description) > 10

    def test_all_tools_have_input_schema(self):
        from mcp_server import TOOLS
        for tool in TOOLS:
            assert tool.input_schema is not None
            assert tool.input_schema["type"] == "object"


class TestIngestUrlHandler:
    """Tests for the ingest_url tool handler."""

    def test_rejects_private_ip(self):
        from mcp_server import handle_ingest_url
        result = json.loads(handle_ingest_url({"url": "http://127.0.0.1/secret", "user_id": "u1"}))
        assert result["status"] == "error"
        assert "blocked" in result["detail"].lower() or "invalid" in result["detail"].lower()

    def test_rejects_file_scheme(self):
        from mcp_server import handle_ingest_url
        result = json.loads(handle_ingest_url({"url": "file:///etc/passwd", "user_id": "u1"}))
        assert result["status"] == "error"

    def test_rejects_ftp_scheme(self):
        from mcp_server import handle_ingest_url
        result = json.loads(handle_ingest_url({"url": "ftp://evil.com/data", "user_id": "u1"}))
        assert result["status"] == "error"

    @patch("mcp_server._call_backend")
    def test_valid_url_calls_backend(self, mock_backend):
        from mcp_server import handle_ingest_url
        mock_backend.return_value = {"status": "success", "stored_chunks": 3}

        result = json.loads(handle_ingest_url({
            "url": "https://example.com/article",
            "user_id": "u1",
            "user_name": "Test",
        }))

        mock_backend.assert_called_once()
        assert result["status"] == "success"


class TestSearchKnowledgeHandler:
    """Tests for the search_knowledge tool handler."""

    def test_rejects_empty_query(self):
        from mcp_server import handle_search_knowledge
        result = json.loads(handle_search_knowledge({"query": ""}))
        assert "error" in result

    @patch("mcp_server._call_backend")
    def test_valid_query_calls_backend(self, mock_backend):
        from mcp_server import handle_search_knowledge
        mock_backend.return_value = {"results": [{"document": "test", "distance": 0.1}]}

        result = json.loads(handle_search_knowledge({"query": "AI concepts"}))

        mock_backend.assert_called_once_with("POST", "/api/knowledge/search", {
            "query": "AI concepts",
            "n_results": 5,
            "source_type": "",
        })
        assert len(result["results"]) == 1


class TestGetWildcatsEventsHandler:
    """Tests for the get_wildcats_events tool handler."""

    @patch("mcp_server._call_backend")
    def test_calls_events_endpoint(self, mock_backend):
        from mcp_server import handle_get_wildcats_events
        mock_backend.return_value = {"events": [{"title": "Hackathon"}]}

        result = json.loads(handle_get_wildcats_events({}))

        mock_backend.assert_called_once_with("GET", "/api/events")
        assert len(result["events"]) == 1


class TestToolRouting:
    """Tests that TOOL_HANDLERS routes correctly."""

    def test_all_tools_have_handlers(self):
        from mcp_server import TOOLS, TOOL_HANDLERS
        for tool in TOOLS:
            assert tool.name in TOOL_HANDLERS, f"No handler for tool: {tool.name}"
