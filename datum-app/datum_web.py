#!/usr/bin/env python3
"""Sign-in page and proxy in front of the DATUM Gateway's dashboard (stdlib only).

Public port 7152 (what Umbrel's app_proxy points at). Behind it the Gateway runs on 127.0.0.1:7153.
* One sign-in (same model as Blake2b ASIC Control: first login = the username and password Umbrel shows
  for the app, changeable under Account; 30-day sessions; back-off after bad attempts).
* After signing in nothing else is asked: the proxy answers the Gateway's own admin digest login with an
  internal password nobody sees, so Config, Kick and the rest just work.
* Also hosts the first-run setup (reward address) and the "waiting for your node" page.
* /umbrel-api (the home-screen widget's numbers) stays reachable without signing in.
"""
import hashlib, hmac, html, http.client, json, os, re, secrets, signal, subprocess, sys, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import datum_setup as S

DATA_DIR = os.environ.get("DATUM_DATA_DIR", "/data")
UI_DIR = os.environ.get("DATUM_UI_DIR", "/app/ui")
PUBLIC_PORT = int(os.environ.get("DATUM_PUBLIC_PORT", "7152"))
GATEWAY = os.environ.get("DATUM_GATEWAY_BIN", "/app/datum_gateway")
COOKIE = "datum_session"
SESSION_DAYS = 30
ITER = 200000
BEHIND_PROXY = os.environ.get("DATUM_BEHIND_PROXY") == "1"
MAX_BODY = 1 << 20

STATE = {"mode": "setup", "msg": ""}          # setup | wait | running
CONF_PATH = [""]
SETUP_DONE = threading.Event()
RESTART = threading.Event()
CHILD = {"p": None}
LOCK = threading.Lock()


