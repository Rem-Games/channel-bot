#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-remchannelbot}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
RUN_USER="${RUN_USER:-$(id -un)}"
RUN_GROUP="${RUN_GROUP:-$(id -gn)}"
TEMPLATE="${PROJECT_DIR}/deploy/systemd/remchannelbot.service.template"

if [[ ! -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
  echo "Missing ${PROJECT_DIR}/.venv/bin/python. Create the virtual environment and install requirements first." >&2
  exit 1
fi

if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
  echo "Missing ${PROJECT_DIR}/.env. Create it from .env.example before starting the service." >&2
  exit 1
fi

tmpfile="$(mktemp)"
sed \
  -e "s|{{USER}}|${RUN_USER}|g" \
  -e "s|{{GROUP}}|${RUN_GROUP}|g" \
  -e "s|{{PROJECT_DIR}}|${PROJECT_DIR}|g" \
  "${TEMPLATE}" > "${tmpfile}"

if [[ "${EUID}" -eq 0 ]]; then
  install -m 0644 "${tmpfile}" "${SERVICE_FILE}"
  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}"
else
  sudo install -m 0644 "${tmpfile}" "${SERVICE_FILE}"
  sudo systemctl daemon-reload
  sudo systemctl enable "${SERVICE_NAME}"
fi

rm -f "${tmpfile}"

echo "Installed ${SERVICE_NAME}."
echo "Start it with: sudo systemctl start ${SERVICE_NAME}"
echo "View logs with: sudo journalctl -u ${SERVICE_NAME} -f"
