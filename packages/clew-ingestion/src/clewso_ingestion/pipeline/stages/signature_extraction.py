"""
Signature Extraction Stage (Async)

Extracts structural signatures (Exports/Imports) from parsed AST nodes for Cross-Repo Linking.
Strictly adheres to the Data Boundary: NO Source Code is emitted.
"""

import logging
import math
from typing import Any

from ..context import IngestionContext, ParsedNode, ProcessingResult, ProcessingStatus
from ..platform_client import PlatformClient

logger = logging.getLogger(__name__)


class SignatureExtractionStage:
    """
    Fourth stage: Extract signatures from parsed nodes.

    Implements the AsyncPipelineStage protocol.

    Responsibilities:
    - Filter parsed nodes for exports (classes, functions, variables)
    - Identify imports (if available in AST - dependent on language support)
    - Construct 'Signature' objects strictly containing metadata
    - Send signatures to the Platform (via context hook or direct API call)
    """

    name = "SignatureExtraction"

    async def execute(self, context: IngestionContext) -> ProcessingResult:
        """
        Extract signatures from all parsed nodes in the context.

        Args:
            context: Ingestion context populated with .nodes from ParsingStage

        Returns:
            ProcessingResult with extraction statistics
        """
        logger.info(f"[{self.name}] Extracting signatures from {len(context.nodes)} nodes")

        exports: list[dict[str, Any]] = []
        imports: list[dict[str, Any]] = []

        try:
            for node in context.nodes:
                if self._is_export(node):
                    signature = self._create_export_signature(node, context.repo_id)
                    exports.append(signature)
                elif node.type == "import":
                    # Capture imports extracted by the parser
                    signature = self._create_import_signature(node, context.repo_id)
                    imports.append(signature)

            if exports or imports:
                platform_url = context.config.get("platform_url")
                api_key = context.config.get("api_key")

                if platform_url and api_key:
                    try:
                        client = PlatformClient(platform_url, api_key)
                        try:
                            # Batching logic
                            batch_size = 1000
                            total_items = max(len(exports), len(imports))
                            num_batches = math.ceil(total_items / batch_size)

                            total_links = 0
                            all_edges = []

                            for i in range(num_batches):
                                start = i * batch_size
                                end = start + batch_size
                                batch_exports = exports[start:end]
                                batch_imports = imports[start:end]

                                result = await client.send_signatures(
                                    repo_id=context.repo_id,
                                    commit_hash=context.config.get("commit_hash", "HEAD"),
                                    exports=batch_exports,
                                    imports=batch_imports,
                                )

                                links_found = result.get("links_found", 0)
                                total_links += links_found
                                if "external_edges" in result:
                                    all_edges.extend(result["external_edges"])

                            logger.info(f"[{self.name}] Platform found {total_links} cross-repo links")
                            context.metadata["cross_repo_links"] = all_edges

                        finally:
                            await client.close()
                    except Exception as e:
                        logger.warning(f"[{self.name}] Failed to send signatures to platform: {e}")

            # For debug/validation we still store them in metadata
            context.metadata["signatures"] = {"exports": exports, "imports": imports}

            logger.info(f"[{self.name}] Extracted {len(exports)} export signatures, {len(imports)} import signatures")

        except Exception as e:
            logger.error(f"[{self.name}] Extraction failed: {e}")
            return ProcessingResult(
                status=ProcessingStatus.FAILED,
                message=str(e),
                items_failed=len(context.nodes),
                errors=[{"context": "global_extraction", "error": str(e)}],
            )

        return ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            message=f"Extracted {len(exports)} signatures",
            items_processed=len(exports),
            metadata={"export_count": len(exports), "import_count": len(imports)},
        )

    def _is_export(self, node: ParsedNode) -> bool:
        """
        Determine if a node represents an exported symbol.

        Refines the raw tree-sitter 'type' mapping and uses scope metadata
        when available to filter out non top-level symbols.

        Note:
            - This method is intentionally conservative when scope information
              is present: if metadata indicates a non-module / non-top-level
              scope, the symbol is *not* treated as an export.
            - When no scope metadata is available on the node, we fall back
              to a simple type-based heuristic and may over-approximate
              exports (nested symbols can be misclassified).
        """
        # First, ensure the node is of an exportable syntactic type.
        is_export_type = node.type in {"class", "function", "variable"}
        if not is_export_type:
            return False

        # Prefer scope information when it is available on the node.
        metadata = getattr(node, "metadata", None)
        if isinstance(metadata, dict):
            # Explicit flag for top-levelness takes precedence if provided.
            is_top_level = metadata.get("is_top_level")
            if is_top_level is False:
                return False

            # Generic scope descriptors (e.g., "module", "class", "function").
            scope = metadata.get("scope") or metadata.get("scope_type")
            if scope is not None and scope not in {"module", "global", "top_level"}:
                # Known to be nested inside a non-module scope.
                return False

        # Some parsers may expose a coarse-grained "kind" field on the node.
        # This check is too restrictive for tree-sitter types (e.g. 'function_definition')
        # kind = getattr(node, "kind", None)
        # if kind is not None and kind not in {"module", "top_level", "declaration"}:
        #     return False

        # Fallback: treat the node as an export based solely on its type.
        return True

    def _create_export_signature(self, node: ParsedNode, repo_id: str) -> dict[str, Any]:
        """
        Create a sanitized signature object.
        NO CONTENT allowed.
        """
        # Unique Symbol Path construction
        # Format: file_path:symbol_name
        usp = f"{node.file_path}:{node.name}"

        return {
            # WARNING: node.content MUST NEVER BE INCLUDED.
            # Source code is strictly forbidden in signatures per Data Boundary.
            "file_path": node.file_path,
            "symbol_name": node.name,
            "symbol_type": node.type,
            "usp": usp,
            "line_no": node.start_line,
        }

    def _create_import_signature(self, node: ParsedNode, repo_id: str) -> dict[str, Any]:
        """
        Create a sanitized import signature object.
        """
        return {
            "file_path": node.file_path,
            "source_module": node.name,  # The parser logic puts the imported module/name in 'name'
            "line_no": node.start_line,
        }
