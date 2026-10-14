#!/bin/sh
# Make your Gitea an exact, read-only copy of your GitHub repos, and pull whenever you want.
#   GITEA=http://192.168.1.50:3000 GUSER=chris GTOKEN=xxxx tools/gitea_mirror.sh create   # once
#   GITEA=... GUSER=... GTOKEN=... tools/gitea_mirror.sh sync                              # pull now
# GTOKEN: Gitea token with write:repository. Mirrors also refresh by themselves every 8 hours.
set -eu
: "${GITEA:?set GITEA}" "${GUSER:?set GUSER}" "${GTOKEN:?set GTOKEN}"
GH_OWNER="${GH_OWNER:-christhealien}"
REPOS="${REPOS:-blake2b blake2b-asic-control datum-gateway-umbrel mempool-umbrel}"
api() { curl -fsS -H "Authorization: token $GTOKEN" -H "Content-Type: application/json" "$@"; }
case "${1:-}" in
  create)
    for r in $REPOS; do
      echo "mirroring $GH_OWNER/$r"
      api -X POST "$GITEA/api/v1/repos/migrate" -d "{\"clone_addr\":\"https://github.com/$GH_OWNER/$r\",\"service\":\"github\",\"repo_name\":\"$r\",\"repo_owner\":\"$GUSER\",\"mirror\":true,\"mirror_interval\":\"8h0m0s\",\"private\":false}" >/dev/null && echo "  ok"
    done ;;
  sync)
    for r in $REPOS; do
      echo "pulling $r"
      api -X POST "$GITEA/api/v1/repos/$GUSER/$r/mirror-sync" >/dev/null && echo "  queued"
    done ;;
  *) echo "usage: $0 create|sync" >&2; exit 1 ;;
esac
