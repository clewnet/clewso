FROM python:3.11-slim

LABEL org.opencontainers.image.source=https://github.com/clewnet/clewso
LABEL org.opencontainers.image.description="Clewso - Context Engine for AI Agents"
LABEL org.opencontainers.image.licenses=AGPL-3.0-only

WORKDIR /app

# Install clew
COPY pyproject.toml .
COPY src/ src/

ARG PIP_EXTRA_INDEX_URL
ENV PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}
RUN pip install --no-cache-dir ".[all]"

# Default to help
ENTRYPOINT ["clewso"]
CMD ["--help"]
