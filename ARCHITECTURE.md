# JobFinder Architecture Assessment

This document records the repository-wide architecture review and the current
modularization target. The refactor keeps public CLI commands and historical
imports working while tightening module ownership.

## Current Shape

JobFinder is a Python data pipeline with three product workflows:

- Scrape jobs through Apify-backed provider actors.
- Deduplicate, filter, and export jobs to Excel or Google Sheets.
- Evaluate exported rows with OpenAI, generate tailored CV PDFs, and write
  results back to the same storage surface.

The main package is already organized under `src/jobfinder`, with thin root and
`scripts/` compatibility wrappers. The test suite covers provider adapters,
search execution, dedupe, evaluator parsing/storage, Google auth helpers, and
pipeline CLI behavior.

## Problems Found

| Area | Problem | Why it was risky | Modular solution |
|---|---|---|---|
| Provider boundary | LinkedIn and Apify implementations lived under `scraper.providers`, while Indeed and Stepstone lived under `providers`. | New provider work had two competing homes, and `scraper/search.py` mixed orchestration with provider ownership details. | Move stable provider behavior behind `jobfinder.providers`, keep `jobfinder.scraper.providers` as compatibility facades. |
| Provider branching | `scraper/search.py` used source-specific branches to build payloads and run actors. | Every new provider would require editing orchestration internals, increasing merge conflicts and coupling. | Add `providers/registry.py` with `ProviderAdapter` public interfaces. |
| Duplicate provider normalization | Indeed and Stepstone duplicated scalar/list/dict normalization helpers. | Divergent cleanup behavior would cause subtle provider-specific bugs and make output normalization harder to test. | Add `providers/normalization.py` and share reusable primitives. |
| Cross-layer import | `scraper/normalize.py` imported `scraper/search.py` only to build Indeed fallback URLs. | Spreadsheet normalization depended on search orchestration, complicating imports and future test isolation. | Import the URL helper directly from the Indeed provider adapter. |
| CLI logging | Scraper, evaluator, and pipeline CLIs each configured logging independently. | Format drift and repeated boilerplate made entry points inconsistent. | Add `core/logging.py` and route each CLI through the shared setup. |
| Integration env access | Google API timeout/retry helpers read `os.environ` directly. | `.env` fallback behavior differed from the rest of the app. | Resolve through `EnvSettings`, preserving real environment precedence. |
| Report path lookup | Report helpers used direct environment access. | CI and local `.env` behavior differed from runtime settings elsewhere. | Route report path lookup through `EnvSettings`. |

## Refactor Applied

| Change | Exact files | Compatibility preserved |
|---|---|---|
| Added shared runtime package | `src/jobfinder/core/__init__.py`, `src/jobfinder/core/logging.py` | Existing `configure_logging()` functions remain in CLI modules. |
| Added provider normalization helpers | `src/jobfinder/providers/normalization.py` | Provider output shape and tests are unchanged. |
| Moved LinkedIn implementation to stable provider package | `src/jobfinder/providers/linkedin.py` | `src/jobfinder/scraper/providers/linkedin.py` re-exports the old path. |
| Moved Apify client implementation to stable provider package | `src/jobfinder/providers/apify_client.py` | `src/jobfinder/scraper/providers/apify_client.py` re-exports functions and `requests` for existing monkeypatch paths. |
| Added provider registry | `src/jobfinder/providers/registry.py` | Existing `scraper/search.py` public helpers still exist. |
| Reduced scraper orchestration coupling | `src/jobfinder/scraper/search.py`, `src/jobfinder/scraper/normalize.py` | Public functions and behavior remain compatible. |
| Standardized CLI logging | `src/jobfinder/scraper/cli.py`, `src/jobfinder/evaluator/cli.py`, `src/jobfinder/pipeline/cli.py` | CLI output format remains the same. |
| Centralized env-backed integration settings | `src/jobfinder/integrations/google/credentials.py`, `src/jobfinder/operations/reports.py`, `src/jobfinder/pipeline/cli.py` | Real environment variables still override `.env`. |
| Moved Google implementation behind integration names | `src/jobfinder/integrations/google/` | Current `jobfinder.google_*` modules remain compatibility facades. |

## Target Folder Structure

```text
src/jobfinder/
  core/                 # Cross-cutting runtime primitives
  providers/            # Source adapters, Apify client, provider registry
  scraper/              # Scrape workflow orchestration, filters, exports, history
  dedupe/               # Pure deterministic duplicate matching and merging
  evaluator/            # OpenAI evaluation, parsing, storage, PDF output
  spreadsheet/          # Shared column contracts
  pipeline/             # Multi-step CLI and preflight checks
  operations/           # CI/reporting helpers
  integrations/google/  # Google credentials, client, Sheets, and Drive adapters
  env.py                # Environment reader
  paths.py              # Repository path constants
  config_files.py       # User-editable config file loading
  google_config.py      # Compatibility facade for Google credential paths
  google_auth.py        # Compatibility facade for Google client helpers
  google_sheets.py      # Compatibility facade for Sheets helpers
  google_drive.py       # Compatibility facade for Drive helpers
```

