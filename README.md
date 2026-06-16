# Homelab

A small, Tailscale-only homelab. A Caddy reverse proxy terminates HTTPS on the
Tailscale IP and proxies to an Nginx container that serves a static dashboard
(landing page, overview shell with time-of-day greetings, and a live network
status page). A host-side Python collector feeds the status page with JSON.

Nothing is ever exposed to the public internet — the proxy binds only to the
machine's Tailscale IP, so only devices on your tailnet can reach it.

---

## Prerequisites

- **Fedora** (or any Linux) with **rootless Podman** and `podman compose`
- **Tailscale** installed and logged in (`tailscaled` running)
- **Python 3** with **psutil** (`sudo dnf install python3-psutil`) — for the status collector
- **firewalld** (default on Fedora)

---

## Project structure

```text
homelab/
├── compose.yaml                # Defines the two containers (proxy + dashboard)
├── .env                        # Your secrets/config — git-ignored (copy of .env.example)
├── .env.example                # Template for .env
├── .gitignore
├── README.md
├── LICENSE
│
├── apps/
│   └── dashboard/
│       ├── nginx.conf          # Nginx server block: maps clean URLs → page files
│       └── public/             # Web root (mounted read-only into the Nginx container)
│           └── homelab/
│               ├── pages/      # The HTML pages, served at /homelab/<name>
│               │   ├── landing.html    # Entry page with the house + "Step Inside"
│               │   ├── dashboard.html  # Overview shell (greeting, sidebar, top clock)
│               │   └── status.html     # Live network map of tailnet devices
│               ├── images/
│               │   ├── house-art.png   # Hand-drawn house on the landing page
│               │   └── mojis/          # Time-of-day greeting images
│               │       ├── morning.png # used by the dashboard greeting depending
│               │       ├── noon.png    #   on the current hour
│               │       ├── night.png
│               │       ├── late.png
│               │       └── fallback.png
│               └── api/        # GENERATED JSON (git-ignored) — written by the collector
│                   ├── status.json     # tailnet devices + network name (refreshed ~5s)
│                   └── config.json     # { "your_name": ... } from .env, for greetings
│
├── services/
│   ├── proxy/
│   │   └── Caddyfile           # TLS + reverse_proxy to the dashboard container
│   └── status-collector/
│       └── collect.py          # Host-side collector (Tailscale + network name → JSON)
│
└── data/                       # Runtime data, git-ignored
    └── proxy/                  # Caddy state + your Tailscale TLS cert/key live here
        ├── fedora.crt          # (named to match TLS_CERT in .env)
        └── fedora.key          # (named to match TLS_KEY in .env)
```

### What serves what

- **Caddy** (`proxy` container) binds `TAILSCALE_IP:80` and `:443`, serves HTTPS
  using the Tailscale cert, and reverse-proxies everything to `dashboard:80`.
- **Nginx** (`dashboard` container) serves `apps/dashboard/public` read-only.
  `nginx.conf` maps the clean URLs to the page files, e.g.
  `/homelab/landing` → `/homelab/pages/landing.html`.
- **collect.py** runs **on the host** (not in a container) because it needs the
  local Tailscale daemon. As a systemd *user* service it refreshes
  `api/status.json` and `api/config.json` every few seconds.

### Public routes

```text
/                    → 301 redirect to /homelab/landing
/homelab/landing     → landing.html
/homelab/dashboard   → dashboard.html
/homelab/status      → status.html
/homelab/api/*.json  → generated status/config data
```

---

## First-time setup

Run these once on the host, from the project root.

### 1. Your Tailscale domain (and enabling HTTPS)

Tailscale gives every device a stable name via **MagicDNS**, in the form:

```text
<machine-name>.<tailnet-name>.ts.net
```

For example, this homelab is reachable at:

```text
fedora.tail86b478.ts.net
```

- **`<machine-name>`** — the name of this machine in Tailscale, usually its
  system hostname. Here it's `fedora`.
- **`<tailnet-name>`** — a random ID unique to your account, like `tail86b478`.
  (Tailnets created without a custom org name get this auto-generated
  `tailXXXXXX` form.)

**Where to find them:**

- **Tailscale admin console** → <https://login.tailscale.com/admin/machines> —
  each machine row shows its name; clicking a machine shows the full
  `…ts.net` address. The tailnet name is also shown on the **DNS** page.
