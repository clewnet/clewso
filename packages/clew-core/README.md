# clew-core

Core shared utilities for the Clew AI Engine ecosystem.

## Components

### Embeddings
The `clew_core.embeddings` module provides a consolidated, robust implementation of embedding generation services used across the Clew ecosystem (`clew-api`, `clew-ingestion`, etc).

Providers available:
- `OpenAIEmbeddings`: Fully async embeddings using the `openai` Python SDK. Automatically batches inputs up to 2,048 items.
- `OllamaEmbeddings`: Fast, locally hosted embeddings using the `httpx` async client. Supports concurrent batch execution.
- `HashEmbeddings`: Deterministic hash-based pseudo-embeddings. **Not suitable for production**, but fast and useful for testing.

The `get_embedding_provider()` factory automatically returns the appropriate provider based on the environment variables defined below.

## Configuration (Environment Variables)

`clew-core` is deliberately lightweight and avoids dependencies on specific configuration management libraries (like `pydantic-settings`). 

**All configuration is read directly from process environment variables via `os.getenv()`.**

If your application uses `.env` files (e.g. via `python-dotenv` or Pydantic's `BaseSettings`), ensure that the values are actually injected into the `os` environment, not just read internally by the configuration library, otherwise `clew-core` will not be able to see them.

### Variables

| Variable | Default | Used By | Description |
|----------|---------|---------|-------------|
| `OPENAI_API_KEY` | None | `OpenAIEmbeddings` | Automatically selects the OpenAI provider if present. |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-large` | `OpenAIEmbeddings` | The name of the model to use. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | `OllamaEmbeddings` | The Ollama server URL. Selects Ollama provider if OPENAI_API_KEY is not set. |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | `OllamaEmbeddings` | Name of the Ollama model. |
| `OLLAMA_TIMEOUT` | `10.0` | `OllamaEmbeddings` | Request timeout in seconds. |
| `EMBEDDING_DIMENSION` | `1536` | All | Used by OpenAI to truncate outputs. Serves as the fallback for Ollama and the exact dimension for HashEmbeddings. |

*(Note: If `EMBEDDING_DIMENSION` is changed at runtime **after** `clew-core.embeddings` has been imported, `HashEmbeddings` will not automatically pick up the new value due to its use in a default argument. You must either set it before import, or pass it explicitly to the constructor).*