# ------------------------------------------------------------------ accounts and sessions
class Auth:
    def __init__(self, directory):
        self.dir = directory
        self.fp, self.sp = os.path.join(directory, "auth.json"), os.path.join(directory, "sessions.json")
        self.sessions, self.fails = {}, {}
        self._load_sessions()

    def _read(self, p):
        try:
            with open(p) as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def has_account(self):
        d = self._read(self.fp)
        return bool(d.get("username") and d.get("hash"))

    @staticmethod
    def _hash(password, salt, iters=ITER):
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iters).hex()

    def set_account(self, username, password, temp=False):
        # temp = the login Umbrel shows / a random first one: the owner must replace it before using the app
        salt = secrets.token_bytes(16)
        S.write_private(self.fp, json.dumps({"username": username, "salt": salt.hex(), "iter": ITER, "hash": self._hash(password, salt), "temp": bool(temp)}))

    def must_change(self):
        return bool(self._read(self.fp).get("temp"))

    def migrate(self):
        """Accounts made before this flag existed: still on the login Umbrel shows? Then it must be changed too."""
        d = self._read(self.fp)
        if d.get("hash") and "temp" not in d:
            pw = os.environ.get("APP_PASSWORD", "")
            d["temp"] = bool(pw and self.check(str(d.get("username", "")), pw))
            S.write_private(self.fp, json.dumps(d))

    def check(self, username, password):
        d = self._read(self.fp)
        if not d.get("hash"):
            return False
        h = self._hash(password, bytes.fromhex(d["salt"]), int(d.get("iter", ITER)))
        return hmac.compare_digest(h, d["hash"]) & hmac.compare_digest(username.encode(), str(d.get("username", "")).encode())

    def username(self):
        return str(self._read(self.fp).get("username", ""))

    def bootstrap(self):
        """First start: the login Umbrel shows for the app (APP_PASSWORD), or a random one printed once."""
        if self.has_account():
            return
        user = os.environ.get("DATUM_DEFAULT_USER", "umbrel").strip() or "umbrel"
        pw = os.environ.get("APP_PASSWORD", "")
        if not pw:
            pw = secrets.token_urlsafe(12)
            print("No APP_PASSWORD given. First login: user %s, password %s" % (user, pw), flush=True)
        self.set_account(user, pw, temp=True)

    # sessions are stored hashed, so a copy of sessions.json is no use to anyone
    @staticmethod
    def _key(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def _load_sessions(self):
        now = time.time()
        self.sessions = {k: v for k, v in self._read(self.sp).items() if isinstance(v, dict) and v.get("exp", 0) > now}

    def _persist(self):
        try:
            S.write_private(self.sp, json.dumps(self.sessions))
        except OSError:
            pass

    def new_session(self, username):
        token = secrets.token_urlsafe(32)
        with LOCK:
            self.sessions[self._key(token)] = {"u": username, "exp": time.time() + SESSION_DAYS * 86400}
            self._persist()
        return token

    def user_for(self, token):
        if not token:
            return None
        with LOCK:
            s = self.sessions.get(self._key(token))
            if s and s["exp"] > time.time():
                return s["u"]
        return None

    def drop(self, token):
        with LOCK:
            self.sessions.pop(self._key(token), None)
            self._persist()

    def drop_all(self):
        with LOCK:
            self.sessions = {}
            self._persist()

    # back-off after bad logins, per client
    def blocked_for(self, client):
        n, until = self.fails.get(client, (0, 0.0))
        return max(0, int(until - time.time()) + 1) if until > time.time() else 0

    def failed(self, client):
        n, _ = self.fails.get(client, (0, 0.0))
        n += 1
        self.fails[client] = (n, time.time() + (min(2 ** (n - 3) * 2, 300) if n >= 3 else 0))
        if len(self.fails) > 500:
            self.fails.clear()

    def ok(self, client):
        self.fails.pop(client, None)


AUTH = None


# ------------------------------------------------------------------ hashrate history, recorded here (not in the browser)
class History:
    """One sample every 15 s while the Gateway runs, kept for 24 h in /data/history.json, so the graph has its
    memory whether or not a dashboard tab is open. Row: [ms, TH/s, connections, accepted, rejected, block height]."""
    KEEP_MS, EVERY = 86400000, int(os.environ.get("DATUM_HISTORY_EVERY", "15"))

    def __init__(self, path):
        self.path, self.lock, self.s = path, threading.Lock(), []
        try:
            with open(path) as f:
                o = json.load(f)
            cut = int(time.time() * 1000) - self.KEEP_MS
            if isinstance(o, dict) and o.get("v") == 1 and isinstance(o.get("s"), list):
                self.s = [r for r in o["s"] if isinstance(r, list) and len(r) == 6 and all(isinstance(x, (int, float)) for x in r) and r[0] >= cut]
        except Exception:
            self.s = []

    def add(self, row):
        with self.lock:
            if self.s and row[0] - self.s[-1][0] < 5000:
                return
            self.s.append(row)
            cut = row[0] - self.KEEP_MS
            while self.s and self.s[0][0] < cut:
                self.s.pop(0)

    def save(self):
        with self.lock:
            data = json.dumps({"v": 1, "s": self.s}, separators=(",", ":"))
        try:
            S.write_private(self.path, data)
        except OSError:
            pass

    def dump(self):
        with self.lock:
            return json.dumps({"v": 1, "now": int(time.time() * 1000), "s": self.s}, separators=(",", ":"))


HISTORY = None


def _val(page, key):
    m = re.search(r'data-k="%s"[^>]*>([^<]*)<' % key, page)
    return m.group(1) if m else ""


def _num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
    return float(m.group()) if m else None


def take_sample():
    status, _, data = gateway_request("GET", "/", None, None)
    if status != 200:
        return None
    page = data.decode("utf-8", "replace")
    th, conn = _num(_val(page, "STRATUM_HASHRATE_ESTIMATE")), _num(_val(page, "STRATUM_TOTAL_CONNECTIONS"))
    if th is None and conn is None:
        return None
    n = lambda v: int(v) if v is not None else 0
    return [int(time.time() * 1000), round(th, 4) if th is not None else 0, n(conn),
            n(_num(_val(page, "STRATUM_SHARES_ACCEPTED"))), n(_num(_val(page, "STRATUM_SHARES_REJECTED"))),
            n(_num(_val(page, "STRATUM_JOB_BLOCK_HEIGHT")))]


def sampler():
    saved = 0.0
    while True:
        time.sleep(History.EVERY)
        if STATE["mode"] != "running":
            continue
        try:
            row = take_sample()
        except Exception:
            row = None
        if row:
            HISTORY.add(row)
        if time.time() - saved > 60:
            HISTORY.save()
            saved = time.time()


# ------------------------------------------------------------------ pages
THEME_JS = """(function(){var K="gc-theme",t="dark";try{if(localStorage.getItem(K)==="light")t="light"}catch(e){}
function a(){document.documentElement.setAttribute("data-theme",t);var b=document.querySelectorAll("[data-theme-toggle]");for(var i=0;i<b.length;i++){b[i].innerHTML=t==="light"?'\\u263e<span class="tl"> Dark</span>':'\\u2600<span class="tl"> Light</span>'}}
a();document.addEventListener("DOMContentLoaded",a);
document.addEventListener("click",function(e){var b=e.target&&e.target.closest?e.target.closest("[data-theme-toggle]"):null;if(!b)return;t=t==="light"?"dark":"light";try{localStorage.setItem(K,t)}catch(x){}a()})})();"""

EXTRA_CSS = """main.narrow{max-width:30rem}.stack{display:flex;flex-direction:column;gap:.8rem}
.stack label{display:flex;flex-direction:column;gap:.3rem;font-size:.85rem;color:var(--muted)}
.stack input,.stack select{width:100%;box-sizing:border-box}.stack .err{color:var(--bad);font-size:.85rem;margin:0}
.stack .okmsg{color:var(--ok);font-size:.85rem;margin:0}.stack button.primary{background:var(--text);color:var(--bg);border-color:var(--text);font-weight:600;margin-top:.3rem}
.big{text-align:center;margin:0 0 1.2rem;font-size:1.4rem;color:var(--muted)}.big b{color:var(--text)}"""


def e(s):
    return html.escape(str(s), True)


def eline(text, good=False):
    return '<p class="eline%s">%s</p>' % (" good" if good else "", e(text)) if text else ""


def shell(title, body, nav=True, user=None, active="", head=""):
    tabs = ""
    right = '<button type="button" class="theme-btn" data-theme-toggle>&#9728;<span class="tl"> Light</span></button>'
    if nav:
        tabs = '<nav class="tabs">' + "".join('<a href="%s">%s</a>' % (h, t) for h, t in
                                               (("/", "Status"), ("/clients", "Clients"), ("/threads", "Threads"), ("/coinbaser", "Coinbaser"), ("/config", "Config"))) + "</nav>"
        right = '<a class="btn%s" href="/account">Account</a>' % (" active" if active == "account" else "") + right
    return """<!DOCTYPE html><html lang="en" data-theme="dark"><head><meta charset="UTF-8"><title>%s</title>
<link rel="icon" type="image/x-icon" href="/assets/icons/favicon.ico"><link rel="stylesheet" href="/assets/style.css">
<meta name="viewport" content="width=device-width, initial-scale=1">%s<style>%s</style><script>%s</script></head><body>
<header class="app"><h1><img src="/assets/icons/datum_logo.svg" alt="" width="30" height="30"><span><span class="brand">DATUM</span> Gateway</span></h1>%s
<div class="spacer"></div><div class="hdr-right">%s</div></header><main class="narrow">%s</main></body></html>""" % (e(title), head, EXTRA_CSS, THEME_JS, tabs, right, body)


def page_login(error="", next_url="/", first=False):
    hint = ('<p class="tip" style="color:var(--muted);font-size:.85rem;margin-top:0">First time? Use the username and password '
            'Umbrel shows for this app. Right after signing in you will be asked to choose your own.</p>') if first else ""
    return shell("Sign in · DATUM Gateway", """<h1 class="big"><b>DATUM</b> Gateway</h1><section class="panel"><div class="panel-h"><h2>Sign in</h2></div>%s
<form method="post" action="/login" class="stack" autocomplete="on"><input type="hidden" name="next" value="%s">
<label>Username<input name="username" autocomplete="username" required autofocus></label>
<label>Password<input name="password" type="password" autocomplete="current-password" required></label>
%s<button type="submit" class="primary">Sign in</button></form></section>
<p class="footer-note">One sign-in covers every page and stays for %d days. Forgot it? Delete auth.json in the app's data folder and restart the app: it goes back to the login Umbrel shows.</p>"""
                 % (hint, e(next_url), eline(error), SESSION_DAYS), nav=False)


def page_account(user, msg="", err="", force=False):
    intro = ('<p style="margin:0 0 .9rem">You are still using the login Umbrel shows for this app. Choose your own username and password '
             'before you continue: anyone who can open the app page could otherwise sign in with it.</p>') if force else ""
    return shell("Account · DATUM Gateway", """<section class="panel"><div class="panel-h"><h2>%s</h2><span class="sub">signed in as %s</span></div>%s
<form method="post" action="/account" class="stack" autocomplete="on">
<label>Current password<input name="current" type="password" autocomplete="current-password" required></label>
<label>New username (leave empty to keep it)<input name="username" autocomplete="username"></label>
<label>New password (at least 8 characters)<input name="password" type="password" autocomplete="new-password" required minlength="8"></label>
<label>New password again<input name="password2" type="password" autocomplete="new-password" required minlength="8"></label>
%s%s<button type="submit" class="primary">Change login</button></form>
<form method="post" action="/logout" style="margin-top:1rem;display:flex;justify-content:space-between;align-items:center;gap:1rem">
<span style="color:var(--muted);font-size:.8rem">Changing it signs out every other device.</span><button type="submit">Log out</button></form></section>"""
                 % ("Choose your own login" if force else "Account", e(user), intro, eline(err), eline(msg, True)), user=user, active="account", nav=not force)


def page_setup(err="", addr="", tag="DATUM Gateway", mode="prefer"):
    sel = lambda m: "selected" if mode == m else ""
    return shell("Setup · DATUM Gateway", """<section class="panel"><div class="panel-h"><h2>Setup</h2><span class="sub">one time; all of this can be changed later on Config</span></div>
<form method="post" action="/setup" class="stack"><label>Bitcoin address for mining rewards
<input name="addr" value="%s" required autocomplete="off" spellcheck="false" placeholder="bc1q..."></label>
<p class="tip" style="margin:0;color:var(--muted);font-size:.78rem">Block rewards you find yourself are paid here. Use an address you control.</p>
<label>Coinbase tag<input name="tag" value="%s" maxlength="30"></label>
<label>Reward sharing<select name="mode"><option value="prefer" %s>Prefer pooled mining, fall back to solo</option>
<option value="require" %s>Pooled mining only</option><option value="never" %s>Solo only (no pool)</option></select></label>
%s<button type="submit" class="primary">Save and start</button></form></section>"""
                 % (e(addr), e(tag), sel("prefer"), sel("require"), sel("never"), eline(err)))


def page_state(title, msg, refresh=5):
    # always reload "/" (never the page we are on: /setup, /restart ... do not exist once the Gateway runs)
    return shell(title, '<section class="panel"><div class="panel-h"><h2>%s</h2></div><p>%s</p>'
                        '<p style="color:var(--muted)">This page refreshes by itself. <a href="/">Continue now</a></p></section>' % (e(title), e(msg)),
                 head='<meta http-equiv="refresh" content="%d;url=/">' % refresh)


# ------------------------------------------------------------------ talking to the Gateway
def _digest_header(challenge, method, uri, user, password):
    p = {m[0].lower(): (m[1] or m[2]) for m in re.findall(r'(\w+)\s*=\s*(?:"([^"]*)"|([^,\s]*))', challenge)}
    algo = p.get("algorithm", "MD5")
    h = (lambda s: hashlib.sha256(s.encode()).hexdigest()) if "256" in algo else (lambda s: hashlib.md5(s.encode(), usedforsecurity=False).hexdigest())
    realm, nonce, nc, cnonce = p.get("realm", ""), p.get("nonce", ""), "00000001", secrets.token_hex(8)
    resp = h("%s:%s:%s:%s:auth:%s" % (h("%s:%s:%s" % (user, realm, password)), nonce, nc, cnonce, h("%s:%s" % (method, uri))))
    out = 'Digest username="%s", realm="%s", nonce="%s", uri="%s", algorithm=%s, response="%s", qop=auth, nc=%s, cnonce="%s"' % (
        user, realm, nonce, uri, algo, resp, nc, cnonce)
    if p.get("opaque"):
        out += ', opaque="%s"' % p["opaque"]
    return out


def gateway_request(method, target, body, ctype):
    """(status, headers, body) from the Gateway, answering its digest challenge when it sends one."""
    pw = S.load(CONF_PATH[0]).get("api", {}).get("admin_password", "")
    hdrs = {"User-Agent": "datum-umbrel-proxy", "Connection": "close"}
    if ctype:
        hdrs["Content-Type"] = ctype
    for attempt in (0, 1):
        c = http.client.HTTPConnection("127.0.0.1", S.INTERNAL_PORT, timeout=30)
        try:
            c.request(method, target, body=body, headers=hdrs)
            r = c.getresponse()
            data = r.read()
            chal = r.getheader("WWW-Authenticate") or ""
            if r.status == 401 and attempt == 0 and chal.lower().startswith("digest") and pw:
                hdrs["Authorization"] = _digest_header(chal, method, target, "admin", pw)
                continue
            return r.status, r.getheaders(), data
        finally:
            c.close()
    return 502, [], b""


PASS_HEADERS = ("content-type", "cache-control", "content-disposition", "location", "refresh")


# ------------------------------------------------------------------ the web server
# Settings the Gateway's own Config page cannot edit; the Config page's "Identity and advanced" panel does,
# through /identity (written to config.json, then the Gateway restarts so the change is certain to apply).
IDENT = [  # (section, key, kind, default, low, high)
    ("mining", "coinbase_tag_primary", "tag", "DATUM Gateway", 0, 30),
    ("stratum", "share_stale_seconds", "int", 120, 60, 150),
    ("stratum", "idle_timeout_no_subscribe", "int", 15, 0, 86400),
    ("stratum", "idle_timeout_no_shares", "int", 7200, 0, 604800),
    ("stratum", "vardiff_min", "int", 1024, 1, 1 << 40),
    ("stratum", "vardiff_target_shares_min", "int", 8, 1, 60),
    ("stratum", "max_clients", "int", 1024, 1, 1024),
    ("bitcoind", "notify_fallback", "bool", True, 0, 1),
    ("datum", "migration_max_seconds", "int", 86400, 0, 31536000),
    ("datum", "protocol_global_timeout", "int", 60, 10, 3600),
    ("logger", "log_level_console", "int", 2, 0, 5),
]


def identity_values(conf):
    out = {}
    for sec, key, kind, dflt, lo, hi in IDENT:
        v = conf.get(sec, {}).get(key, dflt)
        out[sec + "_" + key] = bool(v) if kind == "bool" else v
    return out


def identity_apply(conf, data):
    """validate `data` (name -> value); returns (error, changed). Mutates conf only when everything is valid."""
    new, changed = {}, False
    for sec, key, kind, dflt, lo, hi in IDENT:
        name = sec + "_" + key
        if name not in data:
            continue
        raw = data[name]
        if kind == "bool":
            val = raw in (True, 1, "1", "true", "on", "yes")
        elif kind == "tag":
            val = str(raw).strip()
            if not S.valid_tag(val) or len(val) > hi:
                return "The tag can be up to %d plain characters: letters, digits, spaces, basic punctuation, no < > & quotes or backslash." % hi, False
        else:
            try:
                val = int(str(raw).strip())
            except ValueError:
                return "%s must be a whole number." % key.replace("_", " "), False
            if val < lo or val > hi:
                return "%s must be between %d and %d." % (key.replace("_", " "), lo, hi), False
        new[(sec, key)] = val
    if ("stratum", "max_clients") in new:   # the Gateway refuses to start when this is above threads x clients per thread
        st = conf.get("stratum", {})
        room = int(st.get("max_clients_per_thread", 128)) * int(st.get("max_threads", 8))
        if new[("stratum", "max_clients")] > room:
            return "max clients cannot be above %d with the current thread settings." % room, False
    for (sec, key), val in new.items():
        sect = conf.setdefault(sec, {})
        if sect.get(key) != val:
            sect[key] = val
            changed = True
    return "", changed


def safe_next(n):
    if not n or not n.startswith("/") or n.startswith("//") or re.search(r"[\\\s\x00-\x1f]", n) or n.startswith("/login"):
        return "/"
    return n


class H(BaseHTTPRequestHandler):
    timeout = 20
    server_version = "datum-umbrel"
    sys_version = ""

    def log_message(self, *a):
        pass

    # --- helpers
    def client(self):
        if BEHIND_PROXY:
            xf = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            if xf:
                return xf
        return self.client_address[0]

    def token(self):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return ""

    def send_page(self, body, code=200, cookie=None, location=None, extra=()):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        if location:
            self.send_header("Location", location)
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b)

    def redirect(self, where, cookie=None):
        self.send_page("", 303, cookie=cookie, location=where)

    @staticmethod
    def cookie(token, max_age):
        return "%s=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Strict" % (COOKIE, token, max_age)

    def form(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > 65536:
            return None
        return {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True).items()}

    def origin_ok(self):
        o = self.headers.get("Origin")
        if o is None:
            return True   # browsers always send Origin on cross-site posts; its absence means not a browser form from another site
        return urllib.parse.urlsplit(o).netloc == (self.headers.get("Host") or "")

    def asset(self, path):
        """our own copy of the stylesheet and icons, so the sign-in page looks right before the Gateway is up"""
        rel = path[len("/assets/"):]
        if ".." in rel or rel.startswith("/") or not rel:
            return False
        fp = os.path.join(UI_DIR, rel)
        if not os.path.isfile(fp):
            return False
        ct = {"css": "text/css", "svg": "image/svg+xml", "ico": "image/x-icon", "js": "text/javascript"}.get(rel.rsplit(".", 1)[-1], "application/octet-stream")
        with open(fp, "rb") as f:
            b = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b)
        return True

    # --- routing
    def do_HEAD(self):
        self.route()

    def do_GET(self):
        self.route()

    def do_POST(self):
        self.route()

    def route(self):
        try:
            self._route()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as ex:
            print("proxy error: %r" % (ex,), flush=True)
            try:
                self.send_page(page_state("Something went wrong", "The dashboard could not answer this request. Try again in a moment."), 500)
            except Exception:
                pass

    def _route(self):
        split = urllib.parse.urlsplit(self.path)
        path, post = split.path, self.command == "POST"
        if post and not self.origin_ok():
            return self.send_page(page_state("Blocked", "This request came from another site."), 403)

        if path == "/login":
            return self.login(split)
        if path.startswith("/assets/") and self.command in ("GET", "HEAD") and self.asset(path):
            return
        if path == "/umbrel-api" and self.command == "GET" and STATE["mode"] == "running":
            return self.forward()  # the widget's numbers, as the Gateway itself serves them

        user = AUTH.user_for(self.token())
        if not user:
            if self.command in ("GET", "HEAD") and "json" not in (self.headers.get("Accept") or ""):
                return self.redirect("/login?next=" + urllib.parse.quote(self.path, safe="/?=&"))
            return self.send_page(json.dumps({"error": "sign in required"}), 401, extra=(("Content-Type", "application/json"),))

        # still on the login Umbrel shows: nothing but the Account page (and signing out) until it is replaced
        if AUTH.must_change() and path not in ("/account", "/logout"):
            if self.command in ("GET", "HEAD") and "json" not in (self.headers.get("Accept") or ""):
                return self.redirect("/account")
            return self.send_page(json.dumps({"error": "choose your own login first"}), 403, extra=(("Content-Type", "application/json"),))

        if path == "/history.json" and self.command == "GET":
            return self.send_page(HISTORY.dump(), extra=(("Content-Type", "application/json"), ("Cache-Control", "no-store")))
        if path == "/identity.json" and self.command == "GET":
            return self.send_page(json.dumps(identity_values(S.load(CONF_PATH[0]))), extra=(("Content-Type", "application/json"), ("Cache-Control", "no-store")))
        if path == "/identity" and post:
            return self.identity()
        if path == "/logout" and post:
            AUTH.drop(self.token())
            return self.redirect("/login", cookie=self.cookie("", 0))
        if path == "/restart" and post:
            if STATE["mode"] != "running":
                return self.send_page(json.dumps({"ok": False, "error": "not running"}), 409, extra=(("Content-Type", "application/json"),))
            RESTART.set()
            p = CHILD["p"]
            if p and p.poll() is None:
                p.terminate()
            return self.send_page(json.dumps({"ok": True}), extra=(("Content-Type", "application/json"),))
        if path == "/account":
            return self.account(user)
        if path == "/setup":
            if post and STATE["mode"] == "setup":
                return self.do_setup()
            return self.redirect("/")
        if STATE["mode"] == "setup":
            return self.send_page(page_setup(), extra=())
        if STATE["mode"] == "wait":
            return self.send_page(page_state("Waiting for your Bitcoin node", STATE["msg"]), 503)
        return self.forward()

    # --- sign in / account / setup
    def login(self, split):
        first = False
        if self.command in ("GET", "HEAD"):
            if AUTH.user_for(self.token()):
                return self.redirect(safe_next(urllib.parse.parse_qs(split.query).get("next", ["/"])[0]))
            nxt = safe_next(urllib.parse.parse_qs(split.query).get("next", ["/"])[0])
            return self.send_page(page_login(next_url=nxt, first=bool(os.environ.get("APP_PASSWORD"))))
        f = self.form()
        if f is None:
            return self.send_page(page_login("Bad request."), 400)
        c = self.client()
        wait = AUTH.blocked_for(c)
        nxt = safe_next(f.get("next", "/"))
        if wait:
            return self.send_page(page_login("Too many attempts. Try again in %d s." % wait, nxt), 429)
        u, p = f.get("username", "").strip(), f.get("password", "")
        if AUTH.check(u, p):
            AUTH.ok(c)
            return self.redirect(nxt, cookie=self.cookie(AUTH.new_session(AUTH.username()), SESSION_DAYS * 86400))
        AUTH.failed(c)
        time.sleep(0.4)
        return self.send_page(page_login("Wrong username or password.", nxt), 401)

    def account(self, user):
        force = AUTH.must_change()
        if self.command != "POST":
            return self.send_page(page_account(user, force=force))
        f = self.form()
        if f is None:
            return self.send_page(page_account(user, err="Bad request.", force=force), 400)
        if AUTH.blocked_for(self.client()):
            return self.send_page(page_account(user, err="Too many attempts. Wait a little.", force=force), 429)
        if not AUTH.check(AUTH.username(), f.get("current", "")):
            AUTH.failed(self.client())
            return self.send_page(page_account(user, err="The current password is wrong.", force=force), 403)
        new_user = f.get("username", "").strip() or AUTH.username()
        pw, pw2 = f.get("password", ""), f.get("password2", "")
        if not re.match(r"^[\w.@+-]{1,64}$", new_user):
            return self.send_page(page_account(user, err="Username: 1-64 letters, digits or . _ @ + -", force=force), 400)
        if len(pw) < 8 or len(pw) > 256:
            return self.send_page(page_account(user, err="The password needs at least 8 characters.", force=force), 400)
        if pw != pw2:
            return self.send_page(page_account(user, err="The two new passwords differ.", force=force), 400)
        if pw == f.get("current", "") or (os.environ.get("APP_PASSWORD") and pw == os.environ["APP_PASSWORD"]):
            return self.send_page(page_account(user, err="Pick a new password, not the one you already use or the one Umbrel shows.", force=force), 400)
        AUTH.set_account(new_user, pw)
        AUTH.drop_all()
        token = AUTH.new_session(new_user)
        cookie = self.cookie(token, SESSION_DAYS * 86400)
        if force:
            return self.redirect("/", cookie=cookie)
        return self.send_page(page_account(new_user, msg="Login changed. Other devices were signed out."), cookie=cookie)

    def identity(self):
        def reply(obj, code=200):
            return self.send_page(json.dumps(obj), code, extra=(("Content-Type", "application/json"),))
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n < 0 or n > 65536:
                raise ValueError
            data = json.loads(self.rfile.read(n).decode("utf-8", "replace") or "{}")
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            return reply({"ok": False, "error": "Bad request."}, 400)
        if STATE["mode"] == "wait":
            return reply({"ok": False, "error": "The Gateway is starting; try again in a moment."}, 409)
        conf = S.defaults(S.load(CONF_PATH[0]))
        err, changed = identity_apply(conf, data)
        if err:
            return reply({"ok": False, "error": err}, 400)
        if not changed:
            return reply({"ok": True, "changed": False})
        S.save(CONF_PATH[0], conf)
        if STATE["mode"] == "running":
            RESTART.set()
            p = CHILD["p"]
            if p and p.poll() is None:
                p.terminate()
        return reply({"ok": True, "changed": True})

    def do_setup(self):
        f = self.form()
        if f is None:
            return self.send_page(page_setup("Bad request."), 400)
        addr, tag, mode = f.get("addr", "").strip(), f.get("tag", "").strip(), f.get("mode", "prefer")
        if mode not in ("prefer", "require", "never"):
            mode = "prefer"
        if not S.valid_address(addr):
            return self.send_page(page_setup("That doesn't look like a valid Bitcoin address (checksum failed).", addr, tag, mode), 400)
        if not S.valid_tag(tag):
            return self.send_page(page_setup("The tag can be up to 30 plain characters: letters, digits, spaces, basic punctuation, no < > & quotes or backslash.", addr, tag, mode), 400)
        conf = S.defaults(S.load(CONF_PATH[0]))
        conf["mining"]["pool_address"] = addr
        if tag:
            conf["mining"]["coinbase_tag_primary"] = tag
        conf["datum"]["pooled_mining_only"] = mode == "require"
        if mode == "never":
            conf["datum"]["pool_host"] = ""
        S.save(CONF_PATH[0], conf)
        SETUP_DONE.set()
        return self.send_page(page_state("Saved", "Starting the Gateway…", 3))

    # --- through to the Gateway
    def forward(self):
        body, ctype = None, self.headers.get("Content-Type")
        if self.command == "POST":
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                return self.send_page(page_state("Too large", "That request is too large."), 413)
            body = self.rfile.read(n)
        try:
            status, headers, data = gateway_request("GET" if self.command == "HEAD" else self.command, self.path, body, ctype)
        except OSError:
            return self.send_page(page_state("The Gateway is starting", "It is starting or restarting. This page refreshes by itself.", 3), 503)
        self.send_response(status)
        for k, v in headers:
            if k.lower() in PASS_HEADERS:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


