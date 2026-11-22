# Changelog

All notable changes to **Nebulus Gantry** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.3.1] - 2026-11-21

### Fixed

- GitHub Actions CI: backend flake8 and frontend eslint failures that blocked tests (unused imports and variables, a missing `FPDF` name, bare `except` clauses, export-spreadsheet complexity, an explicit `any`, setState-during-effect, and helpers moved out of a component file).
- Stale frontend tests that still expected the "Message Nebulus..." prompt and absolute API URLs.
- Removed a committed `test_output.txt` and ignored it going forward.

### Changed

- Version metadata set to 2.3.1 (`frontend/package.json`, Settings UI). The FastAPI app `version` is updated from the stale `2.0.0` string to `2.3.1`.

## [2.3.0] - 2026-11-13

Shipped on `main` as tag `v2.3.0`. Highlights from that release: MIT license, AGENTS.md baseline, develop/main history reconciliation, TabbyAPI `model_name` load payload, Excel and structured PDF conversation export, Gantry branding, frontend on port 3002, and `NEBULUS_CHROMA_URL` / `NEBULUS_LLM_URL` env names (legacy aliases still work).
