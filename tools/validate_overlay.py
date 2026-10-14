#!/usr/bin/env python3
"""Check that the redesigned web UI (datum-app/www) still fits a given checkout of CONVOYMining/datum_gateway.

The Gateway fills every ${...} placeholder in its web templates, and a placeholder it does not know breaks
the whole page. So before an image is built against a new upstream release, this script confirms:

  1. every placeholder our templates use is still defined in the upstream C source;
  2. every template file we override is still part of upstream's embedded web resources;
  3. no template contains a stray "${" and post.js still has exactly one printf conversion;
  4. the table headings our scripts look for are still produced by the upstream C code.

It also lists placeholders and files that are new upstream and that our UI does not show yet
(information only: they never break anything).

Usage:  validate_overlay.py --upstream /path/to/datum_gateway [--www datum-app/www]
Exit status: 0 = compatible, 1 = something our UI relies on is gone or changed.
Only the Python standard library is used.
"""
import argparse
import os
import re
import sys

TOKEN = re.compile(r"\$\{([^}]*)\}")
MODIFIERS = ("readonly", "selected", "checked", "disabled", "msg")

# table headings the page scripts look for (regular expressions, matched case-insensitively), per source page
EXPECTED_HEADINGS = {
    "clients": [r"host", r"user", r"last", r"vdiff", r"diffa", r"diffr", r"hashrate", r"agent"],
    "threads": [r"connection", r"sub", r"hashrate"],
    "coinbaser": [r"value", r"address"],
}


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def upstream_home_vars(api_c):
    names = set(re.findall(r'\{\s*"([A-Z][A-Z0-9_]+)"\s*,\s*datum_api_var_', api_c))
    return names


def upstream_config_specials(api_c):
    """The '*name' placeholders datum_api_fill_config_var understands."""
    m = re.search(r"bool datum_api_fill_config_var\(.*?\n}\n", api_c, re.S)
    body = m.group(0) if m else api_c
    return set(re.findall(r'"\*([A-Za-z_]+)"', body))


def upstream_config_options(conf_c):
    """{ 'category_name': var_type } for every option in the Gateway's config table."""
    out = {}
    for m in re.finditer(r'\.var_type\s*=\s*(DATUM_CONF_\w+)\s*,\s*\.category\s*=\s*"(\w+)"\s*,\s*\.name\s*=\s*"(\w+)"', conf_c):
        out["%s_%s" % (m.group(2), m.group(3))] = (m.group(2), m.group(3), m.group(1))
    return out


def upstream_web_resources(cmake):
    m = re.search(r"set\(WEB_RESOURCES(.*?)\)", cmake, re.S)
    return [x.strip() for x in m.group(1).split() if x.strip()] if m else []


