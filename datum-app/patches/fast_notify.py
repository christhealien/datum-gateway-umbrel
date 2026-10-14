#!/usr/bin/env python3
"""Checks for a new block 4 times a second instead of once a second.

On Umbrel the Bitcoin app's config can't be given a blocknotify command, so the Gateway falls back to
asking the node for the best block hash in a loop (notify_fallback). The loop sleeps one second, so miners
can keep working on the old block for up to a second after a new one arrives (stale shares). The call is
tiny and goes to your own node, so 250 ms costs nothing.

Usage: fast_notify.py <upstream-source-dir>   (all-or-nothing, skipped with a notice if the code changed)
"""
import os, sys

OLD = "\t\t\tgbbh = NULL;\n\t\t}\n\t\tsleep(1);\n\t}\n}\n\nvoid *datum_gateway_template_thread("
NEW = "\t\t\tgbbh = NULL;\n\t\t\tusleep(250000); // Umbrel build: poll for new blocks 4x/s instead of 1x/s\n\t\t\tcontinue;\n\t\t}\n\t\tsleep(1); // node did not answer: back off, as upstream does\n\t}\n}\n\nvoid *datum_gateway_template_thread("


def main():
    fp = os.path.join(sys.argv[1], "src/datum_blocktemplates.c")
    try:
        t = open(fp, encoding="utf-8").read()
    except OSError:
        print("fast_notify: file not found, skipping")
        return 0
    if "poll for new blocks 4x/s" in t:
        print("fast_notify: already applied")
        return 0
    if t.count(OLD) != 1:
        print("fast_notify: upstream changed this loop, skipping (stock 1 s polling stays)")
        return 0
    open(fp, "w", encoding="utf-8").write(t.replace(OLD, NEW, 1))
    print("fast_notify: new-block polling is now 250 ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