## Module Ownership Boundaries

| Owner | Public responsibility | Should not own |
|---|---|---|
| `core` | Runtime-neutral helpers such as logging setup. | Product workflow logic. |
| `providers` | Actor payloads, actor output normalization, provider registry, Apify execution. | Final filters, spreadsheet formatting, business workflow orchestration. |
| `scraper` | Search planning, concurrency, final filtering, export orchestration, run history. | Provider-specific actor schemas or evaluator logic. |
| `dedupe` | Pure duplicate identity, scoring, and canonical merging. | Google Sheets reads/writes or final business filters. |
| `evaluator` | Prompt construction, OpenAI calls, parsing, storage updates, CV PDF output. | Scraper provider schemas. |
| `spreadsheet` | Column contracts shared by scraper and evaluator. | Storage API calls. |
| `pipeline` | Child process orchestration and preflight. | Low-level scraper/evaluator behavior. |

## Recommended Conventions

- New providers register a `ProviderAdapter` in `providers/registry.py`.
- Provider modules expose payload builders, actor runners, and actor-output
  normalizers. Internal metadata should stay under `_jobfinder_*` keys.
- Service modules orchestrate workflows; CLI modules only parse args, configure
  logging, translate exceptions to exit codes, and write reports.
- Column changes start in `spreadsheet/schema.py`, then flow into exporters,
  evaluator parsing/storage, tests, and docs.
- `.env` fallback access goes through `EnvSettings`.
- Network clients accept narrow function injection points for tests.
- Compatibility wrappers may remain, but new imports should use stable package
  paths documented here.

## Remaining Anti-Patterns And Bottlenecks

- `scraper/run_history.py` still has both identity-key logic and Google Sheets
  history I/O. Split it into `scraper/history/identity.py` and
  `scraper/history/google_sheets.py` when the next history feature lands.
- `scraper/service.py` is an orchestration-heavy module. It is readable, but new
  workflow steps should be extracted into command objects or small workflow
  functions to avoid becoming a god service.
- `evaluator/service.py` coordinates input reads, OpenAI evaluation, incremental
  saves, PDF generation, and final cleanup. The next growth point is a
  `EvaluationWorkflow` object with injectable storage and evaluator ports.
- Google Sheets and Drive helpers now have integration-owned names, but the
  compatibility facades still need a deprecation window before removal.
- Root scripts and `scripts/` duplicate compatibility wrappers. Keep them for
  backward compatibility, but avoid adding logic there.

## Prioritized Roadmap

1. Keep provider work behind `ProviderAdapter`.
2. Split run-history identity generation from Google Sheets I/O.
3. Introduce storage ports for evaluator reads/writes:
   `EvaluationInputStore` and `EvaluationOutputStore`.
4. Update internal and external examples to prefer
   `jobfinder.integrations.google`.
5. Extract scraper workflow logging into a small run-summary/presenter helper if
   `scraper/service.py` grows further.
6. Add import-boundary checks in CI once package boundaries settle.
7. Consider separate optional dependency groups:
   `jobfinder[scraper]`, `jobfinder[evaluator]`, `jobfinder[google]`,
   `jobfinder[dev]`.

## Migration Strategy

- Phase 1: Add stable modules and compatibility wrappers. This phase is now in
  place.
- Phase 2: Update internal imports to stable paths. Avoid changing user-facing
  commands.
- Phase 3: Update docs and examples to prefer stable paths.
- Phase 4: Add deprecation comments for compatibility wrappers after at least
  one release.
- Phase 5: Remove wrappers only if there is no local or CI usage left.

## Refactor Risk Assessment

| Refactor | Risk | Mitigation |
|---|---|---|
| Provider registry | Low to medium | Existing tests cover provider payloads, source selection, batching, and concurrency. |
| Moving Apify client | Medium | Compatibility facade re-exports `requests` and all public helpers used by tests. |
| Shared provider normalization | Low | Existing provider tests verify normalized fields and metadata. |
| Env-backed Google settings | Low | Default values and real env precedence are preserved. |
| Future history split | Medium | Needs focused tests around hidden seen-job keys and previous-run windows. |
| Future evaluator workflow split | Medium | Preserve incremental save semantics before extracting storage ports. |

## Long-Term Architecture

The clean end state is a ports-and-adapters pipeline:

- Domain modules are pure and deterministic where possible.
- External APIs live in integration adapters.
- Workflows depend on narrow interfaces, not concrete SDK modules.
- Provider additions are adapter-only plus registration.
- Spreadsheet contracts are centralized and versionable.
- CLI commands remain thin shells over testable services.

This keeps JobFinder operational today while giving future providers, storage
backends, and evaluator variants a clean place to grow.
