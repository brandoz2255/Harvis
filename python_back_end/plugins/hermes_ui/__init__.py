"""Hermes desktop-UI facade.

The vendored Hermes UI (front_end/hermes-desktop-ui, served at /hermes/) speaks
the Hermes gateway protocol: a handful of REST endpoints plus a JSON-RPC 2.0
WebSocket. Harvis has no Hermes gateway process, so this package answers that
protocol itself and runs each prompt through Harvis's own chat completion path.

Everything lives under /hermes-api/ (nginx forwards that prefix, upgrade
included, to the backend). Sessions are held in memory only.
"""
