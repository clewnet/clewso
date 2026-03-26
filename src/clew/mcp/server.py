"""
Clew MCP Server

Refactored to follow SOLID principles and eliminate code duplication.

Architecture:
- ClewAPIClient: Reusable HTTP client (eliminates duplicated setup)
- @handle_api_errors: Decorator for consistent error handling (eliminates duplicated try/except)
- Formatters: Presentation layer (separates data from formatting)
"""

import logging

from mcp.server.fastmcp import FastMCP

from .client import ClewAPIClient
from .errors import handle_api_errors
from .formatters import (
    ModuleAnalysisFormatter,
    SearchResultFormatter,
    VerificationFormatter,
)

# Initialize FastMCP Server
mcp = FastMCP("Clew")

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clew-mcp")


@mcp.tool()
@handle_api_errors
async def list_repos() -> str:
    """
    List all repositories currently indexed in Clew.

    Returns:
        A list of repository names and their UUIDs.
    """
    async with ClewAPIClient() as client:
        repos = await client.list_repositories()
        if not repos:
            return "No repositories are currently indexed."

        lines = ["Available Repositories:"]
        for repo in repos:
            lines.append(f"- {repo['name']} (ID: {repo['id']})")
        return "\n".join(lines)


@mcp.tool()
@handle_api_errors
async def search_codebase(query: str, limit: int = 5, repo_id: str | None = None) -> str:
    """
    Search for code relevant to the query AND understand how it is used.

    Returns a synthesized summary of matching code snippets and their context.

    Args:
        query: Natural language query (e.g., "how is authentication handled?")
        limit: Number of entry points to explore (default: 5)
        repo_id: Repository UUID. If provided, search is restricted to this repo.
    """
    async with ClewAPIClient() as client:
        # 1. Search for relevant code
        results = await client.search(query, limit=limit, repo_id=repo_id)

        if not results:
            return f"No results found for query: '{query}'"

        # 2. Fetch graph context for top 3 results
        top_results = results[:3]
        context_data = []

        for result in top_results:
            node_path = result.get("metadata", {}).get("path")
            if not node_path:
                context_data.append((result, {}))
                continue
            try:
                graph = await client.traverse(
                    node_path,
                    relationship_types=["CALLS", "IMPORTS", "DEFINES", "CONTAINS"],
                )
                context_data.append((result, graph))
            except Exception as e:
                logger.warning(f"Could not fetch context for {node_path}: {e}")
                context_data.append((result, {}))

        # 3. Format and return
        return SearchResultFormatter.format_search_results(results, context_data)


@mcp.tool()
@handle_api_errors
async def explore_module(path: str, repo_id: str | None = None) -> str:
    """
    Analyze a specific module/file to understand its dependencies and API.

    Args:
        path: Relative path or filename (e.g., "src/database.py" or "User")
        repo_id: Repository UUID.
    """
    async with ClewAPIClient() as client:
        # 1. Find the module via search
        filters = {"path_contains": path}
        if repo_id:
            filters["repo_id"] = repo_id

        results = await client.search(path, limit=1, filters=filters)

        if not results:
            # Fallback without path filter
            results = await client.search(path, limit=1)

        if not results:
            return f"Could not find module matching '{path}'"

        node = results[0]
        found_path = node.get("metadata", {}).get("path", "unknown")

        if found_path == "unknown":
            return f"Could not determine file path for '{path}'"

        # 2. Traverse graph from this module
        graph = await client.traverse(found_path, relationship_types=["IMPORTS", "DEFINES", "CALLS", "CONTAINS"])

        # 3. Format and return
        return ModuleAnalysisFormatter.format_module_analysis(str(found_path), graph, found_path)


@mcp.tool()
@handle_api_errors
async def verify_concept(concept: str) -> str:
    """
    Verify if a concept, library, or pattern actually exists in the codebase.

    Use this BEFORE performing deep analysis to avoid hallucinations.

    Args:
        concept: The term to verify (e.g. "GraphQL", "Redis", "UserService")

    Returns:
        Verification result (EXISTS or DOES NOT EXIST) with evidence.
    """
    async with ClewAPIClient() as client:
        # Search for the concept
        results = await client.search(concept, limit=5)

        # Format and return
        return VerificationFormatter.format_verification(concept, results)


if __name__ == "__main__":
    mcp.run()
