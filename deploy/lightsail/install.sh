#!/usr/bin/env bash
set -Eeuo pipefail

# Run as root on a fresh Ubuntu 24.04 Lightsail instance after the application,
# config.yaml, and .env have been copied to /opt/matheran/app.

APP_DIR="/opt/matheran/app"
VENV_DIR="/opt/matheran/venv"
APP_USER="matheran"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi
for required in requirements.txt run.py config.yaml .env \
  deploy/lightsail/matheran.service deploy/lightsail/Caddyfile \
  deploy/lightsail/enable-team-https.sh; do
  if [[ ! -f "${APP_DIR}/${required}" ]]; then
    echo "Missing ${APP_DIR}/${required}" >&2
    exit 1
  fi
done
if ! grep -Eq '^[[:space:]]*(export[[:space:]]+)?MATHERAN_API_KEY[[:space:]]*=[[:space:]]*.+$' "${APP_DIR}/.env"; then
  echo "MATHERAN_API_KEY must be set in ${APP_DIR}/.env before installation." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl python3 python3-pip python3-venv ufw

if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir /opt/matheran --create-home --shell /usr/sbin/nologin "${APP_USER}"
fi

# One GiB of swap uses the included SSD and reduces OOM risk on the 1 GiB VM.
if [[ ! -f /swapfile ]]; then
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
fi
if ! swapon --show=NAME --noheadings | grep -Fxq /swapfile; then
  swapon /swapfile
fi
if ! grep -Eq '^/swapfile[[:space:]]' /etc/fstab; then
  printf '/swapfile none swap sw 0 0\n' >> /etc/fstab
fi

python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --disable-pip-version-check --no-cache-dir \
  -r "${APP_DIR}/requirements.txt"

install -d -m 0750 -o "${APP_USER}" -g "${APP_USER}" \
  "${APP_DIR}/data" "${APP_DIR}/cache" "${APP_DIR}/logs"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
chmod 0600 "${APP_DIR}/.env" "${APP_DIR}/config.yaml"

# Every fresh deployment starts in paper mode. FastAPI is loopback-only; Caddy is
# the sole browser-facing process.
"${VENV_DIR}/bin/python" - "${APP_DIR}/config.yaml" <<'PY'
from pathlib import Path
import sys
import yaml

path = Path(sys.argv[1])
config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
config["mode"] = "paper"
config.setdefault("engine", {})["poll_seconds"] = 15
server = config.setdefault("server", {})
server["host"] = "127.0.0.1"
server["port"] = 8787
path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
PY
chown "${APP_USER}:${APP_USER}" "${APP_DIR}/config.yaml"
chmod 0600 "${APP_DIR}/config.yaml"

install -m 0644 "${APP_DIR}/deploy/lightsail/matheran.service" \
  /etc/systemd/system/matheran.service
systemctl daemon-reload
systemctl enable --now matheran.service

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

chmod 0755 "${APP_DIR}/deploy/lightsail/enable-team-https.sh"
"${APP_DIR}/deploy/lightsail/enable-team-https.sh"
