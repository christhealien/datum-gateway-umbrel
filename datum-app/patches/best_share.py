#!/usr/bin/env python3
"""Adds a per-client "Best Share" column to the Gateway's Clients table.

Usage: best_share.py <upstream-source-dir>

The Gateway keeps no best share per client, so three small edits are made to the source before it is
built (a field in the miner struct, an update where an accepted share is booked, one more table cell).
All-or-nothing: if any anchor text is not found exactly once (upstream changed that code), nothing is
written, a notice is printed and the build carries on without the column. The UI then simply shows no
Best Share column.
"""
import os, sys

EDITS = [
    ("src/datum_stratum.h",
     "\tuint64_t share_count_rejected;\n",
     "\tuint64_t share_count_rejected;\n"
     "\tdouble best_share_diff; // hardest accepted share from this client, in hashes (2^256 / share hash)\n"),
    ("src/datum_stratum.c",
     "\tstratum_note_share(m, true, job_diff);\n",
     "\t{\n"
     "\t\tdouble hv = 0.0;\n"
     "\t\tint bi;\n"
     "\t\tfor (bi = 31; bi >= 0; --bi) hv = hv * 256.0 + (double)share_hash[bi];\n"
     "\t\tif (hv >= 1.0) {\n"
     "\t\t\tconst double sd = 1.157920892373162e77 / hv;\n"
     "\t\t\tif (sd > m->best_share_diff) m->best_share_diff = sd;\n"
     "\t\t}\n"
     "\t}\n"
     "\tstratum_note_share(m, true, job_diff);\n"),
    ("src/datum_api.c",
     "<TD><U>DiffR (R)</U></TD> ",
     "<TD><U>DiffR (R)</U></TD> <TD><U>Best Share</U></TD> "),
    ("src/datum_api.c",
     "<TD COLSPAN=\\\"8\\\">Not Subscribed</TD>",
     "<TD COLSPAN=\\\"9\\\">Not Subscribed</TD>"),
    ("src/datum_api.c",
     "\t\t\t\t\tbuf_printf(&output, \" (%\"PRIu64\") %.2f%%</TD>\", m->share_count_rejected, hr);\n",
     "\t\t\t\t\tbuf_printf(&output, \" (%\"PRIu64\") %.2f%%</TD>\", m->share_count_rejected, hr);\n"
     "\t\t\t\t\tbuf_strcat(&output, \"<TD>\");\n"
     "\t\t\t\t\tbuf_datum_format_difficulty(&output, m->best_share_diff);\n"
     "\t\t\t\t\tbuf_strcat(&output, \"</TD>\");\n"),
]


def main():
    root = sys.argv[1]
    try:
        if "best_share_diff" in open(os.path.join(root, "src/datum_stratum.h"), encoding="utf-8").read():
            print("best_share: already applied")
            return 0
    except OSError:
        pass
    texts = {}
    for path, old, new in EDITS:
        fp = os.path.join(root, path)
        try:
            texts.setdefault(path, open(fp, encoding="utf-8").read())
        except OSError:
            print("best_share: %s not found, skipping the Best Share column" % path)
            return 0
        if texts[path].count(old) != 1:
            print("best_share: upstream changed near %r in %s, skipping the Best Share column" % (old.strip()[:50], path))
            return 0
        texts[path] = texts[path].replace(old, new, 1)
    for path, t in texts.items():
        open(os.path.join(root, path), "w", encoding="utf-8").write(t)
    print("best_share: Best Share column added")
    return 0


if __name__ == "__main__":
    sys.exit(main())
