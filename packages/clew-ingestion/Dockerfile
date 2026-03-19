FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
# git is needed for gitpython
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Install python dependencies
# tree-sitter-language-pack provides pre-built grammars for 165+ languages
RUN pip install --no-cache-dir \
    clewso-core \
    "qdrant-client>=1.7.0" \
    neo4j \
    gitpython \
    "tree-sitter>=0.22,<1.0" \
    "tree-sitter-language-pack>=0.6" \
    openai \
    pydantic \
    tenacity

# Copy source code
COPY ./src /app/src

# Set python path to allow imports from /app
ENV PYTHONPATH=/app

# Default command (overridden by docker run)
CMD ["python", "-m", "src.ingest"]
