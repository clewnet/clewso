# Context Ingestion Worker

Background worker for processing code repositories.

**Tech Stack:**
*   Python 3.11+
*   Arcade (Graph Library) or NetworkX
*   Tree-Sitter (AST Parsing)

**Responsibilities:**
*   Cloning Repos
*   Parsing ASTs to find functions/classes
*   Sending vectors to Qdrant
*   Writing nodes to Neo4j
