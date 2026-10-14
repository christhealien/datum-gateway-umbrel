#!/bin/sh
# Copy the app folder into a checkout of the store repo (blake2b) and push.
#   tools/publish_to_store.sh /path/to/store-checkout [remote] [branch]
# For Gitea testing set RETARGET_ARGS, e.g.
#   RETARGET_ARGS="gitea --url http://192.168.1.50:3000 --owner chris" tools/publish_to_store.sh ~/blake2b-gitea
# (only the copy inside the store is rewritten; this repo keeps its GitHub addresses)
set -eu
STORE="${1:?usage: publish_to_store.sh /path/to/store-checkout [remote] [branch]}"
REMOTE="${2:-origin}"; BRANCH="${3:-master}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
APP=blake2b-datum-gateway
VER=$(sed -n 's/^version: "\(.*\)"/\1/p' "$HERE/$APP/umbrel-app.yml")
rm -rf "$STORE/$APP"
cp -r "$HERE/$APP" "$STORE/$APP"
[ -z "${RETARGET_ARGS:-}" ] || python3 "$HERE/tools/retarget.py" $RETARGET_ARGS --app "$STORE/$APP"
cd "$STORE"
git add -A
git diff --cached --quiet && { echo "store already up to date"; exit 0; }
git commit -m "Update $APP to $VER"
git push "$REMOTE" "HEAD:$BRANCH"