- **From the host:**

  ```bash
  tailscale status        # the "Self" line shows the machine name
  tailscale ip -4         # this machine's Tailscale IP (100.x.y.z) → TAILSCALE_IP
  # full MagicDNS name → TAILSCALE_HOST:
  tailscale status --json | python3 -c "import sys,json;print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))"
  ```

**Enable MagicDNS + HTTPS** (required before you can get a cert): in the admin
console → **DNS** → enable **MagicDNS**, then enable **HTTPS Certificates**.
Without this, `tailscale cert` will fail.

### 2. Get a TLS cert

Issue a cert for your full MagicDNS name (use *your* domain — `fedora.tail86b478.ts.net`
is just the example here):

```bash
tailscale cert fedora.tail86b478.ts.net   # creates fedora.tail86b478.ts.net.crt and .key
```

Move the cert + key into `data/proxy/` (create it if needed). You can rename
them to anything; just match `TLS_CERT`/`TLS_KEY` in `.env`:

```bash
mkdir -p data/proxy
mv fedora.tail86b478.ts.net.crt data/proxy/fedora.crt
mv fedora.tail86b478.ts.net.key data/proxy/fedora.key
```

On SELinux systems, label them so the container can read them:

```bash
chcon -t container_file_t data/proxy/fedora.crt data/proxy/fedora.key
```

### 3. Configure `.env`

```bash
cp .env.example .env
```

Then fill it in:

| Variable        | What it is                                                        |
|-----------------|------------------------------------------------------------------|
| `TAILSCALE_IP`  | This machine's Tailscale IP (`tailscale ip -4`)                  |
| `TAILSCALE_HOST`| Full MagicDNS name, e.g. `fedora.tail<...>.ts.net`              |
| `TLS_CERT`      | Cert filename inside `data/proxy/`, e.g. `fedora.crt`           |
| `TLS_KEY`       | Key filename inside `data/proxy/`, e.g. `fedora.key`            |
| `TZ`            | Container timezone, e.g. `Europe/Berlin`                        |

### 4. Open the firewall to the tailnet

The Tailscale interface isn't in a firewalld zone by default, so ports 80/443
are blocked for remote tailnet devices (it works locally but your phone can't
connect). Put `tailscale0` in the trusted zone:

```bash
sudo firewall-cmd --permanent --zone=trusted --add-interface=tailscale0
sudo firewall-cmd --reload
```

This only trusts the Tailscale interface — it does **not** open those ports on
your LAN/physical NIC.

### 5. Start the stack

```bash
podman compose up -d
```

Check it: `https://fedora.tail86b478.ts.net/` (your domain) from any tailnet device.

### 6. Run the status collector (systemd user service)

Create `~/.config/systemd/user/homelab-status.service`:

```ini
[Unit]
Description=Homelab status collector
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 %h/Projects/Others/homelab/services/status-collector/collect.py --interval 5
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

Enable it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now homelab-status.service
```

### 7. Make everything survive reboots

```bash
# user services run at boot without you logging in
sudo loginctl enable-linger $USER

# bring the containers back up on boot
systemctl --user enable podman-restart.service
```

> **Important:** the containers use `restart: always` in `compose.yaml`. This is
> required — `unless-stopped` does **not** auto-start them after a reboot under
> rootless Podman. Also, `podman compose down` *removes* the containers; after a
> `down` you must `podman compose up -d` once. Plain reboots/stops are fine.

---

## Day-to-day

```bash
podman compose up -d        # start / apply changes
podman compose restart      # restart both
podman ps                   # see what's running
systemctl --user status homelab-status.service
```

Editing the **HTML/images** under `apps/dashboard/public/` is live immediately
(Nginx serves them fresh per request). Editing **`nginx.conf`** or
**`compose.yaml`** requires recreating the container:
`podman compose up -d` (a bind-mounted config file won't hot-reload).

---

## Troubleshooting

- **Phone can't connect, but it works on the host** → firewall step 3 (the
  `tailscale0` trusted-zone rule) is missing or was reset.
- **Nothing on 80/443 after a reboot** → containers didn't auto-start; check
  they're `restart: always` and that `podman-restart.service` + linger are
  enabled (setup step 6). Recover now with `podman compose up -d`.
- **Status page shows no devices / stale data** → the collector isn't running:
  `systemctl --user status homelab-status.service`.
- **Cert errors in the browser** → use the `TAILSCALE_HOST` name (the cert is
  issued for it), not the raw IP.
```
