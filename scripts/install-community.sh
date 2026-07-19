#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  sudo bash scripts/install-community.sh [--client-user USER]

Installs the gateway service but does not create credentials and does not start
it. Run scripts/set-imap-credential.sh afterwards, review the non-secret
configuration, then enable and start the service.

--client-user USER
  Add the local OpenClaw user to the narrowly used noema-mail socket group.
  A new login/session is required before the new group membership is active.
EOF
}

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi

client_user=
while [[ $# -gt 0 ]]; do
  case $1 in
    --client-user)
      [[ $# -ge 2 ]] || { echo "--client-user requires a value" >&2; exit 2; }
      client_user=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "${script_dir}/.." && pwd -P)
unit_source=${repo_root}/systemd/noema-mail-gateway.service

[[ -f ${repo_root}/pyproject.toml ]] || {
  echo "Run the installer from a complete NOEMA Mail Gateway checkout." >&2
  exit 3
}
[[ -f ${unit_source} ]] || {
  echo "Missing systemd unit template: ${unit_source}" >&2
  exit 3
}

python_bin=
for candidate in python3.13 python3.12 python3; do
  if command -v "${candidate}" >/dev/null 2>&1; then
    if "${candidate}" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY
    then
      python_bin=$(command -v "${candidate}")
      break
    fi
  fi
done

if [[ -z ${python_bin} ]]; then
  echo "Python 3.12 or newer is required." >&2
  exit 4
fi

for command_name in systemctl install groupadd useradd usermod getent; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command is missing: ${command_name}" >&2
    exit 4
  }
done

if ! getent group noema-mail >/dev/null; then
  groupadd --system noema-mail
fi
if ! getent passwd noema-mail >/dev/null; then
  useradd --system --gid noema-mail --home-dir /nonexistent \
    --shell /usr/sbin/nologin --no-create-home noema-mail
fi

if [[ -n ${client_user} ]]; then
  if ! getent passwd "${client_user}" >/dev/null; then
    echo "The requested client user does not exist: ${client_user}" >&2
    exit 5
  fi
  usermod -a -G noema-mail "${client_user}"
fi

install -d -o root -g root -m 0755 /opt/noema-mail-gateway
"${python_bin}" -m venv /opt/noema-mail-gateway/venv
/opt/noema-mail-gateway/venv/bin/python -m pip install --upgrade pip
/opt/noema-mail-gateway/venv/bin/python -m pip install "${repo_root}"

install -d -o root -g root -m 0750 /etc/noema-mail
install -m 0644 "${unit_source}" /etc/systemd/system/noema-mail-gateway.service

if [[ ! -e /etc/noema-mail/environment.example ]]; then
  install -m 0640 "${repo_root}/config/noema-mail.env.example" \
    /etc/noema-mail/environment.example
fi

systemctl daemon-reload
systemctl enable noema-mail-gateway.service >/dev/null

cat <<EOF
NOEMA Mail Gateway files installed.

The service was enabled but intentionally not started.

Next steps:
  1. sudo bash ${repo_root}/scripts/set-imap-credential.sh
  2. sudoedit /etc/noema-mail/environment
  3. sudo systemctl start noema-mail-gateway
  4. systemctl status noema-mail-gateway --no-pager -l
EOF

if [[ -n ${client_user} ]]; then
  cat <<EOF

User '${client_user}' was added to group 'noema-mail' for Unix-socket access.
Start a fresh login/OpenClaw session before testing the skill.
EOF
fi
