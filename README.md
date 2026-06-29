# AutoCheapMail Orchestration Pipeline

The **AutoCheapMail** pipeline is an automated solution designed to spin up a fully functional, self-hosted mail server from scratch. The automation handles domain registration, cloud infrastructure provisioning, DNS configuration, and mail server deployment.

---

## 🚀 Overview of the Pipeline

The automation is split into sequential steps:

* **`1_provision_vps.py`**: Spawns a DigitalOcean droplet and waits for IP allocation.
* **`2_register_domain.py`**: Interactively checks for and registers an affordable domain via Porkbun, then configures initial DNS records (`A`, `MX`, `SPF`, `DMARC`).
* **`3_deploy_mailserver.sh`**: Installs Docker, sets up Let's Encrypt TLS certificates via Certbot, deploys the `docker-mailserver` container, and optionally creates initial mailboxes and DKIM keys.
* **`run_all.py`**: An orchestrator script that ties the entire process together in a single automated flow. It modifies the standard execution order to ensure the droplet's hostname perfectly matches the mail server's Fully Qualified Domain Name (FQDN) for proper reverse DNS (PTR) alignment.

---

## 📋 Prerequisites

Before running the pipeline, ensure you have the following:

* A **DigitalOcean** account with an active API token and an uploaded SSH key ID.
* A **Porkbun** account with API access enabled (via Account > Domain Management > API Access) and your API keys handy.
* An environment with `python3`, `requests`, `certbot`, and standard SSH/SCP utilities installed.

---

## ⚙️ Environment Variables & Configuration

You will need to set up your environment variables before running the orchestrator.

### 1. Porkbun API Keys

Open `2_register_domain.py` and insert your credentials at the top:

```python
API_KEY    = "pk1_your_porkbun_api_key"        # starts with pk1_
SECRET_KEY = "YOUR_PORKBUN_SECRET_KEY"     # starts with sk1_

```

### 2. Export Orchestrator Variables

Before executing `run_all.py`, configure your terminal environment:

```bash
# DigitalOcean Configuration
export DIGITALOCEAN_API_TOKEN="dop_v1_your_digitalocean_token"
export DO_SSH_KEY_IDS="12345678"         # Numeric ID or fingerprint of your DO SSH key
export SSH_KEY_PATH="~/.ssh/id_ed25519"  # Local path to your private SSH key

# Optional: Auto-create a mailbox upon deployment
export MAIL_USER="you@yourdomain.xyz"
export MAIL_PASS="your-secure-password"

# Run the pipeline
python3 run_all.py

```

---

## 📌 Post-Deployment & Next Steps

Because DNS propagation and cloud provider policies cannot be fully bypassed by automation, you will need to complete a few manual steps once the script finishes:

1. **Add the DKIM Record**: The deploy script will generate a DKIM key. Retrieve the value by running:
```bash
cat /opt/docker-mailserver/mail-config/opendkim/keys/YOUR-DOMAIN.XYZ/mail.txt

```


Log into Porkbun and create a **TXT** record with the name `mail._domainkey.YOUR-DOMAIN.XYZ` pointing to that string.
2. **Open Port 25**: DigitalOcean blocks outbound port 25 by default to prevent spam. You must open a support ticket with DigitalOcean requesting them to unblock outbound port 25 for your droplet so you can send emails to external providers (receiving works immediately).
3. **Managing Mailboxes**: You can add more mailboxes at any time by running the setup utility directly on your VPS:
```bash
cd /opt/docker-mailserver
./setup.sh email add user@yourdomain.xyz password

```