# ------------------------------------------------------------------ supervisor
def run(conf_path):
    global AUTH
    CONF_PATH[0] = conf_path
    os.makedirs(os.path.dirname(conf_path) or ".", exist_ok=True)
    conf = S.sync(conf_path)
    AUTH = Auth(os.path.dirname(conf_path) or ".")
    AUTH.bootstrap()
    AUTH.migrate()
    global HISTORY
    HISTORY = History(os.path.join(os.path.dirname(conf_path) or ".", "history.json"))
    threading.Thread(target=sampler, daemon=True).start()

    srv = ThreadingHTTPServer(("0.0.0.0", PUBLIC_PORT), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    child = CHILD

    def stop(*_):
        HISTORY.save()
        p = child["p"]
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        os._exit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while not S.valid_address(S.load(conf_path).get("mining", {}).get("pool_address")):
        STATE["mode"] = "setup"
        SETUP_DONE.wait(5)
    conf = S.sync(conf_path)

    while True:
        STATE["mode"] = "wait"
        last = None
        while True:
            ready, msg = S.node_status(conf)
            STATE["msg"] = msg
            if ready:
                break
            if msg != last:
                print("waiting for node: " + msg, flush=True)
                last = msg
            time.sleep(5)
        print("node is ready, starting the Gateway", flush=True)
        child["p"] = subprocess.Popen([GATEWAY, "--config", conf_path])
        STATE["mode"] = "running"
        try:
            code = child["p"].wait()
        except Exception:
            code = 1
        if RESTART.is_set():
            RESTART.clear()
            STATE["mode"], STATE["msg"] = "wait", "Restarting the Gateway…"
            print("restarting the Gateway on request", flush=True)
            conf = S.sync(conf_path)
            time.sleep(1)
            continue
        print("the Gateway exited with code %s" % code, flush=True)
        return code or 0
