# AGENTS.md

Canonical guide for agentic coding tools (Claude Code, Codex, Cursor, etc.) working in this repository. Read this before making changes. If something here is wrong or stale, fix it in the same PR as your other work.

## What this integration does

`homeassistant-triad-ams` is a HACS custom integration for the Triad AMS family of audio matrix switches (8x8, 16x16, 24x24). It talks to the device over plain TCP (default port `52000`) using a small binary protocol derived from Tim Weiler's `triad-audio-matrix` work — there is no vendor SDK. Connection is local-polling only (`iot_class: local_polling` in the manifest); there is no discovery, push, or cloud component.

Each *active* output zone surfaces as a Home Assistant `media_player` entity. Per-zone you can turn the zone on/off (route/disconnect), select a routed input, and set volume. An optional "input link" feature lets you bind each Triad input to an existing HA `media_player` (typically a Sonos); when that input is the selected source for a zone, the Triad entity proxies title/artist/album/artwork from the linked entity. The integration is config-entry only — no YAML for user configuration.

Quality scale: currently **Bronze** in `manifest.json`, but `custom_components/triad_ams/quality_scale.yaml` tracks per-rule status across Bronze/Silver/Gold/Platinum and most rules are already marked `done`. Treat that file as the source of truth for what's been implemented vs. still `todo`.

## Layout

```
.
├── AGENTS.md                       # This file
├── CLAUDE.md                       # One-line `@AGENTS.md` import for Claude Code
├── README.md                       # User-facing install/config docs (rendered by HACS)
├── CONTRIBUTING.md                 # Basic contributor guide (PR flow, MIT)
├── hacs.json                       # HACS metadata (sets minimum HA version)
├── pytest.ini                      # Pytest config — note: NO pyproject.toml in this repo
├── .ruff.toml                      # Ruff config (lint + format) — based on HA core
├── .pre-commit-config.yaml         # Ruff + pre-commit-hooks + local pytest hook
├── requirements.txt                # Dev/runtime requirements (HA, pytest, ruff, …)
├── assets/                         # Brand icons/logos (PNG + SVG, 1x + 2x)
├── config/                         # HA dev instance config (mounted by scripts/develop)
│   └── configuration.yaml          # default_config + logger + sonos hosts for local testing
├── scripts/
│   ├── setup                       # Devcontainer postCreate: installs deps, act, pre-commit, Cursor, Claude
│   ├── develop                     # Boots a local HA instance against ./config on :8123
│   ├── lint                        # ruff check --fix && ruff format --check
│   ├── send_command.py             # Standalone TCP debug tool — sends raw hex, prints frame
│   ├── sweep_volume.py             # Standalone helper for sweeping volume across the LUT
│   └── gen_brand_assets.py         # Regenerates files under assets/
├── custom_components/triad_ams/
│   ├── __init__.py                 # Entry setup/teardown, two services, async_migrate_entry
│   ├── manifest.json               # Domain, version (CalVer), codeowners, quality_scale
│   ├── config_flow.py              # Initial config + options (host/port/model + active in/out + links)
│   ├── connection.py               # Low-level TCP framing, command/response, write serialization
│   ├── coordinator.py              # Single-queue/single-worker command pacer; owns the connection
│   ├── media_player.py             # Output zone entity + metadata proxying from linked players
│   ├── models.py                   # TriadAmsOutput + related dataclasses
│   ├── volume_lut.py               # Volume scaling lookup (HA 0..1 ↔ device 0..0x64)
│   ├── const.py                    # DOMAIN, timeouts, VOLUME_STEPS, NETWORK_EXCEPTIONS
│   ├── diagnostics.py              # Diagnostics download (Gold quality rule)
│   ├── repairs.py                  # Repair issue flows
│   ├── services.yaml               # turn_on_with_source, set_protocol_debug
│   ├── strings.json / translations/en.json  # UI strings
│   ├── icons.json                  # Icon translations
│   ├── quality_scale.yaml          # Per-rule quality-scale status (Bronze→Platinum)
│   └── RELEASE.md                  # Maintainer release checklist (older, manifest-version flavor)
├── tests/
│   ├── conftest.py                 # Shared fixtures (mocked connections, HA harness helpers)
│   ├── unit/                       # Fast unit tests per module
│   ├── integration/                # End-to-end tests against an in-process TCP simulator
│   │   └── simulator.py            # Fake Triad device for integration tests
│   └── fixtures/                   # Static test fixtures
└── .github/
    ├── workflows/
    │   ├── lint.yml                # Ruff check + format check on push/PR to main
    │   ├── validate.yml            # Hassfest + HACS validation + full pytest suite
    │   ├── release.yml             # Tag `v*` → GitHub release with auto-generated notes
    │   └── dependabot-auto-merge.yml  # Auto-approves & enables auto-merge for dependabot PRs
    ├── dependabot.yml              # Daily updates: devcontainers, github-actions, pip (excl. homeassistant)
    └── ISSUE_TEMPLATE/             # bug + feature_request forms
```

