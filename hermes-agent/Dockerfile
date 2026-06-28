# Harvis Hermes Agent engine sidecar (Phase E4B) — the REAL NousResearch Hermes Agent
# application as a Build engine + Chat backend. Thin wrapper FROM the official image.
#
# WHY a wrapper (not the bare image): the official gateway is s6-overlay-supervised and
# MUST start as root (it refuses uid 1001), but Harvis's backend collects diffs as uid
# 1001 (the artifact_data owner). So: the gateway/API-server runs as ROOT (Chat surface),
# while Build runs are driven by the backend via `docker exec -u 1001 hermes -z <clone>`
# (files land 1001-owned → backend reads/diffs them). The wrapper also injects a local-
# Ollama provider config into the gateway home on first boot (no cloud key) and creates
# uid 1001 so Build execs have a real home.
#
# Local-Ollama only by default — NO provider/API key is baked. Talks to http://ollama:11434.
FROM nousresearch/hermes-agent:v2026.6.19

# uid 1001 for `docker exec -u 1001` Build runs (matches artifact_data ownership). The
# gateway itself still runs as root under s6; this user is only for the exec'd CLI.
RUN (id -u 1001 >/dev/null 2>&1 || useradd -u 1001 -m -s /bin/bash builder) || true

COPY harvis-entrypoint.sh /usr/local/bin/harvis-entrypoint.sh
RUN chmod +x /usr/local/bin/harvis-entrypoint.sh

# Keep the official s6 init; our wrapper just injects config then hands off to it.
ENTRYPOINT ["/usr/local/bin/harvis-entrypoint.sh"]
CMD ["gateway", "run"]
