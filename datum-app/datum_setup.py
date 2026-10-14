#!/usr/bin/env python3
"""Config helpers for the DATUM Gateway on Umbrel (stdlib only), and the command line the entrypoint uses.

  --check FILE   exit 0 if FILE has a valid mining.pool_address
  --sync  FILE   write Umbrel's bitcoind RPC settings into FILE (and make an internal API password)
  --run   FILE   start everything: sign-in page + proxy, first-run setup, node wait, the Gateway (datum_web.py)
"""
import argparse, base64, hashlib, json, os, re, secrets, sys, urllib.error, urllib.request

INTERNAL_PORT = 7153   # the Gateway's own dashboard/API; only the sign-in proxy talks to it
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BECH = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
TAG_OK = re.compile(r"^[\x20-\x7e]{0,30}$")


def _polymod(values):
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (b >> i) & 1 else 0
    return chk


def _b58check(a):
    n = 0
    for c in a:
        if c not in B58:
            return False
        n = n * 58 + B58.index(c)
    pad = len(a) - len(a.lstrip("1"))
    raw = b"\0" * pad + n.to_bytes((n.bit_length() + 7) // 8, "big")
    if len(raw) != 25 or raw[0] not in (0x00, 0x05, 0x6F, 0xC4):
        return False
    return hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] == raw[-4:]


def valid_address(a):
    a = (a or "").strip()
    if not a or len(a) > 100:
        return False
    low = a.lower()
    if low.startswith(("bc1", "tb1", "bcrt1")):
        if a != low and a != a.upper():
            return False
        hrp, _, data = low.rpartition("1")
        if hrp not in ("bc", "tb", "bcrt") or len(data) < 7:
            return False
        try:
            vals = [BECH.index(c) for c in data]
        except ValueError:
            return False
        const = _polymod([ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp] + vals)
        n = len(vals) - 7                        # characters of program data (without version and checksum)
        if vals[0] == 0:
            return const == 1 and n in (32, 52)  # P2WPKH (20 bytes) / P2WSH (32 bytes)
        return const == 0x2BC830A3 and vals[0] == 1 and n == 52  # taproot (32 bytes)
    return _b58check(a)


def valid_tag(tag):
    return bool(TAG_OK.match(tag)) and not any(c in tag for c in "<>&\"'`\\")


def load(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        try:  # unreadable: keep it for inspection instead of silently replacing it
            os.replace(path, path + ".corrupt")
            print("config.json could not be read; moved to config.json.corrupt", flush=True)
        except OSError:
            pass
        return {}


def write_private(path, text):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # holds passwords
    with os.fdopen(fd, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save(path, conf):
    write_private(path, json.dumps(conf, indent=2))


def defaults(conf):
    conf.setdefault("bitcoind", {}).setdefault("notify_fallback", True)
    conf.setdefault("stratum", {}).setdefault("listen_port", 23334)
    conf.setdefault("mining", {})
    api = conf.setdefault("api", {})
    api["listen_port"] = INTERNAL_PORT
    api["modify_conf"] = True
    conf.setdefault("logger", {}).setdefault("log_to_console", True)
    conf.setdefault("datum", {}).setdefault("pool_host", "datum-beta1.mine.convoy.xyz")
    conf["datum"].setdefault("pool_port", 28915)
    return conf


def sync(path):
    conf = defaults(load(path))
    e = os.environ
    host, port = e.get("APP_BITCOIN_NODE_IP"), e.get("APP_BITCOIN_RPC_PORT")
    if host and port:
        conf["bitcoind"]["rpcurl"] = "http://%s:%s" % (host, port)
    if e.get("APP_BITCOIN_RPC_USER"):
        conf["bitcoind"]["rpcuser"] = e["APP_BITCOIN_RPC_USER"]
    if e.get("APP_BITCOIN_RPC_PASS"):
        conf["bitcoind"]["rpcpassword"] = e["APP_BITCOIN_RPC_PASS"]
    # The Gateway's own admin login (digest auth) is never shown to anyone: the sign-in proxy uses it.
    if not conf["api"].get("admin_password") or conf["api"]["admin_password"] == e.get("APP_PASSWORD"):
        conf["api"]["admin_password"] = secrets.token_urlsafe(24)
    save(path, conf)
    return conf


def node_status(conf):
    """(ready, message) from the node's getblockchaininfo"""
    b = conf.get("bitcoind", {})
    url = b.get("rpcurl")
    if not url:
        return True, ""  # nothing to wait for (cookie file or hand-written config)
    req = urllib.request.Request(url, data=json.dumps({"jsonrpc": "1.0", "id": "w", "method": "getblockchaininfo", "params": []}).encode(),
                                 headers={"Content-Type": "application/json"})
    if b.get("rpcuser"):
        req.add_header("Authorization", "Basic " + base64.b64encode(("%s:%s" % (b["rpcuser"], b.get("rpcpassword", ""))).encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            res = json.loads(r.read().decode()).get("result") or {}
    except urllib.error.HTTPError as e:
        try:
            return False, "The node answered: %s" % ((json.loads(e.read().decode()).get("error") or {}).get("message", e.code))
        except Exception:
            return False, "The node refused the login (HTTP %s). Check that the Bitcoin app is running." % e.code
    except Exception as e:
        return False, "Can't reach the node yet (%s)." % (getattr(e, "reason", None) or e)
    if res.get("initialblockdownload"):
        return False, "The node is still syncing: block %s of %s (%.2f%%)." % (res.get("blocks"), res.get("headers"), 100.0 * float(res.get("verificationprogress", 0)))
    return True, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check"), ap.add_argument("--sync"), ap.add_argument("--run")
    a = ap.parse_args()
    if a.check:
        return 0 if valid_address(load(a.check).get("mining", {}).get("pool_address")) else 1
    if a.sync:
        sync(a.sync)
    if a.run:
        import datum_web
        return datum_web.run(a.run)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
