#!/bin/sh
# Starts the sign-in page and proxy on :7152, the first-run setup, waits for the node, then runs the Gateway.
set -eu
echo "DATUM Gateway, upstream $(cat /app/upstream-ref 2>/dev/null || echo unknown)"
cd /app
exec python3 -I /app/datum_setup.py --run /data/config.json
