# DATUM Gateway for Umbrel (christhealien)

An Umbrel app that runs the [DATUM Gateway](https://github.com/CONVOYMining/datum_gateway) against your own
Bitcoin node (Knots or Core) with a redesigned dashboard. The gateway itself is **built from the newest upstream
release**; this repo only adds the web pages, a sign-in proxy, a first-run setup and two small source patches.

| Folder | What |
|---|---|
| `datum-app/` | Docker image source: `Dockerfile`, `www/` (the 14 web files laid over upstream's), `datum_web.py` (sign-in, setup, node wait, restart, proxy), `datum_setup.py`, `patches/` |
| `blake2b-datum-gateway/` | The Umbrel app folder (manifest, compose, icon, gallery) that goes into the store repo |
| `tools/` | `validate_overlay.py`, `sync_upstream.py`, `publish_to_store.sh`, `gitea_mirror.sh`, `preview.py`, `screenshot.py` |
| `UPSTREAM_TAG` | The upstream release the UI was last checked against |
| `SETUP.md` | Step-by-step: Gitea test, public release, updates |

What differs from stock DATUM Gateway:

* New UI (same look as Blake2b ASIC Control), light/dark, graph, sortable Clients, Config with connect details.
* One sign-in page (no browser pop-up on Config); first login is the one Umbrel shows for the app.
* Clients: **Best Share** per miner (small source patch), share numbers like DATUM / the miner's own / both.
* Restart button, auto-refresh interval, first-run setup, waits for the node to finish syncing.
* New blocks are noticed 4 times a second instead of once (small source patch), because Umbrel's Bitcoin app can't run a `blocknotify` command.

Both patches skip themselves with a notice if upstream changes that code; the build then still works, only without that feature.

Preview the UI without a node: `python3 tools/preview.py` then open http://127.0.0.1:7152 (sample data).

Licence: the upstream gateway is MIT (CONVOYMining / OCEAN). Our additions are MIT as well.