def upstream_headings(api_c):
    """Heading texts the C code writes as <TD><U>Heading</U></TD>, grouped by the function that writes them."""
    result = {}
    for name, key in (("datum_api_client_dashboard", "clients"), ("datum_api_thread_dashboard_inner", "threads"), ("datum_api_coinbaser", "coinbaser")):
        i = api_c.find(name + "(")
        if i < 0:
            result[key] = None
            continue
        j = api_c.find("\n}\n", i)
        seg = api_c[i:j if j > 0 else len(api_c)]
        result[key] = re.findall(r"<U>(.*?)</U>", seg)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upstream", required=True, help="checkout of CONVOYMining/datum_gateway")
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--www", default=os.path.join(here, "..", "datum-app", "www"), help="our overlay's www folder")
    ap.add_argument("--quiet", action="store_true", help="print only problems")
    args = ap.parse_args()

    up, www = os.path.abspath(args.upstream), os.path.abspath(args.www)
    errors, notes = [], []

    api_c = read(os.path.join(up, "src", "datum_api.c"))
    conf_c = read(os.path.join(up, "src", "datum_conf.c"))
    cmake = read(os.path.join(up, "CMakeLists.txt"))

    home_vars = upstream_home_vars(api_c)
    specials = upstream_config_specials(api_c)
    options = upstream_config_options(conf_c)
    resources = upstream_web_resources(cmake)
    if not home_vars:
        errors.append("could not read the status-page variable table from src/datum_api.c (upstream changed its layout)")
    if not options:
        errors.append("could not read the config option table from src/datum_conf.c (upstream changed its layout)")
    if not resources:
        errors.append("could not read WEB_RESOURCES from CMakeLists.txt (upstream changed its layout)")

    # 2. files
    ours = []
    for root, _, files in os.walk(www):
        for fn in files:
            ours.append(os.path.relpath(os.path.join(root, fn), www).replace(os.sep, "/"))
    ours_set = {"www/" + f for f in ours}
    for f in sorted(ours_set - set(resources)):
        errors.append("%s is overridden by our UI but is no longer an embedded web resource upstream" % f)
    for f in sorted(set(resources) - ours_set):
        notes.append("new upstream web file not covered by our UI (upstream's own version will be used): %s" % f)

    # 1 + 3. placeholders
    used_home, used_cfg = set(), set()
    for rel in sorted(ours):
        path = os.path.join(www, rel)
        text = read(path)
        base = os.path.basename(rel)
        if base == "post.js":
            n = text.count("%")
            if n != 1 or text.count("%s") != 1:
                errors.append("post.js is used as a printf format: it must contain exactly one %%s and no other %% (found %d)" % n)
            if "${" in text:
                errors.append("post.js contains '${'")
            continue
        tokens = TOKEN.findall(text)
        if base == "home.html":
            for t in tokens:
                used_home.add(t)
                if t not in home_vars:
                    errors.append("home.html uses ${%s}, which the Gateway no longer defines" % t)
            # every value the page script reads with K("NAME") must be written into the page as data-k="NAME"
            written = set(re.findall(r'data-k="([A-Z0-9_]+)"', text))
            for name in sorted(set(re.findall(r'\bK\("([A-Z0-9_]+)"\)', text)) - written):
                errors.append('home.html reads K("%s") but has no data-k="%s" element for it' % (name, name))
            for name in sorted(written - set(tokens)):
                errors.append('home.html has data-k="%s" without a matching ${%s} placeholder' % (name, name))
        elif base == "config.html":
            for t in tokens:
                mod, _, name = t.rpartition(":") if ":" in t else ("", "", t)
                if mod and mod not in MODIFIERS:
                    errors.append("config.html: ${%s} uses the unknown modifier '%s'" % (t, mod))
                    continue
                used_cfg.add(name)
                if name.startswith("*"):
                    if name[1:] not in specials:
                        errors.append("config.html: ${%s} is not a placeholder the Gateway knows" % t)
                elif name in options:
                    vt = options[name][2]
                    if vt in ("DATUM_CONF_STRING_ARRAY", "DATUM_CONF_USERNAME_MODS"):
                        errors.append("config.html: ${%s} is a %s option, which the Gateway cannot print" % (t, vt))
                    if vt == "DATUM_CONF_STRING" and mod:
                        errors.append("config.html: ${%s}: a modifier is not supported on string options" % t)
                    if vt in ("DATUM_CONF_INT", "DATUM_CONF_DIFFICULTY") and not mod:
                        pass
                else:
                    # a few specials are written without the '*' in some upstream versions: report clearly
                    errors.append("config.html: ${%s} is not a config option or special placeholder upstream" % t)
        elif base == "config_errors.html":
            for t in tokens:
                if t != "*errors":
                    errors.append("config_errors.html may only use ${*errors} (found ${%s})" % t)
        else:
            if tokens:
                errors.append("%s must not contain any ${...} placeholder (found ${%s})" % (rel, tokens[0]))
        # raw templates also must not hide a '${' inside script/style that the engine would pick up
        if base.endswith(".html") and base not in ("home.html", "config.html", "config_errors.html") and "${" in text:
            errors.append("%s contains the sequence '${'" % rel)

    for v in sorted(home_vars - used_home):
        notes.append("status variable not shown by our UI yet: ${%s}" % v)

    # 4. headings
    heads = upstream_headings(api_c)
    for page, patterns in EXPECTED_HEADINGS.items():
        found = heads.get(page)
        if found is None:
            errors.append("the %s page generator was not found in src/datum_api.c" % page)
            continue
        for pat in patterns:
            if not any(re.search(pat, h, re.I) for h in found):
                errors.append("the %s table no longer has a heading matching /%s/ (now: %s)" % (page, pat, ", ".join(found) or "none"))

    if not args.quiet:
        print("upstream:", up)
        print("web files: %d upstream, %d ours" % (len(resources), len(ours_set)))
        print("status variables: %d upstream, %d used" % (len(home_vars), len(used_home)))
        print("config placeholders used: %d" % len(used_cfg))
        for n in notes:
            print("note:", n)
    for e in errors:
        print("ERROR:", e)
    if errors:
        print("\nINCOMPATIBLE: %d problem(s). Do not release this upstream version until the UI is updated." % len(errors))
        return 1
    if not args.quiet:
        print("\nOK: the UI overlay fits this upstream version.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
