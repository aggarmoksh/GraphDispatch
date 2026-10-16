#!/usr/bin/env bash
# Ship the committed code (git archive HEAD) to the host and restart the stack.
#
#   HOST=ec2-user@<PUBLIC_IP> KEY_FILE=~/.ssh/<KEY>.pem deploy/ship.sh          # DRY RUN (default): prints every command
#   HOST=... KEY_FILE=... deploy/ship.sh --yes                                    # really does it (operator only)
#
# Safety: only committed files are shipped (git archive), so no local .env or .env.server can leave this machine.
# The only env file used on the host is ~/graphdispatch/.env.server, created there by the operator.
set -euo pipefail

YES=0
[ "${1:-}" = "--yes" ] && YES=1

HOST="${HOST:-<HOST>}"
KEY_FILE="${KEY_FILE:-<KEY_FILE>}"
SHORT="$(git rev-parse --short HEAD)"
TARBALL="/tmp/graphdispatch-${SHORT}.tar.gz"
REMOTE_BASE="~/graphdispatch"
REMOTE_REL="${REMOTE_BASE}/releases/${SHORT}"
SSH_OPTS="-i ${KEY_FILE} -o StrictHostKeyChecking=accept-new"

if [ "$YES" -eq 1 ]; then
  echo "== SHIPPING ${SHORT} to ${HOST}"
  [ "$HOST" = "<HOST>" ] && { echo "set HOST"; exit 2; }
  [ "$KEY_FILE" = "<KEY_FILE>" ] && { echo "set KEY_FILE"; exit 2; }
else
  echo "== DRY RUN: nothing below is executed. Re-run with --yes to ship ${SHORT}."
fi

if [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then
  echo "WARNING: uncommitted changes exist. They are NOT shipped (only committed HEAD is)."
fi

run() {
  echo "+ $*"
  if [ "$YES" -eq 1 ]; then eval "$@"; fi
}

run "git archive --format=tar.gz -o ${TARBALL} HEAD"
run "scp ${SSH_OPTS} ${TARBALL} ${HOST}:/tmp/"
run "ssh ${SSH_OPTS} ${HOST} 'mkdir -p ${REMOTE_REL} && tar -xzf /tmp/graphdispatch-${SHORT}.tar.gz -C ${REMOTE_REL}'"
run "ssh ${SSH_OPTS} ${HOST} 'ln -sfn ${REMOTE_REL} ${REMOTE_BASE}/current'"
# copy the host's own env file into the release (remote to remote; no local file is involved)
run "ssh ${SSH_OPTS} ${HOST} 'cp ${REMOTE_BASE}/.env.server ${REMOTE_BASE}/current/.env.server'"
run "ssh ${SSH_OPTS} ${HOST} 'cd ${REMOTE_BASE}/current && docker compose up -d --build'"
run "ssh ${SSH_OPTS} ${HOST} 'for i in 1 2 3 4 5 6 7 8 9 10 11 12; do curl -fsS http://localhost/api/health && exit 0; sleep 5; done; exit 1'"
run "rm -f ${TARBALL}"

if [ "$YES" -eq 0 ]; then
  echo "== DRY RUN complete: no files were created, copied or executed."
fi
