# Homelab

Small Tailscale-only homelab dashboard served by Caddy and Nginx.

The dashboard currently includes a landing page, an overview shell with
time-of-day greetings/mojis, and a live status page backed by generated JSON.

## Layout

```text
apps/
  dashboard/
    nginx.conf              # Nginx routes for the static dashboard
    public/
      homelab/
        pages/              # HTML pages served as /homelab/...
        images/             # Browser-facing images
          mojis/            # Time-of-day greeting images
        api/                # Generated JSON read by the pages

services/
  proxy/
    Caddyfile               # TLS + reverse proxy to the dashboard container
  status-collector/
    collect.py              # Host-side collector for Tailscale/status data

data/
  proxy/                    # Runtime Caddy/Tailscale cert data, git-ignored
```

## How It Works

`compose.yaml` starts two containers:

- `proxy`: Caddy binds to the Tailscale IP, serves HTTPS, and reverse-proxies to Nginx.
- `dashboard`: Nginx serves the static files from `apps/dashboard/public`.

The status collector runs on the host, outside the containers, because it needs access to the local Tailscale daemon. It writes public, safe-to-expose JSON into:

```text
apps/dashboard/public/homelab/api/status.json
apps/dashboard/public/homelab/api/config.json
```

Those generated JSON files are ignored by Git.

## Source vs Runtime

Source files live in `apps/`, `services/`, `compose.yaml`, and `.env.example`.

Runtime/local files are ignored:

- `.env`
- `data/`
- generated dashboard API JSON

The public dashboard routes are:

```text
/homelab/landing
/homelab/dashboard
/homelab/status
```
