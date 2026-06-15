#!/usr/bin/env python3
"""Collect the tailnet device list + network name and write it as JSON into the
dashboard site dir for the status page (a network map) to fetch.

Runs on the host (not in a container) so it can reach the Tailscale socket.
Intended as a long-lived systemd user service:

    python3 collect.py --interval 5

Without --interval it writes a single snapshot (handy for testing).
"""
import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
ENV_FILE = os.path.join(ROOT, ".env")
SITE = os.path.join(ROOT, "apps", "dashboard", "public", "homelab")
API_DIR = os.path.join(SITE, "api")
OUT = os.path.join(API_DIR, "status.json")
CONFIG_OUT = os.path.join(API_DIR, "config.json")


def load_env():
    values = {}
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def config_payload():
    env = load_env()
    return {
        "your_name": env.get("YOUR_NAME") or "",
    }


def classify(os_name, name):
    """Best-effort device type from Tailscale's OS field + hostname."""
    o = (os_name or "").lower()
    n = (name or "").lower()
    if "ipad" in n:
        return "tablet"
    if o == "ios":
        return "phone"
    if o == "android":
        return "phone"
    if o == "macos":
        return "laptop"
    if o == "windows":
        return "pc"
    if o == "linux":
        return "pc"
    return "pc"


def collect():
    raw = subprocess.run(
        ["tailscale", "status", "--json"],
        capture_output=True, text=True, timeout=15, check=True,
    ).stdout
    data = json.loads(raw)
    network = data.get("MagicDNSSuffix") or "tailnet"

    def shape(node, is_self=False):
        dns = (node.get("DNSName") or "").rstrip(".")
        short = dns.split(".")[0] if dns else (node.get("HostName") or "device")
        ips = node.get("TailscaleIPs") or []
        ipv4 = next((ip for ip in ips if ":" not in ip), ips[0] if ips else None)
        os_name = node.get("OS") or ""
        return {
            "name": short,
            "os": os_name,
            "ip": ipv4,
            "online": bool(node.get("Online")),
            "self": is_self,
            "kind": classify(os_name, short),
        }

    devices = [shape(data["Self"], is_self=True)]
    for peer in (data.get("Peer") or {}).values():
        devices.append(shape(peer))
    devices.sort(key=lambda d: (not d["self"], not d["online"], d["name"].lower()))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "network": network,
        "devices": devices,
    }


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)
    # keep SELinux label consistent with the rest of the bind-mounted site dir
    try:
        subprocess.run(["chcon", "--reference", SITE, path],
                       capture_output=True, timeout=5)
    except (subprocess.SubprocessError, OSError):
        pass


def write(payload):
    write_json(OUT, payload)
    write_json(CONFIG_OUT, config_payload())


def safe_collect():
    try:
        return collect()
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError, KeyError):
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "network": "tailnet",
            "devices": None,
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=None,
                    help="seconds between refreshes; omit for a single snapshot")
    args = ap.parse_args()
    if args.interval:
        while True:
            write(safe_collect())
            time.sleep(args.interval)
    else:
        write(safe_collect())


if __name__ == "__main__":
    main()
