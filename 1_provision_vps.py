#!/usr/bin/env python3
"""Step 1 (standalone): provision a DigitalOcean droplet and return its public IP.

Run standalone:
    DIGITALOCEAN_API_TOKEN=dop_v1_... python 1_provision_vps.py [droplet-name]

Optional: attach SSH keys so the orchestrator can log in unattended.
    DO_SSH_KEY_IDS=12345678,90123456 ...   # numeric IDs or key fingerprints
"""

import os
import sys
import time

import requests

BASE_URL = "https://api.digitalocean.com/v2/droplets"
POLL_INTERVAL = 10   # seconds between status checks
MAX_WAIT = 300       # give up after 5 minutes


def _headers() -> dict:
    token = os.environ.get("DIGITALOCEAN_API_TOKEN")
    if not token:
        sys.exit("Set DIGITALOCEAN_API_TOKEN in your environment first.")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def provision_vps(name: str = "mail-server-01",
                  ssh_key_ids: list | None = None,
                  size: str = "s-1vcpu-1gb",      # $6/mo
                  image: str = "ubuntu-22-04-x64",
                  region: str = "nyc3") -> str | None:
    """Create a droplet and wait until it has an active public IP. Returns the IP."""
    payload = {"name": name, "size": size, "image": image, "region": region}
    if ssh_key_ids:
        payload["ssh_keys"] = ssh_key_ids

    print(f"Spawning droplet '{name}'...")
    resp = requests.post(BASE_URL, json=payload, headers=_headers(), timeout=30)
    if resp.status_code != 202:
        print("Failed to spawn server:", resp.status_code, resp.text)
        return None

    droplet_id = resp.json()["droplet"]["id"]
    print(f"Droplet created (ID: {droplet_id}). Waiting for IP allocation...")

    deadline = time.time() + MAX_WAIT
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        check = requests.get(f"{BASE_URL}/{droplet_id}", headers=_headers(), timeout=30)
        if check.status_code != 200:
            print("  Status check failed:", check.status_code, check.text)
            continue

        droplet = check.json()["droplet"]
        if droplet["status"] == "active":
            public = [n for n in droplet["networks"]["v4"] if n.get("type") == "public"]
            if public:
                ip = public[0]["ip_address"]
                print(f"SUCCESS! Your new VPS IP is: {ip}")
                if not ssh_key_ids:
                    print("No SSH key attached -- check your email for the root password.")
                return ip
        print(f"  ...still provisioning (status: {droplet['status']})")

    print(f"Gave up after {MAX_WAIT}s -- droplet never reported an active public IP.")
    return None


if __name__ == "__main__":
    drop_name = sys.argv[1] if len(sys.argv) > 1 else "mail-server-01"
    keys_env = os.environ.get("DO_SSH_KEY_IDS")
    keys = [k.strip() for k in keys_env.split(",")] if keys_env else None
    provision_vps(drop_name, keys)
