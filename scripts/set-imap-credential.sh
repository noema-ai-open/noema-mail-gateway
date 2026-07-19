#!/usr/bin/env bash
set -euo pipefail

# Configure one IMAP account without putting the password in argv, shell
# history, a normal environment variable or the repository.

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this script as root, for example: sudo bash scripts/set-imap-credential.sh" >&2
  exit 1
fi

if [[ $# -ne 0 ]]; then
  echo "Do not pass a password or other value as a command-line argument." >&2
  echo "Run the script without arguments; it prompts securely." >&2
  exit 2
fi

CONFIG_DIR=/etc/noema-mail
ENV_FILE=${CONFIG_DIR}/environment
CREDENTIAL_FILE=${CONFIG_DIR}/gmx_app_password.cred

install -d -o root -g root -m 0750 "${CONFIG_DIR}"

read -r -p "IMAP account (usually the full email address): " account
read -r -p "IMAP host [imap.gmx.net]: " imap_host
read -r -p "IMAP port [993]: " imap_port
read -r -p "Account alias [primary]: " account_alias
read -r -p "Inbox folder [INBOX]: " inbox_folder
read -r -p "Drafts folder [Drafts]: " drafts_folder

imap_host=${imap_host:-imap.gmx.net}
imap_port=${imap_port:-993}
account_alias=${account_alias:-primary}
inbox_folder=${inbox_folder:-INBOX}
drafts_folder=${drafts_folder:-Drafts}

if [[ -z ${account} || ${account} =~ [[:space:]=] ]]; then
  echo "The account must be non-empty and contain no whitespace or '='." >&2
  exit 3
fi
if [[ ! ${imap_host} =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "The IMAP host contains unsupported characters." >&2
  exit 3
fi
if [[ ! ${imap_port} =~ ^[0-9]+$ ]] || (( imap_port < 1 || imap_port > 65535 )); then
  echo "The IMAP port must be between 1 and 65535." >&2
  exit 3
fi
if [[ ! ${account_alias} =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "The account alias may contain letters, digits, dot, underscore and hyphen." >&2
  exit 3
fi
if [[ ${inbox_folder} == *$'\n'* || ${inbox_folder} == *$'\r'* || ${drafts_folder} == *$'\n'* || ${drafts_folder} == *$'\r'* ]]; then
  echo "Folder names must not contain line breaks." >&2
  exit 3
fi

printf "IMAP app password: " >&2
IFS= read -r -s app_password
printf "\nRepeat app password: " >&2
IFS= read -r -s app_password_repeat
printf "\n" >&2

cleanup() {
  unset app_password app_password_repeat
  [[ -n ${credential_tmp:-} ]] && rm -f -- "${credential_tmp}"
  [[ -n ${environment_tmp:-} ]] && rm -f -- "${environment_tmp}"
}
trap cleanup EXIT INT TERM HUP

if [[ -z ${app_password} ]]; then
  echo "The app password must not be empty." >&2
  exit 4
fi
if [[ ${app_password} != "${app_password_repeat}" ]]; then
  echo "The two password entries do not match." >&2
  exit 4
fi
if (( ${#app_password} > 256 )); then
  echo "The app password exceeds the gateway limit of 256 characters." >&2
  exit 4
fi

escape_env_value() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  printf '%s' "${value}"
}

credential_tmp=$(mktemp --tmpdir="${CONFIG_DIR}" .imap-credential.XXXXXX)
environment_tmp=$(mktemp --tmpdir="${CONFIG_DIR}" .environment.XXXXXX)
chmod 0600 "${credential_tmp}" "${environment_tmp}"
chown root:root "${credential_tmp}" "${environment_tmp}"

# No trailing newline is required. The gateway accepts one if present, but
# writing the exact secret avoids accidental transformations.
printf '%s' "${app_password}" >"${credential_tmp}"

cat >"${environment_tmp}" <<EOF
NOEMA_MAIL_IMAP_HOST="$(escape_env_value "${imap_host}")"
NOEMA_MAIL_IMAP_PORT="${imap_port}"
NOEMA_MAIL_ACCOUNT="$(escape_env_value "${account}")"
NOEMA_MAIL_ACCOUNT_ALIAS="$(escape_env_value "${account_alias}")"
NOEMA_MAIL_INBOX_FOLDER="$(escape_env_value "${inbox_folder}")"
NOEMA_MAIL_DRAFTS_FOLDER="$(escape_env_value "${drafts_folder}")"
NOEMA_MAIL_IMAP_TIMEOUT="15"
EOF

mv -f -- "${credential_tmp}" "${CREDENTIAL_FILE}"
credential_tmp=
mv -f -- "${environment_tmp}" "${ENV_FILE}"
environment_tmp=
chmod 0600 "${CREDENTIAL_FILE}"
chmod 0640 "${ENV_FILE}"
chown root:root "${CREDENTIAL_FILE}" "${ENV_FILE}"

unset app_password app_password_repeat

printf '%s\n' "Configuration written safely:" \
  "  ${ENV_FILE} (non-secret account settings, root-readable)" \
  "  ${CREDENTIAL_FILE} (app password, root-only 0600)" \
  "" \
  "The password was not printed and was not passed as a command-line argument." \
  "Start or restart the service only after reviewing the non-secret configuration:" \
  "  sudo systemctl restart noema-mail-gateway"
