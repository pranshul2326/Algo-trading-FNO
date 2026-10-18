#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/matheran/app"
HOSTNAME="matheran.54.252.125.60.sslip.io"
CREDENTIALS_FILE="/root/matheran-team-credentials.txt"
USERS_FILE="/etc/caddy/matheran-users"
API_KEY_HEADER_FILE="/etc/caddy/matheran-api-header"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi
for required in .env deploy/lightsail/Caddyfile deploy/lightsail/matheran.service; do
  if [[ ! -f "${APP_DIR}/${required}" ]]; then
    echo "Missing ${APP_DIR}/${required}" >&2
    exit 1
  fi
done

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  apt-transport-https ca-certificates curl debian-archive-keyring debian-keyring gnupg openssl

key_tmp="$(mktemp)"
repo_tmp="$(mktemp)"
users_tmp="$(mktemp)"
credentials_tmp="$(mktemp)"
trap 'rm -f "${key_tmp}" "${repo_tmp}" "${users_tmp}" "${credentials_tmp}"' EXIT

curl --fail --silent --show-error --location \
  https://dl.cloudsmith.io/public/caddy/stable/gpg.key -o "${key_tmp}"
gpg --batch --yes --dearmor \
  --output /usr/share/keyrings/caddy-stable-archive-keyring.gpg "${key_tmp}"
curl --fail --silent --show-error --location \
  https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt -o "${repo_tmp}"
install -m 0644 "${repo_tmp}" /etc/apt/sources.list.d/caddy-stable.list

apt-get update
caddy_version="2.11.7"
available_versions="$(apt-cache madison caddy | awk '{print $3}')"
if ! grep -Fxq "${caddy_version}" <<< "${available_versions}"; then
  echo "Pinned Caddy version ${caddy_version} is unavailable." >&2
  exit 1
fi
apt-get install -y --no-install-recommends "caddy=${caddy_version}"

if [[ ! -f "${USERS_FILE}" ]]; then
  printf 'URL=https://%s\n' "${HOSTNAME}" > "${credentials_tmp}"
  for username in team1 team2 team3; do
    password="$(openssl rand -hex 18)"
    password_hash="$(caddy hash-password --algorithm bcrypt --plaintext "${password}")"
    printf '%s %s\n' "${username}" "${password_hash}" >> "${users_tmp}"
    printf '%s=%s\n' "${username}" "${password}" >> "${credentials_tmp}"
  done
  install -o root -g caddy -m 0640 "${users_tmp}" "${USERS_FILE}"
  install -o root -g root -m 0600 "${credentials_tmp}" "${CREDENTIALS_FILE}"
fi

api_key="$("/opt/matheran/venv/bin/python" - <<'PY'
from dotenv import dotenv_values

key = dotenv_values('/opt/matheran/app/.env').get('MATHERAN_API_KEY')
if not key or any(char in key for char in '\r\n\0'):
    raise SystemExit('MATHERAN_API_KEY is missing or invalid')
print(key)
PY
)"
API_KEY_VALUE="${api_key}" API_KEY_HEADER_FILE="${API_KEY_HEADER_FILE}" \
  "/opt/matheran/venv/bin/python" - <<'PY'
import grp
import os
from pathlib import Path

value = os.environ['API_KEY_VALUE']
path = Path(os.environ['API_KEY_HEADER_FILE'])
escaped = value.replace('\\', '\\\\').replace('"', '\\"')
path.write_text(f'header_up X-API-Key "{escaped}"\n', encoding='utf-8')
os.chown(path, 0, grp.getgrnam('caddy').gr_gid)
os.chmod(path, 0o640)
PY
# Remove the previous environment-based injection. Caddy logs its process
# environment at startup, so secrets must be imported from the protected snippet.
rm -f /etc/caddy/matheran-api-key.env \
  /etc/systemd/system/caddy.service.d/matheran.conf
rmdir --ignore-fail-on-non-empty /etc/systemd/system/caddy.service.d 2>/dev/null || true

install -m 0644 "${APP_DIR}/deploy/lightsail/matheran.service" \
  /etc/systemd/system/matheran.service
install -o root -g root -m 0644 "${APP_DIR}/deploy/lightsail/Caddyfile" \
  /etc/caddy/Caddyfile

systemctl daemon-reload
systemctl restart matheran.service
for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error http://127.0.0.1:8787/health >/dev/null; then
    break
  fi
  if [[ "${attempt}" -eq 30 ]]; then
    journalctl -u matheran.service --no-pager -n 100 >&2
    exit 1
  fi
  sleep 1
done

caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
unset api_key
# HTTP-01 and TLS-ALPN-01 certificate validation must reach Caddy before the
# authenticated HTTPS smoke test can pass. Keep existing VPN rules until then.
ufw allow 80/tcp
ufw allow 443/tcp
systemctl enable caddy.service
systemctl restart caddy.service

team1_password=""
if [[ -f "${CREDENTIALS_FILE}" ]]; then
  team1_password="$(awk -F= '$1 == "team1" {print substr($0, index($0, "=") + 1)}' "${CREDENTIALS_FILE}")"
fi
for attempt in $(seq 1 30); do
  if [[ -n "${team1_password}" ]]; then
    status="$(curl --insecure --silent --output /dev/null --write-out '%{http_code}' \
      --resolve "${HOSTNAME}:443:127.0.0.1" \
      --user "team1:${team1_password}" \
      "https://${HOSTNAME}/api/status" || true)"
    expected="200"
  else
    status="$(curl --insecure --silent --output /dev/null --write-out '%{http_code}' \
      --resolve "${HOSTNAME}:443:127.0.0.1" \
      "https://${HOSTNAME}/api/status" || true)"
    expected="401"
  fi
  if [[ "${status}" == "${expected}" ]]; then
    break
  fi
  if [[ "${attempt}" -eq 30 ]]; then
    journalctl -u caddy.service --no-pager -n 100 >&2
    exit 1
  fi
  sleep 1
done
unset team1_password

# The browser-facing proxy is now healthy. Retire the unused VPN and allow only
# SSH plus the HTTP/HTTPS ports required for redirects and ACME renewal.
systemctl disable --now wg-quick@wg0.service 2>/dev/null || true
rm -rf /etc/wireguard /root/matheran-wireguard-peers
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

apt-get clean
rm -rf /var/lib/apt/lists/*

echo "Team HTTPS proxy is healthy on this server."
echo "Credentials are stored at ${CREDENTIALS_FILE}; their values were not printed."
echo "Public URL: https://${HOSTNAME}"
