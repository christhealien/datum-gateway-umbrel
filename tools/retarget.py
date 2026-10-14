#!/usr/bin/env python3
"""Point the app folder at GitHub (public release) or at your Gitea (testing).

  retarget.py github
  retarget.py gitea --url http://192.168.1.50:3000 --owner chris [--registry 192.168.1.50:3000] [--branch master]

Rewrites image / icon / gallery / repo / support / website / submission in blake2b-datum-gateway/.
Safe to run repeatedly in either direction.
"""
import argparse, os, re, sys

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blake2b-datum-gateway")
SRC_REPO = "datum-gateway-umbrel"
IMG = "blake2b-datum-gateway"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", choices=["github", "gitea"])
    ap.add_argument("--url")
    ap.add_argument("--owner")
    ap.add_argument("--registry")
    ap.add_argument("--branch", default="master")
    ap.add_argument("--app", default=APP, help="app folder to rewrite (default: the one in this repo)")
    ap.add_argument("--gh-owner", default="christhealien")
    ap.add_argument("--gh-branch", default="master")
    a = ap.parse_args()
    if a.target == "github":
        web = "https://github.com/%s/%s" % (a.gh_owner, SRC_REPO)
        raw = "https://raw.githubusercontent.com/%s/%s/%s/" % (a.gh_owner, SRC_REPO, a.gh_branch)
        image = "ghcr.io/%s/%s" % (a.gh_owner, IMG)
    else:
        if not (a.url and a.owner):
            ap.error("gitea needs --url and --owner")
        base = a.url.rstrip("/")
        reg = a.registry or re.sub(r"^https?://", "", base)
        web = "%s/%s/%s" % (base, a.owner, SRC_REPO)
        raw = "%s/%s/%s/raw/branch/%s/" % (base, a.owner, SRC_REPO, a.branch)
        image = "%s/%s/%s" % (reg, a.owner, IMG)
    p = os.path.join(a.app, "umbrel-app.yml")
    out = []
    for line in open(p).read().split("\n"):
        m = re.match(r"^(\s*-\s+|icon: )(https?://\S*?/)(blake2b-datum-gateway/\S+)$", line)
        if m:
            line = m.group(1) + raw + m.group(3)
        else:
            m = re.match(r"^(repo|website|submission): ", line)
            if m:
                line = "%s: %s" % (m.group(1), web)
            elif line.startswith("support: "):
                line = "support: %s/issues" % web
        out.append(line)
    open(p, "w").write("\n".join(out))
    c = os.path.join(a.app, "docker-compose.yml")
    s = open(c).read()
    s = re.sub(r"image: \S+/%s:" % IMG, "image: %s:" % image, s)
    open(c, "w").write(s)
    print("retargeted to", a.target)


if __name__ == "__main__":
    sys.exit(main())
