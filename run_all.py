#!/usr/bin/env python3
"""
The whole process in one command: register a domain, provision a droplet named
after it, point DNS at it, wait for propagation, then deploy the mail server on
the droplet over SSH.

Order matters and differs from 1->2->3:
  (2) register the domain first  -> so we can name the droplet mail.<domain>
                                     (matching reverse DNS) and set DNS before
                                     the mail server requests a TLS cert.
  (1) provision droplet 'mail.<domain>' with an SSH key attached.
  (2) configure DNS (A/MX/SPF/DMARC) pointing at the new IP.
   *  wait for mail.<domain> to resolve to that IP.
  (3) copy + run the deploy script on the droplet via SSH.

Usage:
    export DIGITALOCEAN_API_TOKEN=dop_v1_...
    export DO_SSH_KEY_IDS=12345678          # SSH key ID(s) on your DO account
    export SSH_KEY_PATH=~/.ssh/id_ed25519   # matching private key (optional)
    export MAIL_USER=you@yourdomain.xyz     # optional: auto-create this mailbox
    export MAIL_PASS=...                    # optional
    python run_all.py

Step 2 still needs its Porkbun API_KEY/SECRET_KEY filled in, and you'll confirm
the domain purchase interactively.
"""

import importlib.util
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STEP1_PATH  = os.path.join(HERE, "1_provision_vps.py")
STEP2_PATH  = os.path.join(HERE, "2_register_domain.py")
DEPLOY_PATH = os.path.join(HERE, "3_deploy_mailserver.sh")

DNS_WAIT_TIMEOUT = 900   # seconds to wait for DNS to propagate
SSH_WAIT_TIMEOUT = 180   # seconds to wait for sshd to come up


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolves_to(hostname, ip, timeout=5):
    try:
        socket.setdefaulttimeout(timeout)
        infos = socket.getaddrinfo(hostname, None)
        return any(info[4][0] == ip for info in infos)
    except (socket.gaierror, socket.timeout, OSError):
        return False


def wait_for_dns(hostname, ip):
    print(f"\nWaiting for {hostname} to resolve to {ip} (up to {DNS_WAIT_TIMEOUT // 60} min)...")
    deadline = time.time() + DNS_WAIT_TIMEOUT
    while time.time() < deadline:
        if resolves_to(hostname, ip):
            print(f"  {hostname} now resolves to {ip}.")
            return True
        print("  ...not resolving yet, retrying in 30s")
        time.sleep(30)
    print(f"  Gave up after {DNS_WAIT_TIMEOUT}s. You can run the deploy step manually later.")
    return False


def ssh_opts():
    opts = ["-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15"]
    key = os.environ.get("SSH_KEY_PATH")
    if key:
        opts += ["-i", os.path.expanduser(key)]
    return opts


def wait_for_ssh(ip):
    print(f"Waiting for SSH on {ip} ...")
    deadline = time.time() + SSH_WAIT_TIMEOUT
    while time.time() < deadline:
        try:
            with socket.create_connection((ip, 22), timeout=10):
                print("  SSH is up.")
                return True
        except OSError:
            time.sleep(10)
    print("  SSH didn't come up in time.")
    return False


def deploy_remote(ip, domain):
    user = os.environ.get("MAIL_USER", "")
    pw = os.environ.get("MAIL_PASS", "")
    target = f"root@{ip}"

    print(f"\nCopying deploy script to {target} ...")
    subprocess.run(["scp", *ssh_opts(), DEPLOY_PATH, f"{target}:/root/deploy_mailserver.sh"],
                   check=True)

    remote_cmd = f"bash /root/deploy_mailserver.sh {domain} {user} {pw}".strip()
    print("Running deploy script on the droplet (this takes a few minutes)...\n")
    subprocess.run(["ssh", *ssh_opts(), target, remote_cmd], check=True)


def main():
    step2 = load_module(STEP2_PATH, "step2_domain")
    step1 = load_module(STEP1_PATH, "step1_provision")

    if not os.environ.get("DO_SSH_KEY_IDS"):
        sys.exit("Set DO_SSH_KEY_IDS so the orchestrator can SSH into the droplet "
                 "(or run the three scripts manually instead).")
    ssh_key_ids = [k.strip() for k in os.environ["DO_SSH_KEY_IDS"].split(",")]

    # (2) Register the domain first.
    domain, _ = step2.select_and_register()
    fqdn = f"mail.{domain}"

    # (1) Provision a droplet named after the mail host (so DO sets a matching PTR).
    ip = step1.provision_vps(name=fqdn, ssh_key_ids=ssh_key_ids)
    if not ip:
        sys.exit("Provisioning failed; domain is registered but no server was created.")

    # (2) Point DNS at the new server.
    step2.configure_dns(domain, ip)

    # Wait for propagation so the cert step in (3) can succeed.
    wait_for_dns(fqdn, ip)

    # (3) Deploy the mail server on the droplet.
    if wait_for_ssh(ip):
        try:
            deploy_remote(ip, domain)
        except subprocess.CalledProcessError as e:
            print(f"\nRemote deploy failed ({e}). You can re-run manually:")
            print(f"  scp 3_deploy_mailserver.sh root@{ip}:/root/")
            print(f"  ssh root@{ip} 'bash /root/deploy_mailserver.sh {domain}'")
            return

    print("\n" + "=" * 60)
    print(f"Pipeline finished for {domain}  (server: {ip})")
    print("Remember: add the DKIM TXT record the deploy step printed, and open")
    print("outbound port 25 with DigitalOcean before you can send mail.")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
