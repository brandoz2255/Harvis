# 3D Printer Integration — Design (Phase 10, design only)

**Status:** Design document. No code exists for this yet, and none should be written
until the SSH/local-bridge groundwork (Phase 7) clears its security review.

**Lane:** Local / CLI only. This follows the locked "Web Harvis = GitHub-first"
decision: the web app never touches hardware. All printer I/O happens through a
**local bridge** — the future Harvis CLI running on a machine the user owns, on the
same network as (or physically attached to) the printer.

---

## 1. Goals and non-goals

**Goals**

- Let a Harvis agent take a model request ("print this bracket") through slice →
  preview → user approval → send → status readback, with the human gating every
  irreversible step.
- Support the two dominant self-hosted controllers first: **OctoPrint** (REST API)
  and **Klipper/Moonraker** (HTTP + websocket API). Serial-direct G-code is out of
  scope for v1.
- Slicing via existing **CLI slicers** (PrusaSlicer, Cura) as tool adapters — Harvis
  never implements slicing itself.

**Non-goals (v1)**

- No printer control from the web UI or the Kubernetes deployment. Web Harvis may
  *display* status forwarded by the bridge, nothing more.
- No automatic printing. There is no code path that sends a job without an explicit
  per-job user approval.
- No firmware flashing, no PID tuning, no bed-leveling macros — read-mostly plus
  "start approved job" and "cancel/pause".
- No cloud printer services (Bambu cloud, OctoEverywhere) in v1.

## 2. Architecture: the local bridge

```
User ⇄ Harvis (web or CLI chat)
          │  plans, explains, asks for approval
          ▼
   Harvis CLI (local bridge, runs on the user's host)
          │  adapter calls, local network only
          ├─→ Slicer CLI (prusa-slicer / CuraEngine) — file in, G-code out
          ├─→ OctoPrint REST  (http://octopi.local/api, X-Api-Key)
          └─→ Moonraker API   (http://klipper-host:7125)
```

- The bridge is part of the planned Harvis CLI (roadmap item 2). It holds printer
  credentials locally (same Fernet write-only pattern as `engine_auth` /
  the Phase 7 `user_ssh_hosts` scaffold), talks only to LAN endpoints, and exposes
  results back to the orchestrator as ordinary tool results.
- **Web Harvis never gets the printer's address or API key.** If the user chats from
  the web while a bridge is registered, printer tool calls are routed to the bridge;
  with no bridge online, the tools simply report "no printer bridge connected".
- Host discovery reuses Phase 7's host-profile storage: a printer profile is
  `(name, kind: octoprint|moonraker, base_url, api_key_ref)` and is subject to the
  same host-string validation (no shell metacharacters, bare host only).

## 3. Printer setup flow

Two paths, both ending in a saved printer profile:

1. **Discovery (assisted):** the bridge probes the local network for known
   signatures — mDNS `_octoprint._tcp`, Moonraker's default port 7125 on hosts the
   user names. Discovery only *suggests*; the user confirms each found printer
   before it is saved. No background scanning; probing runs only when the user asks.
2. **Manual:** the user enters base URL + API key in the CLI (`harvis printer add`).
   The key is stored encrypted, write-only, exactly like engine credentials. A
   `harvis printer test` performs one authenticated `GET /api/version` (OctoPrint)
   or `GET /server/info` (Moonraker) and reports reachability — this is the ONLY
   network call setup makes.

## 4. Slicer integration

Slicers are **tool adapters around existing CLIs**, not libraries:

- **PrusaSlicer:** `prusa-slicer --export-gcode --load <profile.ini> -o out.gcode in.stl`
- **Cura:** `CuraEngine slice -j <printer.def.json> -l in.stl -o out.gcode`

Rules:

- Input files come from the workspace (an artifact from a Build run, an STL the user
  provided). Paths are validated and confined to the session workspace — no
  arbitrary host paths.
- Slicer profiles are user-supplied files selected by name from a profiles folder;
  Harvis never synthesizes raw slicer flags from model output. The adapter allows a
  small allowlisted set of overrides (layer height, infill %, material preset),
  each range-checked before being passed through.
