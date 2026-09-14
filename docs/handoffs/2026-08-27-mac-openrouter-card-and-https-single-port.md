# Handoff — 2026-08-27

Mac install session. One design agreed but not built, one feature built but
never run. Nothing was committed during that session.

**Updated later on 2026-08-27:** the OpenRouter card bug this doc opened with
has since been fixed on the `fixes` branch — §1 now records the real cause and
corrects the lead this doc originally ranked first.

---

## Where the branches stand

| Branch | Head | State |
|---|---|---|
| `main` | `d2480fc7` | Pushed. Tagged `docker-desktop-detect-2026-08-26`. |
| `harvis1.3` | `a0329d7b` | Clean, identical to `origin/harvis1.3`. |
| `fixes` | `46a0285e` | Added later on 2026-08-27. One commit ahead of `harvis1.3`, pushed to `origin/fixes`. Carries the OpenRouter fix in §1 plus the Engines-tab freeze, chat titles, Claude-lane web access, and SPA shell caching. |

A merge of `main` into `harvis1.3` was made in error and has been undone — the
branch was reset back to `a0329d7b` and nothing was ever pushed, so no published
history moved. **The two branches stay separate on purpose.** Dev work happens on
`harvis1.3`; we just don't work directly in `main`.

Consequence worth remembering: `harvis1.3` does **not** have the Docker Desktop
detection fix. That went to `main` only. It does have the `nginx -s reload` fix
in `scripts/enable-https.sh`.

Untracked in the working tree, deliberately: `docs/handoffs/2026-08-26-mac-install-and-security-pass.md`
and `database-backup/backups/`.

---

## 1. RESOLVED — the OpenRouter "add API key" card on macOS

**Fixed in `46a0285e` on the `fixes` branch.** No further work needed here.

**Symptom, as reported from the Mac:** the OpenRouter card in Integrations
couldn't be opened to the point of entering an API key.

**Actual cause:** `IntegrationDetailModal.svelte` guarded `def.commands` in the
outer `#if`, then read `def.commands.install`, `.launch`, and `.check`
unguarded inside it. Every card that has setup steps but no CLI commands —
OpenRouter, Discord, Groq — threw before the drawer could render. The fix is
optional chaining on each read:

```diff
-{#if def.commands.install}
-	<CommandBlock label={$i18n.t('Install')} command={def.commands.install} />
+{#if def.commands?.install}
+	<CommandBlock label={$i18n.t('Install')} command={def.commands?.install} />
```

**Correction to what this doc originally said.** It ranked "the bundle on the
Mac isn't built from this source" as the most likely lead, on the strength of
the owui build's two silent-failure modes. **That was wrong** — the bug was a
genuine render failure in the card, reachable from correct source. The lesson
is the one the doc itself stated and then didn't follow: get the console error
before ranking leads. Two things it correctly ruled out (duplicate catalog
entries, a missing `authEngine` mapping) were in fact not the cause.

**Still genuinely open, just unrelated to this bug:** `front_end/owui/Dockerfile:31`
still has `# ENV NODE_OPTIONS="--max-old-space-size=4096"` commented out and
`owui-builder` has no memory limit in compose, so the build can still OOM and
exit 0 on a memory-constrained Mac. That belongs to the punchlist in §5, not
here.

---

## 2. HTTPS on one port — designed, agreed, not built

Decision: HTTPS should be **on by default**, on the **same port** as HTTP, so
there's no `:9000` vs `:9443` swapping.

### How

nginx raises an internal `497` when a plain HTTP request hits a TLS port. Catch
it and bounce:

```
listen 80 ssl;                                     # host :9000
error_page 497 =301 https://$http_host$request_uri;
```

`$http_host` keeps the port the client actually typed, so `http://box:9000`
lands on `https://box:9000`. Keep `:9443` published and serving TLS too, so
existing bookmarks and docs don't break.

### The constraint that shapes everything

`listen 80 ssl` needs the certificate to exist **at config-parse time**. No cert
means nginx won't start, which takes the whole front door down. And two server
blocks can't share port 80 with different `ssl` flags, so the existing
"glob a directory, an empty match is harmless" trick can't carry this.

**Chosen approach:** select the listener file through compose.

```yaml
- ./nginx/${HARVIS_LISTENER_CONF:-listener-http.conf}:/etc/nginx/listener.conf:ro
```

Both `nginx/listener-http.conf` and `nginx/listener-tls.conf` are tracked and
never edited in place. Enabling HTTPS is one `.env` key — the same mechanism
`write_env()` already uses for everything else. A fresh clone with no `.env`
gets plain HTTP and works. Turning it off again is the same one-line flip.
The installer generates the cert *before* writing the key, and refuses to select
the TLS listener if the cert file isn't there.

### Four things that must move together

Found by grepping for scheme-dependent consumers. Miss any and the install
reports a false failure:

- `install.sh:50-51` — `HEALTH_URL` and `SETUP_URL` are `http://localhost:9000`.
  After the swap `curl` gets a 301 and an empty body, and the installer would
  announce the stack never came up. Needs `https` and `-k`.
- `nginx.conf:45-46` — the CORS origin map has `http://…:9000` and
  `https://…:9443`. Add the `https://…:9000` pair.
