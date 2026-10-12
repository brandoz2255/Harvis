# Security Policy

## Known Vulnerabilities

### xlsx (sheetjs) - High Severity

**Status:** ⚠️ Known issue, no fix available from upstream

**Vulnerabilities:**
- GHSA-4r6h-8v6p-xvw6 - Prototype Pollution in sheetJS
- GHSA-5pgg-2g8v-p4x9 - SheetJS Regular Expression Denial of Service (ReDoS)

**Impact:** The `xlsx` package is used only for previewing Excel files in the `XlsxPreview` component. It does not process untrusted user input for file generation or server-side operations.

**Mitigation:**
- The package is only used client-side for rendering Excel file previews
- No server-side processing uses this library
- Files are processed in isolated browser context

**Planned Action:**
Migrate from `xlsx` to `exceljs` or remove XLSX preview functionality in a future release.

## Reporting Security Issues

Please do not open a public issue for a vulnerability. Report it privately
through GitHub: the repository's **Security** tab → **Report a vulnerability**
(https://github.com/brandoz2255/Harvis/security/advisories/new). Include what
you found, how to reproduce it, and the exposure mode the server was in.

## Who can reach your Harvis

Harvis is self-hosted: whoever runs the server is responsible for who can reach
it. The installer's `--expose` option (`-Expose` on Windows) sets this, and the
backend applies matching rules.

| Mode | Who can reach it | What changes |
|---|---|---|
| `local` | This computer only (port 9000 on 127.0.0.1) | Nothing; the first sign-up becomes admin |
| `lan` | Anyone on the same network | The first sign-up becomes admin, so sign up right after installing; self-serve sign-up is closed until the admin opens it in Settings (an `.env` that already says `HARVIS_OWUI_ENABLE_SIGNUP=true` keeps it open, and the installer warns); running code (Build Space, terminals, CAD, engines, kubectl) and downloading models are for admins; everyone keeps chat, notebooks, image generation and their own run results |
| `tunnel` (experimental) | The internet, through a Cloudflare Tunnel behind Cloudflare Access | Everything in `lan`, plus: every request must carry a valid Cloudflare Access token, checked again by Harvis; sign-up and sign-in must use the email Access verified; Cloudflare traffic that skips the `nginx:8081` entrance is refused; cloudflared sits on a network of its own with nginx, so it cannot reach the backend, Ollama or the database by name, but under Docker it can still reach this computer and your network by address, so route the public hostname only to `http://nginx:8081`; nothing is opened on the router |
| `lan+tunnel` (experimental) | Both: anyone on the network at port 9000, and the internet through Cloudflare Access | The `lan` rules on port 9000 and the `tunnel` rules on the Cloudflare entrance. Under Kubernetes, network policy lets cloudflared open only `nginx:8081` and the internet (no private addresses), and only cloudflared may open 8081 |

Without `--expose`, the installer picks for the host: a new install is `local`;
`--k8s` is `lan` (Kubernetes puts Harvis on the network, so sign-up
closes once the admin exists) unless `.env` records `lan+tunnel`; plain
`tunnel` is refused there, use `--k8s --expose lan+tunnel`; an install whose
running nginx already publishes port 9000 to the network keeps it open and
warns; anything else becomes `local`. Running `docker compose up` without the
installer also keeps ports 9000/9443 on 127.0.0.1 unless `.env` sets
`HARVIS_BIND_ADDR_PUBLIC=0.0.0.0`. On a shared server
(`lan`, `tunnel` or `lan+tunnel`) the backend refuses to start with a guessable `JWT_SECRET`,
and in the tunnel modes without the Cloudflare Access settings. To let non-admins
run code anyway, set `HARVIS_BUILD_SPACE_ACCESS=everyone` in `.env`.

The tunnel modes are experimental. Their checks pass against a stand-in for
Cloudflare, but no install has yet been reached through a real Cloudflare
account; for a server people use today, choose `lan`. The tunnel code lives in
the backend's `plugins/tunnel` package and is not loaded at all unless
`HARVIS_EXPOSURE` is `tunnel` or `lan+tunnel`: a `local` or `lan` server serves
no tunnel route and runs none of its checks.

### Tunnel: the regular profile and the lab profile

**Regular** (`--expose tunnel` alone) is the standard Cloudflare setup: the
Access policy you write in Cloudflare decides who gets in, Harvis checks the
Access token again, and the installer warns if this computer is on eduroam.
Most installs want this.

Two options tighten it. They are off unless you set them:

- `--allow-emails a@school.edu,b@school.edu` (`-AllowEmails` on Windows; `@school.edu`
  allows a whole domain) writes `HARVIS_CF_ACCESS_ALLOWED_EMAILS`. Harvis then
  refuses anyone else even when the Access policy is wider, and refuses service
  tokens, which carry no email. Works on every platform.
- `--tunnel-networks lab-wifi,lab-wired` writes `HARVIS_TUNNEL_NETWORKS`. The tunnel
  then runs only while every network this computer is using is on the list (every interface with a
  default route, and whichever one carries traffic to Cloudflare): Wi-Fi
  by the name of the network it is connected to, anything else by its
  NetworkManager connection name. On eduroam, on an unknown network, while a
  network is connecting, or with no network, the tunnel is stopped. A systemd
  user service (`scripts/tunnel-guard.sh`) does this and re-checks on every
  network change and every 30 seconds. Docker never starts the tunnel by itself
  under the lock, and when the service stops, the tunnel stops. Linux with
  NetworkManager only; `install.ps1` refuses a `.env` that carries the lock.
  This is the lab profile. `--allow-emails` is optional with it: without a list,
  the Access policy in Cloudflare alone decides who gets in, so make it narrow.

Under the lab profile the tunnel runs only while you are signed in to that
computer, unless you run `loginctl enable-linger $USER` once. Under Kubernetes
the guard is a system service instead: it runs from boot, scales the tunnel
between 0 and 2 copies, and while the cluster API is down or k3s is stopped it
stops the tunnel's containers directly, every 3 seconds. Check it at any
time with `scripts/tunnel-guard.sh status`. Either option takes `off` to remove it.

What the lab profile does not cover: a Wi-Fi network is judged by its name, so
a nearby network that copies an allowed name would pass. A wired connection is
judged by the name of the profile you saved, and a profile not tied to one
adapter connects on any jack; the installer warns about that and shows the
`nmcli` command that ties it. Starting cloudflared by hand
(`docker compose --profile tunnel up`) bypasses the guard until its next check,
at most 30 seconds later. The Access policy in Cloudflare is still the first
gate; set it to the same people.

A site that always installs the same way can keep these choices in
`config/presets/NAME.env` (keys `EXPOSE`, `TUNNEL_NETWORKS`, `ALLOW_EMAILS`)
and run `./install.sh --preset NAME`. Git ignores that folder, so a site's
network names and people stay on its own machines; options on the command line
win over the preset. `ALLOW_EMAILS=off` says the site keeps no list (and clears
an old one); leaving the key out keeps whatever `.env` already has.

Before hosting Harvis for other people, get permission from whoever owns the
machine and the network it runs on.

## Security Updates

This project uses automated dependency updates via npm audit. Critical and high severity vulnerabilities are addressed as soon as fixes are available from upstream maintainers.
