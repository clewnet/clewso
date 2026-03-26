import logging
import os
from typing import Any

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)


class GraphStore:
    def __init__(
        self,
        *,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = user or os.getenv("NEO4J_USER", "neo4j")
        password = password or os.getenv("NEO4J_PASSWORD", "password")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self._ensure_schema()

    def close(self):
        self.driver.close()

    def _ensure_schema(self):
        """
        Ensure Neo4j schema constraints and indexes exist.

        This method is called on initialization to guarantee that the database
        has the required schema for multi-repo support. All operations are
        idempotent using IF NOT EXISTS.

        Constraints:
        - file_repo_path_unique: Ensures (repo_id, path) uniqueness for Files
        - codeblock_unique: Ensures (repo_id, file_path, name) uniqueness for CodeBlocks

        Indexes:
        - file_repo_id: Speeds up repo_id filtering on Files
        - codeblock_repo_id: Speeds up repo_id filtering on CodeBlocks
        - module_repo_id: Speeds up repo_id filtering on Modules
        - function_repo_id: Speeds up repo_id filtering on Functions
        """
        logger.info("Applying Neo4j schema migrations...")

        with self.driver.session() as session:
            try:
                # Constraint 1: File uniqueness on (repo_id, path)
                session.run("""
                    CREATE CONSTRAINT file_repo_path_unique IF NOT EXISTS
                    FOR (f:File) REQUIRE (f.repo_id, f.path) IS UNIQUE
                """)
                logger.debug("Created constraint: file_repo_path_unique")

                # Constraint 2: CodeBlock uniqueness on (repo_id, file_path, name, type)
                # Migration: drop the old 3-property constraint if it exists
                try:
                    session.run("DROP CONSTRAINT codeblock_unique IF EXISTS")
                except Exception:
                    pass  # Already dropped or never existed
                session.run("""
                    CREATE CONSTRAINT codeblock_unique_v2 IF NOT EXISTS
                    FOR (c:CodeBlock) REQUIRE (c.repo_id, c.file_path, c.name, c.type) IS UNIQUE
                """)
                logger.debug("Created constraint: codeblock_unique_v2")

                # Index 1: File repo_id for filtering
                session.run("""
                    CREATE INDEX file_repo_id IF NOT EXISTS
                    FOR (f:File) ON (f.repo_id)
                """)
                logger.debug("Created index: file_repo_id")

                # Index 2: CodeBlock repo_id for filtering
                session.run("""
                    CREATE INDEX codeblock_repo_id IF NOT EXISTS
                    FOR (c:CodeBlock) ON (c.repo_id)
                """)
                logger.debug("Created index: codeblock_repo_id")

                # Index 3: Module repo_id for filtering
                session.run("""
                    CREATE INDEX module_repo_id IF NOT EXISTS
                    FOR (m:Module) ON (m.repo_id)
                """)
                logger.debug("Created index: module_repo_id")

                # Index 4: Function repo_id for filtering
                session.run("""
                    CREATE INDEX function_repo_id IF NOT EXISTS
                    FOR (f:Function) ON (f.repo_id)
                """)
                logger.debug("Created index: function_repo_id")

                logger.info("Neo4j schema migrations completed successfully")

            except Exception as e:
                logger.error(f"Failed to apply Neo4j schema migrations: {e}")
                raise

    def execute_batch(self, operations: list[tuple[str, dict]]) -> None:
        """
        Execute multiple Cypher queries in a single transaction.

        This is significantly faster than running each query in its own session,
        as it amortizes connection and transaction overhead across all operations.

        Args:
            operations: List of (cypher_query, params_dict) tuples
        """
        if not operations:
            return

        with self.driver.session() as session:
            with session.begin_transaction() as tx:
                for query, params in operations:
                    tx.run(query, **params)  # type: ignore[arg-type]
                tx.commit()

        logger.debug(f"Executed batch of {len(operations)} graph operations")

    def get_last_indexed_commit(self, repo_id: str) -> str | None:
        """Return the last_indexed_commit SHA for a repo, or None if never indexed."""
        with self.driver.session() as session:
            result = session.run(
                "MATCH (r:Repository {id: $repo_id}) RETURN r.last_indexed_commit AS sha",
                repo_id=repo_id,
            )
            record = result.single()
            return record["sha"] if record else None

    def update_last_indexed_commit(self, repo_id: str, commit_sha: str) -> None:
        """Store the commit SHA that was just indexed."""
        with self.driver.session() as session:
            session.run(
                "MATCH (r:Repository {id: $repo_id}) SET r.last_indexed_commit = $sha",
                repo_id=repo_id,
                sha=commit_sha,
            )

    def create_repo_node(self, repo_id: str, name: str, url: str):
        with self.driver.session() as session:
            session.run(
                "MERGE (r:Repository {id: $repo_id}) SET r.name = $name, r.url = $url",
                repo_id=repo_id,
                url=url,
                name=name,
            )

    def create_file_node(self, repo_id: str, file_path: str, qdrant_id: str):
        with self.driver.session() as session:
            session.run(
                """
                MATCH (r:Repository {id: $repo_id})
                MERGE (f:File {path: $file_path, repo_id: $repo_id})
                SET f.qdrant_id = $qdrant_id
                MERGE (r)-[:CONTAINS]->(f)
                """,
                repo_id=repo_id,
                file_path=file_path,
                qdrant_id=qdrant_id,
            )

    def create_file_nodes_batch(self, repo_id: str, items: list[dict[str, Any]]):
        """
        Create multiple file nodes in a single batch.

        Args:
            repo_id: Repository ID
            items: List of dicts with 'file_path' and 'qdrant_id' keys
        """
        with self.driver.session() as session:
            session.run(
                """
                UNWIND $items as item
                MATCH (r:Repository {id: $repo_id})
                MERGE (f:File {path: item.file_path, repo_id: $repo_id})
                SET f.qdrant_id = item.qdrant_id
                MERGE (r)-[:CONTAINS]->(f)
                """,
                repo_id=repo_id,
                items=items,
            )

    def create_code_node(
        self,
        repo_id: str,
        file_path: str,
        name: str,
        node_type: str,
        start_line: int,
        end_line: int,
        qdrant_id: str,
    ):
        with self.driver.session() as session:
            session.run(
                """
                MATCH (f:File {repo_id: $repo_id, path: $file_path})
                MERGE (c:CodeBlock {
                    name: $name,
                    type: $node_type,
                    file_path: $file_path,
                    repo_id: $repo_id
                })
                SET c.start_line = $start_line,
                    c.end_line = $end_line,
                    c.qdrant_id = $qdrant_id
                MERGE (f)-[:DEFINES]->(c)
                """,
                repo_id=repo_id,
                file_path=file_path,
                name=name,
                node_type=node_type,
                start_line=start_line,
                end_line=end_line,
                qdrant_id=qdrant_id,
            )

    def create_import_relationship(self, repo_id: str, file_path: str, module_name: str):
        with self.driver.session() as session:
            session.run(
                """
                MATCH (f:File {repo_id: $repo_id, path: $file_path})
                MERGE (m:Module {name: $module_name, repo_id: $repo_id})
                MERGE (f)-[:IMPORTS]->(m)
                """,
                repo_id=repo_id,
                file_path=file_path,
                module_name=module_name,
            )

    def create_call_relationship(self, repo_id: str, file_path: str, target_name: str):
        with self.driver.session() as session:
            session.run(
                """
                MATCH (f:File {repo_id: $repo_id, path: $file_path})
                MERGE (t:Function {name: $target_name, repo_id: $repo_id})
                MERGE (f)-[:CALLS]->(t)
                """,
                repo_id=repo_id,
                file_path=file_path,
                target_name=target_name,
            )

    def delete_file_node(self, repo_id: str, file_path: str) -> int:
        """
        Delete a file node and all related CodeBlocks.

        Uses DETACH DELETE to remove all relationships automatically.
        This is safe for incremental sync where files are removed from the repository.

        Args:
            repo_id: Repository identifier
            file_path: Path to the file to delete

        Returns:
            Number of nodes deleted (file + related code blocks)
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (f:File {repo_id: $repo_id, path: $path})
                OPTIONAL MATCH (f)-[:DEFINES]->(c:CodeBlock)
                WITH f, collect(c) as codeblocks
                DETACH DELETE f
                FOREACH (cb in codeblocks | DETACH DELETE cb)
                RETURN 1 + size(codeblocks) as deleted_count
                """,
                repo_id=repo_id,
                path=file_path,
            )

            record = result.single()
            deleted_count = record["deleted_count"] if record else 0

            logger.info(f"Deleted file node {file_path} from repo {repo_id}: {deleted_count} nodes removed")

            return deleted_count

    def delete_file_edges(self, repo_id: str, file_path: str) -> None:
        """Delete all outgoing IMPORTS and CALLS edges from a file node.

        Used by incremental sync when a file is modified: edges are refreshed
        by deleting them here and then re-creating them after re-parsing.
        The file node itself (and its DEFINES children) is left intact.

        Args:
            repo_id: Repository identifier.
            file_path: Path to the file whose outgoing edges should be deleted.
        """
        with self.driver.session() as session:
            session.run(
                """
                MATCH (f:File {repo_id: $repo_id, path: $file_path})-[r:IMPORTS|CALLS]->()
                DELETE r
                """,
                repo_id=repo_id,
                file_path=file_path,
            )
        logger.debug(f"Deleted outgoing edges for {file_path} in repo {repo_id}")

    def delete_files_batch(self, repo_id: str, file_paths: list[str]) -> int:
        """
        Delete multiple file nodes in a batch.

        More efficient than calling delete_file_node() in a loop.

        Args:
            repo_id: Repository identifier
            file_paths: List of file paths to delete

        Returns:
            Total number of nodes deleted
        """
        if not file_paths:
            return 0

        with self.driver.session() as session:
            result = session.run(
                """
                UNWIND $paths as path
                MATCH (f:File {repo_id: $repo_id, path: path})
                OPTIONAL MATCH (f)-[:DEFINES]->(c:CodeBlock)
                WITH f, collect(c) as codeblocks
                DETACH DELETE f
                FOREACH (cb in codeblocks | DETACH DELETE cb)
                RETURN count(f) + size(collect(codeblocks)) as deleted_count
                """,
                repo_id=repo_id,
                paths=file_paths,
            )

            record = result.single()
            deleted_count = record["deleted_count"] if record else 0

            logger.info(
                f"Batch deleted {len(file_paths)} file nodes from repo {repo_id}: {deleted_count} total nodes removed"
            )

            return deleted_count


# Protocol conformance check
def _check_graph_writer_protocol() -> None:
    from clewso_core.protocols import GraphWriter

    assert isinstance(GraphStore(uri="bolt://fake", user="x", password="x"), GraphWriter)  # type: ignore[abstract]
