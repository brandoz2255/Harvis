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

ENV ELECTRON_SKIP_BINARY_DOWNLOAD=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    NODE_OPTIONS=--max-old-space-size=8192

WORKDIR /app/hermes-desktop-ui

# The shared workspace package first: it changes far less often than the app, so
# an app-only edit reuses this layer.
COPY hermes-shared /app/hermes-shared

COPY hermes-desktop-ui/package.json hermes-desktop-ui/package-lock.json ./
# --legacy-peer-deps: upstream's vitest peer range does not resolve under npm's
# strict peer solver (arborist crashes in #loadPeerSet). This is the vendored
# tree's own dependency graph, not something Harvis can fix by pinning.
RUN npm install --legacy-peer-deps --no-audit --no-fund

COPY hermes-desktop-ui/ ./
RUN npx vite build

# busybox + the compiled output only — tagging the Node stage would ship gigabytes
# to serve ~40 MB of static files.
FROM busybox:1.37.0 AS artifact
COPY --from=build /app/hermes-desktop-ui/dist /app/dist
