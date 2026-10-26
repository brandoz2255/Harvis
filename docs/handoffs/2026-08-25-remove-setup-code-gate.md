# Handoff — the setup code is gone, and the VM can't rebuild its own frontend

**Date:** 2026-08-25
**Branch:** `claude/jolly-dhawan-5babcd` (worktree), on top of `test/fresh-clone-2026-08-23` @ `21d82e71`
**State:** implemented, compiled, deployed to the test VM, **uncommitted**
**Test bed:** VM 901 `harvis-blank` — `http://192.168.10.201:9000`, `ssh ommblitz@192.168.10.201`

---

## 1. What changed and why

`install.sh` used to mint a `HARVIS_SETUP_CODE` into `.env`, print it once, and refuse the first
signup without it. That protected exactly one thing — the admin seat on an unclaimed instance —
and charged every single install a code-hunt to do it. On a laptop nobody can race you to that
seat, so the friction bought nothing.

**Now:** the first signup claims admin outright, the way OpenWebUI and Jellyfin do it. The gate
still exists as an opt-in: set `HARVIS_SETUP_CODE` in `.env` by hand and the first signup demands
it again. Nothing generates one.

The backend advertises which mode it is in as `features.setup_code_required`, so the signup form
asks for a code only when the server will actually check one. Those two must stay in lockstep —
a mismatch either shows a field nothing validates, or hides one the server demands (that second
case is the "double lockout" already on record in
`docs/reports/2026-07-20-windows-install-e2e-findings.md` as F-05).

## 2. Files touched

| File | Change |
|---|---|
| `python_back_end/main.py` | `_signup_with_connection` — the unset-code branch flipped from fail-closed (403 "not configured") to fail-open. Gate now runs only when `HARVIS_SETUP_CODE` is set and non-empty. Stale comment in `_signup_enabled()` corrected. |
| `python_back_end/owui_compat/config.py` | New `features.setup_code_required`, mirroring the env var. Neighbouring comment corrected. |
| `install.sh` | Stops generating the code. `print_setup_code()` → `print_first_admin()`, which says "the first account you sign up with becomes the admin" unless an operator set a code. |
| `docker-compose.yaml` | `HARVIS_SETUP_CODE` comment rewritten as OPTIONAL; the `HARVIS_OWUI_ENABLE_SIGNUP` comment no longer claims the setup code prevents hijack. |
| `front_end/owui/src/routes/auth/+page.svelte` | `setupCodeRequired` derived from the new flag; field, required-check and submitted header all gate on it. |
| `front_end/owui/src/routes/setup/+page.svelte` | Same, plus the step-0 blurb now has two variants. |
| `front_end/owui/src/lib/apis/auths/index.ts` | Comment only — the client already sent the header conditionally. |
| `python_back_end/create_test_user.py` | Refusal message no longer references the code. |

## 3. What was verified, and what wasn't

Verified live on VM 901:

- Local `vite build` with these changes: **exit 0**, `✓ built in 1m 22s`.
- Both edited Svelte pages compile clean through `vitePreprocess` + the Svelte compiler.
- `python -m py_compile`, `bash -n install.sh`, compose YAML parse: all clean.
- With no code set: `features.setup_code_required: false`, `onboarding: true`.
- With `HARVIS_SETUP_CODE` set: flag flips `true`; signup with **no** code → **403**; signup with a
  **wrong** code → **403**; `users` table still `0`. The opt-in gate genuinely bites.
- Rebuilt bundle on the VM references `setup_code_required` in 5 chunks — the new logic is in the
  served JS, not just the source.
- From the laptop: `/` and `/auth` both 200, health `healthy`, `model_provider: up`.

**Not verified:** an actual successful codeless signup. Completing it creates the admin account,
which is yours to make. That is the one remaining assertion — sign up at
`http://192.168.10.201:9000` with no code and it should just work. If it 403s, the gate inverted
wrong and `main.py` `_signup_with_connection` is the only place to look.

## 4. ⚠ Separate defect found — the VM cannot rebuild its own frontend while the stack runs

`npm run build` requests an 8 GB Node heap (`NODE_OPTIONS=--max-old-space-size=8192`). VM 901 has
7 GB total and ~1 GB free with the stack up. The build reached "rendering chunks" and died:

```
npm error signal SIGKILL
npm error command sh -c npm run pyodide:fetch && NODE_OPTIONS=--max-old-space-size=8192 vite build
```

That is the OOM killer, not a code error — the identical source built fine on the laptop.

Worse, the failure is silent: the `owui-builder` container then printed
`owui build already present in ./front_end/owui/build — skipping` and **exited 0**, so
`docker compose up -d` reported success while serving the previous bundle. A failed frontend
build currently looks like a good deploy.

Workaround used: `docker compose down` → `sudo rm -rf front_end/owui/build` →
`docker compose build owui-builder` → `docker compose up -d`. With 6 GB free it built in 2m 21s.

Worth fixing properly, in rough order of value:
1. Make the builder **fail loudly** when the image build failed — the skip-if-present branch should
   not mask it.
2. Drop `--max-old-space-size` to something a 8 GB box can honour, or set it from available RAM.
3. Document the RAM floor for a from-source install in the README prerequisites.

## 5. Other open items from this session

- **Existing installs still carry a `HARVIS_SETUP_CODE` in `.env`.** With an admin already created
  the gate never fires, so nothing breaks — but an unclaimed instance with a stale code will still
  demand it. Deleting the line is the migration; there is no automated one.
- **`HARVIS_OWUI_ENABLE_SIGNUP` defaults to `true`.** Post-change this is the flag that matters for
  an exposed box: anyone who can reach port 9000 can self-register an ordinary account. Fine for the
  lab VM, not fine for anything internet-facing.
- **VM 901's `.env` now has `HARVIS_LLM_BASE_URL=http://192.168.10.244:11434`** pointing at the
  laptop's Ollama. That only works while the laptop is on the same network — on campus it will not
  resolve, so point it at whatever model server is reachable there, or install Ollama on the VM.

## 6. Picking this up tomorrow

The worktree is dirty with **unrelated** work of yours that must not be swept into a commit:
`front_end/owui/src/lib/integrations/{BrandGlyph.svelte,ConnectionPanel.svelte,catalog.ts,status.ts}`,
`python_back_end/owui_compat/{cloud_chat.py,engine_auth.py,free_providers.py,integrations_status.py}`,
and `docs/handoffs/2026-08-01-agent-reach-and-skillopt.md`. The eight files in §2 are the whole of
this change and should be committed on their own.

Nothing here is committed or pushed.
