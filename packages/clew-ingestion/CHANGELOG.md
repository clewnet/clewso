# Changelog

## [0.1.8](https://github.com/matchdav/clew-engine/compare/clewso-ingestion-v0.1.7...clewso-ingestion-v0.1.8) (2026-03-26)


### Features

* **ladybug:** implement LadybugUnifiedStore integration with enhanced store configuration and testing ([89a6947](https://github.com/matchdav/clew-engine/commit/89a6947e57f9cd9ca1fa1c91f28f19aeb656e92c))
* **ladybug:** integration of embedded db ([e84898d](https://github.com/matchdav/clew-engine/commit/e84898da24c133254eaaace448370e9c7c9677cc))
* update adapters and configurations for LadybugDB integration, enhancing graph and vector adapter support ([9f6f2d1](https://github.com/matchdav/clew-engine/commit/9f6f2d17c2a33c1881184f44e2d8d2bfa6035885))


### Bug Fixes

* streamline migration command help text and improve error messaging for LadybugDB locking ([32a9e6c](https://github.com/matchdav/clew-engine/commit/32a9e6c23e1b706cae6bb263f47b984991c039d6))

## [0.1.7](https://github.com/matchdav/clew-engine/compare/clewso-ingestion-v0.1.6...clewso-ingestion-v0.1.7) (2026-03-20)


### Features

* add language registry and stdlib filter with TOML configuration ([d946ea9](https://github.com/matchdav/clew-engine/commit/d946ea9665dbc2faaed2bf13f5b43892b2280693))
* handle Ctrl-C gracefully with pending write flush ([a5c3ad0](https://github.com/matchdav/clew-engine/commit/a5c3ad07dfc790bfbabbf29b78fb4019fa730346))
* query actual Qdrant and Neo4j counts in finalization summary ([82ce860](https://github.com/matchdav/clew-engine/commit/82ce86007b8dbf9fa3e666de6a21733630796164))
* retry Qdrant upserts on transient failures ([29e1da7](https://github.com/matchdav/clew-engine/commit/29e1da74f69f4c47deabd80503dab9fcef2c6261))
* support Qdrant Cloud connection via URL and API key ([f4dcbec](https://github.com/matchdav/clew-engine/commit/f4dcbec33b008db09668c950dd47e724685ee495))


### Bug Fixes

* clear vector buffer before upsert to prevent unbounded growth ([a5bab08](https://github.com/matchdav/clew-engine/commit/a5bab0817d84648a8de9e5128172bd3acd0c10c2))
* create Qdrant payload indexes and unblock event loop on upserts ([a3f384e](https://github.com/matchdav/clew-engine/commit/a3f384e495ff0be44db5275ed99a3935cb3e6f06))
* derive human-readable repo_id from git remote instead of hashing ([4a1f7e4](https://github.com/matchdav/clew-engine/commit/4a1f7e40c5a404d024febfba49ab504fb881157f))
* eigenhelm issues ([0ef48e3](https://github.com/matchdav/clew-engine/commit/0ef48e399089bfcbda70778dee71104b9c7c0eb6))
* generate UUID point IDs instead of raw SHA256 hex strings ([b571a0e](https://github.com/matchdav/clew-engine/commit/b571a0e89cc4f37cfec7d6cca44d32c8492b0d03))
* include Repository→File relationships in finalization count ([b958048](https://github.com/matchdav/clew-engine/commit/b9580489605429320a9df82f152e1b08764dd649))
* include type in CodeBlock uniqueness constraint for Rust support ([2c510cf](https://github.com/matchdav/clew-engine/commit/2c510cf6260794c1d41ab4679b7de557bd923649))
* make add_batch upsert directly instead of through shared buffer ([de1a56c](https://github.com/matchdav/clew-engine/commit/de1a56c94b596ef0640ed7bb5cbdbaa8612b8d6f))
* move graph driver close from finalization to orchestrator ([5817175](https://github.com/matchdav/clew-engine/commit/5817175413df0384aeacb4c40764c138abcaa484))
* serialize graph writes to prevent Neo4j deadlocks ([98e6250](https://github.com/matchdav/clew-engine/commit/98e62507dfe9776ffcfae8418074b154ad0c12e8))
* use deterministic IDs for code block embeddings ([504fe23](https://github.com/matchdav/clew-engine/commit/504fe2328be7b8999d0e0770948b82ddc78b100e))
* wire unified config into ingestion stores ([0362690](https://github.com/matchdav/clew-engine/commit/0362690aa36fbd1d3c6ec38f5e49969c9abba65d))


### Performance Improvements

* concurrent embedding requests and parallel embed+graph writes ([aa4df0d](https://github.com/matchdav/clew-engine/commit/aa4df0dc14e615d36288ea3591404896fb7bec26))
* pipeline parsing and processing stages with async generators ([f3c28f5](https://github.com/matchdav/clew-engine/commit/f3c28f52a345e03a58101bca2a52e01a1e580791))
* tune batch sizes for concurrent embedding throughput ([1097b77](https://github.com/matchdav/clew-engine/commit/1097b777c658dac79ca80e15234ecfa3822ce6d5))

## [0.1.6](https://github.com/matchdav/clew-engine/compare/clewso-ingestion-v0.1.5...clewso-ingestion-v0.1.6) (2026-03-19)


### Miscellaneous Chores

* **clewso-ingestion:** Synchronize clewso versions

## [0.1.5](https://github.com/matchdav/clew-engine/compare/clewso-ingestion-v0.1.4...clewso-ingestion-v0.1.5) (2026-03-19)


### Bug Fixes

* **parser:** complexity issues ([e6f9d34](https://github.com/matchdav/clew-engine/commit/e6f9d3495e4584886e7d4f9f1ee639d4a5ecf9fa))

## [0.1.4](https://github.com/matchdav/clew-engine/compare/clewso-ingestion-v0.1.3...clewso-ingestion-v0.1.4) (2026-03-19)


### Features

* add --version/-V flag, fix publish workflow and project URLs ([229a780](https://github.com/matchdav/clew-engine/commit/229a780f15a253ca629aa70bbf533e0226b44c10))

## [0.1.3](https://github.com/matchdav/clew-engine/compare/clewso-ingestion-v0.1.2...clewso-ingestion-v0.1.3) (2026-03-19)


### Miscellaneous Chores

* **clewso-ingestion:** Synchronize clewso versions

## [0.1.2](https://github.com/matchdav/clew-engine/compare/clewso-ingestion-v0.1.1...clewso-ingestion-v0.1.2) (2026-03-19)


### Miscellaneous Chores

* **clewso-ingestion:** Synchronize clewso versions

## [0.1.1](https://github.com/matchdav/clew-engine/compare/clewso-ingestion-v0.1.0...clewso-ingestion-v0.1.1) (2026-03-19)


### Features

* add `clew index` CLI command with --incremental support ([7211786](https://github.com/matchdav/clew-engine/commit/721178686f23226f1cdc98b981df73461496f155))
* Add a platform client to send extracted code exports and imports for cross-repository linking. ([c4af57a](https://github.com/matchdav/clew-engine/commit/c4af57afb786b426da210822435bf7dc711eb1ee))
* Add batched processing path to ProcessingStage for 10x graph write speedup ([#52](https://github.com/matchdav/clew-engine/issues/52)) ([a79f244](https://github.com/matchdav/clew-engine/commit/a79f2448bfccac45f9296da0dd1151a405dc02a6))
* Add multi-repo support with automatic schema enforcement ([5142ddb](https://github.com/matchdav/clew-engine/commit/5142ddb9324742327231b52852e713346547443f))
* Add package root to `sys.path` in `conftest.py` files to enable test imports. ([f30a462](https://github.com/matchdav/clew-engine/commit/f30a462206677d77e0697800ac53d908cd0cf0ba))
* Clew Engine v0.1.0 ([132aa20](https://github.com/matchdav/clew-engine/commit/132aa20ac7de067e0cc18262f317a68d07b1468e))
* **clew-ingestion:** package as installable clew-ingestion library ([6ec9e37](https://github.com/matchdav/clew-engine/commit/6ec9e377d76c7cb889918d1669577a42fb5ccd99))
* Cross-Repo Linking & Import Detection ([8154dd8](https://github.com/matchdav/clew-engine/commit/8154dd8acabdc4b317063818a7d002b46dcadd5e))
* Filter standard library and vendor imports, update default OpenAI embedding model, and add batch graph neighbor retrieval. ([1d62428](https://github.com/matchdav/clew-engine/commit/1d62428ba2d153a86b01bc7835b992166ff92e8d))
* Implement batch embedding for OpenAI and Ollama providers and integrate into vector store's `add_batch` method. ([#46](https://github.com/matchdav/clew-engine/issues/46)) ([0fc2535](https://github.com/matchdav/clew-engine/commit/0fc2535668b8a145d3837dc88ccc8309382cd340))
* Implement buffered vector ingestion with batch flushing and support for pre-assigned IDs in the processing pipeline. ([16dfeb1](https://github.com/matchdav/clew-engine/commit/16dfeb1088ce586538e36faa52060a28ab61c045))
* Implement buffered vector ingestion with batch flushing and support for pre-assigned IDs in the processing pipeline. ([deb5237](https://github.com/matchdav/clew-engine/commit/deb5237c4e0500cd75621f2f7bdf239f022ea1bf))
* Implement incremental sync orchestrator, add webhook routes, and update graph and vector store functionality. ([e6412ca](https://github.com/matchdav/clew-engine/commit/e6412ca3f17a674fe1e8f5c1c679d1d9b5ec8171))
* Implement signature extraction stage and define API contract for metadata-only cross-repo linking. ([95c9174](https://github.com/matchdav/clew-engine/commit/95c9174ea59606f6b233e4d7cf04efcd3eb8b379))
* Implement signature extraction stage and define API contract for metadata-only cross-repo linking. ([9bba67d](https://github.com/matchdav/clew-engine/commit/9bba67dd13415eabeff67d8f2ab6140e8f6b0456))
* Initialize clew-ingestion dependencies, update Qdrant adapter and related tests, and modify docker-compose configuration. ([8f5cae4](https://github.com/matchdav/clew-engine/commit/8f5cae462c944d46c950ae7d978c19b9ca510a37))
* Introduce a unique `repo_id` for repositories, replacing `repo_url` as the primary identifier in ingestion and graph storage. ([9e30c00](https://github.com/matchdav/clew-engine/commit/9e30c00094e8e8fc4949664c9297ebcd51c7eb54))
* Phase 1 incremental sync — deterministic IDs, delete methods, IncrementalIngestionPipeline ([c766737](https://github.com/matchdav/clew-engine/commit/c7667371357282adc4de749304de38a121acf941))
* **phase-3.1:** resolve all pyright src errors across clew-mcp and clew-api ([c5766cc](https://github.com/matchdav/clew-engine/commit/c5766ccab01cbdde976cb2b62edb87a748141d5c))
* Refactor ingestion pipeline to use Pipeline and Strategy patterns ([65914c0](https://github.com/matchdav/clew-engine/commit/65914c07d380213f392d4268070294b65efc4b6a))
* retrieval quality improvement ([#38](https://github.com/matchdav/clew-engine/issues/38)) ([3557667](https://github.com/matchdav/clew-engine/commit/3557667800690c4ace1eceb44d2f74076d2a85dc))
* setup pre-commit ([#70](https://github.com/matchdav/clew-engine/issues/70)) ([950deec](https://github.com/matchdav/clew-engine/commit/950deec4be3f04adad257ebb7c8044d1d3106845))
* track last indexed commit SHA on Repository nodes ([6e41b65](https://github.com/matchdav/clew-engine/commit/6e41b656e39af2a8e7f725417eba38bd35b4b949))
* **types:** Phase 3.1 — TypedDicts for core data models, Pyright configs ([1dc768d](https://github.com/matchdav/clew-engine/commit/1dc768d59cffa0c65bf4f99faa11db38f40160f5))


### Bug Fixes

* Add exception chaining for B904 lint compliance ([306979c](https://github.com/matchdav/clew-engine/commit/306979c707333b5797e1ff098a6128aed1d64114))
* address PR review feedback (schema, docstrings, context metadata) ([62a3af0](https://github.com/matchdav/clew-engine/commit/62a3af044280ddab57f8be23a180932865250ee8))
* clean up formatting in test_pipeline_integration.py and exceptions.py ([a842b97](https://github.com/matchdav/clew-engine/commit/a842b97419f8f46402e0df378f660d3f57e4c3ae))
* lint errors in tests ([6d97d43](https://github.com/matchdav/clew-engine/commit/6d97d4399f62d7419579a4475321bac122904314))
* lint issues ([e72f9ab](https://github.com/matchdav/clew-engine/commit/e72f9abaec11ee2beaa8d1377017eba09979dc6b))
* lint issues ([f15862d](https://github.com/matchdav/clew-engine/commit/f15862de91d6907a77a9deecbf24e2f030328059))
* pass str to git.Repo.init() for older GitPython compat ([dd3e655](https://github.com/matchdav/clew-engine/commit/dd3e6558022607559e87bd34c08ae61077a0693d))
* poetry lockfile ([5b973f0](https://github.com/matchdav/clew-engine/commit/5b973f0223034c8cbf4235ce8e5eca56c85e7c84))
* resolve all lint and test failures ([88dc2cb](https://github.com/matchdav/clew-engine/commit/88dc2cb2a43e35bd3bc7d9c5c0ec501697edc155))
* Resolve remaining 6 lint errors for CI ([9dc3ee1](https://github.com/matchdav/clew-engine/commit/9dc3ee16ac370a132130d40e03a535f57d45fc8f))
* tech debt cleanup ([7b17761](https://github.com/matchdav/clew-engine/commit/7b17761ef43c5d021809d8fe9b083785f1fbaeb8))
* **test:** mock tree_sitter modules and use Path for context temp_dir per review ([75cd186](https://github.com/matchdav/clew-engine/commit/75cd186259415e1e57030592ab06b24102ff7fbd))
* **test:** resolve webhook and incremental sync failures ([47c0e9d](https://github.com/matchdav/clew-engine/commit/47c0e9d7e9e29a136ff4de1a8a22b3cfb95ab78c))
* wrap long log line in discovery.py (E501) ([450afa1](https://github.com/matchdav/clew-engine/commit/450afa1a922606fc864da97cdbeb20972c7b88a7))


### Documentation

* add sample fixture repo files for testing and validation ([a842b97](https://github.com/matchdav/clew-engine/commit/a842b97419f8f46402e0df378f660d3f57e4c3ae))
* update README with configuration\ntest: add batching test case ([d948690](https://github.com/matchdav/clew-engine/commit/d9486902a071718ba175e9a38968e5d8fe20f48e))
