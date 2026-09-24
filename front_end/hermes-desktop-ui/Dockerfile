# Builds the vendored Hermes desktop UI for the browser so a fresh clone needs no
# host Node/npm — the same trick front_end/owui/Dockerfile plays for owui.
#
# The build context is front_end/, NOT this directory: `@hermes/shared` resolves
# to ../hermes-shared/src (tsconfig.json + vite.config.ts), which would be outside
# a hermes-desktop-ui context and fail to copy.
#
# Electron and Playwright binaries are pure waste here — nothing in the browser
# build runs them — so their downloads are skipped, which also keeps the image
# from pulling ~200 MB it would immediately throw away.
FROM node:22-bookworm-slim AS build

# Node's heap ceiling for the vite build. A ceiling, not a reservation — but a
# machine with less RAM than this can thrash itself to death reaching for it, so
# it is tunable for the small-box installs Harvis is supposed to survive on.
ARG HERMES_UI_NODE_HEAP_MB=8192

ENV ELECTRON_SKIP_BINARY_DOWNLOAD=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    NODE_OPTIONS=--max-old-space-size=${HERMES_UI_NODE_HEAP_MB}

WORKDIR /app/hermes-desktop-ui

# The shared workspace package first: it changes far less often than the app, so
# an app-only edit reuses this layer.
COPY hermes-shared /app/hermes-shared

COPY hermes-desktop-ui/package.json hermes-desktop-ui/package-lock.json ./
# --ignore-scripts: node-pty's postinstall needs python3/make, which the slim image
# lacks and the browser build never uses.
# --legacy-peer-deps: upstream's vitest peer range does not resolve under npm's
# strict peer solver (arborist crashes in #loadPeerSet). This is the vendored
# tree's own dependency graph, not something Harvis can fix by pinning.
RUN npm install --legacy-peer-deps --ignore-scripts --no-audit --no-fund

COPY hermes-desktop-ui/ ./

# Where the built bundle sends its API calls. The Harvis backend mounts the
# Hermes facade at /hermes-api/api (python_back_end/plugins/hermes_ui/rest.py),
# and nginx proxies /hermes-api/ straight to it. Without this the shim falls
# back to '' (src/lib/desktop-shim/api.ts) and every call lands on bare /api/...,
# which is mostly 404 — except /api/memory, which is an unrelated Harvis plugin
# and answers with a schema this UI does not understand.
ARG VITE_HERMES_API_BASE=/hermes-api
ENV VITE_HERMES_API_BASE=${VITE_HERMES_API_BASE}

RUN npx vite build

# A stamp the publish step can compare against the host's dist/ to tell a current
# build from a stale one. Vite content-hashes every chunk, so the file list alone
# moves whenever the source does; the API base is folded in because it changes the
# bytes without changing any filename.
RUN cd /app/hermes-desktop-ui/dist \
 && { echo "api-base=${VITE_HERMES_API_BASE}"; \
      find . -type f | LC_ALL=C sort | xargs sha256sum | sha256sum; } > .harvis-build-id

# busybox + the compiled output only — tagging the Node stage would ship gigabytes
# to serve ~40 MB of static files.
FROM busybox:1.37.0 AS artifact
COPY --from=build /app/hermes-desktop-ui/dist /app/dist
