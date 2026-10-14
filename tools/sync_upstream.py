#!/usr/bin/env python3
"""Follow upstream releases.

  sync_upstream.py [--repo-dir .] [--check-only] [--force-tag TAG]
  sync_upstream.py --bump "what changed"     # new app version for a UI/packaging change, no upstream change

1. Finds the newest upstream release tag (CONVOYMining/datum_gateway).
2. If it differs from UPSTREAM_TAG: clones it, runs tools/validate_overlay.py against it.
   - incompatible -> exit 2 (nothing changed; look at the output, fix www/, run again)
   - compatible   -> bumps the patch version in umbrel-app.yml / docker-compose.yml,
                     writes UPSTREAM_TAG, prepends release notes, prints NEW_VERSION=x.y.z
Exit 0 and prints NOTHING_TO_DO when already current.
"""
import argparse, os, re, subprocess, sys, tempfile

UP = "https://github.com/CONVOYMining/datum_gateway.git"


def run(*a, **k):
    return subprocess.run(a, check=True, text=True, capture_output=True, **k).stdout


def vkey(t):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", t.lstrip("v")) if x]


def latest(repo):
    tags = [l.split("refs/tags/")[1] for l in run("git", "ls-remote", "--tags", "--refs", repo, "v*").splitlines()]
    if not tags:
        raise SystemExit("no release tags found at " + repo)
    return sorted(tags, key=lambda t: [(0, x) if isinstance(x, int) else (1, x) for x in vkey(t)])[-1]


def bump(d, note, stored, new):
    app = os.path.join(d, "blake2b-datum-gateway")
    mp, cp = os.path.join(app, "umbrel-app.yml"), os.path.join(app, "docker-compose.yml")
    m = open(mp).read()
    old = re.search(r'^version: "([\d.]+)"', m, re.M).group(1)
    x, y, z = old.split(".")
    nv = "%s.%s.%d" % (x, y, int(z) + 1)
    m = m.replace('version: "%s"' % old, 'version: "%s"' % nv).replace("?v=" + old, "?v=" + nv)
    line = note if note else "Built on upstream DATUM Gateway %s (was %s)." % (new, stored)
    notes = "releaseNotes: |-\n  **%s**\n\n  - %s\n\n  " % (nv, line)
    m = re.sub(r"releaseNotes: \|-\n  ", lambda _: notes, m, count=1)
    open(mp, "w").write(m)
    c = open(cp).read()
    open(cp, "w").write(re.sub(r"(blake2b-datum-gateway:)" + re.escape(old), r"\g<1>" + nv, c))
    open(os.path.join(d, "UPSTREAM_TAG"), "w").write(new + "\n")
    print("NEW_VERSION=%s" % nv)
    print("UPSTREAM_TAG=%s" % new)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", default=".")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--force-tag")
    ap.add_argument("--upstream", default=UP)
    ap.add_argument("--bump", metavar="NOTE", help="only bump the app version with this release note")
    a = ap.parse_args()
    d = a.repo_dir
    stored = open(os.path.join(d, "UPSTREAM_TAG")).read().strip()
    if a.bump:
        return bump(d, a.bump, stored, stored)
    new = a.force_tag or latest(a.upstream)
    if new == stored:
        print("NOTHING_TO_DO (upstream %s)" % new)
        return 0
    print("upstream: %s -> %s" % (stored, new))
    with tempfile.TemporaryDirectory() as t:
        src = os.path.join(t, "up")
        run("git", "clone", "--depth", "1", "--branch", new, a.upstream, src)
        v = subprocess.run([sys.executable, "-I", os.path.join(d, "tools/validate_overlay.py"), "--upstream", src,
                            "--www", os.path.join(d, "datum-app/www")], text=True, capture_output=True)
        print(v.stdout + v.stderr)
        if v.returncode:
            print("INCOMPATIBLE: upstream %s changed something the UI depends on" % new)
            return 2
    if a.check_only:
        print("COMPATIBLE")
        return 0
    return bump(d, "", stored, new)


if __name__ == "__main__":
    sys.exit(main())
