# CLAUDE.md

Guidance for coding agents working in this repository. The README is the user-facing
description; this file is the short list of things an agent gets wrong without being told.

## What this is

Harvis is an open-source, self-hosted AI workspace. A FastAPI backend with Postgres and
pgvector, the Hermes desktop UI (React, Vite, TypeScript) served as a static bundle by nginx,
and a model server the user brings (Ollama, LM Studio, llama.cpp, vLLM or anything
OpenAI-compatible). It installs with Docker Compose, or on k3s through `scripts/k8s/`.

## Where things are

| Path | What is there |
|---|---|
| `install.sh`, `install.ps1` | the installers; a fresh machine must work from these alone |
| `docker-compose.yaml` | every service, network and volume; the k3s objects are generated from it |
| `python_back_end/` | the backend; features are plugins under `python_back_end/plugins/` |
| `front_end/hermes-desktop-ui/` | the live UI; Harvis code is under `src/plugins/harvis/`, `src/mods/`, `src/office/` |
| `front_end/hermes-shared/` | code shared with the UI (`@hermes/shared`) |
| `services/voice-onnx/` | speech sidecar (Whisper and Kokoro on ONNX) |
| `browser_runner/`, `repo-sandbox-engine/`, `box-egress/` | agent browser, sandbox and egress control |
| `scripts/k8s/` | the k3s mode |

The browser reaches the app through nginx on port 9000 (`/harvis/` for the UI, `/api` for the
backend). Do not call the backend port directly from UI code.

## Checks to run

UI, from `front_end/hermes-desktop-ui`:

```bash
npx tsc --noEmit -p .
npx vitest run --project ui
npx vite build
```

Backend, offline, from the repository root:

```bash
docker run --rm --network none -e HARVIS_ALLOW_EPHEMERAL_JWT_SECRET=1 \
  -v "$PWD:/repo:ro" -w /repo/python_back_end --entrypoint python \
  harvis-backend:latest -m pytest -q -p no:cacheprovider -o addopts="" tests
```

Installers and compose:

```bash
bash -n install.sh
python3 -m unittest scripts/test_install_edge.py
JWT_SECRET=x POSTGRES_PASSWORD=x docker compose --env-file /dev/null -f docker-compose.yaml config -q
```

A change is done when these were run and passed, not when it looks right.

## Rules

- Never commit until the user has reviewed the changes. Stage or `git commit --dry-run` if
  useful; the user commits, or says to.
- Never commit `.env`, anything under `config/presets/`, or any secret. The stack refuses to
  start without `JWT_SECRET` and `POSTGRES_PASSWORD`; the installers generate both.
- No site-specific names, hostnames, addresses or email addresses in tracked files. This is a
  public repository.
- A fix must work on a fresh machine through the installer, not only on the box it was found on.
- Published ports bind to `127.0.0.1` unless the user chose `--expose lan`. Keep it that way.
- Keep source files under 500 lines and match the style of the file being edited.
- The backend is bind-mounted: `docker restart harvis-backend` picks up Python changes. A UI
  change needs `hermes-ui-builder` rebuilt and `nginx-proxy` restarted (see the README).
- OpenClaw is gone: no gateway, no config, no UI. A few stored names still say `openclaw`
  because renaming them needs a data migration: the tables `openclaw_llm_config` and
  `openclaw_tool_audit`, the `openclaw-projects` volume, the `X-OpenClaw-SessionKey` header,
  the `OPENCLAW_WEB_*` and `OPENCLAW_CONFIG_SET` variables, the old `OPENCLAW_GATEWAY_TOKEN`
  fallback and skill metadata keys. Do not rename one of these in one place only, and do not
  add new names like them.
