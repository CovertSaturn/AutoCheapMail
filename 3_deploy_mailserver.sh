#!/bin/bash
# Step 3 (standalone): install Docker, obtain a TLS cert, and deploy
# docker-mailserver. Run this ON the droplet (as root).
#
# Usage:
#   bash 3_deploy_mailserver.sh <domain> [email] [password]
#   e.g.  bash 3_deploy_mailserver.sh autocheapmail.xyz user@autocheapmail.xyz s3cret
#
# Requirements before running:
#   * DNS for mail.<domain> must already resolve to THIS server's IP
#     (Let's Encrypt validates over HTTP on port 80, which must be free).
#   * Outbound port 25 is blocked by default on most clouds (incl. DigitalOcean);
#     open a support ticket to send mail. Receiving still works without it.
set -euo pipefail

DOMAIN="${1:?Usage: bash 3_deploy_mailserver.sh <domain> [email] [password]}"
EMAIL="${2:-}"
PASSWORD="${3:-}"
FQDN="mail.${DOMAIN}"

echo "==> Installing Docker..."
apt-get update -y
apt-get install -y curl apt-transport-https ca-certificates gnupg lsb-release git
mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

echo "==> Obtaining Let's Encrypt certificate for ${FQDN}..."
# docker-mailserver with SSL_TYPE=letsencrypt expects certs to already exist.
# certbot --standalone needs port 80 free (it is, on a fresh box) and DNS to resolve.
apt-get install -y certbot
certbot certonly --standalone --non-interactive --agree-tos \
  -d "${FQDN}" \
  -m "postmaster@${DOMAIN}" \
  || echo "WARNING: certbot failed (DNS not propagated yet, or port 80 blocked). \
You can re-run this script once mail.${DOMAIN} resolves."

echo "==> Writing docker-compose.yml..."
mkdir -p /opt/docker-mailserver && cd /opt/docker-mailserver
cat > docker-compose.yml <<EOF
services:
  mailserver:
    image: ghcr.io/docker-mailserver/docker-mailserver:latest
    container_name: mailserver
    hostname: ${FQDN}
    ports:
      - "25:25"
      - "143:143"
      - "587:587"
      - "993:993"
    volumes:
      - mail-data:/var/mail
      - mail-state:/var/mail-state
      - mail-logs:/var/log/mail
      - ./mail-config:/tmp/docker-mailserver
      - /etc/letsencrypt:/etc/letsencrypt:ro
    environment:
      - ENABLE_SPAMASSASSIN=1
      - ENABLE_CLAMAV=0
      - ENABLE_FAIL2BAN=1
      - SSL_TYPE=letsencrypt
    cap_add:
      - NET_ADMIN
    restart: always
volumes:
  mail-data:
  mail-state:
  mail-logs:
EOF

echo "==> Starting mail server..."
docker compose up -d

echo "==> Downloading setup utility..."
curl -fsSL -o setup.sh \
  https://raw.githubusercontent.com/docker-mailserver/docker-mailserver/master/setup.sh
chmod +x setup.sh

# Create the first mailbox if credentials were provided.
if [[ -n "${EMAIL}" && -n "${PASSWORD}" ]]; then
  echo "==> Creating mailbox ${EMAIL}..."
  sleep 10  # give the container a moment to come up
  ./setup.sh email add "${EMAIL}" "${PASSWORD}" || \
    echo "Mailbox creation failed; create it manually with ./setup.sh email add"
fi

echo "==> Generating DKIM key..."
./setup.sh config dkim || true
echo
echo "============================================================"
echo "Mail server deployed for ${DOMAIN}."
echo
echo "NEXT STEPS (these can't be fully automated):"
echo "  1. Add the DKIM record. Print it with:"
echo "       cat /opt/docker-mailserver/mail-config/opendkim/keys/${DOMAIN}/mail.txt"
echo "     Create a TXT record  mail._domainkey.${DOMAIN}  with that value."
echo "  2. Open outbound port 25 with your provider (DigitalOcean ticket) to send mail."
echo "  3. Create more mailboxes with:  ./setup.sh email add user@${DOMAIN} password"
echo "============================================================"