- `docker-compose.yaml:496` — `OAUTH_REDIRECT_BASE: "http://localhost:9000"`.
  OAuth callbacks must match the browser's scheme; make it a variable.
- `HARVIS_COOKIE_SECURE` — **leave it `false` for this change.** With no plain
  lane left it could safely be `true`, but a `Secure` cookie plus any certificate
  problem is a lockout on a machine we can't reach, and this ships to strangers.
  Flip it in a separate, deliberate step.

Leave `k8s-manifests/` alone — separate deployment path, separate decision.

### macOS bug in the cert script, fix this alongside

`scripts/enable-https.sh` detects the LAN address with `ip -o -4 addr show` and
falls back to `hostname -I`. **Neither exists on macOS** — `ip` isn't a command
there and macOS `hostname` has no `-I`. On a Mac the certificate comes out
covering localhost only, and HTTPS from a phone then fails on a SAN mismatch,
which is a harder wall than the ordinary self-signed warning.

Also: `openssl req -addext` is used unconditionally. macOS ships LibreSSL, and
older versions (Catalina-era 2.8.3) don't have `-addext`. Probe once and fall
back to a generated temp `openssl.cnf` with a SAN section.

### Build order

1. `nginx/listener-http.conf` + `nginx/listener-tls.conf`; point `nginx.conf` at
   the single include and retire the `tls/*.conf` glob.
2. Compose: variable listener mount, `OAUTH_REDIRECT_BASE` from a variable.
3. macOS fixes in `enable-https.sh`, plus a `--no-apply` mode so the installer
   can call it before any container exists.
4. `install.sh`: `--https` / `--no-https`, default on, prompt shaped like the
   OpenClaw one. Missing `openssl` warns, never fails. Health URLs follow the choice.
5. Verify on the Linux box: both schemes on `:9000`, `:9443` still serving, a real
   login on each, `bash -n`, and a bash-3.2 read for the Mac target.

---

## 3. OpenClaw install prompt — built, never run, parked

Asks at install time whether to include the bundled OpenClaw gateway, defaulting
**yes** (it's the main gateway Harvis ships). `bash -n` passes. **It has never
been executed.** Not on any branch.

Preserved as clean patches at `~/.harvis-wip/2026-08-27-openclaw-prompt/`:

| File | What |
|---|---|
| `openclaw-prompt.patch` | 160-line diff against `origin/main`'s `install.sh` |
| `openclaw-profile.patch` | adds `"openclaw"` to the `profiles:` list on `openclaw` and `openclaw-db-init` |
| `install.sh`, `docker-compose.yaml` | full modified copies |
| `*.main-base` | the `origin/main` originals the diffs were taken against |

Note the base: those patches sit on **`main`'s** `install.sh`, which includes the
Docker Desktop fix. Applying them to `harvis1.3` means re-applying the OpenClaw
hunks onto 1.3's own `install.sh` — not dropping main's file over it, which would
smuggle main's changes into 1.3 through the back door.

The compose half applies cleanly to either branch. It was verified with
`docker compose config --quiet`, and `--profile openclaw` yields exactly the two
expected services.

Still to do: run `--check-only`, `--openclaw`, `--no-openclaw`, and the
interactive default before this lands anywhere.

---

## 4. Decisions still needed

1. **Does the Docker Desktop fix get cherry-picked from `main` onto `harvis1.3`?**
   It's a Mac install fix and the Mac install is the active work, but 1.3 is meant
   to stay independent of main. One commit, `d2480fc7`.
2. **Where does `docs/handoffs/2026-08-26-mac-install-and-security-pass.md` live?**
   It documents the Docker fix, which is on `main`. Still untracked.
3. **Which branch takes the HTTPS work?** Assumed `harvis1.3` unless told otherwise.

---

## 5. Rest of the punchlist

- `front_end/owui/Dockerfile:31` — uncomment `NODE_OPTIONS`, and give
  `owui-builder` a memory limit. Promoted from housekeeping to a suspect by lead
  (a) above.
- `python_back_end/plugins/cron/scheduler.py` — the module docstring still claims
  the tick loop is "intentionally not wired here." It **is** wired:
  `main.py:1199-1200` starts it, `:1227` stops it, `:1775-1778` registers the
  router. The comment is stale and misleading.
- **Automation spec** — investigation done, document not written. The scheduler is
  roughly 80% built already (`plugins/cron/` plus a 742-line `Automations.svelte`
  and its API client). The spec should extend that, not rebuild it.
- **Security pass** — XSS (30 sinks across 21 files, all safe), SQLi (25 f-string
  sites, all identifiers from closed server-side maps) and SSRF (connections
  pinned, each redirect hop re-validated) all came back clean. Two items left:
  confirm the pinning in `openclaw_proxy._ensure_resolved_addresses_public`, and
  run the performance pass — start with the sequential probes in
  `integrations_status.py`.

---

## Deploy reminders

- Backend: `docker compose restart backend` (`owui_compat/` is bind-mounted).
- Frontend: `npm run build` in `front_end/owui/`, then `docker compose restart nginx`.
- Run everything from the repo checkout the stack is deployed from — the deployed
  stack bind-mounts the main checkout, not a worktree.
