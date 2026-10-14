#!/usr/bin/env python3
"""Render the UI pages in a headless browser, report JavaScript errors and save screenshots.

Start the preview first (python3 tools/preview.py), then:

    python3 tools/screenshot.py --out /tmp/shots

Needs Playwright for Python and a Chromium (pip install playwright; playwright install chromium).
With --seed the browser is given 24 h of made-up hashrate history so the Status graph is filled in.
"""
import argparse
import json
import math
import os
import sys
import time

SEED_JS = """
(function () {
  try {
    var now = Date.now(), s = [], h = 912300, i;
    for (i = 24 * 3600; i >= 0; i -= 30) {
      var t = now - i * 1000, th = 11.3 + 0.35 * Math.sin(i / 1700) + 0.18 * Math.sin(i / 230);
      if (i > 15 * 3600 && i < 15 * 3600 + 1500) th *= 0.55;          // a dip
      if (i > 6 * 3600 && i < 6 * 3600 + 600) th *= 0.1;              // a restart
      if (i % 600 === 0 && i > 0) h += 0;
      s.push([t, +th.toFixed(3), 4, 9000 + Math.floor((24 * 3600 - i) * 0.12), 21, 912300 + Math.floor((24 * 3600 - i) / 600)]);
    }
    localStorage.setItem("datum-gw-hist-v1", JSON.stringify({ v: 1, s: s }));
  } catch (e) {}
})();
"""

PAGES = [("status", "/"), ("clients", "/clients"), ("threads", "/threads"), ("coinbaser", "/coinbaser"),
         ("config", "/config"), ("config-errors", "/config-errors"), ("config-restart", "/config-restart")]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:7152")
    ap.add_argument("--out", default="shots")
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--only", default="", help="comma separated page names")
    ap.add_argument("--themes", default="dark,light")
    ap.add_argument("--sizes", default="desktop,mobile")
    ap.add_argument("--viewport", action="store_true", help="never take full-page shots")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    os.makedirs(args.out, exist_ok=True)
    only = [x for x in args.only.split(",") if x]
    sizes = {"desktop": (1440, 900), "mobile": (390, 844)}
    problems = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for size in args.sizes.split(","):
            w, h = sizes[size]
            for theme in args.themes.split(","):
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, color_scheme=theme)
                ctx.add_init_script("try{localStorage.setItem('gc-theme','%s')}catch(e){}" % theme)
                if args.seed:
                    ctx.add_init_script(SEED_JS)
                for name, path in PAGES:
                    if only and name not in only:
                        continue
                    page = ctx.new_page()
                    errs = []
                    page.on("pageerror", lambda e, errs=errs: errs.append("pageerror: %s" % e))
                    page.on("console", lambda m, errs=errs: errs.append("console.%s: %s" % (m.type, m.text)) if m.type in ("error", "warning") else None)
                    page.goto(args.base + path, wait_until="load")
                    page.wait_for_timeout(2200 if name in ("status", "clients") else 900)
                    full = (size == "mobile" or name in ("config",)) and not args.viewport
                    fn = os.path.join(args.out, "%s-%s-%s.png" % (name, theme, size))
                    page.screenshot(path=fn, full_page=full)
                    status = "ok" if not errs else "ERRORS"
                    print("%-14s %-6s %-8s %s %s" % (name, theme, size, status, fn))
                    for e in errs:
                        print("    ", e)
                        problems += 1
                    page.close()
                ctx.close()
        browser.close()
    print("\n%d JavaScript problem(s)" % problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