- Slicer stdout (time estimate, filament used) is parsed into the preview shown at
  the approval gate.

## 5. Adapter interface: prepare / preview / execute / status

Every printer-lane tool implements one contract so the orchestrator, approval UI,
and audit log stay uniform:

```python
class PrinterAdapter(Protocol):
    def prepare(self, job: JobSpec) -> PreparedJob:
        """Validate inputs, slice if needed, run safety checks.
        Pure local work — MUST NOT contact the printer."""

    def preview(self, prepared: PreparedJob) -> JobPreview:
        """Human-readable summary for the approval gate: file name + hash,
        printer, material, temps, estimated time/filament, safety-check results."""

    def execute(self, prepared: PreparedJob, approval: ApprovalToken) -> JobHandle:
        """Upload + start. REFUSES to run without a valid, single-use
        ApprovalToken minted by the user's explicit confirmation of THIS
        preview (token binds to the prepared job's content hash)."""

    def status(self, handle: JobHandle) -> JobStatus:
        """Progress %, current temps, printer state, timestamps. Read-only."""
```

- **MockPrinterAdapter ships first** and is the default: it fakes a printer with
  configurable state transitions so the whole flow (including approval UX and
  status polling) is testable end-to-end with zero hardware. Real adapters
  (`OctoPrintAdapter`, `MoonrakerAdapter`) land only after the mock-driven flow is
  accepted.
- `execute` is the only method with side effects on hardware, and it is unreachable
  without an approval token. Tokens are single-use and expire (~10 minutes), so a
  stale approval can't fire later.

## 6. Send-to-printer workflow (explicit approval)

1. Agent calls `prepare` → slice + safety checks run locally.
2. Agent calls `preview` → Harvis renders the summary card (file, hash, printer,
   material, temps, time, warnings) and asks: **"Send to printer? [yes/no]"**.
3. Only a direct user confirmation mints the ApprovalToken. Agent text can never
   self-approve; the token is created by the CLI/UI layer, not by a tool call.
4. `execute` uploads the G-code and starts the job; the job handle, file hash, and
   approving user are written to an audit record (same spirit as
   `openclaw_tool_audit`).
5. `status` polls; pause/cancel are offered to the user, and cancel requires no
   approval (stopping is always safe).

## 7. Safety checks (run in `prepare`, surfaced in `preview`)

Sanity list, all configurable per printer profile with conservative defaults:

- **Temperature bounds:** nozzle ≤ 260 °C, bed ≤ 100 °C by default; hard-fail above
  profile max. Scan the G-code for `M104/M109/M140/M190` values.
- **Material match:** G-code's material/temp range vs. the profile's loaded
  material; mismatch is a warning the user must acknowledge in the preview.
- **Bounds check:** model + G-code moves within the printer's declared build volume.
- **Duration flag:** jobs estimated > 12 h are flagged prominently (unattended risk).
- **State preconditions:** printer idle, not in error, no job running, before
  `execute` will attempt an upload.
- **File integrity:** the uploaded file's hash must equal the previewed hash — the
  user approves bytes, not a filename.

## 8. Open questions (decide before implementation)

- Bridge ⇄ web-Harvis transport when the user chats from the web: reuse the
  existing workspace SSE/event plumbing vs. a dedicated long-poll — decide with the
  CLI design (roadmap item 2).
- Webcam snapshot in status readback (OctoPrint offers it): nice for remote
  confidence, but adds image handling — defer unless trivial.
- Multi-printer queueing: out of scope for v1; one active job per profile.

## 9. Phasing

1. **P10.1** — `PrinterAdapter` protocol + `MockPrinterAdapter` + approval-token
   flow in the CLI, end-to-end against the mock.
2. **P10.2** — Slicer adapter (PrusaSlicer first) with allowlisted overrides.
3. **P10.3** — `OctoPrintAdapter` (upload + start + status), then Moonraker.
4. **P10.4** — Web status display via the bridge (read-only), audit surfacing.
