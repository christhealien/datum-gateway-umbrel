#!/bin/sh
# By hand: copy the app folder into a checkout of the store repo (blake2b) and push.
# (The image workflow does this automatically when the STORE_TOKEN secret is set.)
#   tools/publish_to_store.sh /path/to/blake2b-checkout [remote] [branch]
set -eu
STORE="${1:?usage: publish_to_store.sh /path/to/blake2b-checkout [remote] [branch]}"
REMOTE="${2:-origin}"; BRANCH="${3:-master}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
APP=blake2b-datum-gateway
VER=$(sed -n 's/^version: "\(.*\)"/\1/p' "$HERE/$APP/umbrel-app.yml")
rm -rf "$STORE/$APP"
cp -r "$HERE/$APP" "$STORE/$APP"
cd "$STORE"
git add -A
git diff --cached --quiet && { echo "store already up to date"; exit 0; }
git commit -m "Update $APP to $VER"
git push "$REMOTE" "HEAD:$BRANCH"