## Dev workflow

This is a **devcontainer-first** repo. The devcontainer (`.devcontainer/devcontainer.json`) is based on `mcr.microsoft.com/devcontainers/python:3.14` and on first create runs `scripts/setup`, which:

- `pip install -r requirements.txt` (pulls in `homeassistant`, `pytest-homeassistant-custom-component`, `ruff`, etc.)
- Installs `nektos/act` (for running GitHub Actions locally)
- `pre-commit install`
- Installs the Cursor and Claude CLIs

There is **no `pyproject.toml`**. Tooling lives in three top-level files: `pytest.ini`, `.ruff.toml`, and `.pre-commit-config.yaml`. Don't move config into a `pyproject.toml` unless you're prepared to retest everything and update CI.

Common commands (run from repo root):

| Task | Command |
| --- | --- |
| Boot a local HA instance against `./config` on port 8123 | `scripts/develop` |
| Lint + format check | `scripts/lint` (`ruff check . --fix && ruff format . --check`) |
| Full test suite (unit + integration) | `pytest tests/` |
| Single test | `pytest tests/unit/test_media_player.py::test_foo -v` |
| Send a raw protocol frame to a real device | `scripts/send_command.py <ip> <port> "<hex>"` |
| Sweep volume on a real device | `scripts/sweep_volume.py …` |

Pytest is parallel by default (`addopts = -n auto -W error` in `pytest.ini`) and treats warnings as errors. `asyncio_mode = auto`, so async tests don't need a decorator. Tests are split into `tests/unit/` (fast, mocked) and `tests/integration/` (run against `tests/integration/simulator.py`, a fake TCP Triad device).

Pre-commit hooks (`.pre-commit-config.yaml`) run on every commit and will:

1. `ruff-check --fix` and `ruff-format`
2. `end-of-file-fixer`, `trailing-whitespace`, `mixed-line-ending` (LF), `check-yaml`
3. **`pytest tests/ -v --tb=short --cov=custom_components.triad_ams`** — yes, the whole test suite runs as a pre-commit hook. Commits can take a while. Don't add `--no-verify`; if a hook fails, fix the issue and re-stage.

CI mirrors this:

- **Lint** workflow: `ruff check .` and `ruff format . --check`
- **Validate** workflow: Hassfest, HACS validation (with `ignore: brands`), and the full pytest suite — also runs nightly on cron
- **Release** workflow: triggered by pushing a `v*` tag

Dependabot is configured for `devcontainers`, `github-actions`, and `pip` on a daily cadence (with `homeassistant` itself pinned via the `hacs.json` minimum). Dependabot PRs are auto-approved and auto-merged by `dependabot-auto-merge.yml` once checks pass.

## Conventions & gotchas

