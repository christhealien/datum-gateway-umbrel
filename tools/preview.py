#!/usr/bin/env python3
"""Preview the DATUM Gateway web UI in a browser without building or running the Gateway.

It serves datum-app/www the way the Gateway does: it fills the same ${...} placeholders (with moving sample
data) and writes the same raw tables the C code writes for the Clients, Threads and Coinbaser pages.

    python3 tools/preview.py                 # http://127.0.0.1:7152/
    python3 tools/preview.py --empty         # no miners connected
    python3 tools/preview.py --readonly      # config editing switched off
    python3 tools/preview.py --noauth        # Clients / Threads / Config ask for the admin password

Standard library only. This is a preview of the *interface*: numbers are made up.
"""
import argparse
import json
import math
import os
import random
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WWW = os.path.join(HERE, "..", "datum-app", "www")
START = time.time()
RNG = random.Random(7)

ARGS = None


def rd(rel):
    with open(os.path.join(WWW, rel), "rb") as f:
        return f.read()


def fmt_diff(v):
    """difficulty (pdiff units) -> hashes, printed the way the Gateway does (k M G T P E, one decimal)"""
    v = v * 4294967296.0
    if v < 1000:
        return "%.0f" % v
    v /= 1000.0
    for unit in "kMGTPEZ":
        if v < 999.95 or unit == "Z":
            return "%.1f%s" % (v, unit)
        v /= 1000.0


MINERS = [
    # tid, cid, host, user, subscribed, ths, vdiff, acc_count, rej_count, ua, coinbase
    (0, 0, "192.168.1.41", "bc1qexample0000000000000000000000000000000.sclite01", True, 4.81, 16384, 18321, 12, "Goldshell-SC-Lite/2.2.0", "Default"),
    (0, 1, "192.168.1.42", "bc1qexample0000000000000000000000000000000.sclite02", True, 4.78, 16384, 18012, 31, "Goldshell-SC-Lite/2.2.0", "Default"),
    (1, 0, "192.168.1.47", "bc1qexample0000000000000000000000000000000.hsbox", True, 0.55, 2048, 4410, 3, "Goldshell-HS-Box/2.2.6", "Tiny"),
    (1, 1, "192.168.1.48", "bc1qexample0000000000000000000000000000000.scbox", True, 0.75, 4096, 6120, 188, "Goldshell-SC-Box/2.2.5", "Default"),
    (2, 0, "192.168.1.60", "bc1qexample0000000000000000000000000000000.rig5", False, 0, 0, 0, 0, "", ""),
]


