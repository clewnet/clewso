"""
Response Formatters (Presentation Layer)

Separates data retrieval from presentation.
Each formatter knows how to render specific data types into user-friendly output.

This follows the Presenter pattern, keeping formatting logic
out of the tool/service layer.
"""


class GraphFormatter:
    """
    Formats graph data for human consumption.

    Handles:
    - Mermaid diagram generation
    - Relationship parsing (incoming/outgoing)
    - Node visualization
    """

    @staticmethod
    def format_graph_context(graph: dict, focus_node_id: str) -> tuple[list[dict], list[dict]]:
        """
        Parse graph into incoming and outgoing relationship lists.

        Args:
            graph: Graph data with nodes and edges
            focus_node_id: The node we're analyzing

        Returns:
            Tuple of (incoming_relationships, outgoing_relationships)
        """
        incoming = []
        outgoing = []

        # Build node name lookup
        node_map = {n["id"]: n.get("name", n.get("label", n["id"])) for n in graph.get("nodes", [])}

        # Parse edges
        for edge in graph.get("edges", []):
            source = edge["source"]
            target = edge["target"]
            rel_type = edge["type"]

            source_name = node_map.get(source, source)
            target_name = node_map.get(target, target)

            if source == focus_node_id:
                # Outgoing: This node → target
                outgoing.append({"target": target_name, "type": rel_type})
            elif target == focus_node_id:
                # Incoming: source → this node
                incoming.append({"source": source_name, "type": rel_type})

        return incoming, outgoing

    @staticmethod
    def build_mermaid_diagram(graph: dict, focus_node_id: str) -> str:
        """
        Generate a Mermaid TD (top-down) graph diagram.

        Args:
            graph: Graph data with nodes and edges
            focus_node_id: Highlight this node

        Returns:
            Mermaid markdown diagram
        """
        lines = ["```mermaid", "graph TD"]

        def clean_id(node_id: str) -> str:
            """Remove non-alphanumeric characters for Mermaid IDs."""
            return "".join(c for c in str(node_id) if c.isalnum())

        # Add nodes
        for node in graph.get("nodes", []):
            node_id = clean_id(node["id"])
            label = node.get("name", node.get("label", node["id"])).replace('"', "'")

            if node["id"] == focus_node_id:
                # Highlight the focus node
                lines.append(f'    {node_id}["{label}"]:::current')
            else:
                lines.append(f'    {node_id}["{label}"]')

        # Add styling for current node
        lines.append("    classDef current fill:#f9f,stroke:#333,stroke-width:2px;")

        # Add edges
        for edge in graph.get("edges", []):
            source_id = clean_id(edge["source"])
            target_id = clean_id(edge["target"])
            rel_type = edge["type"]
            lines.append(f"    {source_id} -->|{rel_type}| {target_id}")

        lines.append("```")
        return "\n".join(lines)


class SearchResultFormatter:
    """
    Formats search results with context.

    Combines search matches with graph context to provide
    comprehensive understanding of where code is used.
    """

    @staticmethod
    def format_search_results(results: list[dict], context_data: list[tuple[dict, dict]]) -> str:
        """
        Format search results with graph context.

        Args:
            results: List of search result items
            context_data: List of (result, graph) tuples with context for top results

        Returns:
            Formatted markdown output
        """
        if not results:
            return "No results found."

        lines = [f"Found {len(results)} matching items. Exploring context for top {len(context_data)}:\n"]

        for i, (result, graph) in enumerate(context_data):
            metadata = result.get("metadata", {})
            path = metadata.get("path", "unknown")
            score = result.get("score", 0.0)
            node_id = result.get("id", "unknown")
            text = result.get("text", "")

            lines.append(f"--- MATCH {i + 1}: {node_id} (Score: {score:.2f}) ---")
            lines.append(f"File: {path}")
            lines.append(f"Snippet:\n{text[:300]}...\n")

            # Add context if available
            if graph:
                incoming, outgoing = GraphFormatter.format_graph_context(graph, node_id)

                if incoming:
                    lines.append("Used By:")
                    lines.extend([f"- {rel['source']} -> {rel['type']}" for rel in incoming])

                if outgoing:
                    lines.append("Relies On:")
                    lines.extend([f"- {rel['type']} -> {rel['target']}" for rel in outgoing])

            lines.append("\n")

        return "\n".join(lines)


class ModuleAnalysisFormatter:
    """
    Formats module/file analysis output.

    Presents:
    - What the module defines
    - What it depends on
    - What uses it
    - Visual diagram
    """

    @staticmethod
    def format_module_analysis(path: str, graph: dict, node_id: str) -> str:
        """
        Format module analysis with relationships and diagram.

        Args:
            path: File path being analyzed
            graph: Graph data
            node_id: The module's node ID

        Returns:
            Formatted analysis output
        """
        lines = [f"Module Analysis: {path}\n"]

        # Generate Mermaid diagram (shown first for visibility)
        mermaid = GraphFormatter.build_mermaid_diagram(graph, node_id)
        lines.append(mermaid)
        lines.append("\n")

        # Parse relationships
        incoming, outgoing = GraphFormatter.format_graph_context(graph, node_id)

        # Extract different relationship types
        defined = [rel["target"] for rel in outgoing if rel["type"] == "DEFINES"]
        imports = [rel["target"] for rel in outgoing if rel["type"] == "IMPORTS"]
        users = [f"{rel['source']} ({rel['type']})" for rel in incoming]

        # Format sections
        if defined:
            lines.append("DEFINES:")
            lines.extend([f"- {item}" for item in defined])
            lines.append("")

        if imports:
            lines.append("DEPENDENCIES (Imports):")
            lines.extend([f"- {item}" for item in imports])
            lines.append("")

        if users:
            lines.append("USAGE (Used By):")
            lines.extend([f"- {user}" for user in users])
            lines.append("")

        if not (defined or imports or users):
            lines.append("No relationships found (isolated module).")

        return "\n".join(lines)


class VerificationFormatter:
    """
    Formats concept verification results.

    Simple formatter for verification tool output.
    """

    @staticmethod
    def format_verification(concept: str, results: list[dict]) -> str:
        """
        Format verification results.

        Args:
            concept: The concept being verified
            results: Search results proving existence

        Returns:
            Verification message
        """
        if not results:
            return f"VERIFICATION FAILED: concept '{concept}' does NOT exist in the codebase."

        lines = [f"VERIFICATION SUCCESS: '{concept}' found in {len(results)} locations.\n"]

        for result in results:
            path = result.get("metadata", {}).get("path", "unknown")
            score = result.get("score", 0.0)
            lines.append(f"- {path} (Score: {score:.2f})")

        return "\n".join(lines)
