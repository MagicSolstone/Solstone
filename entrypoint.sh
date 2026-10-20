#!/bin/sh
# Runs as root just long enough to make /data writable by the unprivileged
# app user, then drops privileges for the server itself (same pattern as
# The Coop Ledger).
#
# PUID/PGID (default 1000:1000) control which host uid/gid owns the data
# files. On Unraid use 99:100 (nobody:users). Solstone only ever reads the
# Crafty servers folder, so that mount can stay read-only.
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" != "0" ]; then
    # Started with a user override (e.g. compose `user:`) -- respect it.
    exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers "$@"
fi

if ! getent group solstone >/dev/null 2>&1; then
    groupadd -o -g "$PGID" solstone 2>/dev/null || groupadd solstone
fi
if ! id solstone >/dev/null 2>&1; then
    useradd -o -u "$PUID" -g solstone -M -s /usr/sbin/nologin solstone 2>/dev/null || useradd -g solstone -M -s /usr/sbin/nologin solstone
fi

mkdir -p /data
chown -R solstone:solstone /data

if command -v setpriv >/dev/null 2>&1; then
    exec setpriv --reuid solstone --regid solstone --clear-groups \
        uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers "$@"
else
    echo "WARNING: setpriv not found -- running as root. This still works, but isn't ideal."
    exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers "$@"
fi
