#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -eq 0 ]]; then
  echo "Run this script as the OpenClaw user, not as root." >&2
  exit 1
fi

if [[ $# -ne 0 ]]; then
  echo "This script takes no arguments." >&2
  exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "${script_dir}/.." && pwd -P)
source_dir=${repo_root}/openclaw-skill/mail
openclaw_dir=${HOME}/.openclaw
skill_dir=${openclaw_dir}/workspace/skills/mail
config_file=${openclaw_dir}/openclaw.json
backup_file=

[[ -f ${source_dir}/SKILL.md && -f ${source_dir}/mail-client.py ]] || {
  echo "The checkout does not contain the complete OpenClaw mail skill." >&2
  exit 3
}
command -v python3 >/dev/null 2>&1 || {
  echo "Python 3 is required." >&2
  exit 4
}

install -d -m 0750 "${skill_dir}"
install -m 0644 "${source_dir}/SKILL.md" "${skill_dir}/SKILL.md"
install -m 0755 "${source_dir}/mail-client.py" "${skill_dir}/mail-client.py"
if [[ -f ${source_dir}/README.md ]]; then
  install -m 0644 "${source_dir}/README.md" "${skill_dir}/README.md"
fi

install -d -m 0700 "${openclaw_dir}"
if [[ -f ${config_file} ]]; then
  backup_file=${config_file}.bak-mail-skill-$(date -u +%Y%m%dT%H%M%SZ)
  cp -p -- "${config_file}" "${backup_file}"
fi

CONFIG_FILE=${config_file} python3 - <<'PY'
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

path = Path(os.environ["CONFIG_FILE"])
if path.exists():
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit("openclaw.json must contain a JSON object")
else:
    data = {}

skills = data.setdefault("skills", {})
if not isinstance(skills, dict):
    raise SystemExit("openclaw.json field 'skills' must be an object")
entries = skills.setdefault("entries", {})
if not isinstance(entries, dict):
    raise SystemExit("openclaw.json field 'skills.entries' must be an object")
mail = entries.setdefault("mail", {})
if not isinstance(mail, dict):
    raise SystemExit("openclaw.json field 'skills.entries.mail' must be an object")
mail["enabled"] = True

path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
fd, temporary_name = tempfile.mkstemp(prefix=".openclaw.json.", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary_name, 0o600)
    os.replace(temporary_name, path)
finally:
    try:
        os.unlink(temporary_name)
    except FileNotFoundError:
        pass
PY

python3 -m json.tool "${config_file}" >/dev/null
chmod 0600 "${config_file}"

printf '%s\n' \
  "OpenClaw mail skill installed:" \
  "  ${skill_dir}" \
  "  skills.entries.mail.enabled = true"

if [[ -n ${backup_file} ]]; then
  echo "Backup: ${backup_file}"
fi

if command -v openclaw >/dev/null 2>&1; then
  echo
  echo "OpenClaw skill registry:"
  openclaw skills list || true
else
  echo "OpenClaw CLI was not found in PATH; start a fresh OpenClaw session and verify the skill there."
fi