def state():
    t = time.time() - START
    wob = lambda a, p: 1 + a * math.sin(t / p)
    empty = ARGS.empty
    miners = [] if empty else MINERS
    th = 0.0 if empty else sum(m[5] for m in miners if m[4]) * wob(0.015, 23)
    acc = int(9000 + t * 3.1) if not empty else 0
    rej = int(21 + t * 0.012) if not empty else 0
    height = 912345 + int(t // 240)
    return dict(t=t, th=th, miners=miners, acc=acc, rej=rej, height=height, empty=empty)


def home_vars(s):
    now = time.time()
    jobts = now - (now % 97) + 0.123
    conns = len(s["miners"])
    subs = sum(1 for m in s["miners"] if m[4])
    dot = lambda c: "<svg viewBox='0 0 100 100' role='img' style='width:1em;height:1em'><circle cx='50' cy='60' r='35' style='fill:%s' /></svg>" % c
    status = dot("lime") + " Connected and Ready"
    if ARGS.status == "error":
        status = dot("red") + " ERROR: bitcoind RPC unreachable"
    elif ARGS.status == "init":
        status = dot("silver") + " Initialising..."
    up = int(s["t"]) + 3 * 86400 + 4 * 3600 + 11 * 60
    uptime = "%d days, %d hours, %d minutes, %d seconds" % (up // 86400, up % 86400 // 3600, up % 3600 // 60, up % 60)
    pooled = ARGS.mode != "solo"
    zeros = "0000000000000000000"
    return {
        "STRATUM_SHARES_ACCEPTED": "%d  (%s diff)" % (s["acc"], fmt_diff(s["acc"] * 16384.0)),
        "STRATUM_SHARES_REJECTED": "%d  (%s diff)" % (s["rej"], fmt_diff(s["rej"] * 16384.0)),
        "DATUM_SHARES_ACCEPTED": ("%d  (%s diff)" % (int(s["acc"] * 0.998), fmt_diff(s["acc"] * 16384.0 * 0.998))) if pooled else "N/A",
        "DATUM_SHARES_REJECTED": ("%d  (%s diff)" % (int(s["rej"] * 1.2), fmt_diff(s["rej"] * 16384.0 * 1.2))) if pooled else "N/A",
        "DATUM_CONNECTION_STATUS": status,
        "DATUM_POOL_HOST": "datum-beta1.mine.convoy.xyz:28915" if pooled else "N/A",
        "DATUM_POOL_TAG": '"DATUM Pool"' if pooled else '"DATUM Gateway"',
        "DATUM_MINER_TAG": '"DATUM User"',
        "DATUM_POOL_DIFF": fmt_diff(1024),
        "DATUM_POOL_PUBKEY": "dbb11fa0c2b5403e4f798fa6071bb97e6079d219598366032fdf2ae01962b13c5e66e2be7d6b008f0b2603f3e6f6fc64768fa786c8129c46d3e30a58677341e1c",
        "DATUM_PROCESS_UPTIME": uptime,
        "STRATUM_ACTIVE_THREADS": "3" if conns else "0",
        "STRATUM_TOTAL_CONNECTIONS": str(conns),
        "STRATUM_TOTAL_SUBSCRIPTIONS": str(subs),
        "STRATUM_HASHRATE_ESTIMATE": "%.2f Th/sec" % s["th"],
        "STRATUM_JOB_INFO": "7f3a9c (%d) @ %.3f" % (41 + int(s["t"] // 97), jobts),
        "STRATUM_JOB_BLOCK_HEIGHT": str(s["height"]),
        "STRATUM_JOB_BLOCK_VALUE": "3.15734812 BTC",
        "STRATUM_JOB_PREVBLOCK": "<span class='leading_zeros'>%s</span>a3f19c0e7b52d8864ce1fa09b73d4c58e2160f9a1b7c3d" % zeros[:19],
        "STRATUM_JOB_TARGET": "<span class='leading_zeros'>%s</span>3b18d0000000000000000000000000000000000000" % zeros[:17],
        "STRATUM_JOB_WITNESS": "6a24aa21a9ed" + "c3d1b0e47f92a65d18e3b04c9f7a2d6e51b8c0f3a94d27e6185b0c3f9a1d72e",
        "STRATUM_JOB_DIFF": "21.8E",
        "STRATUM_JOB_VERSION": "20000000 (536870912)",
        "STRATUM_JOB_BITS": "1703b18d",
        "STRATUM_JOB_TIMEINFO": "Current: %d / Min: %d" % (int(now), int(now) - 5400),
        "STRATUM_JOB_LIMITINFO": "Size: 4000000, Weight: 4000000, SigOps: 80000",
        "STRATUM_JOB_SIZE": "1612890",
        "STRATUM_JOB_WEIGHT": "3398140",
        "STRATUM_JOB_SIGOPS": "28112",
        "STRATUM_JOB_TXNCOUNT": "3641",
    }


CFG = {
    "bitcoind_rpcurl": "http://10.21.21.8:8332", "bitcoind_rpcuser": "umbrel", "bitcoind_work_update_seconds": 40,
    "bitcoind_notify_fallback": True, "stratum_listen_port": 23334, "stratum_vardiff_min": fmt_diff(1024),
    "stratum_vardiff_target_shares_min": 8, "stratum_max_clients": 1024, "stratum_share_stale_seconds": 120,
    "stratum_idle_timeout_no_subscribe": 15, "stratum_idle_timeout_no_shares": 7200, "stratum_fingerprint_miners": True,
    "mining_pool_address": "bc1qexample0000000000000000000000000000000", "mining_coinbase_tag_primary": "DATUM Gateway",
    "mining_coinbase_tag_secondary": "DATUM User", "mining_coinbase_unique_id": 4242, "mining_allow_hasher_time_rolling": False,
    "api_listen_port": 7152, "logger_log_level_console": 2, "datum_pool_port": 28915,
    "datum_pool_pubkey": "dbb11fa0c2b5403e4f798fa6071bb97e6079d219598366032fdf2ae01962b13c5e66e2be7d6b008f0b2603f3e6f6fc64768fa786c8129c46d3e30a58677341e1c",
    "datum_migration_max_seconds": 86400, "datum_protocol_global_timeout": 60,
}


def cfg_fill(token):
    mod, name = (token.split(":", 1) if ":" in token else ("", token))
    ro = ARGS.readonly
    flags = {
        "*ro": ro, "*restart_ro": ro,
        "*datum_pool_pass_workers": False, "*username_behaviour_private": False,
        "*reward_sharing_prefer": ARGS.mode == "prefer", "*reward_sharing_never": ARGS.mode == "solo",
        "datum_pool_pass_full_users": True, "datum_pooled_mining_only": ARGS.mode == "pooled",
        "stratum_fingerprint_miners": CFG["stratum_fingerprint_miners"],
        "mining_allow_hasher_time_rolling": CFG["mining_allow_hasher_time_rolling"],
    }
    if name == "*CSRF_TOKEN":
        return "preview-csrf-token"
    if name in ("*restart_message", "*restart_warning_aria_id"):
        return ""
    if name == "*mining_coinbase_tag_secondary_max":
        return "60"
    if name == "*datum_pool_host":
        return "" if ARGS.mode == "solo" else "datum-beta1.mine.convoy.xyz"
    val = flags.get(name, CFG.get(name))
    if mod in ("readonly", "selected", "checked", "disabled"):
        return (" " + mod) if val else ""
    if mod == "msg":
        return ("<br /><em>Config file disallows editing (set \"admin_password\" and \"modify_conf\" in \"api\" section of config file)</em>") if val else ""
    if name == "*ro":
        return " readonly" if ro else ""
    if name == "*restart_ro":
        return " readonly" if ro else ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if val is None:
        raise KeyError("preview has no sample value for ${%s}" % token)
    return str(val)


def fill(template, fn):
    return re.sub(rb"\$\{([^}]*)\}", lambda m: fn(m.group(1).decode()).encode(), template)


POSTJS = None


def post_js():
    return rd("assets/post.js").decode().replace("%s", "preview-csrf-token")


def clients_page(s):
    out = rd("clients_top.html").decode()
    out += "<form action='/cmd' method='post'><input type='hidden' name='csrf' value='preview-csrf-token' /><TABLE><TR><TD><U>TID/CID</U></TD>  <TD><U>RemHost</U></TD>  <TD><U>Auth Username</U></TD> <TD><U>Subbed</U></TD> <TD><U>Last Accepted</U></TD> <TD><U>VDiff</U></TD> <TD><U>DiffA (A)</U></TD> <TD><U>DiffR (R)</U></TD> <TD><U>Best Share</U></TD> <TD><U>Hashrate (age)</U></TD> <TD><U>Coinbase</U></TD> <TD><U>UserAgent</U> </TD><TD><U>Command</U></TD></TR>"
    total = 0.0
    for i, m in enumerate(s["miners"]):
        tid, cid, host, user, sub, ths, vd, accn, rejn, ua, cb = m
        row = "<TR><TD>%d/%d</TD><TD>%s</TD><TD>%s</TD>" % (tid, cid, host, user)
        if sub:
            accn = int(accn + s["t"] * 0.4)
            hr = ths * (1 + 0.02 * math.sin(s["t"] / (11 + i)))
            total += hr
            pct = rejn / float(accn + rejn) * 100
            row += '<TD> <span style="font-family: monospace;">%4.4x</span> %.1fs</TD>' % (0xa100 + i, 3600 + s["t"])
            row += "<TD>%.1fs</TD><TD>%s</TD><TD>%s (%d)</TD><TD>%s (%d) %.2f%%</TD><TD>%s</TD>" % (1.5 + i * 2.3, fmt_diff(vd), fmt_diff(vd * accn), accn, fmt_diff(vd * rejn), rejn, pct, fmt_diff(vd * (900 + 3100 * ((i * 7) % 5))))
            row += "<TD>%.2f Th/s (%.1fs)</TD><TD>%s</TD><TD>%s</TD>" % (hr, 20 + i * 7, cb, ua)
        else:
            row += '<TD COLSPAN="9">Not Subscribed</TD>'
        row += "<TD><button name='kill_client' value='%d_%d_1_%d' onclick=\"sendPostRequest('/cmd', {cmd:'kill_client',tid:%d,cid:%d,t:1,id:%d}); return false;\">Kick</button></TD></TR>" % (tid, cid, i, tid, cid, i)
        out += row
    out += '</TABLE></form><p class="table-footer">Total active hashrate estimate: %.2f Th/s</p><script>' % total + post_js() + "</script>"
    out += rd("foot.html").decode()
    return out.encode()


def threads_page(s):
    out = rd("threads_top.html").decode()
    out += "<form action='/cmd' method='post'><input type='hidden' name='csrf' value='preview-csrf-token' />"
    out += "<TABLE><TR><TD><U>TID</U></TD>  <TD><U>Connection Count</U></TD>  <TD><U>Sub Count</U></TD> <TD><U>Approx. Hashrate</U></TD> <TD><U>Command</U></TD></TR>"
    byt = {}
    for m in s["miners"]:
        d = byt.setdefault(m[0], [0, 0, 0.0])
        d[0] += 1
        d[1] += 1 if m[4] else 0
        d[2] += m[5] if m[4] else 0
    for tid, (c, sb, th) in sorted(byt.items()):
        out += "<TR><TD>%d</TD>  <TD>%d</TD>  <TD>%d</TD> <TD>%.2f Th/s</TD><TD><button name='empty_thread' value='%d' onclick=\"sendPostRequest('/cmd', {cmd:'empty_thread',tid:%d}); return false;\">Disconnect All</button></TD></TR>" % (tid, c, sb, th, tid, tid)
    out += "</TABLE></form><script>" + post_js() + "</script>"
    out += rd("foot.html").decode()
    return out.encode()


def coinbaser_page(s):
    out = rd("coinbaser_top.html").decode()
    out += "<TABLE><TR><TD><U>Value</U></TD>  <TD><U>Address</U></TD></TR>"
    if not s["empty"] or True:
        out += "<TR><TD>2.05227628 BTC</TD><TD>bc1qpoolpayout0000000000000000000000000000x</TD></TR>"
        out += "<TR><TD>0.78933453 BTC</TD><TD>bc1qminerpayout000000000000000000000000000y</TD></TR>"
        out += "<TR><TD>0.31573731 BTC</TD><TD>bc1qexample0000000000000000000000000000000</TD></TR>"
    out += "</TABLE>"
    out += rd("foot.html").decode()
    return out.encode()


def authfail(top):
    return (rd(top).decode() + rd("auth_failed.html").decode() + rd("foot.html").decode()).encode()


class H(BaseHTTPRequestHandler):
    server_version = "preview"

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="text/html", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        if self.path == "/config":
            self.send(200, rd("config_restart.html") if "restart" in ARGS.post else b"", extra={})
        else:
            self.send(200, b"{}", "application/json")

    def do_GET(self):
        p = self.path.split("?")[0]
        s = state()
        try:
            if p == "/":
                v = home_vars(s)
                body = fill(rd("home.html"), lambda t: v[t])
                return self.send(200, body)
            if p in ("/clients", "/threads", "/config") and ARGS.noauth:
                top = {"/clients": "clients_top.html", "/threads": "threads_top.html", "/config": "config_noauth_top.html"}[p]
                return self.send(401, authfail(top), extra={"WWW-Authenticate": 'Digest realm="DATUM Gateway"'})
            if p == "/clients":
                return self.send(200, clients_page(s))
            if p == "/threads":
                return self.send(200, threads_page(s))
            if p == "/coinbaser":
                return self.send(200, coinbaser_page(s))
            if p == "/config":
                return self.send(200, fill(rd("config.html"), cfg_fill))
            if p == "/config-errors":
                return self.send(200, fill(rd("config_errors.html"), lambda t: "<div class='err'>Invalid Bitcoin Address</div><div class='err'>Coinbase Tag is too long</div>"))
            if p == "/config-restart":
                return self.send(200, rd("config_restart.html"))
            if p == "/history.json":
                # what the app's own recorder would hold: 24 h, one sample every 30 s here, with a restart gap
                now, rows = int(time.time() * 1000), []
                for i in range(24 * 3600, -1, -30):
                    if 5 * 3600 < i < 5 * 3600 + 900:
                        continue  # the app was restarting: no samples
                    th = 11.3 + 0.35 * math.sin(i / 1700.0) + 0.18 * math.sin(i / 230.0)
                    if 15 * 3600 < i < 15 * 3600 + 1500:
                        th *= 0.55
                    rows.append([now - i * 1000, round(th, 3), 4, 9000 + int((24 * 3600 - i) * 0.12), 21, 912300 + int((24 * 3600 - i) / 600)])
                return self.send(200, json.dumps({"v": 1, "now": now, "s": rows}, separators=(",", ":")).encode(), "application/json")
            if p == "/umbrel-api":
                return self.send(200, json.dumps({"type": "three-stats", "refresh": "30s", "link": "", "items": [{"title": "Connections", "text": str(len(s["miners"])), "subtext": "Worker"}, {"title": "Hashrate", "text": "%.2f" % s["th"], "subtext": "TH/s"}]}).encode(), "application/json")
            if p == "/assets/style.css":
                return self.send(200, rd("assets/style.css"), "text/css")
            if p == "/assets/icons/datum_logo.svg":
                return self.send(200, rd("assets/icons/datum_logo.svg"), "image/svg+xml")
            if p in ("/assets/icons/favicon.ico", "/favicon.ico"):
                return self.send(200, rd("assets/icons/favicon.ico"), "image/x-icon")
        except KeyError as e:
            return self.send(500, ("preview: %s" % e).encode())
        self.send(404, b"<H1>Not found</H1>")


def main():
    global ARGS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=7152)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--empty", action="store_true", help="no miners connected")
    ap.add_argument("--readonly", action="store_true", help="config editing disabled")
    ap.add_argument("--noauth", action="store_true", help="Clients / Threads / Config demand the admin password")
    ap.add_argument("--status", choices=["ok", "error", "init"], default="ok")
    ap.add_argument("--mode", choices=["pooled", "prefer", "solo"], default="pooled")
    ap.add_argument("--post", default="restart", help=argparse.SUPPRESS)
    ARGS = ap.parse_args()
    srv = ThreadingHTTPServer((ARGS.host, ARGS.port), H)
    print("Previewing %s at http://%s:%d/  (Ctrl+C to stop)" % (os.path.normpath(WWW), ARGS.host, ARGS.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