- **Ruff is `select = ["ALL"]`** with a short ignore list — expect to satisfy a lot of rule families (annotations, docstrings, security, complexity). Test files have a few rules waived (`S101`, `PLR2004`, `SLF001`, `ARG002`); production code does not.
- **Target Python is 3.13** (`target-version = "py313"` in `.ruff.toml`) even though the devcontainer image is Python 3.14 — keep generated code 3.13-compatible. `keep-runtime-typing = true`, so `from __future__ import annotations` + PEP 604 unions are fine but don't strip `typing` imports indiscriminately.
- **Max cyclomatic complexity is 25** (`mccabe.max-complexity`). Higher than typical Ruff defaults — don't refactor for complexity unless Ruff actually flags it.
- **Domain is `triad_ams`** (snake_case, matches directory). The matching HA device class is `media_player`. The integration owner is `@bharat` (`codeowners` in manifest).
- **Coordinator is custom, not `DataUpdateCoordinator`.** `TriadCoordinator` (`coordinator.py`) is a single-queue, single-worker command pacer that owns the `TriadConnection`. All device I/O must go through it — do not call `TriadConnection` methods directly from entities.
- **Config entry has migrations.** `__init__.async_migrate_entry` upgrades pre-`model` entries. The current `MINOR_VERSION` is `4`; bump `TARGET_MINOR_VERSION` and the matching constant in `config_flow.py` together when changing entry schema.
- **`scripts/develop` boots HA against `./config/`.** That config has hardcoded Sonos IPs (`192.168.0.30..41`) and `homeassistant.components.sonos: error`. Edit your local copy as needed, but don't commit credentials/IPs that aren't already there.
- **Two custom services** are registered in `__init__.py`: `triad_ams.turn_on_with_source` (entity service; takes another media_player as the source) and `triad_ams.set_protocol_debug` (global toggle for protocol-level logging). When changing service signatures, update both `services.yaml` and any translations.
- **Quality scale is tracked in `quality_scale.yaml`.** If you implement a `todo` rule, flip it to `done` in the same PR. If you regress a `done` rule, that's a release blocker.
- **CalVer tags.** See the Releases section below — *not* SemVer. The `manifest.json` version is also CalVer and must match the tag.

## Existing docs

- `README.md` — user install/config docs, what HACS renders
- `CONTRIBUTING.md` — short contributor guide (fork, branch, lint, PR)
- `custom_components/triad_ams/RELEASE.md` — older maintainer release checklist; predates the auto-generated release workflow. The procedure in this file (the "Releases" section) is canonical for tag/title format; `RELEASE.md` retains useful HACS troubleshooting notes.
- `custom_components/triad_ams/quality_scale.yaml` — authoritative status of HA quality-scale rules

## Releases

Tags use CalVer: `v<YYYY.MM.DD>` (e.g. `v2025.12.31`). Release titles use `Triad AMS v<YYYY.MM.DD>` (e.g. `Triad AMS v2025.12.31`).

Build the GitHub release body in three parts:

1. **Lead paragraph** (no header): 1–3 sentences of plain-English summary describing what this release means for users.
2. **`## What's Changed` section**: bullet list of non-dependabot merged PRs since the previous tag, one per line in the format `* <commit subject> by @<author> in <PR url>`. Skip dependabot PRs entirely.
3. **`N dependabot updates:` rollup**: at the bottom, one line per dependency in the format `* <package>: <oldest version in window> → <newest version>`. Collapse all dependabot bumps for the same dep into one line.

End with `**Full Changelog**: <compare link>` (GitHub auto-generates).

The `release.yml` workflow fires on `v*` tag push and creates the release with `generate_release_notes: true` — that gives you a starting draft. Rewrite the body in the three-part shape above before publishing.

## What NOT to touch

- `assets/*.png` — regenerate via `scripts/gen_brand_assets.py` from the SVGs; don't hand-edit the bitmaps.
- `config/` (other than `configuration.yaml`) — gitignored except for the checked-in `configuration.yaml`; `scripts/develop` writes generated HA state here.
- `.coverage`, `.pytest_cache/`, `__pycache__/`, `coverage.xml`, `.ruff_cache/` — all gitignored build artifacts. Never commit.
- `homeassistant` pin in `requirements.txt` — `hacs.json` declares the minimum HA version (currently `2025.10.0`) and Dependabot is configured to *not* bump the `homeassistant` package. Don't bump it casually; coordinate with the `hacs.json` minimum.
- Open Dependabot PRs — they auto-merge once green. Don't rebase or close them as part of unrelated work.
- The Tim Weiler attribution in `README.md` and the protocol bytes derived from it — keep the credit intact.
