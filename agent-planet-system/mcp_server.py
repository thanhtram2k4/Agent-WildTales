# mcp_server.py — WildTails MCP Server
"""
Lightweight MCP server exposing WildTails tools over stdio transport.
Routes to internal FastAPI services — no business logic duplication.

Tools:
  - ingest_url: Ingest a public URL into the knowledge base
  - search_knowledge: Semantic search over ingested knowledge
  - get_wildcats_events: List upcoming Wildcats community events

Usage:
  python mcp_server.py
"""
import asyncio
import json
import logging
import os

import requests
from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp import stdio_server

from mcp_tools import validate_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wildtails.mcp_server")

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
REQUEST_TIMEOUT = 30

# --- Tool definitions ---

TOOLS = [
    types.Tool(
        name="ingest_url",
        description="Ingest a public URL (article or YouTube video) into the WildTails knowledge base. "
                    "Extracts text, chunks it, and stores embeddings for later retrieval.",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The public URL to ingest (http/https only, no local/private IPs)",
                },
                "user_id": {
                    "type": "string",
                    "description": "ID of the user requesting ingestion",
                },
                "user_name": {
                    "type": "string",
                    "description": "Display name of the user",
                    "default": "anonymous",
                },
            },
            "required": ["url", "user_id"],
        },
    ),
    types.Tool(
        name="search_knowledge",
        description="Semantic search over the WildTails knowledge base. "
                    "Returns the most relevant chunks matching the query.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query",
                },
                "n_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": 5,
                },
                "source_type": {
                    "type": "string",
                    "description": "Filter by source type: 'article', 'youtube_transcript', or empty for all",
                    "default": "",
                },
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="get_wildcats_events",
        description="List upcoming Wildcats community events. "
                    "Returns event titles, dates, locations, and links.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
]


# --- Tool handlers ---

def _call_backend(method: str, path: str, json_body: dict | None = None) -> dict:
    """Make an HTTP request to the FastAPI backend."""
    url = f"{BACKEND_URL}{path}"
    try:
        if method == "GET":
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        else:
            resp = requests.post(url, json=json_body or {}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def handle_ingest_url(arguments: dict) -> str:
    """Handle ingest_url tool call with SSRF-safe validation."""
    url = arguments.get("url", "")

    # Strict URL validation before forwarding to backend
    if not validate_url(url):
        return json.dumps({
            "status": "error",
            "detail": "Invalid or blocked URL. Only public http/https URLs are allowed (no local/private IPs).",
        })

    result = _call_backend("POST", "/api/knowledge/ingest", {
        "url": url,
        "user_id": arguments.get("user_id", "mcp_user"),
        "user_name": arguments.get("user_name", "anonymous"),
    })
    return json.dumps(result, ensure_ascii=False)


def handle_search_knowledge(arguments: dict) -> str:
    """Handle search_knowledge tool call."""
    query = arguments.get("query", "")
    if not query:
        return json.dumps({"error": "Query is required"})

    result = _call_backend("POST", "/api/knowledge/search", {
        "query": query,
        "n_results": arguments.get("n_results", 5),
        "source_type": arguments.get("source_type", ""),
    })
    return json.dumps(result, ensure_ascii=False)


def handle_get_wildcats_events(arguments: dict) -> str:
    """Handle get_wildcats_events tool call."""
    result = _call_backend("GET", "/api/events")
    return json.dumps(result, ensure_ascii=False)


TOOL_HANDLERS = {
    "ingest_url": handle_ingest_url,
    "search_knowledge": handle_search_knowledge,
    "get_wildcats_events": handle_get_wildcats_events,
}


# --- MCP Server setup ---

async def _on_list_tools(ctx: ServerRequestContext, params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=TOOLS)


async def _on_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    tool_name = params.name
    arguments = params.arguments or {}

    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Unknown tool: {tool_name}")],
            is_error=True,
        )

    try:
        result_text = handler(arguments)
    except Exception as e:
        logger.error("Tool %s failed: %s", tool_name, e)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Tool error: {e}")],
            is_error=True,
        )

    return types.CallToolResult(
        content=[types.TextContent(type="text", text=result_text)],
    )


server = Server(
    name="wildtails-mcp",
    version="1.0.0",
    description="WildTails knowledge & events MCP server",
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    asyncio.run(main())
