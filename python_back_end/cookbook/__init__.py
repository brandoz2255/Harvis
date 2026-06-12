"""Cookbook — hardware-aware model recommendation + download.

A thin aggregating proxy over per-node `llmfit serve` instances (+ each node's
Ollama for downloads). llmfit is the engine: it owns hardware-scan, fit-scoring,
the model DB, and download ranking. This package adds nothing but routing.
"""

from .router import router  # noqa: F401
