.PHONY: up down logs clean help lint format test test-pre-push build-ingestion publish-local typecheck build-hook test-hook

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  up               Start Docker containers"
	@echo "  down             Stop Docker containers"
	@echo "  lint             Run linting checks (ruff + pyright)"
	@echo "  typecheck        Run pyright type checks across all packages"
	@echo "  format           Run formatting (ruff)"
	@echo "  test             Run unit tests (pytest)"
	@echo "  clean            Remove Docker volumes and cached files"
	@echo "  build-ingestion  Build clew-ingestion wheel + sdist"
	@echo "  publish-local    Build and upload to local private-pypi (localhost:9090)"

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

lint:
	uv run ruff check .
	$(MAKE) typecheck

typecheck:
	@echo "🔍 Pyright: clew-core (strict)"
	cd packages/clew-core && uv run pyright || exit 1
	@echo "🔍 Pyright: clew-ingestion (standard)"
	cd packages/clew-ingestion && uv run pyright || exit 1

format:
	uv run ruff format .

test:
	@echo "📦 Testing: clewso (root + server + mcp)"
	uv run pytest tests/ --ignore=tests/bench --ignore=tests/quality --ignore=tests/e2e || exit 1
	@echo "📦 Testing: clew-ingestion"
	cd packages/clew-ingestion && uv run pytest || exit 1
	@echo "📦 Testing: clew-core"
	cd packages/clew-core && uv run pytest || exit 1

test-pre-push:
	@echo "📦 Testing: clewso (root + server + mcp)"
	uv run pytest tests/ --ignore=tests/bench --ignore=tests/quality --ignore=tests/e2e || exit 1
	@echo "📦 Testing: clew-ingestion (unit only)"
	cd packages/clew-ingestion && uv run pytest --ignore=tests/test_embeddings.py --ignore=tests/test_ingest.py || exit 1
	@echo "📦 Testing: clew-core"
	cd packages/clew-core && uv run pytest || exit 1

clean:
	docker-compose down -v
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +

build-ingestion:
	pip3 install --quiet build
	rm -rf packages/clew-ingestion/dist
	python3 -m build packages/clew-ingestion
	@echo "Built: $$(ls packages/clew-ingestion/dist/)"

publish-local: build-ingestion
	@echo "Publishing to local pypiserver (localhost:9090)..."
	docker cp packages/clew-ingestion/dist/. clewso-private-pypi:/data/packages/
	@echo "Done. Install with:"
	@echo "  pip install clewso-ingestion"

build-hook:
	@echo "Building clew-hook binary..."
	cd cmd/clew-hook && go build -o ../../bin/clew-hook .
	@echo "Built: bin/clew-hook"

test-hook:
	@echo "📦 Testing: clew-hook (Go)"
	cd cmd/clew-hook && go test -v ./...
